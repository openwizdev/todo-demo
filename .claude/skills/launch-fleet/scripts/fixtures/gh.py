#!/usr/bin/env python3
"""A fake `gh` for fleet.sh's tests (test.sh puts it first on PATH as `gh`).

It answers only the reads fleet.sh makes, from a synthetic GitHub in
$FAKE_GH_WORLD (JSON, see check.json), and logs each call to $FAKE_GH_LOG.
It also answers to-tickets's revision.sh (`issue view <n> --json ... --jq`)
and `repo clone` (from the git repository $FAKE_GH_REMOTE).
Any other call, including every write, fails, so the tests catch it.

It is the shell fake gh.sh of before ClosedWiz#1254 in Python, in one process
(gh.sh started three or four jq processes for each call): the same answers,
byte for byte, the same log lines and the same exit statuses, checked call by
call over a whole test run (private/evidence/ci-hotspot-launch-fleet/).

A comment's "edited" time (as GitHub's updatedAt) is its "at" unless set.

GI1's unchanged probe (#2543) reads REST views of what GraphQL answers: the
repository, the account (a world's "login", else synthetic-user), a spec's
sub-issues, an issue's timeline (its labelled events and the pull requests
that close it), a head's check runs and status, and the default branch (its
tip moves with every merged pull request). Every REST answer read with
--include carries an ETag of its body and answers 304 to a matching
If-None-Match; $FAKE_GH_HTTP_LOG counts them.

Faults, for the error cases:
  FAKE_GH_PULL_HEAD=<sha> REST open-PR details report another head, exposing
                            a check rollup mixed with later REST metadata
  FAKE_GH_FAIL=<text>    a call whose log line contains <text> fails (exit 1);
                         an underscore in <text> stands for a space
  FAKE_GH_ERRORS=<op>    GraphQL query <op> answers with `errors`, exit 0
  FAKE_GH_PAGE=<n>       page size for the paginated reads (default 100)
  FAKE_GH_SEARCH_CAP=<n> the search lists at most <n> issues, though it counts them all
  FAKE_GH_NIGHTLY_HTTP=<status> the nightly runs read answers with this HTTP status

GitHub's allowance (ClosedWiz#189). Every GraphQL answer carries rateLimit:
its cost, as GitHub counts it (each connection's `first` or `last` read as
full, those requests added up, divided by 100, rounded to the nearest, at
least 1: checked against GitHub's own dry runs, 2026-10-31), the points
remaining, the limit and when it resets.
  FAKE_GH_REMAINING=<n>     the points remaining (default 5000, of 5000)
  FAKE_GH_RATE_LIMITED=<op> GraphQL query <op> answers as GitHub does once the
                            allowance has run out: an `errors` entry of type
                            RATE_LIMIT (observed live, 2026-11-01), and `gh`
                            exits 1
  FAKE_GH_RATE_TYPE=<type>  that entry's type instead (RATE_LIMITED, the
                            spelling GitHub's clients also check)
  FAKE_GH_SUMMARY_LAG=<n>   the open issues list each spec with <n> fewer
                            tickets than it has, as if <n> were added since
  FAKE_GH_REVISION_WORLD=<file>  `issue view` (revision.sh's reads) answers
                            from this world instead, as if the plan changed
                            between the check's reads and revision.sh's
"""
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from urllib.parse import quote

env = os.environ


class Fail(Exception):
    """A failed call: its message goes to stderr, and it exits 1."""


class Status(Exception):
    """A step that ends the REST answer with this status and no message."""

    def __init__(self, status):
        super().__init__(status)
        self.status = status


def fail(msg):
    raise Fail(msg)


# #641: who wrote a comment. Every comment is the factory's own (a login the
# fixture's docs/agents/fleet.md names as a record author) unless it says
# "author": another login, or null for GitHub's missing user.
FACTORY = 'synthetic-factory[bot]'


# Why an issue was closed, as GraphQL spells it (REST: lowercase): a world's
# "stateReason", else completed for a closed issue.
def state_reason(i, spell):
    reason = i.get('stateReason', 'COMPLETED' if get(i, 'state') == 'CLOSED' else None)
    return None if reason is None else spell(reason)


def actor(login):
    """A GraphQL actor: GitHub's GraphQL names an App's bot without "[bot]"
    (observed live, 2026-11-20); None is GitHub's deleted user."""
    if login is None:
        return None
    if login.endswith('[bot]'):
        return {'__typename': 'Bot', 'login': login[:-len('[bot]')]}
    return {'__typename': 'User', 'login': login}


# KN13 (#1448): an issue's labelled events, oldest first. GitHub records one
# for every label an issue carries; a world that gives the ready label none
# has it put on at 08:00 by the factory ("by" names who put an event's label on).
def label_events(i):
    events = list(each_opt(get(i, 'labelEvents')))
    if 'ready-for-agent' in each_opt(get(i, 'labels')) and not any(get(e, 'name') == 'ready-for-agent' for e in events):
        events.insert(0, {'name': 'ready-for-agent', 'at': '2026-11-01T08:00:00Z'})
    return sorted(events, key=lambda e: get(e, 'at'))


def author(c):
    login = c.get('author', FACTORY) if isinstance(c, dict) else FACTORY
    return None if login is None else {'login': login, 'type': 'Bot' if login.endswith('[bot]') else 'User'}


# --- jq's values, as the shell fake's jq programs treat them ---------------

def compact(v):
    """`jq -c`: one line, no spaces."""
    return json.dumps(v, ensure_ascii=False, separators=(',', ':')).replace('\x7f', '\\u007f')


def pretty(v):
    """jq's default output: two-space indent."""
    return json.dumps(v, ensure_ascii=False, indent=2).replace('\x7f', '\\u007f')


def truthy(v):
    return v is not None and v is not False


def alt(v, d):
    """`v // d`."""
    return v if truthy(v) else d


def get(o, k):
    """`.k`: null on null; an error on anything but an object."""
    if o is None:
        return None
    if not isinstance(o, dict):
        fail('the world is not valid')
    return o.get(k)


def each(v):
    """`.[]`: an error on null or a scalar."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    fail('the world is not valid')


def each_opt(v):
    """`.[]?`."""
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return list(v.values())
    return []


def rank(v):
    """jq's order: null, false, true, numbers, strings, arrays, objects."""
    if v is None:
        return (0,)
    if v is False:
        return (1,)
    if v is True:
        return (2,)
    if isinstance(v, (int, float)):
        return (3, v)
    if isinstance(v, str):
        return (4, v.encode('utf-16-be') if False else [ord(c) for c in v])
    if isinstance(v, list):
        return (5, [rank(x) for x in v])
    return (6, sorted(v), [rank(v[k]) for k in sorted(v)])


def jq_max(vs):
    return max(vs, key=rank) if vs else None


def sort_by(xs, f):
    return sorted(xs, key=lambda x: rank(f(x)))


def tonumber(s):
    """`$s | tonumber? // $s`."""
    try:
        if re.fullmatch(r'-?[0-9]+', s):
            return int(s)
        n = float(s)
        if n != n or n in (float('inf'), float('-inf')):
            return s
        return int(n) if n.is_integer() and abs(n) < 1e17 else n
    except ValueError:
        return s


def argjson(s):
    try:
        return json.loads(s)
    except ValueError:
        sys.stderr.write('jq: Invalid JSON text passed to --argjson\n')
        raise Status(2)


def number_of(s):
    """`$s | tonumber`, for numbers given as text."""
    n = tonumber(s)
    if isinstance(n, str):
        fail('the world is not valid')
    return n


def tostring(n):
    return n if isinstance(n, str) else compact(n)


def ascii_downcase(s):
    if not isinstance(s, str):
        fail('the world is not valid')
    return ''.join(chr(ord(c) + 32) if 'A' <= c <= 'Z' else c for c in s)


def sha_text(n):
    return 'I_%s' % tostring(n)


def updated(i):
    return jq_max([alt(get(i, 'updatedAt'), '2026-11-01T08:00:00Z')]
                  + [get(c, 'at') for c in each_opt(get(i, 'comments'))])


def children(w, n):
    return [i for i in each(w.get('issues')) if get(i, 'parent') == n]


def keep(o, *keys):
    return {k: get(o, k) for k in keys}


# --- the call ---------------------------------------------------------------

def main(argv):
    world_path = env.get('FAKE_GH_WORLD') or ''
    if not world_path:
        sys.stderr.write('FAKE_GH_WORLD: parameter not set\n')
        return 2
    logfile = env.get('FAKE_GH_LOG') or ''
    if not logfile:
        sys.stderr.write('FAKE_GH_LOG: parameter not set\n')
        return 2
    page = env.get('FAKE_GH_PAGE') or '100'

    def answer(line):
        try:
            with open(logfile, 'a') as log:
                log.write(line + '\n')
        except OSError:
            fail("can't write the log")
        pattern = (env.get('FAKE_GH_FAIL') or '').replace('_', ' ')
        if pattern and pattern in line:
            fail('planted failure: ' + line)

    try:
        with open(world_path) as f:
            w = json.load(f)
    except (OSError, ValueError):
        fail('no repo in the world')
    repo = w.get('repo') if isinstance(w, dict) else None
    if not truthy(repo):
        fail('no repo in the world')
    repo = repo if isinstance(repo, str) else compact(repo)
    args = argv
    joined = ' '.join(args)

    if args[:2] == ['repo', 'view']:
        if joined == 'repo view --json isPrivate --jq .isPrivate':
            print('true' if w.get('private', True) else 'false')
            return 0
        if joined != 'repo view --json nameWithOwner --jq .nameWithOwner':
            fail('unexpected: gh ' + joined)
        answer('repo view')
        sys.stdout.write(repo + '\n')
        return 0
    if args[:2] == ['repo', 'clone']:
        if not (len(args) == 8 and args[2] == repo and args[4:8] == ['--', '-q', '--depth', '1']):
            fail('unexpected: gh ' + joined)
        answer('repo clone')
        remote = env.get('FAKE_GH_REMOTE') or ''
        if not remote:
            sys.stderr.write('FAKE_GH_REMOTE: parameter not set\n')
            return 2
        sys.stdout.flush()
        os.execvp('git', ['git', 'clone', '-q', '--depth', '1', 'file://' + remote, args[3]])

    if args[:2] == ['issue', 'view']:
        if not (len(args) == 7 and args[3] == '--json' and args[5] == '--jq'):
            fail('unexpected: gh ' + joined)
        if not re.fullmatch(r'[0-9]+', args[2]):
            fail('not an issue number: ' + args[2])
        fields = args[4]
        if fields not in ('subIssues', 'body', 'number,title,blockedBy'):
            fail('unexpected fields: ' + fields)
        answer('issue view %s %s' % (args[2], fields))
        if env.get('FAKE_GH_REVISION_WORLD'):
            with open(env['FAKE_GH_REVISION_WORLD']) as f:
                w = json.load(f)
        n = int(args[2])
        found = [i for i in each(w.get('issues')) if get(i, 'number') == n]
        if not found:
            fail('Could not resolve to an issue: ' + args[2])
        i = found[0]
        subs = [{'number': get(s, 'number')} for s in children(w, n)]
        full = {'number': get(i, 'number'), 'title': get(i, 'title'), 'body': alt(get(i, 'body'), ''),
                'subIssues': {'totalCount': len(subs), 'nodes': subs},
                'blockedBy': {'nodes': [{'number': b} for b in each_opt(get(i, 'blockedBy'))]}}
        one = {k: v for k, v in full.items() if k in fields.split(',')}
        sys.stdout.flush()
        return subprocess.run(['jq', '-r', args[6]], input=pretty(one) + '\n', text=True).returncode

    if not args or args[0] != 'api':
        fail('unexpected: gh ' + joined)
    args = args[1:]

    o = {'query': '', 'owner': '', 'name': '', 'number': '', 'cursor': '', 'label': '',
         'state': '', 'size': '', 'q': '', 'oid': '', 'login': ''}
    ids = []
    accept = paginate = include = ''
    conditional = path = ''
    while args:
        a = args[0]
        if a in ('-f', '-F'):
            if len(args) < 2:
                fail(a + ' needs a value')
            v = args[1]
            key, eq, value = v.partition('=')
            if eq and key in o:
                o[key] = value
            elif v.startswith('ids[]='):
                ids.append(v[len('ids[]='):])
            else:
                fail('unexpected field: ' + v)
            args = args[2:]
        elif a == '-H':
            h = args[1] if len(args) > 1 else ''
            if h == 'Accept: application/vnd.github.raw+json':
                accept = 'raw'
            elif h == 'Accept: application/vnd.github+json':
                pass
            elif h.startswith('If-None-Match: '):
                conditional = h[len('If-None-Match: '):]
            else:
                fail('unexpected header: ' + h)
            args = args[2:]
        elif a == '--paginate':
            paginate = 'yes'
            args = args[1:]
        elif a == '--include':
            include = 'yes'
            args = args[1:]
        elif a.startswith('-'):
            fail('not a read fleet.sh makes: ' + a)
        else:
            if path:
                fail('two paths: %s %s' % (path, a))
            path = a
            args = args[1:]

    if path == 'graphql':
        sys.stdout.write(graphql(w, repo, o, ids, page, answer))
        return 0
    return rest(w, repo, path, page, paginate, include, accept, conditional, answer)


def pages(a, page):
    """`gh api --paginate`'s pages: one array per page, one after another."""
    n = int(page)
    if a is None:
        return 'null\n'
    out = []
    for start in range(0, max(len(a), 1), n):
        out.append(compact(a[start:start + n]) + '\n')
    return ''.join(out)


def graphql(w, repo, o, ids, page, answer):
    query, owner, name, number, cursor = o['query'], o['owner'], o['name'], o['number'], o['cursor']
    size, q = o['size'], o['q']
    op = ''
    for line in query.split('\n'):
        m = re.match(r'^ *query ([A-Za-z]*)\(', line)
        if m:
            op = m[1]
            break
    if op in ('Singles', 'Nodes', 'Blockers'):
        if owner + name:
            fail(op + ' takes no owner or name')
    elif owner + '/' + name != repo:
        fail('graphql for %s/%s, not %s' % (owner, name, repo))
    label = ''
    if op == 'Singles':
        answer('graphql Singles cursor=' + (cursor or 'none'))
        prefix, suffix = 'repo:%s is:issue label:"' % repo, '" no:parent-issue'
        if not (q.startswith(prefix) and q[len(prefix):].endswith(suffix)):
            fail('unexpected search: ' + q)
        label = q[len(prefix):]
        label = label[:len(label) - len(suffix)]
    elif op in ('Nodes', 'Blockers'):
        answer('graphql %s count=%d' % (op, len(ids)))
    elif op in ('Specs', 'Merged'):
        answer('graphql %s cursor=%s' % (op, cursor or 'none'))
    elif op == 'Spec':
        answer('graphql Spec number=%s%s' % (number, ' size=' + size if size else ''))
    elif op == 'Checks':
        answer('graphql Checks oid=%s cursor=%s' % (o['oid'], cursor or 'none'))
    elif op == 'Item':
        answer('graphql Item number=%s size=%s%s' % (number, size, ' cursor=' + cursor if cursor else ''))
    elif op == 'Writer':
        answer('graphql Writer login=%s' % o['login'])
    else:
        fail('unknown query: ' + query.split('\n')[0])
    if env.get('FAKE_GH_ERRORS', '') == op:
        return '{"data":null,"errors":[{"message":"planted GraphQL error"}]}\n'
    if env.get('FAKE_GH_RATE_LIMITED', '') == op:
        sys.stdout.write(compact({'errors': [{'type': env.get('FAKE_GH_RATE_TYPE') or 'RATE_LIMIT',
                                              'message': 'API rate limit already exceeded for user ID 1.'}]}) + '\n')
        sys.stderr.write('gh: API rate limit already exceeded for user ID 1.\n')
        raise Status(1)
    remaining = tonumber(env.get('FAKE_GH_REMAINING') or '5000')
    issues, pulls = each(w.get('issues')), each(w.get('pulls'))
    # Item (ClosedWiz#259): a number that is neither an issue nor a pull request
    # answers as GitHub does: the item null, an `errors` entry of type NOT_FOUND
    # (observed live, 2026-11-01), and `gh` exits 1.
    if op == 'Item':
        n = argjson(number)
        if not any(get(x, 'number') == n for x in issues + pulls):
            default = w.get('default')
            sys.stdout.write(compact({
                'data': {'rateLimit': {'cost': 1, 'remaining': remaining, 'limit': 5000, 'resetAt': '2026-11-01T13:00:00Z'},
                         'repository': {'databaseId': 1, 'defaultBranchRef': {'name': default if isinstance(default, str) else compact(default)},
                                        'issueOrPullRequest': None}},
                'errors': [{'type': 'NOT_FOUND', 'path': ['repository', 'issueOrPullRequest'],
                            'message': 'Could not resolve to an issue or pull request with the number of %s.' % compact(n)}]}) + '\n')
            sys.stderr.write('gh: Could not resolve to an issue or pull request with the number of %s.\n' % number)
            raise Status(1)
    # A query's own page size, when it sets one ($size), applies when it is smaller.
    # Spec's $size is how many of the spec's tickets it asks for, not a page;
    # Item's, how many issues a pull request closes.
    tickets = 100
    page = argjson(page)
    if size:
        if not re.fullmatch(r'[0-9]+', size):
            fail('size is not a number: ' + size)
        if op in ('Spec', 'Item'):
            tickets = int(size)
        elif int(size) < page:
            page = int(size)
    cap = argjson(env.get('FAKE_GH_SEARCH_CAP') or '1000')
    lag = argjson(env.get('FAKE_GH_SUMMARY_LAG') or '0')

    def round_cost(requests):
        return max(1, math.floor(requests / 100 + 0.5))

    # Legacy tickets cost 40 requests each; REST migration removes labels,
    # comments and the fixed blocker fan-out, leaving 12 (timeline, closing
    # PRs and their commit/check rollups). Actual blockers are batched.
    weight = 40 if 'comments(last: 50)' in query else 33 if 'blockedBy(first: 20)' in query else 12
    if op == 'Spec':
        cost = round_cost(2 + weight * tickets)
    elif op == 'Nodes':
        cost = round_cost(weight * len(ids))
    elif op == 'Item':
        cost = 1 if tickets <= 2 else 2
    else:
        cost = 1
    rate = {'rateLimit': {'cost': cost, 'remaining': remaining, 'limit': 5000, 'resetAt': '2026-11-01T13:00:00Z'}}

    def window(all_):
        start = 0 if cursor == '' else number_of(cursor)
        return {'pageInfo': {'hasNextPage': start + page < len(all_), 'endCursor': tostring(start + page)},
                'nodes': all_[start:start + page]}

    def comments(x):
        return {'pageInfo': {'hasPreviousPage': alt(get(x, 'commentsTruncated'), False)},
                'nodes': [{'databaseId': get(c, 'id'), 'createdAt': get(c, 'at'),
                           'updatedAt': alt(get(c, 'edited'), get(c, 'at')), 'body': get(c, 'body')}
                          for c in each_opt(get(x, 'comments'))]}

    def closing(n):
        return [p for p in pulls if any(c == n for c in each(get(p, 'closes')))]

    def checks(p):
        out = []
        cs = get(p, 'checks')
        entries = list(enumerate(cs)) if isinstance(cs, list) else list(cs.items()) if isinstance(cs, dict) else fail('the world is not valid')
        for i, c in entries:
            if get(c, 'type') == 'StatusContext':
                out.append({'__typename': 'StatusContext', 'id': alt(get(c, 'id'), 'SC_%s' % i), 'context': get(c, 'context'), 'state': get(c, 'state'),
                            'createdAt': get(c, 'createdAt')})
            else:
                out.append({'__typename': 'CheckRun', 'id': alt(get(c, 'id'), 'CR_%s' % i), 'name': get(c, 'name'), 'status': get(c, 'status'),
                            'conclusion': get(c, 'conclusion'),
                            'databaseId': alt(get(c, 'databaseId'), 100 + i if isinstance(i, int) else fail('the world is not valid')),
                            'startedAt': get(c, 'startedAt'),
                            # K9 (#337): the check's workflow run, "run" its createdAt and "runId" its databaseId.
                            'checkSuite': {'workflowRun': None if get(c, 'run') is None else
                                           {'createdAt': get(c, 'run'), 'databaseId': get(c, 'runId')}}})
        return out

    def context_page(p, start=0):
        # Model the actual requested connection window, not unlimited checks.
        window = re.search(r'contexts\(first: ([0-9]+)', query)
        count = int(window.group(1)) if window else 20
        cs = checks(p)
        end = min(start + count, len(cs))
        result = {'totalCount': len(cs),
                  'pageInfo': {'hasNextPage': end < len(cs) or bool(get(p, 'checksTruncated')),
                               'endCursor': str(end) if end > start else None},
                  'nodes': cs[start:end]}
        result.update(p.get('contextPages', {}).get(str(start), {}))
        return result

    def pr(p):
        # Synthetic per-response observations for a PR linked across specs.
        if op == 'Spec':
            p = dict(p, **p.get('specSnapshots', {}).get(number, {}))
        rollup = None if get(p, 'rollup') is None else {
            'state': get(p, 'rollup'),
            'contexts': context_page(p)}
        return {'number': get(p, 'number'), 'state': get(p, 'state'), 'isDraft': alt(get(p, 'draft'), False),
                'merged': get(p, 'state') == 'MERGED', 'mergedAt': get(p, 'mergedAt'),
                'closedAt': get(p, 'closedAt'),  # K9 (#337): when a closed one closed
                'baseRefName': get(p, 'base'), 'headRefOid': get(p, 'head'),
                'commits': {'nodes': [{'commit': {'oid': get(p, 'head'),
                                                  # The full message is returned only when requested;
                                                  # GitHub's display headline can be truncated.
                                                  **({'message': p.get('message', get(p, 'headline'))}
                                                     if re.search(r'\bmessage\b', query) else {}),
                                                  'committedDate': get(p, 'committed'),  # K9 (#337)
                                                  'statusCheckRollup': rollup}}]},
                'comments': comments(p)}

    def ticket(t):
        blockers = []
        for b in each_opt(get(t, 'blockedBy')):
            for i in issues:
                if get(i, 'number') == b:
                    blockers.append({'number': get(i, 'number'), 'state': get(i, 'state'),
                                     'closedByPullRequestsReferences': {'nodes': [
                                         {'number': get(p, 'number'), 'merged': get(p, 'state') == 'MERGED',
                                          'baseRefName': get(p, 'base')} for p in closing(get(i, 'number'))]}})
        return {'number': get(t, 'number'), 'title': get(t, 'title'), 'state': get(t, 'state'),
                'body': alt(get(t, 'body'), ''),
                'labels': {'pageInfo': {'hasNextPage': False}, 'nodes': [{'name': l} for l in each_opt(get(t, 'labels'))]},
                'lastEditedAt': t.get('editedAt'), 'editor': actor(t.get('editor')),
                'timelineItems': {'nodes': [{'createdAt': get(e, 'at'), 'actor': actor(e.get('by', FACTORY)),
                                             'label': {'name': get(e, 'name')}}
                                            for e in label_events(t)[-20:]]},
                'comments': comments(t),
                'blockedBy': {'pageInfo': {'hasNextPage': alt(get(t, 'blockersTruncated'), False)}, 'nodes': blockers},
                'closedByPullRequestsReferences': {'pageInfo': {'hasNextPage': alt(get(t, 'linkedPrsTruncated'), False)},
                                                   'nodes': [pr(p) for p in closing(get(t, 'number'))]}}

    def subs_total(n):
        return len([i for i in issues if get(i, 'parent') == n])

    if op == 'Writer':
        # KN13 (#1448): a repository's collaborators matching a login, with
        # their permission ($world.collaborators: {login: permission}).
        found = [{'permission': v, 'node': {'login': k}} for k, v in (w.get('collaborators') or {}).items()
                 if o['login'].lower() in k.lower()]
        out = {'data': {'repository': {'collaborators': {'edges': found}}}}
    elif op == 'Checks':
        ps = [p for p in pulls if get(p, 'head') == o['oid']]
        if not ps:
            fail('unknown commit: ' + o['oid'])
        p = ps[0]
        start = int(cursor or '0')
        out = {'data': {'repository': {'object': {
            'oid': p.get('contextOids', {}).get(str(start), get(p, 'head')),
            'statusCheckRollup': {'state': get(p, 'rollup'), 'contexts': context_page(p, start)}}}}}
    elif op == 'Singles':
        found = [i for i in issues if get(i, 'parent') is None and any(l == label for l in each_opt(get(i, 'labels')))]
        found = sort_by(found, lambda i: alt(get(i, 'updatedAt'), ''))[::-1]
        nodes = [{'id': sha_text(get(i, 'number')), 'number': get(i, 'number'), 'state': get(i, 'state'),
                  'comments': {'nodes': [{'body': get(c, 'body')} for c in each(jq_slice_last(get(i, 'comments')))]}}
                 for i in found[:cap]]
        out = {'data': {'search': dict({'issueCount': len(found)}, **window(nodes))}}
    elif op in ('Nodes', 'Blockers'):
        nodes = []
        for x in ids:
            for i in issues:
                if sha_text(get(i, 'number')) == x:
                    t = ticket(i)
                    t['parent'] = None if get(i, 'parent') is None else {'number': get(i, 'parent')}
                    t['subIssuesSummary'] = {'total': subs_total(get(i, 'number'))}
                    if op == 'Blockers':
                        t['stateReason'] = state_reason(i, lambda r: r)
                    nodes.append(t)
        out = {'data': {'nodes': nodes}}
    elif op == 'Specs':
        specs = []
        for i in issues:
            if get(i, 'state') != 'OPEN':
                continue
            subs = [s for s in issues if get(s, 'parent') == get(i, 'number')]
            specs.append({'number': get(i, 'number'), 'updatedAt': updated(i), 'body': alt(get(i, 'body'), ''),
                          'subIssuesSummary': {'total': max(len(subs) - lag, 0),
                                               'completed': len([s for s in subs if get(s, 'state') == 'CLOSED'])}})
        out = {'data': {'repository': {'databaseId': 1, 'defaultBranchRef': {'name': w.get('default')},
                                       'issues': window(specs)}}}
    elif op == 'Item':
        def item(i):
            t = ticket(i)
            t['subIssuesSummary'] = {'total': subs_total(get(i, 'number'))}
            if get(i, 'parent') is None:
                t['parent'] = None
            else:
                ss = [s for s in issues if get(s, 'number') == get(i, 'parent')]
                s = ss[0] if ss else None
                t['parent'] = {'number': get(s, 'number'), 'state': get(s, 'state'), 'comments': comments(s),
                               'subIssuesSummary': {'total': subs_total(get(s, 'number'))}}
            return t
        n = number_of(number)
        ps = [p for p in pulls if get(p, 'number') == n]
        if ps:
            p = ps[0]
            start = 0 if cursor == '' else number_of(cursor)
            closes = each(get(p, 'closes')) if get(p, 'closes') is not None else None
            if closes is None:
                fail('the world is not valid')
            nodes = [item(i) for c in closes[start:start + tickets] for i in issues if get(i, 'number') == c]
            target = {'__typename': 'PullRequest', 'number': get(p, 'number'), 'state': get(p, 'state'),
                      'closingIssuesReferences': {'pageInfo': {'hasNextPage': len(closes) > start + tickets,
                                                               'endCursor': tostring(start + tickets)},
                                                  'nodes': nodes}}
        else:
            ii = [i for i in issues if get(i, 'number') == n]
            target = dict({'__typename': 'Issue'}, **item(ii[0] if ii else None))
        out = {'data': {'repository': {'databaseId': 1, 'defaultBranchRef': {'name': w.get('default')},
                                       'issueOrPullRequest': target}}}
    elif op == 'Spec':
        n = number_of(number)
        ss = [i for i in issues if get(i, 'number') == n]
        if not ss:
            out = {'data': {'repository': {'issue': None}}, 'errors': [{'message': 'Could not resolve to an Issue'}]}
        else:
            s = ss[0]
            subs = sort_by([i for i in issues if get(i, 'parent') == get(s, 'number')], lambda i: get(i, 'number'))
            out = {'data': {'repository': {'issue': {
                'number': get(s, 'number'), 'title': get(s, 'title'), 'state': get(s, 'state'),
                'body': alt(get(s, 'body'), ''), 'updatedAt': updated(s), 'comments': comments(s),
                'subIssues': {'pageInfo': {'hasNextPage': truthy(alt(get(s, 'subIssuesTruncated'), False)) or len(subs) > tickets},
                              'nodes': [ticket(t) for t in subs[:tickets]]}}}}}
    else:
        merged = sort_by([p for p in pulls if get(p, 'state') == 'MERGED'], lambda p: get(p, 'updatedAt'))[::-1]
        out = {'data': {'repository': {'pullRequests': window([
            {'number': get(p, 'number'), 'mergedAt': get(p, 'mergedAt'), 'updatedAt': get(p, 'updatedAt'),
             'baseRefName': get(p, 'base'),
             # K9 (#337): a merged one's merge commit.
             'mergeCommit': None if get(p, 'mergeCommit') is None else {'oid': get(p, 'mergeCommit')},
             'closingIssuesReferences': {'nodes': [{'number': c} for c in each(get(p, 'closes'))]}}
            for p in merged])}}}
    data = out['data']
    for k, v in rate.items():
        data[k] = v
    if op == 'Blockers':
        nodes = [{'id': sha_text(get(t, 'number')), 'number': get(t, 'number'),
                  'repository': {'nameWithOwner': w['repo']}, 'labels': t['labels'], 'stateReason': t['stateReason'],
                  'closedByPullRequestsReferences': {'nodes': [
                      {'number': get(p, 'number'), 'merged': get(p, 'merged'), 'baseRefName': get(p, 'baseRefName')}
                      for p in t['closedByPullRequestsReferences']['nodes']]}} for t in data['nodes']]
        data['nodes'] = nodes + [b for b in each_opt(w.get('blockerNodes')) if get(b, 'id') in ids]
    for needle, key in (('blockedBy(first:', 'blockedBy'), ('comments(last:', 'comments'), ('labels(first:', 'labels')):
        if needle not in query:
            out = drop(out, key)
    return compact(out) + '\n'


def jq_slice_last(v):
    """`.[-1:]`: null stays null."""
    if v is None:
        return None
    if not isinstance(v, (list, str)):
        fail('the world is not valid')
    return v[-1:]


def drop(v, key):
    """`walk(if type == "object" then del(.key) else . end)`."""
    if isinstance(v, dict):
        return {k: drop(x, key) for k, x in v.items() if k != key}
    if isinstance(v, list):
        return [drop(x, key) for x in v]
    return v


def rest(w, repo, path, page, paginate, include, accept, conditional, answer):
    # HTTP fixtures keep transport metadata separate from the logical-read log.
    if path.startswith('repositories/1/'):
        path = 'repos/%s/%s' % (repo, path[len('repositories/1/'):])
    rest_page = path.rsplit('&page=', 1)[1] if '&page=' in path else '1'
    if not re.fullmatch(r'[0-9]+', rest_page):
        fail('bad REST page')
    rest_page = int(rest_page)
    out = []
    try:
        result = rest_read(w, repo, path, page, paginate, include, accept, answer, out)
    except Fail as e:
        sys.stderr.write('fake gh: %s\n' % e)
        result = 1
    except Status as e:
        result = e.status
    response = ''.join(out)
    http = '200'
    if '/actions/workflows/ci.yml/runs?' in path:
        http = env.get('FAKE_GH_NIGHTLY_HTTP') or '200'
    if result != 0 and http == '200':
        sys.stdout.write(response)
        return result
    link = ''
    if http == '200' and paginate != 'yes' and 'per_page=100' in path:
        try:
            v = json.loads(response)
        except ValueError:
            fail('bad REST response')
        if isinstance(v, list):
            count = len(v)
        elif isinstance(v, dict):
            count = len(each(v['items'])) if 'items' in v else 0
        else:
            fail('bad REST response')
        n = int(page)
        offset = (rest_page - 1) * n
        if count > offset + n:
            base = path.split('&page=', 1)[0]
            if base.startswith('repos/%s/' % repo):
                base = 'repositories/1/' + base[len('repos/%s/' % repo):]
            link = 'https://api.github.com/%s&page=%d' % (base, rest_page + 1)
        if isinstance(v, list):
            v = v[offset:offset + n]
        elif 'items' in v:
            v['items'] = v['items'][offset:offset + n]
        response = pretty(v) + '\n'
    etag = '"%s"' % hashlib.sha256(response.encode()).hexdigest()
    if include == 'yes':
        if http == '200' and conditional == etag:
            http = '304'
        if env.get('FAKE_GH_HTTP_LOG'):
            with open(env['FAKE_GH_HTTP_LOG'], 'a') as log:
                log.write('%s %s %s\n' % (path, 'conditional' if conditional else 'unconditional', http))
        sys.stdout.write('HTTP/2.0 %s Synthetic\r\nETag: %s\r\n' % (http, etag))
        if link:
            sys.stdout.write('Link: <%s>; rel="next"\r\n' % link)
        sys.stdout.write('\r\n')
        if http == '304':
            sys.stderr.write('gh: HTTP 304\n')
            return 1
    sys.stdout.write(response)
    return result


def between(path, prefix, marker):
    """PATH is PREFIX, then something, then MARKER, then anything: the something."""
    rest = path[len(prefix):]
    return rest[:rest.index(marker)]


def rest_read(w, repo, path, page, paginate, include, accept, answer, out):
    """One REST read: its body into OUT; a failure raises."""
    r = 'repos/%s/' % repo
    issues = lambda: each(w.get('issues'))
    pulls = lambda: each(w.get('pulls'))

    def after(prefix, marker):
        return path.startswith(prefix) and marker in path[len(prefix):]

    if path.startswith(r + 'actions/workflows/ci.yml/runs?'):
        default = w.get('default')
        branch = quote(default if isinstance(default, str) else compact(default), safe='-_.~')
        if path != r + 'actions/workflows/ci.yml/runs?event=schedule&branch=%s&status=completed&per_page=1' % branch or paginate == 'yes':
            fail('unexpected nightly query: ' + path)
        answer('nightly runs branch=' + branch)
        http = env.get('FAKE_GH_NIGHTLY_HTTP') or '200'
        if http != '200':
            # Deliberately misleading JSON: only the actual HTTP status may quiet 404.
            out.append('{"message":"Not Found","status":"404"}\n')
            sys.stderr.write('gh: synthetic HTTP %s\n' % http)
            raise Status(1)
        # The synthetic world is chronological, newest first, like GitHub's list.
        if 'nightlyResponse' in w:
            v = w['nightlyResponse']
        else:
            runs = [x for x in each_opt(w.get('runs')) if get(x, 'path') == '.github/workflows/ci.yml'
                    and get(x, 'event') == 'schedule' and get(x, 'head_branch') == w.get('default')
                    and get(x, 'status') == 'completed']
            v = {'total_count': len(runs), 'workflow_runs': runs[:1]}
        out.append(compact(v) + '\n')
    elif after(r + 'commits/', '/comments?per_page=100'):
        sha = between(path, r + 'commits/', '/comments?per_page=100')
        if paginate != 'yes' and include != 'yes':
            fail('commit comments without pagination')
        answer('commit comments ' + sha)
        if 'commitCommentsResponse' in w:
            out.append(compact(w['commitCommentsResponse']) + '\n')
        else:
            v = [dict({k: x for k, x in c.items() if k != 'author'}, user=author(c))
                 for c in each_opt(w.get('commitComments')) if get(c, 'commit_id') == sha]
            out.append(pages(v, page) if paginate == 'yes' else compact(v) + '\n')
    elif path.startswith(r + 'contents/'):
        f = path[len(r + 'contents/'):]
        answer('contents ' + f)
        if accept != 'raw':
            fail('contents without the raw Accept header')
        files = w.get('files')
        if not isinstance(files, dict) or f not in files:
            fail('HTTP 404: ' + f)
        v = files[f]
        out.append(v if isinstance(v, str) else pretty(v))
    elif after(r + 'pulls/', '/files?per_page=100'):
        n = between(path, r + 'pulls/', '/files?per_page=100')
        answer('files ' + n)
        if paginate != 'yes' and include != 'yes':
            fail('files without pagination')
        try:
            num = json.loads(n)
        except ValueError:
            fail('HTTP 404: pull ' + n)
        ps = [p for p in pulls() if get(p, 'number') == num]
        files = get(ps[0], 'files') if ps else None
        if not truthy(files):
            fail('HTTP 404: pull ' + n)
        out.append(pages(files, page) if paginate == 'yes' else compact(files) + '\n')
    elif path.startswith(r + 'issues?state=open&per_page=100'):
        answer('issues page=%s' % path_page(path))
        lag = argjson(env.get('FAKE_GH_SUMMARY_LAG') or '0')
        v = []
        for i in issues():
            if get(i, 'state') != 'OPEN':
                continue
            subs = [s for s in issues() if get(s, 'parent') == get(i, 'number')]
            v.append({'number': get(i, 'number'), 'body': alt(get(i, 'body'), ''), 'updated_at': updated(i),
                      'sub_issues_summary': {'total': max(len(subs) - lag, 0),
                                             'completed': len([s for s in subs if get(s, 'state') == 'CLOSED'])}})
        out.append(compact(v) + '\n')
    elif path.startswith('search/issues?q='):
        answer('search issues page=%s' % path_page(path))
        encoded = path[len('search/issues?q='):].split('&', 1)[0]
        lbl = encoded.split('label%3A%22', 1)[1] if 'label%3A%22' in encoded else encoded
        if lbl.endswith('%22%20no%3Aparent-issue'):
            lbl = lbl[:-len('%22%20no%3Aparent-issue')]
        elif lbl.endswith('%22'):
            lbl = lbl[:-len('%22')]
        cap = argjson(env.get('FAKE_GH_SEARCH_CAP') or '1000')
        # F6's open-work search (#1353) has no `no:parent-issue` and asks `is:open`.
        whole = 'no%3Aparent-issue' not in encoded
        found = [i for i in issues() if (whole or get(i, 'parent') is None)
                 and ('is%3Aopen' not in encoded or get(i, 'state') == 'OPEN')
                 and any(l == lbl for l in each_opt(get(i, 'labels')))]
        found = sort_by(found, lambda i: alt(get(i, 'updatedAt'), ''))[::-1]
        out.append(compact({'total_count': len(found), 'incomplete_results': False,
                            'items': [{'number': get(i, 'number'), 'node_id': sha_text(get(i, 'number')),
                                       'state': ascii_downcase(get(i, 'state'))} for i in found[:cap]]}) + '\n')
    elif after(r + 'issues/', '/dependencies/blocked_by?per_page=100'):
        n = path[len(r + 'issues/'):].split('/', 1)[0]
        answer('dependencies %s page=%s' % (n, path_page(path)))
        num = argjson(n)
        found = [i for i in issues() if get(i, 'number') == num]
        i = found[0] if found else None
        responses = alt(w.get('dependencyResponses'), {})
        if not isinstance(responses, dict):
            fail('the world is not valid')
        if tostring(num) in responses:
            v = responses[tostring(num)]
        else:
            v = [{'number': get(x, 'number'), 'node_id': sha_text(get(x, 'number')), 'state': ascii_downcase(get(x, 'state'))}
                 for b in each_opt(get(i, 'blockedBy')) for x in issues() if get(x, 'number') == b]
            if truthy(get(i, 'blockersTruncated')):
                v += [{'number': 900000 + k, 'node_id': 'I_unused', 'state': 'open'} for k in range(1, 22)]
        out.append(compact(v) + '\n')
        if not truthy(v):
            raise Status(1)
    elif after(r + 'issues/', '/comments?per_page=100'):
        n = path[len(r + 'issues/'):].split('/', 1)[0]
        answer('issue comments %s page=%s' % (n, path_page(path)))
        num = argjson(n)
        found = [x for x in issues() + pulls() if get(x, 'number') == num]
        if not found:
            raise Status(4)
        i = found[0]
        old = ([{'id': 1 + k, 'at': '2026-01-01T00:00:00Z', 'body': 'Synthetic old comment'} for k in range(51)]
               if truthy(get(i, 'commentsTruncated')) else [])
        cs = alt(get(i, 'comments'), [])
        if not isinstance(cs, list):
            fail('the world is not valid')
        out.append(compact([{'id': get(c, 'id'), 'created_at': get(c, 'at'), 'updated_at': alt(get(c, 'edited'), get(c, 'at')),
                             'user': author(c), 'body': get(c, 'body')} for c in old + cs]) + '\n')
    elif path == r[:-1]:
        # GI1 (#2543): the repository, as the unchanged probe reads it.
        answer('repository')
        out.append(compact({'id': 1, 'full_name': repo, 'private': truthy(w.get('private', True)),
                            'default_branch': w.get('default')}) + '\n')
    elif path == 'user':
        # GI1: the authenticated account; a world's "login" stands for a changed one.
        answer('user')
        out.append(compact({'login': alt(w.get('login'), 'synthetic-user'), 'id': 1}) + '\n')
    elif path == 'installation/repositories?per_page=100':
        # GI7 (#2549): what an App installation token covers; a world's
        # "installation" stands for another installation.
        answer('installation repositories')
        out.append(compact({'total_count': 1, 'repository_selection': 'selected',
                            'repositories': [{'id': 1, 'full_name': repo,
                                              'installation': alt(w.get('installation'), 'synthetic-installation')}]}) + '\n')
    elif after(r + 'issues/', '/sub_issues?per_page=100'):
        n = path[len(r + 'issues/'):].split('/', 1)[0]
        answer('sub issues %s page=%s' % (n, path_page(path)))
        subs = sort_by(children(w, argjson(n)), lambda i: get(i, 'number'))
        out.append(compact([{'number': get(i, 'number'), 'title': get(i, 'title'), 'state': ascii_downcase(get(i, 'state')),
                             'updated_at': updated(i), 'labels': [{'name': l} for l in each_opt(get(i, 'labels'))]}
                            for i in subs]) + '\n')
    elif after(r + 'issues/', '/timeline?per_page=100'):
        # GI1: what GraphQL's labelled events and closing references read, as events.
        n = path[len(r + 'issues/'):].split('/', 1)[0]
        answer('timeline %s page=%s' % (n, path_page(path)))
        num = argjson(n)
        found = [i for i in issues() if get(i, 'number') == num]
        events = [{'event': 'labeled', 'created_at': get(e, 'at'), 'label': {'name': get(e, 'name')}}
                  for i in found for e in label_events(i)]
        events += [{'event': 'connected', 'source': {'issue': {'number': get(p, 'number')}}}
                   for p in pulls() if any(c == num for c in each_opt(get(p, 'closes')))]
        out.append(compact(events) + '\n')
    elif after(r + 'commits/', '/check-runs?per_page=100') or after(r + 'commits/', '/status'):
        # GI1: a head's checks, from the pull requests at that head.
        sha = path[len(r + 'commits/'):].split('/', 1)[0]
        kind = 'check runs' if '/check-runs?' in path else 'status'
        answer('%s %s' % (kind, sha))
        ps = [p for p in pulls() if get(p, 'head') == sha]
        cs = [c for p in ps for c in (each_opt(get(p, 'checks')))]
        if kind == 'status':
            out.append(compact({'state': get(ps[0], 'rollup') if ps else None, 'sha': sha,
                                'statuses': [c for c in cs if get(c, 'type') == 'StatusContext']}) + '\n')
        else:
            runs = [c for c in cs if get(c, 'type') != 'StatusContext']
            out.append(compact({'total_count': len(runs), 'check_runs': runs}) + '\n')
    elif path.startswith(r + 'git/ref/heads/'):
        # GI1: the default branch moves with every merge.
        answer('ref ' + path[len(r + 'git/ref/'):])
        merged = sort_by([p for p in pulls() if get(p, 'state') == 'MERGED'], lambda p: get(p, 'number'))
        tip = hashlib.sha1(compact([[get(p, 'number'), get(p, 'mergedAt'), get(p, 'mergeCommit')] for p in merged]).encode()).hexdigest()
        out.append(compact({'ref': 'refs/' + path[len(r + 'git/ref/'):], 'object': {'type': 'commit', 'sha': tip}}) + '\n')
    elif path.startswith(r + 'issues/') or path.startswith(r + 'pulls/'):
        # Files are handled above, before this broad detail matcher.
        n = path.rsplit('/', 1)[1]
        answer('detail ' + n)
        num = argjson(n)
        found = [i for i in issues() if get(i, 'number') == num]
        if found:
            i = found[0]
            v = {'number': get(i, 'number'), 'title': get(i, 'title'), 'state': ascii_downcase(get(i, 'state')),
                 'state_reason': state_reason(i, ascii_downcase),
                 'body': alt(get(i, 'body'), ''), 'updated_at': updated(i),
                 'labels': [{'name': l} for l in each_opt(get(i, 'labels'))]}
        else:
            ps = [p for p in pulls() if get(p, 'number') == num]
            if not ps:
                raise Status(4)
            p = ps[0]
            pull_head = env.get('FAKE_GH_PULL_HEAD') or ''
            v = {'number': get(p, 'number'), 'title': 'Synthetic pull request', 'body': '',
                 'state': 'open' if get(p, 'state') == 'OPEN' else 'closed', 'merged': get(p, 'state') == 'MERGED',
                 'merged_at': get(p, 'mergedAt'), 'closed_at': get(p, 'closedAt'), 'updated_at': get(p, 'updatedAt'),
                 'draft': alt(get(p, 'draft'), False), 'base': {'ref': get(p, 'base')},
                 'head': {'sha': pull_head if get(p, 'state') == 'OPEN' and pull_head != '' else get(p, 'head')}}
        out.append(compact(v) + '\n')
    elif path.startswith(r + 'git/matching-refs/'):
        prefix = path[len(r + 'git/matching-refs/'):]
        answer('refs ' + prefix)
        out.append(compact([{'ref': 'refs/heads/' + x, 'object': {'type': 'commit', 'sha': '0' * 40}}
                            for x in each(w.get('refs')) if ('heads/' + x).startswith(prefix)]) + '\n')
    else:
        fail('unexpected read: ' + path)
    return 0


def path_page(path):
    return path.rsplit('&page=', 1)[1] if '&page=' in path else '1'


def run(argv):
    """The call's exit status; for test.sh's timing wrapper too."""
    try:
        return main(argv)
    except Fail as e:
        sys.stdout.flush()
        sys.stderr.write('fake gh: %s\n' % e)
        return 1
    except Status as e:
        return e.status
    finally:
        sys.stdout.flush()


if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
