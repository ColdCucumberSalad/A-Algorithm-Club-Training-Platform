from .cosmetic_terms import purchase_terms
"""System administrator member maintenance; no password or card secrets in responses."""
import json
import uuid

from django.contrib.admin.models import LogEntry, CHANGE
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.utils import timezone

from .management_views import administrator_required
from .models import (Team, TeamMembership, CurrencyBalance, CurrencyTransaction,
                     UserInventory, ShopItem, Purchase, ShopFulfillment, ShopCode)
from .views import api_error, body
from .member_titles import title_data, titles_data, validate_title, validate_titles, FONTS, awarded_titles_data, STYLES
from .grades import cohort_data, validate_admission_year, grade_for_year
from .models import UserProfile


def private(data):
    response = JsonResponse(data)
    response['Cache-Control'] = 'no-store'
    return response


def members(team_id):
    return TeamMembership.objects.filter(team_id=team_id, is_active=True,
        user__is_superuser=False, user__is_active=True).exclude(
        user__first_name='CLUB_TEST_SANDBOX').select_related('user')


def audit(actor, member, changes):
    LogEntry.objects.create(user=actor, content_type=ContentType.objects.get_for_model(TeamMembership),
        object_id=str(member.pk), object_repr=f'{member.team_id}:{member.display_name}'[:200],
        action_flag=CHANGE, change_message=json.dumps(changes, ensure_ascii=False))


def summary(member):
    balance = CurrencyBalance.objects.filter(user_id=member.user_id).values_list('balance', flat=True).first()
    return {'id':member.pk, 'user_id':member.user_id, 'name':member.display_name, 'account':member.user.username,
            'role':member.role, 'balance':balance or 0, 'title':title_data(member), 'titles':awarded_titles_data(member), 'title_styles':STYLES, 'title_fonts':FONTS, 'cohort':cohort_data(UserProfile.objects.filter(user_id=member.user_id).first())}


def detail(member):
    return {**summary(member), 'inventory':list(UserInventory.objects.filter(
        member__user_id=member.user_id).select_related('item').order_by('pk').values(
        'id', 'item_id', 'item__name', 'item__item_type', 'quantity')),
        'units':list(ShopFulfillment.objects.filter(purchase__member__user_id=member.user_id).order_by('-pk').values(
        'id', 'item_name', 'status', 'purchase__item__item_type'))}


@administrator_required
def member_list(request, team_id):
    if request.method != 'GET':
        return api_error('仅支持 GET', 405)
    if not Team.objects.filter(pk=team_id).exists():
        return api_error('团队不存在', 404)
    rows = list(members(team_id).order_by('display_name','pk'))
    wallets = dict(CurrencyBalance.objects.filter(user_id__in=[m.user_id for m in rows]).values_list('user_id','balance'))
    balances = {m.pk:wallets.get(m.user_id,0) for m in rows}
    return private({'members':[{'id':m.pk, 'name':m.display_name, 'account':m.user.username,
        'role':m.role, 'balance':balances.get(m.pk,0)} for m in rows],
        'items':list(ShopItem.objects.filter(team_id=team_id).order_by('name','pk').values('id','name','item_type','stock'))})


@administrator_required
def member_settings(request, team_id, member_id):
    if request.method not in ('GET','PATCH'):
        return api_error('仅支持 GET 或 PATCH', 405)
    target = members(team_id).filter(pk=member_id).first()
    if not target:
        return api_error('当前团队成员不存在', 404)
    if request.method == 'GET':
        return private(detail(target))
    data = body(request)
    if not isinstance(data, dict):
        return api_error('设置格式无效')
    try:
        with transaction.atomic():
            user = User.objects.select_for_update().get(pk=target.user_id)
            target = members(team_id).select_for_update(of=('self',)).get(pk=member_id)
            if data.get('action') == 'profile':
                name, account, role = data.get('name'), data.get('account'), data.get('role')
                password = data.get('password','')
                if not isinstance(name,str) or not 1 <= len(name.strip()) <= 40:
                    raise ValueError('成员名字需为 1–40 字')
                if not isinstance(account,str) or not 1 <= len(account.strip()) <= 150:
                    raise ValueError('登录账号需为 1–150 字')
                name, account = name.strip(), account.strip()
                if account.casefold() == 'admin' or account.startswith('__club_test_'):
                    raise ValueError('该登录账号为系统保留名称')
                User._meta.get_field('username').run_validators(account)
                if role not in ('member','admin'):
                    raise ValueError('请选择普通成员或团队管理员')
                if not isinstance(password,str) or len(password) > 128:
                    raise ValueError('新密码格式无效，最多 128 字符')
                if User.objects.exclude(pk=user.pk).filter(username=account).exists():
                    raise ValueError('登录账号已被使用')
                if TeamMembership.objects.filter(team_id=team_id,display_name=name).exclude(pk=target.pk).exists():
                    raise ValueError('团队内已有同名成员')
                user.username = account
                if password:
                    if len(password) < 8:
                        raise ValueError('新密码至少 8 位')
                    validate_password(password,user=user)
                    user.set_password(password)
                user.save(update_fields=['username','password'] if password else ['username'])
                target.display_name, target.role = name, role
                target.save(update_fields=['display_name','role'])
                audit(request.user,target,{'action':'profile','name':name,'account':account,'role':role,'password_reset':bool(password)})
            elif data.get('action') == 'admission_year':
                year = validate_admission_year(data.get('admission_year'))
                profile,_ = UserProfile.objects.get_or_create(user=user)
                profile.admission_year,profile.grade,profile.grade_date = year,grade_for_year(year),timezone.localdate()
                profile.save(update_fields=['admission_year','grade','grade_date'])
                audit(request.user,target,{'action':'admission_year','year':year})
            elif data.get('action') == 'titles':
                target.member_title = validate_titles(data.get('titles'))
                target.save(update_fields=['member_title'])
                audit(request.user,target,{'action':'member_titles','titles':target.member_title})
            elif data.get('action') == 'title':
                target.member_title = validate_title(data.get('title'))
                target.save(update_fields=['member_title'])
                audit(request.user,target,{'action':'member_title','title':target.member_title})
            elif data.get('action') == 'balance':
                value = data.get('balance')
                if type(value) is not int or not -2147483648 <= value <= 2147483647:
                    raise ValueError('Coins 余额需为 -2147483648 至 2147483647 的整数')
                from .currency_services import get_or_create_balance, adjust_currency
                balance = get_or_create_balance(target)
                balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
                if type(data.get('expected_balance')) is not int or balance.balance != data['expected_balance']:
                    return api_error('余额已变化，请刷新成员资料后重试',409)
                delta = value - balance.balance
                if delta:
                    adjust_currency(target,delta,CurrencyTransaction.ADMIN_ADJUST,
                        '成员管理：调整余额',request.user)
                    audit(request.user,target,{'action':'balance','delta':delta,'balance':value})
            else:
                raise ValueError('未知设置操作')
    except (ValueError, ValidationError) as exc:
        return api_error('; '.join(exc.messages) if isinstance(exc,ValidationError) else str(exc))
    except IntegrityError:
        return api_error('账号或成员名字已被使用，请刷新后重试',409)
    except TeamMembership.DoesNotExist:
        return api_error('成员状态已变化，请刷新',409)
    return private(detail(members(team_id).get(pk=member_id)))


@administrator_required
def inventory_settings(request, team_id, member_id):
    if request.method != 'POST':
        return api_error('仅支持 POST',405)
    data = body(request)
    if not isinstance(data,dict):
        return api_error('背包设置格式无效')
    try:
        with transaction.atomic():
            subject=TeamMembership.objects.filter(pk=member_id,team_id=team_id).values_list('user_id',flat=True).first()
            if subject:User.objects.select_for_update().get(pk=subject)
            scope=TeamMembership.objects.filter(team_id=team_id,user_id=request.global_inventory_user_id) if getattr(request,'global_inventory_user_id',None) else members(team_id)
            member = scope.select_for_update(of=('self',)).filter(pk=member_id).first()
            if not member:
                return api_error('当前团队成员不存在',404)
            action = data.get('action')
            if action == 'revoke':
                unit = ShopFulfillment.objects.filter(pk=data.get('unit_id'),purchase__member__user_id=member.user_id).select_related('purchase').first()
                if not unit:
                    return api_error('背包物品不存在',404)
                item = ShopItem.objects.select_for_update().get(pk=unit.purchase.item_id)
                unit = ShopFulfillment.objects.select_for_update().get(pk=unit.pk)
                if unit.status not in ('ready','dispatching'):
                    raise ValueError('只能收回未核销、未派发的物品')
                ShopCode.objects.filter(reserved_for=unit,consumed_at__isnull=True).update(reserved_for=None)
                if item.item_type in ('physical','redeem_code') and item.stock >= 0:
                    item.stock += unit.api_num or 1
                    item.save(update_fields=['stock'])
                unit.status, unit.reclaimed_at = 'reclaimed', timezone.now()
                unit.save(update_fields=['status','reclaimed_at'])
                audit(request.user,member,{'action':'inventory_revoke','unit_id':unit.pk,'item_id':item.pk})
            elif action in ('grant','quantity'):
                item = ShopItem.objects.select_for_update().filter(pk=data.get('item_id'),**({'team_id':team_id} if action=='grant' else {})).first()
                if not item:
                    return api_error('当前团队商品不存在',404)
                quantity = data.get('quantity')
                if type(quantity) is not int or not 0 <= quantity <= 100000:
                    raise ValueError('数量需为 0–100000 的整数')
                if action == 'grant':
                    if not 1 <= quantity <= 100:
                        raise ValueError('单次发放数量为 1–100 件')
                    try:
                        token = uuid.UUID(str(data.get('request_id','')))
                    except ValueError:
                        raise ValueError('发放请求编号无效') from None
                    prior = Purchase.objects.filter(request_id=token).first()
                    if prior:
                        if prior.member_id != member.pk or prior.item_id != item.pk or prior.quantity != quantity or prior.total_price != 0:
                            raise ValueError('该发放请求编号已被使用')
                        return private(detail(member))
                    from .shop_fulfillment import reserve_codes, create_fulfillments
                    if item.stock >= 0 and item.stock < quantity:
                        raise ValueError('商品库存不足')
                    codes = reserve_codes(item,quantity)
                    purchase = Purchase.objects.create(team_id=team_id,member=member,item=item,
                        quantity=quantity,total_price=0,request_id=token,**purchase_terms(item))
                    if item.stock >= 0:
                        item.stock -= quantity
                        item.save(update_fields=['stock'])
                    if item.item_type == 'title':
                        from .shop_titles import award
                        award(member,item,quantity,purchase)
                    if item.item_type in ('badge','theme','frame','cosmetic'):
                        from .cosmetics import award
                        award(member,item,quantity,purchase)
                    create_fulfillments(purchase,codes)
                    if item.item_type not in ('physical','redeem_code','title','badge','theme','frame','cosmetic'):
                        inv,_ = UserInventory.objects.get_or_create(team_id=team_id,member=member,item=item)
                        inv = UserInventory.objects.select_for_update().get(pk=inv.pk)
                        if inv.quantity + quantity > 100000:
                            raise ValueError('背包数量不能超过 100000')
                        inv.quantity += quantity
                        inv.save(update_fields=['quantity'])
                    audit(request.user,member,{'action':'inventory_grant','item_id':item.pk,'quantity':quantity,'purchase_id':purchase.pk})
                else:
                    inv = UserInventory.objects.select_for_update().filter(member__user_id=member.user_id,item=item,**({'pk':data['inventory_id']} if data.get('inventory_id') else {})).first()
                    if not inv or item.item_type in ('physical','redeem_code'):
                        raise ValueError('该物品需要按单件状态管理')
                    if type(data.get('expected_quantity')) is not int or inv.quantity != data['expected_quantity']:
                        return api_error('背包数量已变化，请刷新后重试',409)
                    if quantity > inv.quantity:
                        raise ValueError('增加物品请使用发放入口，以保留库存和发放记录')
                    before = inv.quantity
                    inv.quantity = quantity
                    inv.save(update_fields=['quantity'])
                    audit(request.user,member,{'action':'inventory_quantity','item_id':item.pk,'before':before,'after':quantity})
            else:
                raise ValueError('未知背包操作')
    except (ValueError,ValidationError,TypeError) as exc:
        return api_error(str(exc))
    except IntegrityError:
        return api_error('物品状态已变化，请刷新后重试',409)
    return private(detail(member))
