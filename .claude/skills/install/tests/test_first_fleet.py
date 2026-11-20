#!/usr/bin/env python3
"""Portable first-fleet journey from OpenWiz's synthetic onboarding suite.

Replay the conversation against the packaged install skill, its helper and
the real launch-fleet frontier. The fakes record external commands and refuse
anything outside the fixture; setup inputs are synthetic persisted records.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest

SKILL_DIR = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / 'fixtures'
SKILL = SKILL_DIR / 'SKILL.md'
HELPER = SKILL_DIR / 'scripts/first_fleet.py'
FAKE_GH = FIXTURES / 'fake_gh.py'
REVISION = SKILL_DIR.parent / 'to-tickets/revision.sh'
JOURNEY = json.loads((FIXTURES / 'first-fleet.json').read_text())
NOW = 1793534400  # 2026-11-01T12:00:00Z, the synthetic clock fleet.sh reads
REPO = JOURNEY['repo']
CODEX = ('codex', 'syn-codex-model-01', 'high')
CLAUDE = ('claude-code', 'syn-claude-model-01', 'high')


def table(title, agent):
    return ('## %s\n\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n'
            '| Harness | Synthetic | `--provider %s` |\n| Model | Synthetic | `--model %s` |\n'
            '| Effort | Synthetic | `--reasoning-level %s` |\n\nSource: synthetic.\n\n' % (title, *agent))


def fleet_md(builder=CODEX, small=CODEX, for_gpt=CLAUDE, for_claude=CODEX):
    return ('# Fleet settings\n\nSynthetic settings.\n\n' + table('Builder', builder)
            + table('Builder for small tickets', small) + table('Reviewer for Claude-built', for_claude)
            + table('Reviewer for GPT-built', for_gpt) + '## CI checks\n\n'
            '| Check | Runs | Required on |\n| --- | --- | --- |\n| `build` | 1 | `main` |\n\n'
            'Source: synthetic.\n\n## Standing merge rules\n\n'
            '| Pull request | Review | Merged by, and when |\n| --- | --- | --- |\n| `not-a-check` | none | synthetic |\n\n'
            '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `synthetic-factory[bot]` |\n')


FILES = {
    'docs/agents/fleet.md': fleet_md(),
    'docs/agents/triage-labels.md': (
        '# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
        '| `needs-triage` | `needs-triage` | Synthetic |\n| `needs-info` | `needs-info` | Synthetic |\n'
        '| `ready-for-agent` | `ready-for-agent` | Synthetic |\n| `ready-for-human` | `ready-for-human` | Synthetic |\n'
        '| `wontfix` | `wontfix` | Synthetic |\n'),
}


def skill_steps():
    """The journey's step names, in order, from the packaged skill's numbered sections."""
    explain, _, branch = SKILL.read_text().partition('## 5. First fleet\n')
    names = re.findall(r'^## 4\. (Explain)$', explain, re.M)
    names.extend(re.findall(r'^### [0-9]+\. (.+)$', branch.partition('\n## ')[0], re.M))
    return [name.split()[-1].lower() for name in names]


def answers(turns):
    out = {}
    for turn in turns:
        out.update(turn.get('answers', {}))
    return out


def setup_state(identity='personal_login', brain='in_repository', overrides=None, revision=3, at=None,
                repository=REPO, settings=CODEX):
    """Synthetic setup record with the fields emitted for this selection."""
    at = int(time.time() * 1000) if at is None else at
    value = {'schema': 'openwiz.setup-state.v1', 'revision': revision,
             'checks': {'started': 4, 'committed': 4}, 'app': None, 'operations': []}
    value['project'] = {'repository': repository, 'project': 'prj_synthetic', 'operator': 'synthetic-owner',
                        'service_issue': 7, 'answer_thread': 'thr_synthetic_answer', 'harness': settings[0],
                        'model': settings[1], 'effort': settings[2], 'runtime': None}
    codes = {'cloudroom': 'cloudroom_login_verified', 'harness': 'harness_listed',
             'personal_github': 'identity_verified', 'project': 'project_verified', 'github_app': 'app_missing'}
    if identity == 'personal_login':
        value['identity'] = {'selected': 'personal_login', 'app_choice': 'skip', 'acting_login': 'synthetic-owner',
                             'repository': repository}
    elif identity == 'app':
        value['identity'] = {'selected': 'app', 'app_choice': 'create', 'acting_login': None, 'repository': repository}
        codes['github_app'] = 'app_verified'
    codes.update(overrides or {})
    value['observations'] = {k: {'code': c, 'revision': revision, 'at': at} for k, c in codes.items() if c}
    if brain == 'in_repository':
        value['brain'] = {'location': 'in_repository', 'code_repository': repository, 'code_visibility': 'private',
                          'brain_repository': repository, 'brain_visibility': {'known': 'private'},
                          'visibility_basis': 'github_repository_read', 'folder': '.openwiz/brain',
                          'setting': 'brain_location', 'decision_repositories': None}
    elif brain == 'companion':
        home = repository + '-brain'
        value['brain'] = {'location': 'companion', 'code_repository': repository, 'code_visibility': 'public',
                          'brain_repository': home, 'brain_visibility': {'known': 'private'},
                          'visibility_basis': 'github_repository_read', 'folder': '.openwiz/brain',
                          'setting': 'brain_location',
                          'decision_repositories': {'public': dict(zip(('owner', 'name'), repository.split('/'))),
                                                    'private': dict(zip(('owner', 'name'), home.split('/')))}}
    elif brain == 'other':
        value['brain'] = dict(setup_state(brain='in_repository', repository='synthetic-owner/synthetic-other')['brain'])
    return value


def demo_repository(name=REPO, visibility='private', branches=None):
    """One repository in the synthetic GitHub world."""
    owner, short = name.split('/')
    return {'full_name': name, 'private': visibility == 'private', 'visibility': visibility, 'default_branch': 'main',
            'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'}, 'description': None,
            'homepage': None, 'labels': [], 'pulls': [], 'branches': branches or {}}


def github(repos=(), **switches):
    """Synthetic GitHub state for the demo repository."""
    world = {'user': {'login': 'synthetic-owner', 'type': 'User'}, 'faults': [], 'log': [], 'create': 'ok',
             'repos': {r['full_name'].lower(): r for r in repos}}
    world.update(switches)
    return json.dumps(world)


class Journey:
    """One replay: a private folder with its state, fakes and synthetic GitHub."""

    def __init__(self, case):
        self.dir = Path(tempfile.mkdtemp(prefix='onboard-'))
        case.addCleanup(shutil.rmtree, self.dir, True)
        (self.dir / 'bin').mkdir()
        (self.dir / 'private').mkdir(mode=0o700)
        self.state = self.dir / 'private/onboard.json'
        self.options = self.dir / 'private/models.json'
        self.options.write_text(json.dumps(JOURNEY['options']))
        self.setup_dir = self.dir / 'openwiz-state'
        self.world_path = self.dir / 'world.json'
        self.script = self.dir / 'openwiz-script.json'
        self.log = self.dir / 'openwiz.log'
        self.room_script = self.dir / 'room-script.json'
        self.room_log = self.dir / 'room.log'
        self.openwiz = self.dir / 'bin/openwiz'
        self.openwiz.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, FIXTURES / 'fake_openwiz.py'))
        gh = self.dir / 'bin/gh'
        gh.write_text('#!/bin/sh\nexec "%s" -I -S "%s" "$@"\n' % (sys.executable, FAKE_GH))
        room = self.dir / 'bin/room-cli'
        room.write_text('#!/bin/sh\nexec "%s" -I "%s" "$@"\n' % (sys.executable, FIXTURES / 'fake_room_cli.py'))
        self.repos = self.dir / 'repos.json'
        self.repos.write_text(github())
        self.created_log = self.dir / 'gh-create.log'
        for path in (self.openwiz, gh, room):
            path.chmod(0o755)
        self.world = {'repo': JOURNEY['repo'], 'default': 'main', 'files': dict(FILES), 'issues': [], 'pulls': []}
        self.save_world()
        self.room_script.write_text('{}')
        self.approval = None
        self.calls = []
        self.extra_env = {}
        said = answers(JOURNEY['turns'])
        self.settings = {k: said[k] for k in ('harness', 'model', 'effort')}

    def env(self):
        env = {k: v for k, v in os.environ.items() if k in ('HOME', 'LANG', 'LC_ALL', 'TMPDIR')}
        env.update(PATH='%s:/usr/bin:/bin' % (self.dir / 'bin'), GH_REPO=self.world['repo'],
                   FAKE_GH_WORLD=str(self.world_path), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   LAUNCH_FLEET_NOW=str(NOW), LAUNCH_FLEET_CACHE=str(self.dir / 'cache'),
                   FAKE_OPENWIZ_SCRIPT=str(self.script), FAKE_OPENWIZ_LOG=str(self.log),
                   FAKE_ROOM_SCRIPT=str(self.room_script), FAKE_ROOM_LOG=str(self.room_log),
                   FAKE_GH_REPOS=str(self.repos), FAKE_GH_CREATE_LOG=str(self.created_log), **self.extra_env)
        return env

    def save_world(self):
        self.world_path.write_text(json.dumps(self.world))

    def write_setup(self, value):
        folder = self.setup_dir / 'setup'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.setup_dir.chmod(0o700)
        path = folder / 'state.json'
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def write_config(self, value):
        """The private service settings (service/config.json) beside the setup store."""
        folder = self.setup_dir / 'service'
        folder.mkdir(parents=True, mode=0o700, exist_ok=True)
        (folder / 'config.json').write_text(json.dumps(value))
        (folder / 'config.json').chmod(0o600)

    def plan(self, plan):
        spec = plan['spec']
        self.spec = spec['number']
        self.tickets = plan['tickets']
        self.world['issues'] = [{'number': spec['number'], 'title': spec['title'], 'state': 'OPEN', 'parent': None,
                                 'labels': [], 'body': spec['body'], 'comments': []}]
        for t in plan['tickets']:
            self.world['issues'].append({
                'number': t['number'], 'title': t['title'], 'state': 'OPEN', 'parent': spec['number'],
                'labels': ['ready-for-agent'], 'blockedBy': t['blockers'],
                'body': '## What to build\n\n%s.\n' % t['title'], 'comments': []})
        self.save_world()

    def approve(self, spec=None, tickets=None, comment=90001):
        """to-tickets's approval record, with the fingerprint revision.sh gives the plan now."""
        spec, tickets = spec or self.spec, tickets or self.tickets
        out = subprocess.run(['sh', str(REVISION), str(spec)], env=self.env(), capture_output=True, check=True)
        fingerprint = hashlib.sha256(out.stdout).hexdigest()
        rows = '\n'.join('| #%d | %s | %s | ready-for-agent |' % (
            t['number'], t['title'], ', '.join('#%d' % b for b in t['blockers']) or 'none') for t in tickets)
        body = ('**Plan graph approved by Robin, 2026-11-01, revision 1:** approved the synthetic plan.\n'
                'Private record: https://github.com/jparker2006/ClosedWiz/issues/1#issuecomment-1\n\n'
                '| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n%s\n\nFingerprint: `%s`' % (rows, fingerprint))
        issue = next(i for i in self.world['issues'] if i['number'] == spec)
        issue['comments'].append({'id': comment, 'at': '2026-11-01T10:00:00Z', 'body': body})
        if spec == self.spec:
            self.approval = {'comment': comment, 'revision': 1, 'fingerprint': fingerprint}
        self.save_world()

    def fleet_record(self):
        """The fleet thread's first-wake record on the spec, as launch-fleet writes it."""
        self.world['issues'][0]['comments'].append(
            {'id': 90002, 'at': '2026-11-01T12:05:00Z', 'body': 'launch-fleet: fleet active, loop fleet-%d' % self.spec})
        self.save_world()

    def fleet_view(self, states):
        counts = {k: 0 for k in ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')}
        for s in states:
            counts[s] += 1
        counts.update(tickets=len(states), unknown=0)
        return {'schema': 'openwiz.fleet.v1', 'sources': {}, 'reads': [], 'coverage': {}, 'freshness': {},
                'data': {'view': 'fleet', 'repository': 'r0', 'projects': 'r1', 'threads': 'r2',
                         'fleet': {'spec': self.spec, 'issue': 'r3', 'tickets': 'r4', 'progress': {'known': counts}},
                         'tickets': [{'number': t['number'], 'state': {'known': s}} for t, s in zip(self.tickets, states)],
                         'blockers': [], 'needs_you': {'known': []}, 'unplaced': {'known': []}}}

    def queue(self, script):
        """The installed openwiz's next answers (its fleet view)."""
        self.script.write_text(json.dumps(script))

    def rules(self):
        """The builder and reviewer tables of the world's fleet settings, as the launch reads them."""
        text = self.world['files']['docs/agents/fleet.md']
        found = {}
        for title, key in (('Builder', 'builder'), ('Builder for small tickets', 'builder_small'),
                           ('Reviewer for Claude-built', 'reviewer_claude'), ('Reviewer for GPT-built', 'reviewer_gpt')):
            body = text.split('## %s\n' % title, 1)[1].split('\n## ', 1)[0]
            found[key] = {k: re.search(r'`--%s ([^`\s]+)`' % f, body)[1]
                          for k, f in (('harness', 'provider'), ('model', 'model'), ('effort', 'reasoning-level'))}
        return found

    def helper(self, args):
        argv = [sys.executable, '-I', str(HELPER), *args, '--state', str(self.state)]
        if args[0] in ('continue', 'decisions'):
            argv += ['--setup-state', str(self.setup_dir)]
        if args[0] == 'choose':
            argv += ['--options', str(self.options)]
        if args[0] == 'progress':
            argv += ['--openwiz', str(self.openwiz)]
        result = subprocess.run(argv, env=self.env(), capture_output=True, text=True, cwd=self.dir, timeout=120)
        self.calls.append((args, result))
        return result

    def gh_creates(self):
        """The creation and read-back calls, as the fake gh logged them."""
        if not self.created_log.exists():
            return []
        return [json.loads(line)[:2] for line in self.created_log.read_text().splitlines()]

    def logged(self):
        """Every installed openwiz call, as the fake logged it."""
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def spawns(self):
        """Every room-cli call, as the fake logged it."""
        if not self.room_log.exists():
            return []
        return [json.loads(line) for line in self.room_log.read_text().splitlines()]

    def confirmation(self):
        """The confirmation the latest preview printed: what the user said yes to."""
        for args, result in reversed(self.calls):
            found = re.findall(r'^Confirmation: ([0-9a-f]{64})$', result.stdout, re.M)
            if found:
                return found[-1]
        return '0' * 64

    def tool(self, turn):
        """Run one recorded tool step, answering the fakes as the turn records."""
        args = [self.confirmation() if a == '@preview' else a for a in turn['tool']]
        self.queue({'fleet': [{'exit': 0, 'stdout': self.fleet_view(turn['progress'])}]} if 'progress' in turn else {})
        self.room_script.write_text(json.dumps(
            {'spawn': [{'exit': turn['spawn'], 'stdout': ''}]} if 'spawn' in turn else {}))
        return self.helper(args)

    def replay(self, until=None):
        """Every turn of the recorded journey, in order, up to step `until` (exclusive)."""
        results = []
        for turn in JOURNEY['turns']:
            if until is not None and turn['step'] == until:
                break
            if 'plan' in turn:
                self.plan(turn['plan'])
            elif turn.get('approve'):
                self.approve()
            elif 'setup' in turn:
                self.write_setup(setup_state(turn['setup'], repository=JOURNEY['repo'],
                                             settings=tuple(self.settings[k] for k in ('harness', 'model', 'effort'))))
            elif 'tool' in turn:
                results.append((turn, self.tool(turn)))
        return results


YES = {'tool': ['launch', '--spec', '900', '--yes', '--confirm', '@preview'], 'spawn': 0}
PREVIEW = {'tool': ['launch', '--spec', '900']}


class RecordedJourney(unittest.TestCase):
    def test_the_conversation_follows_the_packaged_skill(self):
        steps = skill_steps()
        self.assertEqual(steps, ['explain', 'project', 'connect', 'grill', 'agents', 'plan', 'launch', 'watch'])
        seen = [turn['step'] for turn in JOURNEY['turns']]
        self.assertEqual(sorted(set(seen), key=steps.index), steps, 'every step, and only the skill\'s')
        self.assertEqual(seen, sorted(seen, key=steps.index), 'in the skill\'s order')

    def test_every_effect_follows_its_yes_and_every_choice_is_the_users_once(self):
        # #636: the harness, model and effort answered during setup are reused,
        # never asked twice; the agent location is its own answer.
        turns = JOURNEY['turns']
        permitted, asked = set(), []
        for i, turn in enumerate(turns):
            permitted |= set(turn.get('permits', []))
            asked += list(turn.get('answers', {}))
            if turn.get('tool', [None])[0] == 'create-repo' and '--yes' in turn['tool']:
                self.assertIn('create_repository', permitted, 'repository created only after a yes')
            if turn.get('tool', [None])[:2] == ['launch', '--spec'] and '--yes' in turn['tool']:
                self.assertIn('start_cloud_agents', permitted, 'agents start only after a yes')
            if turn.get('tool', [None])[0] == 'choose':
                self.assertEqual(turn['tool'], ['choose', '--from-setup', '--agents', answers(turns[:i])['agents']])
        self.assertEqual(len(asked), len(set(asked)), 'no choice is asked twice')
        self.assertEqual(answers(turns)['agents'], 'cloud')
        self.assertNotIn('engine', json.dumps(turns).lower(), 'no engine question or effect')

    def test_the_plan_is_this_grills_small_first_fleet(self):
        plan = next(t['plan'] for t in JOURNEY['turns'] if 'plan' in t)
        self.assertTrue(4 <= len(plan['tickets']) <= 7)
        start = [t['number'] for t in plan['tickets'] if not t['blockers']]
        self.assertGreaterEqual(len(start), 2, 'several start at once')
        # No prewritten plan ships with the skill: none of this plan's titles,
        # and no ticket table, appear anywhere in the skill's runtime material.
        packaged = ''.join(path.read_text() for path in SKILL_DIR.rglob('*')
                           if path.is_file() and path.suffix in {'.md', '.py', '.yaml'}
                           and path.relative_to(SKILL_DIR).parts[0] not in {'tests', 'evidence'})
        for ticket in plan['tickets']:
            self.assertNotIn(ticket['title'].split(': ', 1)[1], packaged)
        self.assertNotIn('| Ticket |', packaged)


class Continuation(unittest.TestCase):
    """#636: onboarding continues from install's verified setup and init, never
    from a guess. Catches a fabricated, stale or unselected identity or brain
    being carried into the first fleet."""

    def carried(self, state):
        j = Journey(self)
        if state is not None:
            j.write_setup(state)
        return j, j.helper(['continue', '--explained'])

    def test_only_current_verified_setup_and_a_brain_are_carried(self):
        stale = int(time.time() * 1000) - 2 * 60 * 60 * 1000
        app_unverified = setup_state('app', overrides={'github_app': 'app_missing'})
        old_generation = setup_state()
        old_generation['observations']['personal_github']['revision'] = 2
        cases = {
            'no setup yet': (None, 5, 'Setup has not run'),
            'no project prepared': (dict(setup_state(), project=None, identity=None, brain=None), 5, 'no prepared project'),
            'login not verified': (setup_state(overrides={'personal_github': 'identity_no_push'}), 5,
                                   'Personal GitHub: not verified (identity_no_push)'),
            'login checked for another selection': (old_generation, 5, 'Personal GitHub: unknown'),
            'every check out of date': (setup_state(at=stale), 5, 'CloudRoom: unknown'),
            'App chosen but not verified': (app_unverified, 5, 'OpenWiz GitHub App: not verified (app_missing)'),
            'no identity choice: the App rule': (setup_state(identity=None), 5, 'OpenWiz GitHub App'),
            'no brain': (setup_state(brain=None), 5, 'Private brain: missing (run openwiz init'),
            'a brain for another repository': (setup_state(brain='other'), 5, 'Private brain: missing'),
            'harness refused': (setup_state(overrides={'harness': 'harness_unavailable'}), 5, 'Agent harness'),
            'unreadable store': ('{"schema": "openwiz.setup-state.v1", "revision": 1, "revision": 2}', 10, 'unreadable'),
            'a project without its CloudRoom project': (json.dumps(dict(setup_state(), project=dict(
                setup_state()['project'], project=None))), 10, 'unreadable'),
        }
        for name, (state, code, words) in cases.items():
            with self.subTest(name):
                j = Journey(self)
                if isinstance(state, str):
                    j.write_setup({})
                    (j.setup_dir / 'setup/state.json').write_text(state)
                elif state is not None:
                    j.write_setup(state)
                result = j.helper(['continue'])
                self.assertEqual(result.returncode, code, result.stdout)
                self.assertIn(words, result.stdout)
                self.assertIn('nothing started', result.stdout)
                self.assertFalse(j.state.exists() and 'setup' in json.loads(j.state.read_text()), 'nothing carried')

    def test_both_identities_carry_the_same_repository_brain_and_settings(self):
        for identity, acting in (('personal_login', 'synthetic-owner, your personal GitHub login (the App is skipped)'),
                                 ('app', 'your OpenWiz GitHub App')):
            with self.subTest(identity):
                j, result = self.carried(setup_state(identity))
                self.assertEqual(result.returncode, 0, result.stdout)
                for line in ('repository %s, CloudRoom project prj_synthetic' % REPO, 'Acting identity: %s.' % acting,
                             'Private brain: %s (in repository)' % REPO, 'harness listed by CloudRoom; its login is not proven',
                             'Next: the grill (the explanation is done)'):
                    self.assertIn(line, result.stdout)
                saved = json.loads(j.state.read_text())
                self.assertEqual((saved['repo'], saved['setup']['settings']),
                                 (REPO, {'harness': 'codex', 'model': 'syn-codex-model-01', 'effort': 'high'}))

    def test_the_carried_repository_is_the_only_one(self):
        j, result = self.carried(setup_state())
        self.assertEqual(result.returncode, 0, result.stdout)
        other = 'synthetic-owner/synthetic-other'
        self.assertEqual(j.helper(['create-repo', '--repo', other, '--yes']).returncode, 5)
        self.assertEqual(j.helper(['spec', '--spec', '900', '--repo', other]).returncode, 5)
        self.assertEqual(j.gh_creates(), [], 'no second repository is read or created')
        j.write_setup(setup_state(repository=other))
        moved = j.helper(['continue'])
        self.assertEqual(moved.returncode, 5, moved.stdout)
        self.assertIn('setup selected %s' % other, moved.stdout)

    def test_a_failed_refresh_withdraws_the_carried_setup_but_keeps_the_choices(self):
        # Review R4: catches an old carried setup staying eligible after setup refuses.
        j, result = self.carried(setup_state())
        self.assertEqual(j.helper(['choose', '--from-setup', '--agents', 'cloud']).returncode, 0)
        j.write_setup(setup_state(overrides={'personal_github': 'identity_no_push'}))
        refused = j.helper(['continue'])
        self.assertEqual(refused.returncode, 5, refused.stdout)
        saved = json.loads(j.state.read_text())
        self.assertNotIn('setup', saved, 'the refused refresh withdraws the carried setup')
        self.assertEqual(saved['choices']['agents'], 'cloud', "the owner's choices stay")

    def test_a_companion_brain_reaches_decisions_only_through_its_configured_pair(self):
        # Review R5: catches a public repository's private companion carried while
        # Decisions' existing repository-pair setting (service/config.json) does not name it.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, config, code in (('no settings file', None, 5),
                                   ('another pair', {'decision_repositories': {'public': pair['public'],
                                                     'private': {'owner': 'synthetic-owner', 'name': 'elsewhere'}}}, 5),
                                   ('the companion pair', {'decision_repositories': pair}, 0)):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                if config is not None:
                    j.write_config(config)
                result = j.helper(['continue'])
                self.assertEqual(result.returncode, code, result.stdout)
                if code:
                    self.assertIn('Decisions repository pair', result.stdout)
                else:
                    self.assertIn('Private brain: %s-brain (companion)' % REPO, result.stdout)

    def test_the_decisions_pair_is_written_once_and_only_on_yes(self):
        # Review R5 (ruling: option A): catches a writer that changes or drops
        # another settings key, writes on a preview, or rewrites on a second run.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, existing in (('no settings file', None),
                               ('an existing settings file', {'schema': 'synthetic', 'server': {'port': 7370},
                                                              'decision_repositories': {'public': pair['public'],
                                                              'private': {'owner': 'synthetic-owner', 'name': 'old'}}})):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                path = j.setup_dir / 'service/config.json'
                if existing is not None:
                    j.write_config(existing)
                before = path.read_bytes() if path.exists() else None
                shown = j.helper(['decisions'])
                self.assertEqual(shown.returncode, 12, shown.stdout)
                self.assertIn('public %s, private %s-brain' % (REPO, REPO), shown.stdout)
                self.assertEqual(path.read_bytes() if path.exists() else None, before, 'a preview writes nothing')
                done = j.helper(['decisions', '--yes'])
                self.assertEqual(done.returncode, 0, done.stdout)
                written = json.loads(path.read_text())
                kept = {k: v for k, v in (existing or {}).items() if k != 'decision_repositories'}
                self.assertEqual(written, dict(kept, decision_repositories=pair), 'only that key changes')
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                first = (path.read_bytes(), path.stat().st_mtime_ns)
                again = j.helper(['decisions', '--yes'])
                self.assertEqual(again.returncode, 0, again.stdout)
                self.assertIn('already reads', again.stdout)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), first, 'a second run changes nothing')
                self.assertEqual(j.helper(['continue']).returncode, 0, 'the companion is then carried')
        private = Journey(self)
        private.write_setup(setup_state())
        self.assertEqual(private.helper(['decisions', '--yes']).returncode, 5, 'no companion, nothing to connect')
        self.assertFalse((private.setup_dir / 'service/config.json').exists())

    def test_a_decisions_write_cut_short_before_its_replace_can_be_confirmed_again(self):
        # Review R6: catches a staging file left by an interrupted write blocking
        # every later confirmation, so the companion could never be connected.
        pair = setup_state(brain='companion')['brain']['decision_repositories']
        for name, existing in (('no settings file', None),
                               ('an existing settings file', {'schema': 'synthetic', 'server': {'port': 7370}})):
            with self.subTest(name):
                j = Journey(self)
                j.write_setup(setup_state(brain='companion'))
                path = j.setup_dir / 'service/config.json'
                if existing is not None:
                    j.write_config(existing)
                before = path.read_bytes() if path.exists() else None
                # The real helper, its process killed (SIGKILL) just before its final replace.
                cut = subprocess.run(
                    [sys.executable, '-I', '-c', 'import os, runpy, signal, sys\n'
                     'os.replace = lambda *a: os.kill(os.getpid(), signal.SIGKILL)\n'
                     'sys.argv = sys.argv[1:]\nrunpy.run_path(sys.argv[0], run_name="__main__")',
                     str(HELPER), 'decisions', '--yes', '--state', str(j.state), '--setup-state', str(j.setup_dir)],
                    env=j.env(), capture_output=True, text=True, cwd=j.dir, timeout=60)
                self.assertEqual(cut.returncode, -9, cut.stdout + cut.stderr)
                self.assertEqual(path.read_bytes() if path.exists() else None, before, 'the cut write changed nothing')
                self.assertEqual(j.helper(['decisions']).returncode, 12)
                done = j.helper(['decisions', '--yes'])
                self.assertEqual(done.returncode, 0, done.stdout)
                self.assertEqual(json.loads(path.read_text()), dict(existing or {}, decision_repositories=pair),
                                 'connected, every other key kept')
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                first = (path.read_bytes(), path.stat().st_mtime_ns)
                self.assertEqual(j.helper(['decisions', '--yes']).returncode, 0)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), first, 'a second run changes nothing')
                self.assertEqual(j.helper(['continue']).returncode, 0, 'the companion is then carried')

    def test_the_prepared_agents_are_reused_only_when_offered(self):
        j = Journey(self)
        self.assertEqual(j.helper(['choose', '--from-setup', '--agents', 'cloud']).returncode, 5, 'nothing carried yet')
        j.write_setup(setup_state(settings=('codex', 'syn-codex-model-01', 'xhigh')))
        self.assertEqual(j.helper(['continue']).returncode, 0)
        unoffered = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(unoffered.returncode, 5, unoffered.stdout)
        both = j.helper(['choose', '--from-setup', '--harness', 'codex', '--model', 'syn-codex-model-01',
                         '--effort', 'high', '--agents', 'cloud'])
        self.assertEqual(both.returncode, 2, 'a carried choice is never overridden in the same call')
        self.assertNotIn('choices', json.loads(j.state.read_text()))


class Launch(unittest.TestCase):
    def test_the_whole_journey_starts_one_fleet_thread_through_launch_fleet(self):
        # #636 (J87 Q1): the first fleet starts as launch-fleet starts every
        # fleet; catches any engine or tick call, a second start, or a start
        # with other settings, project or brief than the carried ones.
        j = Journey(self)
        results = j.replay()
        for turn, result in results:
            self.assertEqual(result.returncode, turn['exit'], (turn['tool'], result.stdout, result.stderr))
        self.assertEqual([c['form'] for c in j.logged()], ['fleet'], 'the installed openwiz only reads progress')
        spawns = j.spawns()
        self.assertEqual(len(spawns), 1, 'one start')
        argv = spawns[0]
        self.assertEqual(argv[:3], ['thread', 'spawn', '--parent-self'])
        rest = argv[3:]
        flags = dict(zip(rest[0::2], rest[1::2]))
        self.assertEqual({k: flags[k] for k in ('--project', '--machine', '--provider', '--model', '--reasoning-level', '--title')},
                         {'--project': 'prj_synthetic', '--machine': 'cloud', '--provider': 'codex',
                          '--model': 'syn-codex-model-01', '--reasoning-level': 'high',
                          '--title': 'Fleet #900: 0.1.0 spec: sheep herding game'})
        for words in ('You are the fleet thread for spec #900 of %s.' % REPO, 'Use the launch-fleet skill.',
                      'do its Fleet threads section, first wake.'):
            self.assertIn(words, flags['--prompt'])
        preview = next(r for turn, r in results if turn['tool'] == ['launch', '--spec', '900']).stdout
        for line in ('1 fleet thread, codex syn-codex-model-01 high', 'checks spec #900 every 10 minutes',
                     'Then 3 builders', '#901 S1: the field and its sheep', 'reviewed by claude-code syn-claude-model-01 high',
                     'CloudRoom project prj_synthetic', 'Cloud Credits: unknown'):
            self.assertIn(line, preview)
        watch = results[-1][1].stdout
        for line in ('Spec #900 has no fleet record yet', '#901 building', '#904 blocked',
                     '5 tickets: 3 building, 2 blocked', 'Counts are progress, not a first merge'):
            self.assertIn(line, watch)
        self.assertEqual(stat.S_IMODE(j.state.stat().st_mode), 0o600, 'owner-only state')

    def test_repeat_and_reload_never_start_again(self):
        j = Journey(self)
        j.replay()
        again = j.tool(YES)
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn('already started', again.stdout)
        self.assertEqual(len(j.spawns()), 1)

    def test_an_uncertain_start_is_never_retried_and_settles_only_on_its_record(self):
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        first = j.tool(dict(YES, spawn=1))
        self.assertEqual(first.returncode, 6, first.stdout)
        self.assertIn('uncertain', first.stdout)
        second = j.tool(YES)
        self.assertEqual(second.returncode, 6, second.stdout)
        self.assertIn('no fleet record yet', second.stdout)
        j.extra_env = {'FAKE_GH_COMMENTS_FAIL': '1'}
        unread = j.tool(YES)
        self.assertEqual(unread.returncode, 6, 'an unread record settles nothing')
        j.extra_env = {}
        j.fleet_record()
        third = j.tool(YES)
        self.assertEqual(third.returncode, 0, third.stdout)
        self.assertIn('has its fleet record', third.stdout)
        self.assertEqual(len(j.spawns()), 1, 'never a second start')

    def test_uncertain_launch_accepts_only_configured_record_authors(self):
        # Catches #1096 F1: outsider text settling an uncertain launch, or an
        # unread author policy/comment read being treated as a started fleet.
        # Earlier recovery tests supplied only the factory's own comment.
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(dict(YES, spawn=1)).returncode, 6)
        j.fleet_record()
        record = j.world['issues'][0]['comments'][-1]
        unresolved = j.state.read_text()
        settings = j.world['files']['docs/agents/fleet.md']
        for author in ('synthetic-outsider', None):
            with self.subTest(author=author):
                j.state.write_text(unresolved)
                record['author'] = author
                j.save_world()
                result = j.tool(YES)
                self.assertEqual(result.returncode, 6, result.stdout)
                self.assertIn('no fleet record yet', result.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'uncertain')
        record['author'] = 'SYNTHETIC-FACTORY[bot]'
        row = '| Record authors | `synthetic-factory[bot]` |'
        policies = {'unreadable': None, 'missing': settings.replace(row, ''),
                    'duplicate': settings.replace(row, row + '\n' + row),
                    'empty': settings.replace(row, '| Record authors | |'),
                    'malformed login': settings.replace(row, '| Record authors | `synthetic-factory[bot]`, invalid |'),
                    'extra cell': settings.replace(row, row + ' extra |')}
        for name, policy in policies.items():
            with self.subTest(policy=name):
                j.state.write_text(unresolved)
                if policy is None:
                    j.world['files'].pop('docs/agents/fleet.md', None)
                else:
                    j.world['files']['docs/agents/fleet.md'] = policy
                j.save_world()
                result = j.tool(YES)
                self.assertEqual(result.returncode, 6, result.stdout)
                self.assertIn('could not be read', result.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'uncertain')
        j.world['files']['docs/agents/fleet.md'] = settings
        j.save_world()
        j.state.write_text(unresolved)
        j.extra_env['FAKE_GH_COMMENTS_FAIL'] = '1'
        unread = j.tool(YES)
        self.assertEqual(unread.returncode, 6, unread.stdout)
        self.assertIn('could not be read', unread.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'uncertain')
        j.extra_env = {}
        # R2 catches an outsider's U+2028 inside JSON blocking a trusted record.
        j.world['issues'][0]['comments'].append(
            {'id': 90003, 'author': 'synthetic-outsider', 'body': 'Thanks!\u2028Looks good.'})
        for author in ('SYNTHETIC-FACTORY[bot]', 'Synthetic-Owner'):
            with self.subTest(trusted=author):
                # Both configured logins, including the fallback user, work
                # case-insensitively on an unresolved start.
                j.state.write_text(unresolved)
                record['author'] = author
                j.world['files']['docs/agents/fleet.md'] = settings.replace(
                    row, '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |')
                j.save_world()
                settled = j.tool(YES)
                self.assertEqual(settled.returncode, 0, settled.stdout)
                self.assertIn('has its fleet record', settled.stdout)
                self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'started')
        self.assertEqual(len(j.spawns()), 1, 'reconciliation never dispatches another fleet')

    def test_a_start_cut_short_before_its_outcome_settles_on_its_record(self):
        # Review R1: catches a start interrupted after the spawn and before its
        # outcome was saved staying pending for ever, even once its fleet record exists.
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        j.room_script.write_text(json.dumps({'spawn': [{'exit': 0, 'stdout': '', 'kill_caller': True}]}))
        cut = j.helper([*YES['tool'][:4], '--confirm', j.confirmation()])
        self.assertNotEqual(cut.returncode, 0)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'pending')
        waiting = j.tool(YES)
        self.assertEqual(waiting.returncode, 6, waiting.stdout)
        j.fleet_record()
        settled = j.tool(YES)
        self.assertEqual(settled.returncode, 0, settled.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'started')
        self.assertEqual(len(j.spawns()), 1, 'never a second start')

    def test_a_start_that_could_not_run_is_refused_and_previewed_again(self):
        # Review R2: catches a known no-dispatch (room-cli not found) recorded as
        # uncertain, which would block every later start.
        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        room = j.dir / 'bin/room-cli'
        moved = j.dir / 'room-cli.away'
        room.rename(moved)
        missing = j.tool(YES)
        self.assertEqual(missing.returncode, 5, missing.stdout)
        self.assertIn('nothing started', missing.stdout)
        self.assertEqual(json.loads(j.state.read_text())['launch']['state'], 'refused')
        moved.rename(room)
        stale = j.tool(YES)
        self.assertEqual(stale.returncode, 5, 'the old yes needs a fresh preview')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(YES).returncode, 0)
        self.assertEqual(len(j.spawns()), 1)

    def test_a_preview_is_void_once_setup_no_longer_verifies(self):
        # Review R4: catches an old preview starting a fleet after setup refuses a
        # prerequisite or its checks expire.
        stale = int(time.time() * 1000) - 2 * 60 * 60 * 1000
        for name, state in (('login lost push access', setup_state(overrides={'personal_github': 'identity_no_push'})),
                            ('checks expired', setup_state(at=stale))):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                self.assertEqual(j.tool(PREVIEW).returncode, 12)
                j.write_setup(state)
                result = j.tool(YES)
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('nothing started', result.stdout)
                self.assertEqual(j.spawns(), [])
                self.assertNotIn('setup', json.loads(j.state.read_text()), 'run continue again')

    def test_missing_or_stale_approval_starts_nothing(self):
        for change in ('missing', 'stale'):
            with self.subTest(change):
                j = Journey(self)
                j.replay(until='launch')
                if change == 'missing':
                    j.world['issues'][0]['comments'] = []
                else:
                    j.world['issues'][3]['body'] += 'A changed body.\n'
                j.save_world()
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertIn('nothing started', result.stdout)
                self.assertEqual(j.spawns(), [])

    def test_another_specs_frontier_is_not_this_fleets(self):
        # Catches a first fleet that would also start an approved ticket of
        # another spec in the same repository.
        j = Journey(self)
        j.replay(until='launch')
        other = {'number': 951, 'title': 'O1: another ticket', 'blockers': []}
        j.world['issues'] += [{'number': 950, 'title': 'Another spec', 'state': 'OPEN', 'parent': None, 'labels': [],
                               'body': 'Synthetic.\n', 'comments': []},
                              {'number': 951, 'title': other['title'], 'state': 'OPEN', 'parent': 950,
                               'labels': ['ready-for-agent'], 'blockedBy': [], 'body': 'Synthetic.\n', 'comments': []}]
        j.save_world()
        j.approve(spec=950, tickets=[other], comment=90009)
        shown = j.tool(PREVIEW)
        self.assertEqual(shown.returncode, 12, shown.stdout)
        self.assertIn('Then 3 builders', shown.stdout)
        self.assertNotIn('#951', shown.stdout)

    def test_the_yes_binds_the_preview_the_user_saw(self):
        # The user said yes to two starts; a third ticket becoming ready before
        # the yes runs must not start without a new preview and yes.
        j = Journey(self)
        j.replay(until='launch')
        j.world['issues'][1]['labels'] = ['ready-for-agent', 'held']
        j.save_world()
        shown = j.tool(PREVIEW)
        self.assertEqual(shown.returncode, 12, shown.stdout)
        self.assertIn('Then 2 builders', shown.stdout)
        j.world['issues'][1]['labels'] = ['ready-for-agent']
        j.save_world()
        shutil.rmtree(j.dir / 'cache', ignore_errors=True)
        result = j.tool(YES)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        self.assertIn('preview again', result.stdout)
        self.assertEqual(j.spawns(), [], 'no start of effects the user never saw')
        bare = j.tool(dict(YES, tool=['launch', '--spec', '900', '--yes']))
        self.assertEqual(bare.returncode, 2, 'a yes names the preview it answers')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(YES).returncode, 0)
        self.assertEqual(len(j.spawns()), 1)

    def test_every_builder_profile_the_fleet_can_use_is_the_users_choice(self):
        # Blocked tickets may later use the small-ticket builder; the reviewer
        # stays in the other model family.
        for name, text in (('small builder differs', fleet_md(small=CLAUDE)),
                           ('reviewer in the same family', fleet_md(for_gpt=CODEX)),
                           ('builder tables missing', fleet_md().replace('## Builder', '## Retired builder'))):
            with self.subTest(name):
                j = Journey(self)
                j.replay(until='launch')
                j.world['files']['docs/agents/fleet.md'] = text
                j.save_world()
                result = j.tool(PREVIEW)
                self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
                self.assertNotIn('Confirmation:', result.stdout)

    def test_without_carried_setup_local_agents_or_another_spec_nothing_starts(self):
        j = Journey(self)
        j.replay(until='launch')
        state = json.loads(j.state.read_text())
        j.state.write_text(json.dumps({k: v for k, v in state.items() if k != 'setup'}))
        uncarried = j.tool(PREVIEW)
        self.assertEqual(uncarried.returncode, 5, uncarried.stdout)
        self.assertIn('run continue first', uncarried.stdout)
        k = Journey(self)
        k.replay(until='launch')
        self.assertEqual(k.helper(['choose', '--from-setup', '--agents', 'local']).returncode, 0)
        local = k.tool(YES)
        self.assertEqual(local.returncode, 5, local.stdout)
        self.assertIn('Local', local.stdout)
        other = k.tool({'tool': ['launch', '--spec', '950']})
        self.assertEqual(other.returncode, 5, other.stdout)
        self.assertEqual(j.spawns() + k.spawns() + j.logged() + k.logged(), [], 'not even a read of the engine')

    def test_another_repository_never_runs_this_onboardings_launch(self):
        # The same state and issue numbers, resumed in another repository.
        j = Journey(self)
        j.replay(until='launch')
        j.world['repo'] = 'synthetic-owner/synthetic-other'
        j.save_world()
        for turn in (PREVIEW, YES, {'tool': ['progress', '--spec', '900'], 'progress': ['building'] * 5}):
            result = j.tool(turn)
            self.assertEqual(result.returncode, 5, (turn['tool'], result.stdout + result.stderr))
            self.assertIn(REPO, result.stdout)
        self.assertEqual(j.spawns() + j.logged(), [])

    def test_the_demo_repository_is_created_once_and_read_back(self):
        j = Journey(self)
        j.replay(until='connect')
        self.assertEqual(j.gh_creates(), [['repo', 'view'], ['repo', 'create'], ['repo', 'view']],
                         'checked absent, created once, read back')
        made = json.loads(j.repos.read_text())['repos']
        self.assertEqual((list(made), made[REPO.lower()]['private']), ([REPO.lower()], True))
        preview = next(r for a, r in j.calls if a[0] == 'create-repo' and '--yes' not in a)
        for words in ('private', REPO, 'your gh identity'):
            self.assertIn(words, preview.stdout)
        again = j.helper(['create-repo', '--repo', REPO, '--yes'])
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'a repeat only reads')

    def test_a_lost_create_is_read_before_any_retry(self):
        # lost: created but no answer, settled by the read-back; unread: the
        # read-back itself fails, so it stays uncertain and the next run reads
        # first; fail: nothing was created, so a later yes may create it.
        for create, fails, first, second, creates in (('lost', 0, 0, 0, 1), ('lost', 2, 6, 6, 1), ('fail', 0, 5, 0, 2)):
            with self.subTest(create, fails=fails):
                j = Journey(self)
                j.repos.write_text(github(create=create, fail_after_create=fails))
                yes = ['create-repo', '--repo', REPO, '--yes']
                if fails:
                    self.assertEqual(j.helper(yes).returncode, 6, j.calls[-1][1].stdout)
                    self.assertIn('uncertain', j.calls[-1][1].stdout)
                    self.assertEqual(j.helper(yes).returncode, 6, 'the next read fails too: still uncertain, no create')
                    self.assertEqual(j.helper(yes).returncode, 0, j.calls[-1][1].stdout)
                    self.assertEqual([c[1] for c in j.gh_creates()].count('create'), 1, 'read, never created twice')
                    continue
                self.assertEqual(j.helper(yes).returncode, first, j.calls[-1][1].stdout)
                state = json.loads(j.repos.read_text())
                j.repos.write_text(json.dumps(dict(state, create='ok', view_fails=0)))
                self.assertEqual(j.helper(yes).returncode, second, j.calls[-1][1].stdout)
                self.assertEqual([c[1] for c in j.gh_creates()].count('create'), creates)

    def test_an_existing_or_public_repository_is_never_taken_as_the_demo(self):
        j = Journey(self)
        j.repos.write_text(github([demo_repository(visibility='public')]))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO]).returncode, 12)
        result = j.helper(['create-repo', '--repo', REPO, '--yes'])
        self.assertEqual(result.returncode, 5, result.stdout)
        self.assertIn('already exists', result.stdout)
        self.assertNotIn(['repo', 'create'], j.gh_creates())

    def test_a_busy_state_file_is_refused(self):
        j = Journey(self)
        j.replay(until='launch')
        with open(str(j.state) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            busy = j.tool(YES)
        self.assertEqual(busy.returncode, 7, busy.stdout + busy.stderr)
        self.assertEqual(j.spawns() + j.logged(), [])



YES_DEMO = ['create-repo', '--repo', REPO, '--yes']


class DemoRepository(unittest.TestCase):
    """Read-back and ownership checks for the demo repository."""

    def world(self, j):
        return json.loads(j.repos.read_text())

    def writes(self, j):
        return [call for call in self.world(j)['log'] if call[0] != 'GET']

    def test_signed_out_demo_creation_refuses_with_a_sign_in_pointer(self):
        # Catches #1096 F2: the real demo command reaching repo creation before
        # GitHub sign-in, then failing with no usable onboarding next step.
        # Earlier demo cases always supplied a signed-in synthetic user.
        j = Journey(self)
        j.repos.write_text(github(signed_out=True))
        before = self.world(j)['repos']
        preview = j.helper(['create-repo', '--repo', REPO])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        result = j.helper(YES_DEMO)
        self.assertEqual(result.returncode, 5, result.stdout)
        for words in ('GitHub', 'sign-in', 'github_login.py sign-in', 'nothing created'):
            self.assertIn(words, result.stdout)
        self.assertEqual((self.world(j)['repos'], self.writes(j)), (before, []))
        self.assertNotIn(['repo', 'create'], j.gh_creates(), 'no creation attempted while signed out')
        self.assertFalse(j.state.exists(), 'no pending creation is saved for a refused sign-in')
        # Once sign-in is available, the same demo can be created and read
        # back; the refusal neither creates nor strands an operation.
        world = self.world(j)
        world['signed_out'] = False
        j.repos.write_text(json.dumps(world))
        created = j.helper(YES_DEMO)
        self.assertEqual(created.returncode, 0, created.stdout)
        self.assertIn('Created and read back', created.stdout)
        self.assertEqual(self.writes(j), [['POST', 'user/repos']])

    # Catches: a yes given to a preview that never said the repository gets
    # an initial README commit on its default branch, or a preview that writes.
    def test_the_preview_discloses_the_initial_commit_and_writes_nothing(self):
        j = Journey(self)
        preview = j.helper(['create-repo', '--repo', REPO])
        self.assertEqual(preview.returncode, 12, preview.stdout)
        for words in ('private', REPO, 'README.md', 'initial commit', 'default branch'):
            self.assertIn(words, preview.stdout)
        self.assertEqual((self.world(j)['repos'], self.writes(j)), ({}, []))

    # Catches: a created repository reported complete (and init started) while
    # its default branch or commit could not be read, or a retry that creates
    # a second repository or pushes its own seed commit.
    def test_an_unread_or_missing_default_branch_is_never_created(self):
        ref = 'repos/%s/git/ref/heads/main' % REPO
        for name, faults, first in (('ref read lost', [{'method': 'GET', 'path': ref, 'mode': 'drop', 'times': 1}], 6),
                                    ('ref read refused', [{'method': 'GET', 'path': ref, 'mode': 500, 'times': 1}], 6)):
            with self.subTest(name):
                j = Journey(self)
                j.repos.write_text(github(faults=faults))
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, first, result.stdout)
                self.assertNotIn('Created', result.stdout)
                again = j.helper(YES_DEMO)
                self.assertEqual(again.returncode, 0, again.stdout)
                self.assertIn('Created and read back', again.stdout)
                self.assertEqual(self.writes(j), [['POST', 'user/repos']], 'one create, no seed push, no other write')

    # Catches: an onboarding whose own repository exists without a default
    # branch (an interrupted or earlier empty create) being reported created,
    # retried, or seeded by a separate push.
    def test_its_own_repository_without_a_default_branch_stays_unresolved(self):
        for state, code in (('pending', 6), ('uncertain', 6), ('created', 5)):
            with self.subTest(state):
                j = Journey(self)
                j.repos.write_text(github([demo_repository()]))
                j.state.write_text(json.dumps({'created': {'repo': REPO, 'state': state}}))
                j.state.chmod(0o600)
                before = self.world(j)['repos']
                for _ in range(2):
                    result = j.helper(YES_DEMO)
                    self.assertEqual(result.returncode, code, result.stdout)
                    self.assertIn('default branch', result.stdout)
                    self.assertNotIn('Created and read back', result.stdout)
                self.assertEqual(self.world(j)['repos'], before, 'nothing created, seeded or pushed')
                self.assertEqual(self.writes(j), [])
                if state != 'created':
                    self.assertNotEqual(json.loads(j.state.read_text())['created']['state'], 'created')

    # Catches: someone else's repository, private or public, taken as the demo
    # or written to, and a repeat that rewrites the owner's later work.
    def test_existing_repositories_and_owner_work_are_never_written(self):
        owned = {'main': {'README.md': 'Owner work.\n', 'game.py': 'print(1)\n'}}
        for visibility in ('private', 'public'):
            with self.subTest(visibility):
                j = Journey(self)
                j.repos.write_text(github([demo_repository(visibility=visibility, branches=owned)]))
                before = self.world(j)['repos']
                result = j.helper(YES_DEMO)
                self.assertEqual(result.returncode, 5, result.stdout)
                self.assertIn('already exists', result.stdout)
                self.assertEqual((self.world(j)['repos'], self.writes(j)), (before, []))
        j = Journey(self)
        self.assertEqual(j.helper(YES_DEMO).returncode, 0, j.calls[-1][1].stdout)
        world = self.world(j)
        world['repos'][REPO.lower()]['branches'].setdefault('main', {})['game.py'] = 'print(1)\n'  # the owner's later commit
        j.repos.write_text(json.dumps(world))
        again = j.helper(YES_DEMO)
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.world(j)['repos'], world['repos'], 'a repeat only reads')
        self.assertEqual(self.writes(j), [['POST', 'user/repos']])


class Resume(unittest.TestCase):
    """#1183: a fresh session resumes the first fleet from the private state alone.
    `next` reads only that state and names the first unfinished step."""

    def next(self, j, *more):
        before = j.state.read_bytes() if j.state.exists() else None
        lock = Path(str(j.state) + '.lock')
        locked = lock.exists()
        calls = (j.gh_creates(), j.logged(), j.spawns())
        result = j.helper(['next', *more])
        self.assertEqual(lock.exists(), locked, 'next opens nothing for writing, not even a lock')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(j.state.read_bytes() if j.state.exists() else None, before, 'next never writes the state')
        self.assertEqual((j.gh_creates(), j.logged(), j.spawns()), calls, 'next runs no gh, openwiz or room-cli')
        return result.stdout

    def test_a_fresh_session_resumes_at_the_first_unfinished_step(self):
        # catches: a resumed journey that restarts from the top, or jumps past an
        # unfinished step (a grill before Connect is carried, a launch before the spec is recorded).
        j = Journey(self)
        seen = []
        for turn in JOURNEY['turns']:
            if not seen or seen[-1] != turn['step']:
                seen.append(turn['step'])
                expected = {'explain': 'project', 'agents': 'grill'}.get(turn['step'], turn['step'])
                self.assertEqual(self.next(j).splitlines()[0], 'Next: %s.' % expected, turn['step'])
            if 'plan' in turn:
                j.plan(turn['plan'])
            elif turn.get('approve'):
                j.approve()
            elif 'setup' in turn:
                j.write_setup(setup_state(turn['setup'], repository=REPO,
                                          settings=tuple(j.settings[k] for k in ('harness', 'model', 'effort'))))
            elif 'tool' in turn:
                j.tool(turn)
        self.assertIn('progress --spec 900', self.next(j))

    def test_an_interrupted_or_withdrawn_step_is_resumed_not_skipped(self):
        # catches: an uncertain create or start reported as done (inviting a second
        # effect), and a withdrawn setup skipped because later choices are saved.
        j = Journey(self)
        j.repos.write_text(github(create='lost', fail_after_create=2))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 6)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: project.')
        self.assertIn('create-repo --repo %s' % REPO, said)
        self.assertIn('reads before it creates', said)

        j = Journey(self)
        j.replay(until='launch')
        self.assertEqual(j.tool(PREVIEW).returncode, 12)
        self.assertEqual(j.tool(dict(YES, spawn=1)).returncode, 6)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: launch.')
        self.assertIn('uncertain', said)
        self.assertIn('never start it again', said)

        j.write_setup(setup_state(overrides={'personal_github': 'identity_no_push'}))
        self.assertEqual(j.helper(['continue']).returncode, 5)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: connect.', 'a withdrawn setup is connected again')


    def test_an_existing_repository_prepared_before_continue_resumes_at_connect(self):
        # catches: #1571, an owner who confirmed an existing repository and prepared it
        # in setup, interrupted before continue, is offered a repository again
        # (Next: project), inviting a second repository while Connect is under way.
        j = Journey(self)
        other = 'synthetic-owner/synthetic-existing'
        bound = j.helper(['select', '--repo', other])
        self.assertEqual(bound.returncode, 0, bound.stdout)
        j.write_setup(setup_state(repository=other))
        for more in ((), ('--setup-state', str(j.setup_dir))):
            said = self.next(j, *more)
            self.assertEqual(said.splitlines()[0], 'Next: connect.', said)
            self.assertIn('Repository: %s.' % other, said)
            self.assertIn('run continue', said)
        self.assertEqual(j.helper(['select', '--repo', REPO]).returncode, 5, 'one repository per onboarding')
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 5, 'and no demo beside it')
        self.assertEqual(j.gh_creates(), [], 'nothing created')

    def test_a_prepared_repository_is_never_taken_as_this_onboardings_selection(self):
        # catches: review R2, a repository setup prepared for an earlier project on this
        # host taken as this onboarding's selection (Next: connect for the wrong repository)
        # when this onboarding recorded none.
        j = Journey(self)
        previous = 'synthetic-owner/previous-project'
        j.write_setup(setup_state(repository=previous))
        said = self.next(j, '--setup-state', str(j.setup_dir))
        self.assertEqual(said.splitlines()[0], 'Next: project.', said)
        self.assertNotIn('Repository:', said)
        self.assertIn(previous, said, 'the candidate is named for the owner to confirm')
        self.assertIn('select --repo %s' % previous, said)
        (j.setup_dir / 'setup/state.json').chmod(0o644)
        self.assertNotIn(previous, self.next(j, '--setup-state', str(j.setup_dir)),
                         'a setup store others can read or replace is never trusted')

    def test_a_local_choice_resumes_at_choose_the_agents(self):
        # catches: #1571, a saved Local answer counted as a finished Choose the agents,
        # so a resumed owner confirms a spec and approves tickets before learning
        # Local cannot launch (Next: plan).
        j = Journey(self)
        j.replay(until='agents')
        self.assertEqual(j.helper(['choose', '--from-setup', '--agents', 'local']).returncode, 0)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: agents.', said)
        self.assertIn('Local', said)
        self.assertIn('--agents cloud', said)
        self.assertEqual(json.loads(j.state.read_text())['choices'], dict(j.settings, agents='local'),
                         'the recorded answer survives the restart')

    def test_a_cloud_choice_resumes_at_choose_the_agents_until_its_builder_tables_read_back(self):
        # catches: #1571, a saved Cloud choice counted as a finished Choose the agents
        # while setup has not yet made the builder tables name it, so a fresh session
        # skips the pending builder settings (Next: plan).
        j = Journey(self)
        j.replay(until='agents')
        j.world['files']['docs/agents/fleet.md'] = fleet_md(builder=CLAUDE, small=CLAUDE)
        j.save_world()
        chosen = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(chosen.returncode, 0, chosen.stdout)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: agents.', said)
        self.assertIn('builder tables', said)
        self.assertEqual(json.loads(j.state.read_text())['choices'], dict(j.settings, agents='cloud'),
                         'the recorded choice survives the restart')
        j.world['files']['docs/agents/fleet.md'] = fleet_md()  # setup made both builder tables the choice
        j.save_world()
        self.assertEqual(self.next(j).splitlines()[0], 'Next: agents.', 'only a read-back settles the tables')
        again = j.helper(['choose', '--from-setup', '--agents', 'cloud'])
        self.assertEqual(again.returncode, 0, again.stdout)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: plan.')
        self.assertEqual({k: v for k, v in json.loads(j.state.read_text())['choices'].items() if k in j.settings},
                         j.settings, 'the read-back keeps the recorded choice')


    def test_a_recorded_launch_resumes_before_the_agent_checks(self):
        # catches: review R1, a launched or uncertain first fleet saved before the
        # builder-table read-back existed sent back to Choose the agents, losing its
        # progress or its never-start-again recovery.
        def older(j):
            state = json.loads(j.state.read_text())
            state['choices'].pop('builder_tables', None)
            j.state.write_text(json.dumps(state))
        j = Journey(self)
        j.replay()
        older(j)
        self.assertEqual(self.next(j).splitlines()[0], 'Next: watch.')
        k = Journey(self)
        k.replay(until='launch')
        self.assertEqual(k.tool(PREVIEW).returncode, 12)
        self.assertEqual(k.tool(dict(YES, spawn=1)).returncode, 6)
        older(k)
        said = self.next(k)
        self.assertEqual(said.splitlines()[0], 'Next: launch.', said)
        self.assertIn('never start it again', said)

    def test_a_connected_repository_outlives_a_withdrawn_setup_after_an_absent_demo(self):
        # catches: an absent demo create counted as "no repository" once setup is
        # withdrawn, so resume asks for a repository again and create-repo makes a
        # second one while the connected repository is still saved (review R1).
        j = Journey(self)
        other = 'synthetic-owner/synthetic-existing'
        j.repos.write_text(github(create='fail'))
        self.assertEqual(j.helper(['create-repo', '--repo', REPO, '--yes']).returncode, 5)
        j.write_setup(setup_state(repository=other))
        self.assertEqual(j.helper(['continue']).returncode, 0, j.calls[-1][1].stdout)
        j.write_setup(setup_state(repository=other, overrides={'personal_github': 'identity_no_push'}))
        self.assertEqual(j.helper(['continue']).returncode, 5)
        said = self.next(j)
        self.assertEqual(said.splitlines()[0], 'Next: connect.', said)
        self.assertIn(other, said)
        creates = [c[1] for c in j.gh_creates()].count('create')
        second = j.helper(['create-repo', '--repo', 'synthetic-owner/second-demo', '--yes'])
        self.assertEqual(second.returncode, 5, second.stdout)
        self.assertIn(other, second.stdout)
        self.assertEqual([c[1] for c in j.gh_creates()].count('create'), creates, 'no second repository')


if __name__ == '__main__':
    unittest.main()
