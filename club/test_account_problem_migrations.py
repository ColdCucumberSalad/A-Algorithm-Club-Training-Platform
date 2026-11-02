from datetime import timedelta
import uuid

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class AccountProblemMigrationTests(TransactionTestCase):
    """Both already-deployed branch histories must upgrade without fake migrations."""

    merged = [('club', '0051_link_tip_ledgers')]

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

    def test_tip_snapshot_cleanup_preserves_amounts_balances_and_audit_links(self):
        apps=self.migrate([('club','0049_currency_transaction_big_amount')])
        uid,sid,pid=self.seed(apps,global_wallet=True)
        row=apps.get_model('club','Submission').objects.get(pk=sid)
        sender=apps.get_model('auth','User').objects.create(username='historical-sender')
        member=apps.get_model('club','TeamMembership').objects.create(user=sender,team_id=row.team_id,
            display_name='Historical sender 提交 #999')
        Balance=apps.get_model('club','CurrencyBalance')
        Balance.objects.filter(user_id=uid).update(balance=19)
        Balance.objects.create(user=sender,team_id=row.team_id,member=member,balance=13)
        receipt=apps.get_model('club','SubmissionTip').objects.create(request_id=uuid.uuid4(),
            team_id=row.team_id,sender_user=sender,sender=member,recipient_id=row.member_id,submission=row,amount=7)
        Ledger=apps.get_model('club','CurrencyTransaction')
        sent=Ledger.objects.create(user=sender,team_id=row.team_id,member=member,amount=-7,balance_after=13,
            transaction_type='tip_sent',description=f'打赏 Member 的提交 #{sid}')
        received=Ledger.objects.create(user_id=uid,team_id=row.team_id,member_id=row.member_id,amount=7,balance_after=19,
            transaction_type='tip_received',description=f'收到 {member.display_name} 对提交 #{sid} 的打赏')
        before=list(Ledger.objects.order_by('pk').values())
        balances=list(Balance.objects.order_by('pk').values())
        receipt_before=apps.get_model('club','SubmissionTip').objects.values().get(pk=receipt.pk)
        apps=self.migrate([('club','0050_anonymize_tip_descriptions')])
        after=list(apps.get_model('club','CurrencyTransaction').objects.order_by('pk').values())
        self.assertEqual([r['description'] for r in after],[f'打赏提交 #{sid}',f'收到提交 #{sid} 的打赏'])
        for prior,current in zip(before,after):
            prior.pop('description');current.pop('description')
            self.assertEqual(prior,current)
        self.assertEqual(list(apps.get_model('club','CurrencyBalance').objects.order_by('pk').values()),balances)
        self.assertEqual(apps.get_model('club','SubmissionTip').objects.values().get(pk=receipt.pk),receipt_before)

    def test_tip_links_backfill_repeated_transfers_without_guessing_ambiguous_history(self):
        apps=self.migrate([('club','0050_anonymize_tip_descriptions')])
        uid,sid,pid=self.seed(apps,global_wallet=True)
        submission=apps.get_model('club','Submission').objects.get(pk=sid)
        sender=apps.get_model('auth','User').objects.create(username='tip-link-sender')
        member=apps.get_model('club','TeamMembership').objects.create(user=sender,team_id=submission.team_id,
            display_name='Known sender')
        Tip=apps.get_model('club','SubmissionTip')
        Ledger=apps.get_model('club','CurrencyTransaction')
        base=timezone.now()-timedelta(minutes=5)
        expected={}
        for index in range(2):
            tip=Tip.objects.create(request_id=uuid.uuid4(),team_id=submission.team_id,sender_user=sender,
                sender=member,recipient_id=submission.member_id,submission=submission,amount=7)
            Tip.objects.filter(pk=tip.pk).update(created_at=base+timedelta(seconds=index*3))
            for kind,owner,mid,delta,balance,offset in [
                    ('tip_sent',sender.pk,member.pk,-7,13-index*7,1),
                    ('tip_received',uid,submission.member_id,7,19+index*7,2)]:
                row=Ledger.objects.create(user_id=owner,team_id=submission.team_id,member_id=mid,
                    amount=delta,balance_after=balance,transaction_type=kind,description=f'提交 #{sid}')
                Ledger.objects.filter(pk=row.pk).update(created_at=base+timedelta(seconds=index*3+offset))
                expected[row.pk]=tip.pk
        for offset in (10,11):
            tip=Tip.objects.create(request_id=uuid.uuid4(),team_id=submission.team_id,sender_user=sender,
                sender=member,recipient_id=submission.member_id,submission=submission,amount=9)
            Tip.objects.filter(pk=tip.pk).update(created_at=base+timedelta(seconds=offset))
        ambiguous=Ledger.objects.create(user_id=uid,team_id=submission.team_id,member_id=submission.member_id,
            amount=9,balance_after=35,transaction_type='tip_received',description=f'收到提交 #{sid} 的打赏')
        Ledger.objects.filter(pk=ambiguous.pk).update(created_at=base+timedelta(seconds=12))
        before=list(Ledger.objects.order_by('pk').values())
        apps=self.migrate(self.merged)
        after=list(apps.get_model('club','CurrencyTransaction').objects.order_by('pk').values())
        for old,new in zip(before,after):
            self.assertEqual(new.pop('tip_id'),expected.get(new['id']))
            self.assertEqual(old,new)
