import json
import uuid
from datetime import timedelta
from unittest.mock import patch
from django.utils import timezone
from .test_cosmetics import CosmeticTests
from .test_shop_titles import ShopTitleTests
from .models import CosmeticGrant,OwnedTitle,Purchase,ShopItem
from .cosmetics import available,frame_data,state
from .member_titles import available_titles_data,titles_data
from .cosmetic_terms import purchase_terms


class ThemeTermTests(CosmeticTests):
    def test_frozen_term_gifts_and_expiry_boundary(self):
        now=timezone.now();self.item.cosmetic_duration_days=7;self.item.save()
        with patch('club.cosmetic_terms.timezone.now',return_value=now):self.buy()
        purchase=Purchase.objects.get(item=self.item)
        self.assertEqual(purchase.cosmetic_expires_at,now+timedelta(days=7))
        self.assertEqual(purchase.cosmetic_duration_days,7)
        self.assertEqual(set(CosmeticGrant.objects.filter(user=self.user).values_list('expires_at',flat=True)),{purchase.cosmetic_expires_at})
        self.assertEqual(self.select('frame','taffy-goggles').status_code,200)
        self.assertEqual(self.select('badge','taffy').status_code,200)
        self.second.refresh_from_db();self.assertEqual(frame_data(self.second)['key'],'taffy-goggles')
        self.item.cosmetic_duration_days=30;self.item.save()
        purchase.refresh_from_db();self.assertEqual(purchase.cosmetic_duration_days,7)
        with patch('club.cosmetic_terms.timezone.now',return_value=purchase.cosmetic_expires_at):
            self.assertEqual(available(self.user.pk,'theme'),[])
            self.assertIsNone(frame_data(self.second))
            self.assertEqual(self.select('frame','taffy-goggles').status_code,409)
            self.buy()
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),2)
        self.assertEqual(CosmeticGrant.objects.filter(user=self.user).count(),3)

    def test_permanent_source_survives_expiring_gift(self):
        badge=ShopItem.objects.create(team=self.team,name='Badge',price=1,item_type='badge',cosmetic_key='taffy')
        from .currency_services import purchase_item
        purchase_item(self.member,badge.pk)
        self.item.cosmetic_duration_days=1;self.item.save();self.buy()
        CosmeticGrant.objects.filter(kind__in=['theme','frame']).update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(len(available(self.user.pk,'badge')),1)
        self.assertIsNone(available(self.user.pk,'badge')[0]['expires_at'])
        self.assertEqual(available(self.user.pk,'frame'),[])

    def test_admin_validation_and_idempotent_grant(self):
        url='/api/currency/admin/shop'
        for days in [True,-1,1.5,36501,'7']:
            response=self.admin.put(url,json.dumps({'item_id':self.item.pk,'cosmetic_duration_days':days}),content_type='application/json')
            self.assertEqual(response.status_code,400,response.content)
        response=self.admin.put(url,json.dumps({'item_id':self.item.pk,'cosmetic_duration_days':2}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        path=f'/api/management/teams/{self.team.pk}/members/{self.member.pk}/inventory'
        payload={'action':'grant','item_id':self.item.pk,'quantity':1,'request_id':str(uuid.uuid4())}
        for _ in range(2):
            response=self.admin.post(path,json.dumps(payload),content_type='application/json')
            self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),1)
        self.assertEqual(CosmeticGrant.objects.filter(user=self.user).count(),3)
        self.assertEqual(Purchase.objects.get(item=self.item).cosmetic_duration_days,2)
        self.assertEqual(self.select('frame','unknown').status_code,409)


class TitleTermTests(ShopTitleTests):
    def test_title_expires_and_can_be_bought_again_without_rewriting_history(self):
        self.item.cosmetic_duration_days=3;self.item.save();self.buy()
        end=OwnedTitle.objects.get(user=self.user).expires_at
        self.assertTrue(end)
        result=self.post(self.client,'/api/profile/titles/wear',{'title':self.definition['text']})
        self.assertEqual(result.status_code,200,result.content)
        self.second.refresh_from_db()
        with patch('club.cosmetic_terms.timezone.now',return_value=end):
            self.assertEqual(titles_data(self.second),[])
            self.assertEqual(available_titles_data(self.second),[])
            result=self.post(self.client,'/api/profile/titles/wear',{'title':self.definition['text']})
            self.assertNotEqual(result.status_code,200)
            self.buy()
        self.assertEqual(Purchase.objects.filter(item=self.item).count(),2)
        self.assertGreater(OwnedTitle.objects.get(user=self.user).expires_at,end)
        self.assertTrue(Purchase.objects.filter(item=self.item,cosmetic_expires_at=end).exists())

    def test_legacy_permanent_and_noncosmetic_term(self):
        self.buy();self.assertIsNone(OwnedTitle.objects.get(user=self.user).expires_at)
        self.assertEqual(available_titles_data(self.second),[self.definition])
        self.item.item_type='general';self.item.cosmetic_duration_days=99
        self.assertEqual(purchase_terms(self.item),{'cosmetic_duration_days':0,'cosmetic_expires_at':None})
