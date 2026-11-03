"""Quote and reclaim only unused purchase units before reversing sign-in rewards."""
import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from django.core import signing
from django.db.models import F
from django.http import JsonResponse
from django.utils import timezone

from .models import (CheckinRecord, CurrencyBalance, CurrencyTransaction, Purchase, ShopCode,
    ShopFulfillment, ShopItem, Submission, TeamMembership, UserInventory, WeeklyStreakGrant)

SALT = 'submission-reward-recovery-v1'


def build_plan(target):
    member, day = target.member, target.record_date
    balance = CurrencyBalance.objects.filter(user_id=member.user_id).values_list('balance', flat=True).first() or 0
    other = Submission.objects.filter(member=member, record_date=day, is_valid=True).exclude(pk=target.pk).exists()
    successor = None
    if getattr(target, 'is_valid', False) and target.problem_id:
        successor = Submission.objects.filter(member__user_id=member.user_id, problem_id=target.problem_id,
            is_duplicate=True).exclude(pk=target.pk).order_by('first_submitted_at','pk').first()
        if successor and successor.member_id == member.pk and successor.record_date == day:
            other = True
    required = 0
    if not other:
        from .currency_services import signed_dates
        required = CheckinRecord.objects.filter(member=member, checkin_date=day).values_list('reward_amount', flat=True).first() or 0
        monday = day-timedelta(days=day.weekday())
        dates = signed_dates(member, monday, monday+timedelta(days=6))-{day}
        if successor and successor.member_id == member.pk and monday <= successor.record_date <= monday+timedelta(days=6):
            dates.add(successor.record_date)
        longest = run = 0
        for offset in range(7):
            run = run+1 if monday+timedelta(days=offset) in dates else 0
            longest = max(longest, run)
        required += sum(WeeklyStreakGrant.objects.filter(member=member,team=member.team,
            week_start=monday,revoked_at__isnull=True,days__gt=longest).values_list('amount',flat=True))
    deficit = max(0, required-balance) if required else 0
    recoveries = []
    if deficit:
        purchases = list(Purchase.objects.filter(member__user_id=member.user_id,
            item__item_type__in=['makeup_ticket','consumable','physical','redeem_code']).select_related('item').order_by('pk'))
        units = {p.pk:{} for p in purchases}
        for unit in ShopFulfillment.objects.filter(purchase_id__in=units):
            units[unit.purchase_id][unit.sequence] = unit
        available = {row.item_id:row for row in UserInventory.objects.filter(member__user_id=member.user_id,quantity__gt=0)}
        unused, pending = defaultdict(list), []
        for purchase in purchases:
            price = purchase.total_price//purchase.quantity
            for sequence in range(1,purchase.quantity+1):
                unit = units[purchase.pk].get(sequence)
                quantity = (unit.api_num or 1) if unit else 1
                entry = {'quantity': quantity, 'purchase_id':purchase.pk,'sequence':sequence,'item_id':purchase.item_id,
                    'name':unit.item_name if unit else purchase.item.name,'refund':price*quantity,'unit_id':unit.pk if unit else None,'inventory_id':None}
                if unit and ((purchase.item.item_type=='redeem_code' and unit.status=='ready') or
                        (purchase.item.item_type in ('physical','consumable') and unit.status=='dispatching')):
                    pending.append(entry)
                elif not unit and purchase.item.item_type in ('makeup_ticket','consumable') and purchase.item_id in available:
                    entry['inventory_id'] = available[purchase.item_id].pk
                    unused[purchase.item_id].append(entry)
        # Old ticket consumption had no per-purchase units. Attribute that consumption
        # oldest-first, leaving only the currently owned quantity eligible for recovery.
        candidates = []
        for item_id, entries in unused.items():
            candidates.extend(entries[-available[item_id].quantity:])
        candidates.sort(key=lambda entry:(entry['purchase_id'],entry['sequence']),reverse=True)
        pending.sort(key=lambda entry:(entry['purchase_id'],entry['sequence']),reverse=True)
        for entry in candidates+pending:
            if entry['refund'] <= 0:
                continue
            recoveries.append(entry)
            deficit -= entry['refund']
            if deficit <= 0:
                break
    return {'submission_id':target.pk,'version':target.version,'balance':balance,
        'reward_reversal':required,'recoveries':recoveries}


def public_plan(plan):
    items = {}
    for entry in plan['recoveries']:
        item = items.setdefault(entry['item_id'],{'name':entry['name'],'quantity':0,'refund':0})
        item['quantity'] += entry.get('quantity', 1)
        item['refund'] += entry['refund']
    refund = sum(entry['refund'] for entry in plan['recoveries'])
    return {'items':list(items.values()),'refund':refund,'reward_reversal':plan['reward_reversal'],
        'balance_after':plan['balance']+refund-plan['reward_reversal']}


def fingerprint(plan):
    return hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def validate_balance_range(plan):
    # Reversals precede item refunds. Reject before changing any submission or
    # inventory when either ledger state would exceed the wallet's integer range.
    reversed_balance = plan['balance'] - plan['reward_reversal']
    final_balance = reversed_balance + sum(entry['refund'] for entry in plan['recoveries'])
    if not (-2147483648 <= reversed_balance <= 2147483647
            and -2147483648 <= final_balance <= 2147483647):
        raise ValueError('奖励收回超出余额存储范围，请先由管理员调整余额后重试')


def quote(target, actor, action):
    plan = build_plan(target)
    validate_balance_range(plan)
    return {**public_plan(plan),'token':signing.dumps({'actor':actor.pk,'action':action,
        'submission':target.pk,'fingerprint':fingerprint(plan)},salt=SALT)}


def lock_recovery_state(member):
    from .currency_services import get_or_create_balance
    TeamMembership.objects.select_for_update().get(pk=member.pk)
    balance = get_or_create_balance(member)
    CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
    list(UserInventory.objects.select_for_update(of=('self',)).filter(member__user_id=member.user_id).order_by('pk'))
    list(ShopFulfillment.objects.select_for_update(of=('self',)).filter(purchase__member__user_id=member.user_id).order_by('pk'))


def authorize(request, target, action, data):
    """Caller holds user/semester/submission locks; serialize purchases and delivery too."""
    lock_recovery_state(target.member)
    plan = build_plan(target)
    try:
        validate_balance_range(plan)
    except ValueError as exc:
        return None,JsonResponse({'error':str(exc)},status=400)
    token = data.get('recovery_token')
    valid = not token and not plan['recoveries']
    if token:
        try:
            payload = signing.loads(token,salt=SALT,max_age=300)
            valid = payload == {'actor':request.user.pk,'action':action,'submission':target.pk,'fingerprint':fingerprint(plan)}
        except (signing.BadSignature,TypeError,ValueError):
            valid = False
    if not valid:
        response = JsonResponse({'error':'余额或物品状态已变化，请重新查看回收清单并确认',
            'requires_recovery_confirmation':True},status=409)
        return None,response
    return plan,None


def reclaim(member, entries):
    from .currency_services import add_currency
    for entry in entries:
        if entry['inventory_id']:
            inventory = UserInventory.objects.select_for_update(of=('self',)).get(pk=entry['inventory_id'],member__user_id=member.user_id)
            if inventory.quantity < 1:
                raise ValueError('背包物品数量已变化，请重新确认')
            inventory.quantity -= 1
            inventory.save(update_fields=['quantity','updated_at'])
        if entry['unit_id']:
            unit = ShopFulfillment.objects.select_for_update(of=('self',)).get(pk=entry['unit_id'],purchase__member__user_id=member.user_id)
            if unit.status not in ('ready','dispatching'):
                raise ValueError('物品已经使用或派送完成，不能回收')
        else:
            unit = ShopFulfillment(purchase_id=entry['purchase_id'],sequence=entry['sequence'],item_name=entry['name'])
        unit.status = 'reclaimed'
        unit.refunded_amount = entry['refund']
        unit.reclaimed_at = timezone.now()
        unit.save()
        ShopCode.objects.filter(reserved_for=unit,consumed_at__isnull=True).update(reserved_for=None)
        ShopItem.objects.filter(pk=entry['item_id'],stock__gte=0).update(stock=F('stock')+entry.get('quantity', 1))
        add_currency(member,entry['refund'],CurrencyTransaction.ITEM_RECOVERY,f'回收 {entry["name"]} ×{entry.get("quantity", 1)}，按原购买价格返还')
