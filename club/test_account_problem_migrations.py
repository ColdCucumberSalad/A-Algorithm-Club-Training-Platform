from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AccountProblemMigrationTests(TransactionTestCase):
    """Both already-deployed branch histories must upgrade without fake migrations."""

    merged = [('club', '0049_currency_transaction_big_amount')]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(self.merged)
        super().tearDown()

    def seed(self, apps, global_wallet=False):
        User = apps.get_model('auth', 'User')
        Team = apps.get_model('club', 'Team')
        Member = apps.get_model('club', 'TeamMembership')
        Balance = apps.get_model('club', 'CurrencyBalance')
        Semester = apps.get_model('club', 'Semester')
        Week = apps.get_model('club', 'Week')
        Problem = apps.get_model('club', 'Problem')
        Submission = apps.get_model('club', 'Submission')
        user = User.objects.create(username='migration-account')
        teams = [Team.objects.create(name=f'Team {i}', code=f'MIG-{i}', created_by=user) for i in range(2)]
        members = [Member.objects.create(user=user, team=team, display_name='Member') for team in teams]
        if global_wallet:
            Balance.objects.create(user=user, team=teams[0], member=members[0], balance=12)
        else:
            for member, amount in zip(members, [5, 7]):
                Balance.objects.create(team=member.team, member=member, balance=amount)
        now = timezone.now()
        semester = Semester.objects.create(team=teams[0], name='Migration semester',
            starts_on=timezone.localdate(), ends_on=timezone.localdate()+timedelta(days=7))
        week = Week.objects.create(semester=semester, number=1, starts_at=now, ends_at=now+timedelta(days=7))
        problem = Problem.objects.create(identity='migration-problem', url='https://example.com/problem')
        row = Submission.objects.create(team=teams[0], member=members[0], semester=semester, week=week, problem=problem)
        return user.pk, row.pk, problem.pk

    def test_production_problem_branch_preserves_duplicates_and_merges_wallets(self):
        self.migrate([('club', '0044_merge_tracker_notifications')])
        apps = self.migrate([('club', '0046_duplicate_submission_priority')])
        uid, sid, pid = self.seed(apps)
        Submission = apps.get_model('club', 'Submission')
        Problem = apps.get_model('club', 'Problem')
        alias = Problem.objects.create(identity='migration-alias', url='https://example.com/alias', canonical_id=pid)
        row = Submission.objects.get(pk=sid)
        row.is_valid=False; row.is_duplicate=True
        row.original_problem_url=alias.url
        row.duplicate_state={'parts':{'proof':{'status':'approved','points':3}}}
        row.save()
        original_time=row.first_submitted_at
        apps = self.migrate(self.merged)
        row = apps.get_model('club', 'Submission').objects.get(pk=sid)
        self.assertTrue(row.is_duplicate); self.assertFalse(row.is_valid)
        self.assertEqual(row.original_problem_url, alias.url)
        self.assertEqual(row.first_submitted_at, original_time)
        self.assertEqual(row.duplicate_state['parts']['proof']['points'], 3)
        self.assertEqual(apps.get_model('club','Problem').objects.get(pk=alias.pk).canonical_id,pid)
        self.assertEqual(list(apps.get_model('club','CurrencyBalance').objects.filter(user_id=uid).values_list('balance',flat=True)),[12])

    def test_account_branch_preserves_wallet_and_backfills_submission_priority(self):
        self.migrate([('club', '0044_merge_tracker_notifications')])
        apps = self.migrate([('club', '0047_report_coin_transaction_types')])
        uid, sid, pid = self.seed(apps, global_wallet=True)
        submitted_at = apps.get_model('club','Submission').objects.get(pk=sid).submitted_at
        apps = self.migrate(self.merged)
        row = apps.get_model('club','Submission').objects.get(pk=sid)
        self.assertTrue(row.is_valid); self.assertFalse(row.is_duplicate)
        self.assertEqual(row.first_submitted_at, submitted_at)
        self.assertEqual(row.original_problem_url,'https://example.com/problem')
        self.assertEqual(apps.get_model('club','CurrencyBalance').objects.get(user_id=uid).balance,12)
