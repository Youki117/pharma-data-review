import subprocess
import unittest
from pathlib import Path

class StabilityUiTests(unittest.TestCase):

    def test_repeat_and_error_recovery(self):
        script = Path(__file__).with_name('test_stability_ui.cjs')
        result = subprocess.run(['node', str(script)], capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
if __name__ == '__main__':
    unittest.main()
