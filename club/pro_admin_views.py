"""Browser-session administration, protected by the normal CSRF middleware."""
import uuid

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .management_views import administrator_required
from .models import AppAccessToken, ProEntitlement, ProAudit
from .pro_services import APP_KEY, MAX_DURATION_DAYS, management_data, extend_expiry
from .shop_fulfillment import private_json
from .views import api_error, body


@administrator_required
def account_pro(request, user_id):
    if getattr(request, 'admin_test_mode', False):
        return api_error('请退出测试模式后管理 Pro', 403)
    if request.method not in ('GET', 'POST'):
        return api_error('仅支持 GET 或 POST', 405)
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=user_id).exclude(first_name='CLUB_TEST_SANDBOX').first()
        if not user:
            return api_error('账号不存在', 404)
        if request.method == 'GET':
            return private_json(management_data(user))
        if not user.is_active or user.is_superuser:
            return api_error('该账号不可在此修改', 403)
        data = body(request)
        try:
            request_id = uuid.UUID(str(data.get('request_id', '')))
        except (ValueError, TypeError, AttributeError):
            return api_error('操作编号无效')
        action, reason = data.get('action'), data.get('reason')
        if action not in ('extend', 'set_expiry', 'revoke', 'revoke_tokens'):
            return api_error('未知 Pro 操作')
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
            return api_error('请填写 1–300 字的操作原因')
        command = {key: data.get(key) for key in ('action', 'days', 'expires_at', 'expected_revision', 'reason')}
        prior = ProAudit.objects.filter(request_id=request_id).first()
        if prior:
            if prior.user_id != user.pk or prior.actor_id != request.user.pk or prior.command != command:
                return api_error('操作编号已被使用', 409)
            return private_json(management_data(user))
        entitlement = ProEntitlement.objects.filter(user=user, app=APP_KEY).first()
        revision = entitlement.revision if entitlement else 0
        if type(data.get('expected_revision')) is not int or data['expected_revision'] != revision:
            return api_error('Pro 状态已变化，请刷新后重试', 409)
        now = timezone.now()
        before = entitlement.expires_at if entitlement else None
        after = before
        if action == 'extend':
            days = data.get('days')
            if type(days) is not int or not 1 <= days <= MAX_DURATION_DAYS:
                return api_error('延长天数需为 1–36500 的整数')
            try:
                after = extend_expiry(before, days, now)
            except ValueError as exc:
                return api_error(str(exc))
        elif action == 'set_expiry':
            value = data.get('expires_at')
            try:
                after = parse_datetime(value) if isinstance(value, str) else None
            except ValueError:
                after = None
            if after is None or timezone.is_naive(after) or not 2000 <= after.year <= 9000:
                return api_error('到期时间需为带时区的 ISO 8601 日期')
        elif action == 'revoke':
            after = now
        if entitlement is None:
            entitlement = ProEntitlement(user=user, app=APP_KEY)
        try:
            with transaction.atomic():
                ProAudit.objects.create(user=user, app=APP_KEY, actor=request.user, action=action,
                    request_id=request_id, command=command, before_expires_at=before,
                    after_expires_at=after, reason=reason.strip())
        except IntegrityError:
            return api_error('操作编号已被使用', 409)
        entitlement.expires_at, entitlement.revision = after, revision + 1
        entitlement.save()
        if action == 'revoke_tokens':
            AppAccessToken.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=now)
        return private_json(management_data(user))
