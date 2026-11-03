"""Room and escrow persistence. Every state change holds the room row lock."""
from datetime import timedelta
import secrets

from django.db import connection, transaction
from django.utils import timezone

from . import poker_engine as engine
from .models import CurrencyBalance, CurrencyTransaction, PokerChipBalance, PokerRoom, PokerSeat
from .currency_services import deduct_currency, get_or_create_balance


GLOBAL_PLAYER_LIMIT = 10
ADMISSION_LOCK_KEY = 749184215
CHIPS_PER_COIN = 1000
MAX_CHIPS = 9_000_000_000_000_000


def chip_balance(user_id):
    return PokerChipBalance.objects.filter(user_id=user_id).values_list('balance', flat=True).first() or 0


def locked_chips(user_id):
    account, _ = PokerChipBalance.objects.get_or_create(user_id=user_id)
    return PokerChipBalance.objects.select_for_update().get(pk=account.pk)


@transaction.atomic
def exchange_chips(member, action, coins):
    if action not in ('buy', 'withdraw') or type(coins) is not int or not 1 <= coins <= 2147483647:
        raise ValueError('兑换数量必须为正整数 Coins')
    if action == 'buy' and not member.team.currency_enabled:
        raise ValueError('当前团队未启用 RBC Coins')
    account = locked_chips(member.user_id)
    chips = coins * CHIPS_PER_COIN
    if action == 'buy':
        if account.balance + chips > MAX_CHIPS:
            raise ValueError('筹码余额超出上限')
        deduct_currency(member, coins, 'poker_buyin', f'德州扑克买入 {chips} 筹码')
        account.balance += chips
    else:
        if account.balance < chips:
            raise ValueError('筹码不足，每满 1000 筹码可提现 1 Coin；请先离桌取回桌上筹码')
        wallet = get_or_create_balance(member)
        wallet = CurrencyBalance.objects.select_for_update().get(pk=wallet.pk)
        if wallet.balance + coins > 2147483647:
            raise ValueError('Coin 钱包余额超出上限')
        account.balance -= chips
        wallet.balance += coins
        wallet.save(update_fields=['balance', 'updated_at'])
        CurrencyTransaction.objects.create(user_id=member.user_id, member=member, team=member.team,
            amount=coins, balance_after=wallet.balance, transaction_type='poker_cashout',
            description=f'德州扑克提现 {chips} 筹码')
    account.save(update_fields=['balance'])


def capacity():
    # Leaving players keep their place until the hand/escrow is actually settled.
    players = PokerSeat.objects.filter(room__closed=False, user__isnull=False).count()
    return {'players': players, 'limit': GLOBAL_PLAYER_LIMIT,
            'available': max(0, GLOBAL_PLAYER_LIMIT - players)}


def reserve_player_slot():
    # Serialize admission across teams, rooms and web processes. The transaction
    # lock is held through seat insertion (and any buy-in), not just the count.
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [ADMISSION_LOCK_KEY])
    if capacity()['available'] == 0:
        raise ValueError(f'全站联机人数已达 {GLOBAL_PLAYER_LIMIT} 人上限，请等待玩家离桌后再试')


def active(room):
    return bool(room.hand and room.hand['street'] != 'finished')


def participant(room, seat):
    player = room.hand.get('players', {}).get(seat.player_id)
    return player if player and player['seat_id'] == seat.pk else None


def cashout(seat):
    """Return table chips once, atomically with removal of the seat."""
    if seat.stack and seat.room.mode == 'coins' and seat.user_id:
        wallet = locked_chips(seat.user_id)
        if wallet.balance + seat.stack > MAX_CHIPS:
            return False  # Keep the escrow until the account has wallet capacity again.
        wallet.balance += seat.stack
        wallet.save(update_fields=['balance'])
    seat.delete()
    return True


def persist(room):
    for seat in room.seats.select_related('member', 'room').order_by('user_id'):
        player = participant(room, seat)
        if player:
            seat.stack = player['stack']
        if not active(room):
            seat.ready = not seat.user_id
            if not seat.user_id and seat.stack == 0:
                seat.stack = room.buy_in
        seat.save(update_fields=['stack', 'ready'])
        if seat.leaving and (not active(room) or not player):
            cashout(seat)
    room.version += 1
    if not room.seats.filter(user__isnull=False).exists():
        room.seats.filter(user__isnull=True).delete()
        room.closed = True
    room.save()


def fold_leaver(room, seat, now):
    player = participant(room, seat)
    if not active(room) or not player or player['folded']:
        return
    uid = seat.player_id
    player['folded'] = True
    room.hand['pending'] = [u for u in room.hand['pending'] if u != uid]
    room.hand['log'] = (room.hand['log'] + [f"{player['name']} 离桌弃牌"])[-24:]
    if len(engine.contenders(room.hand)) == 1 or room.hand['actor'] == uid:
        engine.advance(room.hand, player['number'], now.timestamp())


def close_practice(room):
    """Discard the private practice hand and all seats without settling chips."""
    room.seats.all().delete()
    room.hand = {}
    room.closed = True
    room.version += 1
    room.save(update_fields=['hand', 'closed', 'version'])


def tick(room, now=None):
    if room.closed:
        return False
    now = now or timezone.now()
    changed = False
    for seat in room.seats.select_related('member', 'user', 'room').order_by('user_id'):
        if not seat.user_id:
            continue
        if (seat.leaving or seat.last_seen < now - timedelta(minutes=5) or not seat.member.is_active or not seat.user.is_active):
            if room.mode == 'practice':
                close_practice(room)
                return True
            # An all-in player remains eligible: leaving cannot retract a committed wager.
            if not seat.leaving or seat.ready:
                seat.leaving = True
                seat.ready = False
                seat.save(update_fields=['leaving', 'ready'])
                changed = True
            p = participant(room, seat)
            if active(room) and p and p['stack'] > 0 and not p['folded']:
                fold_leaver(room, seat, now)
                changed = True
            if not active(room) or not p:
                changed = True
    # One timeout per tick gives every newly selected actor their own 45 seconds.
    if active(room) and room.hand.get('deadline', now.timestamp() + 1) <= now.timestamp():
        uid = room.hand['actor']
        legal = engine.legal_actions(room.hand, uid)
        engine.act(room.hand, uid, 'check' if legal['check'] else 'fold', None, now.timestamp())
        changed = True
    elif active(room) and room.hand['actor'].startswith('bot:') and room.hand['deadline'] - 44 <= now.timestamp():
        bot_action(room, now)
        changed = True
    if changed:
        persist(room)
    return changed


@transaction.atomic
def sweep_room(room_id):
    room = PokerRoom.objects.select_for_update().filter(pk=room_id, closed=False).first()
    if room:
        tick(room)


def room_data(room, user_id):
    uid = str(user_id)
    hand = room.hand
    result = hand.get('result')
    seats = []
    for seat in room.seats.select_related('member').order_by('number'):
        p = participant(room, seat)
        show = bool(p and (uid == seat.player_id or (result and result['showdown'] and not p['folded'])))
        seats.append({'user_id': seat.player_id, 'is_bot': not bool(seat.user_id), 'number': seat.number, 'name': seat.display_name,
                      'stack': seat.stack, 'ready': seat.ready, 'leaving': seat.leaving,
                      'cards': p['cards'] if show else [], 'card_count': len(p['cards']) if p else 0,
                      'folded': p['folded'] if p else False, 'bet': p['bet'] if p and active(room) else 0,
                      'in_hand': bool(p and active(room))})
    return {'id': str(room.pk), 'name': room.name, 'mode': room.mode, 'max_players': room.max_players,
            'buy_in': room.buy_in, 'big_blind': room.big_blind, 'version': room.version,
            'closed': room.closed, 'seats': seats, 'hand_number': room.hand_number,
            'dealer': room.dealer, 'street': hand.get('street', 'waiting'),
            'board': hand.get('board', []), 'pot': sum(p['total'] for p in hand.get('players', {}).values()),
            'actor': hand.get('actor'), 'deadline': hand.get('deadline'),
            'result': result, 'log': hand.get('log', []),
            'actions': engine.legal_actions(hand, uid) if active(room) else None}


@transaction.atomic
def create_room(member, data):
    # Team lock makes the room count limit safe across simultaneous creators.
    from .models import Team
    team = Team.objects.select_for_update().get(pk=member.team_id)
    mode = data.get('mode', 'coins')
    if mode not in ('coins', 'practice', 'friendly'):
        raise ValueError('请选择有效的游戏模式')
    if mode == 'coins' and not team.currency_enabled:
        raise ValueError('当前团队未启用 RBC Coins')
    if PokerSeat.objects.filter(user_id=member.user_id).exists():
        raise ValueError('请先离开当前牌桌')
    if PokerRoom.objects.filter(team=team, closed=False).count() >= 20:
        raise ValueError('房间数量已达上限，请加入现有房间')
    name = data.get('name', '')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 40:
        raise ValueError('房间名称应为 1–40 个字符')
    capacity, blind, buy_in = data.get('max_players', 6), data.get('big_blind', 2), data.get('buy_in', 1000)
    if mode == 'friendly':
        blind, buy_in = 10, 1000
    if mode == 'practice':
        bot_count = data.get('bot_count', 3)
        if type(bot_count) is not int or not 1 <= bot_count <= 5:
            raise ValueError('人机练习支持 1–5 个机器人')
        capacity, blind, buy_in = bot_count + 1, 10, 1000
    if type(capacity) is not int or not 2 <= capacity <= 9:
        raise ValueError('房间人数应为 2–9 人')
    if type(blind) is not int or blind not in (2, 4, 10, 20, 50, 100):
        raise ValueError('请选择有效的盲注级别')
    if type(buy_in) is not int or not blind <= buy_in <= 100000:
        raise ValueError('底注应不低于大盲注，上限 100000 筹码')
    room = PokerRoom.objects.create(team=team, created_by_id=member.user_id, name=name.strip(), mode=mode,
                                    max_players=capacity, big_blind=blind, buy_in=buy_in)
    join_room(room, member)
    if mode == 'practice':
        for number in range(1, capacity):
            PokerSeat.objects.create(room=room, bot_name=f'练习机器人 {number}', number=number, stack=buy_in, ready=True)
    return room


@transaction.atomic
def join_room(room, member):
    if room.closed:
        raise ValueError('房间已关闭')
    if room.mode == 'coins' and not member.team.currency_enabled:
        raise ValueError('当前团队未启用 RBC Coins')
    existing = PokerSeat.objects.filter(user_id=member.user_id).first()
    if existing:
        if existing.room_id == room.pk:
            return
        raise ValueError('每个账号只能同时加入一个房间，请先离桌')
    occupied = set(room.seats.values_list('number', flat=True))
    if room.mode == 'practice' and occupied:
        raise ValueError('人机房间为个人练习，请创建自己的练习桌')
    if len(occupied) >= room.max_players:
        raise ValueError('房间已满')
    reserve_player_slot()
    if room.mode == 'coins':
        account = locked_chips(member.user_id)
        if account.balance < room.buy_in:
            raise ValueError('剩余筹码不足，请先在大厅买入筹码')
        account.balance -= room.buy_in
        account.save(update_fields=['balance'])
    PokerSeat.objects.create(room=room, user_id=member.user_id, member=member,
                             number=next(n for n in range(room.max_players) if n not in occupied), stack=room.buy_in)
    room.version += 1
    room.save()


def operate(room, member, data):
    action = data.get('action')
    if action == 'join':
        join_room(room, member)
        return
    seat = room.seats.select_related('member', 'room').filter(user_id=member.user_id).first()
    if not seat:
        raise ValueError('请先加入房间')
    seat.last_seen = timezone.now()
    seat.save(update_fields=['last_seen'])
    if action == 'leave':
        if room.mode == 'practice':
            close_practice(room)
            return
        p = participant(room, seat)
        if active(room) and p:
            seat.leaving = True
            seat.save(update_fields=['leaving'])
            if p['stack'] > 0:
                fold_leaver(room, seat, timezone.now())
            persist(room)
        else:
            if not cashout(seat):
                raise ValueError('筹码余额接近上限，请先提现再结算离桌')
            persist(room)
        return
    if seat.leaving:
        raise ValueError('已申请离桌，将在本手结束后自动结算')
    if action == 'ready':
        if active(room):
            raise ValueError('请等待本手结束')
        if type(data.get('ready')) is not bool or type(data.get('hand_number')) is not int or data['hand_number'] != room.hand_number:
            raise ValueError('请刷新当前手牌后重新准备')
        if seat.stack <= 0:
            raise ValueError('筹码不足，请离桌后重新买入')
        if room.mode == 'coins' and not member.team.currency_enabled:
            raise ValueError('当前团队未启用 RBC Coins，请结算离桌')
        seat.ready = data['ready']
        seat.save(update_fields=['ready'])
        seats = list(room.seats.select_related('member').filter(stack__gt=0, leaving=False).order_by('number'))
        if len(seats) >= 2 and all(s.ready for s in seats):
            room.dealer = next((s.number for s in seats if s.number > room.dealer), seats[0].number)
            room.hand_number += 1
            room.hand = engine.start_hand(seats, room.dealer, room.big_blind, room.max_players,
                                          room.hand_number, timezone.now().timestamp())
            persist(room)
        else:
            room.version += 1
            room.save()
        return
    if data.get('version') != room.version or type(data.get('version')) is not int:
        raise ValueError('牌局已更新，请查看最新牌桌后操作')
    if action == 'refill':
        if room.mode not in ('practice', 'friendly') or active(room) or seat.stack > 0:
            raise ValueError('仅练习局筹码用完后可重新领取')
        seat.stack = room.buy_in
        seat.save(update_fields=['stack'])
        room.version += 1
        room.save()
        return
    engine.act(room.hand, str(member.user_id), action, data.get('amount'), timezone.now().timestamp())
    persist(room)


def bot_action(room, now):
    """Small stochastic opponent using only its own cards and the visible board."""
    state = room.hand
    uid = state['actor']
    legal = engine.legal_actions(state, uid)
    p = state['players'][uid]
    ranks = [int(c[:-1]) for c in p['cards']]
    if state['board']:
        strength = engine.rank_hand(p['cards'] + state['board'])[0]
        strong = strength >= 2
        playable = strength >= 1
    else:
        strong = ranks[0] == ranks[1] or min(ranks) >= 11
        playable = strong or max(ranks) >= 10 or p['cards'][0][-1] == p['cards'][1][-1]
    roll = secrets.randbelow(100)
    amount = min(legal['max_raise_to'], max(legal['min_raise_to'], state['current_bet'] + state['big_blind'] * 2))
    if legal['raise'] and strong and roll < 35:
        action = 'raise'
    elif legal['check']:
        action = 'check'
    elif strong or (playable and legal['call'] <= max(state['big_blind'] * 4, p['stack'] // 5)) or roll < 12:
        action = 'call'
    else:
        action = 'fold'
    engine.act(state, uid, action, amount, now.timestamp())
