"""Anonymous App card verification; no account login or management endpoints."""
import ipaddress
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt

from .models import AppRateLimit
from .pro_services import fingerprint, pro_data, redeem_code
from .views import body


def response(data, status=200):
    result = JsonResponse(data, status=status)
    result['Cache-Control'] = 'private, no-store'
    result['Pragma'] = 'no-cache'
    return result


def error(message, status):
    result = response({'error': message}, status)
    return result


def limited(scope, value, limit, seconds):
    """Database-backed fixed window; independent of process-local caches/workers."""
    now = timezone.now()
    key = salted_hmac('app-rate:' + scope, value).hexdigest()
    # Request-driven bounded expiry avoids a separate background cleanup feature.
    stale = list(AppRateLimit.objects.filter(window_start__lt=now - timedelta(days=1))
                 .order_by('window_start').values_list('pk', flat=True)[:100])
    AppRateLimit.objects.filter(pk__in=stale, window_start__lt=now - timedelta(days=1)).delete()
    with transaction.atomic():
        row, _ = AppRateLimit.objects.select_for_update().get_or_create(key=key, defaults={'window_start': now})
        if now >= row.window_start + timedelta(seconds=seconds):
            row.window_start, row.attempts = now, 0
        if row.attempts >= limit:
            return True
        row.attempts += 1
        row.save(update_fields=['window_start', 'attempts'])
    return False


def throttle_error():
    result = error('请求过于频繁，请稍后重试', 429)
    result['Retry-After'] = '300'
    return result


def client_address(request):
    """Trust only a configured proxy peer and its overwritten single X-Real-IP."""
    try:
        peer = ipaddress.ip_address(request.META.get('REMOTE_ADDR', ''))
    except ValueError:
        return 'invalid-peer'
    try:
        trusted = any(peer in ipaddress.ip_network(cidr) for cidr in settings.APP_TRUSTED_PROXY_CIDRS)
    except ValueError:
        trusted = False  # An invalid deployment configuration fails closed.
    if trusted:
        try:
            return str(ipaddress.ip_address(request.headers.get('X-Real-IP', '')))
        except ValueError:
            pass
    return str(peer)


@csrf_exempt
def card_redeem(request):
    from .models import ProRedeemCode
    if settings.APP_REQUIRE_HTTPS and not request.is_secure():
        return error('App 接口必须通过 HTTPS 访问', 403)
    if request.method != 'POST':
        result = error('请求方法不支持', 405)
        result['Allow'] = 'POST'
        return result
    if limited('card-ip', client_address(request), 30, 300):
        return throttle_error()
    data = body(request)
    code, device = data.get('code'), data.get('device_secret')
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 200 or not isinstance(device, str) or len(device) != 64 or any(c not in '0123456789abcdef' for c in device):
        return error('卡密或设备凭据无效', 400)
    candidate = ProRedeemCode.objects.filter(code_hash=fingerprint(code.strip())).values_list('owner_id', flat=True).first()
    if candidate is None:
        return error('卡密无效', 400)
    with transaction.atomic():
        user = User.objects.select_for_update().filter(pk=candidate, is_active=True).first()
        if not user:
            return error('卡密不可用', 400)
        card = ProRedeemCode.objects.select_for_update().get(code_hash=fingerprint(code.strip()))
        device_hash = fingerprint(device)
        if card.redeemed_at and card.device_hash != device_hash:
            return error('此卡密已被核销', 409)
        if card.device_hash and card.device_hash != device_hash:
            return error('此卡密已被核销', 409)
        # A device's consecutive cards must belong to the same purchasing account.
        if ProRedeemCode.objects.filter(device_hash=device_hash).exclude(owner=user).exists():
            return error('请使用同一购买账号的续期卡密', 409)
        try:
            redeem_code(user, code.strip())
        except ValueError as exc:
            return error(str(exc), 400)
        card.device_hash = device_hash
        card.save(update_fields=['device_hash'])
        return response({'token': device, 'token_expires_at': '8999-01-01T00:00:00+00:00',
            'user': {'id': 'card:' + str(user.pk), 'username': '卡密授权'}, 'pro': pro_data(user)})
