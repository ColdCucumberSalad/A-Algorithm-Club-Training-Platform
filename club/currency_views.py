from .cosmetic_terms import active_term
from .cosmetics import product_data,gift_badge_data,catalog_scope
"""
Currency system views and API endpoints
"""
import json
import base64
import io
import uuid
import calendar
import warnings
import hashlib
from PIL import Image, UnidentifiedImageError
from datetime import datetime, timedelta
from django.core.files.base import ContentFile
from django.db import transaction
from django.contrib.auth.models import User
from django.db.models import Sum
from django.db.models.deletion import ProtectedError
from django.http import JsonResponse, FileResponse, Http404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .views import api_login_required, api_error, body, membership_for
from .models import (
    CurrencyBalance, CurrencyTransaction, CheckinRecord,
    StreakReward, ContestRewardConfig, ContestSubmission,
    ShopItem, Purchase, UserInventory, TeamMembership, Team, FileDeletion
)
from .currency_config import config_data, validate_config, apply_config, currency_icon_url
from .currency_descriptions import ledger_description
from .currency_services import (
    get_or_create_balance, add_currency, deduct_currency,
    get_current_streak, perform_checkin, makeup_checkin,
    purchase_item, calculate_contest_reward, get_transaction_history,
    initialize_default_currency_config,positive_id
)


@api_login_required
@require_http_methods(["GET"])
def api_currency_balance(request):
    """Get currency balance for current member"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    if member.pk and not request.user.is_superuser:
        from .retirement import ensure_retirement_subsidies
        ensure_retirement_subsidies(request.user.pk)
    balance = get_or_create_balance(member) if member.pk and not request.user.is_superuser else None
    streak = get_current_streak(member) if member.pk and not request.user.is_superuser else 0

    return JsonResponse({
        "balance": balance.balance if balance else 0,
        "streak": streak,
        "can_purchase": bool(member.pk and not request.user.is_superuser),
        "site_admin": request.user.is_superuser,
        "currency_icon": currency_icon_url(member.team)
    })


@api_login_required
@require_http_methods(["GET"])
def api_currency_transactions(request):
    """Get transaction history"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    try:
        limit = int(request.GET.get('limit',50))
        if not 1 <= limit <= 500: raise ValueError()
    except (ValueError,TypeError):
        return api_error('记录数量必须是1–500之间的整数')
    transactions = get_transaction_history(member, limit) if member.pk else []

    data = [{
        "id": t.id,
        "amount": t.amount,
        "balance_after": t.balance_after,
        "type": t.transaction_type,
        "type_display": t.get_transaction_type_display(),
        "description": ledger_description(t),
        "created_at": t.created_at.isoformat()
    } for t in transactions]

    return JsonResponse({"transactions": data})


@api_login_required
@require_http_methods(["POST"])
def api_currency_checkin(request):
    """Perform daily check-in"""
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error("未找到团队成员信息", 404)

    if not member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)

    try:
        result = perform_checkin(member)
        return JsonResponse(result)
    except ValueError as e:
        return api_error(str(e), 400)


@api_login_required
@require_http_methods(["POST"])
def api_currency_makeup_checkin(request):
    """Perform makeup check-in"""
    member = membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error("未找到团队成员信息", 404)

    if not member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)

    data = body(request)
    checkin_date_str = data.get("checkin_date")

    if not checkin_date_str:
        return api_error("请提供签到日期", 400)

    try:
        checkin_date = datetime.strptime(checkin_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return api_error("日期格式错误", 400)

    try:
        result = makeup_checkin(member, checkin_date)
        return JsonResponse(result)
    except ValueError as e:
        # Check for special error codes to provide detailed response
        error_code = getattr(e, 'error_code', None)
        if error_code == "INSUFFICIENT_MAKEUP_TICKETS":
            return JsonResponse({
                "success": False,
                "error": str(e),
                "error_code": "INSUFFICIENT_MAKEUP_TICKETS",
                "item_id": getattr(e, 'item_id', None),
                "item_name": getattr(e, 'item_name', '补签券'),
                "item_price": getattr(e, 'item_price', 0)
            }, status=400)
        return api_error(str(e), 400)


@api_login_required
@require_http_methods(["GET"])
def api_currency_checkin_calendar(request):
    """Get check-in calendar for current month"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    if not member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)

    # Get year and month from request
    try:
        year = int(request.GET.get('year',timezone.localdate().year))
        month = int(request.GET.get('month',timezone.localdate().month))
        if not 1 <= year <= 9999 or not 1 <= month <= 12: raise ValueError()
    except (ValueError,TypeError):
        return api_error('年月格式无效')
    # Get all check-in records for the month
    records = CheckinRecord.objects.filter(
        team=member.team,
        member=member,
        checkin_date__year=year,
        checkin_date__month=month
    ).values_list('checkin_date', 'is_makeup')

    calendar_data = {
        str(date): {"checked_in": True, "is_makeup": is_makeup}
        for date, is_makeup in records
    }

    from .currency_services import signed_dates
    from datetime import date
    start=date(year,month,1);end=date(year,month,calendar.monthrange(year,month)[1])
    for day in signed_dates(member,start,end):
        calendar_data.setdefault(str(day),{'checked_in':True,'is_makeup':False})
    return JsonResponse({
        "year": year,
        "month": month,
        "calendar": calendar_data,
        "streak": get_current_streak(member)
    })


@api_login_required
@require_http_methods(["POST"])
def api_contest_submission(request):
    member=membership_for(request)
    if not member or not member.pk or request.user.is_superuser:
        return api_error('仅团队成员可以提交比赛材料',403)
    if not member.team.currency_enabled:return api_error('该团队未启用货币系统',403)
    data=body(request)
    name=data.get('contest_name','');url=data.get('contest_url','')
    if not isinstance(name,str) or not 1 <= len(name.strip()) <= 200 or not isinstance(url,str) or len(url)>500:
        return api_error('比赛名称或链接格式无效')
    if url:
        from django.core.validators import URLValidator
        from django.core.exceptions import ValidationError
        try:URLValidator(schemes=['https','http'])(url)
        except ValidationError:return api_error('比赛链接无效')
    try:picture=decode_shop_image(data.get('screenshot'))
    except ValueError as exc:return api_error(str(exc))
    item=ContestSubmission.objects.create(team=member.team,member=member,contest_name=name.strip(),contest_url=url,screenshot=picture,status=ContestSubmission.PENDING)
    return JsonResponse({'success':True,'submission_id':item.pk,'message':'比赛材料已保存；自动过题奖励请在赛事中心同步核验并领取'})


def shop_item_icon_url(item):
    if not item.icon:
        return None
    version = hashlib.sha256(item.icon.name.encode()).hexdigest()[:16]
    return f"/api/currency/shop/items/{item.pk}/icon?v={version}"


@api_login_required
@require_http_methods(["GET", "HEAD"])
def api_shop_item_icon(request, item_id):
    item = ShopItem.objects.select_related('team').filter(pk=item_id).first()
    if not item or not item.icon or not item.team.currency_enabled:
        raise Http404
    if not membership_for(request, item.team_id) and not UserInventory.objects.filter(member__user=request.user,item=item).exists() and not Purchase.objects.filter(member__user=request.user,item=item).exists():
        raise Http404
    image_file = None
    try:
        image_file = item.icon.open('rb')
        # Older uploads use a .png suffix even when their bytes are JPEG/WebP.
        image = Image.open(image_file)
        content_type = Image.MIME.get(image.format)
        if content_type not in {'image/png', 'image/jpeg', 'image/webp', 'image/gif', 'image/bmp', 'image/x-icon'}:
            raise ValueError('Unsupported shop image')
        image.verify()
        image_file.seek(0)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        if image_file is not None:
            image_file.close()
        raise Http404
    response = FileResponse(image_file, content_type=content_type)
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Security-Policy'] = "default-src 'none'; sandbox"
    return response


@api_login_required
@require_http_methods(["GET"])
@catalog_scope
def api_shop_items(request):
    """Get shop items"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    if not member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)

    from .shop_fulfillment import available_stock
    from .grades import is_retired
    retired = is_retired(request.user.pk)
    items = ShopItem.objects.filter(team=member.team, is_active=True)
    purchased = dict(Purchase.objects.filter(item__team=member.team, member__user_id=request.user.pk)
                     .order_by().values('item_id').annotate(total=Sum('quantity')).values_list('item_id', 'total'))
    from .models import ShopFulfillment
    from django.db.models import Count
    for row in ShopFulfillment.objects.filter(purchase__item__team=member.team,
            purchase__member__user_id=request.user.pk,status='reclaimed').values('purchase__item_id').annotate(total=Count('id')):
        item_id = row['purchase__item_id']
        purchased[item_id] = max(0,purchased.get(item_id,0)-row['total'])

    from .cosmetics import owned_details,product_data
    owned_cosmetics = {kind:owned_details(member.user_id,kind) for kind in ('badge','theme','frame')}
    def owns_cosmetic(item):
        return item.item_type in owned_cosmetics and item.cosmetic_key in owned_cosmetics[item.item_type]
    from .models import OwnedTitle
    owned = list(OwnedTitle.objects.filter(active_term(),user_id=member.user_id, inventory__quantity__gt=0).order_by('acquired_at','pk').values_list('item_id','text','expires_at','definition'))
    owned_items, owned_names = {row[0] for row in owned}, {row[1] for row in owned}
    def owns_title(item):
        return item.item_type == 'title' and (item.pk in owned_items or item.title_definition.get('text') in owned_names)

    def title_preview(item):
        if item.item_type != 'title':return {}
        if owns_title(item):
            return next(row[3] for row in owned if row[0]==item.pk or row[1]==item.title_definition.get('text'))
        return item.title_definition

    def owned_expiry(item):
        if owns_cosmetic(item):end=owned_cosmetics[item.item_type][item.cosmetic_key]
        elif owns_title(item):end=next(row[2] for row in owned if row[0]==item.pk or row[1]==item.title_definition.get('text'))
        else:return None
        return end.isoformat() if end else None
    from .cosmetics import components,ensure_available
    def component_data(item):
        if item.item_type not in ('theme','badge','frame','cosmetic'):return []
        try:return components(item)
        except ValueError:return []
    def appearance_block(item):
        if item.item_type in ('theme','badge','frame','cosmetic'):
            try:ensure_available(member.user_id,item,1)
            except ValueError as exc:return str(exc)
        if owns_title(item) and owned_expiry(item) is None:return '已永久拥有该称号'
        return ''
    data = [{
        "components":component_data(item),
        "expires_at":owned_expiry(item),
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "icon": shop_item_icon_url(item),
        "price": item.price,
        "stock": available_stock(item),
        "allow_multiple_purchase": bool(item.item_type == 'redeem_code' and item.card_source == 'api' and item.allow_multiple_purchase),
        "item_type": item.item_type,
        "cosmetic_duration_days":item.cosmetic_duration_days, "gift_badge":gift_badge_data(item),
        "title_definition": title_preview(item),
        "title_owned": owns_title(item),
        "cosmetic_key":item.cosmetic_key, "cosmetic":product_data(item), "cosmetic_owned":owns_cosmetic(item),
        "purchase_limit": item.purchase_limit if item.item_type == 'physical' else 0,
        "purchased_quantity": purchased.get(item.pk, 0),
        "purchase_limit_reached": bool(item.item_type == 'physical' and item.purchase_limit and purchased.get(item.pk, 0) >= item.purchase_limit),
        "purchase_blocked": (item.item_type == 'physical' and retired) or bool(appearance_block(item)),
        "purchase_block_reason": appearance_block(item) or ('大三+用户不可购买实物类商品' if item.item_type == 'physical' and retired else ''),
    } for item in items]

    return JsonResponse({"items": data})


@api_login_required
@require_http_methods(["POST"])
def api_shop_purchase(request):
    """Purchase an item from shop"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    if not member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)
    if not member.pk or request.user.is_superuser:
        return api_error("系统管理员当前为管理预览，无法购买商品", 403)

    data = body(request)
    item_id = data.get("item_id")
    quantity = data.get("quantity", 1)

    if not item_id:
        return api_error("请提供商品ID", 400)

    try:
        result = purchase_item(member, item_id, quantity,data.get('request_id'))
        balance = get_or_create_balance(member)
        result["balance"] = balance.balance
        return JsonResponse(result)
    except ValueError as e:
        return api_error(str(e), 400)


def inventory_expiry(inv):
    if inv.item.item_type=='title':
        owned=getattr(inv,'owned_title',None);end=owned.expires_at if owned else None
    elif inv.item.item_type=='theme':
        grant=next((g for g in inv.cosmetic_grants.all() if g.kind=='theme' and g.key==inv.item.cosmetic_key),None)
        end=grant.expires_at if grant else None
    else:end=None
    return end.isoformat() if end else None


@api_login_required
@require_http_methods(["GET"])
@catalog_scope
def api_user_inventory(request):
    """Get user inventory"""
    member = membership_for(request)
    if not member:
        return api_error("未找到团队成员信息", 404)

    inventory_items = UserInventory.objects.filter(
        member__user_id=member.user_id,
        quantity__gt=0
    ).select_related('item','owned_title').prefetch_related('cosmetic_grants')

    data = [{
        "id": inv.id,
        "inventory_id": inv.id,
        "item_id": inv.item_id,
        "item_name": inv.item.name,
        "description": inv.item.description,
        "item_type": inv.item.item_type,
        "cosmetic_key":inv.item.cosmetic_key,"cosmetic":product_data(inv.item),"components":[{**g.definition,"expires_at":g.expires_at.isoformat() if g.expires_at else None} for g in inv.cosmetic_grants.all() if g.definition],"expires_at":inventory_expiry(inv),
        "title_definition": getattr(inv,'owned_title',None).definition if inv.item.item_type == 'title' and getattr(inv,'owned_title',None) else {},
        "quantity": inv.quantity,
        "can_use": inv.item.item_type == 'consumable',
        "icon": shop_item_icon_url(inv.item)
    } for inv in inventory_items]

    from .shop_fulfillment import fulfillment_inventory
    data.extend(fulfillment_inventory(member))
    from .cosmetics import available
    direct_badges={inv.item.cosmetic_key for inv in inventory_items if inv.item.item_type=='badge'}
    for badge in available(member.user_id,'badge'):
        if badge['key'] not in direct_badges:
            data.append({'id':'gift-'+badge['key'],'item_id':'gift-'+badge['key'],'item_name':badge['name'],'description':'购买附赠徽章，永久赠品可独立于称号佩戴。','item_type':'badge','cosmetic_key':badge['key'],'cosmetic':badge,'expires_at':badge.get('expires_at'),'quantity':1,'can_use':False,'icon':badge['icon']})
    for frame in available(member.user_id,'frame'):
        data.append({'id':'gift-frame-'+frame['key'],'item_id':'gift-frame-'+frame['key'],'item_name':frame['name'],'description':'主题附赠头像框','item_type':'frame','cosmetic_key':frame['key'],'cosmetic':frame,'expires_at':frame.get('expires_at'),'quantity':1,'can_use':False,'icon':frame['icon']})
    response=JsonResponse({"inventory": data})
    response["Cache-Control"]="private, no-store"
    return response


def decode_shop_image(raw):
    if not isinstance(raw,str) or not raw:
        raise ValueError('请上传有效图片')
    try:
        content=base64.b64decode(raw.split(',',1)[-1],validate=True)
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            picture=Image.open(io.BytesIO(content))
            extensions={'PNG':'.png','JPEG':'.jpg','WEBP':'.webp','GIF':'.gif','BMP':'.bmp','ICO':'.ico'}
            extension=extensions[picture.format]
            picture.verify()
        return ContentFile(content,name=uuid.uuid4().hex+extension)
    except Exception:
        raise ValueError('请上传有效的 PNG、JPEG、WebP、GIF、BMP 或 ICO 图片') from None


# Admin-only views
@api_login_required
@require_http_methods(["POST"])
def api_admin_adjust_balance(request):
    """Admin: Adjust member balance"""
    admin_member = membership_for(request)
    if not request.user.is_superuser or not admin_member:
        return api_error("需要管理员权限", 403)

    if not admin_member.team.currency_enabled:
        return api_error("该团队未启用货币系统", 403)

    data = body(request)
    member_id = data.get("member_id")
    amount = data.get("amount")
    description = data.get("description", "管理员调整")

    if not member_id or amount is None:
        return api_error("请提供成员ID和金额", 400)

    if type(amount) is not int or not -100000 <= amount <= 100000 or amount == 0:
        return api_error("调整金额必须是 -100000 到 100000 之间的非零整数", 400)
    if not isinstance(description, str) or len(description) > 200:
        return api_error("调整说明不能超过 200 字", 400)

    try:member_id=positive_id(member_id)
    except ValueError as exc:return api_error(str(exc))
    try:
        target_member = TeamMembership.objects.get(pk=member_id, team=admin_member.team)
    except TeamMembership.DoesNotExist:
        return api_error("成员不存在", 404)

    try:
        from .currency_services import adjust_currency
        with transaction.atomic():
            User.objects.select_for_update().get(pk=target_member.user_id)
            new_balance = adjust_currency(target_member, amount, CurrencyTransaction.ADMIN_ADJUST, description, request.user)
    except ValueError as exc:
        return api_error(str(exc), 400)

    return JsonResponse({
        "success": True,
        "new_balance": new_balance
    })


@api_login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def api_admin_currency_config(request):
    if not request.user.is_superuser:
        return api_error("需要系统管理员权限", 403)
    data = body(request) if request.method == 'POST' else {}
    team_id = request.GET.get('team_id') or data.get('team_id')
    if team_id is not None and (isinstance(team_id, bool) or not str(team_id).isdigit()):
        return api_error('团队 ID 无效', 400)
    member = membership_for(request, team_id)
    if not member:
        return api_error('团队不存在', 404)
    team = Team.objects.select_for_update().get(pk=member.team_id)
    if request.method == 'POST':
        try:
            validate_config(data)
        except ValueError as exc:
            return api_error(str(exc), 400)
        apply_config(team, data)
    return JsonResponse(config_data(team))


@api_login_required
@require_http_methods(["GET"])
def api_currency_icon(request, team_id):
    member = membership_for(request, team_id)
    if not member or not member.team.currency_enabled or not member.team.currency_icon:
        raise Http404
    try:
        response = FileResponse(member.team.currency_icon.open('rb'), content_type='image/svg+xml')
    except FileNotFoundError:
        raise Http404
    response['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, no-store'
    return response


@api_login_required
@require_http_methods(['GET','POST','PUT','DELETE'])
@transaction.atomic
def api_admin_shop_items(request):
    member=membership_for(request)
    if not request.user.is_superuser or not member:return api_error('需要管理员权限',403)
    if not member.team.currency_enabled:return api_error('该团队未启用货币系统',403)
    if request.method=='GET':
        from .shop_fulfillment import admin_card_data
        return JsonResponse({'items':[{**admin_card_data(i),'id':i.pk,'name':i.name,'description':i.description,'price':i.price,
            'stock':i.stock,'is_active':i.is_active,'item_type':i.item_type,'title_definition':i.title_definition,'cosmetic_key':i.cosmetic_key,'cosmetic_duration_days':i.cosmetic_duration_days,'gift_badge_key':i.gift_badge_key,'cosmetic':product_data(i),'cosmetic_bundle':i.cosmetic_bundle,'purchase_limit':i.purchase_limit,'icon':shop_item_icon_url(i)} for i in ShopItem.objects.filter(team=member.team)]})
    data=body(request)
    if request.method=='POST':item=ShopItem(team=member.team,price=1)
    else:
        try:identity=positive_id(data.get('item_id'))
        except ValueError as exc:return api_error(str(exc))
        item=ShopItem.objects.select_for_update().filter(pk=identity,team=member.team).first()
        if not item:return api_error('商品不存在',404)
    if request.method=='DELETE':
        try:
            name=item.icon.name
            item.delete()
            if name:FileDeletion.objects.create(name=name)
        except ProtectedError:return api_error('商品已有购买记录或用户库存，请改为下架以保留历史记录',409)
        return JsonResponse({'success':True})
    values={key:data.get(key,getattr(item,key)) for key in ['name','description','price','stock','is_active','item_type','purchase_limit','cosmetic_duration_days','gift_badge_key']}
    if not isinstance(values['name'],str) or not 1<=len(values['name'].strip())<=100:return api_error('商品名称需为1–100字')
    if not isinstance(values['description'],str):return api_error('商品说明格式无效')
    if type(values['price']) is not int or not 1<=values['price']<=2147483647:return api_error('商品价格必须为正整数')
    if type(values['stock']) is not int or not -1<=values['stock']<=2147483647:return api_error('库存必须为-1（无限）或非负整数')
    if type(values['is_active']) is not bool:return api_error('上架状态格式无效')
    disabling_existing=bool(item.pk and values['item_type']==item.item_type and not values['is_active'])
    gift=values['gift_badge_key']
    from .cosmetics import catalog
    if not isinstance(gift,str) or gift and gift not in catalog('badge') and not (disabling_existing and gift==item.gift_badge_key):return api_error('赠品徽章无效')
    if values['item_type']!='physical':
        if data.get('gift_badge_key'):return api_error('仅实物类商品可配置该赠品')
        values['gift_badge_key']=''
    days=values['cosmetic_duration_days']
    if type(days) is not int or not 0<=days<=36500:return api_error('有效时长需为 0（永久）或 1–36500 天')
    if values['item_type'] not in ('title','theme','badge','frame','cosmetic'):
        if data.get('cosmetic_duration_days',0):return api_error('该商品类型不支持装扮有效时长')
        values['cosmetic_duration_days']=0

    if values['item_type'] not in ['general','makeup_ticket','consumable','redeem_code','physical','title','badge','theme','frame','cosmetic']:return api_error('商品类型无效')
    if type(values['purchase_limit']) is not int or not 0<=values['purchase_limit']<=2147483647:return api_error('限购数量必须为0（不限购）或正整数')
    if values['item_type'] != 'physical':
        if data.get('purchase_limit', 0):return api_error('仅实物类商品支持限购数量')
        values['purchase_limit'] = 0
    if item.pk and values['item_type']!=item.item_type and (item.purchases.exists() or item.user_inventories.exists()):
        return api_error('已有购买或库存的商品不能更改类型，请新增商品',409)
    from .shop_fulfillment import validate_card_settings, append_codes
    try:card_values,codes=validate_card_settings(item,data,values['item_type'])
    except ValueError as exc:return api_error(str(exc))
    title_definition = {}
    if values['item_type'] == 'title':
        from .member_titles import validate_title
        try:
            title_definition = validate_title(data.get('title_definition',item.title_definition))
            if not title_definition:
                raise ValueError('请配置称号文字、颜色与样式')
            if item.pk and item.purchases.exists() and title_definition['text'] != item.title_definition.get('text'):
                raise ValueError('已有购买记录的称号不能更换文字，请新增商品')
        except ValueError as exc:
            return api_error(str(exc))
    item.title_definition = title_definition
    if values['item_type'] in ('badge','theme','frame'):
        from .cosmetics import catalog
        key=data.get('cosmetic_key',item.cosmetic_key)
        if not isinstance(key,str) or key not in catalog(values['item_type']) and not (disabling_existing and key==item.cosmetic_key):return api_error('请选择支持的外观')
        if item.pk and key!=item.cosmetic_key and item.purchases.exists():return api_error('已有获得记录的商品不能替换外观，请新增商品',409)
        item.cosmetic_key=key
    else:item.cosmetic_key=''
    from .cosmetic_assets import validate_components
    if values['item_type']=='cosmetic':
        bundle=data.get('cosmetic_bundle',item.cosmetic_bundle)
        unlisting_unchanged=disabling_existing and bundle==item.cosmetic_bundle
        if not unlisting_unchanged:
            try:item.cosmetic_bundle=validate_components(bundle)
            except ValueError as exc:return api_error(str(exc))
    else:item.cosmetic_bundle=[]
    icon=None
    if data.get('icon'):
        try:icon=decode_shop_image(data['icon'])
        except ValueError as exc:return api_error(str(exc))
    for key,value in values.items():setattr(item,key,value.strip() if key=='name' else value)
    if card_values:
        for key,value in card_values.items():setattr(item,key,value)
    old=item.icon.name
    if icon:item.icon=icon
    elif 'icon' in data and data['icon'] is None:item.icon=''
    try:item.save()
    except Exception:
        if icon and item.icon.name and item.icon.name!=old:item.icon.storage.delete(item.icon.name)
        raise
    if old and item.icon.name!=old:FileDeletion.objects.create(name=old)
    append_codes(item,codes)
    return JsonResponse({'success':True,'item_id':item.pk})
