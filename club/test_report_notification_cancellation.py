import json
from unittest.mock import Mock,patch

from django.test import TestCase,override_settings
from django.utils import timezone

from . import test_community as fixtures
from .astrbot_notifications import deliver_pending,queue_notification
from .models import AstrBotNotification,Submission,SubmissionPart,TeamNotificationSettings
from .problem_parser import key_cipher


@override_settings(ASTRBOT_NOTIFY_URL='https://bot.example/club/notify')
class ReportNotificationCancellationTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        TeamNotificationSettings.objects.create(team=self.team,enabled=True,
            encrypted_api_token=key_cipher().encrypt(b't'*32).decode())
        self.record=Submission.objects.create(team=self.team,member=self.author_member,
            semester=self.semester,week=self.week,problem=self.problem)
        SubmissionPart.objects.create(submission=self.record,kind='proof',status='approved',points_awarded=1)
        self.url=f'/api/submissions/{self.record.pk}/report'

    def report(self,user,reason):
        self.client.force_login(user)
        response=self.client.post(self.url,json.dumps({'reason':reason}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        return self.record.reports.get(reporter=user)

    def test_cancelled_notification_is_not_sent_and_rereport_sends_only_new_reason(self):
        report=self.report(self.reader,'Initial reason')
        old=AstrBotNotification.objects.get(event_key=f'report:{report.pk}:1')
        self.assertEqual(old.payload['data']['report_id'],report.pk)
        self.assertEqual(self.client.delete(self.url).status_code,200)
        old.refresh_from_db();self.assertIsNotNone(old.cancelled_at)
        response=Mock(status_code=200);response.json.return_value={'ok':True}
        with patch('club.astrbot_notifications.requests.post',return_value=response) as send:
            self.assertEqual(deliver_pending(),0);send.assert_not_called()
            self.report(self.reader,'Replacement reason')
            self.assertEqual(deliver_pending(),1)
        send.assert_called_once()
        self.assertIn('Replacement reason',send.call_args.kwargs['json']['text'])
        self.assertNotIn('Initial reason',send.call_args.kwargs['json']['text'])
        old.refresh_from_db();self.assertIsNone(old.delivered_at)

    def test_closure_cancels_only_reporters_pending_notifications(self):
        report=self.report(self.reader,'Closed reporter reason')
        other=self.report(self.owner,'Other reporter reason')
        delivered=queue_notification('already-delivered','submission_report',self.team,'Historical delivery',report_id=report.pk)
        delivered.delivered_at=timezone.now();delivered.save(update_fields=['delivered_at'])
        self.client.force_login(self.reader)
        response=self.client.post('/api/account/close',json.dumps({'confirmation':'注销账号',
            'password':'test-password'}),content_type='application/json')
        self.assertEqual(response.status_code,200,response.content)
        self.assertIsNotNone(AstrBotNotification.objects.get(event_key=f'report:{report.pk}:1').cancelled_at)
        self.assertIsNone(AstrBotNotification.objects.get(event_key=f'report:{other.pk}:1').cancelled_at)
        delivered.refresh_from_db();self.assertIsNone(delivered.cancelled_at)
        response=Mock(status_code=200);response.json.return_value={'ok':True}
        with patch('club.astrbot_notifications.requests.post',return_value=response) as send:
            self.assertEqual(deliver_pending(),1)
        self.assertIn('Other reporter reason',send.call_args.kwargs['json']['text'])
        self.assertEqual(send.call_args.kwargs['json']['data']['report_id'],other.pk)
