import json
from django.test import TestCase,Client,TransactionTestCase
from django.contrib.auth.models import User
from . import test_community as fixtures
from .models import (Submission,SubmissionPart,SubmissionReport,TeamMembership,CurrencyBalance,
    CurrencyTransaction,ReviewLog)
from .currency_services import get_or_create_balance,add_currency


class ReportRewardTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.item=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem)
        SubmissionPart.objects.create(submission=self.item,kind='proof',status='approved',points_awarded=1)
        self.first=SubmissionReport.objects.create(submission=self.item,version=self.item.version,reporter=self.reader,reason='One')
        self.extra=User.objects.create_user('second-reporter')
        self.extra_member=TeamMembership.objects.create(team=self.team,user=self.extra,display_name='Second')
        self.second=SubmissionReport.objects.create(submission=self.item,version=self.item.version,reporter=self.extra,reason='Two')
        self.client.force_login(self.owner)
        self.url=f'/api/admin/reports/{self.item.pk}/resolve'

    def decide(self,settings=None,**changes):
        data={'action':'reject','note':'已核实举报成立','version':self.item.version,'report_snapshot':[{'id':self.first.pk,'generation':self.first.generation},{'id':self.second.pk,'generation':self.second.generation}],
            'report_coins':settings if settings is not None else {'reward_each':1,'author_penalty':1,'reporter_ids':[self.reader.pk,self.extra.pk]}}
        data.update(changes)
        return self.client.post(self.url,json.dumps(data),content_type='application/json')

    def balance(self,user):return CurrencyBalance.objects.filter(user=user).values_list('balance',flat=True).first() or 0

    def test_multiple_reporters_each_rewarded_author_penalized_once(self):
        add_currency(self.author_member,10,'admin_adjust')
        response=self.decide();self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.balance(self.reader),1);self.assertEqual(self.balance(self.extra),1)
        self.assertEqual(self.balance(self.author),9)
        self.assertEqual(response.json()['report_coins']['reward_total'],2)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='report_penalty').count(),1)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='report_reward').count(),2)
        audit=ReviewLog.objects.get(submission=self.item,action='report_reject')
        self.assertEqual(audit.detail['report_coins']['reporter_ids'],sorted([self.reader.pk,self.extra.pk]))

    def test_repeated_resolution_does_not_pay_twice(self):
        self.assertEqual(self.decide().status_code,200)
        self.assertEqual(self.decide().status_code,409)
        self.assertEqual(self.balance(self.reader),1);self.assertEqual(self.balance(self.author),-1)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').count(),3)

    def test_subset_and_duplicate_recipient_ids_pay_one_account_once(self):
        response=self.decide({'reward_each':2,'author_penalty':0,'reporter_ids':[self.reader.pk,self.reader.pk]})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.balance(self.reader),2);self.assertEqual(self.balance(self.extra),0)
        self.assertEqual(self.balance(self.author),0)
        self.assertEqual(response.json()['report_coins']['rewarded_count'],1)

    def test_zero_settings_and_legacy_decision_do_not_adjust_coins(self):
        self.assertEqual(self.decide({'reward_each':0,'author_penalty':0,'reporter_ids':[]}).status_code,200)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_invalid_settings_cannot_mutate_report_or_wallet(self):
        cases=[{'reward_each':-1,'author_penalty':1,'reporter_ids':[]},
            {'reward_each':True,'author_penalty':1,'reporter_ids':[]},
            {'reward_each':1,'author_penalty':101,'reporter_ids':[]},
            {'reward_each':1,'author_penalty':1,'reporter_ids':[self.author.pk]},
            {'reward_each':1,'author_penalty':1,'reporter_ids':[self.owner.pk]}]
        for value in cases:self.assertEqual(self.decide(value).status_code,400)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.item.reports.filter(status='pending').count(),2)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_dismiss_and_direct_reject_cannot_use_report_rewards(self):
        self.assertEqual(self.decide(action='dismiss').status_code,400)
        data={'version':self.item.version,'note':'直接退回','report_snapshot':[{'id':self.first.pk,'generation':self.first.generation},{'id':self.second.pk,'generation':self.second.generation}],
            'report_coins':{'reward_each':1,'author_penalty':1,'reporter_ids':[self.reader.pk]}}
        response=self.client.post(f'/api/submissions/{self.item.pk}/reject',json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,400,response.content)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.decide(action='dismiss',report_coins=None).status_code,400)
        response=self.client.post(self.url,json.dumps({'action':'dismiss','version':self.item.version,'report_snapshot':[{'id':self.first.pk,'generation':self.first.generation},{'id':self.second.pk,'generation':self.second.generation}]}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_cancelled_or_inactive_reporter_is_not_rewarded(self):
        self.second.status='cancelled';self.second.save(update_fields=['status'])
        self.assertEqual(self.decide().status_code,409)
        response=self.decide({'reward_each':1,'author_penalty':1,'reporter_ids':[self.reader.pk]},report_snapshot=[{'id':self.first.pk,'generation':self.first.generation}])
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.balance(self.reader),1);self.assertEqual(self.balance(self.extra),0)

    def test_overflow_rolls_back_decision_recalculation_and_all_payments(self):
        CurrencyBalance.objects.create(user=self.extra,balance=2147483647)
        add_currency(self.author_member,10,'admin_adjust')
        response=self.decide();self.assertEqual(response.status_code,400,response.content)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.item.parts.get(kind='proof').points_awarded,1)
        self.assertEqual(self.item.reports.filter(status='pending').count(),2)
        self.assertEqual(self.balance(self.author),10);self.assertEqual(self.balance(self.reader),0)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_currency_requires_complete_snapshot_and_other_members_cannot_resolve(self):
        self.assertEqual(self.decide(report_snapshot=None).status_code,409)
        self.client.force_login(self.reader)
        self.assertEqual(self.decide().status_code,403)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)

    def test_cancel_and_rereport_invalidates_old_snapshot_for_both_decisions(self):
        queued=self.client.get('/api/admin/reports').json()['submissions'][0]
        snapshot=[{'id':r['id'],'generation':r['generation']} for r in queued['report_details']]
        reporter=Client();reporter.force_login(self.reader)
        url=f'/api/submissions/{self.item.pk}/report'
        self.assertEqual(reporter.delete(url).status_code,200)
        self.assertEqual(reporter.post(url,json.dumps({'reason':'Replacement reason'}),content_type='application/json').status_code,200)
        self.first.refresh_from_db()
        self.assertEqual(self.first.generation,2)
        for action in ('dismiss','reject'):
            response=self.decide(action=action,report_snapshot=snapshot)
            self.assertEqual(response.status_code,409,response.content)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.item.reports.filter(status='pending').count(),2)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())
        queued=self.client.get('/api/admin/reports').json()['submissions'][0]
        replacement=next(r for r in queued['report_details'] if r['id']==self.first.pk)
        self.assertEqual((replacement['reason'],replacement['generation']),('Replacement reason',2))
        fresh=[{'id':r['id'],'generation':r['generation']} for r in queued['report_details']]
        self.assertEqual(self.decide(report_snapshot=fresh).status_code,200)
        self.assertEqual(self.balance(self.reader),1)
        self.assertEqual(self.balance(self.author),-1)

    def test_malformed_or_id_only_snapshots_cannot_bypass_generation_check(self):
        valid={'id':self.first.pk,'generation':1}
        for snapshot in (None,[self.first.pk,self.second.pk],[valid,valid],
                [{'id':self.first.pk,'generation':True}], [{'id':self.first.pk,'generation':0}]):
            self.assertEqual(self.decide(report_snapshot=snapshot).status_code,409)
        response=self.client.post(self.url,json.dumps({'action':'dismiss','version':self.item.version,
            'report_ids':[self.first.pk,self.second.pk]}),content_type='application/json')
        self.assertEqual(response.status_code,409,response.content)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_queue_marks_ineligible_reporters_and_returns_recipient_identity(self):
        self.extra.is_active=False;self.extra.save(update_fields=['is_active'])
        data=self.client.get('/api/admin/reports').json()['submissions'][0]
        details={r['reporter_id']:r for r in data['report_details']}
        self.assertTrue(details[self.reader.pk]['reward_eligible']);self.assertFalse(details[self.extra.pk]['reward_eligible'])
        self.assertEqual(self.decide().status_code,400)
        self.assertEqual(self.decide({'reward_each':1,'author_penalty':0,'reporter_ids':[self.reader.pk]}).status_code,200)

    def duplicate_successor(self):
        row=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,
            week=self.week,problem=self.problem,record_date=self.item.record_date,
            is_valid=False,is_duplicate=True,duplicate_state={'parts':{'proof':{
                'status':'approved','points':1,'note':''}}})
        SubmissionPart.objects.create(submission=row,kind='proof',status='rejected',points_awarded=0)
        return row

    def test_penalties_increase_debt_and_reporter_rewards_pay_down_debt(self):
        CurrencyBalance.objects.create(user=self.author,balance=-2)
        CurrencyBalance.objects.create(user=self.reader,balance=-4)
        response=self.decide()
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(self.balance(self.author),-3)
        self.assertEqual(self.balance(self.reader),-3)
        self.assertEqual(self.balance(self.extra),1)
        self.assertEqual(self.decide().status_code,409)
        self.assertEqual(self.balance(self.author),-3)

    def test_penalty_underflow_rolls_back_every_report_and_reward(self):
        CurrencyBalance.objects.create(user=self.author,balance=-2147483648)
        response=self.decide()
        self.assertEqual(response.status_code,400,response.content)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.item.reports.filter(status='pending').count(),2)
        self.assertEqual(self.balance(self.author),-2147483648)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_report_rewards_and_duplicate_promotion_commit_together(self):
        from .models import CheckinRecord,SemesterMemberTotal
        self.team.currency_enabled=True;self.team.save()
        successor=self.duplicate_successor()
        CheckinRecord.objects.create(team=self.team,member=self.author_member,
            checkin_date=self.item.record_date,reward_amount=3)
        add_currency(self.author_member,10,'admin_adjust')
        response=self.decide()
        self.assertEqual(response.status_code,200,response.content)
        self.item.refresh_from_db();successor.refresh_from_db()
        self.assertFalse(self.item.is_valid);self.assertFalse(self.item.is_duplicate)
        self.assertTrue(successor.is_valid);self.assertFalse(successor.is_duplicate)
        self.assertEqual(successor.parts.get(kind='proof').points_awarded,1)
        self.assertEqual(SemesterMemberTotal.objects.get(member=self.author_member).total_submissions,1)
        self.assertTrue(CheckinRecord.objects.filter(member=self.author_member).exists())
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type='reward_reversal').exists())
        self.assertEqual(self.balance(self.author),9)
        self.assertEqual(self.balance(self.reader),1);self.assertEqual(self.balance(self.extra),1)
        self.assertEqual(self.decide().status_code,409)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='report_penalty').count(),1)

    def test_report_reward_failure_also_rolls_back_duplicate_promotion(self):
        successor=self.duplicate_successor()
        CurrencyBalance.objects.create(user=self.extra,balance=2147483647)
        response=self.decide()
        self.assertEqual(response.status_code,400,response.content)
        self.item.refresh_from_db();successor.refresh_from_db()
        self.assertTrue(self.item.is_valid)
        self.assertFalse(successor.is_valid);self.assertTrue(successor.is_duplicate)
        self.assertEqual(successor.parts.get(kind='proof').points_awarded,0)
        self.assertFalse(ReviewLog.objects.filter(action='duplicate_promoted',submission=successor).exists())
        self.assertEqual(self.item.reports.filter(status='pending').count(),2)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())
