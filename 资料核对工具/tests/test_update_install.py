import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import update_install

class FixedUpdateTests(unittest.TestCase):

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.target, self.source = (self.root / '程序', self.root / '新版')
        self.exe = '资料核对工具.exe'
        for directory, value in [(self.target, b'old'), (self.source, b'new')]:
            (directory / '_internal').mkdir(parents=True)
            (directory / self.exe).write_bytes(value)
            (directory / '_internal/python312.dll').write_bytes(value)
        (self.target / '用户报告.html').write_text('报告不动', encoding='utf-8')
        self.data = self.root / '独立数据/结果.json'
        self.data.parent.mkdir()
        self.data.write_text('保留结果', encoding='utf-8')

    def apply(self):
        return update_install.apply_package(self.source, self.target, 'suite', '9.1.0')

    def test_replaces_same_executable_and_preserves_user_files_and_one_backup(self):
        with patch('update_install.start_and_wait'), patch('update_install.update_home', return_value=self.root / 'state'):
            self.apply()
            self.assertEqual((self.target / self.exe).read_bytes(), b'new')
            self.assertEqual((self.target / '.review-backup' / self.exe).read_bytes(), b'old')
            (self.source / self.exe).write_bytes(b'newer')
            self.apply()
        self.assertEqual((self.target / self.exe).read_bytes(), b'newer')
        self.assertEqual((self.target / '.review-backup' / self.exe).read_bytes(), b'new')
        self.assertEqual((self.target / '用户报告.html').read_text(encoding='utf-8'), '报告不动')
        self.assertEqual(self.data.read_text(encoding='utf-8'), '保留结果')
        self.assertFalse((self.root / 'state/versions').exists())

    def test_failed_new_launch_restores_executable_and_runtime(self):
        with patch('update_install.start_and_wait', side_effect=ValueError('新版未启动')), patch('update_install.subprocess.Popen') as restart:
            with self.assertRaisesRegex(ValueError, '已恢复'):
                self.apply()
        self.assertEqual((self.target / self.exe).read_bytes(), b'old')
        self.assertEqual((self.target / '_internal/python312.dll').read_bytes(), b'old')
        self.assertEqual(self.data.read_text(encoding='utf-8'), '保留结果')
        restart.assert_called_once()

    def test_unowned_backup_and_added_backup_files_are_never_removed(self):
        backup = self.target / '.review-backup'
        backup.mkdir()
        note = backup / '用户资料.docx'
        note.write_bytes(b'private')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(note.read_bytes(), b'private')
        self.assertEqual((self.target / self.exe).read_bytes(), b'old')
        (backup / '.backup.json').write_text(json.dumps({'product': 'suite', 'target': str(self.target.resolve())}), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.apply()
        self.assertEqual(note.read_bytes(), b'private')

    def test_wrong_startup_ack_stops_new_process_before_rollback(self):
        state = self.root / 'state'
        state.mkdir()
        process = unittest.mock.Mock(pid=123, poll=lambda: None)

        def launch(args, **kwargs):
            (state / ('ready-' + args[-1])).write_text('{"version":"1.0.0","pid":123}', encoding='utf-8')
            return process
        with patch('update_install.update_home', return_value=state), patch('update_install.subprocess.Popen', side_effect=launch):
            with self.assertRaisesRegex(ValueError, '确认不符'):
                update_install.start_and_wait(self.target / self.exe, 'suite', '9.1.0')
        process.terminate.assert_called_once()
        process.wait.assert_called_once()
        self.assertFalse(list(state.glob('ready-*')))

    def test_partial_copy_failure_restores_previous_runtime(self):
        real_copy = update_install.copy_item
        failed = False

        def copy(source, target):
            nonlocal failed
            if source == self.source / '_internal' and (not failed):
                failed = True
                raise OSError('模拟写入失败')
            return real_copy(source, target)
        with patch('update_install.copy_item', side_effect=copy), patch('update_install.subprocess.Popen'):
            with self.assertRaisesRegex(ValueError, '已恢复'):
                self.apply()
        self.assertEqual((self.target / self.exe).read_bytes(), b'old')
        self.assertEqual((self.target / '_internal/python312.dll').read_bytes(), b'old')

    def test_backup_copy_failure_leaves_original_intact_and_reopens_it(self):
        with patch('update_install.copy_item', side_effect=OSError('备份空间不足')), patch('update_install.subprocess.Popen') as restart:
            with self.assertRaisesRegex(ValueError, '已恢复'):
                self.apply()
        self.assertEqual((self.target / self.exe).read_bytes(), b'old')
        self.assertEqual((self.target / '_internal/python312.dll').read_bytes(), b'old')
        restart.assert_called_once()
if __name__ == '__main__':
    unittest.main()
