"""Non-browser selection proofs; harness fixtures always fail, never emit screenshots."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_screenshot


class HarnessSelection(unittest.TestCase):
    def capture(self, folder):
        with patch.dict(os.environ, {'PATH': str(folder)}):
            result = test_screenshot.Screenshots().run_capture(
                folder / 'capture', url='http://127.0.0.1:1/synthetic')
            self.assertEqual(os.environ['PATH'], str(folder))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((folder / 'capture' / 'capture.json').exists())
        return result

    def test_installed_harness_is_used_without_node_or_web_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'python3').symlink_to(sys.executable)
            harness = folder / 'browser-harness'
            harness.write_text(
                '#!/usr/bin/env python3\nimport sys\n'
                'sys.stderr.write("synthetic installed harness selected\\n")\n'
                'sys.exit(23)\n')
            harness.chmod(0o755)
            result = self.capture(folder)
            self.assertIn('synthetic installed harness selected', result.stderr)

    def test_absent_harness_uses_bridge_and_fails_closed_without_node(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / 'python3').symlink_to(sys.executable)
            result = self.capture(folder)
            self.assertIn("No such file or directory: 'node'", result.stderr)


if __name__ == '__main__':
    unittest.main()
