from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from . import test_community as fixtures
from .models import (DatedSolvedProblemCredit, PlatformBinding, PlatformSolvedBaseline,
                     PlatformSolvedRecord, Problem, SolvedProblemCredit, Submission, SubmissionPart)
from .solved import archive_submission_credits, solved_evidence, semester_solved_counts


class LeetcodeSolvedIdentityTests(TestCase):
    def setUp(self):
        fixtures.CommunityTests.setUp(self)
        self.day = timezone.localdate()-timedelta(days=2)
        self.binding = PlatformBinding.objects.create(user=self.author, platform='leetcode',
            account='cn:reader', sync_state={'version': 2})
        self.base = PlatformSolvedBaseline.objects.create(binding=self.binding, total=79,
            captured_at=timezone.now()-timedelta(days=1), ids_complete=False)

    def evidence(self):
        return solved_evidence([self.author.pk])[self.author.pk]

    def credit(self, key='leetcode:two-sum', dated=True):
        SolvedProblemCredit.objects.get_or_create(user=self.author, source='submission', problem_key=key)
        if dated:
            DatedSolvedProblemCredit.objects.get_or_create(user=self.author, source='submission',
                problem_key=key, solved_on=self.day)

    def proof(self, host='leetcode.com'):
        problem = Problem.objects.create(identity='leetcode:two-sum',
            url=f'https://{host}/problems/two-sum/')
        row = Submission.objects.create(team=self.team, member=self.author_member,
            semester=self.semester, week=self.week, problem=problem, record_date=self.day)
        SubmissionPart.objects.create(submission=row, kind='proof', status='approved')
        return row

    def test_old_archived_proof_uses_current_region_floor(self):
        self.credit()
        for account in ('cn:reader', 'reader'):
            with self.subTest(account=account):
                self.binding.account = account
                self.binding.save()
                data = self.evidence()
                self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))
                self.assertEqual(semester_solved_counts([self.author.pk], self.semester)[self.author.pk], 1)
        self.assertEqual(SolvedProblemCredit.objects.get(user=self.author).problem_key, 'leetcode:two-sum')

    def test_undated_archive_does_not_invent_a_date(self):
        self.credit(dated=False)
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (79, 79))
        self.assertIsNone(data['items'][0]['date'])

    def test_platform_backfill_keeps_earliest_verified_archive_date(self):
        self.credit()
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='two-sum',
            solved_on=self.day+timedelta(days=1))
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))
        self.assertEqual(data['items'][0]['date'], self.day)

    def test_live_proof_and_archive_count_once_despite_other_region_url(self):
        self.proof()
        self.credit()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))

    def test_real_archive_survives_source_deletion_without_inflating_floor(self):
        row = self.proof()
        archive_submission_credits(self.semester)
        row.delete()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))

    def test_old_contest_and_regional_keys_merge_with_proof(self):
        for key in ('leetcode:two-sum', 'leetcode:weekly-contest-1:two-sum',
                    'leetcode_cn:two-sum', 'leetcode_us:two-sum'):
            self.credit(key)
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))

    def test_both_regions_share_solved_identities_and_larger_floor(self):
        second = PlatformBinding.objects.create(user=self.author, platform='leetcode',
            account='reader', sync_state={'version': 2})
        PlatformSolvedBaseline.objects.create(binding=second, total=50,
            captured_at=timezone.now()-timedelta(days=1))
        for binding in (self.binding, second):
            PlatformSolvedRecord.objects.create(binding=binding, problem_key='two-sum', solved_on=self.day)
        self.credit()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (79, 78, 1))

    def test_removing_one_region_recalculates_using_remaining_binding(self):
        second = PlatformBinding.objects.create(user=self.author, platform='leetcode',
            account='reader', sync_state={'version': 2})
        PlatformSolvedBaseline.objects.create(binding=second, total=100,
            captured_at=timezone.now()-timedelta(days=1))
        self.credit('leetcode_us:two-sum')
        self.assertEqual(self.evidence()['total'], 100)
        second.delete()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (79, 78))
        self.assertEqual(SolvedProblemCredit.objects.get(user=self.author).problem_key, 'leetcode_us:two-sum')

    def test_other_users_binding_does_not_change_this_users_region(self):
        PlatformBinding.objects.create(user=self.reader, platform='leetcode', account='reader',
            sync_state={'version': 2})
        self.credit()
        data = solved_evidence([self.author.pk, self.reader.pk])
        self.assertEqual((data[self.author.pk]['total'], data[self.author.pk]['undated']), (79, 78))
        self.assertEqual(data[self.reader.pk]['total'], 0)

    def test_no_leetcode_binding_preserves_one_archived_live_solve(self):
        self.binding.delete()
        PlatformBinding.objects.create(user=self.author, platform='codeforces', account='reader',
            sync_state={'version': 2})
        self.proof()
        self.credit()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (1, 0, 1))
