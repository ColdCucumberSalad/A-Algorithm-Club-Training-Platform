import json
import uuid
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
                     AppAccessToken, AppRateLimit, ProEntitlement, ProRedeemCode, ProAudit)
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

    def post(self, client, path, data=None, token=None, **extra):
        if token:
            extra['HTTP_AUTHORIZATION'] = 'Bearer ' + token
        return client.post(path, json.dumps(data or {}), content_type='application/json', secure=True, **extra)

    def login(self, username='pro-buyer', password='Buyer-Test-987!'):
        response = self.post(Client(), '/api/app/auth/login', {'username': username, 'password': password})
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()['token']

    def issue(self, quantity=1):
        purchase_item(self.member, self.item.pk, quantity)
        units = list(ShopFulfillment.objects.order_by('pk'))[-quantity:]
        codes = []
        for unit in units:
            result = self.post(self.browser, f'/api/currency/inventory/{unit.pk}/redeem')
            self.assertEqual(result.status_code, 200, result.content)
            codes.append(result.json()['code'])
        return codes

    def redeem(self, token, code):
        return self.post(Client(), '/api/app/pro/redeem', {'code': code}, token)

    def manage(self, action, **values):
        row = ProEntitlement.objects.filter(user=self.user, app=APP_KEY).first()
        data = {'action': action, 'reason': 'Test reason', 'request_id': str(uuid.uuid4()),
                'expected_revision': row.revision if row else 0, **values}
        return self.post(self.admin, f'/api/management/accounts/{self.user.pk}/pro', data)


@override_settings(APP_REQUIRE_HTTPS=True)
class AppProTests(ProFixture, TestCase):
    def test_login_contract_and_hashed_revocable_token_without_browser_login(self):
        client = Client(enforce_csrf_checks=True)
        result = self.post(client, '/api/app/auth/login', {'username': self.user.username, 'password': 'Buyer-Test-987!'})
        self.assertEqual(result.status_code, 200, result.content)
        data = result.json()
        self.assertEqual(set(data), {'token', 'token_expires_at', 'user', 'pro'})
        self.assertEqual(data['user'], {'id': self.user.pk, 'username': self.user.username})
        self.assertEqual(set(data['pro']), {'active', 'expires_at', 'server_time'})
        self.assertFalse(data['pro']['active'])
        self.assertIsNone(data['pro']['expires_at'])
        token = AppAccessToken.objects.get(user=self.user)
        self.assertNotEqual(token.token_hash, data['token'])
        self.assertEqual(token.token_hash, fingerprint(data['token']))
        self.assertNotIn('sessionid', result.cookies)
        self.assertNotIn('csrftoken', result.cookies)
        self.assertIn('no-store', result['Cache-Control'])
        info = client.get('/api/app/pro', secure=True, HTTP_AUTHORIZATION='Bearer ' + data['token'])
        self.assertEqual(info.status_code, 200)
        self.assertEqual(set(info.json()), {'active', 'expires_at', 'server_time'})
        self.assertEqual(self.post(client, '/api/app/auth/logout', token=data['token']).status_code, 200)
        self.assertEqual(client.get('/api/app/pro', secure=True, HTTP_AUTHORIZATION='Bearer ' + data['token']).status_code, 401)

    def test_session_never_authorizes_token_endpoints_and_bearer_never_admin(self):
        token = self.login()
        self.assertEqual(self.browser.get('/api/app/pro', secure=True).status_code, 401)
        self.assertEqual(self.post(self.browser, '/api/app/pro/redeem', {'code': 'x'}).status_code, 401)
        self.assertEqual(self.post(self.browser, '/api/app/auth/logout').status_code, 401)
        self.assertEqual(Client().get(f'/api/management/accounts/{self.user.pk}/pro',
            secure=True, HTTP_AUTHORIZATION='Bearer ' + token).status_code, 401)
        # Even a valid administrator session cannot replace the Bearer identity.
        data = self.admin.get('/api/app/pro', secure=True, HTTP_AUTHORIZATION='Bearer ' + token)
        self.assertEqual(data.json()['active'], False)

    def test_csrf_still_required_for_admin_and_shop(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.root)
        path = f'/api/management/accounts/{self.user.pk}/pro'
        data = {'action': 'extend', 'days': 31, 'reason': 'CSRF', 'request_id': str(uuid.uuid4()), 'expected_revision': 0}
        self.assertEqual(self.post(client, path, data).status_code, 403)
        client.get('/api/csrf', secure=True)
        result = self.post(client, path, data, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value,
            HTTP_ORIGIN='https://testserver')
        self.assertEqual(result.status_code, 200, result.content)
        client.force_login(self.user)
        self.assertEqual(self.post(client, '/api/currency/inventory/1/redeem').status_code, 403)

    def test_https_methods_malformed_auth_and_disabled_login(self):
        self.assertEqual(Client().post('/api/app/auth/login', '{}', content_type='application/json').status_code, 403)
        self.assertEqual(Client().get('/api/app/auth/login', secure=True).status_code, 405)
        for header in ('', 'Basic abc', 'Bearer short', 'Bearer ' + 'a' * 64, 'Bearer ' + 'a' * 64 + ' extra'):
            self.assertEqual(Client().get('/api/app/pro', secure=True, HTTP_AUTHORIZATION=header).status_code, 401)
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        result = self.post(Client(), '/api/app/auth/login', {'username': self.user.username, 'password': 'Buyer-Test-987!'})
        self.assertEqual(result.status_code, 401)
        self.assertFalse(AppAccessToken.objects.exists())

    def test_expired_password_changed_disabled_and_closed_accounts_invalidate_tokens(self):
        token = self.login()
        AppAccessToken.objects.filter(user=self.user).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.redeem(token, 'x').status_code, 401)
        token = self.login()
        result = self.admin.patch(f'/api/management/accounts/{self.user.pk}', json.dumps(
            {'account': self.user.username, 'password': 'Changed-Test-654!'}), content_type='application/json')
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(self.redeem(token, 'x').status_code, 401)
        token = self.login(password='Changed-Test-654!')
        self.user.refresh_from_db()
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        self.assertEqual(self.redeem(token, 'x').status_code, 401)
        self.user.is_active = True
        self.user.save(update_fields=['is_active'])
        from .account_views import close_user
        close_user(self.user.pk, self.root)
        self.assertEqual(self.redeem(token, 'x').status_code, 401)
        self.assertFalse(AppAccessToken.objects.filter(user=self.user, revoked_at__isnull=True).exists())

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

    def test_redeem_owner_only_stacks_from_now_or_expiry_and_retry_cannot_restore(self):
        codes = self.issue(3)
        token = self.login()
        other = self.login('pro-other', 'Other-Test-987!')
        self.assertEqual(self.redeem(other, codes[0]).status_code, 400)
        now = datetime(2026, 11, 3, 8, 0, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=now):
            self.assertEqual(self.redeem(token, codes[0]).status_code, 200)
            row = ProEntitlement.objects.get(user=self.user)
            self.assertEqual(row.expires_at, now + timedelta(days=31))
            self.assertEqual(self.redeem(token, codes[0]).status_code, 200)
            self.assertEqual(self.redeem(token, codes[1]).status_code, 200)
            row.refresh_from_db()
            self.assertEqual(row.expires_at, now + timedelta(days=62))
            self.assertEqual(ProAudit.objects.filter(action='redeem').count(), 2)
            self.assertEqual(self.manage('revoke').status_code, 200)
            result = self.redeem(token, codes[0])
            self.assertFalse(result.json()['pro']['active'])
            row.expires_at = now - timedelta(days=20)
            row.save(update_fields=['expires_at'])
            self.assertEqual(self.redeem(token, codes[2]).status_code, 200)
            row.refresh_from_db()
            self.assertEqual(row.expires_at, now + timedelta(days=31))

    def test_overflow_rolls_back_code_entitlement_and_audit(self):
        code = self.issue()[0]
        token = self.login()
        expires = datetime(9999, 12, 25, tzinfo=dt_timezone.utc)
        row = ProEntitlement.objects.create(user=self.user, app=APP_KEY, expires_at=expires)
        result = self.redeem(token, code)
        self.assertEqual(result.status_code, 400, result.content)
        row.refresh_from_db()
        self.assertEqual(row.expires_at, expires)
        self.assertEqual(row.revision, 0)
        self.assertIsNone(ProRedeemCode.objects.get().redeemed_at)
        self.assertFalse(ProAudit.objects.exists())
        self.assertEqual(self.manage('extend', days=31).status_code, 400)
        self.assertFalse(ProAudit.objects.exists())

    def test_admin_revision_replay_expiry_revoke_tokens_and_permissions(self):
        path = f'/api/management/accounts/{self.user.pk}/pro'
        payload = {'action': 'extend', 'days': 31, 'reason': 'Manual correction',
                   'request_id': str(uuid.uuid4()), 'expected_revision': 0}
        self.assertEqual(self.post(self.browser, path, payload).status_code, 403)
        first = self.post(self.admin, path, payload)
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(self.post(self.admin, path, payload).json()['expires_at'], first.json()['expires_at'])
        self.assertEqual(ProAudit.objects.count(), 1)
        self.assertEqual(self.post(self.admin, path, {**payload, 'days': 62}).status_code, 409)
        self.assertEqual(self.post(self.admin, path, {**payload, 'request_id': str(uuid.uuid4())}).status_code, 409)
        result = self.manage('set_expiry', expires_at='2027-02-01T12:30:00+08:00')
        self.assertEqual(result.status_code, 200, result.content)
        self.assertTrue(result.json()['active'])
        self.assertEqual(self.manage('set_expiry', expires_at='2027-02-01T12:30:00').status_code, 400)
        token = self.login()
        self.assertEqual(self.manage('revoke_tokens').status_code, 200)
        self.assertEqual(self.redeem(token, 'x').status_code, 401)
        self.assertEqual(self.manage('revoke').status_code, 200)
        audit = self.admin.get(path).json()['audit']
        self.assertEqual(audit[0]['action'], 'revoke')
        self.assertEqual(audit[0]['actor'], self.root.username)
        self.assertEqual(audit[0]['reason'], 'Test reason')

    def test_login_account_and_ip_limits_cannot_be_bypassed_by_forwarded_headers(self):
        data = {'username': self.user.username, 'password': 'wrong'}
        for i in range(10):
            self.assertEqual(self.post(Client(), '/api/app/auth/login', data, HTTP_X_FORWARDED_FOR=f'10.0.0.{i}').status_code, 401)
        result = self.post(Client(), '/api/app/auth/login', data)
        self.assertEqual(result.status_code, 429)
        self.assertIn('Retry-After', result)
        AppRateLimit.objects.all().delete()
        for i in range(61):
            result = self.post(Client(), '/api/app/auth/login', {'username': f'missing-{i}', 'password': 'wrong'},
                HTTP_X_FORWARDED_FOR=f'10.1.0.{i}')
        self.assertEqual(result.status_code, 429)
        self.assertEqual(AppRateLimit.objects.count(), 2)

    def test_throttle_windows_reset_and_cleanup_preserves_recent_rows_and_audits(self):
        from .app_views import limited
        from .tasks import cleanup_app_credentials
        self.assertFalse(limited('test', 'key', 1, 300))
        self.assertTrue(limited('test', 'key', 1, 300))
        AppRateLimit.objects.update(window_start=timezone.now() - timedelta(seconds=301))
        self.assertFalse(limited('test', 'key', 1, 300))
        AppRateLimit.objects.create(key='old', attempts=1, window_start=timezone.now() - timedelta(days=2))
        token = self.login()
        AppAccessToken.objects.create(user=self.user, token_hash='old', auth_hash='x', expires_at=timezone.now() - timedelta(days=31))
        self.manage('extend', days=31)
        result = cleanup_app_credentials.run()
        self.assertEqual(result, {'rate_limits': 1, 'tokens': 1})
        self.assertTrue(AppAccessToken.objects.filter(token_hash=fingerprint(token)).exists())
        self.assertTrue(ProAudit.objects.exists())

    @override_settings(APP_TRUSTED_PROXY_CIDRS=('172.18.0.0/16',))
    def test_trusted_proxy_real_clients_have_independent_ip_and_unknown_account_buckets(self):
        data = {'username': 'missing-client', 'password': 'wrong'}
        for _ in range(10):
            result = self.post(Client(), '/api/app/auth/login', data,
                REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP='198.51.100.10')
            self.assertEqual(result.status_code, 401)
        self.assertEqual(self.post(Client(), '/api/app/auth/login', data,
            REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP='198.51.100.10').status_code, 429)
        self.assertEqual(self.post(Client(), '/api/app/auth/login', data,
            REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP='198.51.100.11').status_code, 401)
        self.assertEqual(AppRateLimit.objects.count(), 4)

    @override_settings(APP_TRUSTED_PROXY_CIDRS=('172.18.0.0/16',))
    def test_untrusted_peer_cannot_forge_real_ip_or_forwarded_for(self):
        data = {'username': 'random-missing', 'password': 'wrong'}
        for i in range(10):
            self.assertEqual(self.post(Client(), '/api/app/auth/login', data, REMOTE_ADDR='203.0.113.9',
                HTTP_X_REAL_IP=f'198.51.100.{i}', HTTP_X_FORWARDED_FOR=f'192.0.2.{i}').status_code, 401)
        self.assertEqual(self.post(Client(), '/api/app/auth/login', data, REMOTE_ADDR='203.0.113.9',
            HTTP_X_REAL_IP='198.51.100.100', HTTP_X_FORWARDED_FOR='192.0.2.100').status_code, 429)
        self.assertEqual(AppRateLimit.objects.count(), 2)

    @override_settings(APP_TRUSTED_PROXY_CIDRS=('172.18.0.0/16',))
    def test_proxy_header_must_be_one_valid_address_and_known_account_limit_is_global(self):
        from .app_views import client_address
        from django.test import RequestFactory
        factory = RequestFactory()
        for value in ('', 'invalid', '198.51.100.1, 198.51.100.2'):
            request = factory.get('/', REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP=value, HTTP_X_FORWARDED_FOR='198.51.100.9')
            self.assertEqual(client_address(request), '172.18.0.3')
        request = factory.get('/', REMOTE_ADDR='172.18.0.3', HTTP_X_REAL_IP='2001:db8::1')
        self.assertEqual(client_address(request), '2001:db8::1')
        data = {'username': self.user.username, 'password': 'wrong'}
        for i in range(10):
            self.assertEqual(self.post(Client(), '/api/app/auth/login', data, REMOTE_ADDR='172.18.0.3',
                HTTP_X_REAL_IP=f'198.51.100.{i}').status_code, 401)
        self.assertEqual(self.post(Client(), '/api/app/auth/login', data, REMOTE_ADDR='172.18.0.3',
            HTTP_X_REAL_IP='198.51.100.100').status_code, 429)


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
        code, token = self.issue()[0], self.login()
        def redeem():
            result = self.redeem(token, code)
            return result.status_code
        before = timezone.now()
        self.assertEqual(self.parallel([redeem, redeem]), [200, 200])
        self.assertEqual(ProAudit.objects.filter(action='redeem').count(), 1)
        delta = ProEntitlement.objects.get(user=self.user).expires_at - before
        self.assertTrue(timedelta(days=31) <= delta < timedelta(days=31, seconds=15))

    def test_simultaneous_different_codes_keep_both_extensions(self):
        codes, token = self.issue(2), self.login()
        before = timezone.now()
        results = self.parallel([lambda: self.redeem(token, codes[0]).status_code,
                                 lambda: self.redeem(token, codes[1]).status_code])
        self.assertEqual(results, [200, 200])
        self.assertEqual(ProAudit.objects.filter(action='redeem').count(), 2)
        delta = ProEntitlement.objects.get(user=self.user).expires_at - before
        self.assertTrue(timedelta(days=62) <= delta < timedelta(days=62, seconds=15))


class CardOnlyTests(ProFixture, TestCase):
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
