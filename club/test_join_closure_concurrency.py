import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db import close_old_connections
from django.test import Client,TransactionTestCase

from . import test_community as fixtures
from .account_views import close_user
from .models import Team,TeamMembership


class JoinClosureConcurrencyTests(TransactionTestCase):
    setUp=fixtures.CommunityTests.setUp

    def assert_stale_join_is_rejected(self,name=None):
        target=Team.objects.create(name='Pending join',code='PENDING-JOIN',created_by=self.owner)
        authenticated,closed=Event(),Event()
        original=User.objects.select_for_update
        def wait_before_user_lock(*args,**kwargs):
            if kwargs.get('no_key'):
                authenticated.set()
                self.assertTrue(closed.wait(10),'Closure did not finish')
            return original(*args,**kwargs)
        def join():
            close_old_connections()
            try:
                client=Client();client.force_login(self.author)
                payload={'team_code':target.code}
                if name is not None:payload['name']=name
                return client.post('/api/auth/join',json.dumps(payload),content_type='application/json').status_code
            finally:
                close_old_connections()
        with patch.object(User.objects,'select_for_update',side_effect=wait_before_user_lock):
            with ThreadPoolExecutor(max_workers=1) as pool:
                pending=pool.submit(join)
                try:
                    self.assertTrue(authenticated.wait(10),'Join did not authenticate before closure')
                    self.assertTrue(close_user(self.author.pk,self.author))
                finally:
                    closed.set()
                self.assertEqual(pending.result(timeout=10),403)
        self.assertFalse(TeamMembership.objects.filter(user=self.author,team=target).exists())
        self.assertFalse(TeamMembership.objects.filter(user=self.author,is_active=True).exists())
        self.author_member.refresh_from_db()
        self.assertTrue(self.author_member.display_name.startswith('已注销用户'))
        self.assertFalse(close_user(self.author.pk,self.author))

    def test_authenticated_join_with_explicit_name_cannot_outlive_closure(self):
        self.assert_stale_join_is_rejected('Restored public name')

    def test_authenticated_join_with_default_name_cannot_outlive_closure(self):
        self.assert_stale_join_is_rejected()
