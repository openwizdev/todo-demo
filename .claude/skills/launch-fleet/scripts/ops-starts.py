#!/usr/bin/env python3
"""OB5 (#1480): approved builder starts and initial green-head reviews in one finite ops pass.

The ops agent reads GitHub and CloudRoom completely and supplies the facts per
candidate (see ../test/ops-starts/README.md). This module checks every start
gate, selects the configured settings and the other-family reviewer from
docs/agents/fleet.md, builds or reuses the one durable `intent` for each
eligible start, and runs it through #1456's ops pass and OB3's boundary. Under
OB-A1 every start stays disabled: `effect_boundary` is never called, and the
result is recorded and the pass ends. Nothing here waits, polls or retries.
"""
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True  # never leave caches in an installed skill


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load(HERE / 'effects.py', 'ops_effects')
records = _load(HERE / 'records.py', 'fleet_records')

TABLES = {'builder': 'Builder', 'small': 'Builder for small tickets',
          'claude-code': 'Reviewer for Claude-built', 'codex': 'Reviewer for GPT-built'}
SMALL = {'polish', 'huntr', 'proposal'}
NOT_READY = {'needs-info', 'needs-triage', 'ready-for-human', 'wontfix', 'held'}
SETTLED = {'completed', 'superseded', 'reconciled_not_executed', 'disabled', 'refused'}
BENCH = 'closedwiz.journey.stage-bench.v1'
# Explicitly synthetic audit example; no recorded factory measurement and no
# recovered-time claim. These invented values illustrate the report's shape.
PROVENANCE = {
    'source': 'synthetic audit example, not an operational measurement',
    'cohort': 'invented merged and open pull requests',
    'initial_review_handoffs': 10,
    'green_to_dispatch_pr_hours': 2.5,
    'meaning': 'synthetic ceiling only; gated intervals and unproven authority are not recoverable time',
}


BUILDER_FIELDS = {'ticket', 'open', 'labels', 'approval', 'approved_ready', 'fingerprint_now', 'table_complete',
                  'blockers', 'blockers_complete', 'holds', 'gates', 'live_builders', 'start_claims', 'open_prs',
                  'admission', 'complete', 'evidence'}
REVIEW_FIELDS = {'pr', 'ticket', 'open', 'draft', 'labels', 'approval', 'fingerprint_now', 'table_complete', 'head',
                 'head_now', 'branch', 'ci', 'builder', 'spans', 'closes', 'base', 'default_branch', 'subject',
                 'verdict', 'holds', 'gates', 'reviewer_available', 'admission', 'complete', 'evidence'}
NESTED = {'ci': {'head', 'state', 'required_complete'}, 'builder': {'record_branch', 'providers'},
          'evidence': {'evidence_class', 'source'}}


class Refusal(Exception):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def read_settings(text):
    """The four start tables of docs/agents/fleet.md, strictly; anything else refuses the pass."""
    tables = {}
    for key, name in TABLES.items():
        parts = re.split(r'^## ' + re.escape(name) + r'\n', text, flags=re.M)
        if len(parts) != 2:
            raise ValueError(f'fleet settings: one "## {name}" section required')
        section = parts[1].split('\n## ', 1)[0]
        flags = {}
        for setting, flag in (('Harness', 'provider'), ('Model', 'model'), ('Effort', 'reasoning-level')):
            rows = re.findall(r'^\| ' + setting + r' \| [^|\n]+ \| `--' + flag + r' ([A-Za-z0-9._-]+)` \|$',
                              section, re.M)
            if len(rows) != 1 or len(re.findall(r'^\| ' + setting + ' ', section, re.M)) != 1:
                raise ValueError(f'fleet settings: "{name}" needs one {setting} row')
            flags[flag] = rows[0]
        tables[key] = dict(provider=flags['provider'], model=flags['model'], effort=flags['reasoning-level'])
    # Fail closed on the family rule itself: each reviewer table names exactly the other family.
    if (tables['claude-code']['provider'] != 'codex' or tables['codex']['provider'] != 'claude-code'
            or {tables['builder']['provider'], tables['small']['provider']} - {'claude-code', 'codex'}):
        raise ValueError('fleet settings: builder/reviewer tables break the family rule')
    return tables


def require(condition, reason):
    if condition is not True:
        raise Refusal(reason)


def current_approval(c):
    effects._validate(effects.SCHEMA['$defs']['approval'], c['approval'])
    require(c['table_complete'] is True and c['fingerprint_now'] == c['approval']['fingerprint'],
            'approval not current')


def check_builder(c, tables):
    """Every frontier gate, in fleet-tick's order; returns the configured builder settings."""
    require(c['complete'], 'incomplete read')
    require(c['open'], 'ticket closed')
    current_approval(c)
    require(c['approved_ready'], 'not approved ready in the current plan')
    labels = c['labels']
    require(type(labels) is list and 'ready-for-agent' in labels and not NOT_READY & set(labels),
            'not ready, or held')
    require(c['holds'] == [] and c['gates'] == [], 'a hold or gate remains')
    require(c['blockers_complete'] and all(b['merged'] is True for b in c['blockers']),
            'a blocker merge is unverified')
    require(type(c['live_builders']) is int and c['live_builders'] == 0, 'a builder exists or is unknown')
    require(c['start_claims'] == [] and c['open_prs'] == [], 'an unsettled start claim or open pull request')
    require(c['admission'] == 'ok', 'start not admitted: ' + str(c['admission']))
    return tables['small' if SMALL & set(labels) else 'builder']


def check_review(c, tables):
    """Initial review of the exact current green head; returns the other-family reviewer settings."""
    require(c['complete'], 'incomplete read')
    require(c['open'] and c['draft'] is False, 'pull request closed or draft')
    current_approval(c)
    require(type(c['labels']) is list and 'held' not in c['labels'] and c['holds'] == [] and c['gates'] == [],
            'ticket held or gated')
    head, ci = c['head'], c['ci']
    require(type(head) is str and re.fullmatch('[0-9a-f]{40}', head) is not None and c['head_now'] == head,
            'head is not current')
    require(ci['head'] == head and ci['state'] == 'success' and ci['required_complete'] is True,
            'required CI is not green at the current head')
    require(c['closes'] == [c['ticket']], 'the pull request does not close exactly its ticket')
    require(type(c['default_branch']) is str and c['default_branch'] != '' and c['base'] == c['default_branch'],
            'the pull request does not target the default branch')
    require(type(c['subject']) is str and re.search(r'\bgreen\b', c['subject']) is not None,
            'the head is not a hand-back (no "green" in its subject)')
    require(c['verdict'] is None, 'the pull request already has a verdict')
    spans = c['spans']
    require(type(spans) is list and all(type(x) is dict and set(x) == {'head', 'given_up'} for x in spans),
            'reviewer history unreadable')
    # First review: no reviewer ever started. Fresh review: every one was given up.
    # A retained reviewer re-checks through OB6 (#1481), never a new start here.
    require(all(x['given_up'] is True for x in spans), 'a retained reviewer re-checks (OB6), no new start')
    builder = c['builder']
    require(builder['record_branch'] is not None and builder['record_branch'] == c['branch'],
            'builder start record does not match the head branch')
    providers = builder['providers']
    require(type(providers) is list and len(providers) == 1 and providers[0] in ('claude-code', 'codex'),
            'builder family unknown or conflicting')
    selected = tables[providers[0]]
    require(selected['provider'] != providers[0], 'configured reviewer is the builder family')
    require(c['reviewer_available'], 'selected reviewer unavailable: waits, never swapped')
    require(c['admission'] == 'ok', 'start not admitted: ' + str(c['admission']))
    return selected


def binding_digest(intent, settings, rule):
    """What a durable start intent binds besides its key: the start identity, settings and rule."""
    identity = {k: intent[k] for k in effects.KEY_FIELDS if k != 'sequence'}
    return digest(dict(identity=identity, settings=settings, rule=rule))


def claim_for(intent, generation, owner):
    """The operation claim for one intent under the pass's generation and owner."""
    claim = {k: intent[k] for k in ('schema', 'repository', 'spec', 'ticket', 'subject', 'operation_key',
                                     'created_at', 'approval', 'rule', 'evidence')}
    claim.update(kind='claim', id=f'claim-{intent["id"]}-g{generation}', scope='operation', generation=generation,
                 previous_generation=generation - 1, owner=owner, intent_id=intent['id'])
    claim['ref'] = effects.claim_ref(claim)
    return claim


def _misses(bench, limits):
    if bench is None:
        return []
    if limits is None:
        raise ValueError('stage misses need the shared limits reader result')
    if bench.get('schema') != BENCH or bench.get('authority') != 'none' or bench.get('settings') != limits:
        raise ValueError('stage-wait evidence is not the current bench under the current limits')
    return [w for w in bench['waits'] if w['result'] == 'missed' and w['end'] is None and w['key'] in bench['misses']
            and w['stage'] in ('builder_start', 'reviewer_start')]


def _miss_matches(wait, c, review):
    if review:
        return (wait['stage'] == 'reviewer_start' and wait['pull_request'] == c.get('pr')
                and wait['key'].split(':')[2] == c.get('head'))
    return wait['stage'] == 'builder_start' and wait['key'] == f'builder_start:t{c.get("ticket")}'


def _operation(c, review, action, subject, selected, world, history, planned, entry):
    """Build or reuse the one durable intent for an eligible start, with its claim and snapshot."""
    repo, spec, ticket = world['repository'], world['spec'], c['ticket']
    generation, owner = world['pass']['generation'], world['pass']['owner']
    head = c['head'] if review else None
    identity = dict(repository=repo, spec=spec, ticket=ticket, subject=subject, approval=c['approval'],
                    action=action, destination='reviewer' if review else 'builder',
                    assignment=f'review-p{c["pr"]}-{head[:12]}-r{len(c["spans"]) + 1}' if review
                    else f'builder-t{ticket}', prior_verdict=None, head=head)
    ticket_history = [r for r in history if (r['repository'], r['spec'], r['ticket']) == (repo, spec, ticket)]
    events = {}
    for r in ticket_history:
        events.setdefault(r['operation_key'], []).append(r)

    def settled(record):
        return any(e['kind'] == 'completion' and e['state'] in SETTLED for e in events.get(record['operation_key'], []))
    mine = [r for r in history + planned if r['kind'] == 'intent'
            and (r['repository'], r['spec'], r['ticket']) == (repo, spec, ticket)]
    same = sorted((r for r in mine if all(r[k] == v for k, v in identity.items())), key=lambda r: r['sequence'])
    bound = binding_digest(dict(identity, sequence=0), selected, world['rule'])
    latest = same[-1] if same else None
    if latest is not None and latest['rule'] == world['rule'] and latest['evidence'][0]['digest'] == bound:
        intent = latest
    elif latest is not None and not settled(latest):
        raise Refusal('start binding changed under an unresolved earlier intent')
    else:
        # First start, or the settled earlier intent's settings/rule changed: a new operation.
        sequence = 1 + max([r['sequence'] for r in mine if r['approval'] == c['approval']], default=0)
        evidence = dict(evidence_class=c['evidence']['evidence_class'], source=c['evidence']['source'],
                        digest=bound)
        intent = dict(identity, schema='openwiz.ops-dispatch.v1', kind='intent', created_at=world['pass']['now'],
                      id='pending', rule=world['rule'], evidence=[evidence], sequence=sequence)
        intent['operation_key'] = effects.operation_key(intent)
        # Repository-unique and deterministic: derived from the full operation identity.
        intent['id'] = f'{action.replace("_", "-")}-{intent["operation_key"][:32]}'
        intent = effects.read_record(json.dumps(intent))
        entry['new'] = not any(r == intent for r in planned)
    # An admitted claim with no later outcome may have started: that is uncertain, not absent.
    unsure = sorted(k for k, rs in events.items()
                    if any(r['kind'] == 'admission' and r['state'] == 'admitted' for r in rs)
                    and not any(r['kind'] in ('transport', 'completion') for r in rs))
    pool = {r['id']: r for r in mine + [intent] if r['approval'] == intent['approval']}
    open_seq = [r['sequence'] for r in pool.values() if not settled(r)]
    snapshot = dict(
        schema='openwiz.ops-dispatch.v1', kind='snapshot', repository=repo, spec=spec, ticket=ticket,
        approval=intent['approval'], head=intent['head'], generation=generation, owner=owner, complete=True,
        uncertain_keys=unsure, paused=False, revoked=False, holds=[], gates=[], cutoff='0' * 40,
        history_digest=digest(ticket_history), next_sequence=min(open_seq, default=intent['sequence']),
        recipient_verified=False, rule=world['rule'], consumers=[], cutoff_changes=[],
        material={k: digest([k, intent['operation_key']]) for k in (
            'intent_digest', 'evidence_digest', 'ownership_digest', 'purpose_digest', 'rule_digest')},
        intents=sorted(pool.values(), key=lambda r: r['sequence']),
        producer=dict(ticket=ticket, approval=intent['approval'], merge='0' * 40, delta_digest='0' * 64))
    claim = claim_for(intent, generation, owner)
    effects.read_record(json.dumps(claim))
    effects.read_record(json.dumps(snapshot))
    return dict(intent=intent, claim=claim, history=ticket_history, snapshot=snapshot)


def plan(world, fleet_text, effect_boundary, bench=None, limits=None):
    """One finite pass. Returns one entry per candidate, builders then reviews, in input order."""
    tables = read_settings(fleet_text)
    misses = _misses(bench, limits)
    generation, owner = world['pass']['generation'], world['pass']['owner']
    history = [effects.read_record(json.dumps(r, allow_nan=False)) for r in world['history']]
    planned = []
    entries, operations = [], []
    for action, candidates in (('builder_start', world['builders']), ('review_start', world['reviews'])):
        review = action == 'review_start'
        for c in candidates:
            shaped = (type(c) is dict and set(c) == (REVIEW_FIELDS if review else BUILDER_FIELDS)
                      and all(type(c[k]) is dict and set(c[k]) == v for k, v in NESTED.items() if k in c)
                      and type(c['ticket']) is int and (not review or type(c['pr']) is int))
            ticket = c['ticket'] if shaped else None
            number = (c['pr'] if review else ticket) if shaped else None
            subject = dict(kind='pull_request' if review else 'issue', number=number)
            missed = next((w['key'] for w in misses if _miss_matches(w, c, review)), None) if shaped else None
            entry = dict(action=action, subject=subject, ticket=ticket, decision='refused', reason=None,
                         settings=None, intent=None, new=False, claim=None, result=None, missed=missed)
            entries.append(entry)
            try:
                if not shaped:
                    raise Refusal('incomplete or malformed source')
                selected = (check_review if review else check_builder)(c, tables)
                operation = _operation(c, review, action, subject, selected, world, history, planned, entry)
            except Refusal as refusal:
                entry['reason'] = str(refusal)
                continue
            except (KeyError, TypeError, ValueError, AttributeError, IndexError):
                # Candidate-local: an unreadable fact or invalid record refuses this start alone.
                entry.update(reason='incomplete or malformed source', new=False)
                continue
            entry.update(decision='dispatch', settings=selected, intent=operation['intent'], claim=operation['claim'])
            if entry['new']:
                planned.append(operation['intent'])
            operations.append((entry, operation))
    view = dict(generations=world['generations'], operations=[op for _, op in operations],
                **{'pass': dict(generation=generation, owner=owner)})
    for (entry, _), result in zip(operations, records.ops_pass(view, effect_boundary, effects)):
        entry['result'] = result
    return entries


def _rank(values, share):
    return values[max(0, math.ceil(share * len(values)) - 1)] if values else None


def report(bench):
    """Eligible start delays with their denominators, from TL2's stage bench (authority none)."""
    if bench.get('schema') != BENCH or bench.get('authority') != 'none':
        raise ValueError('not a TL2 stage bench without authority')
    rows = {row['stage']: row for row in bench['stages']}
    out = dict(authority='none', read_at=bench['read_at'], settings=bench['settings'], provenance=PROVENANCE)
    for stage in ('builder_start', 'reviewer_start'):
        waits = [w for w in bench['waits'] if w['stage'] == stage]
        counts = {k: sum(w['result'] == k for w in waits) for k in rows[stage]['results']}
        if counts != rows[stage]['results'] or rows[stage]['intervals'] != len(waits):
            raise ValueError(f'{stage}: denominators disagree with the waits')
        # Only a start that happened has a dispatch time; an open miss stays in the denominators.
        ended = sorted(w['wait_minutes'] for w in waits if w['end'] is not None
                       and w['result'] in ('missed', 'not missed') and w['wait_minutes'] is not None)
        limit = rows[stage]['limit_minutes']
        out[stage] = dict(limit_minutes=limit, intervals=len(waits), results=counts, measured_ended=len(ended),
                          p50_minutes=_rank(ended, 0.5), p90_minutes=_rank(ended, 0.9),
                          excess_minutes=sum(max(0.0, m - limit) for m in ended),
                          excluded={k: counts[k] for k in ('gated', 'stale', 'unknown')})
    return out


def main():
    args = sys.argv[1:]
    try:
        if len(args) in (2, 4) and args[0] == 'pass' and (len(args) == 2 or args[2] == '--bench'):
            world = json.loads(Path(args[1]).read_text(), object_pairs_hook=records.unique)
            bench = limits = None
            if len(args) == 4:
                bench = json.loads(Path(args[3]).read_text(), object_pairs_hook=records.unique)
                limits = _load(HERE / 'carried/limits.py', 'factory_limits').read(
                    HERE / 'carried/limits.conf')

            def refuse(*_):
                raise RuntimeError('OB-A1: starts are disabled')
            out = plan(world, Path('docs/agents/fleet.md').read_text(), refuse, bench, limits)  # the consumer project's settings
        elif len(args) == 2 and args[0] == 'report':
            out = [report(json.loads(Path(args[1]).read_text(), object_pairs_hook=records.unique))]
        else:
            print('usage: ops-starts.py pass WORLD.json [--bench BENCH.json] | report BENCH.json', file=sys.stderr)
            return 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'ops-starts: refused: {error}', file=sys.stderr)
        return 2
    for item in out:
        print(json.dumps(item, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
