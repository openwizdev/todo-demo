#!/usr/bin/env python3
"""Write and check agent status notes: contracts/agent-status.v1.md (#1254, revision 4).

  status.py write --repo OWNER/NAME --ticket N --agent KIND --state STATE [--why TEXT]
                  --harness TEXT --model TEXT --skills 'SKILL@X.Y.Z[, ...]' --step TEXT [--pr URL] [--preview URL]
                  [--time TIME] [--note ID]
  status.py run --repo OWNER/NAME --ticket N --agent KIND --note ID [--every SECONDS] -- COMMAND...
  status.py check --repo OWNER/NAME
  status.py repair --repo OWNER/NAME --harness TEXT --model TEXT --skills 'launch-fleet@X.Y.Z'

write: exit 0 written and read back, 2 refused or failed (a refusal comes before any
call; a failure after a write is repaired by running the same write again), 3 stop:
the claim is another note's or the fence stopped it (nothing more written). An edit
reads back too (#1441): it steps down when another live note of its kind appeared, and
puts back a release a sibling wake wrote between its read and its edit.
run (#1447): a heartbeat before COMMAND starts and every --every seconds (default 600)
while it runs: an edit of note ID as it reads now, only its time set to now, so GitHub's
updated_at, which alone counts toward the 30-minute lease, is new (a note written this same
second waits for the next). A beat whose read shows the note done or stopped writes nothing.
A failed beat is reported and tried again after 60 seconds (or --every, if shorter). When no
beat can start 120 seconds before the lease of the last good one ends, or on the fence exit,
it stops COMMAND's whole process group (SIGTERM, then SIGKILL to any of it left after 10
seconds) and exits 3. Otherwise it exits as COMMAND does. A refusal or failure before COMMAND
starts exits 2.
check: exit 0 no mismatch, 1 mismatches printed, 2 could not read. It never writes.
repair (#1592): the wake's check and fix. For each asking note with no needs-info it reads
the ticket's notes again and, while a live note still asks, records the repair in its own
fleet note (working), adds the label and reads again. Once no live note asks, it takes off
only the application its own POST made in this wake, puts back a person's application its
DELETE took, and edits its note to done. A wake that stops part way leaves the note working;
the next wake settles that ticket from it. It deletes only under a GitHub App's own login
(#1702): a needs-info it didn't apply in this wake, or any needs-info while it acts as a
person's own account, stays and is reported. It prints each change and every other
mismatch, one report line each: exit 0 nothing to report, 1 lines printed, 2
`status check failed: <why>`.
Every GitHub call goes through `gh api`.
"""
import argparse
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import os
import re
import signal
import subprocess
import sys
import time

sys.dont_write_bytecode = True

MARKER = '<!-- openwiz:status v1 -->'
LEASE = timedelta(minutes=30)
EVERY = 600         # run's default seconds between beats: three beats in each lease
EVERY_MOST = 900    # at most half the lease, leaving room to retry a failed beat
RETRY = 60          # seconds before a failed beat is tried again (#62 R3)
MARGIN = 120        # seconds a beat's GitHub calls may take: no beat starts later than this
                    # before the lease ends, counted from the start of the last good beat
GRACE = 10          # seconds between SIGTERM and SIGKILL when run stops the command
KINDS = ('builder', 'reviewer', 'fleet')
STATES = ('working', 'asking', 'done', 'stopped')
CLAIMING = ('working', 'asking')
ASKING_LABEL = 'needs-info'
# Key, longest value, required. The order is the note's line order.
KEYS = (('agent', 300, True), ('state', 300, True), ('harness', 60, True), ('model', 60, True),
        ('skills', 300, True), ('step', 300, True), ('time', 300, True), ('pr', 300, False), ('preview', 300, False))
REPO = re.compile(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+')
TIME = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
STATE = re.compile(r'(working|asking|done|stopped)( \(([^()]{1,100})\))?')
SKILL = r'[a-z0-9]+(?:-[a-z0-9]+)*@[0-9]+\.[0-9]+\.[0-9]+'
SKILLS = re.compile(rf'{SKILL}(?:, {SKILL})*')
PR = re.compile(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*')
# A public https page: a domain-name host, no user, password, query or fragment (R3).
PREVIEW = re.compile(r'https://(?![^/:]*\.(?:local|internal|lan|localhost)(?:[:/]|$))'
                     r'(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::[0-9]{1,5})?(?:/[^\s"<>?#@\\]*)?')
CONTROL = re.compile(r'[\x00-\x1f\x7f]')
QUOTE = re.compile('["“”]')
# What a note never holds. A guard fails closed: every thr_ token, synthetic or not.
PRIVATE = (
    ('a thread id', re.compile(r'(?<![A-Za-z0-9])thr_', re.I)),
    ('a CloudRoom id', re.compile(r'(?<![A-Za-z0-9])(?:proj|prj|mch|usr|acct|auto|cr)_[A-Za-z0-9]', re.I)),
    ('a machine path', re.compile(
        r'(?<![\w.:/~-])(?:~/|/(?:Users|home|root|tmp|var|private|mnt|Volumes|opt|srv|code)(?:/|\b))', re.I)),
    ('a machine path', re.compile(r'(?<![A-Za-z0-9])[A-Za-z]:\\')),
    # R3: any absolute path of two or more parts; a URL's own path is preceded by its host.
    ('a machine path', re.compile(r'(?<![\w.:/~@%$}\\-])/[\w.~+-]+/[\w.~+-]')),
    ('a machine path', re.compile(r'\$\{?HOME\b|%(?:USERPROFILE|HOMEPATH|HOMEDRIVE|APPDATA|LOCALAPPDATA)%', re.I)),
    ('a machine path', re.compile(r'\\\\[\w.$-]+\\')),
    ('a machine path', re.compile(r'\bfile:', re.I)),
    ('a credential', re.compile(
        r'\b(?:[a-z_]*token|[a-z_]*key|secret|password|passwd|pwd|sig|signature|auth|credentials?)\s*=', re.I)),
    ('a credential', re.compile(r'\b(?:password|passwd|secret|token)\s*:\s*\S|\bbearer\s+\S', re.I)),
    ('a credential', re.compile(r'\bgh[pousr]_[A-Za-z0-9]{8,}|\bgithub_pat_|\bAKIA[0-9A-Z]{16}\b'
                                r'|\bxox[abprs]-|\bsk-[A-Za-z0-9_-]{16,}')),
)
MANIFEST = Path(__file__).resolve().parents[3] / '.claude-plugin' / 'plugin.json'


class Refused(Exception):
    pass


class Failed(Exception):
    pass


class Stop(Exception):
    pass


def refuse(field, why):
    raise Refused(f'{field}: {why}')


def plain(field, value, longest):
    if not value:
        refuse(field, 'empty')
    if CONTROL.search(value):
        refuse(field, 'not one line of plain text')
    if len(value) > longest:
        refuse(field, f'longer than {longest} characters')
    for what, pattern in PRIVATE:
        if pattern.search(value):
            refuse(field, f'holds {what}')
    if QUOTE.search(value) or value.startswith('>'):
        refuse(field, 'holds quoted words')


def shaped(fields):
    """Refused naming the field (never echoing the value), or None: the contract's shape."""
    for key, longest, required in KEYS:
        if key in fields:
            plain(key, fields[key], longest)
        elif required:
            refuse(key, 'missing')
    if fields['agent'] not in KINDS:
        refuse('agent', 'not builder, reviewer or fleet')
    if not STATE.fullmatch(fields['state']) or (fields['state'].startswith(('working', 'asking', 'done'))
                                                 and fields['state'] not in STATES):
        refuse('state', 'not working, asking, done, stopped or stopped (<why>)')
    if not SKILLS.fullmatch(fields['skills']):
        refuse('skills', 'not <skill>@<major>.<minor>.<patch>, joined by a comma and a space')
    if not TIME.fullmatch(fields['time']):
        refuse('time', 'not YYYY-MM-DDTHH:MM:SSZ')
    if 'pr' in fields and not PR.fullmatch(fields['pr']):
        refuse('pr', 'not a GitHub pull request link')
    if 'preview' in fields and not PREVIEW.fullmatch(fields['preview']):
        refuse('preview', 'not an https link')


def bound(skills):
    """R5: every reported skill is one the installed package lists, at its version.

    The package is the one supplying this script; its manifest is the evidence.
    Which skills an agent actually ran is its caller's record (AP2).
    """
    try:
        manifest = json.loads(MANIFEST.read_text())
        version, listed = manifest['version'], manifest['skills']
        if not (isinstance(version, str) and re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
                and isinstance(listed, list) and all(isinstance(x, str) for x in listed)):
            raise ValueError('malformed')
    except (OSError, ValueError, KeyError, TypeError):
        refuse('skills', 'the installed package has no readable manifest')
    names = {x[len('./skills/'):] for x in listed if x.startswith('./skills/')}
    for item in skills.split(', '):
        name, _, at = item.partition('@')
        if name not in names or at != version:
            refuse('skills', f'a skill or version the installed package (openwiz {version}) does not have')


def body(fields):
    return '\n'.join([MARKER] + [f'{key}: {fields[key]}' for key, _, _ in KEYS if key in fields])


def parse(text):
    """A note's fields, or None when it doesn't read exactly as the contract says."""
    lines = (text or '').replace('\r\n', '\n').split('\n')
    if lines[0] != MARKER:
        return None
    fields = {}
    for line in lines[1:]:
        key, sep, value = line.partition(': ')
        if not sep or key in fields or key not in dict((k, 0) for k, _, _ in KEYS):
            return None
        fields[key] = value
    try:
        shaped(fields)
    except Refused:
        return None
    return fields


def gh(method, path, payload=None, accept=None, raw=False):
    command = ['gh', 'api', '--method', method, path]
    if accept:
        command += ['-H', accept]
    if payload is not None:
        command += ['--input', '-']
    try:
        result = subprocess.run(command, input=None if payload is None else json.dumps(payload),
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Failed(f'{method} {path}: {error}')
    if result.returncode != 0:
        raise Failed(f'{method} {path}: {result.stderr.strip()[:300]}')
    if raw:
        return result.stdout
    try:
        return json.loads(result.stdout) if result.stdout.strip() else None
    except ValueError:
        raise Failed(f'{method} {path}: not JSON')


def pages(path):
    """Every item of a paged REST list."""
    items, page = [], 1
    while True:
        chunk = gh('GET', f'{path}?per_page=100&page={page}')
        if not isinstance(chunk, list):
            raise Failed(f'GET {path}: not a list')
        if not chunk:
            return items
        items += chunk
        page += 1


def record_authors(repo):
    spec = importlib.util.spec_from_file_location('grants', Path(__file__).resolve().parent / 'grants.py')
    grants = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grants)
    try:
        text = gh('GET', f'repos/{repo}/contents/docs/agents/fleet.md',
                  accept='Accept: application/vnd.github.raw', raw=True)
        return grants.record_authors(text)
    except (Failed, ValueError) as error:
        raise Failed(f'no record authors in docs/agents/fleet.md: {error}')


def when(stamp):
    return datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def notes(comments, authors):
    """The record authors' readable notes, oldest first: (id, fields, updated, author)."""
    found = []
    for item in comments:
        login = item['user']['login'] if isinstance(item.get('user'), dict) else None
        fields = parse(item.get('body'))
        if isinstance(login, str) and login.lower() in authors and fields:
            found.append((int(item['id']), fields, when(item['updated_at']), login.lower()))
    return sorted(found, key=lambda n: n[0])


def live(note, now):
    return note[1]['state'] in CLAIMING and now - note[2] < LEASE


def holder(found, kind, now):
    """The oldest live note of KIND, which holds its claim, or None."""
    return next((n for n in found if n[1]['agent'] == kind and live(n, now)), None)


def viewer():
    """The acting login, as GitHub's viewer names it, or None when the token can't name itself."""
    try:
        login = gh('POST', 'graphql', {'query': 'query { viewer { login } }'})['data']['viewer']['login']
    except (Failed, KeyError, TypeError):
        return None
    return login if isinstance(login, str) and login else None


EDITS = '''query($id: ID!, $n: Int!) {
  node(id: $id) { ... on IssueComment { userContentEdits(first: $n) { nodes { diff editedAt } } } }
}'''
HISTORY = 20


def replaced(made, fields, floor=None):
    """The note under this writer's edits, from GitHub's edit history (newest first, each the
    full body), or None when there is none. It skips this edit's own earlier tries, which a retry
    after exit 2 leaves (the same write: the same fields but the time), so a release under the
    first try is still found, but only a release that landed once the oldest try had started
    (its editedAt at or after that try's time, which the writer stamps before it reads). A release
    this agent read and then resumed stays under its resume (#57 R1). Later edits by others may
    sit above this edit. A heartbeat passes FLOOR, the time of the note it last saw written
    and read back: earlier beats at or under it are acknowledged, never retries (#62 R2)."""
    try:
        found = gh('POST', 'graphql', {'query': EDITS, 'variables': {'id': made['node_id'], 'n': HISTORY}})
        nodes = found['data']['node']['userContentEdits']['nodes']
        texts = [x['diff'] for x in nodes]
        stamps = [x['editedAt'] for x in nodes]
    except (KeyError, TypeError, ValueError) as error:
        raise Failed(f'note {made.get("id")} was edited but its edit history was not read: {error!r}')
    if not all(isinstance(x, str) for x in texts + stamps):
        raise Failed(f'note {made.get("id")} was edited but its edit history was not read')
    versions = [parse(x) for x in texts]
    k = next((j for j, v in enumerate(versions) if v == fields), None)
    if k is None:
        raise Failed(f'note {made.get("id")} was edited but its edit history does not hold the edit')
    same = {key: value for key, value in fields.items() if key != 'time'}
    first = k = k + 1
    while (k < len(versions) and versions[k] and dict(versions[k], time=None) == dict(same, time=None)
           and not (floor is not None and versions[k]['time'] <= floor)):
        k += 1
    if k < len(versions):
        if k > first and versions[k] and versions[k]['state'] not in CLAIMING:
            try:
                unread = when(stamps[k].replace('.000', '')[:19] + 'Z') >= when(versions[k - 1]['time'])
            except ValueError:
                raise Failed(f'note {made.get("id")} was edited but its edit history has no readable time')
            if not unread:
                return texts[k - 1]
        return texts[k]
    if len(texts) >= HISTORY:
        raise Failed(f'note {made.get("id")} was edited but its edit history is too long to read past it')
    return None


def step_down(found, note_id, kind, fields, repo):
    """After a claim edit: when another live note of its kind exists, stop this one and Stop."""
    other = next((x for x in found if x[0] != note_id and x[1]['agent'] == kind
                  and live(x, datetime.now(timezone.utc))), None)
    if other:
        gh('PATCH', f'repos/{repo}/issues/comments/{note_id}',
           {'body': body(dict(fields, state='stopped (lost claim)'))})
        raise Stop(f'note {other[0]} holds the {kind} claim; note {note_id} is stopped (lost claim)')


def next_beat(now, ok_at, every, failed):
    """#62 R3: seconds until the next beat, or None when no beat can still land inside the lease.
    OK_AT is when the last good beat started (its edit landed after), FAILED whether the last beat
    failed. A failed beat is tried again after RETRY seconds, never later than MARGIN seconds
    before the lease ends."""
    deadline = ok_at + LEASE.total_seconds() - MARGIN
    if now >= deadline:
        return None
    due = now + min(RETRY, every) if failed else ok_at + every
    return max(0, min(due, deadline) - now)


def stop_group(proc):
    """#62 R1: stop the command's whole process group: SIGTERM, then SIGKILL to whatever of the
    group is left after GRACE seconds, even once the command itself has exited."""
    def alive():
        proc.poll()
        try:
            os.killpg(proc.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
    if not alive():
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    end = time.monotonic() + GRACE
    while time.monotonic() < end and alive():
        time.sleep(0.1)
    if alive():
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


def asked_last_by(repo, n, login):
    """True when the issue's events show LOGIN added needs-info last (R1: the writer's own label)."""
    added = [e for e in pages(f'repos/{repo}/issues/{n}/events')
             if e.get('event') == 'labeled' and (e.get('label') or {}).get('name') == ASKING_LABEL]
    actor = (added[-1].get('actor') or {}).get('login') if added else None
    return isinstance(actor, str) and actor.lower() == login.lower()


def write(args, now, beat=False, out=sys.stdout, retried=False):
    """One write. A BEAT (#1447) takes the note's own fields as its re-read shows them, with
    only time set to now, and stops on a note that is done or stopped: it never reopens one."""
    if not beat:
        state = args.state if args.why is None else f'{args.state} ({args.why})'
        if args.why is not None and args.state != 'stopped':
            refuse('state', 'only stopped carries a reason')
        fields = {'agent': args.agent, 'state': state, 'harness': args.harness, 'model': args.model,
                  'step': args.step, 'time': args.time or now.strftime('%Y-%m-%dT%H:%M:%SZ')}
        for key in ('skills', 'pr', 'preview'):
            if getattr(args, key) is not None:
                fields[key] = getattr(args, key)
        shaped(fields)
        bound(fields['skills'])
    if args.note is not None and not re.fullmatch(r'[1-9][0-9]*', args.note):
        refuse('note', 'not a comment id')
    repo, n, kind = args.repo, args.ticket, args.agent
    authors = record_authors(repo)
    # R4: a writer whose login isn't a record author writes nothing: its note would never count.
    login = viewer()
    if login is not None and login.lower() not in authors:
        raise Failed(f'the acting login {login} is not a record author in docs/agents/fleet.md')
    comments = f'repos/{repo}/issues/{n}/comments'
    found = notes(pages(comments), authors)
    if args.note is not None:
        own = next((x for x in found if x[0] == int(args.note)), None)
        if own is None:
            raise Stop(f'note {args.note} is not a record author\'s status note on #{n}')
        if own[1]['agent'] != kind:
            raise Stop(f'note {args.note} is a {own[1]["agent"]} note')
        if own[1]['state'].startswith('stopped'):
            raise Stop(f'note {args.note} is {"stopped: a heartbeat never reopens it" if beat else "stopped"}')
        if beat:
            if own[1]['state'] not in CLAIMING:
                raise Stop(f'note {args.note} is {own[1]["state"]}: a heartbeat never reopens it')
            fields = dict(own[1], time=now.strftime('%Y-%m-%dT%H:%M:%SZ'))
            if fields == own[1]:
                # #62 R4: written this very second. An unchanged body is no edit on GitHub, so
                # wait for the next second and read again.
                if retried:
                    raise Failed(f'note {args.note} already holds this second; nothing to beat')
                time.sleep(1)
                return write(args, datetime.now(timezone.utc), beat, out, retried=True)
            if args.floor is None:
                args.floor = own[1]['time']
            state = args.state = fields['state']
        # R2: whoever holds the claim now, older or newer, fences out every other note of its kind.
        first = holder(found, kind, now)
        if first and first[0] != own[0]:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        made = gh('PATCH', f'repos/{repo}/issues/comments/{own[0]}', {'body': body(fields)})
        note_id, verb = own[0], 'edited'
    else:
        first = holder(found, kind, now)
        if args.state in CLAIMING and first:
            raise Stop(f'note {first[0]} holds the {kind} claim')
        made = gh('POST', comments, {'body': body(fields)})
        note_id, verb = int(made['id']), 'posted'
    author = made['user']['login'] if isinstance(made.get('user'), dict) else None
    if not (isinstance(author, str) and author.lower() in authors):
        # R4: a token that can't name itself is judged by the note GitHub stored.
        if verb == 'posted':
            gh('DELETE', f'repos/{repo}/issues/comments/{note_id}')
        raise Failed(f'note {note_id} was written by {author}, not a record author; it was deleted')
    login = login or author
    # R4: success, and any label, only once a trusted read-back shows the note as written.
    found = notes(pages(comments), authors)
    mine = next((x for x in found if x[0] == note_id), None)
    if verb == 'edited' and args.state in CLAIMING:
        # #1441: the edit landed after its read, so read back as a post does. A release this
        # writer never read, landed under its edit (a sibling wake's), is put back: a release is
        # never lost (P3), even when a later edit has changed the note since (#1463 R1). A
        # release it read, it may resume, as a builder answering a review does.
        try:
            prior = parse(replaced(made, fields, args.floor if beat else None))
        except Failed:
            # #62 R2: an edit history that can't settle the release still leaves the claim to
            # a newer live holder: step down first, then report the failure.
            step_down(found, note_id, kind, fields, repo)
            raise
        if prior and prior['state'] not in CLAIMING and prior != own[1]:
            if mine is None:
                raise Failed(f'note {note_id} was edited over a release but not read back')
            if mine[1]['state'] in CLAIMING:
                gh('PATCH', f'repos/{repo}/issues/comments/{note_id}', {'body': body(prior)})
            raise Stop(f'note {note_id} was {prior["state"].split(" ")[0]} before this edit landed; '
                       'the release is put back')
    if mine is None or mine[1] != fields:
        raise Failed(f'note {note_id} was {verb} but not read back')
    if verb == 'posted' and args.state in CLAIMING:
        first = holder(found, kind, datetime.now(timezone.utc))
        if first and first[0] < note_id:
            gh('PATCH', f'repos/{repo}/issues/comments/{note_id}',
               {'body': body(dict(fields, state='stopped (lost claim)'))})
            raise Stop(f'note {first[0]} holds the {kind} claim; note {note_id} is stopped (lost claim)')
    if verb == 'edited' and args.state in CLAIMING:
        # #1441: a newer note that claimed while this one had lapsed keeps the claim (P1, P2, P4).
        step_down(found, note_id, kind, fields, repo)
    # R1: settle needs-info from what GitHub shows now, so a retry repairs a failed label write.
    labels = [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]
    asking = any(x[1]['state'] == 'asking' and live(x, datetime.now(timezone.utc)) for x in found)
    if asking and ASKING_LABEL not in labels:
        gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
    elif not asking and ASKING_LABEL in labels and asked_last_by(repo, n, login):
        gh('DELETE', f'repos/{repo}/issues/{n}/labels/{ASKING_LABEL}')
    print(f'#{n}: {kind} {state}, status note {note_id} {verb}', file=out)
    return fields


def run(args):
    """#1447: keep the claim live while COMMAND runs; stop COMMAND when the claim is lost."""
    command = args.cmd[1:] if args.cmd[:1] == ['--'] else args.cmd
    if not command:
        refuse('command', 'missing: run --note ID -- COMMAND...')
    if not re.fullmatch(r'[1-9][0-9]*', args.every) or int(args.every) > EVERY_MOST:
        refuse('every', f'not a whole number of seconds from 1 to {EVERY_MOST}')
    if args.note is None or not re.fullmatch(r'[1-9][0-9]*', args.note):
        refuse('note', 'not a comment id')
    every = int(args.every)
    args.floor = None
    ok_at = time.monotonic()
    try:
        args.floor = write(args, datetime.now(timezone.utc), beat=True, out=sys.stderr)['time']
    except Stop as error:
        raise Stop(f'{error}; the command was not started')
    # Its own process group, so a stop reaches everything COMMAND started.
    try:
        proc = subprocess.Popen(command, start_new_session=True)
    except OSError as error:
        raise Failed(f'command: could not start: {error.strerror}')
    # A run that is itself stopped stops COMMAND too, through the cleanup below.
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda number, _: sys.exit(128 + number))
    failed, finished = False, False
    try:
        while True:
            wait = next_beat(time.monotonic(), ok_at, every, failed)
            if wait is None:
                raise Stop(f'note {args.note} could not be kept live inside the lease; the command is stopped')
            try:
                code = proc.wait(timeout=wait)
                finished = True
                return code if code >= 0 else 128 - code
            except subprocess.TimeoutExpired:
                pass
            started = time.monotonic()
            try:
                args.floor = write(args, datetime.now(timezone.utc), beat=True, out=sys.stderr)['time']
                ok_at, failed = started, False
            except Stop as error:
                raise Stop(f'{error}; the command is stopped')
            except (Failed, KeyError, TypeError, IndexError, ValueError) as error:
                # The note stays live until the lease ends; the beat is tried again well before
                # that, and its fence still stops the command if another note claimed meanwhile.
                failed = True
                print(f'status.py: heartbeat failed, trying again in {min(RETRY, every)}s: {error}',
                      file=sys.stderr)
    finally:
        if not finished:
            stop_group(proc)

QUERY = '''query($owner: String!, $name: String!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    issues(states: OPEN, first: 50, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        labels(first: 100) { nodes { name } }
        comments(first: 100) { pageInfo { hasNextPage } nodes { databaseId author { login } body updatedAt } }
        closedByPullRequestsReferences(first: 50, includeClosedPrs: true) { nodes { number state url } }
      }
    }
  }
}'''


def mismatches(number, labels, found, prs, now):
    lines = []
    merged = [pr['url'] for pr in prs if pr['state'] == 'MERGED']
    for note in found:
        nid, fields, updated = note[:3]
        state, kind = fields['state'], fields['agent']
        if state not in CLAIMING:
            continue
        head = f'#{number} note {nid} {kind} {state}'
        first = holder(found, kind, now)
        if merged:
            lines.append(f'{head}: pull request {merged[0]} merged')
        elif not live(note, now):
            lines.append(f'{head}: lapsed, no edit for 30 minutes')
        elif state == 'asking' and ASKING_LABEL not in labels:
            lines.append(f'{head}: no {ASKING_LABEL} label')
        elif first[0] != nid:
            lines.append(f'{head}: note {first[0]} holds the {kind} claim')
    return lines


def scan(repo, authors, now):
    """Every open issue: (number, its readable notes, its mismatch lines)."""
    owner, name = repo.split('/')
    cursor, found = None, []
    while True:
        page = gh('POST', 'graphql', {'query': QUERY,
                                      'variables': {'owner': owner, 'name': name, 'cursor': cursor}})
        issues = page['data']['repository']['issues']
        for issue in issues['nodes']:
            if issue['comments']['pageInfo']['hasNextPage']:
                comments = pages(f'repos/{repo}/issues/{issue["number"]}/comments')
            else:
                comments = [{'id': c['databaseId'], 'user': c['author'], 'body': c['body'],
                             'updated_at': c['updatedAt']} for c in issue['comments']['nodes']]
            own = notes(comments, authors)
            found.append((issue['number'], own, mismatches(
                issue['number'], [label['name'] for label in issue['labels']['nodes']],
                own, issue['closedByPullRequestsReferences']['nodes'], now)))
        if not issues['pageInfo']['hasNextPage']:
            break
        cursor = issues['pageInfo']['endCursor']
    return found


def check(args, now):
    found = [line for _, _, lines in scan(args.repo, record_authors(args.repo), now) for line in lines]
    for line in found:
        print(line)
    return 1 if found else 0


# #1592 (#68 R1): the repair's record is its own fleet note on the ticket, working from just
# before its label write until the label is settled, then done. A wake that stops in between
# leaves it working, and the next wake settles the ticket from it.
REPAIRING = 'adding needs-info for an asking note'
REPAIRED = 'settled needs-info'


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def record(repo, n, base, state, step, note_id=None):
    """Post or edit the repair's fleet note: (its id, GitHub's time for this write)."""
    fields = dict(base, state=state, step=step, time=stamp())
    if note_id is None:
        made = gh('POST', f'repos/{repo}/issues/{n}/comments', {'body': body(fields)})
    else:
        made = gh('PATCH', f'repos/{repo}/issues/comments/{note_id}', {'body': body(fields)})
    if not (isinstance(made.get('updated_at'), str) and TIME.fullmatch(made['updated_at'])):
        raise Failed(f'the repair note on #{n} was written but GitHub gave no time for it')
    return int(made['id']), made['updated_at']


def label_events(repo, n):
    return [e for e in pages(f'repos/{repo}/issues/{n}/events')
            if e.get('event') in ('labeled', 'unlabeled') and (e.get('label') or {}).get('name') == ASKING_LABEL]


def by(event, login):
    actor = (event.get('actor') or {}).get('login')
    return isinstance(actor, str) and actor.lower() == login.lower()


def cleanup(repo, n, login, mine, labelled):
    """Take off the needs-info this wake's own POST applied (#68 R2): only when that application,
    event MINE of the label timeline, is still the last one. GitHub's DELETE takes whatever label is
    there when it lands, so the timeline is read again after it: a person's application that landed
    between the read and the DELETE is put back, and reported. The report lines."""
    events = label_events(repo, n)
    if labelled():
        last = max(k for k, e in enumerate(events) if e['event'] == 'labeled')
        if last != mine:
            return []
        gh('DELETE', f'repos/{repo}/issues/{n}/labels/{ASKING_LABEL}')
        events = label_events(repo, n)
    after = events[mine + 1:]
    off = [k for k, e in enumerate(after) if e['event'] == 'unlabeled' and by(e, login)]
    if not off:
        return []
    people = [e for e in after[:off[-1]] if e['event'] == 'labeled' and not by(e, login)]
    if not people or labelled():
        return []
    gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
    who = people[-1]['actor']['login']
    return [f'#{n}: {ASKING_LABEL} put back: {who} applied it as the repair took it off; check whose it is']


def app(login):
    """#82 R1: only a GitHub App's own login (`<name>[bot]`, which no person can sign in as)
    tells the repair's label events from a person's. Under any other login, such as a person's
    own account shared with the agents, the repair never deletes: it reports instead."""
    return login.endswith('[bot]')


def left(repo, n, login, labelled):
    """#1702: a needs-info this wake can't prove it applied stays. While agents post as a person's
    own account, an application under the repair's login may be that person's hold, or a put-back
    of one, so it is reported, never taken off. The report lines."""
    if not labelled():
        return []
    # Silent only when the last listed application is provably someone else's.
    applied = [e for e in label_events(repo, n) if e['event'] == 'labeled']
    if applied and not by(applied[-1], login):
        return []
    return [f'#{n}: {ASKING_LABEL} left on: no note asks, and the repair can\'t tell whether it or a person '
            'added it; check whose it is']


def settle(repo, n, authors, login, base, pending):
    """#1592: needs-info on one ticket from its notes as they are now, read again after the
    label write, so an agent that resumed meanwhile is never marked as asking. PENDING is the
    repair's own working fleet note from a wake that stopped part way, or None. The report lines."""
    comments = f'repos/{repo}/issues/{n}/comments'

    def asking():
        now = datetime.now(timezone.utc)
        return next((x for x in notes(pages(comments), authors) if x[1]['state'] == 'asking' and live(x, now)), None)

    def labelled():
        return ASKING_LABEL in [label['name'] for label in gh('GET', f'repos/{repo}/issues/{n}')['labels']]

    still = asking()
    if pending is None:
        if still is None or labelled():
            return []
        fleet = [x for x in notes(pages(comments), authors) if x[1]['agent'] == 'fleet' and x[3] == login.lower()]
        note_id = record(repo, n, base, 'working', REPAIRING, fleet[-1][0] if fleet else None)[0]
    else:
        note_id = pending[0]
    report, mine = [], None
    if still is not None and not labelled():
        # #1702: the label's own application is the one new event its POST leaves, under its login.
        # One from an earlier wake can't be told from a person's under the same login.
        before = len(label_events(repo, n))
        gh('POST', f'repos/{repo}/issues/{n}/labels', {'labels': [ASKING_LABEL]})
        new = label_events(repo, n)[before:]
        if app(login) and len(new) == 1 and new[0]['event'] == 'labeled' and by(new[0], login):
            mine = before
        still = asking()
        if still is not None:
            report.append(f'#{n} note {still[0]} {still[1]["agent"]} asking: {ASKING_LABEL} added')
    if still is None:
        report += left(repo, n, login, labelled) if mine is None else cleanup(repo, n, login, mine, labelled)
    record(repo, n, base, 'done', REPAIRED, note_id)
    return report


def guarded(what, act):
    """ACT's result, or Failed naming WHAT: a GitHub answer of the wrong shape fails too."""
    try:
        return act()
    except Failed as error:
        raise Failed(f'{what}: {error}')
    except (KeyError, TypeError, IndexError, ValueError) as error:
        raise Failed(f'{what}: unexpected GitHub answer: {error!r}')


def repair(args, now):
    base = {'agent': 'fleet', 'harness': args.harness, 'model': args.model, 'skills': args.skills}
    try:
        shaped(dict(base, state='working', step=REPAIRING, time=stamp()))
        bound(args.skills)
    except Refused as error:
        raise Failed(f'refused: {error}')

    def read():
        authors = record_authors(args.repo)
        return authors, scan(args.repo, authors, now)

    authors, found = guarded('could not read', read)
    login = viewer()
    reported = 0
    for n, own, lines in found:
        # Without its own login the repair can't tell its label from a person's: it reports.
        pending = None if login is None else next(
            (x for x in reversed(own) if x[1]['agent'] == 'fleet' and x[3] == login.lower()
             and x[1]['state'] == 'working' and x[1]['step'] == REPAIRING), None)
        asks = any(line.endswith(f': no {ASKING_LABEL} label') for line in lines)
        if login is not None and (asks or pending):
            settled = guarded(f'could not repair #{n}', lambda: settle(args.repo, n, authors, login, base, pending))
            lines = [line for line in lines if not line.endswith(f': no {ASKING_LABEL} label')
                     and not (pending and line.startswith(f'#{n} note {pending[0]} '))] + settled
        for line in lines:
            # Each line as it is settled: a later failure never hides an earlier change.
            print(line, flush=True)
            reported += 1
    return 1 if reported else 0


def main(argv):
    parser = argparse.ArgumentParser(prog='status.py')
    sub = parser.add_subparsers(dest='command', required=True)
    w = sub.add_parser('write')
    for flag in ('--repo', '--ticket', '--agent', '--state', '--harness', '--model', '--step'):
        w.add_argument(flag, required=True)
    # --skills has no default: a missing one is refused as the contract's missing field.
    for flag in ('--skills', '--why', '--pr', '--preview', '--time', '--note'):
        w.add_argument(flag)
    r = sub.add_parser('run')
    for flag in ('--repo', '--ticket', '--agent', '--note'):
        r.add_argument(flag, required=True)
    r.add_argument('--every', default=str(EVERY))
    r.add_argument('cmd', nargs=argparse.REMAINDER, metavar='COMMAND')
    c = sub.add_parser('check')
    c.add_argument('--repo', required=True)
    r = sub.add_parser('repair')
    for flag in ('--repo', '--harness', '--model', '--skills'):
        r.add_argument(flag, required=True)
    args = parser.parse_args(argv)
    now = datetime.now(timezone.utc)
    try:
        if not REPO.fullmatch(args.repo):
            raise Refused('repo: not OWNER/NAME')
        if args.command == 'check':
            try:
                return check(args, now)
            except Failed as error:
                raise Failed(f'could not read: {error}')
            except (KeyError, TypeError, IndexError, ValueError) as error:
                raise Failed(f'could not read: unexpected GitHub answer: {error!r}')
        if args.command == 'repair':
            # R2: a failed check is a report line of its own, never a clean pass.
            try:
                return repair(args, now)
            except Failed as error:
                print(f'status check failed: {error}')
                return 2
        if not re.fullmatch(r'[1-9][0-9]*', args.ticket):
            raise Refused('ticket: not an issue number')
        if args.command == 'run':
            if args.agent not in KINDS:
                raise Refused('agent: not builder, reviewer or fleet')
            try:
                return run(args)
            except (KeyError, TypeError, IndexError, ValueError) as error:
                raise Failed(f'unexpected GitHub answer: {error!r}')
        try:
            write(args, now)
        except (KeyError, TypeError, IndexError, ValueError) as error:
            raise Failed(f'unexpected GitHub answer: {error!r}')
        return 0
    except Refused as error:
        print(f'status.py: refused: {error}', file=sys.stderr)
        return 2
    except Stop as error:
        print(f'status.py: stop: {error}', file=sys.stderr)
        return 3
    except Failed as error:
        print(f'status.py: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
