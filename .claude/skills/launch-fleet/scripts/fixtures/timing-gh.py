#!/usr/bin/env python3
"""Synthetic gh timing harness: a locked trace and a bounded reader barrier.

The deadline only detects a stalled barrier. Concurrency is proven by the
readers entering it together, never by an elapsed-time threshold. It is 60 s
(10 s before ClosedWiz#1254): on a busy runner, with other cases running at
once, filling the barrier took longer than 10 s (CI run 42156991869), and a
pool that never fills it still fails, only later.
"""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import time

def fake_gh(args):
    """The fake gh (fixtures/gh.py) on ARGS, in this process: its exit status."""
    sys.dont_write_bytecode = True  # no __pycache__ beside the fixtures
    spec = importlib.util.spec_from_file_location('fake_gh', os.environ['FAKE_GH_SCRIPT'])
    gh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gh)
    return gh.run(args)


DEADLINE = 60  # seconds: a stalled barrier, never a slow one
root = Path(os.environ['FAKE_GH_TIMING'])
args = sys.argv[1:]
endpoint = args[-1]
group = os.environ.get('FAKE_GH_TIMING_GROUP')
rest = args[0] == 'api' and 'graphql' not in args
spec_query = any('query Spec(' in a for a in args)
if not rest and not (group == 'graphs' and spec_query):
    sys.exit(fake_gh(args))
if not rest:
    endpoint = 'graphql Spec ' + next(a for a in args if a.startswith('number='))
pattern = (r'/issues/70(/|$)' if group == 'one' else
           r'/issues/9[0-1][0-9]/comments\?' if group == 'specs' else
           r'/issues/(8[0-9]{2}|9[01][0-9]|92[0-7])/comments\?')
gated = spec_query if group == 'graphs' else False if group == 'all' else re.search(pattern, endpoint) is not None
# All sixteen small-spec comment reads must overlap; releasing after only
# eight arrivals lets early readers finish before a late worker starts.
barrier = (3 if group == 'one' else 16 if group == 'specs' else
           8 if group == 'graphs' else 64)


def update(event):
    with (root / 'state').open('a+') as state:
        fcntl.flock(state, fcntl.LOCK_EX)
        state.seek(0)
        data = json.loads(state.read() or '{}')
        active = data.get('active', 0) + (1 if event == 'start' else -1)
        data['active'] = active
        data['peak'] = max(data.get('peak', 0), active)
        if group == 'all' and '/issues/800/comments?' in endpoint and event == 'start':
            data['crossed'] = True
        if group == 'pipeline' and '/issues/865/comments?' in endpoint and event == 'start':
            data['advanced'] = True
        if gated and event == 'start':
            data['arrived'] = data.get('arrived', 0) + 1
        state.seek(0)
        state.truncate()
        json.dump(data, state)
        with (root / 'trace').open('a') as trace:
            trace.write(json.dumps({'event': event, 'endpoint': endpoint,
                                    'active': active}) + '\n')
        return data


start = time.monotonic()
update('start')
try:
    if gated:
        while True:
            with (root / 'state').open() as state:
                fcntl.flock(state, fcntl.LOCK_SH)
                arrived = json.load(state).get('arrived', 0)
            if arrived >= barrier:
                break
            if time.monotonic() - start > DEADLINE:
                sys.stderr.write('fake gh: independent reader barrier never filled\n')
                sys.exit(1)
            time.sleep(0.01)
    # One slow first-wave read must not hold up every free reader. The
    # second lane's next item releases it; a batch-at-a-time pool deadlocks.
    if group == 'pipeline' and '/issues/800/comments?' in endpoint:
        while True:
            with (root / 'state').open() as state:
                fcntl.flock(state, fcntl.LOCK_SH)
                advanced = json.load(state).get('advanced', False)
            if advanced:
                break
            if time.monotonic() - start > DEADLINE:
                sys.stderr.write('fake gh: a slow reader blocked the next independent read\n')
                sys.exit(1)
            time.sleep(0.01)
    if group == 'all' and '/issues/10/comments?' in endpoint:
        while True:
            with (root / 'state').open() as state:
                fcntl.flock(state, fcntl.LOCK_SH)
                crossed = json.load(state).get('crossed', False)
            if crossed:
                break
            if time.monotonic() - start > DEADLINE:
                sys.stderr.write('fake gh: spec reads stranded independent archive reads\n')
                sys.exit(1)
            time.sleep(0.01)
    fault = os.environ.get('FAKE_GH_TIMING_FAIL')
    if ((fault == 'yes' and endpoint.endswith('/issues/9999')) or
            (fault == 'comments' and '/issues/800/comments?' in endpoint)):
        sys.stderr.write('fake gh: planted concurrent worker failure\n')
        sys.exit(1)
    sys.exit(fake_gh(args))
finally:
    update('finish')
