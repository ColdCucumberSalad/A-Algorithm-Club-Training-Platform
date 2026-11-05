import json
import uuid
from importlib import import_module
from types import SimpleNamespace
from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from .models import Team,TeamMembership,ShopItem,CurrencyBalance,Purchase,PurchaseBadgeGrant,UserInventory
from .currency_services import purchase_item
from .cosmetics import available,badge_data,cache_equipped


class PendantBadgeTests(TestCase):
    def setUp(self):
        self.root=User.objects.get(username='admin')
        self.user=User.objects.create_user('pendant-buyer')
        self.team=Team.objects.create(name='Pendant',code='PENDANT',created_by=self.root,currency_enabled=True)
        self.member=TeamMembership.objects.create(team=self.team,user=self.user,display_name='Buyer')
        self.balance=CurrencyBalance.objects.create(team=self.team,member=self.member,balance=100)
        self.item=ShopItem.objects.create(team=self.team,name='RBC挂坠',item_type='physical',price=3,stock=5,gift_badge_key='rbc-pendant')
        self.client.force_login(self.user)
        session=self.client.session;session['team_id']=self.team.pk;session.save()

    def test_purchase_and_retry_keep_one_permanent_gift_and_physical_delivery(self):
        token=uuid.uuid4()
        for _ in range(2):purchase_item(self.member,self.item.pk,2,token)
        purchase_item(self.member,self.item.pk,1,uuid.uuid4())
        self.assertEqual(PurchaseBadgeGrant.objects.filter(user=self.user).count(),1)
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),2)
        self.assertEqual(list(Purchase.objects.filter(item=self.item).values_list('fulfillments__status',flat=True)),['dispatching']*3)
        self.assertFalse(UserInventory.objects.filter(member=self.member,item=self.item).exists())
        self.balance.refresh_from_db();self.item.refresh_from_db()
        self.assertEqual(self.balance.balance,91);self.assertEqual(self.item.stock,2)
        badge=available(self.user.pk,'badge')[0]
        self.assertEqual(badge['key'],'rbc-pendant');self.assertIsNone(badge['expires_at'])
        response=self.client.get('/api/currency/inventory')
        gifts=[r for r in response.json()['inventory'] if r['item_type']=='badge']
        self.assertEqual(len(gifts),1);self.assertIsNone(gifts[0]['expires_at'])
        response=self.client.post('/api/profile/cosmetics',json.dumps({'kind':'badge','key':'rbc-pendant'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)

    def test_global_wearing_cache_and_later_product_edits(self):
        purchase_item(self.member,self.item.pk)
        other=Team.objects.create(name='Other',code='PENDANT2',created_by=self.root)
        alias=TeamMembership.objects.create(team=other,user=self.user,display_name='Alias',worn_badge='rbc-pendant')
        cache_equipped([alias]);self.assertEqual(badge_data(alias)['key'],'rbc-pendant')
        self.item.gift_badge_key='';self.item.name='Renamed';self.item.is_active=False;self.item.save()
        self.assertEqual(available(self.user.pk,'badge')[0]['key'],'rbc-pendant')
        self.assertIsNone(badge_data(self.member))

    def test_failed_and_ordinary_purchases_award_nothing(self):
        self.balance.balance=0;self.balance.save()
        with self.assertRaises(ValueError):purchase_item(self.member,self.item.pk)
        self.assertFalse(PurchaseBadgeGrant.objects.exists())
        self.balance.balance=100;self.balance.save()
        self.item.gift_badge_key='';self.item.save();purchase_item(self.member,self.item.pk)
        self.assertFalse(PurchaseBadgeGrant.objects.exists())

    def test_admin_configuration_and_grant(self):
        self.client.force_login(self.root)
        session=self.client.session;session['team_id']=self.team.pk;session.save()
        url='/api/currency/admin/shop'
        for value in ['unknown',True,[],None]:
            response=self.client.put(url,json.dumps({'item_id':self.item.pk,'gift_badge_key':value}),content_type='application/json')
            self.assertEqual(response.status_code,400,response.content)
        response=self.client.put(url,json.dumps({'item_id':self.item.pk,'gift_badge_key':'rbc-pendant'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        path=f'/api/management/teams/{self.team.pk}/members/{self.member.pk}/inventory'
        payload={'action':'grant','item_id':self.item.pk,'quantity':1,'request_id':str(uuid.uuid4())}
        for _ in range(2):
            response=self.client.post(path,json.dumps(payload),content_type='application/json')
            self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(PurchaseBadgeGrant.objects.count(),1)
        self.assertEqual(Purchase.objects.get(item=self.item).total_price,0)
        self.balance.refresh_from_db();self.assertEqual(self.balance.balance,100)

    def test_migration_backfills_exact_pendant_only_and_ignores_reclaimed_purchase(self):
        self.item.gift_badge_key='';self.item.name='ＲＢＣ 挂坠';self.item.save()
        purchase_item(self.member,self.item.pk)
        self.assertFalse(PurchaseBadgeGrant.objects.exists())
        ordinary=ShopItem.objects.create(team=self.team,name='Other挂坠',item_type='physical',price=1)
        cancelled=ShopItem.objects.create(team=self.team,name='rbc挂坠',item_type='physical',price=1)
        purchase_item(self.member,cancelled.pk)
        Purchase.objects.filter(item=cancelled).first().fulfillments.update(status='reclaimed')
        migrate=import_module('club.migrations.0065_rbc_pendant_badge').configure_pendants
        editor=SimpleNamespace(connection=SimpleNamespace(alias='default'))
        migrate(apps,editor);migrate(apps,editor)
        self.item.refresh_from_db();ordinary.refresh_from_db()
        self.assertEqual(self.item.gift_badge_key,'rbc-pendant');self.assertEqual(ordinary.gift_badge_key,'')
        self.assertEqual(PurchaseBadgeGrant.objects.count(),1)
        self.assertEqual(PurchaseBadgeGrant.objects.get().purchase.item_id,self.item.pk)
