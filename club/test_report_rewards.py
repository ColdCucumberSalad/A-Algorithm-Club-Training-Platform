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
        data={'action':'reject','note':'已核实举报成立','version':self.item.version,'report_ids':[self.first.pk,self.second.pk],
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
        data={'version':self.item.version,'note':'直接退回','report_ids':[self.first.pk,self.second.pk],
            'report_coins':{'reward_each':1,'author_penalty':1,'reporter_ids':[self.reader.pk]}}
        response=self.client.post(f'/api/submissions/{self.item.pk}/reject',json.dumps(data),content_type='application/json')
        self.assertEqual(response.status_code,400,response.content)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)
        self.assertEqual(self.decide(action='dismiss',report_coins=None).status_code,400)
        response=self.client.post(self.url,json.dumps({'action':'dismiss','version':self.item.version,'report_ids':[self.first.pk,self.second.pk]}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(CurrencyTransaction.objects.filter(transaction_type__startswith='report_').exists())

    def test_cancelled_or_inactive_reporter_is_not_rewarded(self):
        self.second.status='cancelled';self.second.save(update_fields=['status'])
        self.assertEqual(self.decide().status_code,409)
        response=self.decide({'reward_each':1,'author_penalty':1,'reporter_ids':[self.reader.pk]},report_ids=[self.first.pk])
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
        self.assertEqual(self.decide(report_ids=None).status_code,409)
        self.client.force_login(self.reader)
        self.assertEqual(self.decide().status_code,403)
        self.item.refresh_from_db();self.assertTrue(self.item.is_valid)

    def test_queue_marks_ineligible_reporters_and_returns_recipient_identity(self):
        self.extra.is_active=False;self.extra.save(update_fields=['is_active'])
        data=self.client.get('/api/admin/reports').json()['submissions'][0]
        details={r['reporter_id']:r for r in data['report_details']}
        self.assertTrue(details[self.reader.pk]['reward_eligible']);self.assertFalse(details[self.extra.pk]['reward_eligible'])
        self.assertEqual(self.decide().status_code,400)
        self.assertEqual(self.decide({'reward_each':1,'author_penalty':0,'reporter_ids':[self.reader.pk]}).status_code,200)
