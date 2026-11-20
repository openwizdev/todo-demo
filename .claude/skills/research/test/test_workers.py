#!/usr/bin/env python3
"""TV12: moved public worker guard proof, all GitHub responses synthetic.

Catches worker writes, broad/stale allowances and incomplete reads reported as
clean. The recording gh accepts paginated GETs only; no credential or network.
"""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check-workers.sh'
CLEAN = b'clean research: no unexplained changes in checked GitHub surfaces\n'
FAKE_GH = '''#!/bin/sh
printf '%s\\n' "$*" >> "$RESEARCH_FIXTURE/reads"
[ "$#" = 6 ] && [ "$1 $2 $3 $4 $5" = 'api --method GET --paginate --slurp' ] || exit 90
case "$6" in
  'repos/example/widgets/branches?per_page=100') cat "$RESEARCH_FIXTURE/branches" ;;
  'repos/example/widgets/pulls?state=all&per_page=100') cat "$RESEARCH_FIXTURE/pulls" ;;
  'repos/example/widgets/issues/comments?per_page=100') cat "$RESEARCH_FIXTURE/comments" ;;
  'repos/example/widgets/pulls/comments?per_page=100') cat "$RESEARCH_FIXTURE/review-comments" ;;
  *) exit 91 ;;
esac
'''


class WorkerTest(unittest.TestCase):
    def test_worker_github_check(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / 'tools'
            tools.mkdir()
            for name in ('sh', 'jq', 'mktemp', 'rm', 'cat'):
                program = shutil.which(name)
                self.assertIsNotNone(program, name)
                (tools / name).symlink_to(program)
            (tools / 'gh').write_text(FAKE_GH)
            (tools / 'gh').chmod(0o700)
            branch = {'name': 'main', 'commit': {'sha': 'a' * 40}}
            pull = {'number': 17, 'state': 'open', 'merged_at': None,
                    'title': 'Synthetic report', 'body': 'Synthetic evidence', 'draft': False,
                    'head': {'ref': 'research/widgets', 'sha': 'b' * 40,
                             'repo': {'full_name': 'example/widgets'}},
                    'base': {'ref': 'main', 'repo': {'full_name': 'example/widgets'}}}
            comment = {'id': 23, 'body': 'Synthetic note', 'updated_at': '2026-01-01T00:00:00Z'}

            def write(name, value):
                (root / name).write_text(json.dumps(value))

            def reset():
                for name, value in [('branches', [[branch], []]), ('pulls', [[pull]]),
                                    ('comments', [[comment]]), ('review-comments', [[]])]:
                    write(name, value)

            def run(*args):
                return subprocess.run([str(tools / 'sh'), str(SCRIPT), *map(str, args)],
                                      env={'PATH': str(tools), 'GH_REPO': 'example/widgets',
                                           'RESEARCH_FIXTURE': str(root)}, capture_output=True)

            reset()
            before = run('snapshot')
            self.assertEqual(before.returncode, 0, before.stderr)
            snapshot = root / 'before.json'
            snapshot.write_bytes(before.stdout)
            clean = run('check', snapshot)
            self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, CLEAN, b''))
            reads = (root / 'reads').read_text().splitlines()
            self.assertEqual(len(reads), 8)
            for endpoint in ('branches?per_page=100', 'pulls?state=all&per_page=100',
                             'issues/comments?per_page=100', 'pulls/comments?per_page=100'):
                self.assertEqual(sum(line.endswith(endpoint) for line in reads), 2)
            new = {'name': 'room/research-worker', 'commit': {'sha': 'd' * 40}}
            moved = {'name': 'main', 'commit': {'sha': 'c' * 40}}
            cases = [('branches', [[branch], [new]], 'branch room/research-worker'),
                     ('branches', [[moved]], 'branch main'),
                     ('branches', [[]], 'branch main'),
                     ('pulls', [[]], 'pull request #17'),
                     ('comments', [[]], 'comment 23'),
                     ('review-comments', [[comment]], 'review comment 23')]
            for field, value in [('state', 'closed'), ('merged_at', '2026-01-01T00:00:00Z'),
                                 ('title', 'Unexpected edit'), ('body', 'Unexpected body'), ('draft', True)]:
                changed = copy.deepcopy(pull)
                changed[field] = value
                cases.append(('pulls', [[changed]], 'pull request #17'))
            extra = copy.deepcopy(pull)
            extra['number'] = 18
            cases.append(('pulls', [[pull], [extra]], 'pull request #18'))
            for side, field, value in [('head', 'sha', 'f' * 40), ('head', 'ref', 'research/other'),
                                       ('base', 'ref', 'release-example')]:
                changed = copy.deepcopy(pull)
                changed[side][field] = value
                cases.append(('pulls', [[changed]], 'pull request #17'))
            edited = dict(comment, body='Unexpected edit')
            cases.append(('comments', [[edited]], 'comment 23'))
            for file, value, finding in cases:
                with self.subTest(file=file, finding=finding, value=value):
                    reset()
                    write(file, value)
                    result = run('check', snapshot)
                    self.assertEqual((result.returncode, result.stdout, result.stderr),
                                     (1, f'hit research: {finding}\n'.encode(), b''))
            reset()
            write('branches', [[branch, new]])
            allow = root / 'allow.json'
            write('allow.json', {'branch room/research-worker': 'd' * 40})
            self.assertEqual(run('check', snapshot, '--allow', allow).returncode, 0)
            write('allow.json', {'branch room/research-worker': 'e' * 40})
            result = run('check', snapshot, '--allow', allow)
            self.assertEqual((result.returncode, result.stdout), (2, b''))
            for file, key in [('branches', 'branch main'), ('pulls', 'pull request #17'),
                              ('comments', 'comment 23')]:
                with self.subTest(deletion=key):
                    reset()
                    write(file, [[]])
                    write('allow.json', {key: None})
                    result = run('check', snapshot, '--allow', allow)
                    self.assertEqual((result.returncode, result.stdout), (0, CLEAN))
            reset()
            edited = dict(pull, title='Unexpected edit')
            write('pulls', [[edited]])
            write('allow.json', {'pull request #17': None})
            result = run('check', snapshot, '--allow', allow)
            self.assertEqual((result.returncode, result.stdout), (2, b''))
            reset()
            write('allow.json', {'branch main': 'a' * 40})
            result = run('check', snapshot, '--allow', allow)
            self.assertEqual((result.returncode, result.stdout, result.stderr),
                             (2, b'', b'check-workers.sh: allowance does not match observed changes\n'))
            saved = json.loads(snapshot.read_text())
            unknown = copy.deepcopy(saved)
            unknown['items']['tag v1'] = 'a' * 40
            not_sha = copy.deepcopy(saved)
            not_sha['items']['branch main'] = 'main'
            version = dict(saved, version=2)
            for value in (unknown, not_sha, version):
                reset()
                write('invalid.json', value)
                result = run('check', root / 'invalid.json')
                self.assertEqual((result.returncode, result.stdout, result.stderr),
                                 (2, b'', b'check-workers.sh: invalid snapshot\n'))
            for file in ('branches', 'pulls', 'comments', 'review-comments'):
                for bad in ('', '{}', '[]', '[[], {}]', '[[{}]]', '[[{}]', '[[], []'):
                    with self.subTest(file=file, invalid=bad):
                        reset()
                        (root / file).write_text(bad)
                        result = run('check', snapshot)
                        self.assertEqual((result.returncode, result.stdout), (2, b''))
                        self.assertTrue(result.stderr)
                reset()
                (root / file).unlink()
                result = run('check', snapshot)
                self.assertEqual((result.returncode, result.stdout), (2, b''))
            reset()
            write('branches', [[branch], [branch]])
            self.assertEqual(run('snapshot').returncode, 2)
            for bad in ('{}', 'null', '[]', '{"version":1}'):
                (root / 'bad.json').write_text(bad)
                self.assertEqual(run('check', root / 'bad.json').returncode, 2)


if __name__ == '__main__':
    unittest.main()
