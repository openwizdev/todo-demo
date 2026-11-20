#!/usr/bin/env python3
"""A synthetic driver v1 for test-host.py (#1371): it starts nothing.

Run by a `<adapters>/<host>/driver` shim that sets $FAKE_DRIVER_HOST, it appends each call (its host, command
and stdin) to $FAKE_DRIVER_LOG as one JSON line and answers as a driver would:
`start` a run id naming its host, `wake` and `stop` that run. With
$FAKE_DRIVER_MODE `refuse` it fails as v1 says (exit 1, `error` and `next`);
with `garbage` it answers something that is no run; with `extra`, a run with a
repeated or unknown key. While $FAKE_DRIVER_HOLD names a file, it waits; $FAKE_DRIVER_BREAK names a
folder it makes read-only. $FAKE_DRIVER_REFUSALS=K refuses only a command's first K calls in the log
(#1446), and $FAKE_DRIVER_NEXT replaces a refusal's `next` text.
"""
import json
import os
import sys
import time

host = os.environ['FAKE_DRIVER_HOST']
command = sys.argv[1] if len(sys.argv) > 1 else ''
given = sys.stdin.read() if command in ('start', 'wake', 'stop') else ''
with open(os.environ['FAKE_DRIVER_LOG'], 'a') as log:
    log.write(json.dumps({'host': host, 'command': command, 'input': json.loads(given) if given else None}) + '\n')
mode = os.environ.get('FAKE_DRIVER_MODE', '')
if os.environ.get('FAKE_DRIVER_BREAK'):  # the private state folder turns read-only during the start
    os.chmod(os.environ['FAKE_DRIVER_BREAK'], 0o500)
while os.environ.get('FAKE_DRIVER_HOLD') and os.path.exists(os.environ['FAKE_DRIVER_HOLD']):
    time.sleep(0.02)  # held by the test until it removes the file
if mode == 'extra':
    print('{"run": "%s-run-1", "run": "%s-run-2"}' % (host, host) if command == 'start'
          else json.dumps({'run': json.loads(given)['run'], 'woke': True, 'token': 'synthetic'}))
    sys.exit(0)
if os.environ.get('FAKE_DRIVER_REFUSALS'):
    with open(os.environ['FAKE_DRIVER_LOG']) as log:
        made = sum(json.loads(line)['command'] == command for line in log)
    mode = 'refuse' if made <= int(os.environ['FAKE_DRIVER_REFUSALS']) else mode
if mode == 'refuse':
    print(json.dumps({'error': 'the synthetic harness is not signed in',
                      'next': os.environ.get('FAKE_DRIVER_NEXT', 'sign in to the harness, then start again')}))
    sys.exit(1)
if mode == 'garbage':
    print('started, probably')
    sys.exit(0)
if command == 'start':
    print(json.dumps({'run': '%s-run-%d' % (host, json.loads(given)['ticket'])}))
elif command == 'wake':
    print(json.dumps({'run': json.loads(given)['run'], 'woke': True}))
elif command == 'stop':
    print(json.dumps({'run': json.loads(given)['run'], 'stopped': True}))
else:
    print(json.dumps({'error': 'unknown command', 'next': 'run start, wake or stop'}))
    sys.exit(1)
