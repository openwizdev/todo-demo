"""TL4 (#2339): retire and replace a stuck owner after two ticket misses.

One finite pass. The ops agent reads every source completely and supplies its
values: the TL2 stage bench (`journey.py bench --stage-waits`), the private
reconciliation reads below, and the ops-dispatch v1 snapshot, intent, claim and
history. This module counts the owner's distinct evidenced misses, checks
that a single branch writer can be proved, and selects at most one recorded
replacement on the incumbent's existing branch. It has no network/process
client, enable switch or executable effect path: retirement and start stay
disabled under OB-A1, so `effect_boundary` is never called, and every
unavailable boundary is returned as a gap for Jake. P5 remains Unverified.
See ../test/limit-replacement/README.md.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load('ops_effects', HERE / 'effects.py')
limits = _load('factory_limits', HERE / 'carried/limits.py')
LIMITS = HERE / 'carried/limits.conf'
SCHEMA = 'closedwiz.limit-replacement.v1'
BENCH = 'closedwiz.journey.stage-bench.v1'
# The stages whose miss is the owner's own wait. builder_start comes before
# any owner; reviewer_start/merge are dispatcher/reviewer waits;
# builder_question_answer is the orchestrator's (ticket question Q2).
OWNER_STAGES = ('fix_after_changes',)
WAIT_KEYS = {'key', 'stage', 'tickets', 'pull_request', 'wait_minutes', 'wait_range_minutes', 'limit_minutes',
             'result', 'start', 'end', 'support', 'folded', 'gaps'}
RESULTS = ('missed', 'not missed', 'pending', 'unknown', 'gated', 'stale')
# An earlier start on this ticket is settled only when its effect was never
# attempted. A purported completion or non-execution needs an endpoint lookup
# that does not exist yet (#2244), so it stays uncertain.
SETTLED = ('disabled', 'refused', 'superseded')
UNSETTLED = {'transport': ('accepted', 'uncertain'),
             'completion': ('uncertain', 'completed', 'reconciled_not_executed'),
             'admission': ('uncertain', 'reconcile')}
GAPS = (
    'retirement: ops-dispatch v1 has no retirement action and no fenced archive boundary',
    'start: builder_start is an unfenced effect and stays disabled under OB-A1',
    'lookup: no authenticated spawn or retirement outcome lookup (#2244 discovery unstarted)',
    'fencing: no generation fence at the CloudRoom boundary; P5 Unverified',
)
HEX40 = re.compile('[0-9a-f]{40}')
ALIAS = re.compile('[a-z][a-z0-9-]{0,79}')
OPTIONAL_ALIAS = (str, type(None))
SOURCES = dict(complete=bool, ticket=int, overload=str, recorded_misses=list, incumbent=dict, reviewer=dict)
INCUMBENT = dict(assignment=str, family=str, branch=str, head=str, activity=str, worktree=str)
REVIEWER = dict(assignment=OPTIONAL_ALIAS, family_conflicts=list, correction_rounds=dict)
ENUMS = {'overload': ('clear', 'paused', 'unknown'), 'family': ('claude', 'gpt', 'unknown'),
         'activity': ('stopped', 'running', 'unknown'), 'worktree': ('clean', 'handed_off', 'dirty', 'unknown')}


class Refusal(Exception):
    def __init__(self, state, reason, detail):
        super().__init__(detail)
        self.state, self.reason, self.detail = state, reason, detail


def require(condition, detail, state='refused', reason='stale_binding'):
    if not condition:
        raise Refusal(state, reason, detail)


def digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def shape(value, what, types):
    if type(value) is not dict or set(value) != set(types):
        raise ValueError(f'incomplete {what} source')
    for key, kind in types.items():
        if type(value[key]) not in (kind if type(kind) is tuple else (kind,)):
            raise ValueError(f'malformed {what} source: {key}')
    return value


def is_miss_key(key):
    return (type(key) is str and key.split(':', 1)[0] in OWNER_STAGES
            and re.fullmatch(r'[a-z_]+(:[A-Za-z0-9_-]+)+', key) is not None)


def read_sources(sources):
    shape(sources, 'replacement', SOURCES)
    incumbent = shape(sources['incumbent'], 'incumbent', INCUMBENT)
    reviewer = shape(sources['reviewer'], 'reviewer', REVIEWER)
    if sources['ticket'] < 1 or sources['overload'] not in ENUMS['overload']:
        raise ValueError('malformed replacement source')
    for key in ('family', 'activity', 'worktree'):
        if incumbent[key] not in ENUMS[key]:
            raise ValueError(f'malformed incumbent source: {key}')
    if (not ALIAS.fullmatch(incumbent['assignment']) or not HEX40.fullmatch(incumbent['head'])
            or not re.fullmatch(r'[A-Za-z0-9._/-]{1,200}', incumbent['branch'])):
        raise ValueError('malformed incumbent source')
    if reviewer['assignment'] is not None and not ALIAS.fullmatch(reviewer['assignment']):
        raise ValueError('malformed reviewer source: assignment')
    if any(f not in ENUMS['family'] for f in reviewer['family_conflicts']):
        raise ValueError('malformed reviewer source: family_conflicts')
    if any(type(k) is not str or type(v) is not int or v < 0 for k, v in reviewer['correction_rounds'].items()):
        raise ValueError('malformed reviewer source: correction_rounds')
    if not all(is_miss_key(key) for key in sources['recorded_misses']):
        raise ValueError('malformed recorded miss')
    return sources


def read_bench(bench):
    """The TL2 stage-bench output, checked for internal agreement. A miss is a measured fact only."""
    shape(bench, 'bench', dict(schema=str, settings=dict, read_at=str, authority=str, stages=list,
                               waits=list, misses=list, sources=dict))
    if bench['schema'] != BENCH or bench['authority'] != 'none':
        raise ValueError('not a stage-bench v1 measurement')
    settings = shape(bench['settings'], 'settings', dict(schema=str, minutes=dict))
    minutes = shape(settings['minutes'], 'settings minutes', {stage: int for stage in limits.STAGES})
    keys = []
    for wait in bench['waits']:
        if type(wait) is not dict or set(wait) != WAIT_KEYS:
            raise ValueError('incomplete bench wait')
        if (type(wait['key']) is not str or wait['stage'] not in limits.STAGES
                or not wait['key'].startswith(wait['stage'] + ':') or wait['result'] not in RESULTS
                or type(wait['tickets']) is not list or any(type(t) is not int for t in wait['tickets'])
                or type(wait['limit_minutes']) is not int or wait['limit_minutes'] != minutes[wait['stage']]):
            raise ValueError('malformed bench wait')
        keys.append(wait['key'])
    if len(keys) != len(set(keys)):
        raise ValueError('a bench interval is repeated')
    if (any(type(k) is not str for k in bench['misses']) or len(set(bench['misses'])) != len(bench['misses'])
            or set(bench['misses']) != {w['key'] for w in bench['waits'] if w['result'] == 'missed'}):
        raise ValueError('bench misses disagree with its waits')
    return bench


def owner_misses(bench, sources):
    """Distinct owner-stage misses on this ticket: the bench's, plus every earlier recorded one."""
    measured = {w['key'] for w in bench['waits'] if w['result'] == 'missed'
                and w['stage'] in OWNER_STAGES and sources['ticket'] in w['tickets']}
    return sorted(measured | set(sources['recorded_misses']))


def binding(sources):
    """What a replacement intent's evidence digest binds: this ticket, branch, head and incumbent."""
    incumbent = sources['incumbent']
    return digest(dict(ticket=sources['ticket'], branch=incumbent['branch'], head=incumbent['head'],
                       incumbent=incumbent['assignment']))


def record(value, kind):
    try:
        result = effects.read_record(json.dumps(value, allow_nan=False))
    except (TypeError, OverflowError) as error:
        raise ValueError('invalid record') from error
    if result['kind'] != kind:
        raise ValueError(f'expected a {kind} record')
    return result


def is_start(r, ticket):
    return r['kind'] == 'intent' and r['ticket'] == ticket and r['action'] == 'builder_start'


def selects(r, sources):
    """A recorded start intent for this same replacement: ticket, branch, head and incumbent."""
    return is_start(r, sources['ticket']) and [e['digest'] for e in r['evidence']] == [binding(sources)]


def assess(bench, sources, snapshot, history, current_limits, misses, intent):
    """Raise Refusal for the first failing check, in denial priority order."""
    ticket, incumbent = sources['ticket'], sources['incumbent']
    same = [r for r in history if (r['repository'], r['ticket']) == (snapshot['repository'], ticket)]

    # 1. Uncertainty first: nothing later can lower it.
    uncertain = ('reconcile', 'uncertain_outcome')
    require(not snapshot['uncertain_keys'], 'an earlier operation on this ticket is unresolved', *uncertain)
    require(not any(r.get('state') in UNSETTLED.get(r['kind'], ()) for r in same),
            'an earlier effect on this ticket has an unsettled outcome', *uncertain)
    own = intent and intent['operation_key']
    for start in [r for r in same + snapshot['intents'] if is_start(r, ticket) and r['operation_key'] != own]:
        # A completion settles only its own start: same identities and the same binding (R1).
        done = [r for r in same if r['kind'] == 'completion' and r['operation_key'] == start['operation_key']
                and r['intent_id'] == start['id']
                and all(r[k] == start[k] for k in ('repository', 'spec', 'ticket', 'approval', 'subject'))]
        if start in snapshot['intents'] and selects(start, sources):
            continue  # a claimant for this same selection: one is chosen when the intent is bound
        require(any(r['state'] in SETTLED for r in done),
                'an earlier start on this ticket may have run: its outcome is not settled', *uncertain)

    # 2. Complete reads only; an unread page never proves absence.
    require(snapshot['complete'] and sources['complete'], 'a source read is incomplete', reason='incomplete_read')
    require(incumbent['activity'] != 'unknown', "the incumbent's activity is unread", reason='incomplete_read')
    require(incumbent['worktree'] != 'unknown', "the incumbent's uncommitted work is unread",
            reason='incomplete_read')

    # 3. Every hold, gate, pause and the CS5 overload pause survive.
    gates = 'paused_or_revoked'
    require(not snapshot['paused'] and not snapshot['revoked'], 'paused or revoked', reason=gates)
    require(not snapshot['holds'] and not snapshot['gates'], 'a hold or another gate remains', reason=gates)
    require(sources['overload'] == 'clear', 'the overload pause is on or unknown', reason=gates)

    # 4. Current limits, two evidenced misses and a single branch writer.
    require(bench['settings'] == current_limits, 'the bench was measured against other limits')
    require(len(misses) >= 2, 'fewer than two distinct owner misses: no replacement is evidenced')
    require(incumbent['activity'] == 'stopped', 'the incumbent is live: it could still write the branch')
    require(incumbent['worktree'] in ('clean', 'handed_off'), "the incumbent's uncommitted work is not handed off")
    require(incumbent['head'] == snapshot['head'], 'the branch head moved since the incumbent was read')


def check(bench, sources, snapshot, intent=None, claim=None, history=(), effect_boundary=None, limits_path=LIMITS):
    """One finite pass: decide, return the report to record, and end. Never calls effect_boundary.

    Malformed inputs raise ValueError; an unreadable or invalid limits file
    raises as `limits.read` does. Decisions: `none` (under two misses),
    `record_intent` (record the proposed intent, read it back, end), or the
    contract result's state for that intent (`disabled` once selected).
    """
    sources = read_sources(copy.deepcopy(sources))
    bench = read_bench(copy.deepcopy(bench))
    snapshot = record(snapshot, 'snapshot')
    history = [record(r, r.get('kind') if type(r) is dict else None) for r in history]
    if (intent is None) != (claim is None):
        raise ValueError('an intent and its claim are read together')
    if intent is not None:
        intent, claim = record(intent, 'intent'), record(claim, 'claim')
    if snapshot['ticket'] != sources['ticket']:
        raise ValueError('the snapshot is for another ticket')
    current_limits = limits.read(limits_path)
    misses = owner_misses(bench, sources)
    report = dict(schema=SCHEMA, ticket=sources['ticket'], misses=misses, decision='none', result=None,
                  proposal=None, plan=None, gaps=[], detail='', effects=[])
    if intent is None and len(misses) < 2:
        return dict(report, detail=f'{len(misses)} distinct owner miss(es): no replacement')
    try:
        assess(bench, sources, snapshot, history, current_limits, misses, intent)
        if intent is None and any(selects(r, sources) for r in snapshot['intents']):
            return dict(report, decision='duplicate', detail='this replacement intent is already recorded: check it')
        if intent is None:
            proposal = dict(repository=snapshot['repository'], spec=snapshot['spec'], ticket=sources['ticket'],
                            subject=dict(kind='issue', number=sources['ticket']), approval=snapshot['approval'],
                            action='builder_start', destination='builder', prior_verdict=None,
                            head=snapshot['head'], evidence_digest=binding(sources))
            return dict(report, decision='record_intent', proposal=proposal,
                        detail='record this intent, read it back and end; the next pass checks it')
        state, reason, detail = bind(intent, claim, history, snapshot, sources, effect_boundary)
    except Refusal as refusal:
        state, reason, detail = refusal.state, refusal.reason, refusal.detail
    if intent is None:
        return dict(report, decision=state, detail=detail)
    result = dict(schema='openwiz.ops-dispatch.v1', kind='result', operation_key=intent['operation_key'],
                  intent_id=intent['id'], state=state, reason=reason, next='end', effects=[])
    report.update(decision=state, result=record(result, 'result'), detail=detail)
    if state == 'disabled':
        reviewer, incumbent = sources['reviewer'], sources['incumbent']
        report.update(gaps=list(GAPS), plan=dict(
            ticket=sources['ticket'], branch=incumbent['branch'], head=incumbent['head'],
            retire=incumbent['assignment'], replacement=intent['assignment'], reviewer=reviewer['assignment'],
            correction_rounds=dict(reviewer['correction_rounds']),
            # The incumbent's code stays on the branch: its family stays conflicting.
            family_conflicts=sorted(set(reviewer['family_conflicts']) | {incumbent['family']})))
    return report


def bind(intent, claim, history, snapshot, sources, effect_boundary):
    """The intent must be this replacement's, the first claimant's, then OB3 decides the rest."""
    ticket, incumbent = sources['ticket'], sources['incumbent']
    evidence = binding(sources)
    require(intent['action'] == 'builder_start' and intent['destination'] == 'builder'
            and intent['prior_verdict'] is None and intent['subject'] == dict(kind='issue', number=ticket)
            and intent['head'] == snapshot['head'] and [e['digest'] for e in intent['evidence']] == [evidence],
            'the intent does not bind this replacement, branch and head')
    require(intent['assignment'] not in (None, incumbent['assignment'], sources['reviewer']['assignment']),
            'the replacement span must be new: neither the incumbent nor the selected reviewer')
    claimants = sorted((r for r in snapshot['intents'] if selects(r, sources)),
                       key=lambda r: (r['sequence'], r['created_at'], r['id']))
    if claimants and claimants[0]['id'] != intent['id'] and intent in claimants:
        return 'duplicate', 'record_only', 'another intent already claims this replacement'
    result = effects.resume(intent, claim, history, snapshot, effect_boundary)
    detail = {'disabled': 'one replacement selected on the same branch; retirement and start disabled (OB-A1)'}
    return result['state'], result['reason'], detail.get(result['state'], f"OB3 boundary: {result['reason']}")
