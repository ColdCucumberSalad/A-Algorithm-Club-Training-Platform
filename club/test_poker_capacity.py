from django.contrib.auth.models import User
from django.test import TestCase, TransactionTestCase

from .models import CurrencyBalance, CurrencyTransaction, PokerRoom, PokerSeat, TeamMembership
from . import poker_services as poker
from .test_poker import PokerFixtures
from . import test_poker


class CapacityFixtures(PokerFixtures):
    def fill(self, count):
        for index in range(count):
            user = User.objects.create_user(f'capacity-player-{index}')
            member = TeamMembership.objects.create(user=user, team=self.other, display_name=f'Capacity {index}')
            room = PokerRoom.objects.create(team=self.other, created_by=user, name=f'Other {index}',
                                           mode=('coins', 'friendly', 'practice')[index % 3])
            PokerSeat.objects.create(room=room, user=user, member=member, number=0, stack=1000)


class PokerCapacityTests(CapacityFixtures, TestCase):
    def test_all_modes_share_global_limit_and_failed_creation_leaves_no_room_or_charge(self):
        self.fill(10)
        for mode in ('coins', 'friendly', 'practice'):
            response = self.post(self.client, '/api/poker/rooms', {'name':'Full', 'mode':mode})
            self.assertEqual(response.status_code, 400)
            self.assertIn('10 人上限', response.json()['error'])
        self.assertEqual(PokerRoom.objects.count(), 10)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_full_site_rejects_join_without_debiting_wallet(self):
        room = self.create()
        self.fill(9)
        response = self.post(self.clients[1], '/api/poker/rooms/'+room['id'], {'action':'join'})
        self.assertEqual(response.status_code, 409)
        self.assertIn('10 人上限', response.json()['error'])
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[1]).balance, 1000)
        self.assertEqual(PokerSeat.objects.filter(user=self.users[1]).count(), 0)

    def test_existing_player_can_resume_and_leave_at_capacity_then_new_player_can_join(self):
        room = self.create(mode='friendly')
        self.fill(9)
        self.assertEqual(self.action(0, room, 'join').status_code, 200)
        self.assertEqual(self.action(0, room, 'ready').status_code, 200)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertEqual(poker.capacity()['available'], 1)
        response = self.post(self.clients[1], '/api/poker/rooms', {'name':'New', 'mode':'friendly'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(poker.capacity()['players'], 10)

    def test_bots_do_not_take_human_slots_and_lobby_reports_capacity(self):
        self.fill(9)
        self.create(mode='practice', bot_count=5)
        self.assertEqual(PokerSeat.objects.count(), 15)
        self.assertEqual(self.client.get('/api/poker/rooms').json()['capacity'],
                         {'players':10, 'limit':10, 'available':0})

    def test_pending_leave_keeps_slot_until_hand_settles(self):
        room = self.start(self.create(), players=3)
        self.fill(7)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertTrue(PokerSeat.objects.get(user=self.users[0]).leaving)
        self.assertEqual(poker.capacity()['players'], 10)
        response = self.post(self.clients[3], '/api/poker/rooms', {'name':'Waiting', 'mode':'friendly'})
        self.assertEqual(response.status_code, 400)


class PokerCapacityConcurrencyTests(CapacityFixtures, TransactionTestCase):
    concurrent = test_poker.PokerConcurrencyTests.concurrent

    def test_two_different_rooms_compete_for_last_global_slot(self):
        first = self.create()
        response = self.post(self.clients[3], '/api/poker/rooms', {'name':'Second', 'buy_in':100})
        self.assertEqual(response.status_code, 200)
        second = response.json()['room']
        self.fill(7)
        targets = {1:first['id'], 2:second['id']}
        statuses = self.concurrent([1,2], lambda i:self.post(self.clients[i], '/api/poker/rooms/'+targets[i], {'action':'join'}).status_code)
        self.assertEqual(sorted(statuses), [200,409])
        self.assertEqual(poker.capacity()['players'], 10)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='poker_buyin').count(), 0)

    def test_two_teams_cannot_create_past_last_global_slot(self):
        TeamMembership.objects.create(team=self.other, user=self.users[2], display_name='Other team')
        session = self.clients[2].session
        session['team_id'] = self.other.pk
        session.save()
        self.fill(9)
        statuses = self.concurrent([1,2], lambda i:self.post(self.clients[i], '/api/poker/rooms', {'name':'Concurrent', 'mode':'friendly'}).status_code)
        self.assertEqual(sorted(statuses), [200,400])
        self.assertEqual(poker.capacity()['players'], 10)
        self.assertEqual(PokerRoom.objects.count(), 10)
