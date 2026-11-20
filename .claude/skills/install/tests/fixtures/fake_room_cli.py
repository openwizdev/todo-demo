#!/usr/bin/env python3
"""A recording fake `room-cli` for the onboarding launch (#636).

It answers only `thread spawn`, the one CloudRoom call the onboarding helper
makes (launch-fleet's "Starting one" form), from a scripted queue in
$FAKE_ROOM_SCRIPT (JSON: {"spawn": [{"exit": N, "stdout": text}, ...]}), and logs
every call to $FAKE_ROOM_LOG as one JSON line. Any other call, or a spawn with
no answer left, exits 99 so the test sees it. An answer with "kill_caller"
stops the calling process (SIGKILL) after the start is recorded, as an agent
interrupted mid-start. All values are synthetic.
"""
import json
import os
import signal
import sys


def main(argv):
    with open(os.environ['FAKE_ROOM_LOG'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(argv) + '\n')
    path = os.environ['FAKE_ROOM_SCRIPT']
    with open(path, encoding='utf-8') as handle:
        script = json.load(handle)
    queue = script.get('spawn') if argv[:2] == ['thread', 'spawn'] else None
    if not queue:
        sys.stderr.write('fake room-cli: unexpected call\n')
        return 99
    answer = queue.pop(0)
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(script, handle)
    if answer.get('kill_caller'):
        os.kill(os.getppid(), signal.SIGKILL)
    sys.stdout.write(answer.get('stdout', ''))
    return answer['exit']


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
