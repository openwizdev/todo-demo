"""handoff.py's command seam, with a synthetic, recording gh only (#1186)."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'handoff.py'
REPO = 'example-org/example-private'
PAGE_PATH = 'private/orchestration/HANDOFF.md'
FAKE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
answers = json.loads(Path(os.environ['ANSWERS']).read_text())
if args[:3] != ['api', '--method', 'GET'] or len(args) != 4 or args[3] not in answers:
    sys.exit(91)
answer = answers[args[3]]
if answer == 'FAIL':
    print('synthetic private diagnostic', file=sys.stderr)
    sys.exit(1)
print(answer if isinstance(answer, str) else json.dumps(answer))
'''
# Synthetic page: invented fleets, tickets and decisions, no live values.
GOOD = '''# Orchestrator handoff

**Snapshot: 2026-01-02 03:04 UTC, plan graph approved on #10.** Rules in AGENTS.md; status in STATUS.md. A new orchestrator reads this first and checks each line before acting on it.

## Open fleets

| Fleet | Version | Graph approved | Merged | Can start or building | Waiting on blockers | Needs a look |
| --- | --- | --- | --- | --- | --- | --- |
| #10 Example spec | 0.1.0 | 2026-01-02, private record 101 | 1 | 2 | 1 | none |

## Running agents

| Fleet | Builders | Reviewers | Full list | Needs a look |
| --- | --- | --- | --- | --- |
| #10 | 2 (unverified) | 0 | #10 | none |

## Decisions waiting on the user

None.

## Loops

None.

## Standing approvals

None.
'''


def repo(private=True, branch='main'):
    return {'full_name': REPO, 'private': private, 'default_branch': branch,
            'description': 'PRIVATE_DESCRIPTION_SENTINEL'}


def contents(text, sha='a' * 40):
    return {'path': PAGE_PATH, 'sha': sha,
            'content': base64.b64encode(text.encode()).decode(), 'encoding': 'base64'}


class Handoff(unittest.TestCase):
    def run_helper(self, *args, answers=None, files=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'gh').write_text(FAKE)
            (root / 'gh').chmod(0o755)
            (root / 'answers.json').write_text(json.dumps(answers or {}))
            for name, text in (files or {}).items():
                (root / name).write_text(text)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       ANSWERS=str(root / 'answers.json'), CALLS=str(root / 'calls'))
            result = subprocess.run([sys.executable, '-I', str(SCRIPT), *args], cwd=root,
                                    env=env, capture_output=True, text=True)
            calls = ([json.loads(line) for line in (root / 'calls').read_text().splitlines()]
                     if (root / 'calls').exists() else [])
            return result, calls

    # ---- private: the write target must be a verified private repository ----

    def test_private_target_is_confirmed_by_one_get(self):
        result, calls = self.run_helper('private', REPO, answers={f'repos/{REPO}': repo()})
        self.assertEqual((result.returncode, result.stdout), (0, f'private ok: {REPO}\n'))
        self.assertEqual(calls, [['api', '--method', 'GET', f'repos/{REPO}']])

    def test_public_target_is_refused(self):
        result, _ = self.run_helper('private', REPO, answers={f'repos/{REPO}': repo(private=False)})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, f'refused: {REPO} is not private\n')

    def test_unknown_visibility_is_never_private(self):
        for answer in ['FAIL', 'not JSON', {'full_name': REPO, 'default_branch': 'main'},
                       {'private': 'false', 'default_branch': 'main'}, {'private': True}, [],
                       '{"private": false, "private": true, "default_branch": "main"}']:
            with self.subTest(answer=answer):
                result, _ = self.run_helper('private', REPO, answers={f'repos/{REPO}': answer})
                self.assertEqual(result.returncode, 2)
                self.assertTrue(result.stdout.startswith(f'unknown: {REPO} visibility'), result.stdout)
                self.assertNotIn('private diagnostic', result.stdout + result.stderr)

    def test_a_malformed_repository_makes_no_call(self):
        result, calls = self.run_helper('private', '../elsewhere')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, [])

    # ---- check: one page, five sections, nothing secret ----

    def test_the_documented_page_passes(self):
        result, calls = self.run_helper('check', 'page.md', files={'page.md': GOOD})
        self.assertEqual((result.returncode, result.stdout), (0, 'page ok\n'))
        self.assertEqual(calls, [])

    def test_page_shape_problems(self):
        cases = {
            'no title': GOOD.replace('# Orchestrator handoff\n', ''),
            'no snapshot line': GOOD.replace('**Snapshot: ', '**When: '),
            'missing section': GOOD.replace('## Loops\n\nNone.\n\n', ''),
            'sections out of order': GOOD.replace('## Loops', '## TEMP').replace(
                '## Standing approvals', '## Loops').replace('## TEMP', '## Standing approvals'),
            'extra section': GOOD + '\n## History\n\nOld notes.\n',
            'empty section': GOOD.replace('## Loops\n\nNone.\n', '## Loops\n'),
        }
        for name, page in cases.items():
            with self.subTest(name):
                result, _ = self.run_helper('check', 'page.md', files={'page.md': page})
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertNotIn('page ok', result.stdout)

    def test_secrets_and_thread_ids_are_refused_without_echoing_them(self):
        secrets = ['ghp_' + 'A1b2C3d4' * 5, 'github_pat_' + 'x1Y2' * 8, 'owner@example.com',
                   'Bearer ' + 'abcDEF123456' * 2, 'thr_abc123def', '-----BEGIN OPENSSH PRIVATE KEY-----']
        for secret in secrets:
            with self.subTest(secret=secret[:6]):
                page = GOOD.replace('## Loops\n\nNone.', f'## Loops\n\nWatcher {secret} runs hourly.')
                result, _ = self.run_helper('check', 'page.md', files={'page.md': page})
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn('line 23', result.stdout)
                self.assertNotIn(secret, result.stdout + result.stderr)

    def test_an_unreadable_page_is_not_ok(self):
        result, _ = self.run_helper('check', 'missing.md')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('page ok', result.stdout)

    # ---- landed: the private default branch holds exactly this page ----

    def answers(self, text=GOOD, private=True, branch='main'):
        return {f'repos/{REPO}': repo(private, branch),
                f'repos/{REPO}/contents/{PAGE_PATH}?ref={branch}': contents(text)}

    def test_landed_reads_the_default_branch_back(self):
        result, calls = self.run_helper('landed', REPO, PAGE_PATH, 'page.md',
                                        answers=self.answers(branch='trunk'), files={'page.md': GOOD})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(result.stdout, f'landed: {PAGE_PATH} on trunk at {"a" * 40}\n')
        self.assertEqual(calls, [['api', '--method', 'GET', f'repos/{REPO}'],
                                 ['api', '--method', 'GET', f'repos/{REPO}/contents/{PAGE_PATH}?ref=trunk']])

    def test_a_different_default_branch_page_is_not_landed(self):
        result, _ = self.run_helper('landed', REPO, PAGE_PATH, 'page.md',
                                    answers=self.answers(text=GOOD.replace('#10', '#11')),
                                    files={'page.md': GOOD})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, f'not landed: {PAGE_PATH} on main differs from page.md\n')

    def test_landing_on_a_public_repository_is_refused(self):
        result, calls = self.run_helper('landed', REPO, PAGE_PATH, 'page.md',
                                        answers=self.answers(private=False), files={'page.md': GOOD})
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, f'refused: {REPO} is not private\n')
        self.assertEqual(len(calls), 1)

    def test_an_unreadable_read_back_is_unknown(self):
        duplicate = json.dumps(contents(GOOD.replace('#10', '#11')))[:-1] + ', "content": ' + json.dumps(contents(GOOD)['content']) + '}'
        for answer in ['FAIL', {'sha': 'a' * 40}, {'content': '%%%', 'encoding': 'base64', 'sha': 'a' * 40}, duplicate]:
            with self.subTest(answer=str(answer)[:10]):
                answers = self.answers()
                answers[f'repos/{REPO}/contents/{PAGE_PATH}?ref=main'] = answer
                result, _ = self.run_helper('landed', REPO, PAGE_PATH, 'page.md',
                                            answers=answers, files={'page.md': GOOD})
                self.assertEqual(result.returncode, 2, result.stdout)
                self.assertTrue(result.stdout.startswith('unknown: '), result.stdout)


if __name__ == '__main__':
    unittest.main()
