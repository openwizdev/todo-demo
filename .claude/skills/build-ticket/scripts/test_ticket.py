#!/usr/bin/env python3
"""Tests for build-ticket's ticket.py, run through its CLI on synthetic state.

python3 -I skills/build-ticket/scripts/test_ticket.py -v
"""
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / 'ticket.py'
FAKE = HERE / 'fixtures' / 'gh.py'
REPO = 'example/project'
HEAD = 'a' * 40
OLD = 'b' * 40

BODY = """## Parent

Ticket X1 of spec #40.

## Owned paths

- `src/export/` in `example/project`
- `docs/export.md` (shared with #43: its own section)
- its suite in `example/project`

**Relies on:** `docs/guide.md`

## Acceptance criteria

- [ ] Export refuses an existing destination
"""

START = 'launch-fleet: started'


def issue(state='OPEN', labels=('ready-for-agent',), blockers=(), body=BODY, number=41):
    return {'number': number, 'title': 'Export refuses an existing destination', 'state': state,
            'labels': [{'name': n} for n in labels], 'body': body, 'parent': {'number': 40},
            'blockedBy': {'nodes': [{'number': n, 'state': s,
                                     'url': f'https://github.com/{REPO}/issues/{n}'}
                                    for n, s, _ in blockers],
                          'totalCount': len(blockers)},
            'blocking': {'nodes': [{'number': 44, 'state': 'OPEN'}], 'totalCount': 1}}


FLEET = """# Fleet settings

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `example[bot]`, `Owner-1` |
"""


def last(out):
    lines = out.splitlines()
    return lines[-1] if lines else ''


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.bin = self.dir / 'bin'
        self.bin.mkdir()
        gh = self.bin / 'gh'
        gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{FAKE}" "$@"\n')
        gh.chmod(gh.stat().st_mode | stat.S_IXUSR)
        self.world = self.dir / 'world.json'
        self.save({'issues': {'41': issue()}, 'user': {'login': 'jparker', 'id': 7},
                   'comments': {'41': [{'id': 1, 'user': {'login': 'example[bot]'}, 'body': START}]},
                   'pr_head': HEAD, 'checkout_repo': REPO})
        self.origin = self.dir / 'origin.git'
        subprocess.run(['git', 'init', '-q', '--bare', str(self.origin)], check=True)
        self.repo = self.dir / 'checkout'
        self.repo.mkdir()
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.git('remote', 'add', 'origin', str(self.origin))
        self.write('docs/agents/fleet.md', FLEET)
        self.write('src/export/run.py', 'x = 1\n')
        self.write('src/other.py', 'y = 1\n')
        self.git('add', '.')
        self.git('commit', '-q', '-m', 'base')
        self.git('push', '-q', 'origin', 'main')
        self.git('fetch', '-q', 'origin')
        self.git('checkout', '-q', '-b', 'work')

    def tearDown(self):
        self.tmp.cleanup()

    def save(self, world):
        self.world.write_text(json.dumps(world))

    def load(self):
        return json.loads(self.world.read_text())

    def update(self, **values):
        world = self.load()
        world.update(values)
        self.save(world)

    def set_issue(self, n, value):
        world = self.load()
        world['issues'][str(n)] = value
        self.save(world)

    def comments(self, number, *items):
        world = self.load()
        world['comments'][str(number)] = [
            {'id': i, 'user': ({'login': login} if login else None), 'body': body}
            for i, (login, body) in enumerate(items, 1)]
        self.save(world)

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True, capture_output=True,
                              text=True).stdout

    def write(self, rel, text):
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def commit(self, message='change'):
        self.git('add', '-A')
        self.git('commit', '-q', '-m', message)

    def run_ticket(self, *args, timeout=60):
        env = {k: v for k, v in os.environ.items() if k not in ('GH_TOKEN', 'GITHUB_TOKEN')}
        env['PATH'] = f'{self.bin}{os.pathsep}{env.get("PATH", "")}'
        env['FAKE_GH_WORLD'] = str(self.world)
        r = subprocess.run([sys.executable, '-I', str(SCRIPT), *args], cwd=self.repo, env=env,
                           capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr


class Read(Case):
    def test_read_lists_owned_paths_and_readiness(self):
        code, out, err = self.run_ticket('read', REPO, '41')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('owned: src/export/ in example/project', lines)
        self.assertIn('owned: docs/export.md in example/project (shared with #43: its own section)', lines)
        self.assertIn('owned, not a path: its suite in `example/project`', lines)
        self.assertNotIn('owned: example/project in example/project', lines)
        self.assertIn('spec: #40', lines)
        self.assertIn('blocks: #44 OPEN', lines)
        self.assertIn('start: comment 1 by example[bot]: launch-fleet: started', lines)
        self.assertEqual(last(out), 'ready: yes')

    def test_read_keeps_repository_binding_and_annotated_lists(self):
        body = BODY.replace('- its suite in `example/project`\n',
                            '- `tools/` in `example/other`\n'
                            '- the pin and its readers (shared: only what changes): '
                            '`pin.lock`; `tests/checks/skills.rs`, each where the lookup changes\n')
        self.set_issue(41, issue(body=body))
        code, out, err = self.run_ticket('read', REPO, '41')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('owned: tools/ in example/other', lines)
        self.assertIn('owned, check the bullet: pin.lock in example/project', lines)
        self.assertIn('owned, check the bullet: tests/checks/skills.rs in example/project', lines)
        self.assertIn('bullet: the pin and its readers (shared: only what changes): '
                      '`pin.lock`; `tests/checks/skills.rs`, each where the lookup changes', lines)

    def test_read_refuses_an_open_blocker(self):
        self.set_issue(41, issue(blockers=((39, 'CLOSED', 'COMPLETED'), (42, 'OPEN', None))))
        self.set_issue(39, {'state': 'CLOSED', 'stateReason': 'COMPLETED'})
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual(code, 1)
        self.assertEqual(last(out), 'ready: no: #42 is open')

    def test_read_requires_completed_blockers_and_the_fleet_start(self):
        self.set_issue(41, issue(blockers=((39, 'CLOSED', 'NOT_PLANNED'),)))
        self.set_issue(39, {'state': 'CLOSED', 'stateReason': 'NOT_PLANNED'})
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual((code, last(out)), (1, 'ready: no: #39 was closed as NOT_PLANNED'))
        self.set_issue(39, {'state': 'CLOSED', 'stateReason': 'COMPLETED'})
        self.comments(41, ('stranger', START), ('example[bot]', 'launch-fleet: start refused: quota'))
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual((code, last(out)), (1, 'ready: no: no launch-fleet start record from a record author'))
        self.comments(41, ('owner-1', 'launch-fleet: start checked, branch room/41-x'))
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual((code, last(out)), (0, 'ready: yes'))

    def test_read_refuses_incomplete_blocker_data(self):
        for broken in ({}, {'nodes': [], 'totalCount': 1}):
            value = issue()
            value['blockedBy'] = broken
            self.set_issue(41, value)
            code, out, err = self.run_ticket('read', REPO, '41')
            self.assertEqual((code, out), (2, ''), broken)
            self.assertIn('incomplete blocker data', err)

    def test_read_refuses_a_ticket_not_released_to_agents(self):
        for state, labels, reason in (('CLOSED', ('ready-for-agent',), 'the ticket is CLOSED'),
                                      ('OPEN', ('needs-triage',), 'no ready-for-agent label'),
                                      ('OPEN', ('ready-for-agent', 'needs-info'), 'needs-info is open')):
            self.set_issue(41, issue(state=state, labels=labels))
            code, out, _ = self.run_ticket('read', REPO, '41')
            self.assertEqual((code, last(out)), (1, f'ready: no: {reason}'), state)

    def test_read_without_owned_paths_refuses(self):
        self.set_issue(41, issue(body='## What to build\n\nSomething.\n'))
        code, out, _ = self.run_ticket('read', REPO, '41')
        self.assertEqual((code, last(out)), (1, 'ready: no: no owned paths'))

    def test_unreadable_ticket_exits_2(self):
        code, out, err = self.run_ticket('read', REPO, '99')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('cannot read', err)


class Scope(Case):
    def test_scope_passes_owned_and_named_supporting_edits_only(self):
        self.write('src/export/run.py', 'x = 2\n')
        self.write('tests/export_test.py', 'pass\n')
        self.commit()
        code, out, err = self.run_ticket('scope', REPO, '41', '--supporting', 'tests/export_test.py')
        self.assertEqual(code, 0, out + err)
        self.assertIn('owned: src/export/run.py', out.splitlines())
        self.assertIn('supporting: tests/export_test.py', out.splitlines())
        self.assertEqual(last(out), 'scope: ok')

    def test_scope_flags_every_unowned_side(self):
        self.git('mv', 'src/export/run.py', 'src/moved.py')
        self.git('commit', '-q', '-m', 'rename out')
        self.write('src/other.py', 'y = 2\n')            # unstaged
        self.write('src/export-extra/x.py', 'z\n')       # untracked, prefix look-alike
        self.write('docs/export.md.bak', 'z\n')          # untracked, exact look-alike
        code, out, _ = self.run_ticket('scope', REPO, '41')
        lines = out.splitlines()
        self.assertEqual(code, 1)
        for path in ('src/moved.py', 'src/other.py', 'src/export-extra/x.py', 'docs/export.md.bak'):
            self.assertIn(f'OUT: {path}', lines)
        self.assertIn('owned: src/export/run.py', lines)
        self.assertEqual(last(out), 'scope: 4 path(s) outside the owned paths: ask first')

    def test_scope_applies_owned_paths_only_in_their_repository(self):
        self.set_issue(41, issue(body=BODY.replace('- its suite in `example/project`\n',
                                                   '- `src/other.py` in `example/elsewhere`\n')))
        self.write('src/other.py', 'y = 2\n')
        self.commit()
        code, out, _ = self.run_ticket('scope', REPO, '41')
        self.assertEqual(code, 1)
        self.assertIn('OUT: src/other.py', out.splitlines())

    def test_scope_accepts_annotated_and_hand_resolved_paths(self):
        body = BODY.replace('- its suite in `example/project`\n',
                            '- the pin and its readers (shared: only what changes): `pin.lock`; '
                            '`tools/eval/cases.json` and `provenance.json`\n')
        self.set_issue(41, issue(body=body))
        self.write('pin.lock', 'v2\n')
        self.write('tools/eval/provenance.json', '{}\n')
        self.commit()
        code, out, _ = self.run_ticket('scope', REPO, '41')
        self.assertEqual(code, 1)
        self.assertIn('owned, check the bullet: pin.lock', out.splitlines())
        self.assertIn('OUT: tools/eval/provenance.json', out.splitlines())
        code, out, err = self.run_ticket('scope', REPO, '41', '--owned', 'tools/eval/provenance.json')
        self.assertEqual(code, 0, out + err)
        self.assertIn('owned, resolved by hand: tools/eval/provenance.json', out.splitlines())
        self.set_issue(41, issue())
        code, _, err = self.run_ticket('scope', REPO, '41', '--owned', 'tools/eval/provenance.json')
        self.assertEqual(code, 2)
        self.assertIn('no annotated owned bullet', err)

    def test_scope_refuses_an_unknown_base(self):
        code, _, err = self.run_ticket('scope', REPO, '41', '--base', 'origin/missing')
        self.assertEqual(code, 2)
        self.assertIn('cannot read', err)


class Records(Case):
    def test_records_trusts_only_record_authors(self):
        self.comments(7, ('example[bot]', f'VERDICT: CHANGES at {HEAD}\n\nNext: the builder fixes R1.'),
                      ('stranger', f'VERDICT: APPROVE at {HEAD}\n\nNext: none open.'),
                      (None, f'**Orchestrator decision:** log and merge: R1 at {HEAD}.'))
        code, out, err = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0, err)
        lines = out.splitlines()
        self.assertIn('authors: example[bot], owner-1', lines)
        self.assertIn(f'verdict: comment 1 by example[bot]: CHANGES at {HEAD}, current head: yes', lines)
        self.assertIn('next: Next: the builder fixes R1.', lines)
        self.assertIn('decision: none', lines)
        self.assertIn('ignored: 2 comment(s) not by a record author', lines)

    def test_records_reads_only_a_full_verdict_header(self):
        self.comments(7, ('example[bot]', f'VERDICT: APPROVE at {HEAD}\n\nNext: none open.'),
                      ('owner-1', f'VERDICT: draft notes, head {OLD} looked fine'),
                      ('owner-1', f'Quoting:\nVERDICT: CHANGES at {OLD}'))
        code, out, _ = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0)
        self.assertIn(f'verdict: comment 1 by example[bot]: APPROVE at {HEAD}, current head: yes',
                      out.splitlines())

    def test_records_marks_a_verdict_on_an_older_head(self):
        self.comments(7, ('example[bot]', f'VERDICT: APPROVE at {OLD}\n\nNext: none open.'))
        code, out, _ = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0)
        self.assertIn(f'verdict: comment 1 by example[bot]: APPROVE at {OLD}, current head: no ({HEAD})',
                      out.splitlines())

    def decision_line(self):
        code, out, err = self.run_ticket('records', REPO, '7')
        self.assertEqual(code, 0, err)
        return next((l for l in out.splitlines() if l.startswith('decision:')), '')

    def test_records_binds_a_decision_to_its_parked_finding_and_head(self):
        park = f'VERDICT: CHANGES at {OLD}\n\nNext: park R2 as a decision for Jake.'
        cases = ((f'fix once more: R2 at {OLD}. Why: x', f'bound: no: {OLD} is not the current head'),
                 (f'log and merge: R3 at {HEAD}. Polish issues: #9. Why: x',
                  f'bound: no: R3 was not parked at {HEAD}'),
                 ('fix once more R2', 'bound: no: not a decision line'),
                 (f'fix once more: R2 at {HEAD}. Why: x', 'bound: yes'))
        for decision, expected in cases:
            self.comments(7, ('example[bot]', park.replace(OLD, HEAD) if HEAD in decision else park),
                          ('owner-1', f'**Orchestrator decision:** {decision}'))
            line = self.decision_line()
            self.assertTrue(line.startswith('decision: comment 2 by owner-1: '), line)
            self.assertTrue(line.endswith(expected), (decision, line))

    def test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park(self):
        # catches: a partial, early, incomplete or quoted-park decision resuming parked work
        report = (f'VERDICT: CHANGES at {HEAD}\n\n- **R1 [blocking]** x\n  Risk: security: y\n'
                  f'- **R2 [blocking]** x\n  Risk: security: y\n\nNext: park R1 and R2 as a decision for Jake.')
        exact = f'**Orchestrator decision:** fix once more: R1 and R2 at {HEAD}. Why: x'
        partial = f'**Orchestrator decision:** fix once more: R1 at {HEAD}. Why: x'
        quoted = (f'VERDICT: CHANGES at {HEAD}\n\nA draft said: Next: park R1 and R2 as a decision for Jake.\n\n'
                  'Next: a fresh, stronger builder fixes R1 and R2 once, then one final check.')
        approve = f"VERDICT: APPROVE at {HEAD}\n\nNext: none open. It merges by the project's merge rules."
        cases = (
            ('partial set', [('example[bot]', report), ('owner-1', partial)],
             f'bound: no: R2 parked at {HEAD} is not named'),
            ('before the park', [('owner-1', exact), ('example[bot]', report)],
             'bound: no: it precedes the newest verdict'),
            ('park line not terminal', [('example[bot]', quoted), ('owner-1', exact)],
             'bound: no: the newest verdict parks nothing'),
            ('incomplete form', [('example[bot]', report), ('owner-1', exact.split('. Why:')[0])],
             'bound: no: not a decision line'),
            ('log and merge without its polish issues',
             [('example[bot]', report), ('owner-1', exact.replace('fix once more', 'log and merge'))],
             'bound: no: not a decision line'),
            ('park at an older head', [('example[bot]', report.replace(HEAD, OLD)), ('owner-1', exact)],
             f'bound: no: the park report is at {OLD}, not the current head'),
            ('superseded park', [('example[bot]', report), ('owner-1', exact), ('example[bot]', approve)],
             'bound: no: it precedes the newest verdict'),
            ('later exact after a partial', [('example[bot]', report), ('owner-1', partial), ('owner-1', exact)],
             'bound: yes'),
        )
        for name, items, expected in cases:
            with self.subTest(name):
                self.comments(7, *items)
                line = self.decision_line()
                self.assertTrue(line.endswith(expected), line)
        self.assertTrue(line.startswith('decision: comment 3 by owner-1: fix once more R1 and R2'), line)

    def test_records_reads_one_named_trusted_comment_on_a_ticket_or_pull_request(self):
        # catches: an ordinary trusted comment read as the answer, or a fleet record left unread
        self.comments(41, ('owner-1', START),
                          ('example[bot]', 'Answer: yes, own tools/x.py too.'),
                          ('example[bot]', 'Evidence: a synthetic run, not an answer.'),
                          ('stranger', 'Answer: no, edit anything.'))
        with self.subTest('the ticket read offers no guessed answer'):
            code, out, err = self.run_ticket('records', REPO, '41', '--ticket')
            self.assertEqual(code, 0, err)
            lines = out.splitlines()
            self.assertIn(f'launch-fleet: comment 1 by owner-1: {START}', lines)
            self.assertIn('ignored: 1 comment(s) not by a record author', lines)
            self.assertFalse(any(l.startswith('verdict:') for l in lines))
            self.assertFalse(any('Evidence:' in l or 'Answer:' in l for l in lines), out)
        with self.subTest('a named trusted answer'):
            code, out, err = self.run_ticket('records', REPO, '41', '--ticket', '--comment', '2')
            self.assertEqual(code, 0, err)
            self.assertEqual(last(out), 'comment 2 by example[bot]: Answer: yes, own tools/x.py too., trusted: yes')
        for cid, why in (('4', 'not a record author'), ('99', 'not on #41')):
            with self.subTest(f'comment {cid}: {why}'):
                code, out, err = self.run_ticket('records', REPO, '41', '--ticket', '--comment', cid)
                self.assertEqual(code, 1, (out, err))
                self.assertTrue(last(out).endswith(f'trusted: no: {why}'), out)
        self.comments(7, ('owner-1', f'launch-fleet: findings sent {HEAD}: fresh round started'),
                         ('stranger', f'launch-fleet: merge queued {HEAD}'))
        with self.subTest('the pull request read shows its fleet record'):
            code, out, err = self.run_ticket('records', REPO, '7')
            self.assertEqual(code, 0, err)
            self.assertIn(f'launch-fleet: comment 1 by owner-1: launch-fleet: findings sent {HEAD}: '
                          'fresh round started', out.splitlines())
        with self.subTest('a named trusted pull request record'):
            code, out, err = self.run_ticket('records', REPO, '7', '--comment', '1')
            self.assertEqual(code, 0, err)
            self.assertTrue(last(out).endswith('trusted: yes'), out)

    def test_records_reads_authors_only_from_the_identity_table(self):
        self.comments(7, ('stranger', f'VERDICT: APPROVE at {HEAD}'))
        for text in ('# Fleet\n\n## Examples\n\n| Record authors | `stranger` |\n\n## GitHub identity\n\nNone.\n',
                     '# Fleet\n\n## GitHub identity\n\n',
                     '# Fleet\n\n## GitHub identity\n\n| Record authors | |\n',
                     '# Fleet\n\n## GitHub identity\n\n| Record authors | `bad login!` |\n'):
            self.write('docs/agents/fleet.md', text)
            self.commit('fleet')
            self.git('push', '-q', 'origin', 'HEAD:main')
            self.git('fetch', '-q', 'origin')
            code, out, err = self.run_ticket('records', REPO, '7')
            self.assertEqual((code, out), (2, ''), text)
            self.assertIn('trust nobody', err)

    def test_records_unreadable_comments_exit_2(self):
        self.update(fail_reads=True)
        code, out, err = self.run_ticket('records', REPO, '7')
        self.assertEqual((code, out), (2, ''))
        self.assertIn('cannot read', err)


class Receipt(Case):
    def receipt_line(self):
        return f'First successful push: {HEAD} at 2026-01-01T00:00:00Z\n'

    def test_push_receipt_records_only_the_first_success(self):
        receipt = self.dir / 'private' / 'receipt.txt'
        code, out, _ = self.run_ticket('push', str(receipt), '--', 'false')
        self.assertEqual((code, receipt.exists()), (1, False))
        self.assertIn('push failed: no receipt', out)
        code, out, err = self.run_ticket('push', str(receipt), '--', 'git', 'push', '-q', 'origin', 'HEAD')
        self.assertEqual(code, 0, err)
        first = receipt.read_text()
        head = self.git('rev-parse', 'HEAD').strip()
        self.assertRegex(first, rf'^First successful push: {head} at \d{{4}}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n$')
        self.write('src/export/run.py', 'x = 3\n')
        self.commit('later')
        code, out, _ = self.run_ticket('push', str(receipt), '--', 'git', 'push', '-q', 'origin', 'HEAD')
        self.assertEqual((code, receipt.read_text()), (0, first))
        self.assertIn('receipt kept', out)

    def test_push_after_an_unrecorded_earlier_push_stays_unknown(self):
        receipt = self.dir / 'receipt.txt'
        self.git('push', '-q', 'origin', 'main:refs/heads/work')     # branch made at the base
        code, out, err = self.run_ticket('push', str(receipt), '--', 'true')
        self.assertEqual(code, 0, err)
        self.assertTrue(receipt.exists(), out)
        receipt.unlink()
        self.write('src/export/run.py', 'x = 4\n')
        self.commit('checkpoint')
        self.git('push', '-q', 'origin', 'HEAD')                      # a push with no receipt
        self.write('src/export/run.py', 'x = 5\n')
        self.commit('hand-back')
        code, out, err = self.run_ticket('push', str(receipt), '--', 'git', 'push', '-q', 'origin', 'HEAD')
        self.assertEqual(code, 0, err)
        self.assertFalse(receipt.exists())
        self.assertIn('receipt unknown: an earlier push to work has no receipt', out)

    def test_push_refuses_a_receipt_inside_the_checkout(self):
        code, _, err = self.run_ticket('push', str(self.repo / 'receipt.txt'), '--', 'true')
        self.assertEqual(code, 2)
        self.assertFalse((self.repo / 'receipt.txt').exists())
        self.assertIn('outside the checkout', err)

    def test_post_receipt_survives_a_lost_response_and_never_posts_twice(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(self.receipt_line())
        self.update(lose_post_response='exit')
        code, out, err = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 0, err)
        self.assertIn('receipt posted: comment 9000', out)
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 0)
        self.assertIn('receipt reused: comment 9000', out)
        self.assertEqual([c['body'] for c in self.load()['comments']['7']], [receipt.read_text()])

    def test_post_receipt_ignores_a_copy_by_anyone_else(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(self.receipt_line())
        self.comments(7, ('stranger', receipt.read_text()))
        code, out, err = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 0, err)
        self.assertIn('receipt posted: comment 9001', out)
        self.update(poster='stranger')
        receipt.write_text(self.receipt_line().replace('00:00:00', '00:00:01'))
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 1)
        self.assertIn('receipt not posted', out)

    def test_post_receipt_reads_back_after_a_timed_out_post(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(self.receipt_line())
        self.update(lose_post_response='timeout', hang_seconds=150)
        code, out, err = self.run_ticket('post-receipt', REPO, '7', str(receipt), timeout=200)
        self.assertEqual(code, 0, out + err)
        self.assertIn('receipt posted: comment 9000', out)

    def test_post_receipt_without_a_read_back_is_unknown(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(self.receipt_line())
        self.update(lose_post_response='exit', fail_reads_after_post=True)
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 1)
        self.assertIn('receipt unknown: read the pull request before posting again', out)
        self.assertEqual(len(self.load()['comments']['7']), 1)

    def test_post_receipt_reports_a_refused_write(self):
        receipt = self.dir / 'receipt.txt'
        receipt.write_text(self.receipt_line())
        self.update(refuse_post=True)
        code, out, _ = self.run_ticket('post-receipt', REPO, '7', str(receipt))
        self.assertEqual(code, 1)
        self.assertIn('receipt not posted', out)


class Author(Case):
    def test_author_sets_the_users_noreply_identity(self):
        code, out, err = self.run_ticket('author')
        self.assertEqual(code, 0, err)
        got = [self.git('config', key).strip() for key in ('user.name', 'user.email')]
        self.assertEqual(got, ['jparker', '7+jparker@users.noreply.github.com'])
        self.assertEqual(out, 'author: jparker <7+jparker@users.noreply.github.com>\n')


if __name__ == '__main__':
    unittest.main()
