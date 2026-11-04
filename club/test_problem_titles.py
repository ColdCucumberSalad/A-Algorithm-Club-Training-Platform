from unittest.mock import patch

from django.test import SimpleTestCase

from .problem_parser import ai_title, auto_title, canonical_problem, valid_title


QOJ_URL = 'https://qoj.ac/problem/23602'


class ProblemTitleTests(SimpleTestCase):
    def read(self, html, url=QOJ_URL):
        with patch('club.problem_parser.http_fetch', return_value=html):
            return auto_title(url)

    def test_qoj_site_headers_are_skipped(self):
        # Relevant markup from QOJ problem 23602, read through its mirror.
        html = ('<title>Keep Your Distance - Problem - QOJ.ac</title>'
                '<h1 class="d-none d-sm-block">QOJ.ac</h1>'
                '<h1 class="d-block d-sm-none">QOJ</h1>'
                '<h1 class="page-header text-center">#23602. Keep Your Distance\t</h1>')
        for url in [QOJ_URL, 'https://qoj.ac/contest/123/problem/23602']:
            with self.subTest(url=url):
                self.assertEqual(self.read(html, url), 'Keep Your Distance')

    def test_qoj_document_title_fallback(self):
        for suffix in [' - Problem - QOJ.ac', ' - QOJ.ac', ' - QOJ']:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.read(
                    f'<title>Keep Your Distance{suffix}</title><h1>QOJ.ac</h1>'),
                    'Keep Your Distance')

    def test_qoj_heading_preserves_nested_text_and_punctuation(self):
        self.assertEqual(self.read('<h1>QOJ</h1><h1 class="page-header">'
                                   '#42. A &amp; B - <em>Problem</em></h1>'),
                         'A & B - Problem')

    def test_qoj_site_names_are_not_titles_in_auto_or_ai_mode(self):
        for name in ['QOJ', 'QOJ.ac', 'qoj.AC']:
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    valid_title(name)
                with self.assertRaises(ValueError):
                    self.read(f'<title>{name}</title><h1>{name}</h1>')
                with patch('club.problem_parser.ai_json', return_value={'title': name}), \
                        self.assertRaises(ValueError):
                    ai_title(QOJ_URL)

    def test_qoj_challenge_heading_is_not_a_title(self):
        with self.assertRaises(ValueError):
            self.read('<title>Just a moment...</title><div class="h2">'
                      'Enable JavaScript and cookies to continue</div>')

    def test_other_platform_titles_still_work(self):
        samples = [
            ('<title>P1001 A+B Problem - 洛谷</title>', 'P1001 A+B Problem'),
            ('<title>Problem - 123A - Codeforces</title>'
             '<div class="title">A. Prime Permutation</div>', 'A. Prime Permutation'),
            ('<title>AtCoder</title><span class="h2">A - Water</span>', 'A - Water'),
        ]
        for html, expected in samples:
            with self.subTest(html=html):
                self.assertEqual(self.read(html, 'https://example.com/problem/42'), expected)

    def test_qoj_contest_and_direct_links_keep_same_identity(self):
        self.assertEqual(canonical_problem(QOJ_URL)[0],
                         canonical_problem('https://qoj.ac/contest/123/problem/23602')[0])
