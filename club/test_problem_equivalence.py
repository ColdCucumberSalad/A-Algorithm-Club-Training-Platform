import json
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from . import test_community as fixtures
from .models import (Problem, ProblemComparison, Submission, SubmissionPart, CheckinRecord,
                     CurrencyBalance, CurrencyTransaction, SolvedProblemCredit, DatedSolvedProblemCredit, ParserSettings)
from .problem_parser import get_problem, resolve, ai_json
from .problem_equivalence import reconcile_problem, ai_same_problem
from .views import serialize_submission


class ProblemEquivalenceTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.old = self.problem
        self.old.title = '同一道题'
        self.old.status = 'success'
        self.old.save()
        self.new = Problem.objects.create(identity='nowcoder:problem/327285',
            url='https://ac.nowcoder.com/acm/problem/327285', title=self.old.title,
            status='success', generation=1)
        self.first = self.record(self.old, self.author_member, timezone.localdate()-timedelta(days=1))

    def record(self, problem, member, day):
        row=Submission.objects.create(team=self.team,member=member,semester=self.semester,
            week=self.week,problem=problem,record_date=day)
        SubmissionPart.objects.create(submission=row,kind='proof',status='approved',points_awarded=1)
        return row

    def reconcile(self, same=True):
        with patch('club.problem_equivalence.ai_same_problem',return_value=same) as compare:
            reconcile_problem(self.new.pk,1)
        return compare

    def test_confirmed_alias_moves_submissions_and_blocks_future_duplicates(self):
        second=self.record(self.new,self.owner_member,timezone.localdate())
        self.reconcile()
        second.refresh_from_db()
        self.assertEqual(second.problem_id,self.old.pk)
        self.assertTrue(second.is_valid)
        self.assertEqual(get_problem(self.new.url).pk,self.old.pk)
        self.assertEqual(Problem.objects.get(pk=self.new.pk).canonical_id,self.old.pk)
        self.assertTrue(ProblemComparison.objects.get().same)
        response=self.client.post('/api/submissions',{'problem_url':self.new.url,'week_id':self.week.pk,
            'proof':fixtures.CommunityTests.image(self),'code':'int main(){}'})
        self.assertEqual(response.status_code,409,response.content)

    def test_same_user_retains_record_but_loses_points_checkin_and_paid_rewards_once(self):
        second=self.record(self.new,self.author_member,timezone.localdate())
        self.team.currency_enabled=True;self.team.save()
        CheckinRecord.objects.create(team=self.team,member=self.author_member,checkin_date=second.record_date,reward_amount=3)
        CurrencyBalance.objects.create(team=self.team,member=self.author_member,balance=1)
        self.reconcile()
        second.refresh_from_db();self.first.refresh_from_db()
        self.assertTrue(self.first.is_valid)
        self.assertTrue(second.is_duplicate)
        self.assertFalse(second.is_valid)
        self.assertTrue(second.parts.exists())
        self.assertEqual(second.parts.get().points_awarded,0)
        self.assertFalse(CheckinRecord.objects.exists())
        self.assertEqual(CurrencyBalance.objects.get().balance,-2)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='reward_reversal').count(),1)
        data=serialize_submission(second)
        self.assertTrue(data['is_duplicate']);self.assertFalse(data['can_edit']);self.assertFalse(data['can_resubmit'])
        self.assertIn('重复题目',data['rejection_note'])
        self.reconcile()
        self.assertEqual(CurrencyTransaction.objects.count(),1)

    def test_another_valid_submission_on_same_day_keeps_checkin(self):
        day=timezone.localdate()
        self.record(self.new,self.author_member,day)
        unrelated=Problem.objects.create(identity='other',url='https://example.com/other',title='另一题')
        self.record(unrelated,self.author_member,day)
        CheckinRecord.objects.create(team=self.team,member=self.author_member,checkin_date=day,reward_amount=3)
        self.reconcile()
        self.assertTrue(CheckinRecord.objects.exists());self.assertFalse(CurrencyTransaction.objects.exists())

    def test_different_same_named_problems_remain_separate_and_cache_negative(self):
        self.reconcile(False)
        with patch('club.problem_equivalence.ai_same_problem') as ai:
            reconcile_problem(self.new.pk,1)
            ai.assert_not_called()
        self.assertIsNone(Problem.objects.get(pk=self.new.pk).canonical_id)

    def test_missing_ai_evidence_never_merges_or_changes_rewards(self):
        self.record(self.new,self.author_member,timezone.localdate())
        with patch('club.problem_equivalence.ai_same_problem',side_effect=ValueError('证据不足')):
            reconcile_problem(self.new.pk,1)
        self.assertEqual(Submission.objects.filter(is_valid=True).count(),2)
        self.assertFalse(ProblemComparison.objects.exists())
        self.assertIn('证据不足',Problem.objects.get(pk=self.new.pk).error)
        self.assertEqual(Problem.objects.get(pk=self.new.pk).status,'failed')

    def test_nonmatching_titles_do_not_spend_ai_calls(self):
        self.new.title='不同题名';self.new.save()
        self.assertEqual(self.reconcile().call_count,0)

    def test_stale_task_cannot_merge_after_manual_title_update(self):
        def compare(*args):
            Problem.objects.filter(pk=self.new.pk).update(status='manual',generation=2,title='管理员更正')
            return True
        with patch('club.problem_equivalence.ai_same_problem',side_effect=compare):
            reconcile_problem(self.new.pk,1)
        self.assertIsNone(Problem.objects.get(pk=self.new.pk).canonical_id)

    def test_archived_credits_are_rekeyed_without_duplicate_totals(self):
        for problem in [self.old,self.new]:
            SolvedProblemCredit.objects.create(user=self.author,source='submission',problem_key=problem.identity)
            DatedSolvedProblemCredit.objects.create(user=self.author,source='submission',problem_key=problem.identity,solved_on=self.first.record_date)
        self.reconcile()
        self.assertEqual(SolvedProblemCredit.objects.count(),1)
        self.assertEqual(DatedSolvedProblemCredit.objects.count(),1)

    def test_resolution_runs_verification_after_auto_title_success(self):
        self.new.status='pending';self.new.save()
        with patch('club.problem_parser.auto_title',return_value=self.old.title),patch('club.problem_equivalence.ai_same_problem',return_value=True):
            resolve(self.new.pk,1,'auto')
        self.assertEqual(get_problem(self.new.url).pk,self.old.pk)

    def test_strict_ai_response_rejects_strings_and_unknown(self):
        for value in [None,'true',1]:
            with self.subTest(value=value),patch('club.problem_parser.ai_json',return_value={'same_problem':value,'reason':'test'}):
                with self.assertRaises(ValueError):ai_same_problem(self.old,self.new)
        with patch('club.problem_parser.ai_json',return_value={'same_problem':True,'reason':'两边题面和样例一致'}):
            self.assertTrue(ai_same_problem(self.old,self.new))

    def test_ai_comparison_uses_configured_protocol_and_both_urls(self):
        from .problem_parser import key_cipher
        config,_=ParserSettings.objects.update_or_create(pk=1,defaults={
            'base_url':'https://api.example.com/v1','model':'test',
            'encrypted_key':key_cipher().encrypt(b'test-key').decode()})
        for protocol in ['chat','responses']:
            config.api_protocol=protocol;config.save()
            text=json.dumps({'same_problem':False,'reason':'输入约束不同'})
            response={'choices':[{'message':{'content':text}}]} if protocol=='chat' else {
                'output':[{'type':'message','content':[{'type':'output_text','text':text}]}]}
            with patch('club.problem_parser.http_fetch',return_value=json.dumps(response)) as fetch:
                self.assertFalse(ai_same_problem(self.old,self.new))
                sent=json.loads(fetch.call_args.kwargs['payload'])
                self.assertIn(self.new.url,str(sent));self.assertIn(self.old.url,str(sent))
                if protocol=='responses':self.assertEqual(sent['tools'],[{'type':'web_search'}])

    def test_reward_failure_rolls_back_aliases_and_invalidations(self):
        duplicate=self.record(self.new,self.author_member,timezone.localdate())
        with patch('club.problem_equivalence.ai_same_problem',return_value=True),patch(
                'club.currency_services.reconcile_submission_day',side_effect=ValueError('余额错误')):
            reconcile_problem(self.new.pk,1)
        duplicate.refresh_from_db()
        self.assertTrue(duplicate.is_valid);self.assertFalse(duplicate.is_duplicate)
        self.assertEqual(duplicate.problem_id,self.new.pk)
        self.assertIsNone(Problem.objects.get(pk=self.new.pk).canonical_id)
        self.assertFalse(ProblemComparison.objects.exists())


class ProblemEquivalenceConcurrencyTests(TransactionTestCase):
    def test_concurrent_matches_leave_one_valid_record_and_flat_aliases(self):
        from concurrent.futures import ThreadPoolExecutor
        from django.db import close_old_connections
        fixtures.CommunityTests.setUp(self)
        self.problem.title='并发同题';self.problem.status='success';self.problem.save()
        ProblemEquivalenceTests.record(self,self.problem,self.author_member,timezone.localdate())
        problems=[Problem.objects.create(identity='parallel:'+str(i),url=f'https://example.com/{i}',
            title=self.problem.title,status='success',generation=1) for i in range(2)]
        for p in problems:ProblemEquivalenceTests.record(self,p,self.author_member,timezone.localdate())
        def work(pk):
            close_old_connections()
            try:reconcile_problem(pk,1)
            finally:close_old_connections()
        with patch('club.problem_equivalence.ai_same_problem',return_value=True),ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(work,[p.pk for p in problems]))
        self.assertEqual(Submission.objects.count(),3)
        self.assertEqual(Submission.objects.filter(is_valid=True).count(),1)
        self.assertEqual(Submission.objects.filter(is_duplicate=True).count(),2)
        self.assertEqual(set(Submission.objects.values_list('problem_id',flat=True)),{self.problem.pk})
        self.assertEqual(Problem.objects.filter(canonical=self.problem).count(),2)
