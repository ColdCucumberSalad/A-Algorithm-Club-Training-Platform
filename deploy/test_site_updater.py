import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from site_updater import extract, validate_schedule, verify_source, Updater, write
import hashlib
import urllib.error


class UpdateSafetyTests(unittest.TestCase):
    def test_schedule_rejects_invalid_modes_hours_and_extra_commands(self):
        for value in ({'mode': 'auto', 'time': '24:00'}, {'mode': 'shell', 'time': '04:00'}, {'mode': 'auto', 'time': '04:00', 'run': 'id'}):
            with self.assertRaises(ValueError):
                validate_schedule(value)

    def test_archive_cannot_escape_or_overwrite_runtime_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, link in [('repo/../../escape', False), ('repo/.env', False), ('repo/media/avatar', False), ('repo/link', True)]:
                with tarfile.open(root / 'source.tar', 'w') as stream:
                    item = tarfile.TarInfo(name)
                    if link:
                        item.type = tarfile.SYMTYPE; item.linkname = '/etc/passwd'
                    stream.addfile(item)
                with self.assertRaises(ValueError):
                    extract(root / 'source.tar', root / 'out')

    def test_regular_archive_extracts_source_without_root_wrapper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with tarfile.open(root / 'source.tar', 'w') as stream:
                item = tarfile.TarInfo('repo/app.js'); item.size = 5
                stream.addfile(item, io.BytesIO(b'hello'))
            extract(root / 'source.tar', root / 'out')
            self.assertEqual((root / 'out/app.js').read_bytes(), b'hello')

    def test_manual_update_rechecks_target_before_any_build_or_stop(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'check', return_value='b' * 40), patch.object(updater, 'run') as run:
                with self.assertRaises(ValueError):
                    updater.update('a' * 40)
                run.assert_not_called()

    def test_mirror_archive_must_match_official_blob_hashes_with_no_extra_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'app.js').write_bytes(b'hello')
            blob = hashlib.sha1(b'blob 5\0hello').hexdigest()
            commit = {'sha': 'a' * 40, 'tree': {'sha': 'b' * 40}}
            tree = {'tree': [{'path': 'app.js', 'type': 'blob', 'sha': blob}], 'truncated': False}
            with patch('site_updater.github_json', side_effect=[commit, tree]):
                verify_source(root, 'a' * 40)
            (root / 'app.js').write_bytes(b'evil!')
            with patch('site_updater.github_json', side_effect=[commit, tree]), self.assertRaises(ValueError):
                verify_source(root, 'a' * 40)
            (root / 'app.js').write_bytes(b'hello'); (root / 'extra.py').write_bytes(b'extra')
            with patch('site_updater.github_json', side_effect=[commit, tree]), self.assertRaises(ValueError):
                verify_source(root, 'a' * 40)

    def test_notify_checks_but_does_not_install_and_schedule_is_persistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'check') as check, patch.object(updater, 'update') as update:
                updater.process({'id': 'test', 'action': 'check'})
                check.assert_called_once(); update.assert_not_called()
                updater.process({'id': 'setting', 'action': 'schedule', 'data': {'mode': 'notify', 'time': '04:00'}})
                self.assertEqual(json.loads((Path(temporary) / 'schedule.json').read_text())['mode'], 'notify')

    def test_web_switch_refreshes_proxy_before_public_checks_in_both_directions(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            calls = []
            def run(args, **kwargs):
                calls.append(args)
                return 'web\nnginx\ndb' if args[-2:] == ['config', '--services'] else ''
            with patch.object(updater, 'run', side_effect=run), patch.object(updater, 'verify_public', side_effect=lambda: calls.append('public')):
                for direction in ('forward', 'rollback'):
                    calls.clear()
                    updater.start_web()
                    switch = next(i for i, call in enumerate(calls) if isinstance(call, list) and 'up' in call)
                    restart = next(i for i, call in enumerate(calls) if isinstance(call, list) and call[-2:] == ['restart', 'nginx'])
                    self.assertLess(switch, restart, direction)
                    self.assertLess(restart, calls.index('public'), direction)

    def test_external_proxy_deployments_do_not_restart_a_missing_nginx_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'run', return_value='web\nworker\nbeat\ndb') as run:
                updater.refresh_proxy()
                self.assertEqual(run.call_count, 1)

    def test_proxy_restart_failure_prevents_a_successful_public_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'run'), patch.object(updater, 'refresh_proxy', side_effect=RuntimeError('proxy failed')), patch.object(updater, 'verify_public') as public:
                with self.assertRaises(RuntimeError):
                    updater.start_web()
                public.assert_not_called()

    def test_dockerfile_only_changes_always_build_with_the_release_dockerfile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'; source.mkdir()
            (source / 'requirements.txt').write_text('unchanged-dependency\n')
            (source / 'Dockerfile').write_text('FROM python:3.13-slim\nENV NEW_RUNTIME=1\nCMD ["new-startup"]\n')
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'run') as run:
                updater.build_release(source, 'test:new', 'a' * 40)
                args = run.call_args.args[0]
                self.assertEqual(args[args.index('-f') + 1], str(source / 'Dockerfile'))
                self.assertEqual(args[-1], str(source))
                self.assertIn('--pull', args)

    def test_public_check_tolerates_proxy_startup_but_requires_eventual_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test', 'health_url': 'https://example.test/auth.html'})
            from unittest.mock import MagicMock
            response = MagicMock()
            response.__enter__.return_value.status = 200
            with patch('site_updater.urllib.request.urlopen', side_effect=[urllib.error.URLError('starting'), response]) as get, patch('site_updater.time.sleep'):
                updater.verify_public()
                self.assertEqual(get.call_count, 2)
            with patch('site_updater.urllib.request.urlopen', side_effect=urllib.error.URLError('unavailable')), patch('site_updater.time.sleep'):
                with self.assertRaises(RuntimeError):
                    updater.verify_public()


if __name__ == '__main__':
    unittest.main()
