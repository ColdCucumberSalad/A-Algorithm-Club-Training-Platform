import json
import os
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from . import site_updates


class SiteUpdateApiTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name)
        env = patch.dict(os.environ, SITE_UPDATE_DIR=str(self.path))
        env.start(); self.addCleanup(env.stop)
        (self.path / 'heartbeat.json').write_text(json.dumps({'time': time.time()}))
        self.admin, _ = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True})
        self.member = User.objects.create_user('site-update-member')
        self.client.force_login(self.admin)

    def post(self, value):
        return self.client.post('/api/management/site-updates', json.dumps(value), content_type='application/json')

    def test_only_system_admin_can_view_or_start_updates(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get('/api/management/site-updates').status_code, 403)
        self.assertEqual(self.post({'action': 'check'}).status_code, 403)
        self.assertFalse(list(self.path.glob('request-*.json')))

    def test_defaults_and_status_do_not_enqueue_an_update(self):
        value = self.client.get('/api/management/site-updates').json()
        self.assertTrue(value['available'])
        self.assertEqual(value['schedule'], {'mode': 'auto', 'time': '04:00'})
        self.assertFalse(list(self.path.glob('request-*.json')))

    def test_duplicate_requests_are_rejected(self):
        self.assertEqual(self.post({'action': 'check'}).status_code, 202)
        self.assertEqual(self.post({'action': 'check'}).status_code, 409)
        self.assertEqual(len(list(self.path.glob('request-*.json'))), 1)

    def test_update_requires_exact_revision_and_cannot_supply_commands_or_urls(self):
        for payload in [{'action': 'shell', 'command': 'id'}, {'action': 'update', 'revision': 'main'},
                        {'action': 'update', 'revision': 'a' * 40, 'url': 'https://untrusted.test'},
                        {'action': 'check', 'repository': 'another/repo'}]:
            self.assertEqual(self.post(payload).status_code, 409)
        self.assertEqual(self.post({'action': 'update', 'revision': 'a' * 40}).status_code, 202)

    def test_modes_and_time_are_validated(self):
        for mode, clock in [('auto', '04:00'), ('notify', '23:59'), ('off', '00:00')]:
            response = self.client.put('/api/management/site-updates', json.dumps({'mode': mode, 'time': clock}), content_type='application/json')
            self.assertEqual(response.status_code, 202)
            for item in self.path.glob('request-*.json'):
                item.unlink()
        for value in [{'mode': 'auto', 'time': '24:00'}, {'mode': 'unknown', 'time': '04:00'},
                      {'mode': 'auto', 'time': '04:00', 'command': 'id'}]:
            self.assertEqual(self.client.put('/api/management/site-updates', json.dumps(value), content_type='application/json').status_code, 409)

    def test_disconnected_host_never_queues_an_update(self):
        (self.path / 'heartbeat.json').write_text('{"time":0}')
        self.assertFalse(self.client.get('/api/management/site-updates').json()['available'])
        self.assertEqual(self.post({'action': 'check'}).status_code, 409)

    def test_csrf_is_required_for_admin_update(self):
        from django.test import Client
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        self.assertEqual(client.post('/api/management/site-updates', '{"action":"check"}', content_type='application/json').status_code, 403)
