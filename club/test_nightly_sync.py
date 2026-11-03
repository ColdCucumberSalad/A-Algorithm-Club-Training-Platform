from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase
from django.utils import timezone
from django.db import connection
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
