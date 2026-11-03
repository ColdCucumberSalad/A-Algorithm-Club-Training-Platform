import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone as dt_timezone
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .currency_services import purchase_item
from .models import (Team, TeamMembership, CurrencyBalance, ShopItem, ShopFulfillment,
                     AppRateLimit, ProEntitlement, ProRedeemCode)
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

    def redeem(self, code, device='a' * 64):
        return self.post(Client(), '/api/app/cards/redeem', {'code': code, 'device_secret': device})


@override_settings(APP_REQUIRE_HTTPS=True)
class AppProTests(ProFixture, TestCase):
    def test_purchase_claim_is_private_idempotent_and_does_not_start_pro(self):
        with patch('club.shop_fulfillment.http_fetch') as fetch:
            code = self.issue()[0]
            fetch.assert_not_called()
        unit = ShopFulfillment.objects.get()
        card = ProRedeemCode.objects.get()
        self.assertEqual(card.owner_id, self.user.pk)
        self.assertEqual(card.duration_days, 31)
        self.assertEqual(card.code_hash, fingerprint(code))
        self.assertIsNone(card.redeemed_at)
        self.assertFalse(ProEntitlement.objects.exists())
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

    def test_simultaneous_same_code_only_adds_once(self):
        code = self.issue()[0]
        def redeem():
            result = self.redeem(code)
            return result.status_code
        before = timezone.now()
        self.assertEqual(self.parallel([redeem, redeem]), [200, 200])
        self.assertEqual(ProRedeemCode.objects.filter(redeemed_at__isnull=False).count(), 1)
        delta = ProEntitlement.objects.get(user=self.user).expires_at - before
        self.assertTrue(timedelta(days=31) <= delta < timedelta(days=31, seconds=15))

    def test_simultaneous_different_codes_keep_both_extensions(self):
        codes = self.issue(2)
        before = timezone.now()
        results = self.parallel([lambda: self.redeem(codes[0]).status_code,
                                 lambda: self.redeem(codes[1]).status_code])
        self.assertEqual(results, [200, 200])
        self.assertEqual(ProRedeemCode.objects.filter(redeemed_at__isnull=False).count(), 2)
        delta = ProEntitlement.objects.get(user=self.user).expires_at - before
        self.assertTrue(timedelta(days=62) <= delta < timedelta(days=62, seconds=15))


@override_settings(APP_REQUIRE_HTTPS=True)
class CardOnlyTests(ProFixture, TestCase):
    def test_only_card_endpoint_remains(self):
        from django.urls import Resolver404, resolve
        for path in ('/api/app/auth/login', '/api/app/auth/logout', '/api/app/pro',
                     '/api/app/pro/redeem', f'/api/management/accounts/{self.user.pk}/pro'):
            with self.subTest(path=path), self.assertRaises(Resolver404):
                resolve(path)
        data = self.admin.get(f'/api/management/accounts/{self.user.pk}').json()
        self.assertNotIn('pro', data)

    def test_https_method_validation_and_no_session_required(self):
        path = '/api/app/cards/redeem'
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(path, '{}', content_type='application/json').status_code, 403)
        result = client.get(path, secure=True)
        self.assertEqual(result.status_code, 405)
        self.assertEqual(result['Allow'], 'POST')
        for payload in ({}, {'code': 'x', 'device_secret': 'a' * 63},
                        {'code': 'x', 'device_secret': 'G' * 64},
                        {'code': 123, 'device_secret': 'a' * 64}):
            self.assertEqual(self.post(client, path, payload).status_code, 400)
        code = self.issue()[0]
        result = self.post(client, path, {'code': code, 'device_secret': 'a' * 64})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result['Cache-Control'], 'private, no-store')
        self.assertNotIn('sessionid', result.cookies)

    def test_stacking_retry_and_expired_entitlement(self):
        codes = self.issue(3)
        now = datetime(2026, 11, 3, 8, 0, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=now):
            self.assertEqual(self.redeem(codes[0]).status_code, 200)
            first = ProEntitlement.objects.get(user=self.user)
            self.assertEqual(first.expires_at, now + timedelta(days=31))
            self.assertEqual(self.redeem(codes[0]).status_code, 200)
            self.assertEqual(self.redeem(codes[1]).status_code, 200)
            first.refresh_from_db()
            self.assertEqual(first.expires_at, now + timedelta(days=62))
            first.expires_at = now - timedelta(days=1)
            first.save(update_fields=['expires_at'])
            retry = self.redeem(codes[0])
            self.assertFalse(retry.json()['pro']['active'])
            self.assertEqual(self.redeem(codes[2]).status_code, 200)
            first.refresh_from_db()
            self.assertEqual(first.expires_at, now + timedelta(days=31))

    def test_overflow_does_not_consume_card_or_bind_device(self):
        code = self.issue()[0]
        expires = datetime(9999, 12, 25, tzinfo=dt_timezone.utc)
        row = ProEntitlement.objects.create(user=self.user, app=APP_KEY, expires_at=expires)
        result = self.redeem(code)
        self.assertEqual(result.status_code, 400, result.content)
        row.refresh_from_db()
        self.assertEqual(row.expires_at, expires)
        card = ProRedeemCode.objects.get()
        self.assertIsNone(card.redeemed_at)
        self.assertEqual(card.device_hash, '')

    def test_same_device_requires_same_purchase_account(self):
        first = self.issue()[0]
        self.assertEqual(self.redeem(first).status_code, 200)
        self.member = self.team.memberships.get(user=self.other)
        CurrencyBalance.objects.create(user=self.other, member=self.member, team=self.team, balance=100)
        self.browser.force_login(self.other)
        second = self.issue()[0]
        self.assertEqual(self.redeem(second).status_code, 409)
        self.assertEqual(self.redeem(second, 'b' * 64).status_code, 200)

    def test_disabled_account_cannot_verify(self):
        code = self.issue()[0]
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.redeem(code).status_code, 400)
        self.assertFalse(ProEntitlement.objects.exists())

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
            self.assertEqual(self.redeem('unknown').status_code, 400)
        result = self.redeem('unknown')
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
            result = self.post(Client(), '/api/app/cards/redeem', {}, REMOTE_ADDR='203.0.113.9',
                               HTTP_X_REAL_IP=f'198.51.100.{i}', HTTP_X_FORWARDED_FOR=f'192.0.2.{i}')
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.post(Client(), '/api/app/cards/redeem', {},
                                   REMOTE_ADDR='203.0.113.9').status_code, 429)
        self.assertEqual(self.post(Client(), '/api/app/cards/redeem', {}, REMOTE_ADDR='172.18.0.3',
                                   HTTP_X_REAL_IP='198.51.100.10').status_code, 400)

    def test_anonymous_card_claim_retry_and_device_binding(self):
        code = self.issue()[0]
        data = {'code': code, 'device_secret': 'a' * 64}
        first = self.post(Client(), '/api/app/cards/redeem', data)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertTrue(first.json()['user']['id'].startswith('card:'))
        expiry = first.json()['pro']['expires_at']
        repeat = self.post(Client(), '/api/app/cards/redeem', data)
        self.assertEqual(repeat.json()['pro']['expires_at'], expiry)
        data['device_secret'] = 'b' * 64
        self.assertEqual(self.post(Client(), '/api/app/cards/redeem', data).status_code, 409)

    def test_invalid_card_never_grants(self):
        self.assertEqual(self.post(Client(), '/api/app/cards/redeem', {'code': 'unknown', 'device_secret': 'a'*64}).status_code, 400)
        self.assertFalse(ProEntitlement.objects.exists())
