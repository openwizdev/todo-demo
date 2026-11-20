#!/usr/bin/env python3
"""Start, wake and stop builders through the project's chosen host driver (#1371).

  host.py which                              the host docs/agents/host.md chooses, or `host: none`
  host.py start OWNER/NAME N HARNESS MODEL   start #N's builder through that host's driver
  host.py wake OWNER/NAME N                  wake #N's run, on the host that started it
  host.py stop OWNER/NAME N                  stop #N's run, on the host that started it

Run from the project checkout. The setting is the one `Host: <name>` line of
`docs/agents/host.md` on origin's default branch, read at its current tip and
never from the checkout's copy (records v1, section 6); the driver is
`$OPENWIZ_ADAPTERS/<name>/driver` (driver v1). Each run is saved privately in
$LAUNCH_FLEET_RUNS, {"repo": "owner/name", "runs": {"N": {"host", "run"}}},
before success is printed, so a wake or stop always reaches the driver that
started the run, even after the setting changes. A start first checks that the
runs file's folder is writable. A ticket has one live run: a
new start replaces only a run its driver stopped (`"stopped": true`). Each
save re-reads the file under the lock file beside it, so starts at once keep
every run. A driver answer is taken only in exactly its v1 shape.

A refused start or wake (#1446) is tried twice more, 1 then 2 seconds later. If
the third try is refused too, the fleet's status note on #N says
`stopped (driver start failed)` and #N gets one `launch-fleet: driver start
failed` comment; a refusal while both are there writes neither again. The
comment never carries the driver's own words: it gives a fixed reason, the exit
category (`exit 1: refused`) and a pointer to an entry of the owner-only (0600)
log `driver-failures.log` beside $LAUNCH_FLEET_RUNS, which alone keeps the
driver's raw `error` and `next` (the orchestrator's decision on R3, as KN3's
driver did for its R5). The next start or wake that succeeds marks that comment
cleared and posts a `done` fleet note. The fleet note is written as the fleet
agent: $LAUNCH_FLEET_HARNESS, $LAUNCH_FLEET_MODEL and $LAUNCH_FLEET_SKILLS, as
status.py's --harness, --model and --skills; with any unset, only the fleet
note is skipped, with a warning on stderr naming them. On stdout the driver's
text appears only when it holds no credential, private id or machine path
(status.py's and post.py's rules, any URL with user info, with or without a
scheme, and any value of an environment variable named as a secret, as the
driver kit checks); otherwise it is withheld whole.
A stop or an unknown answer is never retried: a run may exist.

Exit 0: `host: <name>`, `host: none`, `started #N on <host>`, `woke ...` or
`stopped ...`; after a start or wake, a second line `unknown: ...` when #N's
failure report could not be cleared (the next success clears it). Exit 1, one
line: `stopped (driver start failed): the <host> driver refused #N's <start|wake>
3 times; next: <its next>`, ending `; unknown: the ticket's report is incomplete (<why>)`
when the note or the comment failed (each is tried; the next refusal writes what
is missing); `refused: <driver's
error>; next: <its next>` for a stop, or another refusal (nothing was started
or saved); `no run: ...` (use today's room-cli route); `unknown: ...` (a run
may exist: reconcile before any retry).
Exit 2, `host.py: <why>` on stderr: an unreadable setting, driver or runs file,
or unwritable run state; nothing was started.
The driver gets the caller's environment unchanged; this script reads no login.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent


def sibling(name):
    spec = importlib.util.spec_from_file_location('launch_fleet_' + name, HERE / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


status, post = sibling('status'), sibling('post')
SETTING = Path('docs/agents/host.md')
NAME = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')     # a driver's name, as driver v1's schema has it
RUN = re.compile(r'[A-Za-z0-9._:-]{1,100}')       # D2
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
TICKET = re.compile(r'[1-9][0-9]{0,8}')
TIMEOUT = 300
BACKOFF = (1, 2)                                  # #1446: seconds before the second and third tries
RETRIED = ('start', 'wake')
FAILED = 'driver start failed'                    # the fleet note's stopped reason
MARK = 'launch-fleet: driver start failed'        # the failure comment's first line
CLEARED = MARK + ', cleared'
FLEET = ('LAUNCH_FLEET_HARNESS', 'LAUNCH_FLEET_MODEL', 'LAUNCH_FLEET_SKILLS')
WITHHELD = 'withheld, as it held a credential, a private id or a machine path; run the driver by hand'
SECRET_NAME = re.compile(r'TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY$|^KEY')  # the driver kit's rule
# R3: any URL with user info (`user@` or `user:password@` before its host), with or without a scheme;
# stdout only, as the ticket never carries the driver's words (the decision on R3 at 90aed73).
USERINFO = re.compile(r'(?:[a-z][a-z0-9+.-]*:)?//[^\s/?#@]*@|(?<![\w.%+-])[^\s/?#@:]+:[^\s/?#@]*@[a-z0-9]', re.I)
LOG = 'driver-failures.log'                       # owner-only, beside LAUNCH_FLEET_RUNS: the driver's own words


class Unreadable(Exception):
    """Exit 2."""


class Outcome(Exception):
    """Exit 1 with this line."""


class Refused(Outcome):
    """The driver refused, in v1's shape. Its raw words go only to the owner-only driver log; the line is public()."""

    def __init__(self, error, next_):
        super().__init__('refused: %s; next: %s' % (public(error), public(next_)))
        self.error, self.next = error, next_


def public(text):
    """The driver's own text, or WITHHELD when any part of it could be private (#1446)."""
    secrets = [v for k, v in os.environ.items() if SECRET_NAME.search(k.upper()) and len(v) >= 8]
    if any(p.search(text) for _, p in status.PRIVATE) or post.PRIVATE.search(text) or USERINFO.search(text) \
            or any(v in text for v in secrets):
        return WITHHELD
    return text


def git(*args):
    try:
        r = subprocess.run(['git', *args], capture_output=True, text=True, timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Unreadable('git %s did not run: %s' % (args[0], type(e).__name__))
    return r.returncode, r.stdout


def setting_text():
    """The setting file on origin's default branch at its current tip, or None when that tip has no file.

    Never the checkout's copy: a fleet's checkout can be older than the default branch (records v1, section 6)."""
    code, out = git('ls-remote', '--symref', 'origin', 'HEAD')
    branch = re.search(r'(?m)^ref: refs/heads/(\S+)\tHEAD$', out) if code == 0 else None
    tip = re.search(r'(?m)^([0-9a-f]{40})\tHEAD$', out) if code == 0 else None
    if not (branch and tip):
        raise Unreadable("origin's default branch is unreadable: run from the project checkout, with origin reachable")
    code, _ = git('fetch', '--quiet', '--no-tags', '--no-write-fetch-head', 'origin', 'refs/heads/' + branch[1])
    if code != 0 or git('cat-file', '-e', tip[1] + '^{commit}')[0] != 0:
        raise Unreadable("origin's default branch %s could not be fetched at %s" % (branch[1], tip[1]))
    if git('cat-file', '-e', '%s:%s' % (tip[1], SETTING))[0] != 0:
        return None
    code, text = git('show', '%s:%s' % (tip[1], SETTING))
    if code != 0:
        raise Unreadable('%s is unreadable on %s' % (SETTING, branch[1]))
    return text


def chosen():
    """The default branch's setting's host name, or None when the project has no setting file."""
    text = setting_text()
    if text is None:
        return None
    lines = re.findall(r'(?m)^Host:[ \t]*(.*?)[ \t]*$', text)
    if len(lines) != 1 or not NAME.fullmatch(lines[0]) or len(lines[0]) > 40:
        raise Unreadable('%s needs exactly one `Host: <name>` line, the name in lowercase letters, digits and '
                         'hyphens' % SETTING)
    return lines[0]


def driver(host):
    adapters = os.environ.get('OPENWIZ_ADAPTERS', '')
    if not adapters or not os.path.isabs(adapters):
        raise Unreadable('set OPENWIZ_ADAPTERS to the absolute path of an OpenWiz adapters/ folder')
    path = Path(adapters, host, 'driver')
    if not (path.is_file() and os.access(path, os.X_OK)):
        raise Unreadable('no driver for host %s: %s is not an executable file' % (host, path))
    return path


ANSWERS = {'start': {'run'}, 'wake': {'run', 'woke'}, 'stop': {'run', 'stopped'}}


def strict(text):
    """JSON with each key once; None for anything else."""
    def once(pairs):
        if len({k for k, _ in pairs}) != len(pairs):
            raise ValueError('repeated key')
        return dict(pairs)
    try:
        return json.loads(text, object_pairs_hook=once)
    except ValueError:
        return None


def call(host, command, given):
    """The driver's run id, or Outcome on a refusal or any answer that isn't exactly v1's."""
    try:
        r = subprocess.run([str(driver(host)), command], input=json.dumps(given), capture_output=True, text=True,
                           timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise Outcome('unknown: the %s driver did not answer %s (%s); a run may exist, so reconcile before any '
                      'retry' % (host, command, type(e).__name__))
    answer = strict(r.stdout)
    if r.returncode == 1 and isinstance(answer, dict) and set(answer) == {'error', 'next'} \
            and all(isinstance(v, str) and 0 < len(v) <= 300 and '\n' not in v for v in answer.values()):
        raise Refused(answer['error'], answer['next'])
    if r.returncode != 0 or not isinstance(answer, dict) or set(answer) != ANSWERS[command] \
            or not isinstance(answer['run'], str) or not RUN.fullmatch(answer['run']) \
            or any(answer[k] is not True for k in ANSWERS[command] - {'run'}) \
            or (command != 'start' and answer['run'] != given['run']):
        raise Outcome('unknown: the %s driver answered no run; a run may exist, so reconcile before any retry' % host)
    return answer['run']


def tried(host, command, given):
    """call(), with a refused start or wake tried twice more after BACKOFF (#1446)."""
    for wait in BACKOFF if command in RETRIED else ():
        try:
            return call(host, command, given)
        except Refused:
            time.sleep(wait)
    return call(host, command, given)


def fleet():
    """The fleet agent's harness, model and skills for its status note, or None, with a warning on stderr, when
    any is unset: then only the fleet note is skipped (the J87 planner's ruling; requiring them waits for 0.1.1)."""
    values = [os.environ.get(name, '') for name in FLEET]
    missing = [name for name, value in zip(FLEET, values) if not value]
    if missing:
        print('host.py: warning: %s unset, so the fleet status note was not written' % ', '.join(missing),
              file=sys.stderr)
        return None
    return values


def reports(repo, n):
    """#N's newest record-author fleet note is stopped by a failed start, and its uncleared failure comments."""
    authors = post.authors(repo)
    items = post.thread(repo, int(n))
    if items is None:
        raise post.Stop('#%s could not be read' % n)
    ours = [c for c in items if post.ours(c, authors) and isinstance(c.get('body'), str)]
    notes = [f for f in (status.parse(c['body']) for c in sorted(ours, key=lambda c: c.get('id', 0)))
             if f and f['agent'] == 'fleet']
    stopped = bool(notes) and notes[-1]['state'] == 'stopped (%s)' % FAILED
    return stopped, [c for c in ours if c['body'].split('\n', 1)[0] == MARK]


def note(repo, n, state, step):
    identity = fleet()
    if identity is None:
        return
    harness, model, skills = identity
    why = ['--why', FAILED] if state == 'stopped' else []
    r = subprocess.run([sys.executable, '-I', str(HERE / 'status.py'), 'write', '--repo', repo, '--ticket', n,
                        '--agent', 'fleet', '--state', state, *why, '--harness', harness, '--model', model,
                        '--skills', skills, '--step', step], capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode != 0:
        raise post.Stop('the fleet note was not written: %s' % (r.stderr.strip() or 'status.py exit %d' % r.returncode))


def logged(repo, n, host, command, refusal):
    """Append the driver's raw refusal to the owner-only log beside the runs file; its entry's time, or None."""
    stamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    entry = {'time': stamp, 'repo': repo, 'ticket': int(n), 'host': host, 'command': command, 'exit': 1,
             'error': refusal.error, 'next': refusal.next}
    try:
        fd = os.open(str(runs_path().with_name(LOG)), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, (json.dumps(entry, sort_keys=True) + '\n').encode())
        finally:
            os.close(fd)
    except (OSError, Unreadable):
        return None
    return stamp


def report(repo, n, host, command, entry):
    """After the third refusal: the fleet note and one comment on #N, each only when #N lacks it.

    The comment never carries the driver's words (the orchestrator's decision on R3 at 90aed73): a fixed
    reason, the exit category and a pointer to the owner-only log's entry. Each write is tried even when the
    other failed (R1 of the review at 1f9c7f6); post.Stop names every failure."""
    stopped, comments = reports(repo, n)
    failed = [] if entry else ['the driver log %s could not be written' % LOG]
    if not stopped:
        try:
            note(repo, n, 'stopped', "the %s driver refused this builder's %s 3 times; the reason is in a comment "
                                     "here" % (host, command))
        except Exception as e:
            failed.append(why(e))
    if not comments:
        where = ("the fleet's owner can read them in the private driver log, `%s` beside `LAUNCH_FLEET_RUNS`, entry "
                 "%s for #%s." % (LOG, entry, n)) if entry else \
            "they could not be saved to the fleet owner's private driver log, so run the driver by hand to read them."
        try:
            post.comment(repo, int(n), "%s\n\nThe %s driver refused to %s this ticket's builder 3 times (exit 1: "
                                       "refused). Its own words are kept off this public ticket: %s"
                                       % (MARK, host, command, where))
        except Exception as e:
            failed.append(why(e))
    if failed:
        raise post.Stop('; '.join(failed))


def clear(repo, n, host, done):
    """After a success: mark #N's failure comments cleared and follow a stopped fleet note with a done one.

    Each write is tried even when another failed, as report()'s are; post.Stop names every failure."""
    stopped, comments = reports(repo, n)
    failed = []
    for c in comments:
        try:
            post.edit(repo, c['id'], CLEARED + c['body'][len(MARK):] + '\n\nCleared: the %s driver %s it later.'
                      % (host, done))
        except Exception as e:
            failed.append(why(e))
    if stopped:
        try:
            note(repo, n, 'done', 'the %s driver %s this builder on a later try' % (host, done))
        except Exception as e:
            failed.append(why(e))
    if failed:
        raise post.Stop('; '.join(failed))


def attempt(repo, n, host, command, given):
    """tried(); after its last refusal, the Outcome line, with #N told (#1446). The driver's run id."""
    try:
        return tried(host, command, given)
    except Refused as refusal:
        line = "stopped (%s): the %s driver refused #%s's %s 3 times; next: %s" % (FAILED, host, n, command,
                                                                                public(refusal.next))
        try:
            report(repo, n, host, command, logged(repo, n, host, command, refusal))
        except Exception as e:  # nothing started: the next refusal writes what is missing
            line += "; unknown: the ticket's report is incomplete (%s)" % why(e)
        raise Outcome(line)


def cleared(repo, n, host, done):
    """clear() after a success is saved: an `unknown: ...` line when it could not, or None."""
    try:
        clear(repo, n, host, done)
    except Exception as e:  # the run is saved: any failure here only delays the clearing
        return 'unknown: the failure report on #%s was not cleared (%s); the next success clears it' % (n, why(e))
    return None


def why(e):
    """A GitHub step's failure, for a line: its reason without post.py's outcome word, or only the error's kind."""
    return re.sub(r'^(?:unknown|refused): ', '', str(e)) if isinstance(e, post.Stop) else type(e).__name__


def runs_path():
    path = os.environ.get('LAUNCH_FLEET_RUNS', '')
    if not path or not os.path.isabs(path):
        raise Unreadable('set LAUNCH_FLEET_RUNS to an absolute private JSON file, outside the checkout')
    return Path(path)


def load(repo):
    path = runs_path()
    try:
        value = strict(path.read_text())
    except FileNotFoundError:
        return {'repo': repo, 'runs': {}}
    except (OSError, UnicodeDecodeError) as e:
        raise Unreadable('%s is unreadable: %s' % (path, e))
    if not (isinstance(value, dict) and set(value) == {'repo', 'runs'} and value['repo'] == repo
            and isinstance(value['runs'], dict)
            and all(TICKET.fullmatch(k) and isinstance(v, dict)
                    and set(v) in ({'host', 'run'}, {'host', 'run', 'stopped'}) and v.get('stopped', True) is True
                    and isinstance(v['host'], str) and NAME.fullmatch(v['host'])
                    and isinstance(v['run'], str) and RUN.fullmatch(v['run']) for k, v in value['runs'].items())):
        raise Unreadable('%s is not a runs file for %s' % (path, repo))
    return value


def ready(repo):
    """Before a driver runs: the runs file's folder is writable and its lock opens, so a start can be saved."""
    path = runs_path()
    if not (path.parent.is_dir() and os.access(path.parent, os.W_OK | os.X_OK)):
        raise Unreadable('%s is not a writable folder: create it, owner-only, before a start' % path.parent)
    try:
        with open(str(path) + '.lock', 'a'):
            pass
    except OSError as e:
        raise Unreadable('the lock beside %s does not open: %s' % (path, e))
    load(repo)


def record(repo, change):
    """Under the runs file's lock, re-read it, apply change(runs) and save it owner-only, read back.

    False when the save or its read-back failed. Starts at once each keep their run."""
    path = runs_path()
    try:
        with open(str(path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            value = load(repo)
            change(value['runs'])
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.runs-')
            with os.fdopen(fd, 'w') as f:
                json.dump(value, f, sort_keys=True)
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
            return load(repo) == value
    except (OSError, Unreadable):
        return False


def main(argv):
    kind = argv[0] if argv else ''
    if kind == 'which' and len(argv) == 1:
        print('host: %s' % (chosen() or 'none'))
        return 0
    shapes = {'start': 5, 'wake': 3, 'stop': 3}
    if shapes.get(kind) != len(argv) or not REPO.fullmatch(argv[1]) or not TICKET.fullmatch(argv[2]):
        raise Unreadable('usage: which | start OWNER/NAME N HARNESS MODEL | wake OWNER/NAME N | stop OWNER/NAME N')
    repo, n = argv[1], argv[2]
    run = load(repo)['runs'].get(n)
    live = 'refused: #%s already has a run on %s; wake or stop it instead'
    if kind == 'start':
        host = chosen()
        if host is None:
            raise Outcome('refused: no host is chosen in %s' % SETTING)
        driver(host)
        ready(repo)
        if run and not run.get('stopped'):
            raise Outcome(live % (n, run['host']))
        new = attempt(repo, n, host, 'start', {'repository': repo, 'ticket': int(n), 'skill': 'build-ticket',
                                                'harness': argv[3], 'model': argv[4]})

        def add(runs):
            if runs.get(n) != run:  # another start saved a run for #N meanwhile
                raise Outcome('unknown: #%s got a second run, %s on %s; stop one of them' % (n, new, host))
            runs[n] = {'host': host, 'run': new}
        if not record(repo, add):
            raise Outcome('unknown: #%s started on %s but its run was not saved; save run %s on host %s for #%s '
                          'privately before anything else' % (n, host, new, host, n))
        print('started #%s on %s' % (n, host))
        unclear = cleared(repo, n, host, 'started')
        if unclear:
            print(unclear)
        return 0
    if not run:
        raise Outcome('no run: #%s was not started through a driver' % n)
    unclear = None
    if kind == 'wake':
        attempt(repo, n, run['host'], kind, {'run': run['run']})
        unclear = cleared(repo, n, run['host'], 'woke')
    else:
        call(run['host'], kind, {'run': run['run']})
    if kind == 'stop' and not run.get('stopped'):
        def stopped(runs):
            if runs.get(n, {}).get('run') == run['run']:
                runs[n]['stopped'] = True
        if not record(repo, stopped):
            raise Outcome('unknown: #%s stopped on %s but that was not saved' % (n, run['host']))
    print('%s #%s on %s' % ({'wake': 'woke', 'stop': 'stopped'}[kind], n, run['host']))
    if unclear:
        print(unclear)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except Outcome as e:
        print(e)
        sys.exit(1)
    except Unreadable as e:
        print('host.py: %s' % e, file=sys.stderr)
        sys.exit(2)
