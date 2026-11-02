import copy
import json
import random
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.db import close_old_connections, transaction
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from . import poker_engine as engine, poker_services as poker
from .models import CurrencyBalance, CurrencyTransaction, PokerRoom, PokerSeat, Team, TeamMembership


def fake_seats(stacks):
    return [SimpleNamespace(pk=i+1, user_id=i+1, player_id=str(i+1), number=i,
                            display_name=f'Player {i+1}', stack=stack) for i, stack in enumerate(stacks)]


class PokerEngineTests(SimpleTestCase):
    def test_hand_rankings_and_wheel(self):
        examples = [
            ['14s','11d','9c','6h','3s'], ['14s','14d','9c','6h','3s'],
            ['14s','14d','9c','9h','3s'], ['14s','14d','14c','6h','3s'],
            ['14s','2d','3c','4h','5s'], ['14s','11s','9s','6s','3s'],
            ['14s','14d','14c','6h','6s'], ['14s','14d','14c','14h','3s'],
            ['10s','11s','12s','13s','14s'],
        ]
        for rank, cards in enumerate(examples):
            self.assertEqual(engine.rank_hand(cards)[0], rank)
        self.assertEqual(engine.rank_hand(examples[4]), (4, 5))
        self.assertGreater(engine.rank_hand(['9s','10d','11c','12h','13s']), (4, 5))
        self.assertEqual(engine.rank_hand(['14s','14d','14c','13h','13s','13d','2s']), (6, 14, 13))

    def test_heads_up_blinds_and_big_blind_option(self):
        state = engine.start_hand(fake_seats([100, 100]), 0, 2, 6, 1, 0)
        self.assertEqual(state['small_blind_user'], '1')
        self.assertEqual(state['big_blind_user'], '2')
        self.assertEqual(state['actor'], '1')
        engine.act(state, '1', 'call', None, 1)
        self.assertEqual(state['street'], 'preflop')
        self.assertEqual(state['actor'], '2')
        engine.act(state, '2', 'check', None, 2)
        self.assertEqual(state['street'], 'flop')
        self.assertEqual(state['actor'], '2')

    def test_side_pots_and_uncalled_refund(self):
        state = engine.start_hand(fake_seats([50, 100, 200]), 0, 2, 6, 1, 0)
        state['board'] = ['2s','3d','7c','8h','9s']
        for uid, total, cards in [('1',50,['14s','14d']), ('2',100,['13s','13d']), ('3',200,['12s','12d'])]:
            state['players'][uid].update(total=total, stack=0, cards=cards)
        engine.settle(state)
        self.assertEqual(state['result']['payouts'], {'1':150,'2':100,'3':100})
        self.assertEqual(sum(p['stack'] for p in state['players'].values()), 350)

    def test_tied_pot_odd_chip_goes_left_of_dealer(self):
        state = engine.start_hand(fake_seats([100]*3), 0, 2, 6, 1, 0)
        state['board'] = ['10s','11s','12s','13s','14s']
        for uid, cards in [('1',['2d','3d']), ('2',['4d','5d']), ('3',['6d','7d'])]:
            state['players'][uid].update(total=1, stack=99, cards=cards)
        state['players']['3']['folded'] = True
        engine.settle(state)
        self.assertEqual(state['result']['payouts'], {'1':1,'2':2,'3':0})

    def test_short_all_in_does_not_reopen_raise(self):
        state = engine.start_hand(fake_seats([100, 100, 7]), 0, 2, 6, 1, 0)
        engine.act(state, '1', 'raise', 6, 1)
        engine.act(state, '2', 'call', None, 2)
        engine.act(state, '3', 'all_in', None, 3)
        self.assertEqual(state['actor'], '1')
        self.assertFalse(engine.legal_actions(state, '1')['raise'])
        self.assertFalse(engine.legal_actions(state, '1')['all_in'])
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            engine.act(state, '1', 'raise', 11, 4)
        self.assertEqual(state, before)
        engine.act(state, '1', 'call', None, 4)
        engine.act(state, '2', 'call', None, 5)
        self.assertEqual(state['street'], 'flop')

    def test_randomized_games_conserve_all_chips_and_finish(self):
        rng = random.Random(41)
        for iteration in range(200):
            stacks = [rng.randint(1, 200) for _ in range(rng.randint(2, 9))]
            state = engine.start_hand(fake_seats(stacks), iteration % len(stacks), 2, 9, 1, 0)
            all_cards = state['deck'] + state['board'] + [c for p in state['players'].values() for c in p['cards']]
            self.assertEqual(len(all_cards), len(set(all_cards)))
            for step in range(250):
                if state['street'] == 'finished':
                    break
                self.assertEqual(sum(p['stack'] + p['total'] for p in state['players'].values()), sum(stacks))
                uid = state['actor']
                legal = engine.legal_actions(state, uid)
                choices = ['fold', 'check' if legal['check'] else 'call']
                if legal['raise']:
                    choices += ['raise', 'all_in']
                action = rng.choice(choices)
                engine.act(state, uid, action, min(legal['max_raise_to'], legal['min_raise_to']), step)
            self.assertEqual(state['street'], 'finished')
            self.assertEqual(sum(p['stack'] for p in state['players'].values()), sum(stacks))
            self.assertTrue(all(p['stack'] >= 0 for p in state['players'].values()))


class PokerFixtures:
    def setUp(self):
        self.admin, _ = User.objects.get_or_create(username='admin', defaults={'is_superuser':True,'is_staff':True})
        self.team = Team.objects.create(name='Poker QA', code='POKERQA', created_by=self.admin, currency_enabled=True)
        self.other = Team.objects.create(name='Other', code='POKEROTHER', created_by=self.admin, currency_enabled=True)
        self.users, self.members, self.clients = [], [], []
        for index in range(4):
            user = User.objects.create_user(f'poker-user-{index}')
            member = TeamMembership.objects.create(team=self.team, user=user, display_name=f'玩家{index}')
            CurrencyBalance.objects.create(user=user, team=self.team, member=member, balance=1000)
            client = Client(); client.force_login(user)
            session = client.session; session['team_id'] = self.team.pk; session.save()
            self.users.append(user); self.members.append(member); self.clients.append(client)
        self.client = self.clients[0]

    def post(self, client, path, data):
        return client.post(path, json.dumps(data), content_type='application/json')

    def create(self, **kwargs):
        data = {'name':'测试牌桌','max_players':3,'big_blind':2,'buy_in':100}
        data.update(kwargs)
        response = self.post(self.client, '/api/poker/rooms', data)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['room']

    def action(self, index, room, action, **kwargs):
        current = self.clients[index].get('/api/poker/rooms/' + room['id']).json()['room']
        if action == 'ready':
            seat = next(s for s in current['seats'] if s['user_id'] == str(self.users[index].pk))
            kwargs.update(ready=not seat['ready'], hand_number=current['hand_number'])
        return self.post(self.clients[index], '/api/poker/rooms/' + room['id'], {'action':action,'version':current['version'],**kwargs})

    def start(self, room, players=2):
        for index in range(1, players):
            self.assertEqual(self.action(index, room, 'join').status_code, 200)
        for index in range(players):
            response = self.action(index, room, 'ready')
            self.assertEqual(response.status_code, 200, response.content)
        return response.json()['room']


class PokerAPITests(PokerFixtures, TestCase):
    def test_auth_team_isolation_and_assets(self):
        self.assertEqual(Client().get('/api/poker/rooms').status_code, 401)
        room = self.create()
        stranger = User.objects.create_user('poker-stranger')
        TeamMembership.objects.create(team=self.other,user=stranger,display_name='外部成员')
        client = Client(); client.force_login(stranger)
        self.assertEqual(client.get('/api/poker/rooms/' + room['id']).status_code, 404)
        self.assertEqual(client.get('/api/poker/rooms').json()['rooms'], [])
        for asset in ['/poker.js', '/poker.css']:
            self.assertEqual(client.get(asset).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/api/poker/rooms').status_code, 400)

    def test_buyin_leave_and_retries_are_not_duplicated(self):
        room = self.create()
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 900)
        self.assertEqual(self.action(0, room, 'join').status_code, 200)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_buyin').count(), 1)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertEqual(self.action(0, room, 'leave').status_code, 409)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_cashout').count(), 1)
        self.assertFalse(PokerSeat.objects.exists())
        self.assertTrue(PokerRoom.objects.get(pk=room['id']).closed)

    def test_insufficient_funds_and_invalid_input_roll_back_room(self):
        for data in [{'buy_in':True}, {'buy_in':-10}, {'max_players':20}, {'big_blind':3}, {'mode':'bad'}, {'name':'x'*41}]:
            response = self.post(self.client, '/api/poker/rooms', {'name':'Bad', **data})
            self.assertEqual(response.status_code, 400)
        wallet = CurrencyBalance.objects.get(user=self.users[0]); wallet.balance = 1; wallet.save()
        response = self.post(self.client, '/api/poker/rooms', {'name':'No money'})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(PokerRoom.objects.exists())
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_private_cards_turn_validation_and_stale_replay(self):
        room = self.start(self.create())
        for index in range(2):
            data = self.clients[index].get('/api/poker/rooms/' + room['id']).json()['room']
            for seat in data['seats']:
                self.assertEqual(len(seat['cards']), 2 if seat['user_id'] == str(self.users[index].pk) else 0)
            self.assertNotIn('deck', data)
            self.assertNotIn('players', data)
        actor = next(i for i, user in enumerate(self.users) if str(user.pk) == room['actor'])
        self.assertEqual(self.action(1-actor, room, 'call').status_code, 409)
        path = '/api/poker/rooms/' + room['id']
        data = {'action':'call','version':room['version']}
        self.assertEqual(self.post(self.clients[actor], path, data).status_code, 200)
        self.assertEqual(self.post(self.clients[actor], path, data).status_code, 409)

    def test_complete_hand_and_wallet_conservation(self):
        room = self.start(self.create())
        for _ in range(30):
            if room['street'] == 'finished':
                break
            index = next(i for i,u in enumerate(self.users) if str(u.pk) == room['actor'])
            data = self.clients[index].get('/api/poker/rooms/' + room['id']).json()['room']
            response = self.action(index, room, 'check' if data['actions']['check'] else 'call')
            self.assertEqual(response.status_code, 200, response.content)
            room = response.json()['room']
        self.assertEqual(room['street'], 'finished')
        self.assertEqual(sum(s['stack'] for s in room['seats']), 200)
        for index in range(2):
            self.assertEqual(self.action(index, room, 'leave').status_code, 200)
        self.assertEqual(sum(CurrencyBalance.objects.filter(user__in=self.users).values_list('balance',flat=True)), 4000)
        self.assertEqual(sum(CurrencyTransaction.objects.values_list('amount',flat=True)), 0)

    def test_leave_during_hand_finishes_and_refunds(self):
        room = self.start(self.create())
        response = self.action(0, room, 'leave')
        self.assertEqual(response.status_code, 200, response.content)
        room = response.json()['room']
        self.assertEqual(room['street'], 'finished')
        self.assertFalse(PokerSeat.objects.filter(user=self.users[0]).exists())
        self.assertEqual(self.action(1, room, 'leave').status_code, 200)
        self.assertEqual(sum(CurrencyBalance.objects.values_list('balance',flat=True)), 4000)

    def test_all_in_leaver_keeps_showdown_rights(self):
        room = self.start(self.create())
        actor = next(i for i,u in enumerate(self.users) if str(u.pk) == room['actor'])
        room = self.action(actor, room, 'all_in').json()['room']
        self.assertEqual(self.action(actor, room, 'leave').status_code, 200)
        persisted = PokerRoom.objects.get(pk=room['id'])
        self.assertFalse(persisted.hand['players'][str(self.users[actor].pk)]['folded'])
        room = self.action(1-actor, room, 'call').json()['room']
        self.assertEqual(room['street'], 'finished')
        self.assertTrue(room['result']['showdown'])
        self.assertFalse(PokerSeat.objects.filter(user=self.users[actor]).exists())
        self.action(1-actor, room, 'leave')
        self.assertEqual(sum(CurrencyBalance.objects.values_list('balance',flat=True)), 4000)

    def test_timeout_disconnect_and_reconnect(self):
        room = self.start(self.create())
        row = PokerRoom.objects.get(pk=room['id']); row.hand['deadline'] = time.time()-1; row.save()
        after = self.client.get('/api/poker/rooms/' + room['id']).json()['room']
        self.assertEqual(after['street'], 'finished')  # Small blind owes a call, so timeout folds.
        self.assertIn('current_room', self.client.get('/api/poker/rooms').json())
        PokerSeat.objects.filter(room=row).update(last_seen=timezone.now()-timedelta(minutes=6))
        poker.sweep_room(row.pk)
        self.assertFalse(PokerSeat.objects.filter(room=row).exists())
        self.assertEqual(sum(CurrencyBalance.objects.values_list('balance',flat=True)), 4000)

    def test_room_capacity_join_mid_hand_and_single_seat(self):
        room = self.start(self.create(max_players=3))
        self.assertEqual(self.action(2, room, 'join').status_code, 200)
        data = self.clients[2].get('/api/poker/rooms/' + room['id']).json()['room']
        self.assertFalse(next(s for s in data['seats'] if s['user_id'] == str(self.users[2].pk))['in_hand'])
        self.assertEqual(self.action(3, room, 'join').status_code, 409)
        self.assertEqual(self.post(self.clients[2], '/api/poker/rooms', {'name':'Another'}).status_code, 400)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[3]).balance, 1000)

    def test_practice_never_touches_wallet_or_income_even_on_cashout(self):
        self.team.currency_enabled = False; self.team.save()
        room = self.create(mode='practice', bot_count=2, buy_in=1000000)
        self.assertEqual(room['mode'], 'practice')
        self.assertEqual(room['buy_in'], 1000)
        self.assertEqual(len(room['seats']), 3)
        self.assertFalse(CurrencyTransaction.objects.exists())
        # Even a large winning practice stack must never be credited as real income.
        PokerSeat.objects.filter(user=self.users[0]).update(stack=5000)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertFalse(CurrencyTransaction.objects.exists())
        self.assertFalse(PokerSeat.objects.exists())

    def test_practice_bots_complete_a_hand_and_are_private(self):
        room = self.create(mode='practice', bot_count=2)
        self.assertEqual(self.clients[1].get('/api/poker/rooms').json()['rooms'], [])
        self.assertEqual(self.clients[1].get('/api/poker/rooms/' + room['id']).status_code, 404)
        room = self.action(0, room, 'ready').json()['room']
        for _ in range(150):
            if room['street'] == 'finished':
                break
            if room['actor'].startswith('bot:'):
                row = PokerRoom.objects.get(pk=room['id']); row.hand['deadline'] = time.time()+43; row.save()
                response = self.client.get('/api/poker/rooms/' + room['id'])
            else:
                response = self.action(0, room, 'check' if room['actions']['check'] else 'call')
            self.assertEqual(response.status_code, 200, response.content)
            room = response.json()['room']
        self.assertEqual(room['street'], 'finished')
        self.assertFalse(CurrencyTransaction.objects.exists())
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertFalse(PokerSeat.objects.exists())

    def test_practice_refill_only_when_busted_and_between_hands(self):
        room = self.create(mode='practice', bot_count=1)
        self.assertEqual(self.action(0, room, 'refill').status_code, 409)
        PokerSeat.objects.filter(user=self.users[0]).update(stack=0)
        self.assertEqual(self.action(0, room, 'refill').status_code, 200)
        self.assertEqual(PokerSeat.objects.get(user=self.users[0]).stack, 1000)
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_disabled_currency_allows_cashout_but_not_new_coin_games(self):
        room = self.create()
        self.team.currency_enabled = False; self.team.save()
        self.assertEqual(self.action(1, room, 'join').status_code, 409)
        self.assertEqual(self.action(0, room, 'ready').status_code, 409)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)

    def test_failed_stale_action_does_not_undo_timeout(self):
        room = self.start(self.create())
        row = PokerRoom.objects.get(pk=room['id']); row.hand['deadline'] = time.time()-1; row.save()
        response = self.post(self.client, '/api/poker/rooms/' + room['id'], {'action':'call','version':room['version']})
        self.assertEqual(response.status_code, 409)
        row.refresh_from_db()
        self.assertEqual(row.hand['street'], 'finished')

    def test_multiple_rooms_keep_independent_hands(self):
        first = self.start(self.create())
        response = self.post(self.clients[2], '/api/poker/rooms', {'name':'第二桌'})
        self.assertEqual(response.status_code, 200)
        second = response.json()['room']
        self.assertEqual(self.action(3, second, 'join').status_code, 200)
        self.action(2, second, 'ready')
        self.action(3, second, 'ready')
        before = PokerRoom.objects.get(pk=second['id']).hand
        actor = next(i for i,u in enumerate(self.users) if str(u.pk) == first['actor'])
        self.assertEqual(self.action(actor, first, 'fold').status_code, 200)
        self.assertEqual(PokerRoom.objects.get(pk=second['id']).hand, before)
        self.assertEqual(len(self.client.get('/api/poker/rooms').json()['rooms']), 2)

    def test_team_deletion_requires_escrow_to_be_settled(self):
        room = self.create()
        admin_client = Client(); admin_client.force_login(self.admin)
        path = f'/api/management/teams/{self.team.pk}'
        response = admin_client.delete(path, json.dumps({'confirmation':self.team.code}), content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertTrue(PokerSeat.objects.filter(user=self.users[0]).exists())
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        response = admin_client.delete(path, json.dumps({'confirmation':self.team.code}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)

    def test_cashout_overflow_keeps_escrow_until_wallet_has_capacity(self):
        room = self.create()
        CurrencyBalance.objects.filter(user=self.users[0]).update(balance=2147483647)
        self.assertEqual(self.action(0, room, 'leave').status_code, 409)
        self.assertEqual(PokerSeat.objects.get(user=self.users[0]).stack, 100)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type='poker_cashout').exists())
        CurrencyBalance.objects.filter(user=self.users[0]).update(balance=2147483547)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 2147483647)

    def test_practice_does_not_even_create_a_real_wallet(self):
        CurrencyBalance.objects.filter(user=self.users[0]).delete()
        room = self.create(mode='practice', bot_count=1)
        self.action(0, room, 'ready')
        self.action(0, room, 'leave')
        self.assertFalse(CurrencyBalance.objects.filter(user=self.users[0]).exists())
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_mutations_require_csrf(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.users[0])
        response = self.post(client, '/api/poker/rooms', {'name':'CSRF'})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PokerRoom.objects.exists())

    def test_ready_is_idempotent_and_survives_another_players_update(self):
        room = self.create()
        self.action(1, room, 'join')
        path = '/api/poker/rooms/' + room['id']
        data = {'action':'ready', 'ready':True, 'hand_number':0, 'version':room['version']}
        self.assertEqual(self.post(self.client, path, data).status_code, 200)
        self.assertEqual(self.post(self.client, path, data).status_code, 200)
        self.assertTrue(PokerSeat.objects.get(user=self.users[0]).ready)
        self.assertEqual(self.post(self.clients[1], path, data).status_code, 200)
        self.assertEqual(PokerRoom.objects.get(pk=room['id']).hand_number, 1)
        self.assertEqual(self.post(self.client, path, data).status_code, 409)

    def test_friendly_room_is_public_free_and_never_creates_wallet_income(self):
        self.team.currency_enabled = False; self.team.save()
        CurrencyBalance.objects.filter(user__in=self.users[:2]).delete()
        room = self.create(mode='friendly', max_players=2, buy_in=999999)
        self.assertEqual(room['buy_in'], 1000)
        self.assertEqual(room['big_blind'], 10)
        self.assertEqual(room['mode'], 'friendly')
        listing = self.clients[1].get('/api/poker/rooms').json()
        self.assertEqual(listing['rooms'][0]['id'], room['id'])
        room = self.start(room)
        self.assertTrue(all(not seat['is_bot'] for seat in room['seats']))
        actor = next(i for i,u in enumerate(self.users) if str(u.pk) == room['actor'])
        self.assertEqual(self.action(actor, room, 'all_in').status_code, 200)
        room = self.action(1-actor, room, 'call').json()['room']
        self.assertEqual(room['street'], 'finished')
        self.assertEqual(sum(s['stack'] for s in room['seats']), 2000)
        for index in range(2):
            self.assertEqual(self.action(index, room, 'leave').status_code, 200)
        self.assertFalse(CurrencyBalance.objects.filter(user__in=self.users[:2]).exists())
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_friendly_refill_is_free_and_cannot_be_used_during_a_hand(self):
        room = self.create(mode='friendly', max_players=2)
        PokerSeat.objects.filter(user=self.users[0]).update(stack=0)
        self.assertEqual(self.action(0, room, 'refill').status_code, 200)
        self.assertEqual(PokerSeat.objects.get(user=self.users[0]).stack, 1000)
        self.assertEqual(self.action(0, room, 'refill').status_code, 409)
        room = self.start(room)
        self.assertEqual(self.action(0, room, 'refill').status_code, 409)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_coin_room_defaults_to_ten_and_accepts_two_coin_buyin(self):
        CurrencyBalance.objects.filter(user=self.users[0]).update(balance=10)
        response = self.post(self.client, '/api/poker/rooms', {'name':'低门槛'})
        self.assertEqual(response.status_code, 200, response.content)
        room = response.json()['room']
        self.assertEqual(room['buy_in'], 10)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 0)
        self.action(0, room, 'leave')
        CurrencyBalance.objects.filter(user=self.users[0]).update(balance=2)
        room = self.create(buy_in=2)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 0)
        self.action(0, room, 'leave')
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 2)


class PokerConcurrencyTests(PokerFixtures, TransactionTestCase):
    def concurrent(self, indexes, callback):
        def work(index):
            close_old_connections()
            try:
                return callback(index)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(work, indexes))

    def test_duplicate_creation_charges_once(self):
        # Separate HTTP sessions for the same user, as in two browser tabs.
        second = Client(); second.force_login(self.users[0])
        clients = [self.client, second]
        statuses = self.concurrent([0,1], lambda i: self.post(clients[i], '/api/poker/rooms', {'name':'Concurrent'}).status_code)
        self.assertEqual(sorted(statuses), [200,400])
        self.assertEqual(PokerSeat.objects.filter(user=self.users[0]).count(), 1)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 990)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_buyin').count(), 1)

    def test_last_seat_is_not_overbooked(self):
        room = self.create(max_players=2)
        statuses = self.concurrent([1,2], lambda i: self.post(self.clients[i], '/api/poker/rooms/' + room['id'], {'action':'join'}).status_code)
        self.assertEqual(sorted(statuses), [200,409])
        self.assertEqual(PokerSeat.objects.filter(room_id=room['id']).count(), 2)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_buyin').count(), 2)

    def test_concurrent_cashouts_only_credit_once(self):
        room = self.create()
        second = Client(); second.force_login(self.users[0])
        clients = [self.client, second]
        statuses = self.concurrent([0,1], lambda i: self.post(clients[i], '/api/poker/rooms/' + room['id'], {'action':'leave'}).status_code)
        self.assertEqual(sorted(statuses), [200,409])
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_cashout').count(), 1)
