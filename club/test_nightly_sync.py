import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from django.test import Client, TestCase, TransactionTestCase
from django.utils import timezone
from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext
from . import test_community as fixtures
from .models import PlatformBinding, PlatformSolvedRecord
from .tasks import sync_bound_accounts_nightly
from .platform_records import store


class NightlySyncTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.binding = PlatformBinding.objects.create(user=self.author, platform='codeforces',
            account='nightly', status='ready', synced_at=timezone.now()-timedelta(days=2),
            sync_state={'version': 2, 'complete': True, 'cursor': 123})

    @patch('club.tasks.sync_bound_accounts_nightly.apply_async')
    @patch('club.platform_account_views.enqueue')
    def test_dispatch_once_preserves_incremental_cursor(self, enqueue, again):
        with self.captureOnCommitCallbacks(execute=True):
            result = sync_bound_accounts_nightly()
        self.assertEqual(result['status'], 'started')
        self.binding.refresh_from_db()
        self.assertFalse(self.binding.sync_state['full'])
        self.assertEqual(self.binding.sync_state['cursor'], 123)
        enqueue.assert_called_once()
        self.assertEqual(again.call_args.kwargs['countdown'], 30)
        self.binding.status = 'ready'
        self.binding.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')

    def test_recent_failed_and_inactive_accounts_are_skipped(self):
        self.binding.synced_at = timezone.now()
        self.binding.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')
        self.binding.synced_at = None
        self.binding.status = 'failed'
        self.binding.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')
        self.binding.status = 'ready'
        self.binding.save()
        self.author.is_active = False
        self.author.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')

    def test_pending_waits_and_stale_pending_fails_without_erasing_snapshot(self):
        self.binding.status = 'pending'
        self.binding.snapshot = {'solved': 10}
        self.binding.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'waiting')
        self.binding.requested_at = timezone.now()-timedelta(hours=1)
        self.binding.save()
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.status, 'failed')
        self.assertEqual(self.binding.snapshot, {'solved': 10})

    def test_expired_chain_stops(self):
        self.assertEqual(sync_bound_accounts_nightly('2000-01-01')['status'], 'expired')

    def test_unchanged_records_do_not_write(self):
        row = {'problem_key':'1:a', 'solved_on':None, 'title':'A', 'url':''}
        store(self.binding, [row])
        with CaptureQueriesContext(connection) as queries:
            store(self.binding, [row])
        self.assertFalse(any(q['sql'].lstrip().upper().startswith(('INSERT', 'UPDATE')) for q in queries))
        store(self.binding, [dict(row, title='Updated')])
        self.assertEqual(PlatformSolvedRecord.objects.get(binding=self.binding).title, 'Updated')


    @patch('club.profile_views.lock_active_member', return_value=None)
    def test_membership_rechecked_before_dispatch(self, guard):
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')
        guard.assert_called_once()
        self.binding.refresh_from_db()
        self.assertEqual(self.binding.status, 'ready')

    def test_no_active_team_is_skipped(self):
        self.author.team_memberships.update(is_active=False)
        self.assertEqual(sync_bound_accounts_nightly()['status'], 'complete')


class NightlySyncLockTests(TransactionTestCase):
    setUp = fixtures.CommunityTests.setUp

    @patch('club.tasks.sync_bound_accounts_nightly.apply_async')
    @patch('club.platform_account_views.enqueue')
    def test_timeout_lock_is_released_before_dispatcher_takes_user_lock(self, enqueue, again):
        from .profile_views import lock_active_member
        stale = PlatformBinding.objects.create(user=self.author, platform='codeforces',
            account='stale', status='pending', requested_at=timezone.now()-timedelta(hours=1))
        ready = PlatformBinding.objects.create(user=self.author, platform='nowcoder',
            account='123', status='ready', synced_at=timezone.now()-timedelta(days=2))

        def manual_retry():
            close_old_connections()
            try:
                client = Client()
                client.force_login(self.author)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '2s'")
                return client.post('/api/profile/platform-accounts/sync',
                    json.dumps({'ids': [stale.pk]}), content_type='application/json').status_code
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            def retry_before_user_lock(user_id, member_id):
                # The dispatcher has already updated the stale row. A real manual
                # request on another connection must now be able to lock that row.
                self.assertEqual(pool.submit(manual_retry).result(timeout=10), 202)
                return lock_active_member(user_id, member_id)

            with patch('club.profile_views.lock_active_member', side_effect=retry_before_user_lock) as guard:
                result = sync_bound_accounts_nightly()

        guard.assert_called_once()
        self.assertEqual(result, {'status': 'started', 'binding_id': ready.pk})
        stale.refresh_from_db()
        ready.refresh_from_db()
        self.assertEqual((stale.status, ready.status), ('pending', 'pending'))
        self.assertEqual(enqueue.call_count, 2)
        again.assert_called_once()
