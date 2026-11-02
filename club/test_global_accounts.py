import json
import uuid
from django.test import TestCase,Client
from django.contrib.auth.models import User
from django.db.models import Sum
from . import test_community as community_fixtures
from .models import (Team,TeamMembership,CurrencyBalance,ShopItem,UserInventory,Purchase,
    Submission,SubmissionPart,SubmissionReport,ReviewLog,ShopFulfillment)
from .currency_services import add_currency,deduct_currency,get_or_create_balance,purchase_item
from .member_titles import titles_data,awarded_titles_data,validate_title


class GlobalAccountFeatureTests(TestCase):
    def setUp(self):
        community_fixtures.CommunityTests.setUp(self)
        self.root=User.objects.filter(username='admin').first() or User.objects.create_superuser('admin',password='Root!Test234')
        self.admin=Client();self.admin.force_login(self.root)
        self.team.currency_enabled=True;self.team.save()
        self.other=Team.objects.create(name='Other global',code='GLOBAL-B',created_by=self.root,currency_enabled=True)
        self.second=TeamMembership.objects.create(team=self.other,user=self.author,display_name='Other alias')

    def post(self,client,url,data,method='post'):
        return getattr(client,method)(url,json.dumps(data),content_type='application/json')

    def record(self):
        item=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,week=self.week,problem=self.problem)
        SubmissionPart.objects.create(submission=item,kind='proof',status='approved',points_awarded=1)
        SubmissionPart.objects.create(submission=item,kind='logic',text_content='original',status='approved',points_awarded=1)
        SubmissionPart.objects.create(submission=item,kind='code',text_content='```cpp\nold code\n```',status='approved',points_awarded=0)
        return item

    def test_one_wallet_across_teams_and_kick_keeps_assets(self):
        add_currency(self.author_member,10,'admin_adjust');deduct_currency(self.second,4,'purchase')
        self.assertEqual(get_or_create_balance(self.author_member).balance,6)
        self.assertEqual(get_or_create_balance(self.second).balance,6)
        self.assertEqual(CurrencyBalance.objects.filter(user=self.author).count(),1)
        item=ShopItem.objects.create(team=self.team,name='Ticket',item_type='makeup_ticket',price=1)
        inv=UserInventory.objects.create(team=self.team,member=self.author_member,item=item,quantity=2)
        result=self.post(self.admin,f'/api/management/teams/{self.team.pk}/members/{self.author_member.pk}',{'confirmation':self.author_member.display_name},'delete')
        self.assertEqual(result.status_code,200,result.content)
        self.author.refresh_from_db();self.assertTrue(self.author.is_active)
        self.assertTrue(UserInventory.objects.filter(pk=inv.pk,quantity=2).exists())
        self.assertEqual(get_or_create_balance(self.second).balance,6)

    def test_global_backpack_visible_and_consumable_usable_from_other_team(self):
        item=ShopItem.objects.create(team=self.team,name='Consumable',item_type='consumable',price=1)
        add_currency(self.author_member,10,'admin_adjust');purchase_item(self.author_member,item.pk)
        session=self.client.session;session['team_id']=self.other.pk;session.save()
        data=self.client.get('/api/currency/inventory').json()['inventory']
        inv=UserInventory.objects.get(member=self.author_member,item=item)
        self.assertTrue(any(row.get('inventory_id')==inv.pk for row in data))
        response=self.post(self.client,f'/api/currency/inventory/{inv.pk}/use',{'request_id':str(uuid.uuid4())})
        self.assertEqual(response.status_code,200,response.content)
        inv.refresh_from_db();self.assertEqual(inv.quantity,0)
        self.assertEqual(self.client.get('/api/currency/balance').json()['balance'],9)

    def test_global_account_unjoined_balance_optimistic_update(self):
        user=User.objects.create_user('without-team')
        url=f'/api/management/accounts/{user.pk}'
        data=self.post(self.admin,url,{'action':'balance','balance':8,'expected_balance':0},'patch')
        self.assertEqual(data.status_code,200,data.content)
        self.assertEqual(data.json()['balance'],8)
        self.assertEqual(self.post(self.admin,url,{'action':'balance','balance':99,'expected_balance':0},'patch').status_code,409)
        self.assertEqual(CurrencyBalance.objects.get(user=user).balance,8)
        from .models import CurrencyTransaction
        self.assertTrue(CurrencyTransaction.objects.filter(user=user,amount=8,member__isnull=True).exists())
        self.assertEqual(self.client.get(url).status_code,403)

    def test_global_inventory_manage_foreign_team_but_not_foreign_user(self):
        item=ShopItem.objects.create(team=self.team,name='Ticket',item_type='makeup_ticket',price=1)
        inv=UserInventory.objects.create(team=self.team,member=self.author_member,item=item,quantity=3)
        url=f'/api/management/accounts/{self.author.pk}/inventory'
        payload={'action':'quantity','inventory_id':inv.pk,'item_id':item.pk,'expected_quantity':3,'quantity':2}
        self.assertEqual(self.post(self.admin,url,payload).status_code,200)
        inv.refresh_from_db();self.assertEqual(inv.quantity,2)
        self.assertEqual(self.post(self.admin,f'/api/management/accounts/{self.reader.pk}/inventory',payload).status_code,404)

    def test_team_manager_can_edit_own_team_not_other_team(self):
        item=self.record();url=f'/api/management/submissions/{item.pk}'
        data={'logic':'Updated solution','blog':'new blog','code':'int main() {}','code_language':'cpp','version':item.version}
        self.assertEqual(self.post(self.client,url,data,'patch').status_code,403)
        self.client.force_login(self.owner)
        original_date,submitted_at=item.record_date,item.submitted_at
        response=self.post(self.client,url,data,'patch');self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db();self.assertEqual(item.member_id,self.author_member.pk);self.assertEqual(item.record_date,original_date);self.assertEqual(item.submitted_at,submitted_at)
        self.assertEqual(item.parts.aggregate(total=Sum('points_awarded'))['total'],3)
        self.assertTrue(ReviewLog.objects.filter(submission=item,action='admin_edit',actor=self.owner).exists())
        self.assertEqual(self.post(self.client,url,data,'patch').status_code,409)
        outsider=User.objects.create_user('other-manager');TeamMembership.objects.create(team=self.other,user=outsider,display_name='Other manager',role='admin')
        self.client.force_login(outsider);self.assertEqual(self.client.get(url).status_code,404)

    def test_edit_does_not_restore_rejected_submission_or_reward_again(self):
        item=self.record();item.is_valid=False;item.save();before=get_or_create_balance(self.author_member).balance
        response=self.post(self.admin,f'/api/management/submissions/{item.pk}',{'version':item.version,'logic':'changed','code':'x','blog':'','code_language':'text'},'patch')
        self.assertEqual(response.status_code,200,response.content);item.refresh_from_db();self.assertFalse(item.is_valid)
        self.assertFalse(item.parts.exclude(kind='proof').exclude(points_awarded=0).exists())
        self.assertEqual(get_or_create_balance(self.author_member).balance,before)

    def test_manager_cannot_use_admin_editor_to_close_reports_on_own_submission(self):
        from .community_views import community_submission
        item=self.record()
        self.author_member.role='admin';self.author_member.save()
        self.week.is_closed=True;self.week.save()
        report=SubmissionReport.objects.create(submission=item,version=item.version,
            reporter=self.reader,reason='Independent review required')
        before=list(item.parts.order_by('pk').values())
        url=f'/api/management/submissions/{item.pk}'
        self.assertFalse(community_submission(item,self.author_member)['can_admin_edit'])
        self.assertEqual(self.client.get(url).status_code,403)
        response=self.post(self.client,url,{'version':item.version,'logic':'original',
            'code':'old code','blog':'','code_language':'cpp'},'patch')
        self.assertEqual(response.status_code,403,response.content)
        item.refresh_from_db();report.refresh_from_db()
        self.assertEqual(item.version,1)
        self.assertEqual(report.status,'pending')
        self.assertEqual(list(item.parts.order_by('pk').values()),before)
        self.assertFalse(ReviewLog.objects.filter(submission=item,action='admin_edit').exists())
        queue=self.client.get('/api/admin/reports').json()['submissions']
        self.assertFalse(next(r for r in queue if r['id']==item.pk)['can_resolve'])

    def test_title_selection_and_safe_styles_are_team_scoped(self):
        self.author_member.member_title=[{'text':'First','style':'wings','color':'#ab6688','font':'serif'},{'text':'Second','style':'president','color':'#809060','font':'system'}];self.author_member.save()
        result=self.post(self.client,'/api/profile/titles/wear',{'title':'Second'})
        self.assertEqual(result.status_code,200,result.content);self.author_member.refresh_from_db()
        self.assertEqual([t['text'] for t in titles_data(self.author_member)],['Second'])
        self.assertEqual(len(awarded_titles_data(self.author_member)),2)
        self.second.refresh_from_db();self.assertIsNone(self.second.worn_titles)
        self.assertEqual(self.post(self.client,'/api/profile/titles/wear',{'title':'Not awarded'}).status_code,409)
        self.assertEqual(self.post(self.client,'/api/profile/titles/wear',{'title':None}).json()['titles'],[])
        for style in ('arbitrary',{},'url(javascript:bad)'):
            with self.assertRaises(ValueError):validate_title({'text':'bad','style':style})

    def test_new_report_prevents_dismissing_unseen_reasons(self):
        item=self.record();first=SubmissionReport.objects.create(submission=item,version=item.version,reporter=self.reader,reason='First reason')
        self.client.force_login(self.owner)
        queue=self.client.get('/api/admin/reports').json()['submissions'];self.assertEqual(len(queue),1)
        extra=User.objects.create_user('extra-reporter');SubmissionReport.objects.create(submission=item,version=item.version,reporter=extra,reason='New reason')
        url=f'/api/admin/reports/{item.pk}/resolve'
        response=self.post(self.client,url,{'action':'dismiss','version':item.version,'report_snapshot':[{'id':first.pk,'generation':first.generation}]})
        self.assertEqual(response.status_code,409,response.content)
        self.assertEqual(item.reports.filter(status='pending').count(),2)
        response=self.post(self.client,url,{'action':'dismiss','version':item.version,'report_snapshot':community_fixtures.report_snapshot(item)})
        self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(item.reports.filter(status='pending').exists())

    def test_wallet_migration_sums_legacy_balances_and_links_global_ledger(self):
        import importlib
        from django.apps import apps
        from .models import CurrencyTransaction
        CurrencyBalance.objects.bulk_create([
            CurrencyBalance(team=self.team,member=self.author_member,balance=12),
            CurrencyBalance(team=self.other,member=self.second,balance=7)])
        CurrencyTransaction.objects.bulk_create([CurrencyTransaction(team=self.team,member=self.author_member,amount=12,balance_after=12,transaction_type='admin_adjust')])
        importlib.import_module('club.migrations.0046_global_wallet_and_worn_titles').merge_wallets(apps,None)
        self.assertEqual(CurrencyBalance.objects.get(user=self.author).balance,19)
        self.assertEqual(CurrencyBalance.objects.filter(member__user=self.author).count(),1)
        self.assertTrue(CurrencyTransaction.objects.filter(user=self.author,amount=12).exists())
