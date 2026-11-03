from datetime import timedelta
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from .models import PlatformBinding, PlatformSolvedBaseline, PlatformSolvedRecord, TrackerCatalog
from .solved import solved_evidence, semester_solved_counts


class AggregateSolvedTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='aggregate-test')
        self.binding = PlatformBinding.objects.create(user=self.user, platform='leetcode',
            account='cn:test', sync_state={'version': 2})
        self.day = timezone.localdate() - timedelta(days=2)
        self.base = PlatformSolvedBaseline.objects.create(binding=self.binding, total=79,
            captured_at=timezone.now()-timedelta(days=1), problem_ids=['known'],
            dated_problems={'known': self.day.isoformat()}, ids_complete=False)

    def evidence(self):
        return solved_evidence([self.user.pk])[self.user.pk]

    def test_missing_details_only_fill_total_and_undated(self):
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (79, 78))
        term = SimpleNamespace(starts_on=self.day, ends_on=timezone.localdate())
        self.assertEqual(semester_solved_counts([self.user.pk], term)[self.user.pk], 1)

    def test_backfill_and_duplicate_do_not_inflate_total(self):
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='known', solved_on=self.day)
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='backfill', solved_on=self.day)
        self.assertEqual((self.evidence()['total'], self.evidence()['undated']), (79, 77))
        self.base.problem_ids += ['backfill']
        self.base.save()
        self.assertEqual(self.evidence()['total'], 79)

    def test_unknown_overlap_and_separate_platform(self):
        second = PlatformBinding.objects.create(user=self.user, platform='leetcode', account='cn:second',
            sync_state={'version': 2})
        PlatformSolvedBaseline.objects.create(binding=second, total=20, captured_at=timezone.now())
        luogu = PlatformBinding.objects.create(user=self.user, platform='luogu', account='test',
            sync_state={'version': 2})
        PlatformSolvedBaseline.objects.create(binding=luogu, total=3, captured_at=timezone.now())
        self.assertEqual(self.evidence()['total'], 82)

    def test_complete_baseline_counts_new_problem_once(self):
        self.base.total = 1
        self.base.ids_complete = True
        self.base.save()
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='new', solved_on=timezone.localdate())
        self.assertEqual(self.evidence()['total'], 2)
        self.base.total = 2
        self.base.problem_ids += ['new']
        self.base.captured_at = timezone.now()
        self.base.save()
        self.assertEqual(self.evidence()['total'], 2)

    def test_incomplete_baseline_cannot_prove_later_solve_is_new(self):
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='possibly-repeated', solved_on=timezone.localdate())
        self.assertEqual(self.evidence()['total'], 79)


class NowcoderAliasFloorTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='alias-floor-test')
        self.binding = PlatformBinding.objects.create(user=self.user, platform='nowcoder',
            account='123', sync_state={'version': 2})
        self.day = timezone.localdate() - timedelta(days=2)
        keys = ['contest/10/a', 'problem/100']
        self.base = PlatformSolvedBaseline.objects.create(binding=self.binding, total=2,
            captured_at=timezone.now()-timedelta(days=1), problem_ids=keys,
            dated_problems={key: self.day.isoformat() for key in keys}, ids_complete=True)
        for key in keys:
            PlatformSolvedRecord.objects.create(binding=self.binding, problem_key=key, solved_on=self.day)
        TrackerCatalog.objects.create(kind='nowcoder', contests=[{'problems': [
            {'key': 'contest/10/a', 'aliases': ['problem/100']}]}])

    def evidence(self):
        return solved_evidence([self.user.pk])[self.user.pk]

    def test_complete_dated_aliases_do_not_create_anonymous_solve(self):
        data = self.evidence()
        self.assertEqual((data['total'], data['undated'], len(data['items'])), (1, 0, 1))

    def test_incomplete_baseline_retains_truly_unknown_solves(self):
        self.base.total = 10
        self.base.ids_complete = False
        self.base.save()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (9, 8))

    def test_complete_baseline_still_counts_new_solve(self):
        PlatformSolvedRecord.objects.create(binding=self.binding, problem_key='problem/200',
            solved_on=timezone.localdate())
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (2, 0))

    def test_unproven_aliases_are_not_discounted(self):
        TrackerCatalog.objects.all().delete()
        data = self.evidence()
        self.assertEqual((data['total'], data['undated']), (2, 0))
