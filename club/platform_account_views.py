import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import PlatformBinding
from .platform_credentials import save_credentials
from .platform_sync import PLATFORMS, validate_account
from .profile_views import eligible, lock_active_member, enqueue, serialize_binding
from .views import api_login_required, api_error, body


def start(binding, full=False):
    prior = binding.sync_state or {}
    resumable = prior.get('phase') == 'records' and binding.status == 'failed' and not full
    binding.sync_state = dict(prior, version=2) if resumable else {
        'version': 2, 'phase': 'profile', 'full': full or not prior.get('complete'),
        'cursor': prior.get('cursor', 0), 'pages': 0, 'count': binding.solved_records.count()}
    binding.sync_token = uuid.uuid4()
    binding.requested_at = timezone.now()
    binding.status = 'pending'
    binding.error = ''
    binding.save()
    transaction.on_commit(lambda: enqueue(binding))


@api_login_required
@require_http_methods(['POST'])
def accounts(request, platform):
    member = eligible(request)
    if not member:
        return api_error('请先加入团队', 403)
    if platform not in PLATFORMS:
        return api_error('不支持的平台', 400)
    data = body(request)
    try:
        account = validate_account(platform, data.get('account'))
        with transaction.atomic():
            if not lock_active_member(request.user.pk,member.pk):
                return api_error('账号或团队身份已失效，不能修改平台绑定',403)
            if platform == 'luogu' and not account.isdigit():
                if any(str((b.snapshot or {}).get('display_name','')).casefold() == account.casefold()
                       for b in PlatformBinding.objects.filter(user=request.user,platform=platform)):
                    return api_error('账号已添加',409)
            binding = PlatformBinding(user=request.user, platform=platform, account=account)
            save_credentials(binding, data)
            binding.save()
            start(binding, True)
    except IntegrityError:
        return api_error('账号已添加', 409)
    except ValueError as exc:
        return api_error(str(exc), 400)
    binding.refresh_from_db()
    return JsonResponse(serialize_binding(binding), status=202)


@api_login_required
@require_http_methods(['PATCH', 'DELETE'])
def account_detail(request, binding_id):
    member = eligible(request)
    if not member:
        return api_error('请先加入团队', 403)
    data = body(request)
    try:
        with transaction.atomic():
            if not lock_active_member(request.user.pk,member.pk):
                return api_error('账号或团队身份已失效，不能修改平台绑定',403)
            binding = PlatformBinding.objects.select_for_update().filter(pk=binding_id, user=request.user).first()
            if not binding:
                return api_error('账号不存在', 404)
            if request.method == 'DELETE':
                binding.delete()
                return JsonResponse({'ok': True})
            account = validate_account(binding.platform, data.get('account', binding.account))
            if binding.account.casefold() != account.casefold():
                binding.solved_records.all().delete()
                from .models import PlatformSolvedBaseline
                PlatformSolvedBaseline.objects.filter(binding=binding).delete()
                binding.snapshot = {}
                binding.synced_at = None
                binding.encrypted_credentials = ''
                binding.sync_state = {}
            binding.account = account
            save_credentials(binding, data)
            start(binding, data.get('full') is True)
    except IntegrityError:
        return api_error('账号已添加', 409)
    except ValueError as exc:
        return api_error(str(exc), 400)
    binding.refresh_from_db()
    return JsonResponse(serialize_binding(binding), status=202)


@api_login_required
@require_http_methods(['POST'])
def sync(request):
    member = eligible(request)
    if not member:
        return api_error('请先加入团队', 403)
    data = body(request)
    ids = data.get('ids')
    if not isinstance(ids, list) or not ids or len(ids) > 200 or any(type(pk) is not int for pk in ids):
        return api_error('请选择账号', 400)
    with transaction.atomic():
        if not lock_active_member(request.user.pk,member.pk):
            return api_error('账号或团队身份已失效，不能同步平台绑定',403)
        bindings = list(PlatformBinding.objects.select_for_update().filter(user=request.user, pk__in=ids))
        if len(bindings) != len(set(ids)):
            return api_error('账号不存在', 404)
        if any(b.status == 'pending' and b.requested_at > timezone.now() - timedelta(minutes=5) for b in bindings):
            return api_error('正在同步', 409)
        if any(b.requested_at > timezone.now() - timedelta(seconds=60) for b in bindings):
            return api_error('请稍后再同步', 429)
        for binding in bindings:
            start(binding, data.get('full') is True)
    return JsonResponse({'bindings': [serialize_binding(b) for b in bindings]}, status=202)
