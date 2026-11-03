"""Native-app-only Bearer authentication. Browser sessions never authorize these views."""
import hmac
import ipaddress
import secrets
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.crypto import salted_hmac
from django.views.decorators.csrf import csrf_exempt

from .models import AppAccessToken, AppRateLimit
from .pro_services import fingerprint, pro_data, redeem_code
from .views import body


def response(data, status=200):
    result = JsonResponse(data, status=status)
    result['Cache-Control'] = 'private, no-store'
    result['Pragma'] = 'no-cache'
    return result


def error(message, status):
    result = response({'error': message}, status)
    if status == 401:
        result['WWW-Authenticate'] = 'Bearer'
    return result


def limited(scope, value, limit, seconds):
    """Database-backed fixed window; independent of process-local caches/workers."""
    now = timezone.now()
    key = salted_hmac('app-rate:' + scope, value).hexdigest()
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


def app_endpoint(method, authenticated=True):
    def decorate(view):
        @csrf_exempt
        @wraps(view)
        def wrapped(request):
            if settings.APP_REQUIRE_HTTPS and not request.is_secure():
                return error('App 接口必须通过 HTTPS 访问', 403)
            if request.method != method:
                result = error('请求方法不支持', 405)
                result['Allow'] = method
                return result
            if not authenticated:
                return view(request)
            header = request.headers.get('Authorization', '')
            parts = header.split()
            if len(parts) != 2 or parts[0].lower() != 'bearer' or len(parts[1]) != 64:
                return error('登录凭据无效或已过期', 401)
            token_hash = fingerprint(parts[1])
            candidate = AppAccessToken.objects.filter(token_hash=token_hash).values_list('user_id', flat=True).first()
            if candidate is None:
                return error('登录凭据无效或已过期', 401)
            # Same order as shop and admin operations: user, then dependent records.
            with transaction.atomic():
                user = User.objects.select_for_update().filter(pk=candidate, is_active=True).first()
                token = AppAccessToken.objects.select_for_update().filter(token_hash=token_hash,
                    revoked_at__isnull=True, expires_at__gt=timezone.now()).first()
                if not user or not token or not hmac.compare_digest(token.auth_hash, user.get_session_auth_hash()):
                    return error('登录凭据无效或已过期', 401)
                request.app_user, request.app_token = user, token
                return view(request)
        return wrapped
    return decorate


@app_endpoint('POST', authenticated=False)
def login(request):
    data = body(request)
    username, password = data.get('username'), data.get('password')
    address = client_address(request)
    if limited('login-ip', address, 60, 300):
        return throttle_error()
    if not isinstance(username, str) or not 1 <= len(username.strip()) <= 150 or not isinstance(password, str) or not 1 <= len(password) <= 128:
        return error('账号或密码格式无效', 400)
    username = username.strip()
    # Unknown random names share the peer's bucket instead of creating a row per name.
    account_key = username.casefold() if User.objects.filter(username=username).exists() else 'unknown:' + address
    if limited('login-account', account_key, 10, 300):
        return throttle_error()
    user = authenticate(request, username=username, password=password)
    if not user or user.first_name == 'CLUB_TEST_SANDBOX':
        return error('账号或密码错误', 401)
    with transaction.atomic():
        # Account disable/reset racing with password verification invalidates the login.
        locked = User.objects.select_for_update().get(pk=user.pk)
        if not locked.is_active or locked.password != user.password:
            return error('账号或密码错误', 401)
        raw = secrets.token_hex(32)
        expires = timezone.now() + timedelta(seconds=settings.APP_TOKEN_TTL_SECONDS)
        AppAccessToken.objects.create(user=locked, token_hash=fingerprint(raw),
            auth_hash=locked.get_session_auth_hash(), expires_at=expires)
        return response({'token': raw, 'token_expires_at': expires.isoformat(),
            'user': {'id': locked.pk, 'username': locked.username}, 'pro': pro_data(locked)})


@app_endpoint('GET')
def pro(request):
    return response(pro_data(request.app_user))


@app_endpoint('POST')
def redeem(request):
    if limited('redeem-user', str(request.app_user.pk), 60, 300):
        return throttle_error()
    try:
        with transaction.atomic():
            redeem_code(request.app_user, body(request).get('code'))
    except ValueError as exc:
        return error(str(exc), 400)
    return response({'pro': pro_data(request.app_user)})


@app_endpoint('POST')
def logout(request):
    request.app_token.revoked_at = timezone.now()
    request.app_token.save(update_fields=['revoked_at'])
    return response({'ok': True})


@app_endpoint('POST', authenticated=False)
def card_redeem(request):
    from .models import ProRedeemCode
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
