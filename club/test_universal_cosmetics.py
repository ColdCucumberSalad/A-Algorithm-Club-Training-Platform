import io
import json
import tempfile
import uuid
import zipfile
from datetime import timedelta
from unittest.mock import patch
from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings,Client
from django.utils import timezone
from .models import Team,TeamMembership,ShopItem,CurrencyBalance,CosmeticAsset,CosmeticGrant,Purchase
from .currency_services import purchase_item
from .cosmetics import available,state,badge_data,cache_equipped
from .cosmetic_assets import PALETTES,store_image


class UniversalCosmeticTests(TestCase):
    def setUp(self):
        self.media=tempfile.TemporaryDirectory();self.addCleanup(self.media.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.media.name);self.override.enable();self.addCleanup(self.override.disable)
        self.root=User.objects.get(username='admin');self.user=User.objects.create_user('resource-buyer')
        self.team=Team.objects.create(name='Resources',code='RESOURCES',created_by=self.root,currency_enabled=True)
        self.member=TeamMembership.objects.create(team=self.team,user=self.user,display_name='Buyer')
        CurrencyBalance.objects.create(team=self.team,member=self.member,balance=1000)
        self.client.force_login(self.root);session=self.client.session;session['team_id']=self.team.pk;session.save()
        self.owner=Client();self.owner.force_login(self.user);session=self.owner.session;session['team_id']=self.team.pk;session.save()
        raw=io.BytesIO();Image.new('RGBA',(32,32),'#a67799').save(raw,format='PNG');self.image=raw.getvalue();self.url=store_image(self.image)

    def post(self,url,data,client=None):return (client or self.client).post(url,json.dumps(data),content_type='application/json')
    def asset(self,kind,key,days=30):
        data={'kind':kind,'key':key,'name':key,'icon':self.url,'duration_days':days}
        if kind=='theme':data.update(background=self.url,palettes=PALETTES)
        response=self.post('/api/management/cosmetic-assets',data)
        self.assertEqual(response.status_code,200,response.content)
        return response.json()['asset']

    def shop(self):
        entries=[self.asset('theme','garden',1),self.asset('badge','garden',0),self.asset('frame','garden',3)]
        response=self.post('/api/currency/admin/shop',{'name':'Garden','price':5,'stock':-1,'is_active':True,'item_type':'cosmetic','cosmetic_bundle':[{'kind':a['kind'],'key':a['key'],'days':a['duration_days']} for a in entries]})
        self.assertEqual(response.status_code,200,response.content)
        return ShopItem.objects.get(team=self.team,name='Garden')

    def test_bundle_independent_expiry_renewal_and_idempotent_purchase_snapshot(self):
        item=self.shop();start=timezone.now()
        with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,item.pk,request_id=uuid.uuid4())
        self.assertEqual(CosmeticGrant.objects.filter(user=self.user).count(),3)
        self.assertIsNone(CosmeticGrant.objects.get(user=self.user,kind='badge').expires_at)
        with patch('django.utils.timezone.now',return_value=start+timedelta(days=1)):
            self.assertEqual(available(self.user.pk,'theme'),[])
            self.assertEqual(len(available(self.user.pk,'badge')),1);self.assertEqual(len(available(self.user.pk,'frame')),1)
            token=uuid.uuid4();purchase_item(self.member,item.pk,request_id=token);purchase_item(self.member,item.pk,request_id=token)
        self.assertEqual(CosmeticGrant.objects.get(user=self.user,kind='theme').expires_at,start+timedelta(days=2))
        self.assertEqual(CosmeticGrant.objects.get(user=self.user,kind='frame').expires_at,start+timedelta(days=6))
        self.assertEqual(Purchase.objects.filter(item=item).count(),2)
        first=Purchase.objects.filter(item=item).earliest('pk');last=Purchase.objects.filter(item=item).latest('pk')
        self.assertNotEqual(first.cosmetic_snapshot,last.cosmetic_snapshot)
        self.assertEqual(self.post('/api/profile/cosmetics',{'kind':'badge','key':'garden'},self.owner).status_code,200)
        self.member.refresh_from_db();cache_equipped([self.member]);self.assertEqual(badge_data(self.member)['key'],'garden')

    def test_catalog_edit_does_not_replace_purchased_theme_and_stale_writes_fail(self):
        item=self.shop();purchase_item(self.member,item.pk)
        before=state(self.user)['themes'][0]
        asset=CosmeticAsset.objects.get(kind='theme',key='garden')
        data={**asset.definition,'revision':asset.revision,'name':'New garden','palettes':{**PALETTES,'light':{**PALETTES['light'],'accent':'#123456'}}}
        response=self.post('/api/management/cosmetic-assets',data);self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(state(self.user)['themes'][0],before)
        self.assertEqual(self.post('/api/management/cosmetic-assets',data).status_code,400)
        response=self.owner.get('/api/currency/shop/items');self.assertEqual(response.status_code,200,response.content)
        self.assertFalse(response.json()['items'][0]['purchase_blocked'])

    def test_revoked_bundle_does_not_restore_omitted_grants_after_contents_change(self):
        for days in (5,0):
            with self.subTest(original_days=days):
                old,new=f'old-{days}',f'new-{days}'
                self.asset('badge',old,days);self.asset('badge',new,1)
                item=ShopItem.objects.create(team=self.team,name=old,item_type='cosmetic',price=1,
                    cosmetic_bundle=[{'kind':'badge','key':old,'days':days}])
                start=timezone.now()
                with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,item.pk)
                grant=CosmeticGrant.objects.get(user=self.user,key=old)
                grant.inventory.quantity=0;grant.inventory.save(update_fields=['quantity'])
                item.cosmetic_bundle=[{'kind':'badge','key':new,'days':1}];item.save(update_fields=['cosmetic_bundle'])
                with patch('django.utils.timezone.now',return_value=start+timedelta(days=1)):
                    purchase_item(self.member,item.pk)
                    keys={row['key'] for row in available(self.user.pk,'badge')}
                self.assertNotIn(old,keys);self.assertIn(new,keys)
                grant.refresh_from_db();self.assertEqual(grant.expires_at,start+timedelta(days=1))
                self.assertEqual(Purchase.objects.filter(item=item).count(),2)

    def test_revoked_title_renewal_starts_from_the_new_purchase(self):
        item=ShopItem.objects.create(team=self.team,name='Revoked title',price=1,item_type='title',
            cosmetic_duration_days=7,title_definition={'text':'Revoked','font':'system','style':'plain','color':'#aa7788'})
        from .models import OwnedTitle
        start=timezone.now()
        with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,item.pk)
        owned=OwnedTitle.objects.get(user=self.user,text='Revoked')
        owned.inventory.quantity=0;owned.inventory.save(update_fields=['quantity'])
        item.cosmetic_duration_days=1;item.save(update_fields=['cosmetic_duration_days'])
        with patch('django.utils.timezone.now',return_value=start+timedelta(days=1)):purchase_item(self.member,item.pk)
        owned.refresh_from_db();self.assertEqual(owned.expires_at,start+timedelta(days=2))
        self.assertEqual(Purchase.objects.filter(item=item).latest('pk').cosmetic_expires_at,owned.expires_at)

    def test_repurchase_does_not_restore_revoked_finite_or_permanent_rights(self):
        for original_days in (5,0):
            with self.subTest(original_days=original_days):
                key=f'revoked-{original_days}'
                self.asset('badge',key,original_days)
                item=ShopItem.objects.create(team=self.team,name=key,item_type='cosmetic',price=1,
                    cosmetic_bundle=[{'kind':'badge','key':key,'days':original_days}])
                start=timezone.now()
                with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,item.pk)
                grant=CosmeticGrant.objects.get(user=self.user,key=key)
                grant.inventory.quantity=0;grant.inventory.save(update_fields=['quantity'])
                item.cosmetic_bundle=[{'kind':'badge','key':key,'days':1}]
                item.save(update_fields=['cosmetic_bundle'])
                with patch('django.utils.timezone.now',return_value=start+timedelta(days=1)):
                    purchase_item(self.member,item.pk)
                grant.refresh_from_db()
                self.assertEqual(grant.expires_at,start+timedelta(days=2))
                self.assertEqual(Purchase.objects.filter(item=item).count(),2)
                snapshot=Purchase.objects.filter(item=item).latest('pk').cosmetic_snapshot[0]
                self.assertEqual(snapshot['expires_at'],grant.expires_at.isoformat())
                self.assertFalse(snapshot.get('already_permanent',False))

    def package(self,manifest,extras=None):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as archive:
            archive.writestr('theme.json',json.dumps(manifest));archive.writestr('badge.png',self.image)
            for name,content in (extras or {}).items():archive.writestr(name,content)
        return SimpleUploadedFile('theme.zip',stream.getvalue(),content_type='application/zip')

    def test_package_preview_import_atomicity_and_purchase(self):
        manifest={'schema_version':1,'name':'Imported','assets':[{'kind':'badge','key':'imported','name':'Imported','icon':'badge.png','duration_days':5}]}
        response=self.client.post('/api/management/cosmetic-assets/package',{'file':self.package(manifest)})
        self.assertEqual(response.status_code,200,response.content)
        prepared=response.json();self.assertFalse(CosmeticAsset.objects.filter(key='imported').exists())
        response=self.post('/api/management/cosmetic-assets/import',prepared)
        self.assertEqual(response.status_code,200,response.content)
        duplicate={**prepared,'assets':[{'kind':'badge','key':'new-one','name':'New','icon':self.url},prepared['assets'][0]]}
        response=self.post('/api/management/cosmetic-assets/import',duplicate)
        self.assertEqual(response.status_code,400);self.assertFalse(CosmeticAsset.objects.filter(key='new-one').exists())
        item=ShopItem.objects.create(team=self.team,name='Imported',item_type='cosmetic',price=1,cosmetic_bundle=prepared['components'])
        purchase_item(self.member,item.pk);self.assertEqual(available(self.user.pk,'badge')[0]['key'],'imported')

    def test_bad_packages_and_untrusted_assets_are_rejected(self):
        valid={'schema_version':1,'assets':[{'kind':'badge','key':'safe','name':'Safe','icon':'badge.png'}]}
        for extra in [{'../escape.png':self.image},{'script.js':b'alert(1)'},{'script.svg':b'<svg onload="alert(1)"/>'},{'C:/escape.png':self.image}]:
            response=self.client.post('/api/management/cosmetic-assets/package',{'file':self.package(valid,extra)})
            self.assertEqual(response.status_code,400,response.content)
        for url in ['https://example.com/a.png','javascript:alert(1)','/api/cosmetic-assets/media/'+'a'*64+'.png']:
            response=self.post('/api/management/cosmetic-assets',{'kind':'badge','key':'bad','name':'Bad','icon':url})
            self.assertEqual(response.status_code,400,response.content)
        response=self.post('/api/management/cosmetic-assets',{'kind':'theme','key':'bad','name':'Bad','css':'*{display:none}'})
        self.assertEqual(response.status_code,400)

    def test_only_global_administrator_can_upload_import_or_edit(self):
        response=self.owner.get('/api/management/cosmetic-assets');self.assertEqual(response.status_code,403)
        for path in ('/api/management/cosmetic-assets','/api/management/cosmetic-assets/import'):
            self.assertEqual(self.post(path,{},self.owner).status_code,403)
        for path in ('/api/management/cosmetic-assets/upload','/api/management/cosmetic-assets/package'):
            response=self.owner.post(path,{'file':SimpleUploadedFile('badge.png',self.image)})
            self.assertEqual(response.status_code,403)
        response=self.post('/api/profile/cosmetics',{'kind':'badge','key':'not-owned'},self.owner)
        self.assertEqual(response.status_code,409)

    def test_finite_title_renewal_stacks_and_preserves_first_purchase(self):
        item=ShopItem.objects.create(team=self.team,name='Title',price=1,item_type='title',cosmetic_duration_days=2,title_definition={'text':'Garden','font':'system','style':'plain','color':'#aa7788'})
        start=timezone.now()
        with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,item.pk)
        with patch('django.utils.timezone.now',return_value=start+timedelta(days=1)):purchase_item(self.member,item.pk)
        from .models import OwnedTitle
        self.assertEqual(OwnedTitle.objects.get(user=self.user).expires_at,start+timedelta(days=4))
        self.assertEqual(Purchase.objects.filter(item=item).earliest('pk').cosmetic_expires_at,start+timedelta(days=2))

    def test_permanent_bundle_cannot_charge_twice_and_inactive_resource_still_wears(self):
        definition=self.asset('badge','evergreen',0)
        item=ShopItem.objects.create(team=self.team,name='Permanent',price=2,item_type='cosmetic',cosmetic_bundle=[{'kind':'badge','key':definition['key'],'days':0}])
        purchase_item(self.member,item.pk)
        with self.assertRaises(ValueError):purchase_item(self.member,item.pk)
        CosmeticAsset.objects.filter(kind='badge',key=definition['key']).update(is_active=False)
        response=self.post('/api/profile/cosmetics',{'kind':'badge','key':definition['key']},self.owner)
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['badge']['icon'],self.url)

    def test_physical_gift_keeps_its_purchased_resource_version(self):
        original=self.asset('badge','gift-snapshot',0)
        item=ShopItem.objects.create(team=self.team,name='Gift',price=1,item_type='physical',gift_badge_key='gift-snapshot')
        purchase_item(self.member,item.pk)
        asset=CosmeticAsset.objects.get(kind='badge',key='gift-snapshot')
        response=self.post('/api/management/cosmetic-assets',{**asset.definition,'revision':asset.revision,'name':'Changed gift'})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(available(self.user.pk,'badge')[0]['name'],original['name'])

    def test_unlist_unchanged_bundle_with_inactive_resource_but_reject_relisting_or_changed_contents(self):
        item=self.shop();purchase_item(self.member,item.pk)
        snapshot=Purchase.objects.get(item=item).cosmetic_snapshot
        CosmeticAsset.objects.filter(kind='theme',key='garden').update(is_active=False)
        def update(data):return self.client.put('/api/currency/admin/shop',json.dumps({'item_id':item.pk,**data}),content_type='application/json')
        response=update({'is_active':False});self.assertEqual(response.status_code,200,response.content)
        item.refresh_from_db();self.assertFalse(item.is_active)
        self.assertNotIn(item.pk,[row['id'] for row in self.owner.get('/api/currency/shop/items').json()['items']])
        self.assertEqual(Purchase.objects.get(item=item).cosmetic_snapshot,snapshot)
        for data in ({'is_active':True},{'is_active':False,'cosmetic_bundle':[{'kind':'theme','key':'garden','days':10}]}):
            response=update(data);self.assertEqual(response.status_code,400,response.content)
            item.refresh_from_db();self.assertFalse(item.is_active)
        response=self.post('/api/currency/admin/shop',{'name':'New inactive','price':1,'item_type':'cosmetic','is_active':False,'cosmetic_bundle':item.cosmetic_bundle})
        self.assertEqual(response.status_code,400,response.content)

    def test_many_products_share_request_scoped_catalog_reads(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        asset=self.asset('badge','catalog-read',5)
        for i in range(25):ShopItem.objects.create(team=self.team,name=f'Catalog {i}',item_type='cosmetic',price=1,cosmetic_bundle=[{'kind':'badge','key':asset['key'],'days':5}])
        with CaptureQueriesContext(connection) as queries:response=self.owner.get('/api/currency/shop/items')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(len(response.json()['items']),25)
        self.assertLessEqual(sum('FROM "club_cosmeticasset"' in q['sql'] for q in queries),3)
        self.assertLessEqual(sum('FROM "club_cosmeticgrant"' in q['sql'] for q in queries),3)

    def test_legacy_permanent_taffy_does_not_make_another_bundle_permanent(self):
        legacy=ShopItem.objects.create(team=self.team,name='Legacy Taffy',item_type='theme',cosmetic_key='taffy',price=1)
        start=timezone.now()
        with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,legacy.pk)
        self.asset('badge','new-extra',1)
        bundle=ShopItem.objects.create(team=self.team,name='One day bundle',item_type='cosmetic',price=1,
            cosmetic_bundle=[{'kind':'theme','key':'taffy','days':1},{'kind':'badge','key':'taffy','days':1},
                {'kind':'frame','key':'taffy-goggles','days':1},{'kind':'badge','key':'new-extra','days':1}])
        with patch('django.utils.timezone.now',return_value=start):purchase_item(self.member,bundle.pk)
        grant=CosmeticGrant.objects.get(user=self.user,inventory__item=bundle,kind='theme')
        self.assertEqual(grant.expires_at,start+timedelta(days=1))
        self.assertTrue(all(g.expires_at==grant.expires_at for g in CosmeticGrant.objects.filter(user=self.user,inventory__item=bundle)))
        self.assertIsNone(state(self.user)['themes'][0]['expires_at'])
        with patch('django.utils.timezone.now',return_value=start+timedelta(hours=12)):purchase_item(self.member,bundle.pk)
        grant.refresh_from_db();self.assertEqual(grant.expires_at,start+timedelta(days=2))
        original=CosmeticGrant.objects.get(user=self.user,inventory__item=legacy,kind='theme')
        response=self.post(f'/api/management/teams/{self.team.pk}/members/{self.member.pk}/inventory',
            {'action':'quantity','item_id':legacy.pk,'inventory_id':original.inventory_id,'quantity':0,'expected_quantity':1})
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(state(self.user)['themes'][0]['expires_at'],grant.expires_at.isoformat())
        self.assertTrue(all(row['expires_at']==grant.expires_at.isoformat() for kind in ('themes','badges','frames') for row in state(self.user)[kind]))
        with patch('django.utils.timezone.now',return_value=start+timedelta(days=3)):
            self.assertEqual(state(self.user)['themes'],[])
        snapshot=Purchase.objects.filter(item=bundle).latest('pk').cosmetic_snapshot[0]
        self.assertEqual(snapshot['expires_at'],grant.expires_at.isoformat())
        self.assertFalse(snapshot.get('already_permanent',False))

    def test_same_source_keeps_its_existing_permanent_rights_when_adding_components(self):
        self.asset('badge','source-permanent',0);self.asset('badge','source-extra',1)
        item=ShopItem.objects.create(team=self.team,name='Same source',item_type='cosmetic',price=1,
            cosmetic_bundle=[{'kind':'badge','key':'source-permanent','days':0}])
        purchase_item(self.member,item.pk)
        item.cosmetic_bundle=[{'kind':'badge','key':'source-permanent','days':1},{'kind':'badge','key':'source-extra','days':1}]
        item.save(update_fields=['cosmetic_bundle']);purchase_item(self.member,item.pk)
        grant=CosmeticGrant.objects.get(user=self.user,inventory__item=item,key='source-permanent')
        self.assertIsNone(grant.expires_at)
        self.assertTrue(Purchase.objects.filter(item=item).latest('pk').cosmetic_snapshot[0]['already_permanent'])

    def test_unlist_inactive_physical_gifts_and_legacy_cosmetics_without_replacing_references(self):
        for kind in ('physical','theme','badge','frame'):
            with self.subTest(item_type=kind):
                asset_kind='badge' if kind=='physical' else kind
                key=f'unlist-{kind}';other=f'replacement-{kind}'
                self.asset(asset_kind,key,1);self.asset(asset_kind,other,1)
                field='gift_badge_key' if kind=='physical' else 'cosmetic_key'
                item=ShopItem.objects.create(team=self.team,name=key,item_type=kind,price=1,**{field:key})
                purchase_item(self.member,item.pk)
                purchase=Purchase.objects.get(item=item);snapshot=purchase.cosmetic_snapshot
                CosmeticAsset.objects.filter(kind=asset_kind,key__in=[key,other]).update(is_active=False)
                def update(data):return self.client.put('/api/currency/admin/shop',json.dumps({'item_id':item.pk,**data}),content_type='application/json')
                response=update({'is_active':False});self.assertEqual(response.status_code,200,response.content)
                item.refresh_from_db();self.assertFalse(item.is_active);self.assertEqual(getattr(item,field),key)
                self.assertNotIn(item.pk,[row['id'] for row in self.owner.get('/api/currency/shop/items').json()['items']])
                purchase.refresh_from_db();self.assertEqual(purchase.cosmetic_snapshot,snapshot)
                for data in ({'is_active':True},{'is_active':False,field:other}):
                    response=update(data);self.assertEqual(response.status_code,400,response.content)
                    item.refresh_from_db();self.assertFalse(item.is_active);self.assertEqual(getattr(item,field),key)
                response=self.post('/api/currency/admin/shop',{'name':other,'price':1,'item_type':kind,'is_active':False,field:key})
                self.assertEqual(response.status_code,400,response.content)
