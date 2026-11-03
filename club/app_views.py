"""Anonymous App card verification; no account login or management endpoints."""
import hmac
import ipaddress
import math
import secrets
from functools import wraps
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt

from .models import AppRateLimit
from .pro_services import APP_KEY, MAX_DURATION_DAYS, fingerprint
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


def card_endpoint(scope):
    def decorate(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request):
            if settings.APP_REQUIRE_HTTPS and not request.is_secure():
                return error('App 接口必须通过 HTTPS 访问', 403)
            if request.method != 'POST':
                result = error('请求方法不支持', 405)
                result['Allow'] = 'POST'
                return result
            if limited(scope, client_address(request), 30, 300):
                return throttle_error()
            data = body(request)
            code = data.get('code')
            if not isinstance(code, str) or not 1 <= len(code.strip()) <= 200:
                return error('请提供有效格式的卡密', 400)
            return view(data, code.strip())
        return wrapped
    return decorate


def locked_card(code):
    from .models import ProRedeemCode
    # Lock the fulfillment too, so a shop reclaim cannot race activation.
    return ProRedeemCode.objects.select_for_update().filter(
        code_hash=fingerprint(code), app=APP_KEY,
        duration_days__gte=1, duration_days__lte=MAX_DURATION_DAYS,
        fulfillment__status='redeemed').first()


@card_endpoint('card-verify-ip')
def card_verify(data, code):
    with transaction.atomic():
        card = locked_card(code)
        if card is None or card.consumed_at:
            return response({'valid': False, 'app': APP_KEY, 'duration_days': None})
        now = timezone.now()
        if card.activation_expires_at and card.activation_expires_at > now:
            result = error('错误，卡密占用，请稍后重试', 409)
            result['Retry-After'] = str(math.ceil((card.activation_expires_at - now).total_seconds()))
            return result
        token = secrets.token_hex(32)
        deadline = now + timedelta(seconds=30)
        result = response({'valid': True, 'app': APP_KEY, 'duration_days': card.duration_days,
                           'activation_token': token, 'activation_expires_at': deadline.isoformat(),
                           'confirmation_timeout_seconds': 30})
        card.activation_token_hash = fingerprint(token)
        card.activation_expires_at = deadline
        card.save(update_fields=['activation_token_hash', 'activation_expires_at'])
        return result


@card_endpoint('card-confirm-ip')
def card_confirm(data, code):
    token = data.get('activation_token')
    if not isinstance(token, str) or len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
        return error('激活回执格式无效', 400)
    with transaction.atomic():
        card = locked_card(code)
        if card is None or not hmac.compare_digest(card.activation_token_hash, fingerprint(token)):
            return error('激活回执无效或已过期，请重新验证卡密', 409)
        if card.consumed_at:
            return response({'ok': True})  # Safe retry if the confirmation response was lost.
        now = timezone.now()
        if card.activation_expires_at is None or card.activation_expires_at <= now:
            return error('激活回执无效或已过期，请重新验证卡密', 409)
        result = response({'ok': True})
        card.consumed_at = now
        card.save(update_fields=['consumed_at'])
        return result
