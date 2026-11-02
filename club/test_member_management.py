import json
import uuid

from django.contrib.admin.models import LogEntry
from django.contrib.auth.models import User
from django.test import TestCase, Client

from .models import (Team, TeamMembership, CurrencyBalance, CurrencyTransaction,
                     ShopItem, UserInventory, Purchase, ShopFulfillment, ShopCode)
from .shop_fulfillment import append_codes


class MemberManagementTests(TestCase):
    def setUp(self):
        self.root = User.objects.filter(username='admin').first() or User.objects.create_superuser('admin',password='RootTest!234')
        self.client.force_login(self.root)
        self.user = User.objects.create_user('member-edit',password='OriginalPassword!234')
        self.team = Team.objects.create(name='Maintenance',code='MAINT',created_by=self.root,currency_enabled=True)
        self.other = Team.objects.create(name='Other',code='OTHERMAINT',created_by=self.root)
        self.member = TeamMembership.objects.create(team=self.team,user=self.user,display_name='Alice')
        self.other_member = TeamMembership.objects.create(team=self.other,user=self.user,display_name='Elsewhere')
        self.base = f'/api/management/teams/{self.team.pk}/members'
        self.url = f'{self.base}/{self.member.pk}/settings'
        self.inventory_url = f'{self.base}/{self.member.pk}/inventory'

    def patch(self, data):
        return self.client.patch(self.url,json.dumps(data),content_type='application/json')

    def inventory(self, data):
        return self.client.post(self.inventory_url,json.dumps(data),content_type='application/json')

    def profile(self, **changes):
        return self.patch({'action':'profile','name':'Alice','account':'member-edit','role':'member',**changes})

    def test_only_system_admin_can_read_or_write(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.base).status_code,401)
        self.client.force_login(self.user)
        self.member.role='admin';self.member.save()
        for url in (self.base,self.url):
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.profile(name='No').status_code,403)
        self.assertEqual(self.inventory({'action':'grant'}).status_code,403)

    def test_scope_and_no_password_or_code_in_read_results(self):
        result=self.client.get(self.url)
        self.assertEqual(result.status_code,200)
        self.assertEqual(result['Cache-Control'],'no-store')
        self.assertNotIn('password',result.content.decode())
        self.assertNotIn(self.user.password,result.content.decode())
        self.assertEqual(self.client.get(f'{self.base}/{self.other_member.pk}/settings').status_code,404)
        sandbox=User.objects.create_user('__club_test_hidden',first_name='CLUB_TEST_SANDBOX')
        TeamMembership.objects.create(team=self.team,user=sandbox,display_name='Private')
        self.assertEqual(len(self.client.get(self.base).json()['members']),1)

    def test_profile_changes_are_scoped_and_password_is_hashed(self):
        response=self.profile(name='New name',account='changed-account',role='admin',password='FreshPassword!987')
        self.assertEqual(response.status_code,200,response.content)
        self.user.refresh_from_db();self.member.refresh_from_db();self.other_member.refresh_from_db()
        self.assertTrue(self.user.check_password('FreshPassword!987'))
        self.assertNotEqual(self.user.password,'FreshPassword!987')
        self.assertEqual(self.member.role,'admin')
        self.assertEqual(self.other_member.display_name,'Elsewhere')
        self.assertEqual(self.other_member.role,'member')
        self.assertIn('团队管理用户组',self.user.groups.values_list('name',flat=True))
        audit=LogEntry.objects.latest('id')
        self.assertNotIn('FreshPassword!987',audit.change_message)
        self.assertNotIn('FreshPassword!987',response.content.decode())
        reader=Client();self.assertTrue(reader.login(username='changed-account',password='FreshPassword!987'))

    def test_blank_password_preserves_existing_login_and_invalid_edit_is_atomic(self):
        original=self.user.password
        self.assertEqual(self.profile(password='').status_code,200)
        self.user.refresh_from_db();self.assertEqual(self.user.password,original)
        self.assertEqual(self.profile(name='Must not save',password='short').status_code,400)
        self.member.refresh_from_db();self.assertEqual(self.member.display_name,'Alice')
        self.assertEqual(self.profile(account='admin').status_code,400)
        self.assertEqual(self.profile(account='__club_test_reserved').status_code,400)
        self.assertEqual(self.profile(role='owner').status_code,400)

    def test_duplicate_names_or_accounts_do_not_overwrite(self):
        duplicate=User.objects.create_user('already-used')
        TeamMembership.objects.create(team=self.team,user=duplicate,display_name='Taken')
        self.assertEqual(self.profile(account='already-used').status_code,400)
        self.assertEqual(self.profile(name='Taken').status_code,400)
        self.member.refresh_from_db();self.assertEqual(self.member.display_name,'Alice')

    def test_balance_has_ledger_allows_debt_and_rejects_stale_values(self):
        CurrencyBalance.objects.create(team=self.team,member=self.member,balance=5)
        self.assertEqual(self.patch({'action':'balance','balance':12,'expected_balance':5}).status_code,200)
        self.assertEqual(CurrencyTransaction.objects.get(member=self.member).amount,7)
        self.assertEqual(self.patch({'action':'balance','balance':12,'expected_balance':5}).status_code,409)
        self.assertEqual(CurrencyTransaction.objects.filter(member=self.member).count(),1)
        self.assertEqual(self.patch({'action':'balance','balance':-1,'expected_balance':12}).status_code,200)
        self.assertEqual(self.patch({'action':'balance','balance':3,'expected_balance':-1}).status_code,200)
        self.assertEqual(CurrencyBalance.objects.get(member=self.member).balance,3)

    def test_grants_are_idempotent_and_quantity_adjustment_cannot_mint_items(self):
        item=ShopItem.objects.create(team=self.team,name='Ticket',price=3,stock=5,item_type='makeup_ticket')
        data={'action':'grant','item_id':item.pk,'quantity':2,'request_id':str(uuid.uuid4())}
        for _ in range(2): self.assertEqual(self.inventory(data).status_code,200)
        self.assertEqual(Purchase.objects.filter(member=self.member).count(),1)
        self.assertEqual(Purchase.objects.get(member=self.member).total_price,0)
        self.assertEqual(UserInventory.objects.get(member=self.member,item=item).quantity,2)
        item.refresh_from_db();self.assertEqual(item.stock,3)
        self.assertEqual(self.inventory({'action':'quantity','item_id':item.pk,'quantity':3,'expected_quantity':2}).status_code,400)
        self.assertEqual(self.inventory({'action':'quantity','item_id':item.pk,'quantity':1,'expected_quantity':2}).status_code,200)
        self.assertEqual(self.inventory({'action':'quantity','item_id':item.pk,'quantity':0,'expected_quantity':2}).status_code,409)

    def test_card_grant_reserves_stock_and_only_unused_unit_can_be_revoked(self):
        item=ShopItem.objects.create(team=self.team,name='Card',price=5,stock=2,item_type='redeem_code')
        append_codes(item,['private-card-1'])
        data={'action':'grant','item_id':item.pk,'quantity':1,'request_id':str(uuid.uuid4())}
        result=self.inventory(data);self.assertEqual(result.status_code,200,result.content)
        self.assertNotIn('private-card-1',result.content.decode())
        unit=ShopFulfillment.objects.get(purchase__member=self.member)
        self.assertTrue(ShopCode.objects.filter(reserved_for=unit).exists())
        self.assertEqual(self.inventory({'action':'revoke','unit_id':unit.pk}).status_code,200)
        self.assertFalse(ShopCode.objects.filter(reserved_for=unit).exists())
        item.refresh_from_db();self.assertEqual(item.stock,2)
        self.assertEqual(self.inventory({'action':'revoke','unit_id':unit.pk}).status_code,400)
        unit.status='redeemed';unit.save()
        self.assertEqual(self.inventory({'action':'revoke','unit_id':unit.pk}).status_code,400)

    def test_failed_card_grant_rolls_back_all_changes(self):
        item=ShopItem.objects.create(team=self.team,name='Empty',price=5,stock=2,item_type='redeem_code')
        response=self.inventory({'action':'grant','item_id':item.pk,'quantity':1,'request_id':str(uuid.uuid4())})
        self.assertEqual(response.status_code,400)
        self.assertFalse(Purchase.objects.filter(member=self.member).exists())
        item.refresh_from_db();self.assertEqual(item.stock,2)
        foreign=ShopItem.objects.create(team=self.other,name='Foreign',price=1)
        self.assertEqual(self.inventory({'action':'grant','item_id':foreign.pk,'quantity':1,'request_id':str(uuid.uuid4())}).status_code,404)

    def test_physical_grant_starts_dispatching_without_charging_coins(self):
        item=ShopItem.objects.create(team=self.team,name='Gift',price=5,stock=2,item_type='physical')
        result=self.inventory({'action':'grant','item_id':item.pk,'quantity':1,'request_id':str(uuid.uuid4())})
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(ShopFulfillment.objects.get(purchase__member=self.member).status,'dispatching')
        self.assertFalse(CurrencyTransaction.objects.filter(member=self.member).exists())

    def test_title_is_team_scoped_and_visible_in_rankings_and_profile(self):
        title={'text':'算法新星','color':'#A86889','font':'serif'}
        response=self.patch({'action':'title','title':title})
        self.assertEqual(response.status_code,200,response.content)
        expected={**title,'color':'#a86889'}
        self.assertEqual(response.json()['title'],expected)
        self.other_member.refresh_from_db();self.assertEqual(self.other_member.member_title,[])
        self.member.refresh_from_db()
        from .rankings import ranking_data
        row=next(r for r in ranking_data(self.member,'checkin')['rows'] if r['memberId']==self.member.pk)
        self.assertEqual(row['title'],expected)
        profile=self.client.get(f'/api/members/{self.member.pk}/profile')
        self.assertEqual(profile.status_code,200,profile.content)
        self.assertEqual(profile.json()['member']['title'],expected)

    def test_title_rejects_css_injection_and_can_be_removed(self):
        self.assertEqual(self.patch({'action':'title','title':{'text':'Valid','color':'#a86889','font':'mono'}}).status_code,200)
        for title in [
            {'text':'X','color':'red;position:fixed'},
            {'text':'X','font':'url(https://example.com)'},
            {'text':'X'*21}, {'text':'X\nY'}, {'text':'X','background':'red'},
        ]:
            self.assertEqual(self.patch({'action':'title','title':title}).status_code,400)
        self.member.refresh_from_db();self.assertEqual(self.member.member_title['text'],'Valid')
        self.assertEqual(self.patch({'action':'title','title':{'text':''}}).status_code,200)
        self.member.refresh_from_db();self.assertEqual(self.member.member_title,{})

    def test_members_cannot_grant_themselves_titles(self):
        self.client.force_login(self.user)
        self.assertEqual(self.patch({'action':'title','title':{'text':'Cannot grant'}}).status_code,403)

    def test_multiple_titles_keep_individual_colors_fonts_and_order(self):
        titles=[{'text':'算法新星','color':'#a86889','font':'serif'},{'text':'训练达人','color':'#559b8a','font':'mono'}]
        response=self.patch({'action':'titles','titles':titles})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['titles'],titles)
        self.assertEqual(response.json()['title'],titles[0])
        self.assertEqual(self.patch({'action':'titles','titles':titles+titles}).status_code,400)
        self.assertEqual(self.patch({'action':'titles','titles':[{'text':str(i)} for i in range(9)]}).status_code,400)
        self.assertEqual(self.patch({'action':'titles','titles':[]}).json()['titles'],[])

    def test_admin_can_correct_global_admission_year_without_changing_titles(self):
        result=self.patch({'action':'admission_year','admission_year':2025})
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()['cohort']['squad_number'],13)
        self.client.force_login(self.user)
        self.assertEqual(self.patch({'action':'admission_year','admission_year':2026}).status_code,403)
