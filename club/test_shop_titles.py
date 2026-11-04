import json
import uuid
from django.contrib.auth.models import User
from django.test import TestCase, Client
from .models import Team, TeamMembership, ShopItem, OwnedTitle, Purchase, CurrencyBalance
from .currency_services import purchase_item
from .member_titles import available_titles_data, titles_data, validate_title


class ShopTitleTests(TestCase):
    def setUp(self):
        self.root = User.objects.get(username='admin')
        self.user = User.objects.create_user('title-buyer')
        self.team = Team.objects.create(name='Titles',code='TITLES',created_by=self.root,currency_enabled=True)
        self.other = Team.objects.create(name='Other titles',code='TITLE2',created_by=self.root,currency_enabled=True)
        self.member = TeamMembership.objects.create(team=self.team,user=self.user,display_name='Buyer')
        self.second = TeamMembership.objects.create(team=self.other,user=self.user,display_name='Alias')
        self.balance = CurrencyBalance.objects.create(team=self.team,member=self.member,balance=100)
        self.definition = {'text':'星海旅人','color':'#668899','font':'serif','style':'orbit'}
        self.item = ShopItem.objects.create(team=self.team,name='永久星海',price=8,stock=3,item_type='title',title_definition=self.definition)
        self.admin = Client(); self.admin.force_login(self.root)
        self.client.force_login(self.user)
        session=self.client.session;session['team_id']=self.other.pk;session.save()
        self.inventory_url=f'/api/management/teams/{self.team.pk}/members/{self.member.pk}/inventory'

    def post(self,client,url,data):
        return client.post(url,json.dumps(data),content_type='application/json')

    def buy(self,**kwargs):
        return purchase_item(self.member,self.item.pk,request_id=kwargs.pop('request_id',uuid.uuid4()),**kwargs)

    def test_purchase_once_global_wearing_and_snapshot(self):
        token=uuid.uuid4();self.buy(request_id=token);self.buy(request_id=token)
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),1)
        self.balance.refresh_from_db();self.item.refresh_from_db()
        self.assertEqual(self.balance.balance,92);self.assertEqual(self.item.stock,2)
        self.assertEqual(available_titles_data(self.second),[self.definition])
        self.assertEqual(titles_data(self.second),[])  # permanent ownership does not auto-equip
        result=self.post(self.client,'/api/profile/titles/wear',{'title':'星海旅人'})
        self.assertEqual(result.status_code,200,result.content)
        self.second.refresh_from_db();self.assertEqual(titles_data(self.second),[self.definition])
        self.item.title_definition={**self.definition,'color':'#aa6688'};self.item.save()
        self.assertEqual(available_titles_data(self.second),[self.definition])
        self.assertEqual(OwnedTitle.objects.get(user=self.user).inventory.quantity,1)

    def test_global_duplicates_and_quantity_rejected_atomically(self):
        with self.assertRaises(ValueError):self.buy(quantity=2)
        self.buy()
        with self.assertRaises(ValueError):self.buy()
        other=ShopItem.objects.create(team=self.other,name='Same title',price=2,item_type='title',title_definition=self.definition)
        with self.assertRaises(ValueError):purchase_item(self.second,other.pk,request_id=uuid.uuid4())
        self.balance.refresh_from_db();self.assertEqual(self.balance.balance,92)
        self.assertEqual(Purchase.objects.filter(member__user=self.user).count(),1)

    def test_admin_grant_retry_and_global_revoke(self):
        data={'action':'grant','item_id':self.item.pk,'quantity':1,'request_id':str(uuid.uuid4())}
        for _ in range(2):
            result=self.post(self.admin,self.inventory_url,data)
            self.assertEqual(result.status_code,200,result.content)
        owned=OwnedTitle.objects.get(user=self.user)
        self.assertEqual(owned.inventory.quantity,1)
        self.balance.refresh_from_db();self.assertEqual(self.balance.balance,100)
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),1)
        self.second.worn_titles=['星海旅人'];self.second.save()
        result=self.post(self.admin,self.inventory_url,{'action':'quantity','item_id':self.item.pk,'inventory_id':owned.inventory_id,'quantity':0,'expected_quantity':1})
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(available_titles_data(self.second),[])
        self.assertEqual(titles_data(self.second),[])
        self.buy();self.assertEqual(OwnedTitle.objects.filter(user=self.user).count(),1)

    def test_legacy_awards_stay_team_local_and_unowned_title_cannot_be_worn(self):
        self.member.member_title=self.definition;self.member.save()
        self.assertEqual(available_titles_data(self.member),[self.definition])
        self.assertEqual(available_titles_data(self.second),[])
        result=self.post(self.client,'/api/profile/titles/wear',{'title':'星海旅人'})
        self.assertEqual(result.status_code,409)
        with self.assertRaises(ValueError):validate_title({**self.definition,'style':'url(evil)'})
        for style in ('neon','metal','shimmer','orbit'):
            self.assertEqual(validate_title({**self.definition,'style':style})['style'],style)

    def test_shop_admin_validates_and_freezes_title_text_after_purchase(self):
        session=self.admin.session;session['team_id']=self.team.pk;session.save()
        url='/api/currency/admin/shop'
        payload={'name':'New title','price':3,'item_type':'title','title_definition':self.definition}
        result=self.post(self.admin,url,{**payload,'title_definition':{}})
        self.assertEqual(result.status_code,400,result.content)
        self.buy()
        result=self.admin.put(url,json.dumps({**payload,'item_id':self.item.pk,'title_definition':{**self.definition,'text':'Different'}}),content_type='application/json')
        self.assertEqual(result.status_code,400,result.content)

    def test_owned_shop_preview_uses_snapshot_across_teams(self):
        self.buy()
        changed = {**self.definition, 'color':'#aa6688', 'font':'mono', 'style':'neon'}
        self.item.title_definition = changed
        self.item.save()
        session = self.client.session; session['team_id'] = self.team.pk; session.save()
        row = next(r for r in self.client.get('/api/currency/shop/items').json()['items'] if r['id'] == self.item.pk)
        self.assertTrue(row['title_owned'])
        self.assertEqual(row['title_definition'], self.definition)
        duplicate = ShopItem.objects.create(team=self.other, name='Global preview', price=2,
            item_type='title', title_definition=changed)
        session = self.client.session; session['team_id'] = self.other.pk; session.save()
        row = next(r for r in self.client.get('/api/currency/shop/items').json()['items'] if r['id'] == duplicate.pk)
        self.assertTrue(row['title_owned'])
        self.assertEqual(row['title_definition'], self.definition)
        newcomer = User.objects.create_user('new-title-viewer')
        TeamMembership.objects.create(team=self.other, user=newcomer, display_name='New buyer')
        self.client.force_login(newcomer)
        session = self.client.session; session['team_id'] = self.other.pk; session.save()
        row = next(r for r in self.client.get('/api/currency/shop/items').json()['items'] if r['id'] == duplicate.pk)
        self.assertFalse(row['title_owned'])
        self.assertEqual(row['title_definition'], changed)

    def test_ranking_title_queries_are_constant_for_the_roster(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from .rankings import ranking_data
        self.buy()
        self.member.worn_titles = [self.definition['text']]
        self.member.save()
        with CaptureQueriesContext(connection) as first:
            row = ranking_data(self.member, 'checkin')['rows'][0]
        self.assertEqual(row['titles'], [self.definition])
        self.assertEqual(row['title'], self.definition)
        for i in range(39):
            user = User.objects.create_user(f'ranking-title-{i}')
            TeamMembership.objects.create(team=self.team, user=user, display_name=f'Member {i}',
                member_title=self.definition, worn_titles=[self.definition['text']])
        with CaptureQueriesContext(connection) as many:
            rows = ranking_data(self.member, 'checkin')['rows']
        self.assertEqual(len(rows), 40)
        self.assertEqual(len(first), len(many))
        self.assertEqual(sum('club_ownedtitle' in q['sql'] for q in many), 1)
        self.assertTrue(all(r['title'] == self.definition and r['titles'] == [self.definition] for r in rows))
