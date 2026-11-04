import json
import uuid
from django.contrib.auth.models import User
from django.test import TestCase,Client
from .models import Team,TeamMembership,ShopItem,CurrencyBalance,CosmeticGrant,UserProfile
from .currency_services import purchase_item
from .cosmetics import available,badge_data,state


class CosmeticTests(TestCase):
    def setUp(self):
        self.root=User.objects.get(username='admin')
        self.user=User.objects.create_user('cosmetic-owner')
        self.team=Team.objects.create(name='Cosmetics',code='COSMETIC',created_by=self.root,currency_enabled=True)
        self.other=Team.objects.create(name='Elsewhere',code='COSMETIC2',created_by=self.root,currency_enabled=True)
        self.member=TeamMembership.objects.create(team=self.team,user=self.user,display_name='Owner')
        self.second=TeamMembership.objects.create(team=self.other,user=self.user,display_name='Alias')
        self.balance=CurrencyBalance.objects.create(team=self.team,member=self.member,balance=50)
        self.item=ShopItem.objects.create(team=self.team,name='塔菲主题',price=10,stock=5,item_type='theme',cosmetic_key='taffy')
        self.client.force_login(self.user)
        session=self.client.session;session['team_id']=self.other.pk;session.save()
        self.admin=Client();self.admin.force_login(self.root)
        session=self.admin.session;session['team_id']=self.team.pk;session.save()

    def select(self,kind,key):
        return self.client.post('/api/profile/cosmetics',json.dumps({'kind':kind,'key':key}),content_type='application/json')

    def buy(self):
        return purchase_item(self.member,self.item.pk,request_id=uuid.uuid4())

    def test_purchase_gift_and_global_independent_selection(self):
        token=uuid.uuid4()
        for _ in range(2):purchase_item(self.member,self.item.pk,request_id=token)
        self.balance.refresh_from_db();self.item.refresh_from_db()
        self.assertEqual(self.balance.balance,40);self.assertEqual(self.item.stock,4)
        self.assertEqual(CosmeticGrant.objects.filter(user=self.user).count(),3)
        self.assertEqual(len(available(self.user.pk,'badge')),1)
        self.assertEqual(state(self.user)['active_theme'],'')
        self.assertEqual(self.select('badge','taffy').status_code,200)
        self.second.refresh_from_db();self.member.refresh_from_db()
        self.assertEqual(badge_data(self.second)['key'],'taffy')
        self.assertIsNone(badge_data(self.member))
        self.assertIsNone(self.second.worn_titles)
        self.assertEqual(self.select('theme','taffy').status_code,200)
        self.assertEqual(state(self.user)['active_theme'],'taffy')
        self.select('theme','');self.assertEqual(badge_data(self.second)['key'],'taffy')
        self.select('badge','');self.second.refresh_from_db();self.assertIsNone(badge_data(self.second))

    def test_unowned_invalid_and_duplicate_cosmetics_are_rejected(self):
        self.assertEqual(self.select('theme','taffy').status_code,409)
        self.assertEqual(self.select('badge','https://bad.example/').status_code,409)
        with self.assertRaises(ValueError):purchase_item(self.member,self.item.pk,quantity=2)
        self.buy()
        with self.assertRaises(ValueError):self.buy()
        other=ShopItem.objects.create(team=self.other,name='Same theme',price=3,item_type='theme',cosmetic_key='taffy')
        with self.assertRaises(ValueError):purchase_item(self.second,other.pk)
        self.balance.refresh_from_db();self.assertEqual(self.balance.balance,40)

    def test_delisting_preserves_owned_items_and_revoke_disables_them(self):
        self.buy();self.select('theme','taffy');self.select('badge','taffy')
        result=self.admin.put('/api/currency/admin/shop',json.dumps({'item_id':self.item.pk,'is_active':False}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(state(self.user)['active_theme'],'taffy')
        self.assertEqual(self.select('badge','taffy').status_code,200)
        self.item.user_inventories.update(quantity=0)
        self.second.refresh_from_db();self.assertIsNone(badge_data(self.second))
        self.assertEqual(state(self.user)['active_theme'],'')
        self.assertEqual(self.select('theme','taffy').status_code,409)

    def test_badge_purchase_without_theme_and_admin_grant(self):
        badge=ShopItem.objects.create(team=self.team,name='小塔菲',price=2,item_type='badge',cosmetic_key='taffy')
        purchase_item(self.member,badge.pk)
        self.assertEqual(available(self.user.pk,'theme'),[])
        self.assertEqual(len(available(self.user.pk,'badge')),1)
        self.assertEqual(self.select('badge','taffy').status_code,200)
        path=f'/api/management/teams/{self.team.pk}/members/{self.member.pk}/inventory'
        result=self.admin.post(path,json.dumps({'action':'grant','item_id':self.item.pk,'quantity':1,'request_id':str(uuid.uuid4())}),content_type='application/json')
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(CosmeticGrant.objects.filter(user=self.user,kind='badge').count(),2)
        self.item.user_inventories.update(quantity=0)
        self.second.refresh_from_db();self.assertEqual(badge_data(self.second)['key'],'taffy')
        self.balance.refresh_from_db();self.assertEqual(self.balance.balance,48)

    def test_badge_backpack_entry_and_hidden_inactive_stock(self):
        self.item.is_active=False;self.item.save()
        session=self.client.session;session['team_id']=self.team.pk;session.save()
        self.assertEqual(self.client.get('/api/currency/shop/items').json()['items'],[])
        self.item.is_active=True;self.item.save();self.buy()
        data=self.client.get('/api/currency/inventory')
        self.assertEqual(data.status_code,200,data.content)
        self.assertEqual(sorted(row['item_type'] for row in data.json()['inventory']),['badge','frame','theme'])
        self.assertTrue(self.client.get('/api/currency/shop/items').json()['items'][0]['cosmetic_owned'])

    def test_admin_updates_preserve_other_fields_and_validate_catalog(self):
        url='/api/currency/admin/shop'
        for active in (False,True):
            result=self.admin.put(url,json.dumps({'item_id':self.item.pk,'is_active':active}),content_type='application/json')
            self.assertEqual(result.status_code,200,result.content)
        self.item.refresh_from_db();self.assertEqual(self.item.cosmetic_key,'taffy');self.assertEqual(self.item.price,10)
        result=self.admin.post(url,json.dumps({'name':'Unsafe','price':1,'item_type':'theme','cosmetic_key':'unknown'}),content_type='application/json')
        self.assertEqual(result.status_code,400)

    def test_retired_badge_removed_without_changing_theme_original_or_ledger(self):
        from importlib import import_module
        from django.apps import apps
        from .models import UserInventory,Purchase
        self.buy();self.select('theme','taffy')
        legacy=ShopItem.objects.create(team=self.team,name='Old badge',price=3,item_type='badge',cosmetic_key='taffy-head')
        inv=UserInventory.objects.create(team=self.team,member=self.member,item=legacy,quantity=1)
        CosmeticGrant.objects.create(user=self.user,inventory=inv,kind='badge',key='taffy-head')
        purchase=Purchase.objects.create(team=self.team,member=self.member,item=legacy,quantity=1,total_price=3)
        self.second.worn_badge='taffy-head';self.second.save()
        import_module('club.migrations.0062_retire_redrawn_badge').retire_badge(apps,None)
        self.second.refresh_from_db();inv.refresh_from_db();legacy.refresh_from_db();self.balance.refresh_from_db()
        self.assertEqual(self.second.worn_badge,'');self.assertEqual(inv.quantity,0);self.assertFalse(legacy.is_active)
        self.assertTrue(Purchase.objects.filter(pk=purchase.pk).exists());self.assertEqual(self.balance.balance,40)
        self.assertEqual([b['key'] for b in available(self.user.pk,'badge')],['taffy'])
        self.assertEqual(state(self.user)['active_theme'],'taffy')
