from .cosmetic_terms import purchase_terms
"""
Currency system business logic
"""
from datetime import date, timedelta
from django.contrib.auth.models import User
from django.db import transaction,IntegrityError
from django.db.models import Sum
import uuid
from django.utils import timezone

from .models import (
    CurrencyBalance, CurrencyTransaction, CheckinRecord,
    StreakReward, ContestRewardConfig, ShopItem, Purchase,
    UserInventory, TeamMembership, MakeupPermission, Semester
)


def positive_id(value):
    if isinstance(value,str) and len(value)<=19 and value.isdigit():value=int(value)
    if type(value) is not int or not 1<=value<=9223372036854775807:
        raise ValueError('编号必须为有效的正整数')
    return value


def get_or_create_balance(member):
    """Get or create currency balance for a member"""
    balance, created = CurrencyBalance.objects.get_or_create(
        user_id=member.user_id,
        defaults={"balance": 0, "team":member.team, "member":member}
    )
    return balance


@transaction.atomic
def adjust_currency(member, amount, transaction_type, description="", created_by=None):
    """Administrative adjustments may create debt; ordinary spending must not."""
    if type(amount) is not int or amount == 0:
        raise ValueError('调整金额必须为非零整数')
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
    result = balance.balance + amount
    if not -2147483648 <= result <= 2147483647:
        raise ValueError('调整后余额超出存储范围')
    balance.balance = result
    balance.save(update_fields=['balance', 'updated_at'])
    CurrencyTransaction.objects.create(user_id=member.user_id, team=member.team, member=member,
        amount=amount, balance_after=result, transaction_type=transaction_type,
        description=description, created_by=created_by)
    return result


@transaction.atomic
def add_currency(member, amount, transaction_type, description="", created_by=None, *, tip=None):
    """Add currency to a member's balance"""
    if type(amount) is not int or amount < 0:
        raise ValueError("金额必须为非负整数")
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
    if balance.balance + amount > 2147483647:
        raise ValueError('RBC Coins 余额已达存储上限，请联系管理员')
    balance.balance += amount
    balance.save()

    CurrencyTransaction.objects.create(
        team=member.team,
        member=member,
        amount=amount,
        balance_after=balance.balance,
        transaction_type=transaction_type,
        description=description,
        created_by=created_by,
        tip=tip,
    )

    return balance.balance


@transaction.atomic
def deduct_currency(member, amount, transaction_type, description="", created_by=None, *, tip=None):
    """Deduct currency from a member's balance"""
    if type(amount) is not int or amount <= 0:
        raise ValueError("扣除金额必须为正整数")
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)

    if balance.balance < amount:
        raise ValueError("余额不足")

    balance.balance -= amount
    balance.save()

    CurrencyTransaction.objects.create(
        team=member.team,
        member=member,
        amount=-amount,
        balance_after=balance.balance,
        transaction_type=transaction_type,
        description=description,
        created_by=created_by,
        tip=tip,
    )

    return balance.balance


def signed_dates(member, start=None, end=None):
    from .models import Submission
    filters = {'member':member}
    checkins = CheckinRecord.objects.filter(**filters)
    submissions = Submission.objects.filter(**filters,is_valid=True)
    if start:
        checkins=checkins.filter(checkin_date__gte=start)
        submissions=submissions.filter(record_date__gte=start)
    end = min(end,timezone.localdate()) if end else timezone.localdate()
    return set(checkins.filter(checkin_date__lte=end).values_list('checkin_date',flat=True)) | set(submissions.filter(record_date__lte=end).values_list('record_date',flat=True))


def get_current_streak(member):
    today=timezone.localdate()
    dates=signed_dates(member)
    cursor=today if today in dates else today-timedelta(days=1)
    streak=0
    while cursor in dates:
        streak+=1
        cursor-=timedelta(days=1)
    return streak


@transaction.atomic
def perform_checkin(member, *, day=None):
    """Sign today, or restore the original day of a rejected submission."""
    today = day or timezone.localdate()
    if not member.pk:
        raise ValueError('仅团队成员可以签到')
    # Use the same lock order as submission creation, deletion and rejection.
    User.objects.select_for_update().get(pk=member.user_id)
    if not TeamMembership.objects.select_for_update().get(pk=member.pk).is_active:
        raise ValueError('当前成员权限已失效')
    from .models import Submission
    if not Submission.objects.filter(team=member.team, member=member,
            record_date=today, is_valid=True).exists():
        raise ValueError('该日期没有有效提交，不能签到或领取奖励')

    # Check if already checked in today
    if CheckinRecord.objects.filter(team=member.team, member=member, checkin_date=today).exists():
        raise ValueError("今日已签到")

    from .reward_rules import daily_amount
    daily_reward = daily_amount(member,today)
    # Create check-in record
    CheckinRecord.objects.create(
        team=member.team,
        member=member,
        checkin_date=today,
        is_makeup=False,
        reward_amount=daily_reward,
    )

    # Award daily check-in reward
    add_currency(member, daily_reward, CurrencyTransaction.CHECKIN, "每日签到")

    # Check for streak rewards
    streak = get_current_streak(member)
    weekly_bonus = settle_weekly_streak(member, today)

    return {"success": True, "streak": streak, "reward": daily_reward, "weekly_bonus": weekly_bonus}


@transaction.atomic
def makeup_checkin(member, checkin_date):
    """Spend one ticket to persist a single historical submission permission."""
    User.objects.select_for_update().get(pk=member.user_id)
    from .semester_calendar import ensure_current_semester
    ensure_current_semester(member.team)
    if checkin_date >= timezone.localdate():
        raise ValueError('补签请选择今天之前的日期')
    today = timezone.localdate()
    semester = Semester.objects.select_for_update().filter(team=member.team, is_active=True,
        archived_at__isnull=True, starts_on__lte=checkin_date, ends_on__gte=today).first()
    if not semester:
        raise ValueError('仅可补交当前学期内的历史日期')
    from .services import build_weeks
    build_weeks(semester)
    week = semester.weeks.filter(starts_at__date__lte=checkin_date, ends_at__date__gt=checkin_date).first()
    if not week:
        raise ValueError('该日期没有对应周次，请联系管理员')
    locked = TeamMembership.objects.select_for_update().get(pk=member.pk)
    if not locked.is_active:
        raise ValueError('当前团队成员权限已失效')
    from .models import Submission
    permission = MakeupPermission.objects.filter(member=member, semester=semester, record_date=checkin_date).first()
    if (permission and permission.completed_at or
            CheckinRecord.objects.filter(team=member.team, member=member, checkin_date=checkin_date).exists() or
            Submission.objects.filter(member=member, record_date=checkin_date, is_valid=True).exists()):
        raise ValueError('该日期已签到或已有有效提交，无需补签')
    from django.db.models import Sum
    def result(already_open):
        remaining = UserInventory.objects.filter(member__user_id=member.user_id,
            item__item_type='makeup_ticket', quantity__gt=0).aggregate(total=Sum('quantity'))['total'] or 0
        return {'success': True, 'remaining_tickets': remaining, 'checkin_date': checkin_date.isoformat(),
                'week_id': week.pk, 'already_open': already_open, 'completed': False}
    if permission:
        return result(True)
    inventory = UserInventory.objects.select_for_update(of=('self',)).filter(
        member__user_id=member.user_id,
        item__item_type='makeup_ticket', quantity__gt=0).order_by('pk').first()
    if not inventory:
        item = ShopItem.objects.filter(team=member.team, item_type='makeup_ticket',
                                       is_active=True).exclude(stock=0).order_by('price', 'pk').first()
        error = ValueError('没有可用补签券，请前往 RBC 商店购买')
        error.error_code = 'INSUFFICIENT_MAKEUP_TICKETS'
        error.item_id = item.pk if item else None
        error.item_name = item.name if item else '补签券'
        error.item_price = item.price if item else None
        raise error
    inventory.quantity -= 1
    inventory.save(update_fields=['quantity'])
    permission = MakeupPermission.objects.create(member=member, semester=semester, record_date=checkin_date)
    from .astrbot_notifications import queue_notification
    queue_notification(f'makeup-use:{permission.pk}', 'item_used', member.team,
        f'【商品使用】{member.display_name} 使用了 {inventory.item.name} ×1。'
        f'\n补签日期：{checkin_date.isoformat()}', member_id=member.pk,
        item_id=inventory.item_id, permission_id=permission.pk)
    return result(False)

@transaction.atomic
def purchase_item(member, item_id, quantity=1, request_id=None):
    """Purchase an item from the shop"""
    if type(quantity) is not int or not 1 <= quantity <= 100:
        raise ValueError("购买数量必须是 1–100 的整数")
    item_id=positive_id(item_id)
    User.objects.select_for_update().get(pk=member.user_id)
    if not TeamMembership.objects.select_for_update().get(pk=member.pk).is_active:
        raise ValueError('当前成员权限已失效')
    token=None
    if request_id is not None:
        try:token=uuid.UUID(str(request_id))
        except (ValueError,TypeError):raise ValueError('购买请求编号无效')
        prior=Purchase.objects.filter(request_id=token).first()
        if prior:
            if prior.member_id!=member.pk or prior.item_id!=item_id or prior.quantity!=quantity:
                raise ValueError('购买请求编号已被使用')
            return {'success':True,'total_price':prior.total_price,'duplicate':True}
    try:
        item = ShopItem.objects.select_for_update().get(pk=item_id, team=member.team, is_active=True)
    except ShopItem.DoesNotExist:
        raise ValueError("商品不存在或已下架")

    if item.item_type == 'redeem_code' and item.card_source == 'api' and quantity > 1 and not item.allow_multiple_purchase:
        raise ValueError('该商品未开启单次多购，请每次购买1件')

    from .grades import is_retired
    if item.item_type == 'physical' and is_retired(member.user_id):
        raise ValueError('大三+用户不可购买实物类商品')

    # The item lock serializes purchases and limit edits before counting history.
    if item.item_type == 'physical' and item.purchase_limit:
        purchased = Purchase.objects.filter(item=item, member__user_id=member.user_id).aggregate(total=Sum('quantity'))['total'] or 0
        from .models import ShopFulfillment
        purchased -= ShopFulfillment.objects.filter(purchase__item=item,
            purchase__member__user_id=member.user_id,status='reclaimed').count()
        if purchased + quantity > item.purchase_limit:
            raise ValueError(f'已达购买上限：每人累计限购{item.purchase_limit}件，已购买{purchased}件')

    # Check stock
    if item.stock != -1 and item.stock < quantity:
        raise ValueError("库存不足")

    if item.item_type == 'title':
        from .shop_titles import ensure_available
        ensure_available(member.user_id, item, quantity)

    if item.item_type in ('badge','theme','frame','cosmetic'):
        from .cosmetics import ensure_available
        ensure_available(member.user_id,item,quantity)

    from .shop_fulfillment import reserve_codes, create_fulfillments
    codes = reserve_codes(item, quantity)
    total_price = item.price * quantity

    # Deduct currency
    deduct_currency(member, total_price, CurrencyTransaction.PURCHASE, f"购买 {item.name} x{quantity}")

    # Update stock
    if item.stock != -1:
        item.stock -= quantity
        item.save()

    # Create purchase record
    try:
        with transaction.atomic():
            purchase = Purchase.objects.create(team=member.team,member=member,item=item,quantity=quantity,total_price=total_price,request_id=token,**purchase_terms(item))
    except IntegrityError:
        raise ValueError('购买请求编号已被使用') from None


    # Add to inventory for consumable items
    if item.item_type in ["makeup_ticket", "consumable"]:
        inventory, created = UserInventory.objects.get_or_create(
            team=member.team,
            member=member,
            item=item,
            defaults={"quantity": 0}
        )
        inventory = UserInventory.objects.select_for_update().get(pk=inventory.pk)
        inventory.quantity += quantity
        inventory.save()

    if item.item_type == 'title':
        from .shop_titles import award
        award(member, item, quantity,purchase)
    if item.item_type in ('badge','theme','frame','cosmetic'):
        from .cosmetics import award
        award(member,item,quantity,purchase)
    create_fulfillments(purchase, codes)
    from .astrbot_notifications import notify_purchase
    notify_purchase(purchase)
    return {"success": True, "total_price": total_price}


def calculate_contest_reward(problems_solved, is_ak, team):
    """Calculate contest reward based on problems solved"""
    if is_ak:
        config = ContestRewardConfig.objects.filter(team=team, is_ak=True).first()
        return config.reward if config else 0

    # Find the highest applicable reward
    configs = ContestRewardConfig.objects.filter(
        team=team,
        is_ak=False,
        problems_solved__lte=problems_solved
    ).order_by('-problems_solved')

    if configs.exists():
        return configs.first().reward

    return 0


def get_transaction_history(member, limit=50):
    """Get transaction history for a member"""
    return CurrencyTransaction.objects.filter(user_id=member.user_id).select_related(
        'tip__sender__user__account_closure','tip__recipient__user__account_closure',
        'tip__sender_user__account_closure')[:limit]


def initialize_default_currency_config(team):
    """Initialize default currency configuration for a team"""
    # Create default streak rewards
    StreakReward.objects.get_or_create(
        team=team,
        days=7,
        defaults={"reward": 2}
    )
    StreakReward.objects.get_or_create(
        team=team,
        days=3,
        defaults={"reward": 1}
    )

    # Create default contest reward configs
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=2,
        defaults={"reward": 1, "is_ak": False}
    )
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=4,
        defaults={"reward": 2, "is_ak": False}
    )
    ContestRewardConfig.objects.get_or_create(
        team=team,
        problems_solved=1,
        defaults={"reward": 5, "is_ak": True}
    )

    # Create default makeup ticket item
    ShopItem.objects.get_or_create(
        team=team,
        item_type="makeup_ticket",
        defaults={
            "name": "补签券",
            "description": "使用补签券开放学期内历史日期的一次提交权限，提交记录后完成补签",
            "price": 3,
            "stock": -1,  # Unlimited
            "is_active": True
        }
    )


@transaction.atomic
def settle_weekly_streak(member, day):
    from .models import WeeklyStreakGrant, Submission
    if not member.team.currency_enabled:
        return 0
    TeamMembership.objects.select_for_update().get(pk=member.pk)
    monday = day - timedelta(days=day.weekday())
    dates = signed_dates(member,monday,monday+timedelta(days=6))
    longest = run = 0
    for offset in range(7):
        run = run + 1 if monday + timedelta(days=offset) in dates else 0
        longest = max(longest, run)
    awarded = 0
    from .reward_rules import streak_rules
    for rule in streak_rules(member,monday):
        if rule.days>longest or not rule.reward:continue
        grant, created = WeeklyStreakGrant.objects.get_or_create(team=member.team,user_id=member.user_id, week_start=monday,
            days=rule.days, defaults={'member':member,'amount':rule.reward})
        if created or grant.revoked_at:
            if grant.revoked_at:
                grant.revoked_at = None
                grant.member = member
                grant.save(update_fields=['revoked_at', 'member'])
            add_currency(member, grant.amount, CurrencyTransaction.STREAK_BONUS,
                f'{monday.isoformat()} 自然周 {rule.days} 天连签奖励')
            awarded += grant.amount
    return awarded


def reverse_signin_reward(member, amount, description):
    """Reverse the exact paid amount, including spent rewards, with an audit entry."""
    if not amount:
        return
    balance = get_or_create_balance(member)
    balance = CurrencyBalance.objects.select_for_update().get(pk=balance.pk)
    if balance.balance-amount < -2147483648:
        raise ValueError('奖励撤回超出余额存储范围，请联系管理员')
    balance.balance -= amount
    balance.save(update_fields=['balance', 'updated_at'])
    CurrencyTransaction.objects.create(team=member.team, member=member, amount=-amount,
        balance_after=balance.balance, transaction_type=CurrencyTransaction.REWARD_REVERSAL,
        description=description)


@transaction.atomic
def reconcile_submission_day(member, day, semester, recoveries=(), *, reopen_makeup=True):
    """Remove day-level benefits only after its final valid submission is gone."""
    from .models import Submission, WeeklyStreakGrant
    TeamMembership.objects.select_for_update().get(pk=member.pk)
    if Submission.objects.filter(member=member, record_date=day, is_valid=True).exists():
        return False
    checkin = CheckinRecord.objects.select_for_update().filter(member=member,
        team=member.team, checkin_date=day).first()
    if checkin:
        reverse_signin_reward(member, checkin.reward_amount, f'{day.isoformat()} 提交全部失效，撤回签到奖励')
        checkin.delete()
    permission = MakeupPermission.objects.filter(member=member, semester=semester, record_date=day)
    if reopen_makeup:
        permission.update(completed_at=None)
    else:
        permission.delete()
    today = timezone.localdate()
    if reopen_makeup and semester.is_active and not semester.archived_at and semester.starts_on <= day < today <= semester.ends_on:
        # Corrections reuse the already earned/opened date; do not spend another ticket.
        MakeupPermission.objects.get_or_create(member=member, semester=semester, record_date=day)
    monday = day-timedelta(days=day.weekday())
    dates = signed_dates(member, monday, monday+timedelta(days=6))
    longest = run = 0
    for offset in range(7):
        run = run+1 if monday+timedelta(days=offset) in dates else 0
        longest = max(longest, run)
    for grant in WeeklyStreakGrant.objects.select_for_update().filter(member=member,
            team=member.team, week_start=monday, revoked_at__isnull=True, days__gt=longest):
        reverse_signin_reward(member, grant.amount, f'{monday.isoformat()} 自然周 {grant.days} 天连签失效，撤回奖励')
        grant.revoked_at = timezone.now()
        grant.save(update_fields=['revoked_at'])
    if recoveries:
        from .reward_recovery import reclaim
        reclaim(member, recoveries)
    return bool(checkin)
