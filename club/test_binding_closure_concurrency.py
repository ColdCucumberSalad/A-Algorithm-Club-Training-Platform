import json
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections
from django.test import Client, TransactionTestCase
from django.utils import timezone

from . import profile_views, platform_account_views
from . import test_community as fixtures
from .account_views import close_user
from .models import PlatformBinding, TeamMembership
from .platform_credentials import load_credentials


class BindingClosureConcurrencyTests(TransactionTestCase):
    setUp=fixtures.CommunityTests.setUp

    def assert_closed_request_rejected(self,module,method,url,data):
        checked,closed=Event(),Event()
        original=module.eligible
        def stale_eligibility(request):
            member=original(request)
            self.assertIsNotNone(member)
            checked.set()
            self.assertTrue(closed.wait(10),'Closure did not finish')
            return member
        def write_binding():
            close_old_connections()
            try:
                client=Client();client.force_login(self.author)
                return getattr(client,method)(url,json.dumps(data),content_type='application/json').status_code
            finally:
                close_old_connections()
        with patch.object(module,'eligible',side_effect=stale_eligibility), \
                patch('club.platform_account_views.save_credentials') as save_credentials, \
                patch('club.platform_account_views.start') as start, \
                patch('club.profile_views.enqueue') as enqueue:
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(write_binding)
                try:
                    self.assertTrue(checked.wait(10),'Binding request did not pass eligibility')
                    self.assertTrue(close_user(self.author.pk,self.author))
                finally:
                    closed.set()
                self.assertEqual(pending.result(timeout=10),403)
            save_credentials.assert_not_called();start.assert_not_called();enqueue.assert_not_called()
        self.assertFalse(PlatformBinding.objects.filter(user=self.author).exists())

    def test_new_account_cannot_restore_credentials_after_closure(self):
        self.assert_closed_request_rejected(platform_account_views,'post','/api/profile/platforms/codeforces/accounts',
            {'account':'restored_handle','api_key':'private-key','api_secret':'private-secret'})

    def test_legacy_put_cannot_recreate_binding_after_closure(self):
        self.assert_closed_request_rejected(profile_views,'put','/api/profile/platforms/codeforces',
            {'account':'restored_handle'})

    def test_account_patch_rechecks_closure_before_saving_credentials(self):
        binding=PlatformBinding.objects.create(user=self.author,platform='codeforces',account='prior_handle')
        self.assert_closed_request_rejected(platform_account_views,'patch',f'/api/profile/platform-accounts/{binding.pk}',
            {'api_key':'private-key','api_secret':'private-secret'})

    def test_sync_rechecks_closure_before_scheduling(self):
        binding=PlatformBinding.objects.create(user=self.author,platform='codeforces',account='prior_handle')
        self.assert_closed_request_rejected(platform_account_views,'post','/api/profile/platform-accounts/sync',
            {'ids':[binding.pk]})

    def test_account_creation_rechecks_inactive_membership(self):
        original=platform_account_views.eligible
        def deactivate(request):
            member=original(request)
            TeamMembership.objects.filter(pk=member.pk).update(is_active=False)
            return member
        with patch.object(platform_account_views,'eligible',side_effect=deactivate), \
                patch('club.platform_account_views.save_credentials') as save_credentials, \
                patch('club.platform_account_views.start') as start:
            response=self.client.post('/api/profile/platforms/codeforces/accounts',json.dumps({
                'account':'restored_handle','api_key':'private-key','api_secret':'private-secret'}),content_type='application/json')
        self.assertEqual(response.status_code,403,response.content)
        save_credentials.assert_not_called();start.assert_not_called()
        self.assertFalse(PlatformBinding.objects.filter(user=self.author).exists())

    def test_active_member_can_create_update_sync_delete_and_use_legacy_binding(self):
        with patch('club.platform_account_views.enqueue') as enqueue:
            response=self.client.post('/api/profile/platforms/codeforces/accounts',json.dumps({
                'account':'active_handle','api_key':'test-key','api_secret':'test-secret'}),content_type='application/json')
            self.assertEqual(response.status_code,202,response.content)
            binding=PlatformBinding.objects.get(user=self.author,platform='codeforces')
            self.assertEqual(load_credentials(binding),{'api_key':'test-key','api_secret':'test-secret'})
            self.assertNotIn('test-secret',binding.encrypted_credentials)
            response=self.client.patch(f'/api/profile/platform-accounts/{binding.pk}',json.dumps({
                'api_secret':'replacement-secret'}),content_type='application/json')
            self.assertEqual(response.status_code,202,response.content)
            binding.refresh_from_db()
            self.assertEqual(load_credentials(binding)['api_secret'],'replacement-secret')
            PlatformBinding.objects.filter(pk=binding.pk).update(status='success',requested_at=timezone.now()-timedelta(minutes=2))
            response=self.client.post('/api/profile/platform-accounts/sync',json.dumps({'ids':[binding.pk]}),content_type='application/json')
            self.assertEqual(response.status_code,202,response.content)
            self.assertEqual(enqueue.call_count,3)
            self.assertEqual(self.client.delete(f'/api/profile/platform-accounts/{binding.pk}').status_code,200)
        with patch('club.profile_views.enqueue') as enqueue:
            response=self.client.put('/api/profile/platforms/atcoder',json.dumps({'account':'active_runner'}),content_type='application/json')
            self.assertEqual(response.status_code,202,response.content)
            enqueue.assert_called_once()
