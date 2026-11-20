"""OB7 (#2112) synthetic ON1 evidence proofs; no endpoint effect, no private reads.

Each case changes one source or record of a complete synthetic ON1 application
and checks what the finite pass decides. The release effect stays disabled
under OB-A1 even with complete evidence: the effect callback must never run.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('on1', HERE / 'on1.py')
on1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(on1)
spec = importlib.util.spec_from_file_location('test_grants', HERE / 'test-grants.py')
test_grants = importlib.util.module_from_spec(spec)
spec.loader.exec_module(test_grants)
EXAMPLES = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())
RULE_TEXT = 'Synthetic ON1 standing rule v1: consumers of merged contract changes, unchanged scope.'
DELTA = '+synthetic additive field `colour` in contracts/synthetic.v1.md'
EVIDENCE = dict(evidence_class='fixture', source='fixture:ops-on1/synthetic', value='synthetic ON1 application read')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def key(intent):
    fields = ('repository', 'spec', 'ticket', 'subject', 'approval', 'action',
              'destination', 'assignment', 'prior_verdict', 'head', 'sequence')
    raw = json.dumps({k: intent[k] for k in fields}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(b'openwiz.ops-operation.v1\n' + raw.encode()).hexdigest()


def fixture():
    """A complete, current ON1 application for synthetic ticket 9001."""
    ex = copy.deepcopy(EXAMPLES)
    record, snap, intent, grant = ex['on1'], ex['snapshot'], ex['intent'], ex['grant']
    approval = copy.deepcopy(record['approval'])
    rule = dict(name='on1', revision=digest(RULE_TEXT), comment=9004)
    intent.update(action='hold_release', destination='ops', assignment='ops-span-1', head=None,
                  rule=copy.deepcopy(rule), id='intent-release-1')
    intent['operation_key'] = key(intent)
    # The exact inputs of OB2's own valid synthetic grant for #9001 (test-grants.py).
    bundle = dict(zip(('grant', 'envelope', 'intent', 'snapshot', 'sources', 'assessment', 'changes', 'history'),
                      test_grants.fixture()))
    grant = bundle['grant']
    history = [dict(id=9009, kind='contract', created_at=20)]
    consumer_src = dict(ticket=9001, approval=copy.deepcopy(approval), scope='Synthetic widget page, unchanged.',
                        paths=['src/page/'], grants=[bundle], relies=['contracts/synthetic.v1.md'],
                        links=['#8999 real'])
    change = dict(commit='7' * 40, path='contracts/synthetic.v1.md', previous_path='contracts/old-synthetic.v1.md',
                  producer_ticket=8999, consumer_tickets=[9001])
    sources = dict(
        producer=dict(ticket=8999, approval=copy.deepcopy(approval), merge='7' * 40, merged=True, delta=DELTA),
        consumers=[consumer_src],
        cutoff=dict(start='6' * 40, end='7' * 40, complete=True, changes=[change]),
        hold=dict(comment=9009, kind='contract', complete=True, history=history),
        revision=dict(comment=9011, created_at=30, approval=copy.deepcopy(approval),
                      fingerprint_now=approval['fingerprint'], table_complete=True, relies_ok=True, links_ok=True),
        rule=RULE_TEXT,
        labels=dict(held=True, ready=False, events=[dict(name='held', action='added', created_at=19)]),
        claims=[], evidence=[copy.deepcopy(EVIDENCE)])
    consumer = dict(ticket=9001, approval=copy.deepcopy(approval), scope_digest=digest(consumer_src['scope']),
                    paths_digest=digest(consumer_src['paths']), grants=[grant['grant_id']],
                    relies_digest=digest(consumer_src['relies']), links_digest=digest(consumer_src['links']))
    producer = dict(ticket=8999, approval=copy.deepcopy(approval), merge='7' * 40, delta_digest=digest(DELTA))
    record.update(operation_key=intent['operation_key'], rule=copy.deepcopy(rule), producer=producer,
                  consumers=[consumer], hold=dict(record['hold'], history_digest=digest(history)),
                  cutoff=dict(record['cutoff'], changes=[change]),
                  evidence=[dict(evidence_class=EVIDENCE['evidence_class'], source=EVIDENCE['source'],
                                 digest=digest(EVIDENCE['value']))])
    record['verification']['before_digest'] = digest(sources)
    snap.update(rule=copy.deepcopy(rule), intents=[intent], holds=[9009], gates=[], cutoff='7' * 40,
                history_digest=digest(history), consumers=[copy.deepcopy(consumer)],
                cutoff_changes=[copy.deepcopy(change)], producer=copy.deepcopy(producer), head=None)
    return record, snap, sources


def never(*_):
    raise AssertionError('the release effect ran')


def run(change=None):
    """Each case's pre-effect digest is resealed over its changed sources, so the
    case proves its own check; `forged_before_digest` proves that seal."""
    record, snap, sources = fixture()
    if change:
        change(record, snap, sources)
        if not getattr(change, 'sealed', False):
            record['verification']['before_digest'] = digest(sources)
    return on1.check_on1(record, snap, sources, never)


def sealed(change):
    change.sealed = True
    return change


def grant_of(sources):
    return sources['consumers'][0]['grants'][0]


def grant_other_repository(record, snap, sources):
    """R2: only the grant's repository changes."""
    grant_of(sources)['grant']['repository'] = 'synthetic/elsewhere'


def unrelated_grant(record, snap, sources):
    """R2: a grant valid in another repository, read with its own snapshot."""
    bundle = grant_of(sources)
    for value in [bundle['grant'], bundle['envelope'], bundle['intent'], bundle['snapshot']] + bundle['snapshot']['intents']:
        value['repository'] = 'synthetic/elsewhere'


def stale_grant_material(record, snap, sources):
    """R2: only a material digest changes."""
    bundle = grant_of(sources)
    for value in (bundle['grant'], bundle['snapshot']):
        value['material']['evidence_digest'] = 'e' * 64


def ended_grant(record, snap, sources):
    """R2: a later lifecycle event revoked the grant."""
    bundle = grant_of(sources)
    bundle['history'].append(dict(copy.deepcopy(bundle['grant']), id='grant-1-revoked', status='revoked'))


def manual_history_kind(record, snap, sources):
    """R3: the history says the covered hold is manual; the hold source says contract."""
    sources['hold']['history'][0]['kind'] = 'manual'
    record['hold']['history_digest'] = snap['history_digest'] = digest(sources['hold']['history'])


def duplicate_history(record, snap, sources):
    """R3: two history entries claim the covered hold's identity."""
    sources['hold']['history'].insert(0, dict(id=9009, kind='contract', created_at=18))
    record['hold']['history_digest'] = snap['history_digest'] = digest(sources['hold']['history'])


def forged_evidence(record, snap, sources):
    """R4: an unrelated valid digest in the record's evidence."""
    record['evidence'][0]['digest'] = 'c' * 64


@sealed
def forged_before_digest(record, snap, sources):
    """R4: an unrelated valid digest as the pre-effect evidence."""
    record['verification']['before_digest'] = 'c' * 64


def ready_tied_with_hold(record, snap, sources):
    """R6: a ready label at the hold's own time, before the revision record."""
    sources['labels']['events'].append(dict(name='ready-for-agent', action='added', created_at=20))


def unrelated_consumer(record, snap, sources):
    """R8: the evidence covers #9002 while the release is for #9001."""
    other = dict(sources['consumers'][0], ticket=9002, grants=[])
    sources['consumers'] = [other]
    entry = dict(record['consumers'][0], ticket=9002, grants=[])
    record['consumers'], snap['consumers'] = [entry], [copy.deepcopy(entry)]
    for changes in (sources['cutoff']['changes'], record['cutoff']['changes'], snap['cutoff_changes']):
        changes[0]['consumer_tickets'] = [9002]


def duplicate_consumer(record, snap, sources):
    """R8: the released ticket is evidenced twice."""
    sources['consumers'].append(copy.deepcopy(sources['consumers'][0]))
    record['consumers'].append(copy.deepcopy(record['consumers'][0]))
    snap['consumers'].append(copy.deepcopy(snap['consumers'][0]))


def late_change(record, snap, sources):
    """A second declared-contract merge through the inclusive cutoff, unassessed."""
    later = dict(commit='8' * 40, path='contracts/synthetic.v1.md', previous_path=None,
                 producer_ticket=8998, consumer_tickets=[9001])
    sources['cutoff'].update(end='8' * 40, changes=sources['cutoff']['changes'] + [later])
    snap.update(cutoff='8' * 40, cutoff_changes=snap['cutoff_changes'] + [copy.deepcopy(later)])


def unassessed_rename(record, snap, sources):
    """The inventory found a rename the record does not name by its old path."""
    sources['cutoff']['changes'][0]['previous_path'] = None


def deletion(record, snap, sources):
    gone = dict(commit='7' * 40, path='contracts/retired.v1.md', previous_path=None,
                producer_ticket=8999, consumer_tickets=[9002])
    sources['cutoff']['changes'].append(gone)
    snap['cutoff_changes'].append(copy.deepcopy(gone))


def newer_hold(record, snap, sources):
    sources['hold']['history'].append(dict(id=9012, kind='manual', created_at=31))
    snap['holds'] = [9009, 9012]


def history_only_newer(record, snap, sources):
    """Snapshot labels look clean, but the full history has a newer live hold."""
    sources['hold']['history'].append(dict(id=9012, kind='live', created_at=31))


def changed_scope(record, snap, sources):
    sources['consumers'][0]['scope'] = 'Synthetic widget page, plus a new export.'


def changed_paths(record, snap, sources):
    sources['consumers'][0]['paths'] = ['src/page/', 'src/export/']


def revoked_grant(record, snap, sources):
    grant_of(sources)['grant']['status'] = 'revoked'


def missing_grant(record, snap, sources):
    sources['consumers'][0]['grants'] = []


def stale_consumer_approval(record, snap, sources):
    sources['consumers'][0]['approval']['revision'] = 2


def fingerprint_moved(record, snap, sources):
    sources['revision']['fingerprint_now'] = 'e' * 64


def table_unchecked(record, snap, sources):
    sources['revision']['table_complete'] = False


def relies_failed(record, snap, sources):
    sources['revision']['relies_ok'] = False


def links_failed(record, snap, sources):
    sources['revision']['links_ok'] = False


def label_before_record(record, snap, sources):
    sources['labels']['events'].append(dict(name='ready-for-agent', action='added', created_at=25))


def partial_both(record, snap, sources):
    sources['labels'].update(held=True, ready=True)


def partial_neither(record, snap, sources):
    sources['labels'].update(held=False, ready=False)


def competing_claim(record, snap, sources):
    sources['claims'] = ['release-claim-2']


def recorded_competing_claim(record, snap, sources):
    record['competing_claims'] = ['release-claim-2']


def other_gate(record, snap, sources):
    record['other_gates'] = ['held live: verified live check still required']


def snapshot_gate(record, snap, sources):
    snap['gates'] = ['ordering: #8997 merges to main']


def unmerged_producer(record, snap, sources):
    sources['producer']['merged'] = False


def additive_only(record, snap, sources):
    """An 'additive field' summary in place of the actual merged delta."""
    sources['producer']['delta'] = 'additive optional field only'


def other_rule(record, snap, sources):
    for value in (record, snap):
        value['rule']['name'] = 'narrow-grant'


def rule_text_changed(record, snap, sources):
    sources['rule'] = RULE_TEXT + ' Amended.'


def factory_skill_hold(record, snap, sources):
    sources['hold']['kind'] = 'factory-skill'


def unread_cutoff(record, snap, sources):
    sources['cutoff']['complete'] = False


def unread_history(record, snap, sources):
    sources['hold']['complete'] = False


def unread_snapshot(record, snap, sources):
    snap['complete'] = False


def uncertain(record, snap, sources):
    snap['uncertain_keys'] = ['f' * 64]


def no_intent(record, snap, sources):
    snap['intents'] = []


def claimed_readback(record, snap, sources):
    """A record claiming post-release read-backs that no enabled effect made."""
    record['verification']['after_digest'] = 'a' * 64
    record['verification']['labels_digest'] = 'b' * 64


def paused(record, snap, sources):
    snap['paused'] = True


def older_hold_active(record, snap, sources):
    """An older manual hold, still unresolved, beside the covered contract hold."""
    sources['hold']['history'].insert(0, dict(id=9008, kind='manual', created_at=15))
    snap['holds'] = [9008, 9009]


def other_action(record, snap, sources):
    intent = snap['intents'][0]
    intent['action'] = 'builder_start'
    intent['operation_key'] = record['operation_key'] = key(intent)


def cutoff_start_moved(record, snap, sources):
    sources['cutoff']['start'] = '5' * 40


def merge_outside_cutoff(record, snap, sources):
    for producer in (record['producer'], snap['producer'], sources['producer']):
        producer['merge'] = '5' * 40


REFUSED = 'refused'
CASES = [
    # name, change, state, reason
    ('a contract merge after the cutoff end', late_change, REFUSED, 'stale_binding'),
    ('a rename the record names differently', unassessed_rename, REFUSED, 'stale_binding'),
    ('a deletion missing from the record', deletion, REFUSED, 'stale_binding'),
    ('a newer manual hold', newer_hold, REFUSED, 'paused_or_revoked'),
    ('a newer live hold only in the full history', history_only_newer, REFUSED, 'paused_or_revoked'),
    ('a changed consumer scope', changed_scope, REFUSED, 'stale_binding'),
    ('changed effective owned paths', changed_paths, REFUSED, 'stale_binding'),
    ('a revoked grant', revoked_grant, REFUSED, 'stale_binding'),
    ('an unread grant', missing_grant, REFUSED, 'stale_binding'),
    ('a consumer on an older approval', stale_consumer_approval, REFUSED, 'stale_binding'),
    ('a plan fingerprint changed since the revision', fingerprint_moved, REFUSED, 'stale_binding'),
    ('an unchecked approval table', table_unchecked, REFUSED, 'stale_binding'),
    ('a failed Relies on check', relies_failed, REFUSED, 'stale_binding'),
    ('a failed link check', links_failed, REFUSED, 'stale_binding'),
    ('a label written before the revision record', label_before_record, 'reconcile', 'uncertain_outcome'),
    ('partial labels: ready back, held still on', partial_both, 'reconcile', 'uncertain_outcome'),
    ('partial labels: held off, ready not back', partial_neither, 'reconcile', 'uncertain_outcome'),
    ('a competing unresolved release claim read from source', competing_claim, REFUSED, 'paused_or_revoked'),
    ('a competing release claim in the record', recorded_competing_claim, REFUSED, 'paused_or_revoked'),
    ('another gate in the record', other_gate, REFUSED, 'paused_or_revoked'),
    ('another gate in the snapshot', snapshot_gate, REFUSED, 'paused_or_revoked'),
    ('a producer without a verified merge', unmerged_producer, REFUSED, 'stale_binding'),
    ('an additive summary in place of the actual delta', additive_only, REFUSED, 'stale_binding'),
    ('a grant rule standing in for ON1', other_rule, REFUSED, 'stale_binding'),
    ('a changed standing rule text', rule_text_changed, REFUSED, 'stale_binding'),
    ('a factory-skill hold', factory_skill_hold, REFUSED, 'stale_binding'),
    ('an unread cutoff page', unread_cutoff, REFUSED, 'incomplete_read'),
    ('an unread hold history page', unread_history, REFUSED, 'incomplete_read'),
    ('an incomplete snapshot', unread_snapshot, REFUSED, 'incomplete_read'),
    ('an uncertain earlier operation', uncertain, 'reconcile', 'uncertain_outcome'),
    ('claimed read-backs of a release nobody could make', claimed_readback, 'reconcile', 'uncertain_outcome'),
    ('a paused ticket', paused, REFUSED, 'paused_or_revoked'),
    ('an older unresolved hold still active', older_hold_active, REFUSED, 'paused_or_revoked'),
    ('an intent for another action', other_action, REFUSED, 'stale_binding'),
    ('a cutoff that starts elsewhere', cutoff_start_moved, REFUSED, 'stale_binding'),
    ('a producer merge outside the cutoff', merge_outside_cutoff, REFUSED, 'stale_binding'),
    ('R2: a grant moved to another repository', grant_other_repository, REFUSED, 'stale_binding'),
    ('R2: a grant valid only for another repository', unrelated_grant, REFUSED, 'stale_binding'),
    ('R2: a grant whose material changed', stale_grant_material, REFUSED, 'stale_binding'),
    ('R2: a grant ended by a later lifecycle event', ended_grant, REFUSED, 'stale_binding'),
    ('R3: the covered hold is manual in its history', manual_history_kind, REFUSED, 'stale_binding'),
    ('R3: two history entries for the covered hold', duplicate_history, REFUSED, 'stale_binding'),
    ('R4: record evidence not derived from the sources', forged_evidence, REFUSED, 'stale_binding'),
    ('R4: a pre-effect digest not derived from the sources', forged_before_digest, REFUSED, 'stale_binding'),
    ('R6: a ready label tied with the hold, before the revision', ready_tied_with_hold, 'reconcile',
     'uncertain_outcome'),
    ('R8: evidence for another consumer than the released ticket', unrelated_consumer, REFUSED, 'stale_binding'),
    ('R8: the released ticket evidenced twice', duplicate_consumer, REFUSED, 'stale_binding'),
]


class On1Proof(unittest.TestCase):
    def test_complete_evidence_is_current_and_the_release_stays_disabled(self):
        out = run()
        self.assertTrue(out['evidence_current'], out['detail'])
        self.assertEqual((out['result']['state'], out['result']['reason']), ('disabled', 'unfenced_effect'))
        self.assertEqual((out['result']['next'], out['result']['effects']), ('end', []))
        self.assertEqual(out['result']['intent_id'], 'intent-release-1')

    def test_each_missing_changed_or_racing_piece_prevents_release(self):
        for name, change, state, reason in CASES:
            with self.subTest(name):
                out = run(change)
                self.assertFalse(out['evidence_current'], name)
                self.assertEqual((out['result']['state'], out['result']['reason']), (state, reason), out['detail'])
                self.assertEqual((out['result']['next'], out['result']['effects']), ('end', []))
                # R9: every outcome stays correlated with its durable intent.
                self.assertEqual(out['result']['intent_id'], 'intent-release-1')

    def test_no_single_intent_raises_without_a_fabricated_reference(self):
        # R9: no result names the ON1 record as if it were the intent.
        for change in (no_intent, lambda r, s, _: s['intents'].append(copy.deepcopy(s['intents'][0]))):
            with self.assertRaises(ValueError):
                run(change)

    def test_string_flags_are_malformed_not_true(self):
        # R5: each safety flag as the string "false" must fail, never certify.
        flags = [('cutoff', 'complete'), ('hold', 'complete'), ('producer', 'merged'), ('revision', 'table_complete'),
                 ('revision', 'relies_ok'), ('revision', 'links_ok'), ('labels', 'held'), ('labels', 'ready')]
        for source, flag in flags:
            with self.subTest(f'{source}.{flag}'), self.assertRaises(ValueError):
                run(lambda r, s, src, source=source, flag=flag: src[source].__setitem__(flag, 'false'))
        for change in (lambda r, s, src: src['hold']['history'][0].__setitem__('created_at', '20'),
                       lambda r, s, src: src['consumers'][0].__setitem__('ticket', True),
                       lambda r, s, src: src['cutoff']['changes'][0].__setitem__('consumer_tickets', ['9001'])):
            with self.subTest('typed fields'), self.assertRaises(ValueError):
                run(change)

    def test_nested_approvals_are_strict_not_python_equal(self):
        # R5 re-check: 3.0 == 3 and True == 1 in Python, so each source approval
        # must pass the contract's strict approval shape before any comparison.
        # The grant assessment's approval reaches grants.py's equality check too.
        def at(source):
            return {'consumer': lambda src: src['consumers'][0],
                    'assessment': lambda src: src['consumers'][0]['grants'][0]['assessment'],
                    }.get(source, lambda src: src[source])
        bad = [('revision', 3.0), ('revision', True), ('revision', 0), ('revision', 2 ** 53),
               ('fingerprint', 'not-a-sha'), ('comment', 9003.0), ('comment', False), ('comment', 0),
               ('comment', 2 ** 53), ('extra', 1)]
        for source in ('producer', 'revision', 'consumer', 'assessment'):
            for field, value in bad:
                with self.subTest(f'{source}.approval.{field}={value!r}'), self.assertRaises(ValueError):
                    run(lambda r, s, src, source=source, field=field, value=value:
                        at(source)(src)['approval'].__setitem__(field, value))

    def test_result_is_a_valid_contract_record(self):
        for change in (None, newer_hold, uncertain):
            out = run(change)
            self.assertEqual(on1.protocol.read_record(json.dumps(out['result']))['kind'], 'result')

    def test_malformed_records_raise_before_any_decision(self):
        record, snap, sources = fixture()
        record['hold']['owner_rule'] = 'c2'
        with self.assertRaises(ValueError):
            on1.check_on1(record, snap, sources, never)
        record, snap, sources = fixture()
        del sources['claims']
        with self.assertRaises(ValueError):
            on1.check_on1(record, snap, sources, never)


if __name__ == '__main__':
    unittest.main(verbosity=1)
