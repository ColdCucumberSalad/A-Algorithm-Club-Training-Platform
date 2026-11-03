"""Server-owned no-limit Hold'em rules. Cards and shuffled decks never come from clients."""
from collections import Counter
from itertools import combinations
import secrets


HAND_NAMES = ['高牌', '一对', '两对', '三条', '顺子', '同花', '葫芦', '四条', '同花顺']


def rank_five(cards):
    ranks = sorted((int(c[:-1]) for c in cards), reverse=True)
    groups = sorted(((count, rank) for rank, count in Counter(ranks).items()), reverse=True)
    unique = sorted(set(ranks), reverse=True)
    straight = (unique[0] if len(unique) == 5 and unique[0] - unique[-1] == 4
                else 5 if unique == [14, 5, 4, 3, 2] else 0)
    flush = len({c[-1] for c in cards}) == 1
    if flush and straight:
        return (8, straight)
    if groups[0][0] == 4:
        return (7, groups[0][1], groups[1][1])
    if [g[0] for g in groups] == [3, 2]:
        return (6, groups[0][1], groups[1][1])
    if flush:
        return (5, *ranks)
    if straight:
        return (4, straight)
    if groups[0][0] == 3:
        return (3, groups[0][1], *sorted((r for n, r in groups[1:]), reverse=True))
    if [g[0] for g in groups[:2]] == [2, 2]:
        return (2, max(groups[0][1], groups[1][1]), min(groups[0][1], groups[1][1]), groups[2][1])
    if groups[0][0] == 2:
        return (1, groups[0][1], *sorted((r for n, r in groups[1:]), reverse=True))
    return (0, *ranks)


def rank_hand(cards):
    return max(rank_five(list(combo)) for combo in combinations(cards, 5))


def ordered(state, after):
    return sorted(state['players'], key=lambda uid: (state['players'][uid]['number'] - after - 1) % state['max_players'])


def contenders(state):
    return [uid for uid, p in state['players'].items() if not p['folded']]


def can_act(state):
    return [uid for uid in contenders(state) if state['players'][uid]['stack'] > 0]


def pay(state, uid, amount):
    p = state['players'][uid]
    amount = min(amount, p['stack'])
    p['stack'] -= amount
    p['bet'] += amount
    p['total'] += amount


def settle(state):
    """Separate each contribution tier, including uncalled-bet refunds and odd chips."""
    live = contenders(state)
    showdown = len(live) > 1
    scores = {uid: rank_hand(state['players'][uid]['cards'] + state['board']) for uid in live} if showdown else {}
    payouts = {uid: 0 for uid in state['players']}
    pots = []
    previous = 0
    for level in sorted({p['total'] for p in state['players'].values() if p['total']}):
        contributors = [uid for uid, p in state['players'].items() if p['total'] >= level]
        amount = (level - previous) * len(contributors)
        previous = level
        if len(contributors) == 1:
            winners = contributors  # Return an unmatched wager, even to a folded leaver.
        else:
            eligible = [uid for uid in live if state['players'][uid]['total'] >= level]
            # A tier containing only folded wagers belongs to the remaining player(s).
            eligible = eligible or live
            best = max(scores[uid] for uid in eligible) if showdown else None
            winners = [uid for uid in eligible if not showdown or scores[uid] == best]
        winners = [uid for uid in ordered(state, state['dealer']) if uid in winners]
        share, odd = divmod(amount, len(winners))
        for index, uid in enumerate(winners):
            payouts[uid] += share + (index < odd)
        pots.append({'amount': amount, 'winners': winners, 'refund': len(contributors) == 1})
    for uid, amount in payouts.items():
        state['players'][uid]['stack'] += amount
    state.update(street='finished', actor=None, deadline=None, pending=[],
                 result={'payouts': payouts, 'pots': pots, 'showdown': showdown,
                         'hands': {uid: HAND_NAMES[score[0]] for uid, score in scores.items()}})


def advance(state, after, now):
    """Move to the next actor, street, or showdown; automatically run out all-ins."""
    while True:
        if len(contenders(state)) == 1:
            settle(state)
            return
        active = can_act(state)
        state['pending'] = [uid for uid in state['pending'] if uid in active]
        if len(active) == 1 and state['players'][active[0]]['bet'] >= state['current_bet']:
            state['pending'] = []
        if state['pending']:
            state['actor'] = next(uid for uid in ordered(state, after) if uid in state['pending'])
            state['deadline'] = now + 45
            return
        if state['street'] == 'river':
            settle(state)
            return
        next_street = {'preflop': 'flop', 'flop': 'turn', 'turn': 'river'}[state['street']]
        state['deck'].pop()  # Burn one card before each community street.
        state['board'].extend(state['deck'].pop() for _ in range(3 if next_street == 'flop' else 1))
        state.update(street=next_street, current_bet=0, min_raise=state['big_blind'])
        for p in state['players'].values():
            p.update(bet=0, acted_at=None)
        state['pending'] = can_act(state) if len(can_act(state)) > 1 else []
        after = state['dealer']


def start_hand(seats, dealer, big_blind, max_players, hand_number, now):
    deck = [str(rank) + suit for suit in 'shdc' for rank in range(2, 15)]
    secrets.SystemRandom().shuffle(deck)
    players = {s.player_id: {'seat_id': s.pk, 'number': s.number, 'name': s.display_name,
               'stack': s.stack, 'cards': [], 'folded': False, 'bet': 0, 'total': 0, 'acted_at': None} for s in seats}
    state = dict(players=players, deck=deck, board=[], dealer=dealer, big_blind=big_blind,
                 max_players=max_players, hand_number=hand_number, street='preflop',
                 current_bet=big_blind, min_raise=big_blind, result=None, log=[])
    order = ordered(state, dealer)
    for _ in range(2):
        for uid in order:
            players[uid]['cards'].append(deck.pop())
    small = next(uid for uid, p in players.items() if p['number'] == dealer) if len(players) == 2 else order[0]
    big = next(uid for uid in ordered(state, players[small]['number']) if uid != small)
    pay(state, small, big_blind // 2)
    pay(state, big, big_blind)
    state.update(small_blind_user=small, big_blind_user=big, pending=can_act(state))
    advance(state, players[big]['number'], now)
    return state


def legal_actions(state, uid):
    if state.get('actor') != uid or state['street'] == 'finished':
        return None
    p = state['players'][uid]
    call = max(0, state['current_bet'] - p['bet'])
    reopened = p['acted_at'] is None or state['current_bet'] - p['acted_at'] >= state['min_raise']
    raise_allowed = reopened and len(can_act(state)) > 1 and p['stack'] > call
    return {'call': min(call, p['stack']), 'check': call == 0,
            'raise': raise_allowed, 'min_raise_to': state['current_bet'] + state['min_raise'],
            'max_raise_to': p['bet'] + p['stack'], 'all_in': p['stack'] <= call or raise_allowed}


def act(state, uid, action, amount, now):
    legal = legal_actions(state, uid)
    if legal is None:
        raise ValueError('尚未轮到你操作')
    p = state['players'][uid]
    if action == 'all_in':
        if not legal['all_in']:
            raise ValueError('当前不能全下，加注尚未重新开放')
        action = 'call' if p['stack'] <= state['current_bet'] - p['bet'] else 'raise'
        amount = p['bet'] + p['stack']
    if action == 'fold':
        p['folded'] = True
    elif action == 'check':
        if not legal['check']:
            raise ValueError('当前有下注，不能过牌')
    elif action == 'call':
        if legal['check']:
            raise ValueError('当前无需跟注，请过牌')
        pay(state, uid, legal['call'])
    elif action == 'raise':
        if not legal['raise'] or type(amount) is not int:
            raise ValueError('当前不能加注或加注金额无效')
        if amount <= state['current_bet'] or amount > legal['max_raise_to']:
            raise ValueError('加注金额超出可用筹码')
        if amount < legal['min_raise_to'] and amount != legal['max_raise_to']:
            raise ValueError('加注不足最小额度，只有全下可低于该额度')
        increase = amount - state['current_bet']
        pay(state, uid, amount - p['bet'])
        state['current_bet'] = amount
        if increase >= state['min_raise']:
            state['min_raise'] = increase
            state['pending'] = can_act(state)
        else:
            state['pending'] = list(set(state['pending']) | {u for u in can_act(state) if state['players'][u]['bet'] < amount})
    else:
        raise ValueError('不支持的操作')
    p['acted_at'] = state['current_bet']
    state['pending'] = [u for u in state['pending'] if u != uid]
    label = {'fold': '弃牌', 'check': '过牌', 'call': '跟注', 'raise': '加注至'}[action]
    state['log'] = (state['log'] + [f"{p['name']} {label}" + (f" {p['bet']}" if action in ('call', 'raise') else '')])[-24:]
    advance(state, p['number'], now)
