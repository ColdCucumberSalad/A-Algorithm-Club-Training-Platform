from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from .platform_records import history_page, profile
from .platform_sync import SyncError


def submissions(rows='', next_page=False):
    return ('<table><tr><td>unrelated table</td></tr></table>'
            '<table><tr><th>Problem</th><th>Submitter</th><th>Result</th><th>Submit time</th></tr>'
            + rows + '</table>' + ('<a href="?page=2">2</a>' if next_page else ''))


def row(user='reader', result='AC ✓', key='42', linked=False):
    name = (f'<a href="/user/profile/{user}">{user}</a>' if linked else
            f'<span class="uoj-username" data-nickname="{user}" data-rating="1800">{user}</span><sup>#</sup>')
    return (f'<tr><td><a href="/contest/9/problem/{key}">Task</a></td><td>{name}</td>'
            f'<td>{result}</td><td>2026-11-01 12:30:00</td></tr>')


class QojPageTests(SimpleTestCase):
    def setUp(self):
        self.binding = SimpleNamespace(platform='qoj', account='reader')
        self.remote = Mock(credentials={'platform': 'qoj', 'cookie': '__Host-UOJSESSID=fixture'})

    def read(self, html, **state):
        self.remote.text.return_value = html
        return history_page(self.remote, self.binding, dict(full=True, **state))

    def test_private_plain_username_is_read_and_pagination_kept(self):
        rows, state, done = self.read(submissions(row(), next_page=True))
        self.assertEqual([r['problem_key'] for r in rows], ['42'])
        self.assertEqual(rows[0]['solved_on'], '2026-11-01')
        self.assertEqual(rows[0]['url'], 'https://qoj.ac/problem/42')
        self.assertEqual(state['page'], 2)
        self.assertFalse(done)

    def test_old_linked_username_and_compact_table_still_work(self):
        rows, _, done = self.read('<table>' + row(linked=True, result='100.0') + '</table>')
        self.assertEqual(len(rows), 1)
        self.assertTrue(done)

    def test_foreign_user_and_wa_are_not_marked_accepted(self):
        html = submissions(row(user='someone-else') + row(result='WA (100ms)', key='43') + row(key='44'))
        rows, _, _ = self.read(html)
        self.assertEqual([r['problem_key'] for r in rows], ['44'])
        with self.assertRaisesMessage(SyncError, '绑定账号不一致'):
            self.read(submissions(row(user='someone-else')))

    def test_unknown_pages_are_errors_not_empty_successes(self):
        for html in ['<table><tr><td>Not a submission list</td></tr></table>',
                     '<html><title>Just a moment...</title><table></table></html>',
                     '<form><input name="password"></form>',
                     submissions(row().replace('class="uoj-username"', 'class="unknown"'))]:
            with self.subTest(html=html), self.assertRaises(SyncError):
                self.read(html)

    def test_recognized_empty_submission_table_is_valid(self):
        rows, _, done = self.read(submissions())
        self.assertEqual(rows, [])
        self.assertTrue(done)

    def test_chinese_and_english_profile_keep_rating(self):
        for title in ['积分', 'Rating']:
            for metadata in ['data-rated="1" data-rating="1800"', '']:
                self.remote.text.return_value = (
                    '<span class="uoj-username" data-nickname="other" data-rating="9999">other</span>'
                    f'<h2><span class="uoj-username" data-nickname="reader" {metadata}>reader</span></h2>'
                    f'<div class="list-group-item"><h4 class="list-group-item-heading">{title}</h4>'
                    '<p class="list-group-item-text">1,800</p></div>')
                self.assertEqual(profile(self.remote, self.binding)['rating'], 1800)

    def test_profile_must_belong_to_bound_user(self):
        for html in ['<table></table>', '<h2><span class="uoj-username" data-nickname="other" data-rating="9999">other</span></h2>']:
            self.remote.text.return_value = html
            with self.assertRaises(SyncError):
                profile(self.remote, self.binding)

    def test_failed_page_does_not_store_or_complete_zero_records(self):
        from .platform_records import run_step
        binding = Mock(platform='qoj', account='reader', sync_state={'phase': 'records', 'page': 1})
        with patch('club.platform_records.PlatformBinding.objects') as manager, \
                patch('club.platform_records.Remote') as remote_class, \
                patch('club.platform_records.attach'), patch('club.platform_records.store') as store:
            manager.filter.return_value.first.return_value = binding
            remote_class.return_value.text.return_value = '<table><tr><td>unknown page</td></tr></table>'
            remote_class.return_value.credentials = {'cookie': '__Host-UOJSESSID=fixture'}
            run_step(1, 'fixture-token')
            store.assert_not_called()
            self.assertEqual(manager.filter.return_value.update.call_args.kwargs['status'], 'failed')
