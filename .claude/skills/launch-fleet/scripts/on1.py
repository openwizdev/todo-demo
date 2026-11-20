"""Finite OB7 (#2112) ON1 evidence checks. No release executor, network client or effect.

The ops agent reads every source completely and supplies its values; this module
recomputes the record's digests from them and refuses on anything missing,
changed, racing or uncertain. Matching JSON is not authentication. Under OB-A1
the hold-release effect stays disabled even when all evidence is current, so
`effect_boundary` is never called. Sources are private helper inputs, not a new
wire contract; the durable record and result use ops-dispatch v1, decoded by the
pinned reference reader so schema semantics have one implementation.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('ops_protocol', ROOT / 'skills/launch-fleet/test/ops-protocol/protocol.py')
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)
spec = importlib.util.spec_from_file_location('grants', Path(__file__).resolve().parent / 'grants.py')
grants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grants)
BINDING = ('repository', 'spec', 'ticket', 'approval')
# Exact source types: a string "false" must never pass as a checked flag (R5).
OPTIONAL_STR = (str, type(None))
TYPES = {
    'producer': dict(ticket=int, approval=dict, merge=str, merged=bool, delta=str),
    'cutoff': dict(start=str, end=str, complete=bool, changes=list),
    'hold': dict(comment=int, kind=str, complete=bool, history=list),
    'revision': dict(comment=int, created_at=int, approval=dict, fingerprint_now=str,
                     table_complete=bool, relies_ok=bool, links_ok=bool),
    'labels': dict(held=bool, ready=bool, events=list),
    'consumer': dict(ticket=int, approval=dict, scope=str, paths=list, grants=list, relies=list, links=list),
    'change': dict(commit=str, path=str, previous_path=OPTIONAL_STR, producer_ticket=int, consumer_tickets=list),
    'hold history': dict(id=int, kind=str, created_at=int),
    'label event': dict(name=str, action=str, created_at=int),
    'evidence': dict(evidence_class=str, source=str, value=str),
    # The exact inputs of the existing OB2 grant check, per grant (R2).
    'grant': dict(grant=dict, envelope=dict, intent=dict, snapshot=dict, sources=dict, assessment=dict,
                  changes=list, history=list),
}
SOURCES = dict(producer=dict, consumers=list, cutoff=dict, hold=dict, revision=dict, rule=str, labels=dict,
               claims=list, evidence=list)


class Refusal(Exception):
    def __init__(self, state, reason, detail):
        super().__init__(detail)
        self.state, self.reason, self.detail = state, reason, detail


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def checked(value, kind):
    record = protocol.read_record(json.dumps(value, allow_nan=False))
    if record['kind'] != kind:
        raise ValueError('wrong record kind')
    return record


def shape(value, what, types=None):
    types = TYPES[what] if types is None else types
    if type(value) is not dict or set(value) != set(types):
        raise ValueError(f'incomplete {what} source')
    for key, kind in types.items():
        if type(value[key]) not in (kind if type(kind) is tuple else (kind,)):
            raise ValueError(f'malformed {what} source: {key}')
    return value


def listed(values, what, kind=None):
    for value in values:
        if kind is None:
            shape(value, what)
        elif type(value) is not kind:
            raise ValueError(f'malformed {what} source')
    return values


def deny(state, reason, detail):
    raise Refusal(state, reason, detail)


def require(condition, detail, state='refused', reason='stale_binding'):
    if not condition:
        deny(state, reason, detail)


def read_sources(sources):
    shape(sources, 'ON1', SOURCES)
    for what in ('producer', 'cutoff', 'hold', 'revision', 'labels'):
        shape(sources[what], what)
    for consumer in listed(sources['consumers'], 'consumer'):
        for what, kind in (('paths', str), ('relies', str), ('links', str)):
            listed(consumer[what], what, kind)
        listed(consumer['grants'], 'grant')
    for change in listed(sources['cutoff']['changes'], 'change'):
        listed(change['consumer_tickets'], 'change consumer', int)
    listed(sources['hold']['history'], 'hold history')
    listed(sources['labels']['events'], 'label event')
    listed(sources['claims'], 'claim', str)
    listed(sources['evidence'], 'evidence')
    # R5: 3.0 == 3 and True == 1 in Python, so every source approval must pass
    # the contract's strict approval shape before any comparison uses it.
    # That includes each grant assessment's approval, which grants.py compares too;
    # an assessment without one is still refused there as incomplete.
    assessments = [bundle.get('assessment') for consumer in sources['consumers']
                   for bundle in consumer['grants'] if type(bundle) is dict]
    for value in [sources['producer']['approval'], sources['revision']['approval']] + [
            consumer['approval'] for consumer in sources['consumers']] + [
            a['approval'] for a in assessments if type(a) is dict and 'approval' in a]:
        protocol._validate(protocol._node('#/$defs/approval'), value)
    return sources


def bound_intent(record, snapshot):
    """The one durable intent this operation belongs to, resolved before any check (R9)."""
    intents = [i for i in snapshot['intents'] if i['operation_key'] == record['operation_key']]
    if len(intents) != 1:
        raise ValueError('no single durable release intent for this operation')
    return checked(intents[0], 'intent')


def grant_valid(bundle, consumer, record, current):
    """The existing OB2 grant check: binding, rule, recomputed material and lifecycle."""
    grant, snap = bundle['grant'], bundle['snapshot']
    return (type(grant) is dict and grant.get('ticket') == consumer['ticket'] == snap.get('ticket')
            and all(grant.get(k) == snap.get(k) == record[k] for k in ('repository', 'spec'))
            and grant.get('approval') == current
            and grants.check_grant(**copy.deepcopy(bundle))['purpose_current'])


def assess(record, snapshot, sources, intent):
    """Raise Refusal for the first failing check, in denial priority order."""
    labels, hold, revision = sources['labels'], sources['hold'], sources['revision']
    current = snapshot['approval']
    covered = [h for h in hold['history'] if h['id'] == hold['comment']]

    # 1. Uncertainty first: nothing later can lower it.
    require(not snapshot['uncertain_keys'], 'an earlier operation on this ticket is unresolved',
            'reconcile', 'uncertain_outcome')
    require(labels['held'] and not labels['ready'],
            'partial or unexplained labels: reconcile before any other effect', 'reconcile', 'uncertain_outcome')
    # A label event tied with the hold is not proved older than it (R6).
    require(all(e['created_at'] > revision['created_at'] for e in labels['events']
                if e['created_at'] >= max([h['created_at'] for h in covered] or [0])),
            'a label changed at or after the hold but before the revision record', 'reconcile', 'uncertain_outcome')
    require(record['verification']['after_digest'] is None and record['verification']['labels_digest'] is None,
            'the record claims read-backs of a release no enabled effect could make', 'reconcile', 'uncertain_outcome')

    # 2. Complete reads only; an unread page never proves absence.
    require(snapshot['complete'], 'the snapshot read is incomplete', reason='incomplete_read')
    require(sources['cutoff']['complete'] and record['cutoff']['complete'] and record['cutoff']['inclusive'],
            'the inclusive cutoff inventory is incomplete', reason='incomplete_read')
    require(hold['complete'] and record['verification']['history_complete'],
            'the hold history is incomplete', reason='incomplete_read')

    # 3. Every other gate, newer hold and competing claim keeps the hold.
    gates = 'paused_or_revoked'
    require(not snapshot['paused'] and not snapshot['revoked'], 'paused or revoked', reason=gates)
    require(not record['other_gates'] and not snapshot['gates'], 'another gate remains', reason=gates)
    require(not record['competing_claims'] and not sources['claims'], 'a competing release claim is unresolved',
            reason=gates)
    require(snapshot['holds'] == [record['hold']['comment']], 'another hold is active', reason=gates)
    newest = max(hold['history'], key=lambda h: (h['created_at'], h['id']), default=None)
    require(newest is not None and newest['id'] == hold['comment'], 'a newer hold is in the full history',
            reason=gates)

    # 4. Binding: one current plan, one rule, one durable release intent.
    require(all(record[k] == snapshot[k] for k in BINDING)
            and record['subject'] == {'kind': 'issue', 'number': snapshot['ticket']}, 'stale record binding')
    require(record['rule']['name'] == 'on1' and record['rule'] == snapshot['rule']
            and record['rule']['revision'] == digest(sources['rule']), 'not the current ON1 rule')
    require(intent['action'] == 'hold_release' and all(intent[k] == record[k] for k in BINDING)
            and intent['subject'] == record['subject'] and intent['rule'] == record['rule'],
            'the release intent is bound elsewhere')

    # 5. The complete unchanged revision record precedes any label change.
    require(record['revision_record'] == revision['comment'] and revision['approval'] == current
            and revision['fingerprint_now'] == current['fingerprint'],
            'the plan is not the approved revision now')
    require(revision['table_complete'] and revision['relies_ok'] and revision['links_ok'],
            'the revision table, Relies on or link checks did not pass')

    # 6. Producer: approved ticket, verified merge, actual delta.
    producer = sources['producer']
    require(producer['merged'] and producer['delta'], 'the producer merge is unverified')
    require(record['producer'] == snapshot['producer'] == dict(
        ticket=producer['ticket'], approval=producer['approval'], merge=producer['merge'],
        delta_digest=digest(producer['delta'])), 'the producer or its actual delta changed')

    # 7. Consumers: current approval, unchanged scope/paths, valid grants.
    expected = []
    tickets = [c['ticket'] for c in sources['consumers']]
    # The released ticket is one of the evidenced consumers, exactly once (R8).
    require(len(set(tickets)) == len(tickets) and tickets.count(snapshot['ticket']) == 1,
            'the released ticket is not exactly one evidenced consumer')
    for consumer in sources['consumers']:
        require(consumer['approval'] == current, f"consumer #{consumer['ticket']} is not on the current approval")
        ids = []
        for bundle in consumer['grants']:
            require(grant_valid(bundle, consumer, record, current),
                    f"a grant is not valid for consumer #{consumer['ticket']}")
            ids.append(bundle['grant']['grant_id'])
        expected.append(dict(ticket=consumer['ticket'], approval=consumer['approval'],
                             scope_digest=digest(consumer['scope']), paths_digest=digest(consumer['paths']),
                             grants=ids, relies_digest=digest(consumer['relies']),
                             links_digest=digest(consumer['links'])))
    require(record['consumers'] == snapshot['consumers'] == expected, 'a consumer changed since the assessment')

    # 8. The whole inclusive cutoff, renames and deletions included.
    cutoff, changes = sources['cutoff'], sources['cutoff']['changes']
    require(record['cutoff']['start'] == cutoff['start'] and record['cutoff']['end'] == cutoff['end']
            == snapshot['cutoff'], 'the cutoff moved')
    require(record['cutoff']['changes'] == changes == snapshot['cutoff_changes'],
            'a declared-contract change through the cutoff is unassessed')
    tickets = set(tickets)
    require(any(c['commit'] == producer['merge'] for c in changes)
            and all(c['producer_ticket'] == producer['ticket'] and set(c['consumer_tickets']) <= tickets
                    for c in changes)
            and tickets <= {t for c in changes for t in c['consumer_tickets']},
            'a change through the cutoff has another producer or consumer')

    # 9. The exact covered contract hold and its full history.
    ids = [h['id'] for h in hold['history']]
    require(hold['comment'] == record['hold']['comment'] and hold['kind'] == 'contract'
            and len(set(ids)) == len(ids) and len(covered) == 1 and covered[0]['kind'] == 'contract'
            and record['hold']['history_digest'] == snapshot['history_digest'] == digest(hold['history']),
            'not the exact covered contract hold')

    # 10. Evidence and the pre-effect digest are recomputed from what was read (R4).
    try:
        grants.evidence_matches(record, sources)
    except ValueError as error:
        deny('refused', 'stale_binding', str(error))
    require(record['verification']['before_digest'] == pre_effect(sources),
            'the pre-effect evidence digest does not match the sources read')


def pre_effect(sources):
    """The digest of every source read before an effect, evidence included."""
    return digest(sources)


def check_on1(record, snapshot, sources, effect_boundary):
    """One finite pass: assess, record the result and end. Never calls effect_boundary.

    Malformed records or sources raise ValueError. Otherwise the result is a
    contract `result`: refused/reconcile with its reason, or disabled because
    OB-A1 keeps the release effect off even for complete, current evidence.
    """
    record, snapshot = checked(record, 'on1'), checked(snapshot, 'snapshot')
    sources = read_sources(copy.deepcopy(sources))
    intent = bound_intent(record, snapshot)
    try:
        assess(record, snapshot, sources, intent)
        state, reason, detail, current = 'disabled', 'unfenced_effect', 'evidence current; release disabled (OB-A1)', True
    except Refusal as refusal:
        state, reason, detail, current = refusal.state, refusal.reason, refusal.detail, False
    except (KeyError, TypeError) as error:
        raise ValueError('incomplete ON1 source') from error
    result = dict(schema='openwiz.ops-dispatch.v1', kind='result', operation_key=record['operation_key'],
                  intent_id=intent['id'], state=state, reason=reason, next='end', effects=[])
    return dict(result=checked(result, 'result'), evidence_current=current, detail=detail)
