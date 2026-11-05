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
