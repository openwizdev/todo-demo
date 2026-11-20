"""TL3 (#2338): recover an evidenced missed stage limit with one recorded fix helper.

One finite pass. The ops agent supplies, for each open miss in TL2's stage
bench (`closedwiz.journey.stage-bench.v1` waits), the pull request facts it read
completely from GitHub and the operation records it read back. This module:

1. selects at most one fix helper for the miss (`select`), or a refusal;
2. proposes the ops-dispatch v1 intent to record **before** any dispatch, or
   reuses the one already recorded for the same miss;
3. sends a recorded, claimed intent through #1456's `records.ops_pass`, which
   sends it through OB3's `resume`: the effect boundary is never called, so
   under OB-A1 an eligible helper start ends `disabled`;
4. reports the outcome; only a `complete` result, which needs a verified
   endpoint completion, ever counts as a recovery (`counted`).

Builder and reviewer starts (#1480), question routing (#1481) and merging
(#2189) stay with their owners: a miss of those stages selects no helper. A CI
or conflict helper recovers an already missed named stage; red CI or a
conflict alone is no sixth limit. There is no network or process client here,
no timer, collector or dispatcher. See ../test/limit-recovery/README.md.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True  # never leave caches in an installed skill
HERE = Path(__file__).resolve().parent


def _load(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load('ops_effects', 'effects.py')
records = _load('ops_records', 'records.py')

SHA = '[0-9a-f]{40}'
# TL2's key forms (journey-contract.md section 10) for the PR stages TL3 reads.
KEYS = {
    'fix_after_changes': re.compile(rf'fix_after_changes:p([1-9][0-9]*):({SHA}):c([1-9][0-9]*)'),
    'merge': re.compile(rf'merge:p([1-9][0-9]*):({SHA}):c([1-9][0-9]*):(?:[0-9TZ:-]+|-)'),
}
# Stages whose recovery already has an owner: TL3 never duplicates it.
OWNERS = {'builder_start': '#1480', 'reviewer_start': '#1480', 'builder_question_answer': '#1481',
          'merge': '#2189'}
STAGES = set(KEYS) | set(OWNERS)
ROLES = ('ci-fix', 'findings-fix', 'conflict-fix')
# The fleet's start gates (fleet-tick frontier rule): any of these holds the work.
HOLDING = {'held', 'needs-info', 'needs-triage', 'ready-for-human', 'wontfix'}
MISS = dict(key=str, stage=str, tickets=list, pull_request=(int, type(None)), wait_minutes=(int, float, type(None)),
            wait_range_minutes=(list, type(None)), limit_minutes=int, result=str, start=(str, type(None)),
            end=(str, type(None)), support=list, folded=int, gaps=list)
FACTS = dict(complete=bool, ticket=int, pull_request=int, pr_state=str, head=str, ci=str,
             conflict=(bool, type(None)),
             owner=str, family=(str, type(None)), labels=list)
ENUMS = dict(pr_state={'open', 'closed', 'merged'}, ci={'success', 'failure', 'pending', 'unknown'},
             owner={'idle', 'active', 'unknown'})
CASE = dict(miss=dict, facts=dict, rule=dict, source=str, created_at=int, intent_id=str, snapshot=dict,
            claim=(dict, type(None)), history=list)
# The helper starts on the builder's branch as builder-role work. ops-dispatch v1
# has no dedicated helper action; this is the closest existing one, and its
# effect stays disabled (OB-A1). A dedicated kind would be Jake's decision.
ACTION, DESTINATION = 'builder_start', 'builder'
HISTORY = {'intent', 'admission', 'transport', 'ack', 'completion'}
# The states OB3's resume keeps unresolved: nothing later lowers them.
UNSETTLED = {'transport': {'accepted', 'uncertain'}, 'completion': {'uncertain', 'completed', 'reconciled_not_executed'},
             'admission': {'uncertain', 'reconcile'}}


def _shape(value, types, what):
    if type(value) is not dict or set(value) != set(types):
        raise ValueError(f'incomplete {what}')
    for key, kind in types.items():
        if type(value[key]) not in (kind if type(kind) is tuple else (kind,)):
            raise ValueError(f'malformed {what}: {key}')
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def _read(miss, facts):
    _shape(miss, MISS, 'miss')
    _shape(facts, FACTS, 'facts')
    if miss['stage'] not in STAGES or any(facts[k] not in v for k, v in ENUMS.items()):
        raise ValueError('unknown stage or fact value')
    if facts['family'] not in (None, 'claude', 'gpt') or re.fullmatch(SHA, facts['head']) is None:
        raise ValueError('malformed facts')
    if (not all(type(item) is str for item in facts['labels'] + miss['gaps'] + miss['support'])
            or not all(type(t) is int for t in miss['tickets'])):
        raise ValueError('malformed labels or tickets')
    parsed = KEYS[miss['stage']].fullmatch(miss['key']) if miss['stage'] in KEYS else None
    if miss['stage'] in KEYS and (parsed is None or int(parsed[1]) != miss['pull_request']):
        raise ValueError('miss key does not match its stage evidence')
    return parsed


def select(miss, facts):
    """The one helper an open, evidenced miss calls for, or why none. Pure."""
    parsed = _read(miss, facts)

    def no(reason, detail):
        return dict(role=None, reason=reason, detail=detail)

    def helper(role, detail):
        return dict(role=role, reason='eligible', detail=detail)

    stage = miss['stage']
    if miss['result'] != 'missed':
        return no('not_missed', f"the {stage} wait is {miss['result']}, not a measured miss")
    if miss['end'] is not None:
        return no('already_ended', 'the stage ended after its goal; there is nothing to recover')
    if miss['gaps']:
        return no('unknown_history', 'the miss has source gaps: ' + ', '.join(miss['gaps']))
    if not facts['complete']:
        return no('incomplete_read', 'a source page was not read; absence is never inferred')
    if stage in OWNERS and not (stage == 'merge' and facts['conflict'] is not False):
        return no('existing_owner', f'{stage} recovery belongs to {OWNERS[stage]}')
    if facts['pull_request'] != miss['pull_request'] or facts['ticket'] not in miss['tickets']:
        return no('stale_binding', 'the facts are for another pull request or ticket')
    if facts['pr_state'] != 'open':
        return no('not_open', f"the pull request is {facts['pr_state']}")
    if HOLDING & set(facts['labels']) or 'ready-for-agent' not in facts['labels']:
        return no('held', 'the ticket is held or waiting on a question')
    if facts['owner'] != 'idle':
        reason = 'active_owner' if facts['owner'] == 'active' else 'unknown_history'
        return no(reason, f"the retained builder is {facts['owner']} since the miss; no competing writer")
    if facts['family'] is None:
        return no('unknown_history', "the builder's family is unknown, so no helper model can keep it")
    head = parsed[2]
    if stage == 'merge':
        if facts['head'] != head:
            return no('stale_head', 'the approved head is no longer current')
        if facts['conflict'] is None:
            return no('unknown_history', 'whether the approved head conflicts with main is unknown')
        return helper('conflict-fix', 'the approved head conflicts with main')
    if facts['head'] == head:
        return helper('findings-fix', 'no push since the CHANGES verdict')
    if facts['ci'] == 'failure':
        return helper('ci-fix', 'the newer head is red and the builder is idle')
    if facts['conflict']:
        return helper('conflict-fix', 'the newer head conflicts with main')
    if facts['ci'] == 'unknown' or facts['conflict'] is None:
        return no('unknown_history', "the newer head's CI or conflict state is unknown")
    return no('no_cause', 'the newer head is not red and does not conflict; no CI or conflict timer exists')


def propose(selection, case):
    """The intent to record before any dispatch. The same miss always names the same work."""
    miss, facts, snapshot = case['miss'], case['facts'], case['snapshot']
    parsed = KEYS[miss['stage']].fullmatch(miss['key'])
    intent = dict(
        schema='openwiz.ops-dispatch.v1', kind='intent', id=case['intent_id'],
        repository=snapshot['repository'], spec=snapshot['spec'], ticket=snapshot['ticket'],
        subject=dict(kind='pull_request', number=miss['pull_request']), operation_key='0' * 64,
        created_at=case['created_at'], approval=copy.deepcopy(snapshot['approval']), rule=copy.deepcopy(case['rule']),
        evidence=[dict(evidence_class='fixture' if case['source'].startswith('fixture:') else 'observation',
                       source=case['source'], digest=digest(dict(miss=miss, facts=facts)))],
        action=ACTION, destination=DESTINATION,
        assignment=f"{selection['role']}-{digest(miss['key'])[:16]}",
        prior_verdict=int(parsed[3]) if selection['role'] == 'findings-fix' else None,
        head=facts['head'], sequence=snapshot['next_sequence'])
    intent['operation_key'] = effects.operation_key(intent)
    return effects.read_record(json.dumps(intent))


def _helper(intent):
    return (intent['action'] == ACTION and intent['destination'] == DESTINATION
            and type(intent['assignment']) is str and intent['assignment'].startswith(tuple(r + '-' for r in ROLES)))


def _identities(intent, history):
    """OB3's identity rule: each (repository, id) once, and never reused by another record."""
    ids = [(r['repository'], r['id']) for r in history]
    return len(ids) == len(set(ids)) and all(
        r == intent for r in history if (r['repository'], r['id']) == (intent['repository'], intent['id']))


def _belongs(record, intent):
    """OB3's binding rule for a same-key record: this plan, this subject and this intent."""
    return (all(record[k] == intent[k] for k in ('repository', 'spec', 'ticket', 'approval', 'subject'))
            and (record == intent if record['kind'] == 'intent' else record.get('intent_id', intent['id']) == intent['id']))


def recover(view, cases, effect_boundary):
    """One finite pass over open misses. Returns one record per case, in order; never executes.

    view: {"pass": {generation, owner}, "generations": [admitted generation claims]}.
    Each case: {miss, facts, rule, source, created_at, intent_id, snapshot, claim, history}.
    `record_intent` asks the caller to record and read back the proposed intent;
    `admit_claim` to admit its operation claim through OB3. Neither dispatches.
    """
    out, reserved, operations = [], {}, []
    for case in cases:
        _shape(case, CASE, 'case')
        rule, snapshot = case['rule'], effects.read_record(json.dumps(case['snapshot']))
        if rule.get('name') != 'dispatch' or snapshot['kind'] != 'snapshot':
            raise ValueError('TL3 intents are bound to the current dispatch rule and a snapshot')
        history = [effects.read_record(json.dumps(r)) for r in case['history']]
        if any(r['kind'] not in HISTORY for r in history):
            raise ValueError('not an operation history record')
        selection = select(case['miss'], case['facts'])
        base = dict(role=selection['role'], detail=selection['detail'], intent=None, result=None)

        def end(state, reason, detail=None, intent=None):
            return dict(base, state=state, reason=reason, intent=intent, detail=detail or base['detail'])
        if selection['role'] is None:
            out.append(end('refused', selection['reason']))
            continue
        # R1: the snapshot's ticket, and so its approval, must be the miss's own.
        if snapshot['ticket'] != case['facts']['ticket']:
            out.append(end('refused', 'stale_binding', 'the snapshot is for another ticket'))
            continue
        fresh = propose(selection, case)
        same = ('subject', 'action', 'destination', 'assignment', 'head', 'prior_verdict')
        recorded = [i for i in snapshot['intents'] if all(i[k] == fresh[k] for k in same)
                    and all(i[k] == snapshot[k] for k in ('repository', 'spec', 'ticket', 'approval'))]
        others = [i for i in snapshot['intents'] if _helper(i) and i['subject'] == fresh['subject']
                  and i['head'] == fresh['head'] and i['assignment'] != fresh['assignment']]
        if len(recorded) > 1:
            raise ValueError('two recorded intents for one miss')
        intent = recorded[0] if recorded else fresh
        # R2: one helper per pull request head across this pass, recorded or only proposed.
        slot = (fresh['repository'], fresh['subject']['number'], fresh['head'])
        if others or reserved.get(slot, intent['operation_key']) != intent['operation_key']:
            out.append(end('refused', 'another_helper', 'another recovery helper is recorded or proposed at this head'))
            continue
        again = slot in reserved
        reserved[slot] = intent['operation_key']
        if not recorded:
            out.append(end('duplicate' if again else 'record_intent', 'eligible', intent=fresh))
            continue
        # R4: reuse only under the current dispatch rule; older authority goes back for reassessment.
        if intent['rule'] != rule:
            out.append(end('refused', 'stale_binding', 'the intent was recorded under another dispatch rule'))
            continue
        if case['claim'] is None:
            # R3: OB3's resume order: unique immutable identities, then uncertainty
            # first, then every same-key record must belong to this intent. A lost
            # claim read-back is never a second admission.
            mine = [r for r in history if r['operation_key'] == intent['operation_key']]
            if not _identities(intent, history):
                out.append(end('refused', 'incomplete_read', 'the history has an ambiguous record identity', intent))
            elif snapshot['uncertain_keys'] or any(
                    all(r[k] == intent[k] for k in ('repository', 'spec', 'ticket'))
                    and r.get('state') in UNSETTLED.get(r['kind'], ()) for r in history):
                out.append(end('reconcile', 'uncertain_outcome', 'an operation on this ticket is unresolved', intent))
            elif not all(_belongs(r, intent) for r in mine):
                out.append(end('refused', 'stale_binding', 'a history record of this operation is bound elsewhere', intent))
            elif any(r['kind'] == 'admission' and r['state'] in ('admitted', 'duplicate') for r in mine):
                out.append(end('refused', 'incomplete_read', 'an admitted claim was not read back', intent))
            else:
                out.append(end('admit_claim', 'eligible', intent=intent))
            continue
        out.append(end(None, None, intent=intent))
        operations.append((len(out) - 1, dict(intent=intent, claim=case['claim'], history=case['history'],
                                              snapshot=snapshot)))
    if operations:
        results = records.ops_pass(dict(view, operations=[op for _, op in operations]), effect_boundary, effects)
        for (index, _), result in zip(operations, results):
            out[index].update(state=result['state'], reason=result['reason'], result=result)
    return out


def counted(record):
    """A recovery counts only on a complete result; refusals, disabled and uncertain never do."""
    result = record.get('result')
    return record.get('state') == 'complete' and type(result) is dict and result.get('state') == 'complete'


def main():
    if sys.argv[1:] != ['pass']:
        print('usage: limit-recovery.py pass < {"view": ..., "cases": [...]}', file=sys.stderr)
        return 2

    def refuse(*_):
        raise RuntimeError('OB-A1: effects are disabled')
    try:
        value = json.loads(sys.stdin.read(), object_pairs_hook=records.unique)
        for item in recover(value['view'], value['cases'], refuse):
            print(json.dumps(dict(item, counted=counted(item)), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'limit-recovery: pass refused: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
