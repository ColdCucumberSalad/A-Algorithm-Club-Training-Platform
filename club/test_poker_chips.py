from importlib import import_module

from django.apps import apps
from django.test import TestCase, TransactionTestCase

from .models import CurrencyBalance, CurrencyTransaction, PokerChipBalance, PokerRoom, PokerSeat
from . import poker_engine as engine
from . import poker_services as poker
from .test_poker import PokerFixtures
from . import test_poker


class ChipWalletTests(PokerFixtures, TestCase):
    def exchange(self, action, coins):
        return self.post(self.client, '/api/poker/rooms/chips', {'action': action, 'coins': coins})

    def test_buy_withdraw_preserves_remainder_and_records_only_coins(self):
        PokerChipBalance.objects.filter(user=self.users[0]).update(balance=500)
        result = self.exchange('buy', 2)
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json(), {'balance': 998, 'chips': 2500})
        self.assertEqual(self.exchange('withdraw', 2).json(), {'balance': 1000, 'chips': 500})
        self.assertEqual(self.exchange('withdraw', 1).status_code, 400)
        self.assertEqual(list(CurrencyTransaction.objects.order_by('pk').values_list('amount', flat=True)), [-2, 2])
        self.assertEqual(self.client.get('/api/poker/rooms').json()['chips'], 500)

    def test_invalid_insufficient_and_overflow_exchanges_do_not_change_assets(self):
        for value in [True, 0, -1, 1.5, '1', None, 2147483648]:
            self.assertEqual(self.exchange('buy', value).status_code, 400)
        self.assertEqual(self.exchange('unknown', 1).status_code, 400)
        self.assertEqual(self.exchange('buy', 1001).status_code, 400)
        CurrencyBalance.objects.filter(user=self.users[0]).update(balance=2147483647)
        self.assertEqual(self.exchange('withdraw', 1).status_code, 400)
        self.assertEqual(PokerChipBalance.objects.get(user=self.users[0]).balance, 1000)
        self.assertFalse(CurrencyTransaction.objects.exists())

    def test_zero_account_and_disabled_currency(self):
        PokerChipBalance.objects.filter(user=self.users[0]).delete()
        self.assertEqual(self.client.get('/api/poker/rooms').json()['chips'], 0)
        self.assertEqual(self.exchange('buy', 1).json()['chips'], 1000)
        self.team.currency_enabled = False; self.team.save()
        self.assertEqual(self.exchange('buy', 1).status_code, 400)
        self.assertEqual(self.exchange('withdraw', 1).status_code, 200)

    def test_table_chips_cannot_be_withdrawn_and_practice_chips_cannot_be_redeemed(self):
        room = self.create(buy_in=1000)
        self.assertEqual(self.exchange('withdraw', 1).status_code, 400)
        self.assertEqual(self.action(0, room, 'leave').status_code, 200)
        self.assertEqual(self.exchange('withdraw', 1).status_code, 200)
        room = self.create(mode='friendly')
        self.action(0, room, 'leave')
        self.assertEqual(self.exchange('withdraw', 1).status_code, 400)

    def test_both_practice_modes_keep_winnings_and_refills_out_of_redeemable_balance(self):
        for mode in ('friendly', 'practice'):
            with self.subTest(mode=mode):
                PokerChipBalance.objects.filter(user=self.users[0]).update(balance=1500)
                wallet_before = CurrencyBalance.objects.get(user=self.users[0]).balance
                receipts_before = CurrencyTransaction.objects.count()
                room = self.create(mode=mode, bot_count=1)
                self.assertEqual(self.client.get('/api/poker/rooms').json()['chips'], 1500)
                PokerSeat.objects.filter(user=self.users[0]).update(stack=0)
                self.assertEqual(self.action(0, room, 'refill').status_code, 200)
                self.assertEqual(PokerSeat.objects.get(user=self.users[0]).stack, 1000)
                # Include a large winning practice stack and a forged mode on leave.
                PokerSeat.objects.filter(user=self.users[0]).update(stack=250000)
                self.assertEqual(self.action(0, room, 'leave', mode='coins').status_code, 200)
                self.assertEqual(PokerChipBalance.objects.get(user=self.users[0]).balance, 1500)
                self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, wallet_before)
                self.assertEqual(CurrencyTransaction.objects.count(), receipts_before)
                # Only the real 1,500 chips can be redeemed; practice winnings add nothing.
                self.assertEqual(self.exchange('withdraw', 1).status_code, 200)
                self.assertEqual(self.exchange('withdraw', 1).status_code, 400)
                self.assertEqual(PokerChipBalance.objects.get(user=self.users[0]).balance, 500)

    def test_practice_does_not_create_a_redeemable_wallet_or_credit_on_disconnect(self):
        from datetime import timedelta
        from django.utils import timezone
        PokerChipBalance.objects.filter(user=self.users[0]).delete()
        for mode in ('friendly', 'practice'):
            with self.subTest(mode=mode):
                room = self.create(mode=mode, bot_count=1)
                PokerSeat.objects.filter(user=self.users[0]).update(stack=100000,
                    last_seen=timezone.now() - timedelta(minutes=6))
                poker.sweep_room(room['id'])
                self.assertFalse(PokerSeat.objects.filter(user=self.users[0]).exists())
                self.assertFalse(PokerChipBalance.objects.filter(user=self.users[0]).exists())
                self.assertFalse(CurrencyTransaction.objects.exists())
                self.assertEqual(self.exchange('withdraw', 1).status_code, 400)

    def test_formal_coin_room_cannot_claim_practice_refill(self):
        room = self.create(buy_in=1000)
        PokerSeat.objects.filter(user=self.users[0]).update(stack=0)
        self.assertEqual(self.action(0, room, 'refill', mode='friendly').status_code, 409)
        self.assertEqual(PokerSeat.objects.get(user=self.users[0]).stack, 0)
        self.assertEqual(PokerChipBalance.objects.get(user=self.users[0]).balance, 0)

    def test_migration_rollback_only_allows_empty_chip_tables(self):
        from django.db.migrations.exceptions import IrreversibleError
        reverse = import_module('club.migrations.0058_poker_chip_wallet').reverse_empty_tables
        with self.assertRaises(IrreversibleError):
            reverse(apps, None)
        PokerChipBalance.objects.all().delete()
        room = PokerRoom.objects.create(team=self.team, created_by=self.users[0], name='Legacy', mode='coins')
        with self.assertRaises(IrreversibleError):
            reverse(apps, None)
        room.delete()
        reverse(apps, None)

    def test_legacy_active_table_conversion_preserves_coin_value(self):
        room = self.start(self.create())
        row = PokerRoom.objects.get(pk=room['id'])
        before = {uid: p['stack'] + p['total'] for uid, p in row.hand['players'].items()}
        import_module('club.migrations.0058_poker_chip_wallet').convert_existing_tables(apps, None)
        row.refresh_from_db()
        self.assertEqual(row.buy_in, 100000)
        self.assertEqual(row.big_blind, 2000)
        for uid, player in row.hand['players'].items():
            self.assertEqual(player['stack'] + player['total'], before[uid] * 1000)
        engine.act(row.hand, row.hand['actor'], 'fold', None, 0)
        row.save(); poker.persist(row)
        for index in range(2):
            self.assertEqual(self.action(index, room, 'leave').status_code, 200)
        self.assertEqual(sum(PokerChipBalance.objects.values_list('balance', flat=True)), 203800)


class ChipExchangeConcurrencyTests(PokerFixtures, TransactionTestCase):
    concurrent = test_poker.PokerConcurrencyTests.concurrent

    def test_concurrent_withdrawals_cannot_spend_same_chips(self):
        statuses = self.concurrent([0, 1], lambda _: self.post(self.client,
            '/api/poker/rooms/chips', {'action': 'withdraw', 'coins': 1}).status_code)
        self.assertEqual(sorted(statuses), [200, 400])
        self.assertEqual(PokerChipBalance.objects.get(user=self.users[0]).balance, 0)
        self.assertEqual(CurrencyBalance.objects.get(user=self.users[0]).balance, 1001)
        self.assertEqual(CurrencyTransaction.objects.count(), 1)
