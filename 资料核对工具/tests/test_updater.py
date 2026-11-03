import hashlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import updater

def release(version='9.1.0', product='suite', raw=b'zip'):
    name = f'review-{product}-v{version}.zip'
    return {'tag_name': 'v' + version, 'draft': False, 'prerelease': False, 'body': '版本说明', 'assets': [{'name': name, 'size': len(raw), 'digest': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'browser_download_url': f'https://github.com/{updater.REPOSITORY}/releases/download/v{version}/{name}'}]}

def package(product='suite', extra=None):
    stream = io.BytesIO()
    name = updater.PRODUCTS[product]
    with zipfile.ZipFile(stream, 'w') as archive:
        archive.writestr(name + '/' + name + '.exe', b'test-placeholder')
        archive.writestr(name + '/_internal/python312.dll', b'test-placeholder')
        if extra:
            item = zipfile.ZipInfo()
            item.filename = extra
            archive.writestr(item, b'invalid')
    return stream.getvalue()

class UpdateTests(unittest.TestCase):

    def test_version_comparison_and_all_product_assets(self):
        self.assertGreater(updater.version_tuple('v1.10.0'), updater.version_tuple('1.9.9'))
        for product in updater.PRODUCTS:
            self.assertEqual(updater.release_info(release(product=product), product)['version'], '9.1.0')
        self.assertIsNone(updater.release_info(release('1.0.0'), 'suite'))
        for invalid in ('main', '../../tmp', '1.2.3-beta', '1.2', None):
            with self.assertRaises(ValueError):
                updater.version_tuple(invalid)

    def test_reject_draft_prerelease_wrong_asset_origin_and_digest(self):
        for field, value in [('draft', True), ('prerelease', True)]:
            data = release()
            data[field] = value
            with self.assertRaises(ValueError):
                updater.release_info(data, 'suite')
        for field, value in [('browser_download_url', 'https://example.com/update.zip'), ('size', -1), ('digest', None), ('name', 'wrong.zip')]:
            data = release()
            data['assets'][0][field] = value
            with self.assertRaises(ValueError):
                updater.release_info(data, 'suite')

    def test_download_checks_size_digest_and_cancellation(self):
        raw = package()
        info = updater.release_info(release(raw=raw), 'suite')
        opener = Mock()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'update.zip'
            for data, cancelled, valid in [(raw, False, True), (raw[:-1], False, False), (b'x' * len(raw), False, False), (raw, True, False)]:
                event = threading.Event()
                if cancelled:
                    event.set()
                opener.open.return_value = io.BytesIO(data)
                with patch('updater.urllib.request.build_opener', return_value=opener):
                    if valid:
                        updater.download(info, path, lambda _: None, event)
                        self.assertEqual(path.read_bytes(), raw)
                    else:
                        with self.assertRaises(ValueError):
                            updater.download(info, path, lambda _: None, event)

    def test_extract_rejects_traversal_links_and_incomplete_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / 'download.zip'
            source.write_bytes(package())
            updater.extract_package(source, base / 'valid', 'suite')
            self.assertTrue((base / 'valid/资料核对工具/资料核对工具.exe').exists())
            for extra in ('../escaped.exe', '/escaped.exe', '资料核对工具/../escaped.exe', '资料核对工具/C:escaped.exe', '资料核对工具/\\escaped.exe'):
                source.write_bytes(package(extra=extra))
                with self.assertRaises(ValueError):
                    updater.extract_package(source, base / 'invalid', 'suite')
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('资料核对工具/readme.txt', b'no executable')
            with self.assertRaises(ValueError):
                updater.extract_package(source, base / 'invalid', 'suite')
            self.assertFalse((base / 'escaped.exe').exists())

    def test_offline_check_is_explicit_and_does_not_block(self):
        update = updater.Updater('suite')
        with patch('updater.urllib.request.urlopen', side_effect=OSError('offline')):
            update._check()
        self.assertEqual(update.status()['stage'], 'error')
        self.assertIn('可继续使用', update.status()['message'])

    def test_no_update_and_new_release(self):
        update = updater.Updater('suite')
        for version, stage in [('1.0.0', 'latest'), ('9.1.0', 'available')]:
            with patch('updater.urllib.request.urlopen', return_value=io.BytesIO(json.dumps(release(version)).encode())):
                update._check()
            self.assertEqual(update.status()['stage'], stage)

    def test_install_requires_packaged_program_idle_and_available_release(self):
        update = updater.Updater('suite', lambda: True)
        update._release = updater.release_info(release(), 'suite')
        update._state.update(stage='available')
        self.assertFalse(update.install()['ok'])
        update._state['installable'] = True
        self.assertFalse(update.install()['ok'])
        update.busy = lambda: False
        with patch('updater.threading.Thread') as thread:
            self.assertTrue(update.install()['ok'])
            self.assertEqual(update.status()['stage'], 'installing')
            self.assertEqual(thread.call_count, 1)
            self.assertFalse(update.install()['ok'])

    def test_handoff_waits_for_helper_before_closing_original_window(self):
        self.install_case(fail=False)

    def test_helper_launch_failure_leaves_window_and_original_files(self):
        self.install_case(fail=True)

    def install_case(self, fail):
        raw = package()
        info = updater.release_info(release(raw=raw), 'suite')
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / 'state'
            target = Path(temporary) / '原程序'
            target.mkdir()
            original = target / '资料核对工具.exe'
            original.write_bytes(b'original')
            update = updater.Updater('suite')
            update._window = Mock()

            def fetch(info, path, progress, cancelled):
                path.write_bytes(raw)

            def launch(args, **kwargs):
                self.assertEqual(args[1], '--apply-update')
                plan = Path(args[2])
                self.assertEqual(json.loads(plan.read_text(encoding='utf-8'))['target'], str(target.resolve()))
                self.assertFalse((home / 'versions').exists())
                update._window.destroy.assert_not_called()
                if fail:
                    raise OSError('launch failed')
                (plan.parent / 'helper-ready').write_text('123', encoding='ascii')
                return Mock(pid=123, poll=lambda: None)
            with patch('updater.update_home', return_value=home), patch('updater.sys.executable', str(original)), patch('updater.download', side_effect=fetch), patch('updater.subprocess.Popen', side_effect=launch):
                update._install(info)
            self.assertEqual(original.read_bytes(), b'original')
            if fail:
                self.assertEqual(update.status()['stage'], 'available')
                self.assertFalse(list(home.glob('pending-*')))
                update._window.destroy.assert_not_called()
            else:
                self.assertEqual(len(list(home.glob('pending-*/plan.json'))), 1)
                update._window.destroy.assert_called_once()

    def test_original_entry_uses_installed_newer_version_and_source_never_redirects(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            (home / 'active.json').write_text('{"version":"9.1.0"}', encoding='utf-8')
            target = updater.executable(home, 'suite', '9.1.0')
            target.parent.mkdir(parents=True)
            target.write_bytes(b'placeholder')
            with patch('updater.update_home', return_value=home), patch('updater.subprocess.Popen') as launch:
                self.assertFalse(updater.launch_installed('suite'))
                with patch.object(sys, 'frozen', True, create=True):
                    self.assertTrue(updater.launch_installed('suite'))
                launch.assert_called_once_with([str(target)], cwd=target.parent)
if __name__ == '__main__':
    unittest.main()
