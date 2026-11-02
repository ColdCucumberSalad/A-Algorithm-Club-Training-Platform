from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from . import test_community as fixtures
from django.core import signing
from django.core.cache import caches
from .models import Submission, Problem
from .problem_equivalence import reconcile_problem

class GalleryAudit(TestCase):
    setUp = fixtures.CommunityTests.setUp

    def record(self, problem, minutes):
        row = Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester, week=self.week, problem=problem)
        Submission.objects.filter(pk=row.pk).update(submitted_at=timezone.now()-timedelta(minutes=minutes))
        return row

    def test_deleting_latest_solution_repeats_problem(self):
        old = self.record(self.problem, 100)
        latest = self.record(self.problem, 0)
        for i in range(21):
            p = Problem.objects.create(identity=f'audit:{i}', url=f'https://qoj.ac/problem/{i}')
            self.record(p, i+1)
        first = self.client.get('/api/showcase?all=1').json()
        self.assertIn(self.problem.pk, [p['id'] for p in first['problems']])
        latest.delete()
        second = self.client.get('/api/showcase', {'all':'1', 'cursor':first['next']}).json()
        self.assertNotIn(self.problem.pk, [p['id'] for p in second['problems']], 'Already displayed problem must not repeat')

    def test_rejecting_latest_solution_does_not_repeat_problem(self):
        old = self.record(self.problem, 100)
        latest = self.record(self.problem, 0)
        for i in range(21):
            p = Problem.objects.create(identity=f'audit:{i}', url=f'https://qoj.ac/problem/{i}')
            self.record(p, i+1)
        first = self.client.get('/api/showcase?all=1').json()
        self.assertIn(self.problem.pk, [p['id'] for p in first['problems']])
        Submission.objects.filter(pk=latest.pk).update(is_valid=False)
        second = self.client.get('/api/showcase', {'all':'1', 'cursor':first['next']}).json()
        self.assertNotIn(self.problem.pk, [p['id'] for p in second['problems']], 'Already displayed problem must not repeat')

    def test_cross_platform_alias_remains_findable_by_original_platform(self):
        self.problem.title = 'same problem'
        self.problem.status = 'success'
        self.problem.save()
        self.record(self.problem, 2)
        other = Problem.objects.create(identity='luogu:P1000', url='https://www.luogu.com.cn/problem/P1000', title=self.problem.title, status='success', generation=1)
        row = Submission.objects.create(team=self.team, member=self.owner_member, semester=self.semester, week=self.week, problem=other, original_problem_url=other.url)
        with patch('club.problem_equivalence.ai_same_problem', return_value=True):
            reconcile_problem(other.pk, 1)
        row.refresh_from_db()
        self.assertTrue(row.is_valid)
        self.assertEqual(row.problem_id, self.problem.pk)
        data = self.client.get('/api/showcase?all=1&platform=luogu').json()
        self.assertEqual(len(data['problems']), 1, 'Visible Luogu solution must remain discoverable under Luogu')

    def test_platform_counts_details_and_all_platforms_match(self):
        self.record(self.problem, 3)
        luogu = Submission.objects.create(team=self.team, member=self.owner_member, semester=self.semester, week=self.week, problem=self.problem, original_problem_url='https://www.luogu.com.cn/problem/P1000')
        all_rows = self.client.get('/api/showcase?all=1').json()
        self.assertEqual(len(all_rows['problems']), 1)
        self.assertEqual(all_rows['problems'][0]['count'], 2)
        selected = self.client.get('/api/showcase?all=1&platform=luogu').json()
        self.assertEqual(selected['problems'][0]['count'], 1)
        self.assertIn('luogu.com.cn', selected['problems'][0]['url'])
        url = f'/api/problems/{self.problem.pk}/submissions'
        detail = self.client.get(url, {'platform': 'luogu', 'cursor': ''}).json()
        self.assertEqual([r['id'] for r in detail['submissions']], [luogu.pk])
        self.assertIn('luogu.com.cn', detail['problem']['url'])
        self.assertEqual(len(self.client.get(url, {'cursor': ''}).json()['submissions']), 2)

    def make_pages(self):
        rows = []
        for i in range(45):
            p = Problem.objects.create(identity=f'page:{i}', url=f'https://qoj.ac/problem/{i}')
            rows.append(self.record(p, i))
        return rows, self.client.get('/api/showcase?all=1').json()

    def test_invalid_records_skipped_and_page_filled(self):
        rows, first = self.make_pages()
        Submission.objects.filter(pk__in=[r.pk for r in rows[20:23]]).update(is_valid=False)
        second = self.client.get('/api/showcase', {'all': '1', 'cursor': first['next']}).json()
        self.assertEqual([r['id'] for r in second['problems']], [r.problem_id for r in rows[23:43]])
        third = self.client.get('/api/showcase', {'all': '1', 'cursor': second['next']}).json()
        self.assertEqual([r['id'] for r in third['problems']], [r.problem_id for r in rows[43:]])

    def test_archive_and_membership_rechecked(self):
        rows, first = self.make_pages()
        self.semester.archived_at = timezone.now()
        self.semester.save(update_fields=['archived_at'])
        self.assertEqual(self.client.get('/api/showcase', {'all': '1', 'cursor': first['next']}).json()['problems'], [])
        self.author_member.is_active = False
        self.author_member.save(update_fields=['is_active'])
        self.assertEqual(self.client.get('/api/showcase', {'all': '1', 'cursor': first['next']}).status_code, 403)

    def test_expired_snapshot_and_changed_scope_rejected(self):
        rows, first = self.make_pages()
        self.assertEqual(self.client.get('/api/showcase', {'all':'1', 'cursor':first['next'], 'platform':'qoj'}).status_code, 400)
        state = signing.loads(first['next'], salt='gallery-snapshot-v2')
        caches['gallery'].delete('snapshot:' + state['id'])
        response = self.client.get('/api/showcase', {'all':'1', 'cursor':first['next']})
        self.assertEqual(response.status_code, 400)
        self.assertIn('过期', response.json()['error'])

    def test_edit_does_not_remove_pending_detail_from_snapshot(self):
        rows = [self.record(self.problem, i) for i in range(23)]
        url = f'/api/problems/{self.problem.pk}/submissions'
        first = self.client.get(url, {'cursor':''}).json()
        Submission.objects.filter(pk=rows[21].pk).update(submitted_at=timezone.now())
        second = self.client.get(url, {'cursor':first['next']}).json()
        self.assertEqual([r['id'] for r in second['submissions']], [r.pk for r in rows[20:]])

    def test_day_group_times_stay_fixed_until_refresh(self):
        rows, first = self.make_pages()
        pending = rows[21]
        pending.refresh_from_db()
        original = pending.submitted_at.isoformat()
        Submission.objects.create(team=self.team, member=self.author_member, semester=self.semester, week=self.week, problem=pending.problem)
        second = self.client.get('/api/showcase', {'all':'1', 'cursor':first['next']}).json()
        found = next(p for p in second['problems'] if p['id'] == pending.problem_id)
        self.assertEqual(found['group_uploaded_at'], original)
        refreshed = self.client.get('/api/showcase?all=1').json()
        self.assertEqual(refreshed['problems'][0]['id'], pending.problem_id)
        self.assertNotEqual(refreshed['problems'][0]['group_uploaded_at'], original)

    def test_platform_day_uses_latest_upload_in_selected_platform(self):
        older = self.record(self.problem, 60)
        older.refresh_from_db()
        newer = Submission.objects.create(team=self.team, member=self.owner_member, semester=self.semester, week=self.week, problem=self.problem, original_problem_url='https://www.luogu.com.cn/problem/P1000')
        selected = self.client.get('/api/showcase?all=1&platform=nowcoder').json()['problems'][0]
        self.assertEqual(selected['group_uploaded_at'], older.submitted_at.isoformat())
        all_rows = self.client.get('/api/showcase?all=1').json()['problems']
        self.assertEqual(len(all_rows), 1)
        self.assertEqual(all_rows[0]['group_uploaded_at'], newer.submitted_at.isoformat())

    def test_concurrent_deletion_or_rejection_during_list_response(self):
        from . import community_views
        original = community_views.snapshot_page
        for platform in ('', 'nowcoder'):
            for action in ('delete', 'reject'):
                with self.subTest(platform=platform, action=action):
                    row = self.record(self.problem, 0)
                    def change_after_group_query(*args, **kwargs):
                        result = original(*args, **kwargs)
                        if action == 'delete':
                            row.delete()
                        else:
                            Submission.objects.filter(pk=row.pk).update(is_valid=False)
                        return result
                    with patch.object(community_views, 'snapshot_page', side_effect=change_after_group_query):
                        response = self.client.get('/api/showcase', {'all':'1', 'platform':platform})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.json()['problems'], [])
