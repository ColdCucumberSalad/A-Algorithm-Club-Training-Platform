import json
import uuid
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth.models import User
from .models import Team, TeamMembership, ShopItem, ShopCode, ShopFulfillment, Purchase, CurrencyBalance, CurrencyTransaction, UserInventory
from .currency_services import purchase_item
from .shop_fulfillment import append_codes, available_stock
from .problem_parser import key_cipher


class ShopFulfillmentTests(TestCase):
    def setUp(self):
        self.root = User.objects.get(username='admin')
        self.team = Team.objects.create(name='Delivery', code='FULFILL', created_by=self.root, currency_enabled=True)
        self.other = Team.objects.create(name='Other', code='OTHER-F', created_by=self.root, currency_enabled=True)
        self.user = User.objects.create_user('delivery-owner')
        self.member = TeamMembership.objects.create(team=self.team, user=self.user, display_name='Owner')
        self.balance = CurrencyBalance.objects.create(team=self.team, member=self.member, balance=100)
        self.owner = self.login(self.user, self.team)
        self.admin = self.login(self.root, self.team)
        self.other_user = User.objects.create_user('delivery-outsider')
        TeamMembership.objects.create(team=self.other, user=self.other_user, display_name='Other', role='admin')
        self.outsider = self.login(self.other_user, self.other)

    def login(self, user, team):
        client = Client()
        client.force_login(user)
        session = client.session
        session['team_id'] = team.pk
        session.save()
        return client

    def post(self, client, path, data=None):
        return client.post(path, json.dumps(data or {}), content_type='application/json')

    def item(self, kind='redeem_code', **kwargs):
        return ShopItem.objects.create(team=self.team, name='Gift', price=3, item_type=kind, **kwargs)

    def test_reserved_stock_then_private_idempotent_redemption(self):
        item = self.item()
        append_codes(item, ['CODE-A', 'CODE-B', 'CODE-A'])
        self.assertEqual(item.card_codes.count(), 2)
        token = str(uuid.uuid4())
        purchase_item(self.member, item.pk, 2, token)
        purchase_item(self.member, item.pk, 2, token)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.balance, 94)
        self.assertEqual(ShopFulfillment.objects.count(), 2)
        self.assertEqual(Purchase.objects.count(), 1)
        self.assertEqual(available_stock(item), 0)
        self.assertEqual(ShopCode.objects.filter(consumed_at__isnull=False).count(), 0)
        before = self.owner.get('/api/currency/inventory').json()['inventory']
        self.assertEqual(len(before), 2)
        self.assertTrue(all(row['code'] is None for row in before))
        unit = ShopFulfillment.objects.order_by('pk').first()
        path = f'/api/currency/inventory/{unit.pk}/redeem'
        self.assertEqual(self.post(self.outsider, path).status_code, 404)
        first = self.post(self.owner, path)
        again = self.post(self.owner, path)
        self.assertEqual(first.status_code, 200)
        self.assertIn(first.json()['code'], ['CODE-A', 'CODE-B'])
        self.assertEqual(again.json()['code'], first.json()['code'])
        self.assertTrue(again.json()['duplicate'])
        self.assertIn('no-store', first['Cache-Control'])
        self.assertEqual(ShopCode.objects.filter(consumed_at__isnull=False).count(), 1)
        self.assertNotIn('CODE-', ShopCode.objects.first().encrypted_value)
        self.assertEqual(self.outsider.get('/api/currency/inventory').json()['inventory'], [])
        self.assertNotIn('CODE-', self.owner.get('/api/currency/shop/items').content.decode())

    def test_insufficient_codes_roll_back_purchase_and_balance(self):
        item = self.item()
        append_codes(item, ['SINGLE'])
        with self.assertRaisesMessage(ValueError, '卡密库存不足'):
            purchase_item(self.member, item.pk, 2)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.balance, 100)
        self.assertEqual(Purchase.objects.count(), 0)
        self.assertEqual(CurrencyTransaction.objects.count(), 0)
        self.assertEqual(available_stock(item), 1)

    def test_api_failure_does_not_consume_and_retry_uses_stable_key(self):
        config = {'url': 'https://cards.example.org/issue', 'method': 'POST', 'body': {}, 'response_path': 'data.code'}
        item = self.item(card_source='api', encrypted_card_api=key_cipher().encrypt(json.dumps(config).encode()).decode())
        purchase_item(self.member, item.pk)
        unit = ShopFulfillment.objects.get()
        path = f'/api/currency/inventory/{unit.pk}/redeem'
        with patch('club.shop_fulfillment.http_fetch', side_effect=TimeoutError) as fetch:
            failed = self.post(self.owner, path)
            first_key = fetch.call_args.kwargs['headers']['Idempotency-Key']
        self.assertEqual(failed.status_code, 502)
        unit.refresh_from_db()
        self.assertEqual(unit.status, 'ready')
        self.assertEqual(unit.encrypted_code, '')
        with patch('club.shop_fulfillment.http_fetch', return_value='{"data":{"code":"API-SECRET"}}') as fetch:
            success = self.post(self.owner, path)
            self.assertEqual(fetch.call_args.kwargs['headers']['Idempotency-Key'], first_key)
            self.assertEqual(fetch.call_args.kwargs['redirects'], 0)
            self.assertTrue(fetch.call_args.kwargs['public_only'])
        self.assertEqual(success.json()['code'], 'API-SECRET')
        with patch('club.shop_fulfillment.http_fetch') as fetch:
            self.assertEqual(self.post(self.owner, path).json()['code'], 'API-SECRET')
            fetch.assert_not_called()
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.balance, 97)

    def test_physical_dispatch_notification_and_team_scoping(self):
        item = self.item('physical')
        purchase_item(self.member, item.pk)
        unit = ShopFulfillment.objects.get()
        self.assertEqual(unit.status, 'dispatching')
        self.assertEqual(self.owner.get('/api/currency/admin/dispatch').status_code, 403)
        self.assertEqual(self.outsider.get('/api/currency/admin/dispatch').json()['pending_count'], 0)
        self.assertEqual(self.post(self.outsider, '/api/currency/admin/dispatch', {'id': unit.pk}).status_code, 404)
        inbox = self.admin.get('/api/currency/admin/dispatch').json()
        self.assertEqual(inbox['pending_count'], 1)
        self.assertEqual(inbox['orders'][0]['item_name'], 'Gift')
        self.assertEqual(self.post(self.admin, '/api/currency/admin/dispatch', {'id': unit.pk}).status_code, 200)
        self.assertTrue(self.post(self.admin, '/api/currency/admin/dispatch', {'id': unit.pk}).json()['duplicate'])
        row = self.owner.get('/api/currency/inventory').json()['inventory'][0]
        self.assertEqual(row['status'], 'delivered')
        self.assertFalse(row['can_redeem'])
        self.assertEqual(self.admin.get('/api/currency/admin/dispatch').json()['pending_count'], 0)

    def test_old_tickets_unchanged_and_unlimited(self):
        item = self.item('makeup_ticket')
        purchase_item(self.member, item.pk, 2)
        self.assertEqual(UserInventory.objects.get(item=item).quantity, 2)
        self.assertEqual(ShopFulfillment.objects.count(), 0)
        self.assertEqual(available_stock(item), -1)

    def test_admin_card_setup_append_only_and_no_secret_echo(self):
        data = {'name': 'Cards', 'price': 2, 'stock': -1, 'item_type': 'redeem_code', 'card_source': 'inventory', 'card_codes': 'A\nB\nA'}
        result = self.post(self.admin, '/api/currency/admin/shop', data)
        self.assertEqual(result.status_code, 200)
        item = ShopItem.objects.get(pk=result.json()['item_id'])
        self.assertEqual(item.card_codes.count(), 2)
        purchase_item(self.member, item.pk)
        updated = self.admin.put('/api/currency/admin/shop', json.dumps({'item_id': item.pk, 'card_codes': 'B\nC'}), content_type='application/json')
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(item.card_codes.count(), 3)
        self.assertEqual(item.card_codes.filter(reserved_for__isnull=False).count(), 1)
        self.assertEqual(self.admin.put('/api/currency/admin/shop', json.dumps({'item_id': item.pk, 'card_source': 'api'}), content_type='application/json').status_code, 400)
        self.assertEqual(self.owner.get('/api/currency/admin/shop').status_code, 403)

    def test_api_configuration_rejects_private_endpoint(self):
        data = {'name': 'API Cards', 'price': 2, 'stock': -1, 'item_type': 'redeem_code', 'card_source': 'api',
                'card_api': {'url': 'https://127.0.0.1/cards'}}
        self.assertEqual(self.post(self.admin, '/api/currency/admin/shop', data).status_code, 400)
        self.assertFalse(ShopItem.objects.exists())

    def api_item(self, **kwargs):
        config = {'url': 'https://cards.example.org/issue?token=public&num=999',
                  'method': 'POST', 'body': {'product': 'coupon', 'num': 999}, 'response_path': 'data.code'}
        return self.item(card_source='api', encrypted_card_api=key_cipher().encrypt(json.dumps(config).encode()).decode(), **kwargs)

    def test_api_multi_purchase_freezes_num_and_redeems_one_code_idempotently(self):
        item = self.api_item(allow_multiple_purchase=True, stock=10)
        token = str(uuid.uuid4())
        purchase_item(self.member, item.pk, 4, token)
        self.assertTrue(purchase_item(self.member, item.pk, 4, token)['duplicate'])
        unit = ShopFulfillment.objects.get()
        self.assertEqual(unit.api_num, 4)
        self.balance.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual((self.balance.balance, item.stock), (88, 6))
        self.assertEqual(self.owner.get('/api/currency/inventory').json()['inventory'][0]['api_num'], 4)
        item.allow_multiple_purchase = False
        item.save()
        path = f'/api/currency/inventory/{unit.pk}/redeem'
        with patch('club.shop_fulfillment.http_fetch', side_effect=TimeoutError) as fetch:
            self.assertEqual(self.post(self.owner, path).status_code, 502)
            first_key = fetch.call_args.kwargs['headers']['Idempotency-Key']
            self.assertEqual(json.loads(fetch.call_args.kwargs['payload']), {'product': 'coupon', 'num': 4})
        with patch('club.shop_fulfillment.http_fetch', return_value='{"data":{"code":"FOUR-USES"}}') as fetch:
            self.assertEqual(self.post(self.owner, path).json()['code'], 'FOUR-USES')
            self.assertEqual(json.loads(fetch.call_args.kwargs['payload'])['num'], 4)
            self.assertEqual(fetch.call_args.kwargs['headers']['Idempotency-Key'], first_key)
        with patch('club.shop_fulfillment.http_fetch') as fetch:
            self.assertTrue(self.post(self.owner, path).json()['duplicate'])
            fetch.assert_not_called()

    def test_api_multi_get_uses_one_num_query_and_preserves_existing_parameters(self):
        from urllib.parse import parse_qs, urlsplit
        item = self.api_item(allow_multiple_purchase=True)
        config = json.loads(key_cipher().decrypt(item.encrypted_card_api.encode()).decode())
        config['method'] = 'GET'
        item.encrypted_card_api = key_cipher().encrypt(json.dumps(config).encode()).decode()
        item.save()
        purchase_item(self.member, item.pk, 3)
        with patch('club.shop_fulfillment.http_fetch', return_value='{"data":{"code":"GET-CARD"}}') as fetch:
            self.assertEqual(self.post(self.owner, f'/api/currency/inventory/{ShopFulfillment.objects.get().pk}/redeem').status_code, 200)
            self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query), {'token': ['public'], 'num': ['3']})
            self.assertIsNone(fetch.call_args.kwargs['payload'])

    def test_api_multi_disabled_and_invalid_quantities_cannot_spend(self):
        item = self.api_item()
        for quantity in (2, 0, -1, 1.5, True, '2', 101):
            with self.assertRaises(ValueError):
                purchase_item(self.member, item.pk, quantity)
        self.balance.refresh_from_db()
        self.assertEqual(self.balance.balance, 100)
        self.assertFalse(Purchase.objects.exists())
        item.allow_multiple_purchase = True
        item.stock = 2
        item.save()
        with self.assertRaisesMessage(ValueError, '库存不足'):
            purchase_item(self.member, item.pk, 3)
        purchase_item(self.member, item.pk, 1)
        self.assertEqual(ShopFulfillment.objects.get().api_num, 1)

    def test_api_multi_admin_validation_and_public_visibility(self):
        from .shop_fulfillment import validate_card_settings
        item = self.api_item()
        for invalid in ('true', 1, None):
            with self.assertRaisesMessage(ValueError, '开关格式无效'):
                validate_card_settings(item, {'allow_multiple_purchase': invalid}, 'redeem_code')
        with self.assertRaisesMessage(ValueError, '仅 API 类'):
            validate_card_settings(item, {'allow_multiple_purchase': True}, 'physical')
        response = self.admin.put('/api/currency/admin/shop', json.dumps({
            'item_id': item.pk, 'allow_multiple_purchase': True}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(self.admin.get('/api/currency/admin/shop').json()['items'][0]['allow_multiple_purchase'])
        public = self.owner.get('/api/currency/shop/items').json()['items'][0]
        self.assertTrue(public['allow_multiple_purchase'])
        self.assertNotIn('encrypted_card_api', public)
        self.assertNotIn('card_api', public)
