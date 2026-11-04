import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from site_updater import extract, validate_schedule, Updater, write


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

    def test_old_columns_can_be_preserved_without_accepting_modified_values(self):
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

    def test_notify_checks_but_does_not_install_and_schedule_is_persistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            updater = Updater({'project': temporary, 'control': temporary, 'compose_project': 'test'})
            with patch.object(updater, 'check') as check, patch.object(updater, 'update') as update:
                updater.process({'id': 'test', 'action': 'check'})
                check.assert_called_once(); update.assert_not_called()
                updater.process({'id': 'setting', 'action': 'schedule', 'data': {'mode': 'notify', 'time': '04:00'}})
                self.assertEqual(json.loads((Path(temporary) / 'schedule.json').read_text())['mode'], 'notify')


if __name__ == '__main__':
    unittest.main()
