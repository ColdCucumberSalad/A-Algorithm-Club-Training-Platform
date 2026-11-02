import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import transaction, close_old_connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from . import test_community as fixtures
from .models import (Problem, Submission, SubmissionPart, CheckinRecord, CurrencyBalance,
                     CurrencyTransaction, Semester, SemesterMemberTotal, TeamMembership)
from .problem_parser import canonical_problem
from .problem_equivalence import reconcile_problem
from .services import refresh_totals
from .views import serialize_submission


class DuplicateSuccessionTests(TestCase):
    image = fixtures.CommunityTests.image

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.problem.identity=canonical_problem(self.problem.url)[0]
        self.problem.title='同题';self.problem.status='success';self.problem.save()
        self.alias=Problem.objects.create(identity='nowcoder:problem/327285',
            url='https://ac.nowcoder.com/acm/problem/327285',title='同题',status='success',generation=1)
        self.first=self.record(self.problem,timezone.localdate())
        self.second=self.record(self.alias,timezone.localdate())
        with patch('club.problem_equivalence.ai_same_problem',return_value=True):
            reconcile_problem(self.alias.pk,1)
        self.first.refresh_from_db();self.second.refresh_from_db()

    def record(self,problem,day):
        row=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,
            week=self.week,problem=problem,record_date=day,original_problem_url=problem.url)
        SubmissionPart.objects.create(submission=row,kind='proof',status='approved',points_awarded=1)
        return row

    def edit(self,row,url=None):
        row.refresh_from_db()
        return self.client.post(f'/api/submissions/{row.pk}/edit',{'week_id':row.week_id,'version':row.version,
            'problem_url':url or row.original_problem_url,'code':'int main() {return 0;}',
            'logic':'更新材料','proof':self.image()})

    def delete(self,row):
        row.refresh_from_db()
        return self.client.delete(f'/api/submissions/{row.pk}',json.dumps({'version':row.version}),content_type='application/json')

    def test_retained_original_can_edit_without_changing_priority(self):
        initial=self.first.first_submitted_at
        response=self.edit(self.first)
        self.assertEqual(response.status_code,201,response.content)
        self.first.refresh_from_db();self.second.refresh_from_db()
        self.assertEqual(self.first.first_submitted_at,initial)
        self.assertTrue(self.first.is_valid);self.assertFalse(self.second.is_valid)

    def test_duplicate_is_editable_and_deletable_but_remains_invalid(self):
        initial=self.second.first_submitted_at
        self.assertTrue(serialize_submission(self.second)['can_edit'])
        response=self.edit(self.second)
        self.assertEqual(response.status_code,201,response.content)
        self.second.refresh_from_db()
        self.assertFalse(self.second.is_valid);self.assertTrue(self.second.is_duplicate)
        self.assertEqual(self.second.first_submitted_at,initial)
        self.assertIn('更新材料',self.second.parts.get(kind='logic').text_content)
        self.assertEqual(self.second.parts.get(kind='logic').points_awarded,0)
        self.assertEqual(self.delete(self.second).status_code,200)
        self.first.refresh_from_db();self.assertTrue(self.first.is_valid)

    def test_same_url_is_blocked_even_if_the_prior_record_is_duplicate(self):
        response=self.client.post('/api/submissions',{'week_id':self.week.pk,'problem_url':self.alias.url,
            'proof':self.image(),'code':'int main(){}'})
        self.assertEqual(response.status_code,409,response.content)

    def test_distinct_known_alias_can_be_added_as_an_invalid_record(self):
        third=Problem.objects.create(identity='nowcoder:contest/142559/e',
            url='https://ac.nowcoder.com/acm/contest/142559/E',title='同题',status='success',canonical=self.problem)
        response=self.client.post('/api/submissions',{'week_id':self.week.pk,'problem_url':third.url,
            'proof':self.image(),'code':'int main(){}'})
        self.assertEqual(response.status_code,201,response.content)
        self.assertTrue(response.json()['submission']['is_duplicate'])
        self.assertEqual(Submission.objects.filter(is_valid=True).count(),1)

    def test_deleting_winner_promotes_next_and_preserves_same_day_checkin(self):
        self.team.currency_enabled=True;self.team.save()
        CheckinRecord.objects.create(team=self.team,member=self.author_member,
            checkin_date=self.first.record_date,reward_amount=3)
        CurrencyBalance.objects.create(team=self.team,member=self.author_member,balance=3)
        self.assertEqual(self.delete(self.first).status_code,200)
        self.second.refresh_from_db()
        self.assertTrue(self.second.is_valid);self.assertFalse(self.second.is_duplicate)
        self.assertEqual(self.second.parts.get(kind='proof').points_awarded,1)
        self.assertEqual(CheckinRecord.objects.count(),1)
        self.assertEqual(CurrencyBalance.objects.get().balance,3)
        self.assertFalse(CurrencyTransaction.objects.exists())
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_submissions,1)

    def test_rejecting_winner_promotes_second_and_excludes_rejected_record(self):
        self.client.force_login(self.owner)
        response=self.client.post(f'/api/submissions/{self.first.pk}/reject',
            json.dumps({'version':self.first.version,'note':'截图不匹配'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.first.refresh_from_db();self.second.refresh_from_db()
        self.assertFalse(self.first.is_valid);self.assertFalse(self.first.is_duplicate)
        self.assertTrue(self.second.is_valid)
        self.client.force_login(self.author)
        self.assertEqual(self.delete(self.second).status_code,200)
        self.first.refresh_from_db();self.assertFalse(self.first.is_valid)

    def test_original_edit_is_not_blocked_by_legacy_archived_duplicate(self):
        old=Semester.objects.create(team=self.team,name='已归档',starts_on=timezone.localdate()-timedelta(days=90),
            ends_on=timezone.localdate()-timedelta(days=60),is_active=False,archived_at=timezone.now())
        from .services import build_weeks
        build_weeks(old)
        self.second.semester=old;self.second.week=old.weeks.first();self.second.record_date=old.starts_on
        self.second.original_problem_url='';self.second.save()
        self.assertEqual(self.edit(self.first).status_code,201)
        self.assertTrue(serialize_submission(self.second)['can_edit'])
        self.assertTrue(serialize_submission(self.second)['can_delete'])
        self.assertEqual(self.edit(self.second,url=self.problem.url).status_code,201)
        self.assertEqual(self.delete(self.second).status_code,200)

    def test_cross_day_promotion_restores_exact_reward_and_next_priority(self):
        day=timezone.localdate()-timedelta(days=1)
        self.second.record_date=day
        self.second.duplicate_state={'checkin':{'is_makeup':False,'reward_amount':2}}
        self.second.save()
        self.team.currency_enabled=True;self.team.daily_checkin_reward=7;self.team.save()
        self.assertEqual(self.delete(self.first).status_code,200)
        self.assertEqual(CheckinRecord.objects.get().reward_amount,2)
        self.assertEqual(CurrencyBalance.objects.get().balance,2)
        self.assertEqual(self.delete(self.second).status_code,200)
        self.assertEqual(CurrencyBalance.objects.get().balance,0)

    def test_multiple_successors_use_initial_order_after_an_edit(self):
        third_alias=Problem.objects.create(identity='https://example.com/third',url='https://example.com/third',
            canonical=self.problem,status='success')
        response=self.client.post('/api/submissions',{'week_id':self.week.pk,'problem_url':third_alias.url,
            'proof':self.image(),'code':'int main(){}'})
        self.assertEqual(response.status_code,201,response.content)
        self.assertTrue(response.json()['submission']['is_duplicate'])
        third=Submission.objects.get(pk=response.json()['submission']['id'])
        self.assertEqual(self.edit(self.second).status_code,201)
        self.assertEqual(self.delete(self.first).status_code,200)
        self.second.refresh_from_db();third.refresh_from_db()
        self.assertTrue(self.second.is_valid);self.assertFalse(third.is_valid)
        self.assertEqual(self.delete(self.second).status_code,200)
        third.refresh_from_db();self.assertTrue(third.is_valid)

    def test_same_day_successor_never_quotes_unnecessary_item_recovery(self):
        from .reward_recovery import build_plan
        self.team.currency_enabled=True;self.team.save()
        CheckinRecord.objects.create(team=self.team,member=self.author_member,
            checkin_date=self.first.record_date,reward_amount=3)
        CurrencyBalance.objects.create(team=self.team,member=self.author_member,balance=0)
        self.assertEqual(build_plan(self.first)['reward_reversal'],0)
        self.assertEqual(build_plan(self.first)['recoveries'],[])

    def test_editing_duplicate_to_a_different_problem_reconciles_both_groups(self):
        url='https://ac.nowcoder.com/acm/problem/123456'
        other=Problem.objects.create(identity=canonical_problem(url)[0],url=url,status='success',title='另一道题')
        response=self.edit(self.second,url=url)
        self.assertEqual(response.status_code,201,response.content)
        self.first.refresh_from_db();self.second.refresh_from_db()
        self.assertTrue(self.first.is_valid);self.assertTrue(self.second.is_valid)
        self.assertFalse(self.second.is_duplicate)
        self.assertEqual(self.second.problem_id,other.pk)

    def test_promotion_restores_original_points_after_configuration_change(self):
        self.semester.screenshot_points=5;self.semester.save()
        self.assertEqual(self.delete(self.first).status_code,200)
        self.second.refresh_from_db()
        self.assertEqual(self.second.parts.get(kind='proof').points_awarded,1)


class SemesterMergeConcurrencyTests(TransactionTestCase):
    def test_unrelated_submitter_waits_for_merge_semester_lock(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from .problem_equivalence import rebalance_submissions
        fixtures.CommunityTests.setUp(self)
        self.problem.title='锁测试';self.problem.status='success';self.problem.save()
        alias=Problem.objects.create(identity='lock:alias',url='https://example.com/alias',
            title=self.problem.title,status='success',generation=1)
        def row(problem,member):
            record=Submission.objects.create(team=self.team,member=member,semester=self.semester,
                week=self.week,problem=problem,record_date=timezone.localdate())
            SubmissionPart.objects.create(submission=record,kind='proof',status='approved',points_awarded=1)
        row(self.problem,self.author_member);row(alias,self.author_member)
        unrelated=Problem.objects.create(identity='lock:other',url='https://example.com/other')
        reader=TeamMembership.objects.get(user=self.reader,team=self.team)
        merging,attempted,acquired=Event(),Event(),Event()
        def writer():
            close_old_connections()
            try:
                self.assertTrue(merging.wait(10))
                with transaction.atomic():
                    User.objects.select_for_update().get(pk=self.reader.pk)
                    attempted.set()
                    semester=Semester.objects.select_for_update().get(pk=self.semester.pk)
                    acquired.set();row(unrelated,reader);refresh_totals(semester)
            finally:close_old_connections()
        def watch(*args,**kwargs):
            merging.set();self.assertTrue(attempted.wait(10))
            self.assertFalse(acquired.wait(.2),'Unrelated writer entered before merge released its semester lock')
            return rebalance_submissions(*args,**kwargs)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(writer)
            with patch('club.problem_equivalence.ai_same_problem',return_value=True),patch(
                    'club.problem_equivalence.rebalance_submissions',side_effect=watch):
                reconcile_problem(alias.pk,1)
            pending.result(timeout=10)
        self.assertTrue(acquired.is_set())
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_submissions,1)
        self.assertEqual(SemesterMemberTotal.objects.get(member=reader).total_submissions,1)
