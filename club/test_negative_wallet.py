import json

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone

from . import test_community as fixtures
from .currency_services import (add_currency, adjust_currency, deduct_currency,
    get_or_create_balance, purchase_item, reconcile_submission_day)
from .models import (CheckinRecord, CurrencyBalance, CurrencyTransaction, Purchase,
    ShopItem, Submission, Team, TeamMembership, UserInventory)


class NegativeWalletTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.team.currency_enabled=True; self.team.save()
        self.root=User.objects.filter(username='admin').first() or User.objects.create_superuser('admin',password='Test-password-123')
        self.admin=Client(); self.admin.force_login(self.root)
        session=self.admin.session; session['team_id']=self.team.pk; session.save()
        self.url=f'/api/management/accounts/{self.author.pk}'

    def set_balance(self,value,expected):
        return self.admin.patch(self.url,json.dumps({'action':'balance','balance':value,
            'expected_balance':expected}),content_type='application/json')

    def balance(self):
        return get_or_create_balance(self.author_member).balance

    def test_global_negative_balance_is_shared_audited_and_version_checked(self):
        other=Team.objects.create(name='Other debt team',code='DEBT-OTHER',created_by=self.root)
        member=TeamMembership.objects.create(team=other,user=self.author,display_name='Other')
        response=self.set_balance(-5,0)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(get_or_create_balance(member).balance,-5)
        self.assertEqual(self.set_balance(-6,0).status_code,409)
        entry=CurrencyTransaction.objects.get(user=self.author)
        self.assertEqual((entry.amount,entry.balance_after,entry.created_by_id),(-5,-5,self.root.pk))
        self.assertEqual(self.client.get('/api/currency/balance').json()['balance'],-5)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.patch(self.url,json.dumps({'action':'balance','balance':-99,
            'expected_balance':-5}),content_type='application/json').status_code,403)
        self.assertEqual(self.balance(),-5)

    def test_member_absolute_and_legacy_relative_admin_adjustments_allow_debt(self):
        url=f'/api/management/teams/{self.team.pk}/members/{self.author_member.pk}/settings'
        result=self.admin.patch(url,json.dumps({'action':'balance','balance':-7,'expected_balance':0}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        result=self.admin.post('/api/currency/admin/adjust',json.dumps({'member_id':self.author_member.pk,
            'amount':-3,'description':'Debt adjustment'}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(self.balance(),-10)
        self.assertEqual(list(CurrencyTransaction.objects.filter(user=self.author).order_by('pk').values_list('amount',flat=True)),[-7,-3])

    def test_full_balance_range_has_exact_64_bit_adjustment_ledger(self):
        for value,expected in [(2147483647,0),(-2147483648,2147483647),(2147483647,-2147483648)]:
            result=self.set_balance(value,expected)
            self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(list(CurrencyTransaction.objects.filter(user=self.author).order_by('pk').values_list('amount',flat=True)),
            [2147483647,-4294967295,4294967295])
        for value in (-2147483649,2147483648,True,1.5,'-2'):
            self.assertEqual(self.set_balance(value,2147483647).status_code,400)
        self.assertEqual(self.balance(),2147483647)
        self.assertEqual(CurrencyTransaction.objects.filter(user=self.author).count(),3)

    def test_adjustment_underflow_is_atomic(self):
        self.assertEqual(self.set_balance(-2147483648,0).status_code,200)
        result=self.admin.post('/api/currency/admin/adjust',json.dumps({'member_id':self.author_member.pk,
            'amount':-1}),content_type='application/json')
        self.assertEqual(result.status_code,400,result.content)
        self.assertEqual(self.balance(),-2147483648)
        self.assertEqual(CurrencyTransaction.objects.filter(user=self.author).count(),1)

    def test_income_pays_down_debt_and_spending_never_borrows(self):
        adjust_currency(self.author_member,-5,'admin_adjust')
        item=ShopItem.objects.create(team=self.team,name='Paid item',item_type='consumable',price=2,stock=4)
        for amount,expected in [(3,-2),(2,0),(4,4)]:
            if self.balance()<2:
                with self.assertRaises(ValueError):purchase_item(self.author_member,item.pk)
                with self.assertRaises(ValueError):deduct_currency(self.author_member,1,'tip_sent')
                self.assertFalse(Purchase.objects.exists());self.assertFalse(UserInventory.objects.exists())
                item.refresh_from_db();self.assertEqual(item.stock,4)
            self.assertEqual(add_currency(self.author_member,amount,'contest_reward'),expected)
        purchase_item(self.author_member,item.pk)
        self.assertEqual(self.balance(),2)
        self.assertEqual(CurrencyBalance.objects.filter(user=self.author).count(),1)

    def test_reward_reversal_can_increase_existing_debt_once(self):
        adjust_currency(self.author_member,-2,'admin_adjust')
        day=timezone.localdate()
        CheckinRecord.objects.create(team=self.team,member=self.author_member,checkin_date=day,reward_amount=3)
        reconcile_submission_day(self.author_member,day,self.semester)
        reconcile_submission_day(self.author_member,day,self.semester)
        self.assertEqual(self.balance(),-5)
        self.assertEqual(CurrencyTransaction.objects.filter(user=self.author,transaction_type='reward_reversal').count(),1)

    def test_reward_underflow_is_rejected_before_deleting_submission(self):
        self.assertEqual(self.set_balance(-2147483648,0).status_code,200)
        row=Submission.objects.create(team=self.team,member=self.author_member,
            semester=self.semester,week=self.week,problem=self.problem)
        CheckinRecord.objects.create(team=self.team,member=self.author_member,
            checkin_date=row.record_date,reward_amount=3)
        self.assertEqual(self.client.get(f'/api/submissions/{row.pk}/reversal-preview',{'action':'delete'}).status_code,400)
        result=self.client.delete(f'/api/submissions/{row.pk}',json.dumps({'version':row.version}),content_type='application/json')
        self.assertEqual(result.status_code,400,result.content)
        self.assertTrue(Submission.objects.filter(pk=row.pk,is_valid=True).exists())
        self.assertTrue(CheckinRecord.objects.filter(member=self.author_member).exists())
        self.assertEqual(self.balance(),-2147483648)
