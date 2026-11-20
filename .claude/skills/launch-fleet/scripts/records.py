#!/usr/bin/env python3
"""Resolve fleet records from public facts. Thread identities never become public records.

Optional private state: {"repo": "owner/name", "threads": {"builder:N": "...",
"review:P:FULL_START_COMMIT": "...", "review:P:claim:COMMENT_ID": "...",
"comment:COMMENT_ID": "..."}}.
Readers never update it. Starters save it privately before recording success.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ID = re.compile(r'\bthr_[A-Za-z0-9][A-Za-z0-9_-]*')
SHA = r'[0-9a-f]{40}'


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON key')
        value[key] = item
    return value


def first(body):
    return next((line.strip() for line in body.splitlines() if line.strip()), '')


def private_state(repo):
    path = os.environ.get('LAUNCH_FLEET_STATE')
    if not path:
        return {}
    source = Path(path)
    if not source.is_absolute():
        raise ValueError('private state needs an absolute path')
    value = json.loads(source.read_text(), object_pairs_hook=unique)
    if (not isinstance(value, dict) or set(value) != {'repo', 'threads'} or value['repo'] != repo
            or not isinstance(value['threads'], dict)
            or not all(isinstance(k, str) and isinstance(v, str) and ID.fullmatch(v)
                       for k, v in value['threads'].items())):
        raise ValueError('unreadable private record map')
    return value['threads']


def discover():
    try:
        r = subprocess.run(['room-cli', 'thread', 'list', '--include-archived', '--include-hidden', '--json'],
                           capture_output=True, text=True, timeout=10)
        if r.returncode:
            return None
        rows = json.loads(r.stdout, object_pairs_hook=unique)
        if not isinstance(rows, list) or any(not isinstance(t, dict) or not isinstance(t.get('id'), str)
                                            or not ID.fullmatch(t['id']) for t in rows):
            return None
        if len({t['id'] for t in rows}) != len(rows):
            return None
        return rows
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def choose(key, matches, state, threads):
    saved = state.get(key)
    if threads is None:
        return (saved, None) if saved else (None, 'thread discovery is out of reach')
    if len(matches) > 1:
        return None, 'two threads match ' + key
    found = matches[0]['id'] if matches else None
    if saved and found and saved != found:
        return None, 'private state and CloudRoom disagree for ' + key
    if saved:
        # A saved identity is authoritative when title discovery finds nothing.
        return saved, None
    return (found, None) if found else (None, 'no thread matches ' + key)


UNREADABLE, UNSET, MISSING = object(), object(), object()


def driver_runs(repo):
    """host.py's runs ({N: run}) from LAUNCH_FLEET_RUNS (#1371), stopped ones too.

    UNSET when the wake restored no run map, MISSING when its file isn't there, UNREADABLE when it doesn't read."""
    path = os.environ.get('LAUNCH_FLEET_RUNS')
    if not path:
        return UNSET
    if not os.path.exists(path):
        return MISSING
    sys.dont_write_bytecode = True  # never leave caches in an installed skill
    spec = importlib.util.spec_from_file_location('launch_fleet_host', Path(__file__).resolve().parent / 'host.py')
    host = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(host)
    try:
        return host.load(repo)['runs']
    except host.Unreadable:
        return UNREADABLE


def builder_thread(n, branch, threads, state, runs=None):
    if runs is UNREADABLE:
        return None, 'the private runs file is unreadable'
    if runs is MISSING:
        return None, 'the private run map LAUNCH_FLEET_RUNS was not restored from the private state'
    if isinstance(runs, dict) and str(n) in runs:
        # Started through a host driver: host.py wakes and stops it (a stop answers again); no CloudRoom thread exists.
        return f'run:{n}', None
    saved = state.get(f'builder:{n}')
    if branch and any(t['id'] == saved and t.get('branch') is not None and t['branch'] != branch for t in threads or []):
        return None, 'private state disagrees with the checked builder branch'
    matches = [t for t in threads or [] if isinstance(t.get('title'), str)
               and t['title'].startswith(f'#{n}: ')
               and (branch is None or t.get('branch') == branch)]
    found, error = choose(f'builder:{n}', matches, state, threads)
    if runs is UNSET and error == f'no thread matches builder:{n}':
        error += ', and no private run map LAUNCH_FLEET_RUNS was restored'
    return found, error


def reviewer_thread(n, commit, threads, state, claim=None, retired=()):
    # Claim IDs survive edits and distinguish replacements at the same head.
    saved = state.get(f'review:{n}:claim:{claim}')
    if saved:
        state = {**state, f'review:{n}:{commit}': saved}
    threads = [t for t in threads if t['id'] not in retired] if threads is not None else None
    pattern = re.compile(rf'Review #{n} at ([0-9a-f]{{1,40}})')
    matches = [t for t in threads or [] if (m := pattern.fullmatch(t.get('title') or '')) and commit.startswith(m[1])]
    return choose(f'review:{n}:{commit}', matches, state, threads)


def annotate(world, repo, private, threads, state):
    """Attach private routing metadata; preserve every original body and comment position."""
    runs = driver_runs(repo)

    def item(obj):
        span = []
        retired = set()
        start = None
        start_claim = None
        routes = dict(state)
        comments = sorted(obj.get('comments', {}).get('nodes', []), key=lambda c: (c['createdAt'], c['databaseId']))
        for c in comments:
            line = first(c['body']).removeprefix('launch-fleet: ')
            c['recordError'] = None
            legacy = ID.search(line)
            if legacy:
                if not private:
                    c['recordError'] = 'legacy thread record is not accepted in public'
                    continue
                if ', thread ' + legacy[0] in line:
                    c['resolvedThread'] = legacy[0]
                gave_up = re.fullmatch(rf'review failed {SHA}, thread thr_[A-Za-z0-9_-]+: .+', line)
                # Historical private starts may put a model note after the thread.
                line = re.sub(rf'^(review started {SHA}), thread thr_[A-Za-z0-9_-]+ \(.+\)$',
                              r'\1', line)
                line = re.sub(r', thread thr_[A-Za-z0-9_-]+', '', line)
                if gave_up:
                    line = line.replace('review failed ', 'review given up ', 1)
            branch = re.fullmatch(r'start checked, branch ([A-Za-z0-9._/-]+)', line)
            if not legacy and (line == 'started' or branch):
                c['resolvedThread'], c['recordError'] = builder_thread(obj['number'], branch[1] if branch else None, threads, state, runs)
            review = re.fullmatch(rf'(review started|re-check sent|review told again|review given up) ({SHA})(?:: .+)?', line)
            if review:
                kind, commit = review.groups()
                if kind == 'review given up' and start is None and legacy:
                    start = commit
                edited_start = kind == 'review given up' and f'review:{obj["number"]}:claim:{c["databaseId"]}' in state
                if kind == 'review started' or edited_start:
                    # A retained start-claim key also marks the boundary after an edit.
                    span, start, start_claim = [], commit, c['databaseId']
                    if legacy and c.get('resolvedThread'):
                        routes[f'review:{obj["number"]}:{commit}'] = c['resolvedThread']
                span.append(c)
                if kind == 'review given up':
                    # Preserve the retired identity for archival only. An edited start
                    # has no public start commit left; its immutable claim key survives.
                    identity = state.get(f'review:{obj["number"]}:claim:{c["databaseId"]}')
                    identity = identity or state.get(f'review:{obj["number"]}:claim:{start_claim}')
                    identity = identity or next((r.get('archiveThread') or r.get('resolvedThread')
                                                 for r in span if r.get('archiveThread') or r.get('resolvedThread')), None)
                    if identity is None:
                        identity, _ = reviewer_thread(obj['number'], start or commit, threads, routes, start_claim, retired)
                    c['archiveThread'] = identity
                    if identity:
                        retired.add(identity)
                    # An edited claim keeps its position; close records later in this span too.
                    for record in span:
                        record['reviewClosed'] = True
                        if record.get('resolvedThread'):
                            retired.add(record['resolvedThread'])
                        record['recordError'] = None
                    c['givenUp'] = True
                elif start is None:
                    c['recordError'] = 'review record has no readable start on this pull request'
                elif not legacy:
                    c['resolvedThread'], c['recordError'] = reviewer_thread(obj['number'], start, threads, routes, start_claim, retired)
                if c.get('resolvedThread') in retired:
                    c['recordError'] = 'reviewer was already given up on this pull request'
                if any(record.get('givenUp') for record in span):
                    c['reviewClosed'] = True
                    c['recordError'] = None
            if re.fullmatch(r'(?:resume starting [0-9]+ for #[0-9]+|release starting [0-9]+)', line):
                c['resolvedThread'] = state.get('comment:' + str(c['databaseId']))
        for child in obj.get('subIssues', {}).get('nodes', []):
            item(child)
        for child in obj.get('closedByPullRequestsReferences', {}).get('nodes', []):
            item(child)
    for obj in world['specs'] + world['singles']:
        item(obj)
    return world


def _effects():
    import importlib.util
    sys.dont_write_bytecode = True  # never leave caches in an installed skill
    spec = importlib.util.spec_from_file_location('ops_effects', Path(__file__).resolve().parent / 'effects.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ops_owner(claims, effects=None):
    """#1456: the current logical fleet owner from the complete admitted generation history.

    The caller supplies every admitted generation claim it read back for one
    repository/spec. Returns (repository, spec, generation, owner): the owner
    belongs to that fleet only. A gap, fork or mixed history selects no owner
    (ValueError); an empty history has generation 0 and no fleet or owner.
    """
    effects = effects or _effects()
    claims = [effects.read_record(json.dumps(c, allow_nan=False)) for c in claims]
    if any(c['kind'] != 'claim' or c['scope'] != 'generation' for c in claims):
        raise ValueError('not a generation claim')
    if len({(c['repository'], c['spec']) for c in claims}) > 1:
        raise ValueError('generation history spans two fleets')
    claims.sort(key=lambda c: c['generation'])
    if [c['generation'] for c in claims] != list(range(1, len(claims) + 1)):
        raise ValueError('incomplete or forked generation history')
    if not claims:
        return (None, None, 0, None)
    last = claims[-1]
    return (last['repository'], last['spec'], last['generation'], last['owner'])


def ops_pass(view, effect_boundary, effects=None):
    """#1456: one finite pass over candidate operations; never executes an effect.

    view: {"pass": {"generation", "owner"}, "generations": [admitted generation
    claims], "operations": [{"intent", "claim", "history", "snapshot"}]}. The
    handlers that build intents (#1480, #1481, #2112, #2338, #2339) supply the
    operations. Every copy first goes through OB3's resume, whose effect
    boundary stays uncalled under OB-A1, and its own records are checked to
    hold together. Recorded uncertainty from any readable copy wins: the
    operation is reconcile on its first valid copy, whatever its generation.
    Otherwise a valid copy outside the current owner's fleet (repository, spec,
    generation, owner) is refused stale_claim. Only a valid copy that is
    reconciled or current consumes its key; a later copy of a consumed key
    (project and spec ticks share keys) is a duplicate. Invalid, mismatched and
    stale copies consume nothing and never block other operations. Returns one
    schema-valid result per operation, in input order.
    """
    effects = effects or _effects()
    repository, spec, generation, owner = ops_owner(view['generations'], effects)
    mine = (view['pass']['generation'], view['pass']['owner'])

    def result(intent, state, reason):
        key = intent.get('operation_key') if isinstance(intent, dict) else None
        ident = intent.get('id') if isinstance(intent, dict) else None
        key = key if isinstance(key, str) and re.fullmatch('[0-9a-f]{64}', key) else '0' * 64
        ident = ident if isinstance(ident, str) and re.fullmatch('[a-z][a-z0-9-]{0,79}', ident) else 'unreadable'
        return dict(schema='openwiz.ops-dispatch.v1', kind='result', operation_key=key, intent_id=ident,
                    state=state, reason=reason, next='end', effects=[])

    def fleet(record):
        return isinstance(record, dict) and (record.get('repository'), record.get('spec')) == (repository, spec)

    def bound(intent, operation, outcome):
        # A copy's own records must hold together. Checked with its history and
        # snapshot uncertainty set aside, so uncertainty-first cannot vouch for a
        # mismatched claim or snapshot.
        if outcome['reason'] in ('incomplete_read', 'stale_binding'):
            return False
        probe = effects.resume(intent, operation['claim'], [], dict(operation['snapshot'], uncertain_keys=[]),
                               effect_boundary)
        return probe['reason'] not in ('incomplete_read', 'stale_binding')

    def current(intent, operation):
        # Both the operation's claim and its snapshot must belong to the current
        # generation and owner before a non-reconcile copy may consume its key.
        claim, snapshot = operation['claim'], operation['snapshot']
        return (mine == (generation, owner) and all(map(fleet, (intent, claim, snapshot)))
                and all((record['generation'], record['owner']) == (generation, owner)
                        for record in (claim, snapshot)))

    candidates = []
    for operation in view['operations']:
        intent = operation.get('intent') if isinstance(operation, dict) else None
        try:
            intent = effects.read_record(json.dumps(intent, allow_nan=False))
            if intent['kind'] != 'intent':
                raise ValueError('not an intent')
            outcome = effects.read_record(json.dumps(effects.resume(
                intent, operation['claim'], operation['history'], operation['snapshot'], effect_boundary)))
            valid = bound(intent, operation, outcome)
        except (KeyError, TypeError, ValueError):
            candidates.append((intent, None, result(intent, 'refused', 'incomplete_read'), False))
            continue
        unsure = outcome['state'] == 'reconcile'
        if not valid and unsure:
            outcome = result(intent, 'refused', 'stale_binding')
        candidates.append((intent, operation if valid else None, outcome, unsure))
    # Proven uncertainty from any copy whose intent was readable stays with the operation.
    uncertain = {intent['operation_key'] for intent, _, _, unsure in candidates if unsure}
    consumed = set()
    results = []
    for intent, operation, outcome, _ in candidates:
        if operation is None:
            results.append(outcome)
            continue
        key = intent['operation_key']
        if key in consumed:
            results.append(result(intent, 'duplicate', 'record_only'))
        elif key in uncertain:
            consumed.add(key)
            results.append(result(intent, 'reconcile', 'uncertain_outcome'))
        elif not current(intent, operation):
            # A stale copy is refused and consumes nothing: a current copy may follow.
            results.append(result(intent, 'refused', 'stale_claim'))
        else:
            consumed.add(key)
            results.append(outcome)
    return results


def main():
    if sys.argv[1:] == ['ops-pass']:
        def refuse(*_):
            raise RuntimeError('OB-A1: effects are disabled')
        try:
            view = json.loads(sys.stdin.read(), object_pairs_hook=unique)
            for item in ops_pass(view, refuse):
                print(json.dumps(item, sort_keys=True))
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'records: ops pass refused: {error}', file=sys.stderr)
            return 2
        return 0
    world = json.load(sys.stdin)
    repo, private = sys.argv[1:]
    # Avoid CloudRoom entirely for legacy-only inputs and ordinary frontier checks.
    def needed(x):
        if isinstance(x, dict):
            if isinstance(x.get('body'), str) and re.match(r'^launch-fleet: (started$|start checked, branch |review started |re-check sent )', first(x['body'])) and not ID.search(first(x['body'])):
                return True
            return any(needed(v) for v in x.values())
        return isinstance(x, list) and any(needed(v) for v in x)
    try:
        state = private_state(repo)
        threads = discover() if needed(world) else None
        json.dump(annotate(world, repo, private == 'true', threads, state), sys.stdout)
    except (OSError, ValueError, KeyError, TypeError):
        print('records: private routing state could not be read', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
