import json
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import Client, TestCase
from . import test_community as fixtures
from .models import (AccountClosure,TeamMembership,Team,UserProfile,PlatformBinding,
    CurrencyBalance,ShopItem,Purchase,UserInventory,Submission,SubmissionPart,SubmissionReport)


class AccountLifecycleTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.root=User.objects.filter(username='admin').first() or User.objects.create_superuser('admin',password='RootPass!Test123')
        self.root.set_password('RootPass!Test123');self.root.save(update_fields=['password'])
        self.admin=Client();self.admin.force_login(self.root)
    def post(self,client,url,data):return client.post(url,json.dumps(data),content_type='application/json')
    def close(self,client=None,**extra):return self.post(client or self.client,'/api/account/close',{'confirmation':'注销账号','password':'test-password',**extra})

    def test_admin_lists_unjoined_accounts_but_team_manager_cannot(self):
        user=User.objects.create_user('no-team-account',password='LongPass!123')
        result=self.admin.get('/api/management/accounts?q=no-team-account')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['accounts'][0]['teams'],[])
        self.assertNotIn('password',result.content.decode())
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/api/management/accounts').status_code,403)
        self.assertEqual(self.client.patch(f'/api/management/accounts/{user.pk}',json.dumps({'account':'wrong'}),content_type='application/json').status_code,403)

    def test_global_login_update_preserves_all_team_aliases(self):
        other=Team.objects.create(name='Other',code='GLOBALOTHER',created_by=self.root)
        second=TeamMembership.objects.create(team=other,user=self.author,display_name='Other alias')
        result=self.admin.patch(f'/api/management/accounts/{self.author.pk}',json.dumps({'account':'global-new-login','password':'GlobalPassword!234'}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.author.refresh_from_db();self.author_member.refresh_from_db();second.refresh_from_db()
        self.assertEqual(self.author_member.display_name,'A同学');self.assertEqual(second.display_name,'Other alias')
        self.assertTrue(self.author.check_password('GlobalPassword!234'))
        self.assertEqual(self.author.username,'global-new-login')

    def test_self_closure_requires_password_and_explicit_confirmation(self):
        self.assertEqual(self.close(password='bad').status_code,403)
        self.assertEqual(self.close(confirmation='wrong').status_code,400)
        self.author.refresh_from_db();self.assertTrue(self.author.is_active)
        self.assertFalse(AccountClosure.objects.filter(user=self.author).exists())

    def test_closure_stops_every_team_identity_and_keeps_accounting(self):
        other=Team.objects.create(name='Second',code='SECONDCLOSE',created_by=self.root)
        second=TeamMembership.objects.create(team=other,user=self.author,display_name='Second name',role='admin')
        PlatformBinding.objects.create(user=self.author,platform='leetcode',account='cn:private-account',encrypted_credentials='sensitive')
        CurrencyBalance.objects.create(team=self.team,member=self.author_member,balance=12)
        item=ShopItem.objects.create(team=self.team,name='Owned',price=3)
        purchase=Purchase.objects.create(team=self.team,member=self.author_member,item=item,quantity=1,total_price=3)
        inv=UserInventory.objects.create(team=self.team,member=self.author_member,item=item,quantity=1)
        other_session=Client();other_session.force_login(self.author)
        response=self.close();self.assertEqual(response.status_code,200,response.content)
        self.author.refresh_from_db();self.author_member.refresh_from_db();second.refresh_from_db()
        self.assertFalse(self.author.is_active);self.assertFalse(self.author.has_usable_password())
        self.assertFalse(self.author_member.is_active);self.assertFalse(second.is_active)
        self.assertEqual(second.role,'member');self.assertTrue(second.display_name.startswith('已注销用户'))
        self.assertEqual(CurrencyBalance.objects.get(member=self.author_member).balance,12)
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists());inv.refresh_from_db();self.assertEqual(inv.quantity,1)
        self.assertFalse(PlatformBinding.objects.filter(user=self.author).exists())
        self.assertEqual(other_session.get('/api/account').status_code,401)
        self.assertEqual(AccountClosure.objects.filter(user=self.author).count(),1)

    def test_unjoined_user_can_close_and_root_cannot_close_itself(self):
        user=User.objects.create_user('unjoined-close',password='test-password');self.client.force_login(user)
        self.assertEqual(self.client.get('/api/account').status_code,200)
        self.assertEqual(self.close().status_code,200)
        self.assertEqual(self.close(client=self.admin,password='RootPass!Test123').status_code,403)

    def test_admin_closure_requires_root_password_and_exact_target(self):
        url=f'/api/management/accounts/{self.author.pk}/close'
        payload={'confirmation':'注销账号','account':'author','admin_password':'bad'}
        self.assertEqual(self.post(self.admin,url,payload).status_code,403)
        payload['admin_password']='RootPass!Test123';payload['account']='stale'
        self.assertEqual(self.post(self.admin,url,payload).status_code,409)
        payload['account']='author';self.assertEqual(self.post(self.admin,url,payload).status_code,200)
        self.assertEqual(self.post(self.admin,url,payload).status_code,409)
        self.assertEqual(self.admin.get('/api/management/accounts').status_code,200)


class ReportReasonTests(TestCase):
    setUp=fixtures.CommunityTests.setUp
    def submit_record(self):
        record=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem)
        SubmissionPart.objects.create(submission=record,kind='proof',status='approved',points_awarded=1)
        return record
    def report(self,record,reason='截图与题目不符'):
        return self.client.post(f'/api/submissions/{record.pk}/report',json.dumps({'reason':reason}),content_type='application/json')

    def test_reason_is_required_when_supplied_and_duplicates_are_idempotent(self):
        record=self.submit_record();self.client.force_login(self.reader)
        self.assertEqual(self.report(record,' ').status_code,400)
        self.assertEqual(self.report(record,'x'*501).status_code,400)
        with patch('club.astrbot_notifications.notify_report') as notify:
            self.assertEqual(self.report(record).status_code,200);self.assertEqual(self.report(record).status_code,200)
            self.assertEqual(notify.call_count,1)
        self.assertEqual(record.reports.get().reason,'截图与题目不符')

    def test_cancel_is_scoped_and_rereport_keeps_history_generation(self):
        record=self.submit_record();self.client.force_login(self.reader);self.report(record)
        url=f'/api/submissions/{record.pk}/report'
        self.client.force_login(self.owner);self.client.delete(url)
        self.assertEqual(record.reports.get().status,'pending')
        self.client.force_login(self.reader)
        self.assertEqual(self.client.delete(url).status_code,200)
        self.assertEqual(record.reports.get().status,'cancelled')
        self.assertEqual(self.client.delete(url).status_code,200)
        self.assertEqual(self.report(record,'补充新的材料问题').status_code,200)
        report=record.reports.get();self.assertEqual(report.generation,2);self.assertEqual(report.status,'pending')

    def test_resolved_report_cannot_be_cancelled_or_reopened(self):
        record=self.submit_record();self.client.force_login(self.reader);self.report(record)
        self.client.force_login(self.owner)
        result=self.client.post(f'/api/admin/reports/{record.pk}/resolve',json.dumps({'action':'dismiss','version':record.version}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.client.force_login(self.reader)
        self.assertEqual(self.client.delete(f'/api/submissions/{record.pk}/report').status_code,409)
        self.report(record);self.assertEqual(record.reports.get().status,'dismissed')

    def test_reasons_only_appear_in_moderation_queue(self):
        record=self.submit_record();self.client.force_login(self.reader);self.report(record,'需要人工核对截图')
        self.assertEqual(self.client.get('/api/admin/reports').status_code,403)
        public=self.client.get(f'/api/problems/{self.problem.pk}/submissions').json()
        self.assertNotIn('需要人工核对截图',json.dumps(public,ensure_ascii=False))
        self.client.force_login(self.owner)
        data=self.client.get('/api/admin/reports').json()['submissions'][0]
        self.assertEqual(data['report_reasons'],['需要人工核对截图'])
