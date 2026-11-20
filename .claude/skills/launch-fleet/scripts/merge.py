#!/usr/bin/env python3
"""Merge one approved pull request at its exact head, then post the ticket's cost (WS8, #1181).

  merge.py read  OWNER/NAME PR HEAD
  merge.py admit OWNER/NAME PR HEAD CHECKS
  merge.py merge OWNER/NAME PR HEAD CHECKS BODY --ticket N [--base-rule-checked] [-- COST ARGS]
  merge.py cost  OWNER/NAME PR HEAD TICKET [-- COST ARGS]

`read` prints where the pull request stands: `merged <commit>`, `queued`,
`open, the merge queue is on|off[; it left the queue at <time>: <reason>]` or
`stop: <why>`. `admit` prints `admit: ...`, `base rule: no merge queue;
mergeable: <state>` or `wait: <why>`; CHECKS are fleet.md's required checks,
comma-separated. Both only read.

`merge` reads, admits and merges HEAD with `gh pr merge --merge
--match-head-commit` (never `--admin`), reads it back and records the outcome:
`merged <commit>; cost ...` (exit 0), `queued; recorded <id>` (exit 0),
`pending: ...` (exit 0, nothing recorded: read again next wake),
`blocked: <why>; recorded <id>` (exit 1). Without a merge queue it merges only
with `--base-rule-checked`, after you applied fleet.md's base rule and
`fleet.sh every` still prints this merge line. BODY names the APPROVE and the
plan approval that allowed it.

`cost`, also run by `merge` after a verified merge, runs the project's FM4
command `tools/collector/cost_line.py --repo OWNER/NAME --pr PR [COST ARGS]`
from the current directory and posts `launch-fleet: cost: <its line>` on the
ticket, or `launch-fleet: cost unknown (PR #PR): <why>`; never a zero for an
unknown part. It posts once: `cost already posted <id>` names an earlier
record author's record. It refuses before a verified merge at HEAD.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_post', HERE / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)
Stop = post.Stop

QUERY = '''query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { defaultBranchRef { name } pullRequest(number: $number) {
    state baseRefName headRefOid isMergeQueueEnabled isInMergeQueue mergeable mergeCommit { oid }
    mergeQueueEntry { headCommit { oid } }
    timelineItems(itemTypes: [REMOVED_FROM_MERGE_QUEUE_EVENT], last: 1) {
      nodes { ... on RemovedFromMergeQueueEvent { createdAt reason } } }
    commits(last: 1) { nodes { commit { oid statusCheckRollup { contexts(first: 50) { pageInfo { hasNextPage }
      nodes { __typename ... on CheckRun { name conclusion } ... on StatusContext { context state } } } } } } } } } }'''
COST = 'tools/collector/cost_line.py'
SHA = re.compile(r'[0-9a-f]{40}')


def snapshot(repo, number):
    owner, name = repo.split('/')
    value = post.read_json('api', 'graphql', '-f', f'owner={owner}', '-f', f'name={name}', '-F', f'number={number}',
                           '-f', f'query={QUERY}')
    try:
        r = value['data']['repository']
        return r['defaultBranchRef']['name'], r['pullRequest']
    except (TypeError, KeyError):
        raise Stop('stop: the pull request could not be read')


def where(main, p, head):
    if not isinstance(p, dict):
        return 'stop: no such pull request'
    if p['headRefOid'] != head:
        return f"stop: its head is {p['headRefOid']}, not {head}"
    if p['baseRefName'] != main:
        return f"stop: its base is {p['baseRefName']}, not the default branch {main}"
    if p['state'] == 'MERGED' and isinstance((p.get('mergeCommit') or {}).get('oid'), str):
        return 'merged ' + p['mergeCommit']['oid']
    entry = ((p.get('mergeQueueEntry') or {}).get('headCommit') or {}).get('oid')
    if p['state'] == 'OPEN' and p['isInMergeQueue'] is True and entry == head:
        return 'queued'
    if p['state'] == 'OPEN' and p['isInMergeQueue'] is False and type(p['isMergeQueueEnabled']) is bool:
        nodes = (p.get('timelineItems') or {}).get('nodes') or []
        left = nodes[-1] if nodes else None
        return ('open, the merge queue is ' + ('on' if p['isMergeQueueEnabled'] else 'off')
                + (f"; it left the queue at {left['createdAt']}: {left['reason']}" if left else ''))
    return f"stop: {p['state']}, in the merge queue: {p['isInMergeQueue']}"


def admission(main, p, head, checks):
    if not isinstance(p, dict):
        return 'wait: no such pull request'
    if p['state'] != 'OPEN':
        return f"wait: it is {p['state']}, not open"
    commit = ((p.get('commits') or {}).get('nodes') or [{}])[0].get('commit') or {}
    if p['headRefOid'] != head or commit.get('oid') != head:
        return f"wait: its head is {p['headRefOid']}, not {head}"
    if p['baseRefName'] != main:
        return f"wait: its base is {p['baseRefName']}, not the default branch {main}"
    contexts = (commit.get('statusCheckRollup') or {}).get('contexts') or {}
    if (contexts.get('pageInfo') or {}).get('hasNextPage') is not False:
        return 'wait: its head has more checks than one read shows'
    green = {n.get('name') or n.get('context') for n in contexts.get('nodes') or []
             if (n.get('conclusion') or n.get('state')) == 'SUCCESS'}
    missing = [c for c in checks if c not in green]
    if missing:
        return 'wait: not every required check is green on it: ' + ', '.join(missing)
    if p['isMergeQueueEnabled'] is True:
        return f'admit: the merge queue re-tests it on the latest {main}'
    if p['isMergeQueueEnabled'] is False:
        return f"base rule: no merge queue; mergeable: {p['mergeable']}"
    return 'wait: whether the merge queue is on is unknown'


def record(repo, number, body):
    try:
        return post.comment(repo, number, body).split()[-1]
    except Stop as outcome:
        return f'not recorded ({outcome})'


def cost(repo, number, head, ticket, extra=()):
    state = where(*snapshot(repo, number), head)
    if not state.startswith('merged '):
        raise Stop(f'refused: no verified merge at {head} ({state})')
    auth = post.authors(repo)
    for c in post.thread(repo, ticket) or []:
        first = (c.get('body') or '').split('\n', 1)[0]
        if post.ours(c, auth) and first.startswith('launch-fleet: cost') and f'(PR #{number})' in first:
            return f"cost already posted {c['id']}"
    body = f'launch-fleet: cost unknown (PR #{number}): '
    if not Path(COST).is_file():
        body += 'no cost command'
    else:
        try:
            r = subprocess.run([sys.executable, '-I', COST, '--repo', repo, '--pr', str(number), *extra],
                               capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
            out, err, code = r.stdout.splitlines(), r.stderr.strip(), r.returncode
        except (OSError, subprocess.TimeoutExpired):
            out, err, code = [], '', None
        reason = re.fullmatch(r'cost: ([A-Za-z0-9 #,.()-]+); nothing printed', err)
        if code == 0 and len(out) == 1 and out[0].startswith(f'Ticket #{ticket} cost (PR #{number}): '):
            body = 'launch-fleet: cost: ' + out[0]
        elif code == 0:
            body += 'unexpected cost output'
        else:
            body += reason.group(1) if reason else 'the cost command failed'
    return 'cost posted ' + post.comment(repo, ticket, body).split()[-1]


def merge(repo, number, head, checks, body, ticket, checked, extra):
    def blocked(why):
        raise Stop(f'blocked: {why}; recorded ' + record(repo, number, f'launch-fleet: merge blocked {head}: {why}'))

    main, p = snapshot(repo, number)
    state = where(main, p, head)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        return 'queued; the queue merges it or lets it go'
    if state.startswith('stop: '):
        blocked(state[6:])
    if '; it left the queue at ' in state:
        auth = post.authors(repo)
        if any(post.ours(c, auth) and (c.get('body') or '').startswith(f'launch-fleet: merge queued {head}')
               for c in post.thread(repo, number) or []):
            blocked('left the merge queue: ' + state.split(': ', 1)[1])
    admit = admission(main, p, head, checks)
    if admit.startswith('wait: '):
        blocked(admit[6:])
    if admit.startswith('base rule: ') and not checked:
        raise Stop(admit + '; check the base rule and fleet.sh every, then pass --base-rule-checked')
    done = post.gh('pr', 'merge', str(number), '--repo', repo, '--merge', '--match-head-commit', head,
                   '--body', body) is not None
    state = where(*snapshot(repo, number), head)
    if state.startswith('merged '):
        return state + '; ' + cost(repo, number, head, ticket, extra)
    if state == 'queued':
        return 'queued; recorded ' + record(repo, number, f'launch-fleet: merge queued {head}: {body}')
    if state.startswith('open') and done:
        return 'pending: the merge command succeeded but it still reads open; read it again next wake'
    blocked(state[6:] if state.startswith('stop: ') else state)


def main(argv):
    extra = []
    if '--' in argv:
        at = argv.index('--')
        argv, extra = argv[:at], argv[at + 1:]
    usage = __doc__.split('\n\n')[1]
    try:
        verb, repo, number, head, *rest = argv
        number = int(number) if re.fullmatch(r'[1-9][0-9]{0,11}', number) else None
        ok = post.REPO.fullmatch(repo) and number and SHA.fullmatch(head)
    except ValueError:
        ok = False
    if not ok:
        print(usage, file=sys.stderr)
        return 2
    try:
        if verb == 'read' and not rest:
            print(where(*snapshot(repo, number), head))
        elif verb == 'admit' and len(rest) == 1:
            print(admission(*snapshot(repo, number), head, rest[0].split(',')))
        elif verb == 'cost' and len(rest) == 1 and rest[0].isdigit():
            print(cost(repo, number, head, int(rest[0]), extra))
        elif verb == 'merge' and len(rest) >= 4 and rest[2] == '--ticket' and rest[3].isdigit() \
                and set(rest[4:]) <= {'--base-rule-checked'}:
            print(merge(repo, number, head, rest[0].split(','), rest[1], int(rest[3]),
                        '--base-rule-checked' in rest[4:], extra))
        else:
            print(usage, file=sys.stderr)
            return 2
    except Stop as outcome:
        print(outcome)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
