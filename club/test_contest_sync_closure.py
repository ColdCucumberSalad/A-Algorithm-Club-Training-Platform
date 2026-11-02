from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TransactionTestCase
from django.utils import timezone

from . import test_community as fixtures
from . import contest_progress_views
from .account_views import close_user
from .models import ContestParticipation,ContestProblemProgress,ContestSyncState,PlatformBinding
from .tasks import discover_contest_progress,hydrate_contest_progress


class ContestSyncClosureTests(TransactionTestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.binding=PlatformBinding.objects.create(user=self.author,platform='codeforces',account='private_handle')
        self.state=ContestSyncState.objects.create(user=self.author,status='pending',
            requested_at=timezone.now(),remaining=1,total=1,messages={'private_handle':'old message'})
        self.token=str(self.state.token)
        self.contest=ContestParticipation.objects.create(user=self.author,platform='codeforces',account='private_handle',
            contest_key='existing',title='Existing contest',starts_at=timezone.now()-timedelta(hours=2),
            ends_at=timezone.now(),source_data={'account':'private_handle'},detail_complete=True,sync_error='private_handle error')
        self.proof=ContestProblemProgress.objects.create(participation=self.contest,problem_key='A',label='A',
            title='Verified proof',accepted=True,official_ac=True,accepted_at=timezone.now())

    def discovered_rows(self,*args):
        return [{'contest_key':'new-contest','title':'New contest','url':'https://codeforces.com/contest/999',
            'starts_at':timezone.now()-timedelta(hours=2),'ends_at':timezone.now(),
            'source_data':{'account':'private_handle'}}]

    def close_in_thread(self,started=None,finished=None):
        close_old_connections()
        try:
            if started:started.set()
            return close_user(self.author.pk,self.author)
        finally:
            if finished:finished.set()
            close_old_connections()

    def run_task(self,task,*args):
        close_old_connections()
        try:return task(*args)
        finally:close_old_connections()

    def assert_cancelled_and_anonymized(self):
        self.state.refresh_from_db()
        self.assertNotEqual(str(self.state.token),self.token)
        self.assertEqual((self.state.status,self.state.remaining,self.state.total,self.state.messages),('cancelled',0,0,{}))
        self.assertIsNotNone(self.state.finished_at)
        for row in ContestParticipation.objects.filter(user=self.author):
            self.assertTrue(row.account.startswith('closed:'))
            self.assertEqual((row.source_data,row.sync_error),({},''))
        self.proof.refresh_from_db();self.assertTrue(self.proof.accepted);self.assertTrue(self.proof.official_ac)

    def network_overlaps_closure(self,task,args,source_name,result):
        fetching,release=Event(),Event()
        def fetch(*args):
            fetching.set()
            self.assertTrue(release.wait(10),'Network operation was not released')
            return result()
        with patch('club.contest_progress_sources.Remote'),patch(source_name,side_effect=fetch), \
                patch('club.tasks.enqueue_hydration') as enqueue:
            with ThreadPoolExecutor(max_workers=2) as pool:
                job=pool.submit(self.run_task,task,*args)
                try:
                    self.assertTrue(fetching.wait(10),'Task did not start fetching')
                    closed=pool.submit(self.close_in_thread)
                    self.assertTrue(closed.result(timeout=5),'Closure did not commit while network call was outside locks')
                finally:release.set()
                job.result(timeout=10)
            enqueue.assert_not_called()
        self.assert_cancelled_and_anonymized()

    def test_discovery_result_fetched_before_closure_cannot_create_history_afterward(self):
        self.network_overlaps_closure(discover_contest_progress,(self.author.pk,self.token),
            'club.contest_progress_sources.discover',self.discovered_rows)
        self.assertFalse(ContestParticipation.objects.filter(user=self.author,contest_key='new-contest').exists())

    def test_discovery_already_past_binding_check_commits_before_closure_scan(self):
        writing,closing,closed=Event(),Event(),Event()
        original=ContestParticipation.objects.update_or_create
        def paused_write(*args,**kwargs):
            writing.set()
            self.assertTrue(closing.wait(10),'Closure did not try to acquire the user lock')
            self.assertFalse(closed.wait(.2),'Closure passed an in-progress discovery write')
            return original(*args,**kwargs)
        with patch('club.contest_progress_sources.Remote'), \
                patch('club.contest_progress_sources.discover',side_effect=self.discovered_rows), \
                patch.object(ContestParticipation.objects,'update_or_create',side_effect=paused_write), \
                patch('club.tasks.enqueue_hydration'):
            with ThreadPoolExecutor(max_workers=2) as pool:
                job=pool.submit(self.run_task,discover_contest_progress,self.author.pk,self.token)
                self.assertTrue(writing.wait(10),'Discovery did not pass its binding check')
                closure=pool.submit(self.close_in_thread,closing,closed)
                job.result(timeout=10)
                self.assertTrue(closure.result(timeout=10))
        self.assertTrue(ContestParticipation.objects.filter(user=self.author,contest_key='new-contest').exists())
        self.assert_cancelled_and_anonymized()

    def test_late_hydration_cannot_restore_private_errors_or_replace_verified_progress(self):
        self.network_overlaps_closure(hydrate_contest_progress,(self.contest.pk,self.token),
            'club.contest_progress_sources.hydrate',lambda:([], 'private_handle late error'))
        self.assertEqual(ContestProblemProgress.objects.filter(participation=self.contest).count(),1)

    def test_queued_old_tasks_exit_without_remote_requests_after_closure(self):
        close_user(self.author.pk,self.author)
        with patch('club.contest_progress_sources.Remote') as remote, \
                patch('club.contest_progress_sources.discover') as discover, \
                patch('club.contest_progress_sources.hydrate') as hydrate:
            discover_contest_progress(self.author.pk,self.token)
            hydrate_contest_progress(self.contest.pk,self.token)
        remote.assert_not_called();discover.assert_not_called();hydrate.assert_not_called()
        self.assert_cancelled_and_anonymized()

    def test_active_discovery_and_hydration_still_complete_and_ignore_duplicate_jobs(self):
        with patch('club.contest_progress_sources.Remote'), \
                patch('club.contest_progress_sources.discover',side_effect=self.discovered_rows) as discover, \
                patch('club.tasks.enqueue_hydration') as enqueue:
            discover_contest_progress(self.author.pk,self.token)
            row=ContestParticipation.objects.get(user=self.author,contest_key='new-contest')
            enqueue.assert_called_once_with(row.pk,self.token)
            self.state.refresh_from_db();self.assertEqual((self.state.status,self.state.remaining),('pending',1))
            with patch('club.contest_progress_sources.hydrate',return_value=([
                    {'problem_key':'A','label':'A','title':'Accepted','accepted':True,'official_ac':True}],'')):
                hydrate_contest_progress(row.pk,self.token)
            self.state.refresh_from_db();self.assertEqual((self.state.status,self.state.remaining),('ready',0))
            self.assertTrue(ContestProblemProgress.objects.filter(participation=row,accepted=True).exists())
            discover_contest_progress(self.author.pk,self.token)
            discover.assert_called_once()

    def test_stale_sync_request_cannot_restart_sync_after_closure(self):
        original=contest_progress_views.membership_for
        def stale_member(request):
            member=original(request)
            close_user(self.author.pk,self.author)
            return member
        with patch.object(contest_progress_views,'membership_for',side_effect=stale_member), \
                patch('club.contest_progress_views.enqueue') as enqueue:
            response=self.client.post('/api/contests/progress')
        self.assertEqual(response.status_code,403,response.content)
        enqueue.assert_not_called()
        self.assert_cancelled_and_anonymized()
