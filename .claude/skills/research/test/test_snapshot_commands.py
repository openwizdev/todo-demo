#!/usr/bin/env python3
"""TV12: run the documented commands in fresh shells with awkward paths.

Catches lost snapshot paths and unquoted spaces/apostrophes at the shell boundary.
The fake checker records arguments only; it does not supply the quoting tested.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

SKILL = Path(__file__).resolve().parents[1] / 'SKILL.md'


class SnapshotTest(unittest.TestCase):
    def test_snapshot_path_survives_fresh_shells(self):
        skill = SKILL.read_text()
        dispatch = skill.split('## 2. Dispatch fresh workers\n', 1)[1].split('## Worker:', 1)[0]
        blocks = re.findall(r'```sh\n(.*?)\n```', dispatch, re.S)
        self.assertTrue(blocks)
        for block in blocks:
            assigned = set(re.findall(r'^\s*([a-zA-Z0-9_]+)=', block, re.M))
            for name in re.findall(r'\$\{?([a-zA-Z0-9_]+)', block):
                self.assertIn(name, assigned, f'cross-shell variable ${name}: {block}')
        commands = [line for block in blocks for line in block.splitlines()]
        checker = 'sh "<research-skill-folder>/scripts/check-workers.sh" '

        def command(verb):
            matches = [line for line in commands if line.startswith(checker + verb + ' ')]
            self.assertEqual(len(matches), 1, f'{verb}: {matches}')
            return matches[0]

        snapshot_command = command('snapshot')
        check_command = command('check')
        reruns = re.findall(r'`(check .*?--allow .*?)`', dispatch)
        self.assertEqual(len(reruns), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            folder = root / 'skill folder'
            script = folder / 'scripts/check-workers.sh'
            script.parent.mkdir(parents=True)
            script.write_text('for arg in "$@"; do printf \'arg:%s\\n\' "$arg"; done\n')
            snapshot = root / "tmp dir/it's a snapshot"
            snapshot.parent.mkdir()
            allow = root / 'tmp dir/exact changes.json'

            def shell(text):
                filled = text.replace('<research-skill-folder>', str(folder))
                for placeholder, path in [('<snapshot-path>', snapshot), ('<exact-changes.json>', allow)]:
                    filled = filled.replace(placeholder, str(path).replace("'", "'\\''"))
                result = subprocess.run(['sh', '-c', filled], cwd=root, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout.decode()

            self.assertEqual(shell(snapshot_command), '')
            self.assertEqual(snapshot.read_text(), 'arg:snapshot\n')
            self.assertEqual(shell(check_command), f'arg:check\narg:{snapshot}\n')
            self.assertEqual(shell(checker + reruns[0]),
                             f'arg:check\narg:{snapshot}\narg:--allow\narg:{allow}\n')


if __name__ == '__main__':
    unittest.main()
