#!/usr/bin/env python3
"""The install skill's first-fleet checks (#1108, joined to install in #636). Standard library only.

  first_fleet.py continue --state FILE --setup-state DIR [--explained]
  first_fleet.py decisions --state FILE --setup-state DIR [--yes]
  first_fleet.py create-repo --state FILE --repo OWNER/NAME [--yes]
  first_fleet.py select --state FILE --repo OWNER/NAME
  first_fleet.py choose --state FILE --options FILE (--harness P --model M --effort E | --from-setup) --agents cloud|local
  first_fleet.py spec --state FILE --spec N --repo OWNER/NAME
  first_fleet.py launch --state FILE --spec N [--yes --confirm DIGEST]
  first_fleet.py progress --state FILE --spec N --openwiz PROGRAM
  first_fleet.py next --state FILE [--setup-state DIR]

It adds no approval, planner or engine. `continue` carries what install and
setup already recorded in the installed OpenWiz state (DIR is its `<state>`):
the one selected repository and CloudRoom project, the acting GitHub identity,
the private brain `openwiz init` made, the prepared harness, model and effort,
and whether install already gave the explanation. It reads current setup
evidence only and refuses, naming each one, when a prerequisite is missing,
refused, unknown or out of date; it never fills one in. `create-repo` makes the
one disposable demo repository, private, with the user's own gh identity, only
on --yes: it saves the name first, creates it with its disclosed initial README
commit in that one create (#1074: init proposes the brain on its default
branch), reads back the repository, default branch and commit, and reads before
any retry of a create whose answer was lost. It never pushes into a repository.

`select` records the existing repository the owner confirmed, before Connect,
as this onboarding's one repository; it reads and changes nothing else.

`launch` starts the first fleet the way launch-fleet starts every fleet: it
reads launch-fleet's own frontier (../../launch-fleet/scripts/fleet.sh
frontier, which checks that to-tickets's approval is current), keeps this
spec's tickets, reads the fleet settings setup wrote (every builder table the
user's choice, each reviewer from the other model family), and starts one
fleet thread for the spec, with launch-fleet's own brief. That thread makes
its own loop, which runs the spec's check (`fleet.sh spec <S>`), records
itself on the spec and starts the frontier's builders. A preview prints a
confirmation digest of its exact effects; `--yes --confirm DIGEST` starts only
if a fresh read still has exactly those effects. It never calls the engine or
the engine's tick. The launch is saved before the start runs, and is never run
twice: a repeat only reads the spec's fleet record and progress, and an
uncertain start stays uncertain until that record reads back. Every command
checks the checkout is the repository this onboarding recorded.

`choose` records the choice, then for Cloud reads the fleet's builder tables
back: Choose the agents is done only once both name exactly that choice. Local
stays recorded but unfinished, since a Local fleet cannot launch yet.

`next` reads only the state file and prints the first unfinished step and
what to run there, so a fresh session resumes without repeating an effect.
With --setup-state it also reads, never writes, the repository setup
prepared: for the selected repository that is Connect's progress; with no
selection it is only a candidate for the owner to confirm with `select`, since
setup may have prepared it for an earlier project (#1571).

The state file is private and owner-only; keep it outside the checkout. It
holds the user's choices, the carried setup facts, this onboarding's spec and
its one launch record.

Exits: 0 done; 1 a read failed; 2 usage; 5 refused, nothing started;
6 uncertain, never retried; 7 busy; 10 state unavailable; 12 preview, awaiting --yes.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
import urllib.parse

LAUNCH_FLEET = Path(__file__).resolve().parents[2] / 'launch-fleet'
FLEET_SH = LAUNCH_FLEET / 'scripts/fleet.sh'
OPTIONS = {
    'continue': ({'--state', '--setup-state'}, {'--explained'}, set()),
    'decisions': ({'--state', '--setup-state'}, {'--yes'}, set()),
    'create-repo': ({'--state', '--repo'}, {'--yes'}, set()),
    'select': ({'--state', '--repo'}, set(), set()),
    'choose': ({'--state', '--options', '--agents'}, {'--from-setup'}, {'--harness', '--model', '--effort'}),
    'spec': ({'--state', '--spec', '--repo'}, set(), set()),
    'launch': ({'--state', '--spec'}, {'--yes'}, {'--confirm'}),
    'progress': ({'--state', '--spec', '--openwiz'}, set(), set()),
    'next': ({'--state'}, set(), {'--setup-state'}),
}
FAMILY = {'claude-code': 'claude', 'codex': 'gpt'}
REVIEWER = {'claude': 'Reviewer for Claude-built', 'gpt': 'Reviewer for GPT-built'}
STATES = ('ready', 'building', 'in_review', 'changes_requested', 'merged', 'held', 'blocked')
NOTHING = 'nothing started.'
# setup.v1's current-evidence window and its codes that establish `verified`.
CURRENT_MS = 60 * 60 * 1000
DRIFT_MS = 5 * 60 * 1000
VERIFIED = {'cloudroom': 'cloudroom_login_verified', 'personal_github': 'identity_verified',
            'github_app': 'app_verified', 'project': 'project_verified'}
NAMES = {'cloudroom': 'CloudRoom', 'harness': 'Agent harness', 'personal_github': 'Personal GitHub',
         'github_app': 'OpenWiz GitHub App', 'project': 'Project'}
REPOSITORY = r'[A-Za-z0-9][-A-Za-z0-9]*/[-A-Za-z0-9_.]+'
FLEET_RECORD = 'launch-fleet: fleet active, loop fleet-'


class Exit(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def strict(text):
    """One JSON value; a repeated key anywhere is refused."""
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate key')
            value[key] = item
        return value
    return json.loads(text, object_pairs_hook=pairs)


def parse(argv):
    if not argv or argv[0] not in OPTIONS:
        raise Exit(2, 'usage: first_fleet.py continue|create-repo|select|choose|spec|launch|progress|next ... '
                      '(see its header)')
    values, switches, optional = OPTIONS[argv[0]]
    got, rest = {}, argv[1:]
    while rest:
        name = rest.pop(0)
        if name in got or (name not in values | optional and name not in switches):
            raise Exit(2, 'usage: unknown or repeated option %s' % name)
        if name in switches:
            got[name] = True
            continue
        if not rest:
            raise Exit(2, 'usage: %s needs a value' % name)
        got[name] = rest.pop(0)
    missing = sorted(values - set(got))
    if missing:
        raise Exit(2, 'usage: missing %s' % ', '.join(missing))
    if argv[0] == 'choose':
        named = {'--harness', '--model', '--effort'} & set(got)
        if got.get('--from-setup') and named or not got.get('--from-setup') and len(named) != 3:
            raise Exit(2, 'usage: choose takes --harness, --model and --effort, or --from-setup for the ones '
                          'setup already recorded')
    if '--spec' in got and not re.fullmatch(r'[1-9][0-9]{0,9}', got['--spec']):
        raise Exit(2, 'usage: --spec takes an issue number')
    if argv[0] == 'launch' and ('--confirm' in got) != bool(got.get('--yes')) or not re.fullmatch(r'[0-9a-f]{64}', got.get('--confirm', '0' * 64)):
        raise Exit(2, 'usage: --yes takes --confirm with the digest of the preview the user said yes to')
    if '--repo' in got and not re.fullmatch(REPOSITORY, got['--repo']):
        raise Exit(2, 'usage: --repo takes owner/name')
    if '--agents' in got and got['--agents'] not in ('cloud', 'local'):
        raise Exit(2, 'usage: --agents is cloud or local')
    if '--setup-state' in got and not os.path.isabs(got['--setup-state']):
        raise Exit(2, 'usage: --setup-state takes the installed state folder by absolute path')
    if '--openwiz' in got:
        program = got['--openwiz']
        if not os.path.isabs(program) or not os.path.isfile(program) or not os.access(program, os.X_OK):
            raise Exit(2, 'usage: --openwiz takes the installed program by absolute path')
    return argv[0], got


class State:
    """The private state file, held under its lock for the whole command."""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_absolute():
            raise Exit(2, 'usage: --state takes an absolute path')
        try:
            self.lock = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise Exit(10, 'The onboarding state is unavailable; ' + NOTHING)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Exit(7, 'Another onboarding command is using this state; ' + NOTHING)
        self.value = self.read()

    def read(self):
        try:
            info = os.lstat(self.path)
        except FileNotFoundError:
            return {}
        except OSError:
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Exit(10, 'The onboarding state must be an owner-only regular file; ' + NOTHING)
        try:
            value = strict(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise Exit(10, 'The onboarding state is unreadable; ' + NOTHING)
        known = {'created', 'choices', 'repo', 'spec', 'preview', 'launch', 'setup'}
        if not isinstance(value, dict) or set(value) - known:
            raise Exit(10, 'The onboarding state has an unknown shape; ' + NOTHING)
        return value

    def save(self):
        temp = self.path.with_name(self.path.name + '.new')
        try:
            fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(self.value, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            return True
        except OSError:
            try:
                os.unlink(temp)
            except OSError:
                pass
            return False


def run(argv, env=None):
    try:
        return subprocess.run(argv, capture_output=True, timeout=600, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None


# --- The continuation from install and setup (#636) ----------------------

def setup_facts(folder):
    """What the installed setup recorded and currently verifies, or Exit naming
    each prerequisite that is not verified now. Reads the setup store only."""
    path = Path(folder) / 'setup/state.json'
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise Exit(10, "OpenWiz's setup state must be an owner-only file; " + NOTHING)
        value = strict(path.read_text(encoding='utf-8'))
        assert value['schema'] == 'openwiz.setup-state.v1' and type(value['revision']) is int
        observations, project = value['observations'], value['project']
        assert isinstance(observations, dict) and (project is None or isinstance(project, dict))
        if project is not None:
            assert all(isinstance(project[k], str) and project[k]
                       for k in ('repository', 'project', 'harness', 'model', 'effort'))
            assert re.fullmatch(REPOSITORY, project['repository'])
        identity, brain = value.get('identity'), value.get('brain')
        assert identity is None or (isinstance(identity, dict) and isinstance(identity['selected'], str)
                                    and (identity['acting_login'] is None or isinstance(identity['acting_login'], str)))
        assert brain is None or (isinstance(brain, dict) and all(
            isinstance(brain[k], str) for k in ('location', 'code_repository', 'brain_repository'))
            and (brain['decision_repositories'] is None or isinstance(brain['decision_repositories'], dict)))
    except FileNotFoundError:
        raise Exit(5, 'Setup has not run in this OpenWiz state yet; run the setup check first; ' + NOTHING)
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(10, "OpenWiz's setup state is unreadable; " + NOTHING)
    if project is None:
        raise Exit(5, 'Setup has no prepared project: prepare it (setup.py prepare) and check again; ' + NOTHING)
    repository = project['repository']
    if not (identity and identity.get('repository') == repository):
        identity = None
    skipped = bool(identity and identity['selected'] == 'personal_login' and identity.get('app_choice') == 'skip'
                   and identity['acting_login'])
    now = int(time.time() * 1000)

    def state(component):
        seen = observations.get(component)
        if not isinstance(seen, dict) or not isinstance(seen.get('code'), str):
            return 'missing', 'not checked yet'
        current = (seen.get('revision') == value['revision'] and type(seen.get('at')) is int
                   and seen['at'] <= now + DRIFT_MS and now - seen['at'] <= CURRENT_MS)
        if not current:
            return 'unknown', 'its last check is out of date or for another selection'
        if seen['code'] == VERIFIED.get(component):
            return 'verified', None
        return ('unknown' if seen['code'].endswith('_unreadable') else 'not verified'), seen['code']

    needed = ['cloudroom', 'personal_github', 'project'] + ([] if skipped else ['github_app'])
    problems = []
    for component in needed:
        found, why = state(component)
        if found != 'verified':
            problems.append('%s: %s (%s)' % (NAMES[component], found, why))
    harness, why = state('harness')
    if harness == 'verified' or why == 'harness_listed':
        harness_line = 'listed by CloudRoom; its login is not proven by setup'
    else:
        problems.append('%s: %s (%s)' % (NAMES['harness'], harness, why))
    if brain is None or brain['code_repository'].lower() != repository.lower():
        problems.append('Private brain: missing (run openwiz init for %s, then the setup check)' % repository)
    elif brain['location'] == 'companion' and not decisions_pair(folder, brain['decision_repositories']):
        problems.append("Decisions repository pair: not configured (the private settings' decision_repositories "
                        'must name %s as public and %s as private, so Decisions reads the companion)'
                        % (repository, brain['brain_repository']))
    if problems:
        raise Exit(5, 'Setup is not ready for the first fleet: %s; %s' % ('; '.join(problems), NOTHING))
    acting = ('%s, your personal GitHub login (the App is skipped)' % identity['acting_login'] if skipped
              else 'your OpenWiz GitHub App')
    return {'setup_state': str(folder), 'repository': repository, 'project': project['project'],
            'settings': {k: project[k] for k in ('harness', 'model', 'effort')},
            'identity': {'selected': 'personal_login' if skipped else 'app', 'acting': acting},
            'brain': {'location': brain['location'], 'repository': brain['brain_repository']},
            'harness': harness_line}


def decisions_pair(folder, pair):
    """Whether the existing private settings (service/config.json, decisions.v1's
    repository roles) name exactly the brain's public/private pair. Read only."""
    try:
        settings = strict((Path(folder) / 'service/config.json').read_text(encoding='utf-8'))
        configured = settings['decision_repositories']
        name = lambda roles, role: '%s/%s' % (roles[role]['owner'], roles[role]['name'])
        return all(name(configured, r).lower() == name(pair, r).lower() for r in ('public', 'private'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def connect_decisions(got):
    """A public repository's companion brain, connected to Decisions through the
    existing private settings: decisions.v1's `decision_repositories` pair in
    <state>/service/config.json. Only that key is written; every other byte of an
    existing settings file stays. Preview first; --yes writes it once."""
    folder = Path(got['--setup-state'])
    try:
        value = strict((folder / 'setup/state.json').read_text(encoding='utf-8'))
        brain = value['brain']
        assert isinstance(brain, dict) and brain['location'] == 'companion'
        pair = brain['decision_repositories']
        assert set(pair) == {'public', 'private'}
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(5, 'Setup records no companion brain to connect; nothing changed.')
    if decisions_pair(folder, pair):
        print('Decisions already reads %s/%s with its companion.' % (pair['public']['owner'], pair['public']['name']))
        return 0
    path = folder / 'service/config.json'
    try:
        settings = strict(path.read_text(encoding='utf-8'))
        assert isinstance(settings, dict)
    except FileNotFoundError:
        settings = {}
    except (OSError, ValueError, AssertionError):
        raise Exit(10, 'The private settings file is unreadable; nothing changed.')
    print('Effect: set Decisions\' repository pair in the private settings: public %s/%s, private %s/%s. '
          'Restart the OpenWiz server afterwards.' % (pair['public']['owner'], pair['public']['name'],
                                                    pair['private']['owner'], pair['private']['name']))
    if not got.get('--yes'):
        print("Nothing changed. On the user's yes to exactly this, run again with --yes.")
        return 12
    settings['decision_repositories'] = pair
    temp = None
    try:
        path.parent.mkdir(mode=0o700, exist_ok=True)
        # Review R6: a staging file of its own for each attempt (owner-only,
        # created exclusively), so one left by an interrupted attempt never
        # blocks this one; nothing else in the folder is touched.
        fd, temp = tempfile.mkstemp(prefix='config.json.', suffix='.new', dir=path.parent)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(settings, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except OSError:
        if temp is not None:
            try:
                os.unlink(temp)
            except OSError:
                pass
        raise Exit(10, 'Could not write the private settings; nothing changed.')
    print('Decisions now reads the companion. Restart the OpenWiz server, then run continue.')
    return 0


def withdraw(state):
    """A failed refresh withdraws launch eligibility; the owner's choices and work stay."""
    if 'setup' in state.value:
        del state.value['setup']
        state.save()


def refreshed(state, folder):
    """Setup's current facts, or Exit after withdrawing the carried setup."""
    try:
        return setup_facts(folder)
    except Exit:
        withdraw(state)
        raise


def carry_on(got):
    state = State(got['--state'])
    facts = refreshed(state, got['--setup-state'])
    if state.value.get('repo') not in (None, facts['repository']):
        raise Exit(5, 'This onboarding is for %s, but setup selected %s; %s' % (
            state.value['repo'], facts['repository'], NOTHING))
    created = state.value.get('created')
    if created and created['state'] == 'created' and created['repo'] != facts['repository']:
        raise Exit(5, 'This onboarding created %s, but setup selected %s; %s' % (
            created['repo'], facts['repository'], NOTHING))
    earlier = state.value.get('setup') or {}
    facts['explained'] = bool(got.get('--explained') or earlier.get('explained'))
    state.value['setup'] = facts
    state.value['repo'] = facts['repository']
    if not state.save():
        raise Exit(10, 'Could not save the carried setup; ' + NOTHING)
    print('Carried from setup: repository %s, CloudRoom project %s.' % (facts['repository'], facts['project']))
    print('Acting identity: %s.' % facts['identity']['acting'])
    print('Private brain: %s (%s).' % (facts['brain']['repository'], facts['brain']['location'].replace('_', ' ')))
    print('Prepared agents: %s %s %s; harness %s.' % (
        facts['settings']['harness'], facts['settings']['model'], facts['settings']['effort'], facts['harness']))
    print('Next: %s.' % ('the grill (the explanation is done)' if facts['explained'] else 'the explanation'))
    return 0


# --- The demo repository --------------------------------------------------

def gh_env():
    env = dict(os.environ)
    env.pop('GH_REPO', None)
    return env


def look(name):
    """The repository as GitHub shows it now, from reads only: 'absent', 'public',
    'empty' (private, but no default branch and commit read back) or
    {'branch', 'commit'} (private, its default branch at that commit). None when
    a read failed or answered something else: unknown, never success."""
    result = run(['gh', 'repo', 'view', name, '--json', 'nameWithOwner,isPrivate,defaultBranchRef'], gh_env())
    if result is None:
        return None
    if result.returncode != 0:
        return 'absent' if b'Could not resolve to a Repository' in result.stderr else None
    try:
        found = strict(result.stdout.decode('utf-8'))
        assert found['nameWithOwner'] == name and type(found['isPrivate']) is bool
        branch = (found['defaultBranchRef'] or {}).get('name') or ''
        assert isinstance(branch, str)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AttributeError, AssertionError):
        return None
    if not found['isPrivate']:
        return 'public'
    if not branch:
        return 'empty'
    result = run(['gh', 'api', '--include', '-X', 'GET',
                  'repos/%s/git/ref/heads/%s' % (name, urllib.parse.quote(branch, safe='/'))], gh_env())
    if result is None:
        return None
    head, _, body = result.stdout.replace(b'\r\n', b'\n').partition(b'\n\n')
    status = re.match(rb'HTTP/[0-9.]+ ([0-9]{3})', head)
    if status is None:
        return None
    if status.group(1) in (b'404', b'409'):  # no such ref; 409 is GitHub's empty repository
        return 'empty'
    try:
        assert status.group(1) == b'200'
        commit = strict(body.decode('utf-8'))['object']['sha']
        assert isinstance(commit, str) and re.fullmatch('[0-9a-f]{40}', commit)
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, AssertionError):
        return None
    return {'branch': branch, 'commit': commit}


def created_line(name, seen):
    return 'Created and read back: %s, private, default branch %s at commit %s.' % (
        name, seen['branch'], seen['commit'])


def create_repo(got):
    name = got['--repo']
    print('Effect: create one new private GitHub repository, %s, with your gh identity, in one GitHub create with '
          'its initial commit: a README.md holding only the title "# %s" on its default branch, which OpenWiz '
          'init needs to propose the brain. Nothing else is created or pushed; its CloudRoom project stays yours '
          'to make or pick.' % (name, name.split('/')[1]))
    if not got.get('--yes'):
        print("Nothing created. On the user's yes to exactly this, run again with --yes.")
        return 12
    state = State(got['--state'])
    if state.value.get('setup') and state.value['setup']['repository'] != name:
        raise Exit(5, 'Setup already selected %s for this onboarding; it makes no second repository.'
                   % state.value['setup']['repository'])
    if state.value.get('repo') not in (None, name):
        raise Exit(5, 'This onboarding is for %s; it makes no second repository.' % state.value['repo'])
    record = state.value.get('created')
    if record and record['repo'] != name and record['state'] != 'absent':
        raise Exit(5, 'This onboarding already made %s; it makes one demo repository.' % record['repo'])
    login = run(['gh', 'api', 'user', '--jq', '.login'], gh_env())
    if (login is None or login.returncode != 0
            or not re.fullmatch(rb'[A-Za-z0-9](-?[A-Za-z0-9])*', login.stdout.strip())):
        raise Exit(5, 'GitHub sign-in could not be verified. Complete the GitHub sign-in step first '
                      '(github_login.py sign-in), then run create-repo again; nothing created.')
    seen = look(name)
    if seen is None:
        raise Exit(1 if not record else 6, 'Could not read whether %s exists; nothing created.' % name)
    if record and record['repo'] == name and record['state'] in ('pending', 'uncertain', 'created'):
        if isinstance(seen, dict):
            state.value['created'] = {'repo': name, 'state': 'created', **seen}
            if not state.save():
                raise Exit(6, 'Could not save the created repository; it exists, so never create it again.')
            print(created_line(name, seen))
            return 0
        if seen == 'public':
            raise Exit(5, '%s is not the private repository this onboarding created; nothing created.' % name)
        if seen == 'empty':
            if record['state'] == 'created':
                raise Exit(5, '%s has no default branch and initial commit, which init needs; OpenWiz never pushes '
                              'one into an existing repository. Add a first commit yourself, or choose a new '
                              'name; nothing created.' % name)
            state.value['created'] = {'repo': name, 'state': 'uncertain'}
            state.save()
            raise Exit(6, '%s exists, but its default branch and initial commit did not read back; nothing more '
                          'was created or pushed. Run this again to read it back.' % name)
        if record['state'] == 'created':
            raise Exit(5, '%s is not the private repository this onboarding created; nothing created.' % name)
    elif seen != 'absent':
        raise Exit(5, '%s already exists; choose another name, or use it as an existing repository; '
                      'nothing created.' % name)
    state.value['created'] = {'repo': name, 'state': 'pending'}
    if not state.save():
        raise Exit(10, 'Could not save the repository name first; nothing created.')
    run(['gh', 'repo', 'create', name, '--private', '--add-readme'])
    seen = look(name)
    ended = 'created' if isinstance(seen, dict) else 'absent' if seen == 'absent' else 'uncertain'
    state.value['created'] = {'repo': name, 'state': ended, **(seen if ended == 'created' else {})}
    saved = state.save()
    if ended == 'created' and saved:
        print(created_line(name, seen))
        return 0
    if ended == 'absent' and saved:
        raise Exit(5, 'GitHub did not create %s; nothing created. Try again only after the user says yes again.' % name)
    raise Exit(6, 'Whether %s was created with its default branch and initial commit is uncertain; read it back '
                  'before any retry (run this again).' % name)


def select(got):
    """The existing repository the owner confirmed, bound to this onboarding before Connect."""
    state = State(got['--state'])
    name = got['--repo']
    if state.value.get('repo') not in (None, name):
        raise Exit(5, 'This onboarding is for %s; it takes no second repository; nothing recorded.'
                   % state.value['repo'])
    record = state.value.get('created')
    if record and record['repo'] != name and record['state'] != 'absent':
        raise Exit(5, 'This onboarding already made %s; it takes no second repository; nothing recorded.'
                   % record['repo'])
    state.value['repo'] = name
    if not state.save():
        raise Exit(10, 'Could not save the repository; nothing recorded.')
    print('Recorded: this onboarding is for %s. Connect it next.' % name)
    return 0


# --- Choices ----------------------------------------------------------------

def choose(got):
    state = State(got['--state'])
    if got.get('--from-setup'):
        carried = state.value.get('setup')
        if not carried:
            raise Exit(5, 'No setup was carried into this onboarding (run continue first); nothing recorded.')
        settings = carried['settings']
    else:
        settings = {'harness': got['--harness'], 'model': got['--model'], 'effort': got['--effort']}
    try:
        offered = strict(Path(got['--options']).read_text(encoding='utf-8'))
        assert offered['schema'] == 'openwiz.cloud-options.v1' and offered['state'] == {'kind': 'offered'}
        harnesses = [h for h in offered['harnesses'] if h['provider'] == settings['harness']]
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        raise Exit(1, 'The saved `openwiz models --json` output is unreadable; nothing recorded.')
    efforts = [e for h in harnesses for m in h['models'] if m['model'] == settings['model'] for e in m['efforts']]
    if len(harnesses) != 1 or settings['effort'] not in efforts:
        raise Exit(5, 'That harness, model and effort are not among the offered options; nothing recorded.')
    if settings['harness'] not in FAMILY:
        raise Exit(5, "The fleet's review rules cover Claude Code and Codex builders only; nothing recorded.")
    choices = dict(settings, agents=got['--agents'])
    read = None  # unread: the choice is recorded, its builder tables are not settled
    if got['--agents'] == 'cloud':
        try:
            rules = fleet_rules(repository(state.value.get('repo')), state.value['repo'])
        except Exit:
            rules = None
        if rules is not None:
            try:
                review(choices, rules)  # the launch's own check of the same tables
                read = True
            except Exit:
                read = False
    if read:
        choices['builder_tables'] = 'read'
    state.value['choices'] = choices
    if not state.save():
        raise Exit(10, 'Could not save the choices; nothing recorded.')
    print(chosen_line(choices) + (' (as prepared in setup)' if got.get('--from-setup') else ''))
    if got['--agents'] == 'local':
        print(LOCAL)
    elif read:
        print("Read back: both of the fleet's builder tables name exactly this choice, with an other-family "
              'reviewer.')
    else:
        print(tables_line(choices, 'could not be read' if read is None else 'do not name this choice yet'))
        return 1 if read is None else 0
    return 0


LOCAL = ('Local fleet agents are not available yet: launch-fleet starts the fleet and its builders in the Cloud. '
         'Run choose again with --agents cloud, or stop here.')


def chosen_line(choices):
    where = 'in the Cloud' if choices['agents'] == 'cloud' else 'on this computer (Local)'
    return 'Recorded: builders use %s %s %s, and run %s.' % (
        choices['harness'], choices['model'], choices['effort'], where)


def tables_line(choices, why):
    return ("The fleet's builder tables %s: run setup so both name exactly %s %s %s, with the reviewer from the "
            'other family, then run choose again with --agents cloud to read them back.' % (
                why, choices['harness'], choices['model'], choices['effort']))


def repository(recorded):
    """The environment for every read and run, once the checkout is the recorded repository."""
    if not recorded:
        raise Exit(5, 'This onboarding recorded no repository; record its spec first; ' + NOTHING)
    env = dict(os.environ)
    named = env.pop('GH_REPO', None)
    if named is not None and named != recorded:
        raise Exit(5, 'GH_REPO names %s, but this onboarding is for %s; %s' % (named, recorded, NOTHING))
    result = run(['gh', 'repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read which repository this checkout is; ' + NOTHING)
    here = result.stdout.decode('utf-8', 'replace').strip()
    if here != recorded:
        raise Exit(5, 'This checkout is %s, but this onboarding is for %s; %s' % (here, recorded, NOTHING))
    env['GH_REPO'] = recorded
    return env


def record_spec(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    carried = state.value.get('setup')
    if carried and carried['repository'] != got['--repo']:
        raise Exit(5, 'Setup selected %s for this onboarding; it plans no spec in %s; nothing recorded.' % (
            carried['repository'], got['--repo']))
    repository(got['--repo'])
    if state.value.get('launch') and state.value.get('repo') not in (None, got['--repo']):
        raise Exit(5, 'This onboarding already launched in %s; nothing recorded.' % state.value['repo'])
    launch = state.value.get('launch')
    if launch and launch['spec'] != spec and launch['state'] != 'refused':
        raise Exit(5, 'This onboarding already launched spec #%d; it plans one first fleet.' % launch['spec'])
    state.value['spec'] = spec
    state.value['repo'] = got['--repo']
    if not state.save():
        raise Exit(10, 'Could not save the spec; nothing recorded.')
    print('Recorded: this onboarding planned spec #%d in %s.' % (spec, got['--repo']))
    return 0


# --- The launch, through launch-fleet ----------------------------------------

def frontier(env):
    result = run(['sh', str(FLEET_SH), 'frontier'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, 'Could not read the approved frontier; ' + NOTHING)
    tickets = {}
    for line in result.stdout.decode('utf-8', 'replace').splitlines():
        match = re.fullmatch(r'#([1-9][0-9]*) (.+)', line)
        if not match or int(match[1]) in tickets:
            raise Exit(1, 'The frontier read was not in its form; ' + NOTHING)
        tickets[int(match[1])] = match[2]
    return tickets


def gh_json(argv, env, what):
    result = run(['gh', *argv], env)
    try:
        assert result is not None and result.returncode == 0
        return strict(result.stdout.decode('utf-8'))
    except (AssertionError, UnicodeDecodeError, ValueError):
        raise Exit(1, 'Could not read %s; %s' % (what, NOTHING))


def spec_facts(spec, env):
    """The spec's title and its sub-issue numbers, read from GitHub."""
    subs = gh_json(['issue', 'view', str(spec), '--json', 'subIssues', '--jq', '.subIssues'], env, "the spec's tickets")
    head = gh_json(['issue', 'view', str(spec), '--json', 'number,title,blockedBy', '--jq', '{number, title}'],
                   env, 'the spec')
    try:
        numbers = [node['number'] for node in subs['nodes']]
        assert subs['totalCount'] == len(numbers) == len(set(numbers)) and all(type(n) is int for n in numbers)
        assert head['number'] == spec and isinstance(head['title'], str) and head['title'].strip()
    except (KeyError, TypeError, AssertionError):
        raise Exit(1, "The spec's tickets were not read completely; " + NOTHING)
    return ' '.join(head['title'].split()), set(numbers)


def agent(lines):
    """harness, model and effort from one settings table's `room-cli thread spawn` flags."""
    text = '\n'.join(lines)
    found = {}
    for key, flag in (('harness', 'provider'), ('model', 'model'), ('effort', 'reasoning-level')):
        values = re.findall(r'`--%s ([^`\s]+)`' % flag, text)
        if len(values) != 1:
            return None
        found[key] = values[0]
    return found


def fleet_rules(env, repo):
    """The builder and reviewer tables of docs/agents/fleet.md on the default branch."""
    result = run(['gh', 'api', 'repos/%s/contents/docs/agents/fleet.md' % repo,
                  '-H', 'Accept: application/vnd.github.raw+json'], env)
    if result is None or result.returncode != 0:
        raise Exit(1, "Could not read the fleet settings (docs/agents/fleet.md); run setup; " + NOTHING)
    found, name = {}, None
    for line in result.stdout.decode('utf-8', 'replace').split('\n'):
        if line.startswith('## '):
            name = line[3:].strip()
            found.setdefault(name, [])
        elif name is not None:
            found[name].append(line)
    rules = {key: agent(found[title]) if title in found else None for key, title in (
        ('builder', 'Builder'), ('builder_small', 'Builder for small tickets'),
        ('reviewer_claude', REVIEWER['claude']), ('reviewer_gpt', REVIEWER['gpt']))}
    return rules


def review(choices, rules):
    """Refuse unless every builder table is the user's choice and its reviewer is the other family."""
    want = {k: choices[k] for k in ('harness', 'model', 'effort')}
    if rules['builder'] != want or rules['builder_small'] != want:
        raise Exit(5, "The fleet's builder tables (builder and small-ticket builder) are not exactly the user's "
                      'choice; run setup so both match, then preview again; ' + NOTHING)
    family = FAMILY[want['harness']]
    reviewer = rules['reviewer_' + family]
    if reviewer is None or FAMILY.get(reviewer['harness']) in (None, family):
        raise Exit(5, "The fleet's reviewer for these builders is not from the other model family; " + NOTHING)
    return want, reviewer


def brief(spec, repo):
    """launch-fleet's own fleet-thread brief ("Fleet threads", "Starting one"), literally."""
    return ("You are the fleet thread for spec #%d of %s. Use the launch-fleet skill. Read "
            "'skills/launch-fleet/SKILL.md' if present, otherwise find '*/skills/launch-fleet/SKILL.md' only inside "
            "your own harness's configured plugin cache: Codex uses CODEX_HOME/plugins/cache (default "
            "HOME/.codex/plugins/cache); Claude uses CLAUDE_CODE_PLUGIN_CACHE_DIR/cache when set, otherwise "
            "CLAUDE_CONFIG_DIR/plugins/cache (default HOME/.claude/plugins/cache); for another harness use its "
            "installation metadata. Prefer active installation metadata over cache scanning when available. During "
            "cache scans exclude other harness caches, source checkouts, orphaned versions marked .orphaned_at, and "
            "targets outside the selected cache. Follow symlinks and deduplicate real paths. Verify "
            ".claude-plugin/plugin.json manifest name openwiz and entry ./skills/launch-fleet; report missing, "
            "unreadable or ambiguous matches, otherwise read the unique matching file and follow it; do its Fleet "
            "threads section, first wake." % (spec, repo))


def fleet_recorded(spec, env):
    """Only configured record authors settle a start; unread input stays unknown."""
    settings = run(['gh', 'api', 'repos/%s/contents/docs/agents/fleet.md' % env['GH_REPO'],
                    '-H', 'Accept: application/vnd.github.raw+json'], env)
    if settings is None or settings.returncode != 0:
        return None
    try:
        # The same Record authors policy as fleet.sh settings(): exactly one
        # row in GitHub identity, only comma-separated backticked logins, no
        # extra cells or malformed entries, compared case-insensitively.
        rows, identity = [], False
        for line in settings.stdout.decode('utf-8').splitlines():
            if line.startswith('## '):
                identity = line == '## GitHub identity'
            if identity and re.match(r'^\| *Record authors *\|', line):
                rows.append(line)
        if len(rows) != 1:
            return None
        row = re.fullmatch(r'\| *Record authors *\|([^|]*)\|\s*', rows[0])
        login = r'`[A-Za-z0-9](-?[A-Za-z0-9])*(\[bot\])?`'
        if row is None or not re.fullmatch(r'\s*' + login + r'(\s*,\s*' + login + r')*\s*', row[1]):
            return None
        authors = {value.lower() for value in re.findall(r'`([^`]*)`', row[1])}
    except UnicodeDecodeError:
        return None
    result = run(['gh', 'api', '--paginate', 'repos/%s/issues/%d/comments?per_page=100' % (env['GH_REPO'], spec),
                  '--jq', '.[] | {author: .user.login, body} | @json'], env)
    if result is None or result.returncode != 0:
        return None
    try:
        lines = result.stdout.decode('utf-8').split('\n')
        if lines[-1] == '':
            lines.pop()
        comments = [strict(line) for line in lines]
        if any(not isinstance(c, dict) or set(c) != {'author', 'body'} or not isinstance(c['body'], str)
               or c['author'] is not None and not isinstance(c['author'], str) for c in comments):
            return None
    except (UnicodeDecodeError, ValueError):
        return None
    return any(c['author'] is not None and c['author'].lower() in authors
               and c['body'].split('\n')[0].strip() == FLEET_RECORD + str(spec) for c in comments)


def launch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d; it launches only the spec its own grill planned; %s'
                   % (spec, NOTHING))
    carried = state.value.get('setup')
    if not carried:
        raise Exit(5, 'No verified setup was carried into this onboarding (run continue first); ' + NOTHING)
    choices = state.value.get('choices')
    if not choices:
        raise Exit(5, 'The harness, model, effort and agent location are not chosen yet; ' + NOTHING)
    env = repository(state.value.get('repo'))
    previous = state.value.get('launch')
    if previous and previous['spec'] == spec and previous['state'] != 'refused':
        recorded = fleet_recorded(spec, env)
        if previous['state'] in ('pending', 'uncertain') and recorded:
            previous['state'] = 'started'
            state.save()
        settled = previous['state'] == 'started'
        print('Spec #%d already started once (%s); not starting again.' % (
            spec, 'its fleet thread was started' if settled else 'uncertain: never a retry'))
        print(record_line(spec, recorded))
        return 0 if settled else 6
    # Review R4: the carried setup must still be what setup verifies now.
    if not isinstance(carried.get('setup_state'), str):
        withdraw(state)
        raise Exit(5, 'The carried setup names no setup state to recheck; run continue again; ' + NOTHING)
    current = refreshed(state, carried['setup_state'])
    if any(current[k] != carried.get(k) for k in current):
        withdraw(state)
        raise Exit(5, 'Setup changed since it was carried; run continue again; ' + NOTHING)
    if choices['agents'] != 'cloud':
        raise Exit(5, "Local fleet agents are not available yet: launch-fleet starts the fleet thread and its "
                      'builders in the Cloud. Choose Cloud, or stop here; ' + NOTHING)
    ready = frontier(env)
    title, members = spec_facts(spec, env)
    starts = sorted(n for n in ready if n in members)
    if not starts:
        raise Exit(5, 'No approved ticket of spec #%d is ready to start: the plan is unapproved, changed since its '
                      'approval, or still blocked; %s' % (spec, NOTHING))
    builder, reviewer = review(choices, fleet_rules(env, state.value['repo']))
    effects = {'repo': state.value['repo'], 'spec': spec, 'project': carried['project'], 'title': title,
               'fleet_thread': builder, 'builder': builder, 'reviewer': reviewer,
               'tickets': [[n, ready[n]] for n in starts]}
    digest = hashlib.sha256(json.dumps(effects, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if got.get('--yes'):
        shown = state.value.get('preview') or {}
        if got['--confirm'] != digest or shown.get('effects') != digest or shown.get('spec') != spec:
            raise Exit(5, 'The effects changed since the preview the user said yes to (or it was never shown); '
                          'preview again and ask again; ' + NOTHING)
    agents = '%s %s %s' % (builder['harness'], builder['model'], builder['effort'])
    print('Ready to start the first fleet for spec #%d, through launch-fleet, in the Cloud (CloudRoom project %s):'
          % (spec, carried['project']))
    print('1 fleet thread, %s. It makes its own loop, which checks spec #%d every 10 minutes '
          "(launch-fleet's fleet.sh spec %d), and records itself on the spec." % (agents, spec, spec))
    print('Then %d builders, each %s, on the approved frontier:' % (len(starts), agents))
    for ticket in starts:
        print('#%d %s' % (ticket, ready[ticket]))
    print('Each pull request is reviewed by %s %s %s, from the other model family.' % (
        reviewer['harness'], reviewer['model'], reviewer['effort']))
    print('Cloud Credits: unknown until measured. Model-provider charges are separate.')
    if not got.get('--yes'):
        state.value['preview'] = {'spec': spec, 'effects': digest}
        if not state.save():
            raise Exit(10, 'Could not save the preview; ' + NOTHING)
        print('Confirmation: %s' % digest)
        print('Nothing started. Show this to the user; on their yes to exactly these effects, run again with '
              '--yes --confirm %s.' % digest)
        return 12
    state.value['launch'] = {'spec': spec, 'state': 'pending', 'effects': digest, 'tickets': starts}
    if not state.save():
        raise Exit(10, 'Could not save the launch record; ' + NOTHING)
    argv = ['room-cli', 'thread', 'spawn', '--parent-self', '--project', carried['project'],
            '--machine', 'cloud', '--provider', builder['harness'], '--model', builder['model'],
            '--reasoning-level', builder['effort'], '--title', 'Fleet #%d: %s' % (spec, title),
            '--prompt', brief(spec, state.value['repo'])]
    try:
        result = subprocess.run(argv, capture_output=True, timeout=600, env=env)
    except (FileNotFoundError, PermissionError):
        # Review R2: room-cli never ran, so nothing was dispatched. A fresh
        # preview and yes are needed before another try.
        state.value['launch']['state'] = 'refused'
        state.value.pop('preview', None)
        saved = state.save()
        raise Exit(5 if saved else 6, 'room-cli could not be run, so no fleet thread was dispatched; nothing started. '
                   'Fix the CloudRoom installation, then preview again and ask again.' if saved else
                   'room-cli could not be run, but that could not be saved; the start stays pending until read.')
    except (OSError, subprocess.TimeoutExpired):
        result = None
    ended = 'started' if result is not None and result.returncode == 0 else 'uncertain'
    state.value['launch']['state'] = ended
    if not state.save():
        print('Could not save the outcome; the start stays uncertain and is never retried.')
        ended = 'uncertain'
    if ended == 'started':
        print("Started spec #%d's fleet thread. Its first wake makes its loop, records itself and starts the "
              'builders.' % spec)
        return 0
    print('Whether the fleet thread started is uncertain. Never start it again by hand: run this command again '
          "to read the spec's fleet record, or look for the thread in CloudRoom.")
    return 6


def record_line(spec, recorded):
    if recorded is None:
        return "The spec's fleet record could not be read right now."
    if recorded:
        return 'Spec #%d has its fleet record: the fleet thread made its loop and runs the spec.' % spec
    return 'Spec #%d has no fleet record yet: its fleet thread has not finished its first wake.' % spec


def watch(got):
    state = State(got['--state'])
    spec = int(got['--spec'])
    if state.value.get('spec') != spec:
        raise Exit(5, 'This onboarding planned no spec #%d.' % spec)
    env = repository(state.value.get('repo'))
    print(record_line(spec, fleet_recorded(spec, env)))
    return progress(spec, got['--openwiz'], env)


def progress(spec, program, env):
    result = run([program, 'fleet', str(spec), '--json'], env)
    try:
        assert result is not None and result.returncode == 0
        view = strict(result.stdout.decode('utf-8'))
        assert view['schema'] == 'openwiz.fleet.v1' and view['data']['view'] == 'fleet'
        assert view['data']['fleet']['spec'] == spec
        tickets, counts = view['data']['tickets'], view['data']['fleet']['progress']
    except (AssertionError, UnicodeDecodeError, ValueError, KeyError, TypeError):
        print('Progress for spec #%d is unreadable right now.' % spec)
        return 1
    for ticket in tickets:
        known = ticket['state'].get('known') if isinstance(ticket.get('state'), dict) else None
        print('#%d %s' % (ticket['number'], known if known in STATES else 'unknown'))
    known = counts.get('known') if isinstance(counts, dict) else None
    if isinstance(known, dict):
        parts = ['%d %s' % (known[s], s.replace('_', ' ')) for s in STATES + ('unknown',) if known.get(s)]
        print('%d tickets: %s' % (known.get('tickets', 0), ', '.join(parts) or 'none yet'))
    else:
        print('Counts unknown: some reads are incomplete.')
    print('Counts are progress, not a first merge: a merge counts only when GitHub reads it back.')
    return 0


def prepared(folder):
    """The repository setup selected for this onboarding (its prepared project, or
    else its sign-in), read only; None when there is none or it is unreadable."""
    path = Path(folder) / 'setup/state.json'
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            return None
        value = strict(path.read_text(encoding='utf-8'))
        assert value['schema'] == 'openwiz.setup-state.v1'
        for record in (value.get('project'), value.get('identity')):
            if isinstance(record, dict) and isinstance(record.get('repository'), str):
                return record['repository'] if re.fullmatch(REPOSITORY, record['repository']) else None
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        pass
    return None


def resume(got):
    """The first unfinished first-fleet step, from the saved state alone."""
    state = State.__new__(State)  # read only: no lock, nothing opened for writing
    state.path = Path(got['--state'])
    if not state.path.is_absolute():
        raise Exit(2, 'usage: --state takes an absolute path')
    value = state.read()
    created, launched = value.get('created') or {}, value.get('launch') or {}
    demo = created.get('repo') if created.get('state') != 'absent' else None  # an absent create made nothing
    repo, spec = value.get('repo') or demo, value.get('spec')
    folder = got.get('--setup-state')
    candidate = prepared(folder) if folder else None
    choices = value.get('choices') or {}
    if created.get('state') in ('pending', 'uncertain'):
        step = ('project', 'Creating %s is %s: run create-repo --repo %s --yes again; it reads before it creates.'
                % (created['repo'], created['state'], created['repo']))
    elif not repo and candidate:
        step = ('project', 'This onboarding has no repository yet. Setup prepared %s, perhaps for an earlier '
                'project: ask the owner whether this first fleet is for it. On their yes, run select --repo %s; '
                'otherwise offer the ideas, then choose or create its one repository.' % (candidate, candidate))
    elif not repo:
        step = ('project', 'Offer the ideas, then choose or create its one repository.')
    elif not value.get('setup'):
        step = ('connect', '%sConnect %s with the installed tools, then run continue.' % (
            'Setup already prepared it; ' if candidate == repo else '', repo))
    elif spec and launched.get('spec') == spec and launched.get('state') in ('pending', 'uncertain'):
        step = ('launch', 'The start of spec #%d is uncertain: run launch --spec %d to read its fleet record; '
                'never start it again.' % (spec, spec))
    elif spec and launched.get('spec') == spec and launched.get('state') == 'started':
        step = ('watch', 'Run progress --spec %d.' % spec)
    elif not choices:
        step = ('grill', 'Run the grill unless its summary is already confirmed; then choose the agents.')
    elif choices.get('agents') != 'cloud':
        step = ('agents', '%s %s' % (chosen_line(choices), LOCAL))
    elif choices.get('builder_tables') != 'read':
        step = ('agents', '%s %s' % (chosen_line(choices),
                                     tables_line(choices, 'have not read back this choice yet')))
    elif not spec:
        step = ('plan', 'Confirm the spec, approve the exact plan, then run spec --spec <N> --repo %s.' % repo)
    else:
        step = ('launch', 'Preview with launch --spec %d and ask for a yes to exactly that.' % spec)
    print('Next: %s.' % step[0])
    if repo:
        print('Repository: %s.' % repo)
    print(step[1])
    return 0


def main(argv):
    try:
        command, got = parse(argv)
        if command == 'continue':
            return carry_on(got)
        if command == 'decisions':
            return connect_decisions(got)
        if command == 'create-repo':
            return create_repo(got)
        if command == 'select':
            return select(got)
        if command == 'choose':
            return choose(got)
        if command == 'spec':
            return record_spec(got)
        if command == 'launch':
            return launch(got)
        if command == 'next':
            return resume(got)
        return watch(got)
    except Exit as stop:
        print(stop.args[0])
        return stop.code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
