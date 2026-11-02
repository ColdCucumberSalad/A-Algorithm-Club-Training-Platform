"""Reserved stock, private redemption and the workbench dispatch inbox."""
import hashlib
import json
import uuid
from urllib.parse import urlsplit

from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import ShopItem, ShopCode, ShopFulfillment, UserInventory, Purchase, TeamMembership
from .problem_parser import key_cipher, http_fetch, canonical_problem
from .views import api_login_required, api_error, membership_for, body


def private_json(data):
    response = JsonResponse(data)
    response['Cache-Control'] = 'private, no-store'
    return response


def available_stock(item):
    if item.item_type == 'redeem_code' and item.card_source == 'inventory':
        remaining = item.card_codes.filter(reserved_for__isnull=True, consumed_at__isnull=True).count()
        return remaining if item.stock == -1 else min(item.stock, remaining)
    return item.stock


def admin_card_data(item):
    return {'card_source': item.card_source,
            'available_codes': item.card_codes.filter(reserved_for__isnull=True, consumed_at__isnull=True).count(),
            'has_card_api': bool(item.encrypted_card_api)}


def validate_card_settings(item, data, item_type):
    if item_type != 'redeem_code':
        return None, []
    source = data.get('card_source', item.card_source)
    if source not in ('inventory', 'api'):
        raise ValueError('请选择库存或 API 卡密来源')
    if item.pk and source != item.card_source and item.purchases.exists():
        raise ValueError('已有购买记录，不能更改卡密来源，请新增商品')
    raw = data.get('card_codes', '')
    if not isinstance(raw, str) or len(raw) > 1000000:
        raise ValueError('卡密列表格式无效或超过 1MB')
    codes = list(dict.fromkeys(line.strip() for line in raw.splitlines() if line.strip()))
    if len(codes) > 10000 or any(len(code) > 4096 for code in codes):
        raise ValueError('一次最多追加10000条卡密，单条最多4096字')
    encrypted = item.encrypted_card_api
    config = data.get('card_api')
    if config is not None:
        if not isinstance(config, dict):
            raise ValueError('API 配置需为 JSON 对象')
        url = config.get('url', '')
        try:
            canonical_problem(url)
        except Exception:
            raise ValueError('请填写公开的 HTTPS API 地址') from None
        if urlsplit(url).scheme != 'https':
            raise ValueError('卡密 API 必须使用 HTTPS')
        if config.get('method', 'POST') not in ('GET', 'POST'):
            raise ValueError('卡密 API 仅支持 GET 或 POST')
        headers = config.get('headers', {})
        if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str) or '\n' in k + v or '\r' in k + v for k, v in headers.items()):
            raise ValueError('API 请求头格式无效')
        if not isinstance(config.get('body', {}), dict):
            raise ValueError('API 请求体需为 JSON 对象')
        path = config.get('response_path', 'code')
        if not isinstance(path, str) or not path or len(path) > 200:
            raise ValueError('请填写卡密的响应字段路径，例如 data.code')
        raw_config = json.dumps(config, ensure_ascii=False)
        if len(raw_config) > 20000:
            raise ValueError('API 配置过大')
        encrypted = key_cipher().encrypt(raw_config.encode()).decode()
    if source == 'api' and not encrypted:
        raise ValueError('请先填写卡密 API 配置')
    return {'card_source': source, 'encrypted_card_api': encrypted}, codes


def append_codes(item, codes):
    for code in codes:
        ShopCode.objects.get_or_create(item=item, fingerprint=hashlib.sha256(code.encode()).hexdigest(),
            defaults={'encrypted_value': key_cipher().encrypt(code.encode()).decode()})


def reserve_codes(item, quantity):
    if item.item_type != 'redeem_code' or item.card_source != 'inventory':
        return []
    codes = list(ShopCode.objects.select_for_update().filter(item=item,
        reserved_for__isnull=True, consumed_at__isnull=True).order_by('pk')[:quantity])
    if len(codes) != quantity:
        raise ValueError('卡密库存不足')
    return codes


def create_fulfillments(purchase, codes):
    if purchase.item.item_type not in ('redeem_code', 'physical'):
        return
    for index in range(purchase.quantity):
        unit = ShopFulfillment.objects.create(purchase=purchase, sequence=index + 1,
            item_name=purchase.item.name, status='dispatching' if purchase.item.item_type == 'physical' else 'ready')
        if codes:
            code = codes[index]
            code.reserved_for = unit
            code.save(update_fields=['reserved_for'])


def fulfillment_inventory(member):
    return [{'id': 'fulfillment-' + str(unit.pk), 'fulfillment_id': unit.pk,
        'item_id': unit.purchase.item_id, 'item_name': unit.item_name,
        'description': unit.purchase.item.description, 'item_type': unit.purchase.item.item_type,
        'quantity': 1, 'status': unit.status, 'icon': '/api/currency/shop/items/' + str(unit.purchase.item_id) + '/icon' if unit.purchase.item.icon else None,
        'purchased_at': unit.purchase.purchased_at.isoformat(), 'can_redeem': unit.status == 'ready',
        'code': key_cipher().decrypt(unit.encrypted_code.encode()).decode() if unit.status == 'redeemed' and unit.encrypted_code else None}
        for unit in ShopFulfillment.objects.filter(purchase__member__user_id=member.user_id).select_related('purchase__item').order_by('-pk')]


@api_login_required
@require_http_methods(['POST'])
@transaction.atomic
def use_consumable(request, inventory_id):
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser or getattr(request, 'admin_test_mode', False):
        return api_error('请使用持有物品的成员账号', 403)
    try:
        token = uuid.UUID(str(body(request).get('request_id', '')))
    except (ValueError, TypeError, AttributeError):
        return api_error('使用请求编号无效', 400)
    from django.contrib.auth.models import User
    User.objects.select_for_update().get(pk=member.user_id)
    if not TeamMembership.objects.select_for_update().filter(pk=member.pk, is_active=True).exists():
        return api_error('当前成员权限已失效', 403)
    inventory = UserInventory.objects.select_for_update(of=('self',)).filter(pk=inventory_id,
        member__user_id=member.user_id, item__item_type='consumable').select_related('item').first()
    if not inventory:
        return api_error('消耗品不存在', 404)
    prior = ShopFulfillment.objects.filter(request_key=token).select_related('purchase').first()
    if prior:
        if prior.purchase.member.user_id != member.user_id or prior.purchase.item_id != inventory.item_id:
            return api_error('使用请求编号已被使用', 409)
        return private_json({'ok': True, 'duplicate': True, 'status': prior.status, 'fulfillment_id': prior.pk})
    if inventory.quantity < 1:
        return api_error('物品数量不足', 409)
    # Existing consumables already have purchase history but no per-unit fulfillment.
    # Allocate one unused purchase unit on demand, keeping old backpacks usable.
    from django.db.models import Count, F
    purchase = Purchase.objects.filter(member=inventory.member, item=inventory.item).annotate(
        used_units=Count('fulfillments')).filter(quantity__gt=F('used_units')).order_by('pk').first()
    if not purchase:
        return api_error('物品购买记录不完整，请联系管理员', 409)
    try:
        with transaction.atomic():
            used_sequences = set(purchase.fulfillments.values_list('sequence', flat=True))
            sequence = next(number for number in range(1,purchase.quantity+1) if number not in used_sequences)
            unit = ShopFulfillment.objects.create(purchase=purchase, sequence=sequence,
                item_name=inventory.item.name, status='dispatching', request_key=token)
    except IntegrityError:
        return api_error('使用请求编号已被使用，请刷新后重试', 409)
    inventory.quantity -= 1
    inventory.save(update_fields=['quantity', 'updated_at'])
    from .astrbot_notifications import notify_item_use
    notify_item_use(unit)
    return private_json({'ok': True, 'status': unit.status, 'fulfillment_id': unit.pk})


def fetch_card(item, unit):
    config = json.loads(key_cipher().decrypt(item.encrypted_card_api.encode()).decode())
    headers = {**config.get('headers', {}), 'Idempotency-Key': str(unit.request_key), 'Content-Type': 'application/json'}
    payload = json.dumps(config.get('body', {})).encode() if config.get('method', 'POST') == 'POST' else None
    try:
        result = json.loads(http_fetch(config['url'], payload=payload, headers=headers, timeout=8, public_only=True, redirects=0))
        for key in config.get('response_path', 'code').split('.'):
            result = result[int(key)] if isinstance(result, list) else result[key]
        if not isinstance(result, str) or not result.strip() or len(result) > 4096:
            raise ValueError()
        return result.strip()
    except Exception:
        raise ValueError('暂未取得卡密，物品未消耗；请稍后重试或联系管理员') from None


@api_login_required
@require_http_methods(['POST'])
@transaction.atomic
def redeem(request, unit_id):
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error('请使用购买商品的成员账号', 403)
    from django.contrib.auth.models import User
    User.objects.select_for_update().get(pk=member.user_id)
    TeamMembership.objects.select_for_update().get(pk=member.pk)
    unit = ShopFulfillment.objects.select_for_update().filter(pk=unit_id,
        purchase__member__user_id=member.user_id).select_related('purchase__item').first()
    if not unit or unit.purchase.item.item_type != 'redeem_code':
        return api_error('物品不存在', 404)
    if unit.status == 'redeemed':
        return private_json({'code': key_cipher().decrypt(unit.encrypted_code.encode()).decode(), 'duplicate': True})
    if unit.status != 'ready':
        return api_error('该物品当前不能核销', 409)
    item = unit.purchase.item
    if item.card_source == 'inventory':
        card = ShopCode.objects.select_for_update().filter(reserved_for=unit, consumed_at__isnull=True).first()
        if not card:
            return api_error('卡密暂不可用，请联系管理员', 409)
        code = key_cipher().decrypt(card.encrypted_value.encode()).decode()
        card.consumed_at = timezone.now()
        card.save(update_fields=['consumed_at'])
    else:
        try:
            code = fetch_card(item, unit)
        except ValueError as error:
            return api_error(str(error), 502)
    unit.status = 'redeemed'
    unit.redeemed_at = timezone.now()
    unit.encrypted_code = key_cipher().encrypt(code.encode()).decode()
    unit.save(update_fields=['status', 'redeemed_at', 'encrypted_code'])
    from .astrbot_notifications import notify_item_use
    notify_item_use(unit)
    return private_json({'code': code})


@api_login_required
@require_http_methods(['GET', 'POST'])
def dispatch_inbox(request):
    member = membership_for(request)
    if not request.user.is_superuser and (not member or not member.is_admin):
        return api_error('需要团队管理权限', 403)
    if getattr(request, 'admin_test_mode', False):
        return api_error('请退出测试模式后处理发货', 403)
    query = ShopFulfillment.objects.filter(purchase__item__item_type__in=['physical', 'consumable'])
    if not request.user.is_superuser:
        query = query.filter(purchase__team=member.team)
    if request.method == 'GET':
        rows = query.filter(status='dispatching').select_related('purchase__member', 'purchase__team', 'purchase__item').order_by('pk')
        return private_json({'pending_count': rows.count(), 'orders': [{'id': unit.pk, 'item_name': unit.item_name,
            'member_name': unit.purchase.member.display_name, 'team_name': unit.purchase.team.name,
            'item_type': unit.purchase.item.item_type, 'purchased_at': unit.purchase.purchased_at.isoformat()} for unit in rows[:200]]})
    with transaction.atomic():
        from .currency_services import positive_id
        try:
            identity = positive_id(body(request).get('id'))
        except ValueError as error:
            return api_error(str(error), 400)
        candidate = query.select_related('purchase').filter(pk=identity).first()
        if candidate:
            TeamMembership.objects.select_for_update().get(pk=candidate.purchase.member_id)
        unit = query.select_for_update(of=('self',)).select_related('purchase__item').filter(pk=identity).first()
        if not unit:
            return api_error('派发记录不存在', 404)
        completed_status = 'consumed' if unit.purchase.item.item_type == 'consumable' else 'delivered'
        if unit.status == completed_status:
            return private_json({'ok': True, 'duplicate': True})
        if unit.status != 'dispatching':
            return api_error('派发状态已变化', 409)
        unit.status = completed_status
        unit.delivered_at = timezone.now()
        unit.delivered_by = request.user
        unit.save(update_fields=['status', 'delivered_at', 'delivered_by'])
    return private_json({'ok': True})
