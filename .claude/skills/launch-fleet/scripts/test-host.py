#!/usr/bin/env python3
"""host.py (#1371): builders start, wake and stop through the chosen host's driver; a refused start or
wake is tried twice more, then reported on the ticket once, and a later success clears it (#1446).

python3 -I skills/launch-fleet/scripts/test-host.py

Each case is a synthetic project checkout with `docs/agents/host.md`, an
adapters folder of synthetic drivers (fixtures/driver.py, one per host) that
log every call, a private runs file and a synthetic GitHub (fixtures/fake_github.py on PATH as `gh`).
Nothing reaches GitHub or a host.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'synthetic-owner/synthetic-repo'
VERSION = json.loads((HERE.parents[2] / '.claude-plugin/plugin.json').read_text())['version']
FLEET_MD = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
            '| Record authors | `openwiz[bot]`, `synthetic-owner` |\n')
MARK = 'launch-fleet: driver start failed'
NEXT = 'sign in to the harness, then start again'


class Project:
    """A synthetic project: a bare origin whose default branch is `trunk`, a fleet checkout cloned from it,
    an adapters folder and a private runs file. set() changes the setting on the default branch only."""

    def __init__(self, test, setting='Host: local\n', hosts=('local', 'cloudroom')):
        self.dir = Path(tempfile.mkdtemp())
        test.addCleanup(subprocess.run, ['rm', '-rf', str(self.dir)])
        test.addCleanup(subprocess.run, ['chmod', '-R', 'u+w', str(self.dir)])
        self.git_env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1',
                            GIT_AUTHOR_NAME='synthetic', GIT_AUTHOR_EMAIL='synthetic@example.invalid',
                            GIT_COMMITTER_NAME='synthetic', GIT_COMMITTER_EMAIL='synthetic@example.invalid')
        self.git('init', '-q', '--bare', '-b', 'trunk', str(self.dir / 'origin.git'))
        self.git('clone', '-q', str(self.dir / 'origin.git'), str(self.dir / 'writer'))
        (self.dir / 'writer/docs/agents').mkdir(parents=True)
        (self.dir / 'writer/README.md').write_text('synthetic\n')
        self.git('-C', str(self.dir / 'writer'), 'add', '-A')
        self.git('-C', str(self.dir / 'writer'), 'commit', '-q', '-m', 'start')
        self.git('-C', str(self.dir / 'writer'), 'push', '-q', 'origin', 'trunk')
        if setting is not None:
            self.set(setting)
        self.git('clone', '-q', str(self.dir / 'origin.git'), str(self.dir / 'repo'))
        for host in hosts:
            folder = self.dir / 'adapters' / host
            folder.mkdir(parents=True)
            (folder / 'driver').write_text('#!/bin/sh\nFAKE_DRIVER_HOST=%s exec "%s" -I "%s" "$@"\n'
                                           % (host, sys.executable, HERE / 'fixtures/driver.py'))
            (folder / 'driver').chmod(0o755)
        self.log = self.dir / 'driver.log'
        self.runs = self.dir / 'private/runs.json'
        self.runs.parent.mkdir()
        bin_dir = self.dir / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'gh').write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, HERE / 'fixtures/fake_github.py'))
        (bin_dir / 'gh').chmod(0o755)
        self.world = self.dir / 'world.json'
        self.world.write_text(json.dumps({'repo': REPO, 'me': 'openwiz[bot]', 'fleet_md': FLEET_MD, 'next_id': 5000,
                                          'comments': {}, 'writes': [], 'faults': {}}))
        self.env = dict(self.git_env, OPENWIZ_ADAPTERS=str(self.dir / 'adapters'), LAUNCH_FLEET_RUNS=str(self.runs),
                        FAKE_DRIVER_LOG=str(self.log), PATH='%s:%s' % (bin_dir, os.environ['PATH']),
                        FAKE_WORLD=str(self.world), LAUNCH_FLEET_HARNESS='Claude Code',
                        LAUNCH_FLEET_MODEL='Opus 5.5 Medium', LAUNCH_FLEET_SKILLS='launch-fleet@' + VERSION)

    def git(self, *args):
        subprocess.run(['git', *args], check=True, env=self.git_env, capture_output=True, timeout=60)

    def set(self, setting):
        """Change the setting on origin's default branch; the fleet checkout keeps what it had."""
        (self.dir / 'writer/docs/agents/host.md').write_text('# Host\n\nWhere this project\'s agents run.\n\n' + setting)
        self.git('-C', str(self.dir / 'writer'), 'add', '-A')
        self.git('-C', str(self.dir / 'writer'), 'commit', '-q', '-m', 'host')
        self.git('-C', str(self.dir / 'writer'), 'push', '-q', 'origin', 'trunk')

    def host(self, *args, **env):
        r = subprocess.run([sys.executable, '-I', str(HERE / 'host.py'), *map(str, args)], cwd=self.dir / 'repo',
                           capture_output=True, text=True, timeout=60, env=dict(self.env, **env))
        return r.returncode, r.stdout.strip(), r.stderr.strip()

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def saved(self):
        return json.loads(self.runs.read_text()) if self.runs.exists() else None

    def github(self):
        return json.loads(self.world.read_text())

    def fault(self, **faults):
        world = self.github()
        world['faults'] = faults
        self.world.write_text(json.dumps(world))

    def ticket(self, n=7):
        """#N's comments as GitHub holds them: (first line, the rest) of each, oldest first."""
        return [tuple(c['body'].split('\n', 1)) if '\n' in c['body'] else (c['body'], '')
                for c in self.github()['comments'].get(str(n), [])]

    def fleet_notes(self, n=7):
        """The `state:` of each fleet status note on #N, oldest first."""
        return [next(line[len('state: '):] for line in body.split('\n') if line.startswith('state: '))
                for first, body in self.ticket(n) if first == '<!-- openwiz:status v1 -->' and 'agent: fleet' in body]

    def driver_log(self):
        """The owner-only driver log's entries (#1446, the decision on R3): the driver's own words live only here."""
        log = self.runs.with_name('driver-failures.log')
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def failure(self, command='start', entry=0, n=7):
        """The one failure comment #N should hold: a fixed reason, the exit category and a pointer to a log entry."""
        return (MARK, "The local driver refused to %s this ticket's builder 3 times (exit 1: refused). Its own words "
                      "are kept off this public ticket: the fleet's owner can read them in the private driver log, "
                      "`driver-failures.log` beside `LAUNCH_FLEET_RUNS`, entry %s for #%s."
                % (command, self.driver_log()[entry]['time'], n))

    def failures(self, n=7):
        """The failure comments on #N: each one's first line and text."""
        return [(first, rest.strip()) for first, rest in self.ticket(n) if first.startswith(MARK)]


class Host(unittest.TestCase):
    def test_start_goes_through_the_chosen_driver_and_saves_its_run(self):
        p = Project(self)
        self.assertEqual(p.host('which'), (0, 'host: local', ''))
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (0, 'started #7 on local', ''))
        self.assertEqual(p.calls(), [{'host': 'local', 'command': 'start', 'input': {
            'repository': REPO, 'ticket': 7, 'skill': 'build-ticket', 'harness': 'claude', 'model': 'claude-opus-5-5'}}])
        self.assertEqual(p.saved(), {'repo': REPO, 'runs': {'7': {'host': 'local', 'run': 'local-run-7'}}})
        self.assertEqual(p.runs.stat().st_mode & 0o777, 0o600)
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.host('stop', REPO, 7), (0, 'stopped #7 on local', ''))
        self.assertEqual([(c['host'], c['command'], c['input']) for c in p.calls()[1:]],
                         [('local', 'wake', {'run': 'local-run-7'}), ('local', 'stop', {'run': 'local-run-7'})])
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7', 'stopped': True}})
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5'), (0, 'started #7 on local', ''))
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})

    def test_changing_the_setting_switches_the_driver_and_each_run_keeps_its_own(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        p.set('Host: cloudroom\n')
        # R1: the default branch decides, not the fleet checkout's older copy.
        self.assertIn('Host: local', (p.dir / 'repo/docs/agents/host.md').read_text())
        self.assertEqual(p.host('which'), (0, 'host: cloudroom', ''))
        self.assertEqual(p.host('start', REPO, 8, 'codex', 'gpt-6.1-sol'), (0, 'started #8 on cloudroom', ''))
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.host('wake', REPO, 8), (0, 'woke #8 on cloudroom', ''))
        self.assertEqual([(c['host'], c['command'], c['input'].get('run') or c['input']['ticket']) for c in p.calls()],
                         [('local', 'start', 7), ('cloudroom', 'start', 8),
                          ('local', 'wake', 'local-run-7'), ('cloudroom', 'wake', 'cloudroom-run-8')])
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'},
                                             '8': {'host': 'cloudroom', 'run': 'cloudroom-run-8'}})

    def test_a_ticket_never_gets_a_second_run(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        p.set('Host: cloudroom\n')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')
        self.assertEqual((code, out), (1, 'refused: #7 already has a run on local; wake or stop it instead'))
        self.assertEqual(len(p.calls()), 1)

    def test_an_unreadable_answer_saves_no_run_and_is_never_retried(self):
        # A refusal is tested in Failures below. An unknown answer may mean a run exists: one call, no retry (#1446).
        p = Project(self)
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='garbage')
        self.assertEqual((code, out), (1, 'unknown: the local driver answered no run; a run may exist, '
                                          'so reconcile before any retry'))
        self.assertIsNone(p.saved())
        self.assertEqual(len(p.calls()), 1)
        code, out, _ = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', FAKE_DRIVER_MODE='extra')
        self.assertEqual((code, out), (1, 'unknown: the local driver answered no run; a run may exist, '
                                          'so reconcile before any retry'))
        self.assertIsNone(p.saved())
        self.assertEqual(len(p.calls()), 2)
        self.assertEqual(p.github()['writes'], [])
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[0], 0)
        self.assertEqual(p.host('wake', REPO, 7, FAKE_DRIVER_MODE='extra')[:2],
                         (1, 'unknown: the local driver answered no run; a run may exist, so reconcile before any retry'))

    def test_starts_at_once_keep_every_run(self):
        p = Project(self)
        hold = p.dir / 'hold'
        hold.touch()
        slow = subprocess.Popen([sys.executable, '-I', str(HERE / 'host.py'), 'start', REPO, '7', 'claude', 'm'],
                                cwd=p.dir / 'repo', env=dict(p.env, FAKE_DRIVER_HOLD=str(hold)),
                                stdout=subprocess.PIPE, text=True)
        self.addCleanup(slow.kill)
        for _ in range(500):  # until #7's driver has its call (it logs before it waits)
            if p.calls():
                break
            time.sleep(0.02)
        self.assertEqual(len(p.calls()), 1)
        self.assertEqual(p.host('start', REPO, 8, 'claude', 'm'), (0, 'started #8 on local', ''))
        hold.unlink()
        self.assertEqual((slow.communicate(timeout=60)[0].strip(), slow.returncode), ('started #7 on local', 0))
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'},
                                             '8': {'host': 'local', 'run': 'local-run-8'}})

    def test_unwritable_run_state_starts_nothing_and_a_lost_save_keeps_the_run(self):
        # R3: the private state is checked before the driver runs; a save lost after a start names the run.
        p = Project(self)
        code, out, err = p.host('start', REPO, 7, 'claude', 'm', LAUNCH_FLEET_RUNS=str(p.dir / 'missing/runs.json'))
        self.assertEqual((code, out), (2, ''))
        self.assertTrue(err.startswith('host.py: '), err)
        self.assertEqual(p.calls(), [])
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_BREAK=str(p.runs.parent))
        self.assertEqual((code, out), (1, 'unknown: #7 started on local but its run was not saved; save run '
                                          'local-run-7 on host local for #7 privately before anything else'))
        self.assertEqual(len(p.calls()), 1)

    def test_no_run_or_no_setting_leaves_the_room_cli_route(self):
        p = Project(self, setting=None)
        self.assertEqual(p.host('which'), (0, 'host: none', ''))
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')[:2],
                         (1, 'refused: no host is chosen in docs/agents/host.md'))
        self.assertEqual(p.host('wake', REPO, 9)[:2], (1, 'no run: #9 was not started through a driver'))
        self.assertEqual(p.calls(), [])

    def test_a_broken_setting_or_driver_starts_nothing(self):
        cases = {'two lines': 'Host: local\nHost: cloudroom\n', 'bad name': 'Host: ../local\n',
                 'no driver': 'Host: boat\n', 'no line': 'Somewhere: local\n'}
        for name, setting in cases.items():
            with self.subTest(name):
                p = Project(self, setting=setting)
                code, out, err = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5')
                self.assertEqual((code, out), (2, ''), err)
                self.assertTrue(err.startswith('host.py: '), err)
                self.assertEqual(p.calls(), [])
                self.assertIsNone(p.saved())
        p = Project(self)
        code, _, err = p.host('start', REPO, 7, 'claude', 'claude-opus-5-5', OPENWIZ_ADAPTERS='')
        self.assertEqual(code, 2)
        self.assertIn('OPENWIZ_ADAPTERS', err)
        self.assertEqual(p.calls(), [])


STOPPED = 'stopped (driver start failed)'


class Failures(unittest.TestCase):
    """#1446: a refused start or wake is tried three times in all, then reported on the ticket once."""

    def test_a_refused_start_is_tried_three_times_with_backoff_then_reported_once(self):
        p = Project(self)
        began = time.monotonic()
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertGreaterEqual(time.monotonic() - began, 3, 'two waits, of 1 and 2 seconds')
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertIsNone(p.saved())
        self.assertEqual(p.fleet_notes(), [STOPPED])
        self.assertEqual(p.failures(), [p.failure()])
        # The fleet tries again later and the driver still refuses: no second note or comment.
        writes = len(p.github()['writes'])
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[:2], (code, out))
        self.assertEqual(len(p.calls()), 6)
        self.assertEqual(len(p.github()['writes']), writes)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_the_drivers_own_words_stay_in_the_owners_log_never_on_the_ticket(self):
        # The orchestrator's decision on R3 at 90aed73: no free text of the driver's ever reaches the ticket.
        p = Project(self)
        words = 'reach svc:made-up-pass-44@driver.example.invalid, then ask the synthetic operator'
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', FAKE_DRIVER_NEXT=words)[0], 1)
        world = json.dumps(p.github())
        for part in ('made-up-pass-44', 'synthetic operator', 'not signed in'):
            self.assertNotIn(part, world)
        self.assertEqual(p.failures(), [p.failure()])
        log = p.runs.with_name('driver-failures.log')
        self.assertEqual(log.stat().st_mode & 0o777, 0o600)
        entry = p.driver_log()[0]
        self.assertEqual({k: entry[k] for k in ('repo', 'ticket', 'host', 'command', 'exit', 'error', 'next')},
                         {'repo': REPO, 'ticket': 7, 'host': 'local', 'command': 'start', 'exit': 1,
                          'error': 'the synthetic harness is not signed in', 'next': words})
        # A later refusal adds its own entry; the one comment keeps pointing at the first.
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((len(p.driver_log()), p.failures()), (2, [p.failure()]))

    def test_a_start_that_succeeds_on_a_retry_reports_nothing(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_REFUSALS='2'), (0, 'started #7 on local', ''))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})
        self.assertEqual(p.github()['writes'], [])

    def test_a_later_success_clears_the_stopped_state_once(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm'), (0, 'started #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual(p.failures(), [(MARK + ', cleared', p.failure()[1] + '\n\nCleared: the local driver started '
                                                                       'it later.')])
        writes = len(p.github()['writes'])
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(len(p.github()['writes']), writes)

    def test_a_refused_wake_is_retried_reported_and_cleared(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm')[0], 0)
        code, out, _ = p.host('wake', REPO, 7, FAKE_DRIVER_MODE='refuse')
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s wake 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start', 'wake', 'wake', 'wake'])
        self.assertEqual(p.fleet_notes(), [STOPPED])
        self.assertEqual(p.failures(), [p.failure('wake')])
        self.assertEqual(p.host('wake', REPO, 7, FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])

    def test_a_stop_is_never_retried(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm')[0], 0)
        code, out, _ = p.host('stop', REPO, 7, FAKE_DRIVER_MODE='refuse')
        self.assertEqual((code, out), (1, 'refused: the synthetic harness is not signed in; next: ' + NEXT))
        self.assertEqual([c['command'] for c in p.calls()], ['start', 'stop'])
        self.assertEqual(p.github()['writes'], [])

    def test_a_credential_or_private_id_in_the_drivers_text_never_reaches_the_ticket(self):
        secret = 'synthetic-secret-value-0123'
        token, thread = 'gh' + 'p_synthetic0123456789abcdef', 'thr' + '_synthetic1'  # no literal in the diff
        leaks = {'a token': 'export token=%s and retry' % token,
                 'a thread id': 'resume %s by hand' % thread, 'a machine path': 'edit /srv/synthetic/driver.conf',
                 'a secret value': 'use %s to sign in' % secret,
                 # R3 of the re-check at 004afb6: a URL's user info, password or not, from the driver's own config.
                 'a URL password': 'sign in at https://svc-account:made-up-pass-42@driver.example.invalid/login',
                 'a URL user': 'open ssh://made-up-user@driver.example.invalid to sign in',
                 # The decision on R3: a schemeless endpoint, as libcurl guesses its protocol.
                 'a schemeless URL password': 'set the endpoint to svc:made-up-pass-43@driver.example.invalid/api'}
        for name, text in leaks.items():
            with self.subTest(name):
                p = Project(self)
                code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', FAKE_DRIVER_NEXT=text,
                                      SYNTHETIC_API_TOKEN=secret)
                world = json.dumps(p.github())
                for part in (token, thread, '/srv/', secret, 'made-up-pass-42', 'made-up-user', 'made-up-pass-43'):
                    self.assertNotIn(part, world)  # the ticket first: the public boundary
                withheld = 'withheld, as it held a credential, a private id or a machine path; run the driver by hand'
                self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s'
                                               % (STOPPED, withheld)))
                self.assertEqual(p.failures(), [p.failure()])
                self.assertEqual(p.driver_log()[0]['next'], text)  # the raw words, only in the owner's log

    def test_a_report_github_lost_is_written_by_the_next_failure(self):
        p = Project(self)
        p.fault(post='fail')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('%s: the local driver refused #7\'s start 3 times; next: %s; unknown: the ticket\'s '
                                       'report is incomplete (' % (STOPPED, NEXT)), out)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_a_lost_note_write_still_posts_the_failure_comment_in_the_same_run(self):
        # R1 of the review at 1f9c7f6: the note and the comment are written apart, so one failing never hides the other.
        p = Project(self)
        p.fault(post='fail')  # the first POST is the fleet note's
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')
        self.assertEqual(p.failures(), [p.failure()])
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(code, 1)
        self.assertTrue(out.startswith('%s: the local driver refused #7\'s start 3 times; next: %s; unknown: the ticket\'s '
                                       'report is incomplete (the fleet note was not written: ' % (STOPPED, NEXT)), out)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        self.assertEqual((p.fleet_notes(), len(p.failures())), ([STOPPED], 1))

    def test_a_clearing_github_lost_keeps_the_saved_run_and_the_next_success_clears(self):
        p = Project(self)
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse')[0], 1)
        p.fault(patch='fail')
        code, out, _ = p.host('start', REPO, 7, 'claude', 'm')
        self.assertEqual(code, 0)
        self.assertEqual(out.split('\n')[0], 'started #7 on local')
        self.assertTrue(out.split('\n')[1].startswith('unknown: the failure report on #7 was not cleared ('), out)
        self.assertEqual(p.saved()['runs'], {'7': {'host': 'local', 'run': 'local-run-7'}})
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])  # R1's cause on the clearing route: written apart
        self.assertEqual(p.host('wake', REPO, 7), (0, 'woke #7 on local', ''))
        self.assertEqual(p.fleet_notes(), [STOPPED, 'done'])
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])

    def test_no_fleet_identity_still_starts_retries_and_comments_but_writes_no_note(self):
        # J87 planner ruling, relayed by the fleet manager: unset identity skips only the fleet note, with a warning.
        p = Project(self)
        unset = dict(LAUNCH_FLEET_HARNESS='', LAUNCH_FLEET_MODEL='', LAUNCH_FLEET_SKILLS='')
        code, out, err = p.host('start', REPO, 7, 'claude', 'm', FAKE_DRIVER_MODE='refuse', **unset)
        self.assertEqual((code, out), (1, '%s: the local driver refused #7\'s start 3 times; next: %s' % (STOPPED, NEXT)))
        self.assertEqual([c['command'] for c in p.calls()], ['start'] * 3)
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(p.failures(), [p.failure()])
        self.assertEqual(err, 'host.py: warning: LAUNCH_FLEET_HARNESS, LAUNCH_FLEET_MODEL, LAUNCH_FLEET_SKILLS '
                              'unset, so the fleet status note was not written')
        self.assertEqual(p.host('start', REPO, 7, 'claude', 'm', **unset)[:2], (0, 'started #7 on local'))
        self.assertEqual([first for first, _ in p.failures()], [MARK + ', cleared'])
        self.assertEqual(p.fleet_notes(), [])
        self.assertEqual(p.host('wake', REPO, 7, LAUNCH_FLEET_MODEL=''), (0, 'woke #7 on local', ''))

if __name__ == '__main__':
    unittest.main()
