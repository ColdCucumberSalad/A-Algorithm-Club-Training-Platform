"""Pro benefit operations. Call mutations inside a transaction with the User locked."""
import hashlib
import secrets
import uuid
from datetime import timedelta

from django.utils import timezone

from .models import ProEntitlement, ProRedeemCode, ProAudit
from .problem_parser import key_cipher

APP_KEY = 'rbc_helper'
MAX_DURATION_DAYS = 36500


def extend_expiry(before, days, now=None):
    now = now or timezone.now()
    try:
        return max(now, before or now) + timedelta(days=days)
    except (OverflowError, ValueError):
        raise ValueError('累计 Pro 时长超出可保存的日期范围，请联系管理员') from None


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()


def pro_data(user, now=None):
    now = now or timezone.now()
    row = ProEntitlement.objects.filter(user=user, app=APP_KEY).first()
    expires = row.expires_at if row else None
    return {'active': bool(user.is_active and expires and expires > now),
            'expires_at': expires.isoformat() if expires else None, 'server_time': now.isoformat()}


def issue_code(unit, owner):
    if unit.pro_app != APP_KEY or not unit.pro_duration_days:
        raise ValueError('Pro 商品配置无效，请联系管理员')
    code = 'RBC-' + secrets.token_hex(24).upper()
    ProRedeemCode.objects.create(fulfillment=unit, owner=owner, app=unit.pro_app,
        duration_days=unit.pro_duration_days, code_hash=fingerprint(code))
    # The shop fulfillment is the sole encrypted recoverable copy, visible to its buyer.
    unit.encrypted_code = key_cipher().encrypt(code.encode()).decode()
    return code


def redeem_code(user, raw):
    if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 200:
        raise ValueError('卡密无效或不属于当前账号')
    code = ProRedeemCode.objects.select_for_update().filter(
        owner=user, app=APP_KEY, code_hash=fingerprint(raw.strip())).first()
    if not code:
        raise ValueError('卡密无效或不属于当前账号')
    if code.redeemed_at:
        return  # A retry never restores a subsequently revoked benefit.
    now = timezone.now()
    entitlement = ProEntitlement.objects.filter(user=user, app=APP_KEY).first()
    if entitlement is None:
        entitlement = ProEntitlement(user=user, app=APP_KEY)
    before = entitlement.expires_at
    entitlement.expires_at = extend_expiry(before, code.duration_days, now)
    entitlement.revision += 1
    entitlement.save()
    code.redeemed_at = now
    code.save(update_fields=['redeemed_at'])
    ProAudit.objects.create(user=user, app=APP_KEY, actor=user, action='redeem',
        request_id=uuid.uuid4(), code=code, before_expires_at=before,
        after_expires_at=entitlement.expires_at)


def management_data(user):
    row = ProEntitlement.objects.filter(user=user, app=APP_KEY).first()
    audits = ProAudit.objects.filter(user=user, app=APP_KEY).select_related('actor')[:50]
    return {'app': APP_KEY, **pro_data(user), 'revision': row.revision if row else 0,
        'unredeemed_codes': ProRedeemCode.objects.filter(owner=user, app=APP_KEY, redeemed_at__isnull=True).count(),
        'audit': [{'id': a.pk, 'action': a.action, 'actor': a.actor.username if a.actor else None,
            'before_expires_at': a.before_expires_at.isoformat() if a.before_expires_at else None,
            'after_expires_at': a.after_expires_at.isoformat() if a.after_expires_at else None,
            'reason': a.reason, 'created_at': a.created_at.isoformat()} for a in audits]}
