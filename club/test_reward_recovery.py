import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.test import TestCase, TransactionTestCase, Client
from django.db import close_old_connections

from .currency_services import add_currency, purchase_item
from .models import CurrencyTransaction, ShopCode, ShopFulfillment, ShopItem, Submission, UserInventory
from .shop_fulfillment import append_codes
from .test_submission_reconciliation import SubmissionReconciliationTests


class InventoryRewardRecoveryTests(TestCase):
    setUp = SubmissionReconciliationTests.setUp
    image = SubmissionReconciliationTests.image
    submit_day = SubmissionReconciliationTests.submit_day
    balance = SubmissionReconciliationTests.balance

    def buy(self, kind='consumable', price=2, quantity=1, **kwargs):
        item = ShopItem.objects.create(team=self.team,name='测试物品',item_type=kind,price=price,stock=5,**kwargs)
        if kind == 'redeem_code':
            append_codes(item,['CODE-ONE','CODE-TWO'])
        purchase_item(self.author_member,item.pk,quantity)
        return item

    def preview(self, item, action='delete'):
        response = self.client.get(f'/api/submissions/{item.pk}/reversal-preview',{'action':action})
        self.assertEqual(response.status_code,200,response.content)
        return response.json()

    def test_bundled_api_card_is_reclaimed_as_a_whole_at_original_total(self):
        from .currency_services import adjust_currency
        submission = self.submit_day()
        add_currency(self.author_member, 10, 'admin_adjust')
        item = self.buy(kind='redeem_code', price=2, quantity=3, card_source='api', allow_multiple_purchase=True)
        adjust_currency(self.author_member, -self.balance(), 'admin_adjust')
        item.price = 99
        item.allow_multiple_purchase = False
        item.save(update_fields=['price', 'allow_multiple_purchase'])
        plan = self.preview(submission)
        self.assertEqual(plan['items'], [{'name': '测试物品', 'quantity': 3, 'refund': 6}])
        self.assertEqual(self.delete(submission, plan['token']).status_code, 200)
        unit = ShopFulfillment.objects.get(purchase__item=item)
        item.refresh_from_db()
        self.assertEqual((unit.status, unit.refunded_amount, item.stock), ('reclaimed', 6, 5))
        self.assertEqual(self.balance(), 3)

    def test_existing_debt_recovers_unused_items_then_records_remaining_debt(self):
        from .currency_services import adjust_currency
        submission=self.submit_day()
        item=self.buy(price=2)
        adjust_currency(self.author_member,-5,'admin_adjust')
        self.assertEqual(self.balance(),-4)
        plan=self.preview(submission)
        self.assertEqual(plan['refund'],2)
        self.assertEqual(plan['reward_reversal'],3)
        self.assertEqual(plan['balance_after'],-5)
        self.assertEqual(self.delete(submission).status_code,409)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(self.balance(),-5)
        self.assertEqual(UserInventory.objects.get(item=item).quantity,0)
        self.assertEqual(ShopFulfillment.objects.filter(status='reclaimed').count(),1)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='item_recovery').count(),1)
        add_currency(self.author_member,2,'contest_reward')
        self.assertEqual(self.balance(),-3)

    def delete(self, item, token=None):
        return self.client.delete(f'/api/submissions/{item.pk}',json.dumps({'version':item.version,'recovery_token':token}),content_type='application/json')

    def confirm_delivery(self, unit):
        self.client.force_login(self.owner)
        response = self.client.post('/api/currency/admin/dispatch',json.dumps({'id':unit.pk}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.client.force_login(self.author)

    def test_unused_item_requires_confirmation_and_refunds_original_paid_price(self):
        submission = self.submit_day()
        item = self.buy()
        item.price = 100
        item.save(update_fields=['price'])
        plan = self.preview(submission)
        self.assertEqual(plan['items'],[{'name':'测试物品','quantity':1,'refund':2}])
        self.assertEqual(plan['balance_after'],0)
        self.assertEqual(self.balance(),1)
        self.assertEqual(self.delete(submission).status_code,409)
        self.assertTrue(Submission.objects.filter(pk=submission.pk,is_valid=True).exists())
        self.assertEqual(UserInventory.objects.get(item=item).quantity,1)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(self.balance(),0)
        self.assertEqual(UserInventory.objects.get(item=item).quantity,0)
        unit = ShopFulfillment.objects.get(purchase__item=item)
        self.assertEqual((unit.status,unit.refunded_amount),('reclaimed',2))
        item.refresh_from_db()
        self.assertEqual(item.stock,5)
        self.assertEqual(CurrencyTransaction.objects.filter(transaction_type='item_recovery').count(),1)
        self.assertEqual(self.delete(submission,plan['token']).status_code,404)

    def test_pending_physical_item_is_reclaimed_and_no_longer_uses_its_limit(self):
        submission = self.submit_day()
        item = self.buy('physical',price=3,purchase_limit=1)
        unit = ShopFulfillment.objects.get()
        plan = self.preview(submission)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        unit.refresh_from_db()
        self.assertEqual(unit.status,'reclaimed')
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get('/api/currency/admin/dispatch').json()['pending_count'],0)
        self.assertEqual(self.client.post('/api/currency/admin/dispatch',json.dumps({'id':unit.pk}),content_type='application/json').status_code,409)
        self.client.force_login(self.author)
        row = next(row for row in self.client.get('/api/currency/shop/items').json()['items'] if row['id']==item.pk)
        self.assertEqual(row['purchased_quantity'],0)
        self.assertFalse(row['purchase_limit_reached'])

    def test_delivery_after_preview_requires_a_new_confirmation_and_leaves_delivered_item(self):
        submission = self.submit_day()
        self.buy('physical',price=3)
        unit = ShopFulfillment.objects.get()
        old = self.preview(submission)
        self.confirm_delivery(unit)
        self.assertEqual(self.delete(submission,old['token']).status_code,409)
        self.assertTrue(Submission.objects.filter(pk=submission.pk).exists())
        fresh = self.preview(submission)
        self.assertEqual(fresh['items'],[])
        self.assertEqual(fresh['balance_after'],-3)
        self.assertEqual(self.delete(submission,fresh['token']).status_code,200)
        self.assertEqual(self.balance(),-3)
        unit.refresh_from_db()
        self.assertEqual(unit.status,'delivered')

    def test_card_reserved_for_an_unused_item_is_released_but_redeemed_cards_are_not(self):
        submission = self.submit_day()
        item = self.buy('redeem_code',price=3)
        plan = self.preview(submission)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(ShopCode.objects.filter(item=item,reserved_for__isnull=True,consumed_at__isnull=True).count(),2)
        self.assertEqual(self.balance(),0)
        submission = self.submit_day()
        purchase_item(self.author_member,item.pk)
        unit = ShopFulfillment.objects.get(status='ready')
        self.assertEqual(self.client.post(f'/api/currency/inventory/{unit.pk}/redeem').status_code,200)
        plan = self.preview(submission)
        self.assertEqual(plan['items'],[])
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        unit.refresh_from_db()
        self.assertEqual(unit.status,'redeemed')

    def test_recovery_keeps_free_unit_sequences_usable_and_returns_unused_tickets(self):
        submission = self.submit_day()
        add_currency(self.author_member,2,CurrencyTransaction.ADMIN_ADJUST)
        item = self.buy(price=2,quantity=2)
        inventory = UserInventory.objects.get(item=item)
        plan = self.preview(submission)
        self.assertEqual(plan['refund'],2)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(ShopFulfillment.objects.get().sequence,2)
        response = self.client.post(f'/api/currency/inventory/{inventory.pk}/use',json.dumps({'request_id':str(uuid.uuid4())}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(ShopFulfillment.objects.get(status='dispatching').sequence,1)

    def test_enough_balance_does_not_recover_items_and_other_members_cannot_inspect(self):
        submission = self.submit_day()
        add_currency(self.author_member,10,CurrencyTransaction.ADMIN_ADJUST)
        item = self.buy()
        plan = self.preview(submission)
        self.assertEqual(plan['items'],[])
        self.client.force_login(self.reader)
        self.assertEqual(self.client.get(f'/api/submissions/{submission.pk}/reversal-preview').status_code,403)
        self.client.force_login(self.author)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(UserInventory.objects.get(item=item).quantity,1)
        self.assertFalse(ShopFulfillment.objects.exists())

    def test_available_items_are_recovered_before_the_remaining_debt_is_recorded(self):
        from .currency_services import deduct_currency
        submission = self.submit_day()
        self.buy(price=1)
        deduct_currency(self.author_member,2,CurrencyTransaction.ADMIN_ADJUST,'已消费')
        plan = self.preview(submission)
        self.assertEqual((plan['refund'],plan['balance_after']),(1,-2))
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        self.assertEqual(self.balance(),-2)

    def test_pending_consumables_can_be_recovered_but_confirmed_consumables_cannot(self):
        submission = self.submit_day()
        item = self.buy(price=3)
        inventory = UserInventory.objects.get(item=item)
        token = str(uuid.uuid4())
        path = f'/api/currency/inventory/{inventory.pk}/use'
        self.assertEqual(self.client.post(path,json.dumps({'request_id':token}),content_type='application/json').status_code,200)
        plan = self.preview(submission)
        self.assertEqual(plan['refund'],3)
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        retry = self.client.post(path,json.dumps({'request_id':token}),content_type='application/json')
        self.assertEqual(retry.json()['status'],'reclaimed')
        submission = self.submit_day()
        purchase_item(self.author_member,item.pk)
        inventory.refresh_from_db()
        result = self.client.post(path,json.dumps({'request_id':str(uuid.uuid4())}),content_type='application/json').json()
        unit = ShopFulfillment.objects.get(pk=result['fulfillment_id'])
        self.confirm_delivery(unit)
        plan = self.preview(submission)
        self.assertEqual(plan['items'],[])
        self.assertEqual(self.delete(submission,plan['token']).status_code,200)
        unit.refresh_from_db()
        self.assertEqual(unit.status,'consumed')

    def test_admin_rejection_uses_an_admin_bound_recovery_confirmation(self):
        submission = self.submit_day()
        self.buy('makeup_ticket',price=3)
        author_plan = self.preview(submission)
        self.client.force_login(self.owner)
        path = f'/api/submissions/{submission.pk}/reject'
        payload = {'note':'截图不符','version':submission.version,'recovery_token':author_plan['token']}
        self.assertEqual(self.client.post(path,json.dumps(payload),content_type='application/json').status_code,409)
        plan = self.preview(submission,'reject')
        payload['recovery_token'] = plan['token']
        self.assertEqual(self.client.post(path,json.dumps(payload),content_type='application/json').status_code,200)
        self.assertEqual(self.balance(),0)
        self.assertEqual(ShopFulfillment.objects.get().status,'reclaimed')


class ConcurrentRewardRecoveryTests(TransactionTestCase):
    setUp = SubmissionReconciliationTests.setUp
    image = SubmissionReconciliationTests.image
    submit_day = SubmissionReconciliationTests.submit_day

    def test_confirmation_and_recovery_cannot_both_succeed_for_the_same_physical_unit(self):
        submission = self.submit_day()
        item = ShopItem.objects.create(team=self.team,name='并发物品',item_type='physical',price=3)
        purchase_item(self.author_member,item.pk)
        unit = ShopFulfillment.objects.get()
        quote = self.client.get(f'/api/submissions/{submission.pk}/reversal-preview').json()
        admin = Client()
        admin.force_login(self.owner)
        session = admin.session
        session['team_id'] = self.team.pk
        session.save()
        barrier = Barrier(2)
        def operation(delivery):
            close_old_connections()
            try:
                barrier.wait()
                if delivery:
                    return admin.post('/api/currency/admin/dispatch',json.dumps({'id':unit.pk}),content_type='application/json').status_code
                return self.client.delete(f'/api/submissions/{submission.pk}',json.dumps({'version':1,'recovery_token':quote['token']}),content_type='application/json').status_code
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(operation,[True,False])),[200,409])
        unit.refresh_from_db()
        self.assertIn(unit.status,['delivered','reclaimed'])
