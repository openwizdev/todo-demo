#!/usr/bin/env python3
"""post.py on a synthetic GitHub (WS8, #1181): public records, read back.

python3 -I skills/launch-fleet/scripts/test-post.py
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')


class World:
    """One synthetic repository and a `gh` on PATH that serves it."""

    def __init__(self, test, **extra):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        gh = bin_dir / 'gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, HERE / 'fixtures/fake_github.py'))
        gh.chmod(0o755)
        self.path = self.dir / 'world.json'
        value = {'repo': REPO, 'me': 'openwiz[bot]', 'fleet_md': FLEET_MD, 'next_id': 5000,
                 'comments': {}, 'writes': [], 'faults': {}}
        value.update(extra)
        self.save(value)
        self.env = dict(os.environ, PATH='%s:%s' % (bin_dir, os.environ['PATH']), FAKE_WORLD=str(self.path))

    def load(self):
        return json.loads(self.path.read_text())

    def save(self, value):
        self.path.write_text(json.dumps(value))

    def update(self, **changes):
        value = self.load()
        value.update(changes)
        self.save(value)

    def run(self, script, *args, cwd=None):
        r = subprocess.run([sys.executable, '-I', str(HERE / script), *map(str, args)], capture_output=True,
                           text=True, env=self.env, cwd=cwd or self.dir, timeout=60)
        return r.returncode, r.stdout.strip()

    def writes(self):
        return self.load()['writes']

    def bodies(self, number):
        return [c['body'] for c in self.load()['comments'].get(str(number), [])]


def comment(cid, body, login='openwiz[bot]'):
    return {'id': cid, 'body': body, 'user': {'login': login}, 'created_at': '2026-01-01T00:00:00Z'}


class Post(unittest.TestCase):
    def test_a_record_is_posted_once_and_read_back(self):
        w = World(self)
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out), (0, 'posted 5001'))
        self.assertEqual(w.bodies(12), ['launch-fleet: starting'])
        self.assertEqual(len(w.writes()), 1)

    def test_private_identities_are_refused_with_zero_writes(self):
        w = World(self)
        for body in ('launch-fleet: started, thread thr_synthetic1',
                     'launch-fleet: look: builder thr_abc and thr_def both match',
                     'launch-fleet: started\n\nwith gho_synthetictoken0123456789',
                     '**Needs you:** loop loop_synthetic9 refused'):
            with self.subTest(body=body):
                code, out = w.run('post.py', 'comment', REPO, 12, body)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])

    def test_only_fleet_records_are_posted(self):
        w = World(self)
        for body in ('Looks good to me', '', 'VERDICT: APPROVE at ' + 'a' * 40, ' launch-fleet starting'):
            with self.subTest(body=body):
                code, out = w.run('post.py', 'comment', REPO, 12, body)
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])
        self.assertEqual(w.run('post.py', 'comment', REPO, 3, '**Needs you:** spec #3 changed since revision 2')[0], 0)

    def test_a_lost_response_is_unknown_and_left_for_reconciliation(self):
        # catches: (#1555) a write whose response is lost adopting the one new
        # identical record, which a second wake can equally have written.
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]}, faults={'post': 'lost'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out.split(' ')[0]), (1, 'unknown:'), out)
        self.assertEqual(len(w.writes()), 1)

    def test_another_wakes_identical_record_is_never_adopted(self):
        # catches: (#1555) a failed write returning another wake's identical
        # claim id as its own, so both wakes proceed as owners of one claim.
        w = World(self, faults={'post': 'fail'})
        # The other wake's identical claim lands while this wake's write is in flight.
        inject = w.dir / 'other_wake.py'
        inject.write_text('import json, os\nw = json.load(open(os.environ["FAKE_WORLD"]))\n'
                          'w["comments"].setdefault("12", []).append(%r)\n'
                          'json.dump(w, open(os.environ["FAKE_WORLD"], "w"))\n' % comment(8001, 'launch-fleet: starting'))
        gh = w.dir / 'bin' / 'gh'
        head, rest = gh.read_text().split('\n', 1)
        gh.write_text('%s\ncase " $* " in *" POST "*) "%s" -I "%s";; esac\n%s' % (head, sys.executable, inject, rest))
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual((code, out.split(' ')[0]), (1, 'unknown:'), out)

    def test_a_failed_write_is_unknown_never_posted(self):
        w = World(self, faults={'post': 'fail'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_identical_text_from_anyone_else_is_not_the_record(self):
        # The response is lost, and the only new comment with these words is not a record author's.
        w = World(self, me='someone-else', faults={'post': 'lost'})
        code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_without_record_authors_nothing_is_trusted(self):
        for fleet_md in (None, '# Fleet settings\n', FLEET_MD.replace('`openwiz[bot]`, ', '`openwiz[bot]` ')):
            with self.subTest(fleet_md=fleet_md):
                w = World(self, fleet_md=fleet_md)
                code, out = w.run('post.py', 'comment', REPO, 12, 'launch-fleet: starting')
                self.assertEqual(code, 1)
                self.assertTrue(out.startswith('refused: '), out)
                self.assertEqual(w.writes(), [])

    def test_an_edit_is_read_back(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]})
        self.assertEqual(w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started'), (0, 'edited 4000'))
        self.assertEqual(w.bodies(12), ['launch-fleet: started'])

    def test_a_lost_edit_is_recovered_and_a_failed_one_is_unknown(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting')]}, faults={'patch': 'lost'})
        self.assertEqual(w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started'), (0, 'edited 4000'))
        w.update(faults={'patch': 'fail'})
        code, out = w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: start checked, branch room/12-x')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)

    def test_another_authors_comment_is_never_edited(self):
        w = World(self, comments={'12': [comment(4000, 'launch-fleet: starting', login='someone-else')]})
        code, out = w.run('post.py', 'edit', REPO, 4000, 'launch-fleet: started')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('refused: '), out)
        self.assertEqual(w.writes(), [])



class SelfGrant(unittest.TestCase):
    """self-grant.py (#1353, F4): a wake grants and records the four bounded
    kinds itself, each with its reason; a model or effort change is refused."""

    def test_each_kind_is_recorded_with_its_reason(self):
        # catches: a grant made without a record, or recorded without its
        # reason, so nobody can audit what the fleet allowed itself.
        w = World(self)
        cases = [('supporting-edit', 'two lines in check/run.py, which runs the new test',
                  'launch-fleet: granted supporting edit: two lines in check/run.py, which runs the new test'),
                 ('dependency-wiring', 'the spec-approved pinned parser in the build file',
                  'launch-fleet: granted dependency wiring: the spec-approved pinned parser in the build file'),
                 ('read-route', 'the issue timeline, under the API rules',
                  'launch-fleet: granted read route: the issue timeline, under the API rules')]
        for kind, reason, body in cases:
            with self.subTest(kind=kind):
                self.assertEqual(w.run('self-grant.py', REPO, 12, kind, reason)[0], 0)
                self.assertEqual(w.bodies(12)[-1:], [body])
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof table names the after bench', '--spec', 3)
        self.assertEqual(code, 0, out)
        self.assertEqual(w.bodies(3), ['launch-fleet: spec changed for #12: the proof table names the after bench'])
        self.assertEqual(w.bodies(12)[-1], 'launch-fleet: granted spec change on #3: the proof table names the after bench')
        self.assertEqual(len(w.writes()), 5)

    def test_a_model_or_effort_change_or_any_other_ask_is_refused(self):
        # catches: a fleet that grants itself a stronger model or effort, or
        # anything outside the four kinds, instead of asking.
        w = World(self)
        for kind, why in (('model', 'refused: a model or effort change is never a self-grant; ask Jake'),
                          ('effort', 'refused: a model or effort change is never a self-grant; ask Jake'),
                          ('contract', 'refused: not a self-grant kind; ask the orchestrator'),
                          ('spend', 'refused: not a self-grant kind; ask the orchestrator')):
            with self.subTest(kind=kind):
                self.assertEqual(w.run('self-grant.py', REPO, 12, kind, 'a stronger fixer round'), (1, why))
        for args in ((REPO, 12, 'spec-change', 'no spec named'), (REPO, 12, 'read-route', ''),
                     (REPO, 12, 'read-route', 'two\nlines'), (REPO, 12, 'read-route', 'x', '--spec', 12)):
            with self.subTest(args=args):
                self.assertEqual(w.run('self-grant.py', *args)[0], 2)
        self.assertEqual(w.writes(), [])

    def test_a_spec_change_not_read_back_records_no_grant(self):
        # catches: a ticket told its spec changed when the spec record may
        # never have been written.
        w = World(self, faults={'post': 'fail'})
        code, out = w.run('self-grant.py', REPO, 12, 'spec-change', 'the proof names the after bench', '--spec', 3)
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('unknown: '), out)
        self.assertEqual(w.bodies(12), [])

if __name__ == '__main__':
    unittest.main()
