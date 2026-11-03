"""Anonymous App card verification; no account login or management endpoints."""
import ipaddress
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


@csrf_exempt
def card_verify(request):
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
    code = data.get('code')
    if not isinstance(code, str) or not 1 <= len(code.strip()) <= 200:
        return error('请提供有效格式的卡密', 400)
    with transaction.atomic():
        # Lock both the card and its fulfillment: only one request can consume it,
        # and a concurrent shop reclaim cannot race a successful verification.
        card = ProRedeemCode.objects.select_for_update().filter(
            code_hash=fingerprint(code.strip()), app=APP_KEY, consumed_at__isnull=True,
            duration_days__gte=1, duration_days__lte=MAX_DURATION_DAYS,
            fulfillment__status='redeemed').first()
        result = response({'valid': card is not None, 'app': APP_KEY,
                           'duration_days': card.duration_days if card else None})
        if card:
            card.consumed_at = timezone.now()
            card.save(update_fields=['consumed_at'])
        # Commit before returning the prepared response. HTTP delivery cannot be
        # made atomic with a database commit; a lost response does not undo use.
        return result
