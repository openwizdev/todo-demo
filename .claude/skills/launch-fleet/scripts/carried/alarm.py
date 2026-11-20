#!/usr/bin/env python3
"""One bounded CS5 observation/admission decision. Never sends notifications."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import uuid

ACTIONS = ('merge-batch', 'automatic-refresh', 'nonessential-poll',
           'completion', 'reconciliation')
ESSENTIAL = ('completion', 'reconciliation')
MAX_BYTES = 2 * 1024 * 1024
MAX_PENDING = 10000
RANK = {'healthy': 0, 'unknown': 1, 'alarm': 2, 'escalate': 3}


def pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('duplicate key')
        value[key] = item
    return value


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('not a regular input')
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('oversized input')
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('not JSON'))), raw
    except RecursionError:
        # Decoder nesting limits vary by Python version. All read boundaries
        # treat excess nesting as invalid data and preserve essential actions.
        raise ValueError('excessive JSON nesting') from None


def obj(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise ValueError('invalid object')


def integer(value):
    if type(value) is not int or value < 0:
        raise ValueError('invalid integer')
    return value


def queue_wait(queue, stamp, now):
    obj(queue, 'complete jobs')
    if queue['complete'] is not True or not isinstance(queue['jobs'], list) or len(queue['jobs']) > 10000:
        raise ValueError('incomplete queue')
    oldest = 0
    ids = set()
    for job in queue['jobs']:
        obj(job, 'id required status queued_at started_at')
        identity = job['id']
        if (not isinstance(identity, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', identity)
                or identity in ids or type(job['required']) is not bool
                or job['status'] not in ('queued', 'in_progress', 'completed')):
            raise ValueError('invalid job')
        ids.add(identity)
        queued = integer(job['queued_at'])
        if queued > stamp:
            raise ValueError('future job')
        started = job['started_at']
        if job['status'] == 'queued':
            if started is not None:
                raise ValueError('queued job already started')
            if job['required']:
                oldest = max(oldest, now - queued)
        elif started is not None and not queued <= integer(started) <= stamp:
            raise ValueError('invalid start time')
        elif job['status'] == 'in_progress' and started is None:
            raise ValueError('missing start time')
    return oldest


def pool_causes(budget, pool, now):
    obj(budget, 'remaining limit reset_at retry_after')
    remaining, limit = integer(budget['remaining']), integer(budget['limit'])
    if limit == 0 or remaining > limit or integer(budget['reset_at']) <= now:
        raise ValueError('unknown or reset budget')
    backoff = integer(budget['retry_after']) > now
    causes = []
    if remaining == 0:
        causes.append(pool + '_exhausted')
    elif remaining * 10 < limit:
        causes.append(pool + '_below_ten_percent')
    if backoff:
        causes.append(pool + '_backoff')
    return causes


def observe(value, repository, now, max_age):
    obj(value, 'repository observed_at complete queue budgets')
    stamp = integer(value['observed_at'])
    if (value['repository'] != repository or type(value['complete']) is not bool
            or not 0 <= now - stamp <= max_age):
        raise ValueError('stale or foreign observation')
    unknown = not value['complete']
    causes = []
    oldest = None
    try:
        oldest = queue_wait(value['queue'], stamp, now)
        if oldest >= 300:
            causes.append('required_job_wait')
    except (ValueError, TypeError, KeyError):
        unknown = True
    budgets = value['budgets']
    if not isinstance(budgets, dict) or set(budgets) != {'rest', 'graphql'}:
        unknown = True
    for pool in ('rest', 'graphql'):
        try:
            causes.extend(pool_causes(budgets[pool], pool, now))
        except (ValueError, TypeError, KeyError):
            unknown = True
    escalate = (oldest is not None and oldest >= 900 or
                any(c.endswith('_exhausted') for c in causes))
    level = 'escalate' if escalate else 'alarm' if causes else 'unknown' if unknown else 'healthy'
    if unknown:
        causes.append('observation_unknown')
    return dict(level=level, oldest_wait_seconds=oldest, causes=causes)


def checked_state(state, repository):
    obj(state, 'repository paused since level causes observed_at evidence_sha256')
    if state['repository'] != repository or state['paused'] is not True:
        raise ValueError('invalid pause')
    integer(state['since'])
    trigger = {key: state[key] for key in ('level', 'causes', 'observed_at', 'evidence_sha256')}
    obj(trigger, 'level causes observed_at evidence_sha256')
    if (trigger['level'] not in ('unknown', 'alarm', 'escalate')
            or not isinstance(trigger['causes'], list) or not trigger['causes']
            or any(c not in CAUSES for c in trigger['causes'])
            or len(set(trigger['causes'])) != len(trigger['causes'])
            or not re.fullmatch('[0-9a-f]{64}', trigger['evidence_sha256'])):
        raise ValueError('invalid trigger')
    integer(trigger['observed_at'])
    return state


CAUSES = {'required_job_wait', 'rest_exhausted', 'graphql_exhausted',
          'rest_below_ten_percent', 'graphql_below_ten_percent',
          'rest_backoff', 'graphql_backoff', 'observation_unknown', 'state_unknown'}


def sync_directory(path):
    directory = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def save(path, value, staging=None):
    fd, pending = tempfile.mkstemp(prefix='.pause-', dir=staging or path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)


def journal(path, trigger):
    path.mkdir(mode=0o700, exist_ok=True)
    sync_directory(path.parent)
    # Stage outside the journal so a concurrent admission sees only complete,
    # atomically published records. Each writer has its own immutable entry.
    save(path / (uuid.uuid4().hex + '.json'), trigger, staging=path.parent)


def pending_triggers(path, repository):
    try:
        entries = os.scandir(path)
    except FileNotFoundError:
        return []
    triggers = []
    total_bytes = 0
    with entries:
        for entry in entries:
            if len(triggers) >= MAX_PENDING:
                raise ValueError('too many pending triggers')
            value, raw = read(entry.path)
            total_bytes += len(raw)
            if total_bytes > MAX_BYTES:
                raise ValueError('oversized pending journal')
            triggers.append((Path(entry.path), checked_state(value, repository)))
    return sorted(triggers, key=lambda item: (item[1]['since'], item[1]['observed_at'], item[0].name))


def decision(args):
    raw = b''
    try:
        value, raw = read(args.input)
        result = observe(value, args.repository, args.now, args.max_age)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        result = dict(level='unknown', oldest_wait_seconds=None, causes=['observation_unknown'])
    digest = hashlib.sha256(raw).hexdigest()
    trigger = dict(level=result['level'], causes=result['causes'],
                   observed_at=args.now, evidence_sha256=digest)
    state = None
    saved = True
    try:
        args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        pending = Path(str(args.state) + '.pending')
        if result['level'] != 'healthy':
            journal(pending, dict(repository=args.repository, paused=True, since=args.now, **trigger))
        lock = os.open(str(args.state) + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        with os.fdopen(lock, 'r+') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                state = checked_state(read(args.state)[0], args.repository)
            except FileNotFoundError:
                pass
            records = pending_triggers(pending, args.repository)
            changed = False
            for _, retained in records:
                if state is None:
                    state = retained.copy()
                    changed = True
                elif RANK[retained['level']] > RANK[state['level']]:
                    state.update({key: retained[key] for key in trigger})
                    changed = True
            if changed:
                save(args.state, state)
            elif records:
                # A prior rename can be visible even when its directory sync
                # failed. Retry that barrier before consuming its journal.
                sync_directory(args.state.parent)
            # A crash before the pause is fsynced leaves the journal intact.
            # Delete only this snapshot: concurrent publishers stay pending.
            for path, _ in records:
                path.unlink()
            if records:
                sync_directory(pending)
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        saved = False
        if result['level'] == 'healthy':
            result['level'] = 'unknown'
        result['causes'].append('state_unknown')
    paused = state is not None or result['level'] != 'healthy' or not saved
    return dict(result, paused=paused, allowed=not paused or args.action in ESSENTIAL,
                state_saved=saved, evidence_sha256=digest,
                escalation='due_not_sent' if (result['level'] == 'escalate' or
                    state is not None and state['level'] == 'escalate') else 'not_due',
                pause=state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--state', required=True, type=Path)
    parser.add_argument('--now', type=int, default=int(time.time()))
    parser.add_argument('--max-age', type=int, default=60)
    parser.add_argument('--action', required=True, choices=ACTIONS)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository) or args.now < 0 or args.max_age < 0:
        parser.error('invalid repository or observation clock')
    result = decision(args)
    print(json.dumps(result, sort_keys=True))
    return 0 if result['allowed'] else 1


if __name__ == '__main__':
    sys.exit(main())
