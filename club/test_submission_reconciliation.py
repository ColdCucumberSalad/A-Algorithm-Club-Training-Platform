import json
from datetime import timedelta
from io import StringIO
import importlib
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.apps import apps
from django.test import TestCase
from django.utils import timezone

from . import test_community as fixtures
from .currency_services import deduct_currency, get_current_streak, makeup_checkin, reconcile_submission_day
from .models import (CheckinRecord, CurrencyBalance, CurrencyTransaction, MakeupPermission, Problem,
    ShopItem, SolvedProblemCredit, StreakReward, Submission, SubmissionPart, Team, TeamMembership,
    UserInventory, WeeklyStreakGrant)
from .solved import lifetime_solved_counts


class SubmissionReconciliationTests(TestCase):
    image = fixtures.CommunityTests.image

    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.team.currency_enabled = True
        self.team.daily_checkin_reward = 3
        self.team.save()
        self.today = timezone.localdate()

    def submit_day(self, day=None, submission_id=None):
        day = day or self.today
        week = self.semester.weeks.get(starts_at__date__lte=day, ends_at__date__gt=day)
        path = f'/api/submissions/{submission_id}/resubmit' if submission_id else '/api/submissions'
        with patch('club.problem_parser.get_problem', return_value=self.problem):
            response = self.client.post(path, {'week_id': week.pk, 'record_date': day.isoformat(),
                'problem_url': self.problem.url, 'proof': self.image(), 'code': 'int main() {}', 'code_language': 'cpp'})
        self.assertEqual(response.status_code, 201, response.content)
        return Submission.objects.get(pk=response.json()['submission']['id'])

    def remove(self, item):
        response = self.client.delete(f'/api/submissions/{item.pk}', json.dumps({'version':item.version}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)

    def balance(self):
        return CurrencyBalance.objects.get(member=self.author_member).balance

    def activity(self, day):
        return self.client.get('/api/training-activity', {'start':day.isoformat(), 'end':day.isoformat()}).json()['days'][0]

    def reject(self, item, report=False):
        if report:
            self.client.force_login(self.reader)
            self.client.post(f'/api/submissions/{item.pk}/report')
        self.client.force_login(self.owner)
        path = f'/api/admin/reports/{item.pk}/resolve' if report else f'/api/submissions/{item.pk}/reject'
        response = self.client.post(path, json.dumps({'action':'reject','version':item.version,'note':'无效截图','report_snapshot':fixtures.report_snapshot(item)}), content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_login(self.author)

    def test_only_last_submission_reverses_daily_and_weekly_rewards_and_resubmit_requalifies(self):
        StreakReward.objects.create(team=self.team, days=1, reward=5)
        first = self.submit_day()
        self.problem = Problem.objects.create(identity='rollback:second',url='https://example.com/second')
        second = self.submit_day()
        self.assertEqual(self.balance(), 8)
        self.remove(first)
        self.assertEqual(self.balance(), 8)
        self.assertTrue(self.activity(self.today)['hasSubmission'])
        self.remove(second)
        self.assertEqual(self.balance(), 0)
        self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
        grant = WeeklyStreakGrant.objects.get(member=self.author_member)
        self.assertIsNotNone(grant.revoked_at)
        self.assertEqual(get_current_streak(self.author_member), 0)
        today = next(day for day in self.client.get('/api/dashboard').json()['pulse'] if day['isToday'])
        self.assertFalse(today['hasSubmission'])
        self.assertFalse(today['submitted'])
        self.assertTrue(today['canSubmit'])
        self.submit_day()
        self.assertEqual(self.balance(), 8)
        grant.refresh_from_db()
        self.assertIsNone(grant.revoked_at)
        self.assertEqual(WeeklyStreakGrant.objects.filter(member=self.author_member).count(), 1)

    def test_spent_reward_is_fully_reversed_without_blocking_deletion(self):
        item = self.submit_day()
        deduct_currency(self.author_member, 3, CurrencyTransaction.PURCHASE, '已消费')
        self.team.daily_checkin_reward = 20
        self.team.save()
        self.remove(item)
        self.assertEqual(self.balance(), -3)
        reversal = CurrencyTransaction.objects.get(transaction_type=CurrencyTransaction.REWARD_REVERSAL)
        self.assertEqual(reversal.amount, -3)
        reconcile_submission_day(self.author_member, self.today, self.semester)
        self.assertEqual(self.balance(), -3)

    def test_weekly_reward_remains_while_another_qualifying_run_exists(self):
        monday = self.today-timedelta(days=self.today.weekday()+7)
        StreakReward.objects.create(team=self.team, days=3, reward=5)
        records = {}
        for offset in (0,1,2,4,5,6):
            day = monday+timedelta(days=offset)
            self.problem = Problem.objects.create(identity=f'reward:run:{offset}',url=f'https://example.com/run/{offset}')
            MakeupPermission.objects.create(member=self.author_member,semester=self.semester,record_date=day)
            records[offset] = self.submit_day(day)
        self.assertEqual(self.balance(), 5)
        self.remove(records[0])
        self.assertEqual(self.balance(), 5)
        self.remove(records[4])
        self.assertEqual(self.balance(), 0)

    def test_migration_captures_the_paid_amount_instead_of_current_configuration(self):
        self.submit_day()
        CheckinRecord.objects.filter(member=self.author_member).update(reward_amount=0)
        self.team.daily_checkin_reward = 100
        self.team.save()
        migration = importlib.import_module('club.migrations.0035_signin_reward_reversal')
        migration.capture_paid_rewards(apps, SimpleNamespace(connection=SimpleNamespace(alias='default')))
        self.assertEqual(CheckinRecord.objects.get(member=self.author_member).reward_amount, 3)

    def test_direct_and_report_rejection_reset_checkin_solved_and_restore_on_resubmit(self):
        for report in (False, True):
            with self.subTest(report=report):
                self.problem = Problem.objects.create(identity=f'rollback:reject:{report}',url=f'https://example.com/{report}')
                item = self.submit_day()
                self.assertEqual(lifetime_solved_counts([self.author.pk])[self.author.pk], 1)
                self.reject(item, report=report)
                self.assertEqual(self.balance(), 0)
                self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
                self.assertEqual(lifetime_solved_counts([self.author.pk]).get(self.author.pk, 0), 0)
                self.assertEqual(self.activity(self.today)['ac'], 0)
                self.submit_day(submission_id=item.pk)
                self.assertEqual(self.balance(), 3)
                self.assertEqual(self.activity(self.today)['ac'], 1)
                item.refresh_from_db()
                self.remove(item)

    def test_makeup_deletion_reopens_permission_without_another_ticket(self):
        day = self.today-timedelta(days=1)
        ticket = ShopItem.objects.create(team=self.team,name='Ticket',price=1,item_type='makeup_ticket')
        inventory = UserInventory.objects.create(team=self.team,member=self.author_member,item=ticket,quantity=2)
        makeup_checkin(self.author_member, day)
        item = self.submit_day(day)
        self.remove(item)
        permission = MakeupPermission.objects.get(member=self.author_member,record_date=day)
        self.assertIsNone(permission.completed_at)
        record = self.activity(day)
        self.assertFalse(record['checkedIn'])
        self.assertFalse(record['isMakeup'])
        self.assertTrue(record['makeupOpen'])
        self.assertTrue(record['canSubmit'])
        self.assertTrue(makeup_checkin(self.author_member, day)['already_open'])
        self.submit_day(day)
        permission.refresh_from_db()
        self.assertIsNotNone(permission.completed_at)
        self.assertTrue(self.activity(day)['isMakeup'])
        inventory.refresh_from_db()
        self.assertEqual(inventory.quantity, 1)

    def test_rejected_historical_submission_recompletes_makeup_on_resubmit(self):
        day = self.today-timedelta(days=1)
        MakeupPermission.objects.create(member=self.author_member,semester=self.semester,record_date=day)
        item = self.submit_day(day)
        self.reject(item)
        self.assertFalse(self.activity(day)['makeupOpen'])
        original_time = item.submitted_at
        self.submit_day(day, submission_id=item.pk)
        item.refresh_from_db()
        self.assertEqual(item.submitted_at, original_time)
        self.assertFalse(self.activity(day)['isMakeup'])
        self.assertEqual(self.balance(), 3)
        self.assertFalse(self.activity(day)['canSubmit'])

    def test_rejected_closed_week_submission_can_reuse_its_reopened_permission(self):
        day = self.today-timedelta(days=8)
        MakeupPermission.objects.create(member=self.author_member,semester=self.semester,record_date=day)
        item = self.submit_day(day)
        self.reject(item)
        item.week.is_closed = True
        item.week.save()
        mine = self.client.get('/api/submissions?mine=1').json()['submissions']
        self.assertTrue(next(row for row in mine if row['id']==item.pk)['can_resubmit'])
        self.submit_day(day, submission_id=item.pk)
        self.assertFalse(self.activity(day)['isMakeup'])

    def test_prior_normal_day_becomes_open_makeup_when_removed_later(self):
        item = self.submit_day()
        with patch('django.utils.timezone.now', return_value=timezone.now()+timedelta(days=1)):
            self.remove(item)
            self.assertTrue(self.activity(self.today)['makeupOpen'])
            self.assertEqual(self.balance(), 0)
            self.submit_day(self.today)
            self.assertTrue(self.activity(self.today)['isMakeup'])

    def test_other_valid_and_durable_ac_evidence_survives_deletion(self):
        item = self.submit_day()
        other = Team.objects.create(name='Other',code='ROLLBACK-OTHER',created_by=self.owner)
        member = TeamMembership.objects.create(team=other,user=self.author,display_name='Other')
        # Legacy cross-team evidence still counts even if current-team evidence is removed.
        duplicate = Submission.objects.create(team=other,member=member,semester=self.semester,week=self.week,
            problem=self.problem,record_date=self.today)
        SubmissionPart.objects.create(submission=duplicate,kind='proof',status='approved')
        SolvedProblemCredit.objects.create(user=self.author,source='contest',problem_key='cf:1:A')
        self.remove(item)
        self.assertEqual(lifetime_solved_counts([self.author.pk])[self.author.pk], 2)
        duplicate.is_valid = False
        duplicate.save()
        self.assertEqual(lifetime_solved_counts([self.author.pk])[self.author.pk], 1)

    def test_repair_command_previews_then_repairs_legacy_orphan_once(self):
        item = self.submit_day()
        Submission.objects.filter(pk=item.pk).delete()
        out = StringIO()
        call_command('reconcile_signins',stdout=out)
        self.assertIn('orphan_dates=1',out.getvalue())
        self.assertEqual(self.balance(), 3)
        call_command('reconcile_signins',apply=True,stdout=StringIO())
        self.assertEqual(self.balance(), 0)
        call_command('reconcile_signins',apply=True,stdout=StringIO())
        self.assertEqual(self.balance(), 0)

    def test_rejected_correction_keeps_original_day_and_time_with_other_valid_submission(self):
        first = self.submit_day()
        first_time = first.submitted_at
        original_problem = self.problem
        self.problem = Problem.objects.create(identity='correction:other', url='https://example.com/other')
        self.submit_day()
        self.reject(first)
        self.problem = original_problem
        with patch('django.utils.timezone.now', return_value=timezone.now()+timedelta(days=1)):
            self.submit_day(self.today, submission_id=first.pk)
        first.refresh_from_db()
        self.assertEqual(first.submitted_at, first_time)
        self.assertEqual(first.record_date, self.today)
        self.assertEqual(self.balance(), 3)
        self.assertFalse(CheckinRecord.objects.get(member=self.author_member).is_makeup)
        self.assertEqual(lifetime_solved_counts([self.author.pk])[self.author.pk], 2)

    def test_rejected_only_record_requires_ticket_for_new_overview_but_not_correction(self):
        StreakReward.objects.create(team=self.team, days=1, reward=5)
        item = self.submit_day()
        first_time = item.submitted_at
        ticket = ShopItem.objects.create(team=self.team,name='Ticket',price=1,item_type='makeup_ticket')
        inventory = UserInventory.objects.create(team=self.team,member=self.author_member,item=ticket,quantity=2)
        with patch('django.utils.timezone.now', return_value=timezone.now()+timedelta(days=1)):
            self.reject(item)
            self.assertEqual(self.balance(), 0)
            self.assertFalse(self.activity(self.today)['makeupOpen'])
            self.assertFalse(MakeupPermission.objects.filter(member=self.author_member,record_date=self.today).exists())
            with patch('club.problem_parser.get_problem', return_value=self.problem):
                denied = self.client.post('/api/submissions', {'week_id':item.week_id,'record_date':self.today.isoformat(),
                    'problem_url':self.problem.url,'proof':self.image(),'code':'int main() {}','code_language':'cpp'})
            self.assertEqual(denied.status_code, 409)
            self.assertIn('补签券', denied.json()['error'])
            self.submit_day(self.today, submission_id=item.pk)
            self.assertEqual(self.balance(), 8)
            self.assertFalse(CheckinRecord.objects.get(member=self.author_member).is_makeup)
            item.refresh_from_db()
            self.assertEqual(item.submitted_at, first_time)
            self.reject(item)
            makeup_checkin(self.author_member,self.today)
            inventory.refresh_from_db()
            self.assertEqual(inventory.quantity, 1)
            self.problem = Problem.objects.create(identity='correction:new',url='https://example.com/new')
            self.submit_day(self.today)
            self.assertTrue(CheckinRecord.objects.get(member=self.author_member).is_makeup)
            self.assertEqual(self.balance(), 5)
            self.problem = item.problem
            self.submit_day(self.today, submission_id=item.pk)
            self.assertEqual(self.balance(), 5)
        inventory.refresh_from_db()
        self.assertEqual(inventory.quantity, 1)

    def test_standalone_checkin_without_valid_submission_has_no_side_effects(self):
        StreakReward.objects.create(team=self.team,days=1,reward=5)
        for day in (self.today, self.today-timedelta(days=1)):
            from .currency_services import perform_checkin
            with self.assertRaisesMessage(ValueError, '没有有效提交'):
                perform_checkin(self.author_member, day=day)
        response = self.client.post('/api/currency/checkin')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
        self.assertFalse(CurrencyTransaction.objects.filter(member=self.author_member).exists())
        self.assertFalse(WeeklyStreakGrant.objects.filter(member=self.author_member).exists())

    def test_standalone_checkin_cannot_restore_deleted_or_rejected_submission_rewards(self):
        StreakReward.objects.create(team=self.team,days=1,reward=5)
        for reject in (False, True):
            with self.subTest(reject=reject):
                self.problem = Problem.objects.create(identity=f'checkin:bypass:{reject}',url=f'https://example.com/bypass/{reject}')
                item = self.submit_day()
                if reject:
                    self.reject(item)
                else:
                    self.remove(item)
                before = CurrencyTransaction.objects.filter(member=self.author_member).count()
                for _ in range(2):
                    response = self.client.post('/api/currency/checkin')
                    self.assertEqual(response.status_code, 400, response.content)
                self.assertEqual(self.balance(), 0)
                self.assertFalse(CheckinRecord.objects.filter(member=self.author_member).exists())
                self.assertIsNotNone(WeeklyStreakGrant.objects.get(member=self.author_member).revoked_at)
                self.assertEqual(CurrencyTransaction.objects.filter(member=self.author_member).count(), before)

    def test_standalone_checkin_requires_same_member_team_and_record_date(self):
        item = self.submit_day()
        CheckinRecord.objects.filter(member=self.author_member).delete()
        CurrencyBalance.objects.filter(member=self.author_member).update(balance=0)
        item.record_date = self.today-timedelta(days=1)
        item.save(update_fields=['record_date'])
        self.assertEqual(self.client.post('/api/currency/checkin').status_code, 400)
        item.record_date = self.today
        item.member = self.owner_member
        item.save(update_fields=['record_date','member'])
        self.assertEqual(self.client.post('/api/currency/checkin').status_code, 400)
        item.member = self.author_member
        item.save(update_fields=['member'])
        self.assertEqual(self.client.post('/api/currency/checkin').status_code, 200)
        self.assertEqual(self.balance(), 3)
        self.assertEqual(self.client.post('/api/currency/checkin').status_code, 400)
        self.assertEqual(self.balance(), 3)
