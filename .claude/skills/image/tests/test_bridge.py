"""Non-browser portability proofs for the test-only Chromium bridge."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

BRIDGE = Path(__file__).resolve().parent / 'bridge' / 'browser-harness'


class Bootstrap(unittest.TestCase):
    def run_program(self, program):
        return subprocess.run([str(BRIDGE)], input=program, text=True,
                              capture_output=True, timeout=10)

    def test_executes_helper_python_without_cloudroom_or_browser(self):
        result = self.run_program("print('bridge bootstrap OK')")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'bridge bootstrap OK\n')

    def test_program_failure_propagates(self):
        result = self.run_program("raise RuntimeError('synthetic failure')")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('synthetic failure', result.stderr)

    def test_missing_node_fails_without_success(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'python3').symlink_to(sys.executable)
            result = subprocess.run(
                [str(BRIDGE)], input='new_tab()', text=True,
                env={**os.environ, 'PATH': temp}, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('node', result.stderr)


if __name__ == '__main__':
    unittest.main()
