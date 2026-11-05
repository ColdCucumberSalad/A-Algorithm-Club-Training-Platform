import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from site_updater import extract, validate_schedule, verify_source, Updater, write, source_urls, apt_urls, apt_mirror_proxy
import hashlib
import urllib.error
from contextlib import contextmanager, ExitStack
from unittest.mock import MagicMock


class UpdateSafetyTests(unittest.TestCase):
    def test_mirrors_precede_official_source_fallbacks(self):
        urls = source_urls('a' * 40)
        self.assertTrue(urls[0].startswith('https://gh-proxy.com/'))
        self.assertTrue(urls[1].startswith('https://ghfast.top/'))
        self.assertTrue(urls[2].startswith('https://codeload.github.com/'))
        self.assertTrue(all('a' * 40 in url for url in urls))

    def test_build_proxy_restricts_hosts_and_falls_back_without_partial_responses(self):
        from urllib.request import build_opener, ProxyHandler
        original = 'http://deb.debian.org/debian/dists/trixie/InRelease'
        self.assertEqual(apt_urls(original)[-1], original)
        for url in ('http://127.0.0.1/private', 'http://deb.debian.org.evil/debian/test',
                    'http://deb.debian.org:8000/debian/test', 'http://deb.debian.org/private'):
            with self.assertRaises(ValueError):
                apt_urls(url)
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = b'signed-metadata'
        with apt_mirror_proxy() as proxy:
            opener = build_opener(ProxyHandler({'http': proxy}))
            with patch('site_updater.urllib.request.urlopen', side_effect=[urllib.error.URLError('mirror down'), response]) as upstream:
                with opener.open(original, timeout=5) as result:
                    self.assertEqual(result.read(), b'signed-metadata')
                self.assertEqual(upstream.call_args_list[0].args[0], apt_urls(original)[0])
                self.assertEqual(upstream.call_args_list[1].args[0], apt_urls(original)[1])

    @contextmanager
    def recovery_fixture(self, failure, stop_fails=False):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as patches:
            root = Path(temporary).resolve()
            for kind in ('media', 'static'):
                (root / 'data' / kind).mkdir(parents=True)
                (root / 'data' / kind / 'preserved.txt').write_text('original')
            (root / '.env').write_text('test-only')
            (root / 'compose.yaml').write_text('image: test:old\n' * 3)
            updater = Updater({'project': str(root), 'control': str(root / 'control'), 'compose_project': 'test', 'network': 'test'})
            updater.state['current'] = 'b' * 40
            events, starts = [], []
            guards = [(MagicMock(), 'initial-guard'), (MagicMock(), 'rollback-guard')]
            def run(args, **kwargs):
                if args[-2:] == ['-aq', 'web']:
                    return 'test-web'
                if args[:2] == ['docker', 'inspect']:
                    return json.dumps([{'Destination': '/app/media', 'Source': str(root / 'data/media')}, {'Destination': '/app/staticfiles', 'Source': str(root / 'data/static')}])
                if args[-4:] == ['stop', 'beat', 'worker', 'web']:
                    events.append('stop')
                    if stop_fails and updater.state.get('recovery_required'):
                        raise RuntimeError('stop failed')
                if args[-4:] == ['kill', 'beat', 'worker', 'web']:
                    events.append('kill')
                    raise RuntimeError('kill failed')
                if args[-2:] == ['worker', 'beat'] and 'up' in args:
                    events.append('restart-workers')
                    if failure == 'workers':
                        raise RuntimeError('worker restart failed')
                return ''
            def start():
                starts.append(True); events.append('start-web')
                if len(starts) == 1:
                    raise RuntimeError('forward validation failed')
                if failure == 'web':
                    raise RuntimeError('rollback validation failed')
            def extract_archive(archive, source):
                source.mkdir(); (source / 'Dockerfile').write_text('test')
            response = MagicMock()
            response.__enter__.return_value.read1.side_effect = [b'archive', b'']
            patches.enter_context(patch.object(updater, 'run', side_effect=run))
            patches.enter_context(patch.object(updater, 'check', return_value='a' * 40))
            patches.enter_context(patch.object(updater, 'image', return_value='test:old'))
            def acquire_guard(image):
                events.append('acquire-guard')
                return guards[0] if events.count('acquire-guard') == 1 else guards[1]
            patches.enter_context(patch.object(updater, 'guard', side_effect=acquire_guard))
            patches.enter_context(patch.object(updater, 'build_release'))
            patches.enter_context(patch.object(updater, 'rehearsal'))
            patches.enter_context(patch.object(updater, 'audit'))
            patches.enter_context(patch.object(updater, 'dump', side_effect=lambda path: path.write_bytes(b'database')))
            patches.enter_context(patch.object(updater, 'start_web', side_effect=start))
            patches.enter_context(patch('site_updater.urllib.request.urlopen', return_value=response))
            patches.enter_context(patch('site_updater.extract', side_effect=extract_archive))
            patches.enter_context(patch('site_updater.verify_source'))
            patches.enter_context(patch('site_updater.subprocess.run', side_effect=lambda *args, **kwargs: events.append('release-guard')))
            yield updater, events, guards[1]

    def test_failed_rollback_web_or_workers_stops_apps_before_guard_release(self):
        for failure in ('web', 'workers'):
            with self.subTest(failure=failure), self.recovery_fixture(failure) as (updater, events, guard):
                with self.assertRaisesRegex(RuntimeError, '应用服务已停止'):
                    updater.update('a' * 40)
                self.assertEqual(events[-2:], ['stop', 'release-guard'])
                self.assertTrue(updater.state['recovery_required'])
                guard[0].stdin.close.assert_called_once()
                self.assertEqual(events.count('acquire-guard'), 2)
                self.assertEqual(events.count('release-guard'), 2)

    def test_failed_stop_retains_guard_and_requires_manual_recovery(self):
        with self.recovery_fixture('web', stop_fails=True) as (updater, events, guard):
            with self.assertRaisesRegex(RuntimeError, 'kill failed'):
                updater.update('a' * 40)
            self.assertEqual(events[-2:], ['stop', 'kill'])
            self.assertEqual(events.count('release-guard'), 1, 'only the terminated database session is released')
            self.assertEqual(updater.retained_guard, guard)
            self.assertTrue(updater.state['recovery_required'])
            guard[0].stdin.close.assert_not_called()

    def test_interrupted_manual_update_is_quarantined_even_if_image_is_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            updater.status(state='running', action='update', operation='interrupted', current='a' * 40)
            request = updater.control / 'request-interrupted.json'
            write(request, {'id': 'interrupted', 'action': 'update', 'data': {'revision': 'a' * 40}})
            restarted = Updater(updater.config)
            restarted.quarantine_interrupted()
            self.assertFalse(list(restarted.control.glob('request-*.json')))
            self.assertTrue(request.with_suffix('.interrupted').exists())
            self.assertTrue(restarted.state['recovery_required'])
            with patch.object(restarted, 'check') as check:
                with self.assertRaisesRegex(RuntimeError, '人工恢复'):
                    restarted.process({'id': 'retry', 'action': 'update', 'data': {'revision': 'a' * 40}})
                check.assert_not_called()
            self.assertNotEqual(restarted.state['state'], 'succeeded')

    def test_recovery_flag_survives_restart_and_harmless_settings_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            updater.status(state='failed', recovery_required=True)
            updater.process({'id': 'settings', 'action': 'schedule', 'data': {'mode': 'auto', 'time': '04:00'}})
            restarted = Updater(updater.config)
            request = restarted.control / 'request-pending.json'
            write(request, {'id': 'pending', 'action': 'update', 'data': {'revision': 'a' * 40}})
            restarted.quarantine_interrupted()
            self.assertTrue(restarted.state['recovery_required'])
            self.assertFalse(request.exists())

    def test_legacy_failed_state_with_remaining_update_cannot_replay(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            updater.status(state='failed', operation='legacy')
            request = updater.control / 'request-legacy.json'
            write(request, {'id': 'legacy', 'action': 'update', 'data': {'revision': 'a' * 40}})
            updater.quarantine_interrupted()
            self.assertFalse(request.exists())
            self.assertTrue(updater.state['recovery_required'])

    def test_interrupted_check_is_not_replayed_and_does_not_block_new_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            updater.status(state='running', action='check', operation='check')
            request = updater.control / 'request-check.json'
            write(request, {'id': 'check', 'action': 'check'})
            updater.quarantine_interrupted()
            self.assertFalse(request.exists())
            self.assertFalse(updater.state['recovery_required'])
            with patch.object(updater, 'check') as check:
                updater.process({'id': 'new-check', 'action': 'check'})
                check.assert_called_once()

    def test_daemon_restart_quarantines_before_queue_or_daily_update_processing(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            updater.status(state='running', action='update', operation='interrupted')
            write(updater.control / 'request-interrupted.json', {'id': 'interrupted', 'action': 'update', 'data': {'revision': 'a' * 40}})
            import sys
            with patch.dict(sys.modules, {'fcntl': MagicMock()}), patch('site_updater.threading.Thread'), patch('site_updater.time.sleep', side_effect=SystemExit), patch.object(updater, 'process') as process, patch.object(updater, 'check') as check, patch.object(updater, 'update') as update:
                with self.assertRaises(SystemExit):
                    updater.serve()
                process.assert_not_called(); check.assert_not_called(); update.assert_not_called()
            self.assertTrue(updater.state['recovery_required'])

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
