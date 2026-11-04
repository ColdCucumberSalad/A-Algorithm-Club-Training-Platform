from .cosmetics import badge_data,frame_data, available, state as cosmetic_state
"""Own-account profile editing and explicitly requested platform synchronization."""
import uuid
from datetime import timedelta

from PIL import Image, UnidentifiedImageError
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404, JsonResponse, HttpResponseNotModified
from django.utils.cache import patch_vary_headers
from django.utils.http import parse_etags
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import AccountClosure, FileDeletion, PlatformBinding, UserProfile, TeamMembership
from .views import api_login_required, api_error, body, membership_for
from .platform_sync import PLATFORMS, validate_account
from . import avatar_images
from .member_titles import title_data, titles_data, awarded_titles_data, available_titles_data
from .grades import cohort_data


def avatar_url(user, size='large'):
    profile = UserProfile.objects.filter(user=user).first()
    return avatar_images.url_for(profile, size=size)


def serialize_binding(binding):
    pending = binding.status == 'pending'
    expired = pending and binding.requested_at < timezone.now() - timedelta(minutes=5)
    from .models import PlatformSolvedBaseline
    try:
        baseline=binding.solved_baseline
    except PlatformSolvedBaseline.DoesNotExist:
        baseline=None
    return {
        'id': binding.pk,
        'has_credentials': bool(binding.encrypted_credentials),
        'sync_progress': {'pages': binding.sync_state.get('pages', 0), 'count': binding.sync_state.get('count', 0)},
        'platform': binding.platform, 'account': binding.account,
        'snapshot': binding.snapshot,
        'status': 'failed' if expired else binding.status,
        'error': '同步超时，请重新同步' if expired else binding.error,
        'synced_at': binding.synced_at.isoformat() if binding.synced_at else None,
        'solved_baseline': {'total':baseline.total,'known_dates':len(baseline.dated_problems),
            'captured_at':baseline.captured_at.isoformat() if baseline.captured_at else None,
            'error':baseline.error} if baseline else None,
    }


def profile_data(request):
    member = membership_for(request)
    from .grades import grade_on, GRADES
    personal = UserProfile.objects.filter(user=request.user).first()
    grade = grade_on(personal)
    from .platform_rewards import available_rewards
    rewards=available_rewards(member)
    return {'name': member.display_name, 'account': request.user.username, 'title':title_data(member), 'titles':titles_data(member), 'awarded_titles':available_titles_data(member), 'worn_titles':member.worn_titles,'badge':badge_data(member),'avatar_frame':frame_data(member),'cosmetics':cosmetic_state(request.user),
            'cohort':cohort_data(personal), 'grade': grade, 'grade_label': GRADES[grade] if grade is not None else '注册资料缺失，请联系管理员',
            'grade_options': GRADES,
            'team_name': member.team.name, 'avatar': avatar_images.url_for(personal),
            'avatar_small': avatar_images.url_for(personal, member.pk, 'small'),
            'member_id': member.pk, 'member_avatar': avatar_images.url_for(personal, member.pk, 'small'),
            'platforms': PLATFORMS,
            'rewards':{'keys':list(rewards),'total':sum(row['amount'] for row in rewards.values())},
            'bindings': [serialize_binding(b) for b in request.user.platform_bindings.select_related('solved_baseline')]}


def eligible(request):
    member = membership_for(request)
    return member if member and member.pk and not request.user.is_superuser else None


def lock_active_member(user_id, member_id):
    """Call inside the write transaction; recheck eligibility after the user lock."""
    user = User.objects.select_for_update().get(pk=user_id)
    if not user.is_active or AccountClosure.objects.filter(user=user).exists():
        return None
    return TeamMembership.objects.select_for_update().filter(
        pk=member_id,user=user,is_active=True).first()


@api_login_required
@require_http_methods(['GET'])
def member_profile(request, member_id):
    """Read-only same-team profile, using saved public platform snapshots."""
    from django.core.paginator import Paginator, InvalidPage
    from .models import Submission, SubmissionPart
    from .views import serialize_submission
    from .grades import grade_on, GRADES
    viewer = membership_for(request)
    if not viewer:
        return api_error('请先加入团队',403)
    target = TeamMembership.objects.filter(pk=member_id, team=viewer.team,
        is_active=True, user__is_active=True, user__is_superuser=False).select_related('user').first()
    if not target:
        return api_error('成员不存在',404)
    # Never expose private sandbox users to ordinary members.
    if target.user.first_name == 'CLUB_TEST_SANDBOX' and target.user_id != request.user.pk:
        return api_error('成员不存在',404)
    personal = UserProfile.objects.filter(user=target.user).first()
    grade = grade_on(personal)
    allowed = {'rating','max_rating','solved','solved_label','rank','contests',
               'difficulty','rating_history','notes','profile_url'}
    bindings = [{'platform':b.platform, 'account':b.account, 'status':b.status,
        'synced_at':b.synced_at.isoformat() if b.synced_at else None,
        'snapshot':{key:value for key,value in (b.snapshot if isinstance(b.snapshot,dict) else {}).items() if key in allowed}}
        for b in target.user.platform_bindings.filter(platform__in=PLATFORMS)]
    query = Submission.objects.filter(member=target,team=viewer.team,is_valid=True,
        semester__archived_at__isnull=True).select_related('week','semester','problem','member').prefetch_related('parts').order_by('-submitted_at','-pk')
    try:
        page = Paginator(query,20).page(request.GET.get('page','1'))
    except InvalidPage:
        return api_error('提交页码无效')
    records = []
    for submission in page:
        record = serialize_submission(submission,parts=[p for p in submission.parts.all() if p.status==SubmissionPart.APPROVED])
        for key in ('can_edit','can_delete','can_resubmit'):
            record[key] = False
        record['rejection_note'] = ''
        for part in record['parts']:
            part['note'] = ''
        records.append(record)
    response = JsonResponse({'member':{'id':target.pk,'name':target.display_name,'role':target.role,'title':title_data(target),'titles':titles_data(target),'badge':badge_data(target),'avatar_frame':frame_data(target),'cohort':cohort_data(personal),
        'grade_label':GRADES[grade] if grade is not None else '',
        'avatar':avatar_images.url_for(personal,target.pk,'small')},
        'platforms':PLATFORMS,'bindings':bindings,'submissions':records,
        'next_page':page.next_page_number() if page.has_next() else None,'total':page.paginator.count})
    response['Cache-Control'] = 'private, no-store'
    return response


@api_login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    member = eligible(request)
    if not member:
        if request.method == 'GET' and request.user.is_superuser:
            return JsonResponse({'name': request.user.first_name or request.user.username, 'account': request.user.username, 'grade_label': '系统管理员', 'avatar': avatar_url(request.user), 'platforms': {}, 'bindings': [], 'read_only': True})
        return api_error('请先加入团队后管理个人资料', 403)
    if request.method == 'GET':
        return JsonResponse(profile_data(request))
    if 'grade' in request.POST or 'admission_year' in request.POST:
        return api_error('入学年份仅在注册时选择，修改请联系管理员',400)
    name = request.POST.get('name', member.display_name).strip()
    if not name or len(name) > 40:
        return api_error('昵称需为 1–40 个字符', 400)
    upload = request.FILES.get('avatar')
    avatar = None
    thumbnail = None
    if upload:
        if upload.size > 3 * 1024 * 1024:
            return api_error('头像不能超过 3 MB', 400)
        try:
            avatar, thumbnail = avatar_images.prepare_upload(upload)
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
            return api_error('请上传有效的 PNG、JPEG 或 WebP 图片（最多 1600 万像素）', 400)
    stored = []
    try:
        with transaction.atomic():
            member = lock_active_member(request.user.pk,member.pk)
            if not member:
                return api_error('账号或团队身份已失效，不能修改个人资料',403)
            member.display_name = name
            member.save(update_fields=['display_name'])
            personal, _ = UserProfile.objects.get_or_create(user=request.user)
            if avatar:
                old = personal.avatar.name
                storage = personal.avatar.storage
                name = storage.save(f'avatars/{uuid.uuid4().hex}.jpg', ContentFile(avatar))
                stored.append(name)
                small = storage.save(avatar_images.thumbnail_name(name), ContentFile(thumbnail))
                stored.append(small)
                personal.avatar = name
                personal.save(update_fields=['avatar'])
                if old:
                    FileDeletion.objects.create(name=old)
                    FileDeletion.objects.create(name=avatar_images.thumbnail_name(old))
            result = profile_data(request)
    except Exception as error:
        for name in stored:
            FileDeletion.objects.create(name=name)
        if isinstance(error, IntegrityError):
            return api_error('当前团队中已有此昵称，请换一个昵称', 409)
        raise
    return JsonResponse(result)


@api_login_required
@require_http_methods(['POST'])
def change_password(request):
    if request.user.is_superuser:
        from .system_management_views import change_admin_password
        return change_admin_password(request)
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.models import User
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError
    data = body(request)
    old, new, confirm = (data.get(k) for k in ('old_password','new_password','confirm_password'))
    if not all(isinstance(v,str) for v in (old,new,confirm)) or len(new)<8 or len(new)>128:
        return api_error('新密码需为 8–128 个字符',400)
    if new != confirm:
        return api_error('两次新密码不一致',400)
    with transaction.atomic():
        user=User.objects.select_for_update().get(pk=request.user.pk)
        if not user.check_password(old):
            return api_error('当前密码不正确',400)
        if old == new:
            return api_error('新密码不能与当前密码相同',400)
        try:
            validate_password(new,user)
        except ValidationError as exc:
            return api_error('；'.join(exc.messages),400)
        user.set_password(new);user.save(update_fields=['password'])
    update_session_auth_hash(request,user)
    return JsonResponse({'ok':True})


@api_login_required
@require_http_methods(['GET', 'HEAD'])
def avatar(request, member_id=None):
    user = request.user
    if member_id is not None:
        viewer = membership_for(request)
        if not viewer:
            raise Http404
        member = TeamMembership.objects.filter(pk=member_id, team=viewer.team,
            is_active=True, user__is_active=True).first()
        if not member:
            raise Http404
        user = member.user
    personal = UserProfile.objects.filter(user=user).first()
    if not personal or not personal.avatar:
        raise Http404
    size = request.GET.get('size', 'large')
    if size not in {'small', 'large'}:
        return api_error('头像尺寸无效', 400)
    try:
        name = avatar_images.ensure_thumbnail(personal) if size == 'small' else personal.avatar.name
        token = avatar_images.version(personal.avatar.name)
        etag = f'"{token}-{size}"'
        matches = parse_etags(request.headers.get('If-None-Match', ''))
        if '*' in matches or etag in matches or 'W/' + etag in matches:
            response = HttpResponseNotModified()
        else:
            file = personal.avatar.storage.open(name, 'rb')
            try:
                content_type = Image.MIME.get(Image.open(file).format, 'image/jpeg')
                file.seek(0)
                response = FileResponse(file, content_type=content_type)
            except Exception:
                file.close()
                raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        raise Http404
    response['ETag'] = etag
    response['Cache-Control'] = 'private, max-age=86400, immutable' if request.GET.get('v') == token else 'private, no-cache'
    # Authenticated team images must never enter a shared CDN cache.
    response['CDN-Cache-Control'] = 'no-store'
    response['Surrogate-Control'] = 'no-store'
    patch_vary_headers(response, ['Cookie'])
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def enqueue(binding):
    from .tasks import sync_platform_binding
    try:
        sync_platform_binding.delay(binding.pk, str(binding.sync_token))
    except Exception:
        PlatformBinding.objects.filter(pk=binding.pk, sync_token=binding.sync_token).update(
            status='failed', error='同步服务暂不可用，请稍后重试')


@api_login_required
@require_http_methods(['PUT', 'POST', 'DELETE'])
def platform_binding(request, platform):
    member = eligible(request)
    if not member:
        return api_error('请先加入团队', 403)
    if platform not in PLATFORMS:
        return api_error('不支持的平台', 400)
    data = body(request)
    if 'cookie' in data:
        return api_error('洛谷查询 Cookie 由系统管理员统一配置',400)
    with transaction.atomic():
        # Serialize changes per user, including first-time binding creation.
        if not lock_active_member(request.user.pk,member.pk):
            return api_error('账号或团队身份已失效，不能修改平台绑定',403)
        binding = PlatformBinding.objects.filter(user=request.user, platform=platform).first()
        if PlatformBinding.objects.filter(user=request.user, platform=platform).count() > 1:
            return api_error('请选择具体账号', 409)
        if request.method == 'DELETE':
            if binding:
                binding.delete()
            return JsonResponse({'ok': True})
        if request.method == 'POST' and not binding:
            return api_error('请先绑定账号', 400)
        if binding and binding.requested_at > timezone.now() - timedelta(seconds=60):
            return api_error('请等待一分钟后再同步', 429)
        if request.method == 'PUT':
            try:
                account = validate_account(platform, data.get('account'))
            except ValueError as exc:
                return api_error(str(exc), 400)
            changed = not binding or binding.account != account
            if not binding:
                binding = PlatformBinding(user=request.user, platform=platform)
            if changed:
                binding.snapshot = {}; binding.synced_at = None
                if binding.pk:
                    from .models import PlatformSolvedBaseline
                    PlatformSolvedBaseline.objects.filter(binding=binding).delete()
            binding.account = account
        if platform == 'qoj' or binding.sync_state.get('version') == 2:
            from .platform_account_views import start
            if not binding.pk:
                binding.save()
            start(binding, data.get('full') is True)
            binding.refresh_from_db()
            return JsonResponse(serialize_binding(binding), status=202)
        binding.sync_token = uuid.uuid4()
        binding.requested_at = timezone.now()
        binding.status = 'pending'; binding.error = ''
        binding.save()
        transaction.on_commit(lambda: enqueue(binding))
    binding.refresh_from_db()
    return JsonResponse(serialize_binding(binding), status=202)


@api_login_required
@require_http_methods(['POST'])
@transaction.atomic
def wear_title(request):
    member=eligible(request)
    if not member: return api_error('请先加入团队',403)
    data=body(request)
    if 'title' not in data:return api_error('请选择称号')
    selected=data.get('title')
    if selected is not None and not isinstance(selected,str): return api_error('称号选择无效')
    member=TeamMembership.objects.select_for_update().get(pk=member.pk,is_active=True)
    if selected is not None and selected not in [t['text'] for t in available_titles_data(member)]:
        return api_error('该称号未授予或已被收回',409)
    member.worn_titles=[selected] if selected else []
    member.save(update_fields=['worn_titles'])
    return JsonResponse({'titles':titles_data(member)})
