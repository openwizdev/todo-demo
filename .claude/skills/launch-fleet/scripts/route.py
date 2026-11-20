#!/usr/bin/env python3
"""The wake route (FF2, #1332): one webhook tick's lookups. GH_REPO is the project's repository, where its specs live.

  route.py refs FROM N...    The project's tickets that messages from repository FROM name.
                             FROM is the project: N... unchanged. Any other repository: the
                             project's issues each named pull request closes (one GraphQL read).
                             Prints the numbers once each, ascending, on one line, for
                             `fleet.sh wake`; nothing when none.
  route.py loop FILE S       The loop id under key S of the private loop map FILE
                             ({"repo": GH_REPO, "loops": {"S": "<loop id>"}}), for `room-cli loop run`.
                             No file, no key, another repository or an unusable id: prints
                             nothing and exits 0, which leaves the spec to its own loop.
  route.py tick FROM FILE N...
                             One webhook tick's group of messages from repository FROM: refs,
                             then `fleet.sh wake` (only when refs names a ticket), then each
                             `wake fleet #S: room-cli loop run fleet-<S>` line with its handle
                             resolved through FILE: `wake fleet #S: room-cli loop run <loop id>`,
                             or `wake fleet #S: unresolved`. Every other line of the wake is
                             printed unchanged. No ticket: prints nothing, exit 0. A refused
                             lookup or wake: its exit status and reason.
  route.py gh api ARGS...    `gh api ARGS...` for a call that sends or reads a webhook, started with a
                             clean environment: only the names in KEEP pass (how gh finds itself,
                             its login, host and repository, certificates and a proxy). Every other
                             setting is dropped, so no trace setting reaches it: GH_DEBUG, DEBUG,
                             GODEBUG or one a later release adds. Standard input, output and the
                             exit status are gh's own. Needs no GH_REPO.

Exit 2 with the reason on stderr for bad arguments or a read that fails or is
partial. refs, loop and tick only read; gh writes only what its caller pipes in. None of
them prints a webhook address or a thread id.
"""
import json
import os
import re
import subprocess
import sys

REPO = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}')
NUMBER = re.compile(r'[1-9][0-9]{0,8}')
LOOP_ID = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_-]{0,127}')
WAKE_FLEET = re.compile(r'wake fleet #([1-9][0-9]{0,8}): room-cli loop run fleet-\1')
QUERY = ('query($o: String!, $n: String!) { repository(owner: $o, name: $n) { %s } }')
ITEM = ('i%d: issueOrPullRequest(number: %d) { __typename ... on PullRequest { closingIssuesReferences(first: 50) '
        '{ pageInfo { hasNextPage } nodes { number repository { nameWithOwner } } } } }')


class Refused(Exception):
    pass


def refs(home, source, numbers):
    if source.lower() == home.lower():
        return sorted(set(numbers))
    owner, name = source.split('/')
    query = QUERY % ' '.join(ITEM % (n, n) for n in sorted(set(numbers)))
    r = subprocess.run(['gh', 'api', 'graphql', '-f', 'query=' + query, '-f', 'o=' + owner, '-f', 'n=' + name],
                       capture_output=True, text=True, timeout=60)
    try:
        answer = json.loads(r.stdout)
        items = answer['data']['repository']
        errors = answer.get('errors') or []
    except (ValueError, KeyError, TypeError):
        raise Refused("can't read %s: %s" % (source, (r.stderr or r.stdout).strip()[:200] or 'no answer'))
    other = [e for e in errors if not isinstance(e, dict) or e.get('type') != 'NOT_FOUND']
    if not isinstance(items, dict) or other or (r.returncode != 0 and not errors):
        why = '; '.join('%s: %s' % (e.get('type'), e.get('message')) if isinstance(e, dict) else str(e)
                        for e in other) or r.stderr.strip() or 'unexpected answer'
        raise Refused("can't read %s: %s" % (source, why[:200]))
    found = set()
    for n in numbers:
        item = items.get('i%d' % n)
        if not item or item.get('__typename') != 'PullRequest':
            continue
        closing = item['closingIssuesReferences']
        if closing['pageInfo']['hasNextPage']:
            raise Refused('%s#%d closes more than one page of issues' % (source, n))
        found.update(c['number'] for c in closing['nodes']
                     if c['repository']['nameWithOwner'].lower() == home.lower())
    return sorted(found)


def loop(home, path, spec):
    try:
        with open(path) as f:
            value = json.load(f)
        loop_id = value['loops'][spec]
        if value['repo'].lower() != home.lower() or not LOOP_ID.fullmatch(loop_id):
            return None
        return loop_id
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def tick(home, source, path, numbers):
    found = refs(home, source, numbers)
    if not found:
        return 0
    fleet = os.environ.get('ROUTE_FLEET_SH') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fleet.sh')
    r = subprocess.run(['sh', fleet, 'wake', *map(str, found)], capture_output=True, text=True, timeout=600)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        return r.returncode
    for line in r.stdout.splitlines():
        m = WAKE_FLEET.fullmatch(line)
        if m:
            loop_id = loop(home, path, m.group(1))
            line = 'wake fleet #%s: %s' % (m.group(1), 'room-cli loop run ' + loop_id if loop_id else 'unresolved')
        print(line)
    return 0

# The environment a webhook's `gh api` call keeps; everything else, trace settings above all, is dropped.
KEEP = ('PATH', 'HOME', 'USER', 'LOGNAME', 'TMPDIR', 'LANG', 'LC_ALL',
        'GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN', 'GH_HOST', 'GH_REPO',
        'GH_CONFIG_DIR', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_STATE_HOME', 'XDG_CACHE_HOME', 'XDG_RUNTIME_DIR',
        'DBUS_SESSION_BUS_ADDRESS', 'SSL_CERT_FILE', 'SSL_CERT_DIR',
        'HTTPS_PROXY', 'https_proxy', 'HTTP_PROXY', 'http_proxy', 'NO_PROXY', 'no_proxy')


def quiet_gh(args):
    env = {k: os.environ[k] for k in KEEP if k in os.environ}
    try:
        os.execvpe('gh', ['gh', 'api', *args], env)
    except OSError as e:
        raise Refused('cannot start gh: %s' % e.strerror)


def main(argv):
    if argv[:2] == ['gh', 'api'] and len(argv) > 2:
        return quiet_gh(argv[2:])
    home = os.environ.get('GH_REPO', '')
    if not REPO.fullmatch(home):
        raise Refused('GH_REPO must be the project repository, owner/name')
    if len(argv) >= 3 and argv[0] == 'refs' and REPO.fullmatch(argv[1]) and all(NUMBER.fullmatch(a) for a in argv[2:]):
        found = refs(home, argv[1], [int(a) for a in argv[2:]])
        if found:
            print(' '.join(map(str, found)))
        return 0
    if len(argv) == 3 and argv[0] == 'loop' and NUMBER.fullmatch(argv[2]):
        loop_id = loop(home, argv[1], argv[2])
        if loop_id:
            print(loop_id)
        return 0
    if len(argv) >= 4 and argv[0] == 'tick' and REPO.fullmatch(argv[1]) and all(NUMBER.fullmatch(a) for a in argv[3:]):
        return tick(home, argv[1], argv[2], [int(a) for a in argv[3:]])
    raise Refused('usage: route.py refs OWNER/NAME N... | route.py loop FILE S | route.py tick OWNER/NAME FILE N... | route.py gh api ARGS...')


if __name__ == '__main__':
    try:
        sys.exit(main(sys.argv[1:]))
    except Refused as e:
        print('route.py: %s' % e, file=sys.stderr)
        sys.exit(2)
