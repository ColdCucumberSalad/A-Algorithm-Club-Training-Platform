from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from .platform_records import history_page
from .platform_sync import SyncError, validate_account


class LeetcodeRecordTests(SimpleTestCase):
    def remote(self, submissions, *, cookie=True, identity=None, has_next=False):
        remote = Mock(credentials={'cookie': 'fixture'} if cookie else {})
        remote.json.side_effect = [
            {'data': {'userStatus': identity or {'isSignedIn': True, 'username': 'reader', 'userSlug': 'reader'}}},
            {'data': {'submissionList': {'hasNext': has_next, 'submissions': submissions}}},
        ]
        return remote

    def test_cn_cookie_reads_problem_urls_and_keeps_pagination(self):
        remote = self.remote([
            {'statusDisplay': 'Accepted', 'title': 'Two Sum', 'url': '/problems/two-sum/', 'timestamp': '1793664000'},
            {'statusDisplay': 'Wrong Answer', 'url': '/problems/other/', 'timestamp': '1793663999'},
        ], has_next=True)
        rows, state, done = history_page(remote, SimpleNamespace(platform='leetcode', account='cn:reader'), {'page': 2, 'full': True})
        self.assertEqual([r['problem_key'] for r in rows], ['two-sum'])
        self.assertEqual(rows[0]['url'], 'https://leetcode.cn/problems/two-sum/')
        self.assertEqual(rows[0]['solved_on'], '2026-11-03')
        self.assertFalse(done)
        self.assertEqual(state['page'], 3)
        self.assertTrue(state['complete'])
        for call in remote.json.call_args_list:
            self.assertEqual(call.args[0], 'https://leetcode.cn/graphql/')
        payload = remote.json.call_args.kwargs['payload']
        self.assertEqual(payload['variables'], {'offset': 20, 'limit': 20})
        self.assertNotIn('titleSlug', payload['query'])

    def test_cn_absolute_problem_url_and_incremental_cutoff(self):
        remote = self.remote([{'statusDisplay': '通过', 'title': '题目', 'url': 'https://leetcode.cn/problems/two-sum/description/', 'timestamp': '1793664000'}], has_next=True)
        rows, _, done = history_page(remote, SimpleNamespace(platform='leetcode', account='cn:reader'), {'cursor': 1794000000})
        self.assertEqual(rows[0]['problem_key'], 'two-sum')
        self.assertTrue(done)

    def test_global_cookie_uses_global_slug_and_endpoint(self):
        remote = self.remote([{'statusDisplay': 'Accepted', 'title': 'Two Sum', 'titleSlug': 'two-sum', 'timestamp': '1793664000'}])
        rows, _, done = history_page(remote, SimpleNamespace(platform='leetcode', account='reader'), {'full': True})
        self.assertEqual(rows[0]['url'], 'https://leetcode.com/problems/two-sum/')
        self.assertTrue(done)
        for call in remote.json.call_args_list:
            self.assertEqual(call.args[0], 'https://leetcode.com/graphql/')
        self.assertIn('titleSlug', remote.json.call_args.kwargs['payload']['query'])

    def test_cookie_mismatch_and_expiry_never_read_history(self):
        for identity in [{'isSignedIn': False}, {'isSignedIn': True, 'username': 'other', 'userSlug': 'other'}]:
            remote = self.remote([], identity=identity)
            with self.assertRaisesMessage(SyncError, 'Cookie 与账号不匹配'):
                history_page(remote, SimpleNamespace(platform='leetcode', account='cn:reader'), {})
            self.assertEqual(remote.json.call_count, 1)

    def test_cn_cookie_with_missing_problem_identity_fails_instead_of_dropping_ac(self):
        remote = self.remote([{'statusDisplay': 'Accepted', 'url': '/submissions/detail/123/', 'timestamp': '1793664000'}])
        with self.assertRaisesMessage(SyncError, '缺少题目标识'):
            history_page(remote, SimpleNamespace(platform='leetcode', account='cn:reader'), {})

    def test_public_history_routes_to_the_selected_region(self):
        for account, endpoint, data in [
            ('cn:reader', 'https://leetcode.cn/graphql/noj-go/', {'recentACSubmissions': [{'submitTime': 1793664000, 'question': {'titleSlug': 'two-sum', 'title': 'Two Sum'}}]}),
            ('reader', 'https://leetcode.com/graphql/', {'recentAcSubmissionList': [{'timestamp': '1793664000', 'titleSlug': 'two-sum', 'title': 'Two Sum'}]}),
        ]:
            remote = Mock(credentials={})
            remote.json.return_value = {'data': data}
            rows, state, done = history_page(remote, SimpleNamespace(platform='leetcode', account=account), {})
            self.assertEqual(remote.json.call_args.args[0], endpoint)
            self.assertEqual(remote.json.call_args.kwargs['payload']['variables'], {'u': 'reader'})
            self.assertEqual(rows[0]['problem_key'], 'two-sum')
            self.assertTrue(done)
            self.assertFalse(state['complete'])
            self.assertEqual(validate_account('leetcode', account), account)
