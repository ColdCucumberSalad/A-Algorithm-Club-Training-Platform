import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections, transaction
from django.test import Client, TransactionTestCase
from django.utils import timezone

from . import profile_views
from . import test_community as fixtures
from .account_views import close_user
from .currency_services import add_currency, get_or_create_balance, purchase_item
from .models import (AccountClosure, CheckinRecord, ShopFulfillment, ShopItem, Submission, SubmissionPart,
    Team, TeamMembership, UserInventory, UserProfile)
from .reward_recovery import reclaim
from .views import serialize_submission


class ClosureProfileConcurrencyTests(TransactionTestCase):
    setUp = fixtures.CommunityTests.setUp

    def test_already_eligible_profile_request_cannot_restore_closed_name_or_avatar(self):
        UserProfile.objects.create(user=self.author)
        row=Submission.objects.create(team=self.team,member=self.author_member,
            semester=self.semester,week=self.week,problem=self.problem)
        eligible,closed=Event(),Event()
        original=profile_views.eligible

        def pause_after_eligibility(request):
            member=original(request)
            self.assertIsNotNone(member)
            eligible.set()
            self.assertTrue(closed.wait(10),'Closure did not finish')
            return member

        def update_profile():
            close_old_connections()
            try:
                client=Client();client.force_login(self.author)
                return client.post('/api/profile',{'name':'Restored private name',
                    'avatar':fixtures.CommunityTests.image(self)}).status_code
            finally:
                close_old_connections()

        with patch('club.profile_views.eligible',side_effect=pause_after_eligibility):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(update_profile)
                try:
                    self.assertTrue(eligible.wait(10),'Profile did not pass eligibility')
                    self.assertTrue(close_user(self.author.pk,self.author))
                finally:
                    closed.set()
                self.assertEqual(pending.result(timeout=10),403)
        self.author_member.refresh_from_db();self.author.refresh_from_db()
        self.assertFalse(self.author.is_active)
        self.assertTrue(self.author_member.display_name.startswith('已注销用户'))
        self.assertEqual(UserProfile.objects.get(user=self.author).avatar.name,'')
        self.assertEqual(serialize_submission(Submission.objects.select_related('member').get(pk=row.pk))['member_name'],
            self.author_member.display_name)

    def test_stale_eligibility_is_rejected_after_membership_deactivation(self):
        original=profile_views.eligible
        def deactivate(request):
            member=original(request)
            TeamMembership.objects.filter(pk=member.pk).update(is_active=False)
            return member
        before=self.author_member.display_name
        with patch('club.profile_views.eligible',side_effect=deactivate):
            response=self.client.post('/api/profile',{'name':'Unauthorized change'})
        self.assertEqual(response.status_code,403,response.content)
        self.author_member.refresh_from_db()
        self.assertEqual(self.author_member.display_name,before)
        self.assertFalse(UserProfile.objects.filter(user=self.author,avatar__gt='').exists())

    def test_closure_marker_blocks_profile_write_even_if_active_flag_is_stale(self):
        AccountClosure.objects.create(user=self.author,closed_by=self.author)
        before=self.author_member.display_name
        response=self.client.post('/api/profile',{'name':'Reopened name'})
        self.assertEqual(response.status_code,403,response.content)
        self.author_member.refresh_from_db()
        self.assertEqual(self.author_member.display_name,before)


class ForeignPurchaseRecoveryConcurrencyTests(TransactionTestCase):
    setUp = fixtures.CommunityTests.setUp

    def test_foreign_physical_recovery_serializes_with_dispatch_without_inventory(self):
        self.team.currency_enabled=True;self.team.save()
        other=Team.objects.create(name='Foreign origin',code='FOREIGN-RECOVERY',
            created_by=self.owner,currency_enabled=True)
        foreign=TeamMembership.objects.create(team=other,user=self.author,display_name='Foreign buyer')
        TeamMembership.objects.create(team=other,user=self.owner,display_name='Foreign manager',role='admin')
        target=Submission.objects.create(team=self.team,member=self.author_member,semester=self.semester,
            week=self.week,problem=self.problem,record_date=timezone.localdate())
        SubmissionPart.objects.create(submission=target,kind='proof',status='approved',points_awarded=1)
        CheckinRecord.objects.create(team=self.team,member=self.author_member,
            checkin_date=target.record_date,reward_amount=3)
        add_currency(self.author_member,3,'checkin')
        item=ShopItem.objects.create(team=other,name='Foreign physical',item_type='physical',price=3,stock=2)
        purchase_item(foreign,item.pk)
        unit=ShopFulfillment.objects.get(purchase__member=foreign)
        self.assertEqual(unit.status,'dispatching')
        self.assertFalse(UserInventory.objects.filter(member=foreign).exists())
        session=self.client.session;session['team_id']=self.team.pk;session.save()
        preview=self.client.get(f'/api/submissions/{target.pk}/reversal-preview',{'action':'delete'}).json()
        self.assertEqual(preview['refund'],3)
        membership_locked,fulfillment_locked,dispatch_started=Event(),Event(),Event()

        def deliver():
            close_old_connections()
            try:
                client=Client();client.force_login(self.owner)
                session=client.session;session['team_id']=other.pk;session.save()
                with transaction.atomic():
                    TeamMembership.objects.select_for_update().get(pk=foreign.pk)
                    membership_locked.set()
                    self.assertTrue(fulfillment_locked.wait(10),'Recovery did not lock fulfillment')
                    dispatch_started.set()
                    return client.post('/api/currency/admin/dispatch',json.dumps({'id':unit.pk}),
                        content_type='application/json').status_code
            finally:
                close_old_connections()

        def after_global_locks(member,entries):
            fulfillment_locked.set()
            self.assertTrue(dispatch_started.wait(10),'Dispatch did not start')
            return reclaim(member,entries)

        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(deliver)
            try:
                self.assertTrue(membership_locked.wait(10),'Origin membership was not locked')
                with patch('club.reward_recovery.reclaim',side_effect=after_global_locks):
                    response=self.client.delete(f'/api/submissions/{target.pk}',json.dumps({
                        'version':target.version,'recovery_token':preview['token']}),content_type='application/json')
                self.assertEqual(response.status_code,200,response.content)
            finally:
                fulfillment_locked.set()
            self.assertEqual(pending.result(timeout=10),409)
        unit.refresh_from_db()
        self.assertEqual(unit.status,'reclaimed')
        self.assertEqual(get_or_create_balance(self.author_member).balance,0)
