"""#1481 (OB6): GitHub-first inbox records, recheck routing and recipient pull/ACK.

Pure, finite helpers over complete source reads the caller supplies; no network,
process, CloudRoom or GitHub client and no effect. Every pending message is an
ops-dispatch v1 `intent` recorded on GitHub before any delivery; that record is
the inbox. Transport acceptance, recipient acknowledgement and completion stay
separate records. A message is context, never new authority: OB3's boundary
keeps every delivery disabled under OB-A1. See ../test/ops-inbox/README.md.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
SHA = re.compile(r'[0-9a-f]{40}')
STAGES = ('fix_after_changes', 'builder_question_answer')


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


effects = _load(HERE / 'effects.py', 'ops_effects_inbox')
limits = _load(HERE / 'carried/limits.py', 'factory_limits_inbox')


def _record(value):
    return effects.read_record(json.dumps(value, allow_nan=False))


def _digest(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def _unique(records):
    """Deduplicate identical copies by (repository, id); conflicting reuse raises."""
    seen = {}
    for record in map(_record, records):
        identity = (record['repository'], record['id'])
        if identity in seen and seen[identity] != record:
            raise ValueError('conflicting immutable record identity')
        seen[identity] = record
    return list(seen.values())


def _sequences(intents, view):
    """Sequences of one ticket/approval must be exactly 1..n, each allocated once."""
    numbers = sorted(i['sequence'] for i in intents
                     if (i['repository'], i['ticket'], i['approval']) == (view['repository'], view['ticket'], view['approval']))
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError('missing or conflicting sequence allocation')
    return len(numbers)


def _identity(record):
    return (record['subject']['number'], record['action'], record['destination'], record['assignment'],
            record['prior_verdict'], record['head'], json.dumps(record['approval'], sort_keys=True),
            record['evidence'][0]['source'])


def message(view, destination, assignment, prior_verdict, head, evidence, prefix, created_at=None):
    """Plan one durable delivery intent, or return the one already recorded.

    Returns ('record', intent) to post on GitHub before any delivery, or
    ('duplicate', existing). The first evidence entry names the triggering
    source; with the key fields (sequence aside) it identifies the message, so
    duplicate wakes and ticks find the same item. Sequence is allocated once per
    ticket/approval in source order. Raises ValueError on conflicting records.
    """
    intents = [r for r in _unique(view['intents']) if r['kind'] == 'intent']
    count = _sequences(intents, view)
    subject = {'kind': 'pull_request', 'number': view['pull_request']}
    intent = dict(schema='openwiz.ops-dispatch.v1', kind='intent', repository=view['repository'],
                  spec=view['spec'], ticket=view['ticket'], subject=subject, operation_key='0' * 64,
                  created_at=view['now'] if created_at is None else created_at, approval=view['approval'],
                  rule=view['rule'], evidence=evidence, action='delivery', destination=destination,
                  assignment=assignment, prior_verdict=prior_verdict, head=head, sequence=count + 1)
    for existing in intents:
        if _identity(existing) == _identity(intent):
            return 'duplicate', existing
    intent['id'] = f'{prefix}-{subject["number"]}-{_digest(list(_identity(intent)))[:16]}'
    intent['operation_key'] = effects.operation_key(intent)
    return 'record', _record(intent)


def _authored(items, view):
    """#641: only the factory's own comments: each item's author must be one of
    view['authors'] (lowercase logins, as grants.record_authors reads them).
    A missing author, or a view with no authors, trusts nobody."""
    authors = view.get('authors', frozenset())
    return [i for i in items if type(i.get('author')) is str and i['author'].lower() in authors]


def spans(records):
    """The reviewer span from public launch-fleet PR records, as records.py reads them.

    Returns (assignment, start comment, open, re-checked heads) for the latest
    span, or None when the records are ambiguous: no readable start, a record
    before any start, a thread identity in public, or a reused comment id.
    """
    ids = [r['comment'] for r in records]
    if len(ids) != len(set(ids)):
        return None
    span = None
    for r in sorted(records, key=lambda r: r['comment']):
        line = r['line'].removeprefix('launch-fleet: ')
        if 'thr_' in line:
            return None
        match = re.fullmatch(r'(review started|re-check sent|review told again|review given up) ([0-9a-f]{40})(?:: .+)?', line)
        if not match:
            continue
        kind, commit = match.groups()
        if kind == 'review started':
            span = {'start': r['comment'], 'open': True, 'sent': set()}
        elif span is None:
            return None
        elif kind == 'review given up':
            span['open'] = False
        elif kind == 're-check sent':
            span['sent'].add(commit)
    return span


def _verdict_evidence(view, verdict):
    source = f'https://github.com/{view["repository"]}/pull/{view["pull_request"]}#issuecomment-{verdict["comment"]}'
    return [{'evidence_class': 'observation', 'source': source,
             'digest': _digest({'verdict': verdict, 'ci': view.get('ci'), 'head': view['head']})}]


def recheck(view):
    """AC1: one recheck to the recorded reviewer for a new green head after its verdict.

    view: repository, spec, ticket, pull_request, approval (current), rule,
    complete, head, ci {head, state}, records [{comment, author, line}] (public
    launch-fleet PR records), verdicts [{comment, author, verdict, head}] (VERDICT
    comments), authors (the record authors), intents (read-back ops intents of
    the ticket), now (ms). A record or verdict by anyone else is ignored.
    Returns ('record', intent), ('duplicate', intent), ('none', why) or
    ('refused', why). Keyed by PR, head, prior verdict and assignment.
    """
    if not view['complete']:
        return 'refused', 'incomplete read'
    span = spans(_authored(view['records'], view))
    if span is None:
        return 'refused', 'ambiguous reviewer'
    if not span['open']:
        return 'refused', 'reviewer retired'
    verdicts = _authored(view['verdicts'], view)
    if not verdicts:
        return 'none', 'no verdict'
    verdict = max(verdicts, key=lambda v: v['comment'])  # older verdicts are superseded
    if verdict['comment'] < span['start']:
        return 'none', 'verdict precedes the current reviewer span'
    if verdict['head'] == view['head']:
        return 'none', 'head unchanged since the verdict'
    ci = view['ci']
    if not ci or ci['head'] != view['head'] or ci['state'] != 'success':
        return 'none', 'ci not green at the head'
    if view['head'] in span['sent']:
        return 'none', 'recheck already sent'
    try:
        return message(view, 'reviewer', f'review-span-{span["start"]}', verdict['comment'], view['head'],
                       _verdict_evidence(view, verdict), 'recheck')
    except ValueError as error:
        return 'refused', str(error)


def findings(view):
    """Findings to the builder: the latest CHANGES at the current head, keyed apart from rechecks."""
    if not view['complete']:
        return 'refused', 'incomplete read'
    verdicts = _authored(view['verdicts'], view)
    if not verdicts:
        return 'none', 'no verdict'
    verdict = max(verdicts, key=lambda v: v['comment'])
    if verdict['verdict'] != 'CHANGES' or verdict['head'] != view['head']:
        return 'none', 'no CHANGES at the head'
    try:
        return message(view, 'builder', view['builder'], verdict['comment'], verdict['head'],
                       _verdict_evidence(view, verdict), 'findings')
    except ValueError as error:
        return 'refused', str(error)


def _result(intent, state, reason):
    return dict(schema='openwiz.ops-dispatch.v1', kind='result', operation_key=intent['operation_key'],
                intent_id=intent['id'], state=state, reason=reason, next='end', effects=[])


def _belongs(record, intent):
    return (record['kind'] != 'intent' and record['operation_key'] == intent['operation_key']
            and record['intent_id'] == intent['id']
            and all(record[k] == intent[k] for k in ('repository', 'spec', 'ticket', 'subject', 'approval')))


def _acked(record, intent, verified):
    """A settling ACK: its own-output id was verified, and it binds this intent's recipient,
    assignment, sequence and (for a head-bound item) head."""
    return (record['kind'] == 'ack' and record['id'] in verified and _belongs(record, intent)
            and (record['recipient'], record['assignment'], record['sequence'])
            == (intent['destination'], intent['assignment'], intent['sequence'])
            and intent['head'] in (None, record['checked_head']))


def pull(view, recipient, assignment, own):
    """AC2/AC4: the recipient's own pending items, read directly from GitHub records.

    view: repository, spec, ticket, approval and head (current), complete,
    cursor (start), read_through (end of this complete read), records (every
    ops record on the ticket and its PRs). own: ids of records this recipient
    itself wrote (its own-output evidence, kept privately). A same-account ack
    it did not write, or accepted transport, settles nothing. Any incomplete
    read, a record bound to another repository/spec/ticket, conflicting identity
    or sequence gap returns no items and the start cursor. verdicts: the PR's
    complete current VERDICT list; a builder/reviewer item bound to an older
    verdict is superseded. Ordering spans every destination of the
    ticket/approval: an unresolved earlier item defers later ones. Another
    recipient's ACK settles its item only when listed in verified_acks
    (independently verified own-output ids, kept privately).
    """
    stop = {'complete': False, 'cursor': view['cursor'], 'items': [], 'next': 'end'}
    if not view['complete']:
        return stop
    try:
        records = _unique(view['records'])
        # R1: every record must carry this view's complete repository/spec/ticket binding.
        if any((r['repository'], r['spec'], r['ticket']) != (view['repository'], view['spec'], view['ticket'])
               for r in records):
            return stop
        intents = [r for r in records if r['kind'] == 'intent']
        _sequences(intents, view)
        latest = max((v['comment'] for v in _authored(view['verdicts'], view)), default=None)
    except (KeyError, TypeError, ValueError):
        return stop
    verified = own | set(view['verified_acks'])
    items, blocked = [], set()
    # R3: order across every destination of the ticket/approval, then report this recipient's items.
    for intent in sorted(intents, key=lambda i: (i['approval']['revision'], i['sequence'])):
        events = [r for r in records if _belongs(r, intent)]
        states = {(r['kind'], r.get('state')) for r in events}
        stream = json.dumps(intent['approval'], sort_keys=True)
        if states & {('transport', 'uncertain'), ('completion', 'uncertain')}:
            state = 'reconcile', 'uncertain_outcome'
        elif any(_acked(r, intent, verified) for r in events):
            state = 'acknowledged', 'record_only'
        elif ('completion', 'completed') in states:
            state = 'complete', 'already_complete'
        elif (('completion', 'superseded') in states or intent['approval'] != view['approval']
              or intent['head'] not in (None, view['head'])
              # R2: a verdict-bound item is superseded by any newer verdict.
              or (intent['destination'] in ('builder', 'reviewer') and intent['prior_verdict'] is not None
                  and intent['prior_verdict'] != latest)):
            state = 'superseded', 'superseded'
        elif stream in blocked:
            state = 'deferred', 'out_of_order'
        else:
            state = 'recorded', 'record_only'
        if state[0] in ('recorded', 'reconcile', 'deferred'):
            blocked.add(stream)
        if (intent['destination'], intent['assignment']) == (recipient, assignment):
            items.append(_record(_result(intent, *state)))
    return {'complete': True, 'cursor': view['read_through'], 'items': items, 'next': 'end'}


def acknowledge(view, recipient, assignment, own, intent_id, ident, created_at, evidence, checks_digest):
    """The ack record the intended recipient posts after checking its next item.

    Only the next `recorded` item of its own stream can be acknowledged; the
    checked head is the current head the recipient read. Raises ValueError.
    """
    result = pull(view, recipient, assignment, own)
    item = next((i for i in result['items'] if i['intent_id'] == intent_id), None)
    if item is None or item['state'] != 'recorded':
        raise ValueError('not this recipient\'s next pending item')
    intent = next(r for r in _unique(view['records']) if r['kind'] == 'intent' and r['id'] == intent_id)
    ack = {k: intent[k] for k in ('schema', 'repository', 'spec', 'ticket', 'subject', 'operation_key',
                                  'approval', 'rule')}
    ack.update(kind='ack', id=ident, created_at=created_at, evidence=evidence, intent_id=intent_id,
               recipient=recipient, assignment=assignment, sequence=intent['sequence'],
               checked_head=view['head'], checks_digest=checks_digest)
    return _record(ack)


def wake(view, recipient, assignment, own, source):
    """One finite recipient wake: pull, name what is due, end. No watcher or sleep."""
    result = pull(view, recipient, assignment, own)
    due = [i['intent_id'] for i in result['items'] if i['state'] == 'recorded']
    return dict(result, source=source, due=due, next='end')


def recovery(wakes):
    """AC3: only a complete independent wake that found work shows the pull path usable.

    An idle inbox, a partial read or a PC-sourced wake proves nothing. This is a
    synthetic classification; only OB8's live run establishes recovery.
    """
    if any(w['source'] == 'independent' and w['complete'] and w['items'] for w in wakes):
        return 'pull usable (synthetic)'
    return 'unverified'


def _ungated(start, end, held):
    """Minutes from start to end minus the union of held intervals (each [on, off], on <= off)."""
    if any(type(on) is not int or type(off) is not int or on > off for on, off in held):
        raise ValueError('malformed held interval')
    total, cursor = end - start, start
    for on, off in sorted(held):
        on, off = max(on, cursor), min(off, end)
        if off > on:
            total -= off - on
            cursor = off
    return round(total / 60000, 3)


def measure(records, own, now, eligible, held):
    """AC6: recheck delay from eligibility (green head) to the reviewer's own bound ack, and
    the oldest pending item's age, both excluding the union of held time, with their
    denominators. Only an own bound ACK or a completed/superseded completion settles an
    item; uncertain, refused, disabled or unverified non-execution outcomes stay pending."""
    records = _unique(records)
    intents = [r for r in records if r['kind'] == 'intent']
    acks = {}
    for intent in intents:
        found = [r for r in records if _acked(r, intent, own)]
        if found:
            acks[intent['id']] = min(found, key=lambda r: r['created_at'])
    settled = set(acks) | {i['id'] for i in intents for r in records
                           if r['kind'] == 'completion' and _belongs(r, i) and r['state'] in ('completed', 'superseded')}
    delay = {'eligible': 0, 'measured': 0, 'open': 0, 'unknown': 0, 'minutes': []}
    for intent in intents:
        if intent['destination'] != 'reviewer' or intent['prior_verdict'] is None:
            continue
        delay['eligible'] += 1
        if intent['head'] not in eligible:
            delay['unknown'] += 1
        elif intent['id'] in acks:
            delay['measured'] += 1
            delay['minutes'].append(_ungated(eligible[intent['head']], acks[intent['id']]['created_at'], held))
        else:
            delay['open'] += 1
    pending = [i for i in intents if i['id'] not in settled]
    oldest = max((_ungated(i['created_at'], now, held) for i in pending), default=None)
    return {'recheck_delay': delay, 'pending': {'count': len(pending), 'oldest_minutes': oldest}}


def due(settings, bench, intents, decisions, context):
    """AC7: missed fix/answer goals, routed through the existing durable items.

    settings: the limits file (TL1 reader; refusal propagates). bench: TL2's
    stage bench, read with the same settings. intents: read-back ops intents.
    decisions: question comment ids the ops agent judged to need a new decision.
    context: the independently verified {repository, spec, approval, owners},
    owners mapping 'builder:<ticket>' / 'orchestrator:<ticket>' to the
    assignment. Only a current `delivery` intent with that complete binding,
    the wait's ticket/subject/head/origin and the owner's assignment counts.
    A route names the existing role and item; delivery or escalation is never a
    completed fix or answer, which only an evidenced end source shows. Helper
    dispatch on a missed stage is #2338's; nothing here starts or sends.
    """
    loaded = limits.read(settings)
    if (bench.get('schema') != 'closedwiz.journey.stage-bench.v1' or bench.get('authority') != 'none'
            or bench.get('settings') != loaded):
        raise ValueError('stage bench does not match the loaded settings')
    intents = [r for r in _unique(intents) if r['kind'] == 'intent']
    rows = []
    for wait in bench['waits']:
        if wait['stage'] not in STAGES or wait['result'] != 'missed':
            continue
        if wait['stage'] == 'fix_after_changes':
            pr, head, origin = re.fullmatch(r'fix_after_changes:p(\d+):([0-9a-f]{40}):c(\d+)', wait['key']).groups()
            route, what, subject = 'builder', 'findings', {'kind': 'pull_request', 'number': int(pr)}
            tickets = wait['tickets']
        else:
            ticket, origin = re.fullmatch(r'builder_question_answer:t(\d+):c(\d+)', wait['key']).groups()
            route, what, head = 'orchestrator', 'answer', None
            subject, tickets = {'kind': 'issue', 'number': int(ticket)}, [int(ticket)]
        match = [i for i in intents
                 if i['action'] == 'delivery' and i['destination'] == route and i['ticket'] in tickets
                 and (i['repository'], i['spec'], i['approval']) == (context['repository'], context['spec'],
                                                                     context['approval'])
                 and i['subject'] == subject and i['head'] == head and i['prior_verdict'] == int(origin)
                 and i['assignment'] == context['owners'].get(f'{route}:{i["ticket"]}')]
        keys = sorted({i['operation_key'] for i in match})
        gap = None if len(keys) == 1 else (f'no durable {what} item: record one before routing' if not keys
                                            else f'ambiguous {what} items')
        rows.append({'key': wait['key'], 'stage': wait['stage'], 'route': route,
                     'operation_key': keys[0] if len(keys) == 1 else None,
                     'done': f'evidenced end {wait["end"]}' if wait['end'] else None,
                     'exception': 'needs a new decision from Jake' if int(origin) in decisions else None,
                     'gap': gap, 'wait_minutes': wait['wait_minutes'], 'limit_minutes': wait['limit_minutes']})
    return rows
