import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .currency_services import purchase_item
from .models import (Team, TeamMembership, CurrencyBalance, ShopItem, ShopFulfillment,
                     AppRateLimit, ProRedeemCode)
from .problem_parser import key_cipher
from .pro_services import APP_KEY, fingerprint


class ProFixture:
    def setUp(self):
        self.root = User.objects.filter(username='admin').first() or User.objects.create_superuser('admin', password='Root-Test-987!')
        self.user = User.objects.create_user('pro-buyer', password='Buyer-Test-987!')
        self.other = User.objects.create_user('pro-other', password='Other-Test-987!')
        self.team = Team.objects.create(name='Pro test', code='PRO-TEST', created_by=self.root, currency_enabled=True)
        self.member = TeamMembership.objects.create(team=self.team, user=self.user, display_name='Buyer')
        TeamMembership.objects.create(team=self.team, user=self.other, display_name='Other')
        CurrencyBalance.objects.create(user=self.user, member=self.member, team=self.team, balance=1000)
        self.item = ShopItem.objects.create(team=self.team, name='Unrelated product name', price=3,
            item_type='redeem_code', card_source='pro', pro_app=APP_KEY, pro_duration_days=31, stock=10)
        self.browser = Client()
        self.browser.force_login(self.user)
        session = self.browser.session
        session['team_id'] = self.team.pk
        session.save()
        self.admin = Client()
        self.admin.force_login(self.root)
        session = self.admin.session
        session['team_id'] = self.team.pk
        session.save()

    def post(self, client, path, data=None, **extra):
        return client.post(path, json.dumps(data or {}), content_type='application/json', secure=True, **extra)

    def issue(self, quantity=1):
        purchase_item(self.member, self.item.pk, quantity)
        units = list(ShopFulfillment.objects.order_by('pk'))[-quantity:]
        codes = []
        for unit in units:
            result = self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem')
            self.assertEqual(result.status_code, 200, result.content)
            codes.append(result.json()['code'])
        return codes

    def verify(self, code):
        return self.post(Client(), '/api/app/cards/verify', {'code': code})

    def confirm(self, code, token):
        return self.post(Client(), '/api/app/cards/confirm', {'code': code, 'activation_token': token})


@override_settings(APP_REQUIRE_HTTPS=True)
class AppProTests(ProFixture, TestCase):
    def test_purchase_claim_is_private_and_idempotent(self):
        with patch('club.shop_fulfillment.http_fetch') as fetch:
            code = self.issue()[0]
            fetch.assert_not_called()
        unit = ShopFulfillment.objects.get()
        card = ProRedeemCode.objects.get()
        self.assertEqual(card.owner_id, self.user.pk)
        self.assertEqual(card.duration_days, 31)
        self.assertEqual(card.code_hash, fingerprint(code))
        self.assertNotIn(code, unit.encrypted_code)
        self.assertEqual(key_cipher().decrypt(unit.encrypted_code.encode()).decode(), code)
        again = self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem')
        self.assertEqual(again.json()['code'], code)
        self.assertTrue(again.json()['duplicate'])
        self.assertEqual(ProRedeemCode.objects.count(), 1)
        self.item.refresh_from_db()
        self.assertEqual(self.item.stock, 9)
        self.browser.force_login(self.other)
        self.assertEqual(self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem').status_code, 404)
        self.assertNotIn(code, self.admin.get(f'/api/management/accounts/{self.user.pk}').content.decode())
        self.assertNotIn(code, self.browser.get('/api/currency/shop/items').content.decode())

    def test_configuration_explicit_and_old_goods_and_zero_stock_untouched(self):
        path = '/api/currency/admin/shop'
        base = {'name': 'Configured', 'price': 2, 'stock': 0, 'item_type': 'redeem_code', 'card_source': 'pro'}
        for values in ({}, {'pro_app': 'other', 'pro_duration_days': 31},
                       {'pro_app': APP_KEY, 'pro_duration_days': True},
                       {'pro_app': APP_KEY, 'pro_duration_days': 0}):
            self.assertEqual(self.post(self.admin, path, {**base, **values}).status_code, 400)
        result = self.post(self.admin, path, {**base, 'pro_app': APP_KEY, 'pro_duration_days': 31})
        self.assertEqual(result.status_code, 200, result.content)
        item = ShopItem.objects.get(pk=result.json()['item_id'])
        self.assertEqual(item.stock, 0)
        with self.assertRaisesMessage(ValueError, '库存不足'):
            purchase_item(self.member, item.pk)
        legacy = ShopItem.objects.create(team=self.team, name='RBC Helper Pro', price=1, item_type='redeem_code')
        self.assertEqual(legacy.card_source, 'inventory')
        self.assertEqual(legacy.pro_app, '')
        self.assertIsNone(legacy.pro_duration_days)

    def test_purchase_snapshot_survives_duration_changes_and_unlisting(self):
        purchase_item(self.member, self.item.pk)
        self.item.pro_duration_days = 62
        self.item.is_active = False
        self.item.save(update_fields=['pro_duration_days', 'is_active'])
        unit = ShopFulfillment.objects.get()
        result = self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem')
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(ProRedeemCode.objects.get().duration_days, 31)
        self.assertEqual(unit.pro_duration_days, 31)


@override_settings(APP_REQUIRE_HTTPS=True)
class AppProConcurrencyTests(ProFixture, TransactionTestCase):
    def parallel(self, operations):
        if connection.vendor != 'postgresql':
            self.skipTest('Requires real PostgreSQL row locks')
        barrier = Barrier(len(operations))
        def run(operation):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return operation()
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))


    def test_simultaneous_claim_returns_one_code(self):
        purchase_item(self.member, self.item.pk)
        unit = ShopFulfillment.objects.get()
        cookies = self.browser.cookies.copy()
        def claim():
            client = Client()
            client.cookies = cookies.copy()
            result = self.post(client, f'/api/currency/inventory/{unit.pk}/redeem')
            return result.status_code, result.json()
        results = self.parallel([claim, claim])
        self.assertTrue(all(status == 200 for status, _ in results), results)
        self.assertEqual(len({data['code'] for _, data in results}), 1)
        self.assertEqual(ProRedeemCode.objects.count(), 1)


    def test_concurrent_verification_reserves_card_only_once(self):
        code = self.issue()[0]
        def verify():
            result = self.verify(code)
            return result.status_code, result.json()
        results = self.parallel([verify, verify])
        self.assertCountEqual([status for status, _ in results], [200, 409])
        success = next(data for status, data in results if status == 200)
        busy = next(data for status, data in results if status == 409)
        self.assertTrue(success['valid'])
        self.assertEqual(busy, {'error': '错误，卡密占用，请稍后重试'})
        self.assertIsNone(ProRedeemCode.objects.get().consumed_at)
        self.assertEqual(self.confirm(code, success['activation_token']).status_code, 200)

    def test_concurrent_confirmation_consumes_once_and_replays_safely(self):
        code = self.issue()[0]
        token = self.verify(code).json()['activation_token']
        results = self.parallel([lambda: self.confirm(code, token).json(),
                                 lambda: self.confirm(code, token).json()])
        self.assertEqual(results, [{'ok': True}, {'ok': True}])
        card = ProRedeemCode.objects.get()
        self.assertIsNotNone(card.consumed_at)
        self.assertFalse(self.verify(code).json()['valid'])



@override_settings(APP_REQUIRE_HTTPS=True)
class CardVerifyTests(ProFixture, TestCase):
    def test_verify_reserves_until_app_receipt_then_consumes(self):
        code = self.issue()[0]
        before_units = list(ShopFulfillment.objects.values())
        result = self.post(Client(enforce_csrf_checks=True), '/api/app/cards/verify', {'code': code})
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['duration_days'], 31)
        self.assertEqual(data['confirmation_timeout_seconds'], 30)
        self.assertEqual(result['Cache-Control'], 'private, no-store')
        self.assertNotIn('sessionid', result.cookies)
        card = ProRedeemCode.objects.get()
        self.assertIsNone(card.consumed_at)
        self.assertEqual(card.activation_token_hash, fingerprint(data['activation_token']))
        self.assertNotIn(data['activation_token'], list(ProRedeemCode.objects.values())[0].values())
        for client in (self.browser, self.admin, Client()):
            retry = self.post(client, '/api/app/cards/verify', {'code': code})
            self.assertEqual(retry.status_code, 409)
            self.assertEqual(retry.json(), {'error': '错误，卡密占用，请稍后重试'})
        receipt = self.post(Client(enforce_csrf_checks=True), '/api/app/cards/confirm',
                            {'code': code, 'activation_token': data['activation_token']})
        self.assertEqual(receipt.json(), {'ok': True})
        card.refresh_from_db()
        self.assertIsNotNone(card.consumed_at)
        consumed = card.consumed_at
        self.assertEqual(self.confirm(code, data['activation_token']).json(), {'ok': True})
        self.assertEqual(ProRedeemCode.objects.get().consumed_at, consumed)
        self.assertEqual(self.verify(code).json(), {'valid': False, 'app': APP_KEY, 'duration_days': None})
        self.assertEqual(list(ShopFulfillment.objects.values()), before_units)
        again = self.post(self.browser, f'/api/currency/inventory/{card.fulfillment_id}/redeem')
        self.assertEqual(again.json()['code'], code)
        self.assertFalse(self.verify(code).json()['valid'])

    def test_timeout_releases_card_and_rejects_late_or_superseded_receipt(self):
        code = self.issue()[0]
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            first = self.verify(code).json()
        self.assertEqual(ProRedeemCode.objects.get().activation_expires_at, now + timedelta(seconds=30))
        with patch('django.utils.timezone.now', return_value=now + timedelta(seconds=29)):
            self.assertEqual(self.verify(code).status_code, 409)
        with patch('django.utils.timezone.now', return_value=now + timedelta(seconds=30)):
            self.assertEqual(self.confirm(code, first['activation_token']).status_code, 409)
            second = self.verify(code).json()
            self.assertTrue(second['valid'])
            self.assertNotEqual(first['activation_token'], second['activation_token'])
            self.assertEqual(self.confirm(code, first['activation_token']).status_code, 409)
            self.assertIsNone(ProRedeemCode.objects.get().consumed_at)
            self.assertEqual(self.confirm(code, second['activation_token']).json(), {'ok': True})

    def test_receipt_before_deadline_consumes_and_other_tokens_do_not(self):
        code = self.issue()[0]
        now = timezone.now()
        with patch('django.utils.timezone.now', return_value=now):
            token = self.verify(code).json()['activation_token']
        with patch('django.utils.timezone.now', return_value=now + timedelta(seconds=29)):
            self.assertEqual(self.confirm(code, '0' * 64).status_code, 409)
            self.assertIsNone(ProRedeemCode.objects.get().consumed_at)
            self.assertEqual(self.confirm(code, token).status_code, 200)
        with patch('django.utils.timezone.now', return_value=now + timedelta(seconds=31)):
            self.assertEqual(self.confirm(code, token).json(), {'ok': True})
            self.assertEqual(self.confirm(code, '0' * 64).status_code, 409)

    def test_receipt_requires_valid_code_token_and_active_fulfillment(self):
        code = self.issue()[0]
        for token in (None, '', 'x', 'G' * 64, 12):
            self.assertEqual(self.confirm(code, token).status_code, 400)
        self.assertEqual(self.confirm(code, '0' * 64).status_code, 409)
        token = self.verify(code).json()['activation_token']
        other = self.issue()[0]
        self.assertEqual(self.confirm(other, token).status_code, 409)
        self.assertEqual(self.confirm('unknown', token).status_code, 409)
        ShopFulfillment.objects.filter(pk=ProRedeemCode.objects.get(code_hash=fingerprint(code)).fulfillment_id).update(status='reclaimed')
        self.assertEqual(self.confirm(code, token).status_code, 409)
        self.assertFalse(ProRedeemCode.objects.filter(consumed_at__isnull=False).exists())

    def test_confirmation_failure_keeps_reservation_retryable(self):
        code = self.issue()[0]
        token = self.verify(code).json()['activation_token']
        for target in ('club.app_views.response', 'club.pro_models.ProRedeemCode.save'):
            with self.subTest(target=target), patch(target, side_effect=RuntimeError('test failure')):
                with self.assertRaises(RuntimeError):
                    self.confirm(code, token)
            self.assertIsNone(ProRedeemCode.objects.get().consumed_at)
        self.assertEqual(self.confirm(code, token).json(), {'ok': True})

    def test_verification_limit_does_not_block_confirmation_retry(self):
        code = self.issue()[0]
        token = self.verify(code).json()['activation_token']
        for _ in range(29):
            self.assertEqual(self.verify('unknown').status_code, 200)
        self.assertEqual(self.verify(code).status_code, 429)
        self.assertEqual(self.confirm(code, token).json(), {'ok': True})
        self.assertEqual(self.confirm(code, token).json(), {'ok': True})

    def test_response_or_database_failure_does_not_consume_card(self):
        code = self.issue()[0]
        for target in ('club.app_views.response', 'club.pro_models.ProRedeemCode.save'):
            with self.subTest(target=target), patch(target, side_effect=RuntimeError('test failure')):
                with self.assertRaises(RuntimeError):
                    self.verify(code)
            card = ProRedeemCode.objects.get()
            self.assertIsNone(card.consumed_at)
            self.assertIsNone(card.activation_expires_at)
            self.assertEqual(card.activation_token_hash, '')
        self.assertTrue(self.verify(code).json()['valid'])

    def test_unknown_card_returns_invalid_with_no_duration(self):
        result = self.verify('RBC-UNKNOWN')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'valid': False, 'app': APP_KEY, 'duration_days': None})
        self.assertFalse(ProRedeemCode.objects.exists())

    def test_snapshot_survives_product_changes_and_account_state(self):
        code = self.issue()[0]
        self.item.pro_duration_days = 62
        self.item.is_active = False
        self.item.save(update_fields=['pro_duration_days', 'is_active'])
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.verify(code).json()['duration_days'], 31)

    def test_unissued_reclaimed_or_wrong_app_cards_are_invalid(self):
        purchase_item(self.member, self.item.pk)
        self.assertFalse(self.verify('RBC-NOT-ISSUED').json()['valid'])
        unit = ShopFulfillment.objects.get()
        result = self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem')
        code = result.json()['code']
        for status in ('ready', 'reclaimed'):
            ShopFulfillment.objects.filter(pk=unit.pk).update(status=status)
            self.assertFalse(self.verify(code).json()['valid'])
        ShopFulfillment.objects.filter(pk=unit.pk).update(status='redeemed')
        ProRedeemCode.objects.update(app='other')
        self.assertFalse(self.verify(code).json()['valid'])
        for days in (0, 36501):
            ProRedeemCode.objects.update(app=APP_KEY, duration_days=days)
            self.assertFalse(self.verify(code).json()['valid'])

    def test_https_methods_and_malformed_requests(self):
        path = '/api/app/cards/verify'
        client = Client()
        self.assertEqual(client.post('/api/app/cards/confirm', '{}', content_type='application/json').status_code, 403)
        self.assertEqual(client.get('/api/app/cards/confirm', secure=True).status_code, 405)
        self.assertEqual(client.post(path, '{}', content_type='application/json').status_code, 403)
        result = client.get(path, secure=True)
        self.assertEqual(result.status_code, 405)
        self.assertEqual(result['Allow'], 'POST')
        for payload in ({}, {'code': ''}, {'code': ' '}, {'code': 123},
                        {'code': None}, {'code': 'x' * 201}):
            self.assertEqual(self.post(client, path, payload).status_code, 400)
        for raw in ('{broken', '[]', 'null'):
            result = client.post(path, raw, content_type='application/json', secure=True)
            self.assertEqual(result.status_code, 400)

    def test_old_endpoints_and_subscription_models_are_removed(self):
        from django.apps import apps
        from django.urls import Resolver404, resolve
        for path in ('/api/app/cards/redeem', '/api/app/auth/login', '/api/app/auth/logout',
                     '/api/app/pro', '/api/app/pro/redeem',
                     f'/api/management/accounts/{self.user.pk}/pro'):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)
        for model in ('ProEntitlement', 'ProAudit', 'AppAccessToken'):
            with self.subTest(model=model), self.assertRaises(LookupError):
                apps.get_model('club', model)

    def test_limit_and_request_driven_expiry(self):
        from .app_views import limited
        AppRateLimit.objects.create(key='stale', attempts=1,
                                    window_start=timezone.now() - timedelta(days=2))
        self.assertFalse(limited('test', 'key', 1, 300))
        self.assertFalse(AppRateLimit.objects.filter(pk='stale').exists())
        self.assertTrue(limited('test', 'key', 1, 300))
        AppRateLimit.objects.update(window_start=timezone.now() - timedelta(seconds=301))
        self.assertFalse(limited('test', 'key', 1, 300))
        for _ in range(30):
            self.assertEqual(self.verify('unknown').status_code, 200)
        result = self.verify('unknown')
        self.assertEqual(result.status_code, 429)
        self.assertEqual(result['Retry-After'], '300')

    @override_settings(APP_TRUSTED_PROXY_CIDRS=('172.18.0.0/16',))
    def test_proxy_ip_is_trusted_only_for_configured_peer(self):
        from django.test import RequestFactory
        from .app_views import client_address
        factory = RequestFactory()
        for value in ('', 'invalid', '198.51.100.1, 198.51.100.2'):
            request = factory.get('/', REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP=value)
            self.assertEqual(client_address(request), '172.18.0.3')
        request = factory.get('/', REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP='2001:db8::1')
        self.assertEqual(client_address(request), '2001:db8::1')
        for i in range(30):
            result = self.post(Client(), '/api/app/cards/verify', {}, REMOTE_ADDR='203.0.113.9',
                               HTTP_X_REAL_IP=f'198.51.100.{i}', HTTP_X_FORWARDED_FOR=f'192.0.2.{i}')
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.post(Client(), '/api/app/cards/verify', {},
                                   REMOTE_ADDR='203.0.113.9').status_code, 429)
        self.assertEqual(self.post(Client(), '/api/app/cards/verify', {}, REMOTE_ADDR='172.18.0.3',
                                   HTTP_X_REAL_IP='198.51.100.10').status_code, 400)
