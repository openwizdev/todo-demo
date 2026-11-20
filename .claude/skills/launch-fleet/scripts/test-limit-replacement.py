#!/usr/bin/env python3
"""TL4 (#2339) proofs: retire and replace a stuck owner after two ticket misses.

Synthetic stage-bench output, ops records and source reads only, in virtual
time: no GitHub, CloudRoom or process call, no sleep. Every case also checks
that the effect callback never runs: retirement and start stay disabled under
OB-A1 even when every check passes.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

sys.dont_write_bytecode = True
import unittest

HERE = Path(__file__).resolve().parent


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lr = load(HERE / 'limit-replacement.py', 'limit_replacement')
reference = load(HERE.parent / 'test/ops-protocol/protocol.py', 'ops_protocol_reference')
EXAMPLES = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())
# The literal defaults of tools/collector/limits.conf (limits-contract.md).
SETTINGS = {'schema': 'closedwiz.factory-limits.v1',
            'minutes': {'builder_start': 10, 'reviewer_start': 5, 'merge': 5,
                        'fix_after_changes': 30, 'builder_question_answer': 15}}
HEAD = 'c' * 40
NEW_HEAD = 'e' * 40
BRANCH = 'room/9001-synthetic-widget'
GAPS = ['retirement', 'start', 'lookup', 'fencing']


def sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def wait(key, result='missed', ticket=9001, stage=None):
    stage = stage or key.split(':')[0]
    return {'key': key, 'stage': stage, 'tickets': [ticket], 'pull_request': 9101,
            'wait_minutes': 45.0, 'wait_range_minutes': [45.0, 45.0],
            'limit_minutes': SETTINGS['minutes'][stage], 'result': result,
            'start': 's1', 'end': None, 'support': [], 'folded': 0, 'gaps': []}


FIX1 = f'fix_after_changes:p9101:{"a" * 40}:c7001'
FIX2 = f'fix_after_changes:p9101:{HEAD}:c7002'


def bench(*waits, settings=SETTINGS):
    return {'schema': 'closedwiz.journey.stage-bench.v1', 'settings': copy.deepcopy(settings),
            'read_at': '2030-03-01T12:00:00Z', 'authority': 'none', 'stages': [],
            'waits': [copy.deepcopy(w) for w in waits],
            'misses': sorted(w['key'] for w in waits if w['result'] == 'missed'), 'sources': {}}


def sources():
    """Complete reads for synthetic ticket 9001: a stopped builder, clean worktree."""
    return {'complete': True, 'ticket': 9001, 'overload': 'clear', 'recorded_misses': [],
            'incumbent': {'assignment': 'builder-span-1', 'family': 'claude', 'branch': BRANCH,
                          'head': HEAD, 'activity': 'stopped', 'worktree': 'clean'},
            'reviewer': {'assignment': 'review-span-1', 'family_conflicts': [],
                         'correction_rounds': {'R1': 2, 'R3': 1}}}


def material(src=None):
    """The replacement binding, computed independently of the module (test's own digest)."""
    src = src or sources()
    inc = src['incumbent']
    return sha({'ticket': src['ticket'], 'branch': inc['branch'], 'head': inc['head'],
                'incumbent': inc['assignment']})


class Proof(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.snapshot = copy.deepcopy(EXAMPLES['snapshot'])
        self.snapshot['holds'] = []  # the shared example carries an ON1 hold
        self.src = sources()
        self.bench = bench(wait(FIX1), wait(FIX2))
        self.intent, self.claim = self.replacement_intent('intent-replace-1', 1)
        self.snapshot['intents'] = [copy.deepcopy(self.intent)]
        self.history = []

    def replacement_intent(self, ident, sequence, head=HEAD, digest=None):
        intent = copy.deepcopy(EXAMPLES['intent'])
        intent.update(id=ident, sequence=sequence, head=head, assignment='builder-span-2',
                      action='builder_start', destination='builder')
        intent['evidence'] = [{'evidence_class': 'observation', 'source': 'fixture:limit-replacement/misses',
                               'digest': digest or material()}]
        intent['operation_key'] = reference.operation_key(intent)
        claim = copy.deepcopy(EXAMPLES['operation'])
        claim.update(intent_id=ident, operation_key=intent['operation_key'])
        claim['ref'] = reference.claim_ref(claim)
        return intent, claim

    def run_check(self, recorded=True, **overrides):
        args = dict(bench=self.bench, sources=self.src, snapshot=self.snapshot,
                    intent=self.intent if recorded else None, claim=self.claim if recorded else None,
                    history=self.history, effect_boundary=lambda *a: self.calls.append(a))
        args.update(overrides)
        if not recorded and 'snapshot' not in overrides:
            # Before its intent is recorded, the snapshot holds no replacement intent.
            args['snapshot'] = dict(self.snapshot, intents=[i for i in self.snapshot['intents']
                                                            if i['id'] != self.intent['id']])
        report = lr.check(**args)
        self.assertEqual(self.calls, [], 'the effect boundary must never be called')
        self.assertEqual(report['effects'], [])
        if report['result'] is not None:
            self.assertEqual(reference.read_record(json.dumps(report['result'])), report['result'])
            self.assertEqual(report['result']['next'], 'end')
        return report

    def outcome(self, report):
        result = report['result']
        return report['decision'], result and result['state'], result and result['reason']

    # AC1: zero/one miss never retires; two select one replacement on the same branch.

    def test_zero_and_one_owner_miss_never_select(self):
        cases = {
            'no misses': bench(wait(FIX1, 'not missed'), wait(FIX2, 'pending')),
            'one miss': bench(wait(FIX1), wait(FIX2, 'unknown')),
            # Q2: only the builder's own stage counts against it.
            'other stages': bench(wait(FIX1), wait('reviewer_start:p9101:' + HEAD + ':-'),
                                  wait('merge:p9101:' + HEAD + ':c7003:-'),
                                  wait('builder_question_answer:t9001:c7004'),
                                  wait('builder_start:t9001')),
            'another ticket': bench(wait(FIX1), wait(FIX2, ticket=9002)),
        }
        for name, value in cases.items():
            for intent in (False, True):
                with self.subTest(name, intent=intent):
                    self.calls = []
                    report = self.run_check(recorded=intent, bench=value)
                    if intent:
                        # An intent with under two misses is not evidenced.
                        self.assertEqual(self.outcome(report), ('refused', 'refused', 'stale_binding'))
                    else:
                        self.assertEqual((report['decision'], report['result'], report['plan']),
                                         ('none', None, None))
                    self.assertLess(len(report['misses']), 2)

    def test_tl2_demonstration_bench_is_read_as_published(self):
        # TL2's sanitized output: ticket 4301 has three misses, one of them its builder's own.
        published = json.loads((HERE.parent / 'test/ops-inbox/stage-waits-bench.json').read_text())
        self.src['ticket'] = self.snapshot['ticket'] = 4301
        report = self.run_check(recorded=False, bench=published)
        self.assertEqual(len(published['misses']), 3)
        self.assertEqual((report['decision'], [m.split(':')[0] for m in report['misses']]),
                         ('none', ['fix_after_changes']))

    def test_two_misses_record_intent_first_then_select_one_disabled_replacement(self):
        report = self.run_check(recorded=False)
        self.assertEqual(report['decision'], 'record_intent')
        self.assertEqual(report['misses'], sorted([FIX1, FIX2]))
        proposal = report['proposal']
        self.assertEqual((proposal['action'], proposal['destination'], proposal['head'],
                          proposal['prior_verdict'], proposal['evidence_digest']),
                         ('builder_start', 'builder', HEAD, None, material()))
        self.assertEqual(proposal['subject'], {'kind': 'issue', 'number': 9001})

        report = self.run_check()
        self.assertEqual(self.outcome(report), ('disabled', 'disabled', 'unfenced_effect'))
        plan = report['plan']
        self.assertEqual((plan['branch'], plan['head'], plan['retire'], plan['replacement']),
                         (BRANCH, HEAD, 'builder-span-1', 'builder-span-2'))
        self.assertEqual([gap.split(':')[0] for gap in report['gaps']], GAPS)

    # AC2: repeated wakes, duplicates, simultaneous claimants and changing heads.

    def test_repeated_observations_of_one_interval_are_one_miss(self):
        self.bench = bench(wait(FIX1))
        self.src['recorded_misses'] = [FIX1, FIX1]
        report = self.run_check(recorded=False)
        self.assertEqual((report['decision'], report['misses']), ('none', [FIX1]))

    def test_earlier_recorded_misses_survive_a_fresh_tick(self):
        # The fresh bench no longer lists the first miss; its earlier record still counts.
        self.bench = bench(wait(FIX2))
        self.src['recorded_misses'] = [FIX1]
        report = self.run_check()
        self.assertEqual(report['misses'], sorted([FIX1, FIX2]))
        self.assertEqual(self.outcome(report), ('disabled', 'disabled', 'unfenced_effect'))
        for bad in ([FIX1, 7], ['merge:p9101:x:c1:-'], 'fix', [' ' + FIX1]):
            with self.subTest(recorded=bad), self.assertRaises(ValueError):
                self.src['recorded_misses'] = bad
                self.run_check()

    def test_duplicate_wakes_reach_the_same_operation_and_decision(self):
        first, second = self.run_check(), self.run_check()
        self.assertEqual(first, second)
        self.assertEqual(first['result']['operation_key'], self.intent['operation_key'])
        self.assertEqual(self.run_check(recorded=False)['proposal'], self.run_check(recorded=False)['proposal'])

    def test_simultaneous_claimants_leave_exactly_one_writer(self):
        other, other_claim = self.replacement_intent('intent-replace-2', 2)
        self.snapshot['intents'] = [copy.deepcopy(other), copy.deepcopy(self.intent)]
        report = self.run_check(intent=other, claim=other_claim)
        self.assertEqual(self.outcome(report), ('duplicate', 'duplicate', 'record_only'))
        self.assertIsNone(report['plan'])
        report = self.run_check()
        self.assertEqual(self.outcome(report), ('disabled', 'disabled', 'unfenced_effect'))

    def test_a_changed_head_never_acts_on_the_old_selection(self):
        # The branch moved after the intent: the stale intent is refused.
        for change in ('snapshot', 'incumbent', 'both'):
            with self.subTest(change):
                self.setUp()
                if change in ('snapshot', 'both'):
                    self.snapshot['head'] = NEW_HEAD
                if change in ('incumbent', 'both'):
                    self.src['incumbent']['head'] = NEW_HEAD
                report = self.run_check()
                self.assertEqual(self.outcome(report), ('refused', 'refused', 'stale_binding'))
                self.assertIsNone(report['plan'])
                if change != 'both':
                    # The incumbent's read and the branch tip disagree: nothing to propose.
                    report = self.run_check(recorded=False)
                    self.assertEqual((report['decision'], report['proposal']), ('refused', None))
        self.setUp()
        self.snapshot['head'] = self.src['incumbent']['head'] = NEW_HEAD
        report = self.run_check(recorded=False)
        self.assertEqual((report['decision'], report['proposal']['head']), ('record_intent', NEW_HEAD))
        self.assertEqual(report['proposal']['evidence_digest'], material(self.src))

    def test_an_earlier_unsettled_replacement_blocks_a_new_head_selection(self):
        # An intent for the old head without a settled completion: it may have run.
        old, _ = self.replacement_intent('intent-replace-0', 1, head='a' * 40, digest='f' * 64)
        new, new_claim = self.replacement_intent('intent-replace-1', 2)
        self.snapshot.update(intents=[copy.deepcopy(new)], next_sequence=2)
        self.history = [old]
        report = self.run_check(intent=new, claim=new_claim)
        self.assertEqual(self.outcome(report), ('reconcile', 'reconcile', 'uncertain_outcome'))
        report = self.run_check(recorded=False)
        self.assertEqual(report['decision'], 'reconcile')
        for state, expected in (('disabled', 'disabled'), ('refused', 'disabled'),
                                ('completed', 'reconcile'), ('uncertain', 'reconcile'),
                                ('reconciled_not_executed', 'reconcile')):
            with self.subTest(earlier=state):
                done = copy.deepcopy(EXAMPLES['completion'])
                done.update(id='completion-0', intent_id=old['id'], operation_key=old['operation_key'], state=state)
                self.history = [old, done]
                self.assertEqual(self.run_check(intent=new, claim=new_claim)['decision'], expected)
        # R1: a disabled completion bound to another spec, approval or subject settles nothing.
        other_approval = dict(old['approval'], revision=old['approval']['revision'] + 1)
        for field, value in (('spec', 9999), ('approval', other_approval),
                             ('subject', {'kind': 'pull_request', 'number': 9101})):
            with self.subTest(mismatched=field):
                done = copy.deepcopy(EXAMPLES['completion'])
                done.update(id='completion-0', intent_id=old['id'], operation_key=old['operation_key'],
                            state='disabled')
                done[field] = value
                self.history = [old, done]
                self.assertEqual(self.run_check(intent=new, claim=new_claim)['decision'], 'reconcile')
                self.assertEqual(self.run_check(recorded=False)['decision'], 'reconcile')

    def test_a_stale_dispatcher_generation_is_refused(self):
        self.snapshot.update(generation=2, owner='standby')
        self.assertEqual(self.outcome(self.run_check()), ('refused', 'refused', 'stale_claim'))

    # AC3: handoff, live owner, uncertain effects and missing evidence before effects.

    def test_the_incumbent_must_be_stopped_with_its_work_handed_off(self):
        cases = [('activity', 'running', 'stale_binding'), ('activity', 'unknown', 'incomplete_read'),
                 ('worktree', 'dirty', 'stale_binding'), ('worktree', 'unknown', 'incomplete_read')]
        for field, value, reason in cases:
            for intent in (False, True):
                with self.subTest(field=field, value=value, intent=intent):
                    self.setUp()
                    self.src['incumbent'][field] = value
                    report = self.run_check(recorded=intent)
                    self.assertEqual(report['decision'], 'refused')
                    self.assertIsNone(report['proposal'])
                    self.assertIsNone(report['plan'])
                    if intent:
                        self.assertEqual(report['result']['reason'], reason)
        self.setUp()
        self.src['incumbent']['worktree'] = 'handed_off'
        self.assertEqual(self.run_check()['decision'], 'disabled')

    def test_the_old_owner_resuming_after_selection_stops_the_replacement(self):
        self.assertEqual(self.run_check()['decision'], 'disabled')
        self.src['incumbent']['activity'] = 'running'
        self.assertEqual(self.outcome(self.run_check()), ('refused', 'refused', 'stale_binding'))

    def test_uncertain_prior_effects_reconcile_before_anything_else(self):
        accepted = copy.deepcopy(EXAMPLES['transport'])
        accepted.update(state='accepted', operation_key='9' * 64, intent_id='intent-other')
        for name in ('snapshot key', 'transport on this ticket'):
            for intent in (False, True):
                with self.subTest(name, intent=intent):
                    self.setUp()
                    self.src['incumbent']['activity'] = 'running'  # uncertainty outranks it
                    if name == 'snapshot key':
                        self.snapshot['uncertain_keys'] = ['9' * 64]
                    else:
                        self.history = [copy.deepcopy(accepted)]
                    report = self.run_check(recorded=intent)
                    self.assertEqual(report['decision'], 'reconcile')
                    if intent:
                        self.assertEqual(report['result']['reason'], 'uncertain_outcome')

    def test_incomplete_reads_refuse(self):
        for target in ('snapshot', 'sources'):
            with self.subTest(target):
                self.setUp()
                (self.snapshot if target == 'snapshot' else self.src)['complete'] = False
                self.assertEqual(self.outcome(self.run_check()), ('refused', 'refused', 'incomplete_read'))
                self.assertEqual(self.run_check(recorded=False)['decision'], 'refused')

    def test_selection_reports_every_unavailable_boundary_for_jake(self):
        report = self.run_check()
        self.assertEqual(len(report['gaps']), 4)
        self.assertIn('#2244', report['gaps'][2])
        self.assertIn('P5', report['gaps'][3])

    # AC4: holds, scope, reviewer/family, correction rounds, CI/live/spending gates survive.

    def test_holds_gates_and_overload_refuse_with_no_proposal(self):
        cases = [('snapshot', 'holds', [9009]), ('snapshot', 'gates', ['live check pending']),
                 ('snapshot', 'paused', True), ('snapshot', 'revoked', True),
                 ('sources', 'overload', 'paused'), ('sources', 'overload', 'unknown')]
        for target, field, value in cases:
            for intent in (False, True):
                with self.subTest(field=field, value=value, intent=intent):
                    self.setUp()
                    (self.snapshot if target == 'snapshot' else self.src)[field] = value
                    report = self.run_check(recorded=intent)
                    self.assertEqual(report['decision'], 'refused')
                    self.assertIsNone(report['proposal'])
                    if intent:
                        self.assertEqual(report['result']['reason'], 'paused_or_revoked')

    def test_reviewer_span_family_conflicts_and_correction_rounds_carry_over(self):
        self.src['reviewer']['family_conflicts'] = ['gpt']
        plan = self.run_check()['plan']
        self.assertEqual(plan['reviewer'], 'review-span-1')
        self.assertEqual(plan['correction_rounds'], {'R1': 2, 'R3': 1})
        # The incumbent's code stays on the branch, so its family stays conflicting.
        self.assertEqual(plan['family_conflicts'], ['claude', 'gpt'])
        self.setUp()
        self.src['incumbent']['family'] = 'unknown'
        self.assertIn('unknown', self.run_check()['plan']['family_conflicts'])
        # The replacement can be neither the incumbent's nor the reviewer's span.
        for span in ('builder-span-1', 'review-span-1'):
            with self.subTest(span=span):
                self.setUp()
                intent, claim = self.replacement_intent('intent-replace-1', 1)
                intent['assignment'] = span
                intent['operation_key'] = reference.operation_key(intent)
                claim['operation_key'] = intent['operation_key']
                claim['ref'] = reference.claim_ref(claim)
                self.snapshot['intents'] = [copy.deepcopy(intent)]
                report = self.run_check(intent=intent, claim=claim)
                self.assertEqual(self.outcome(report), ('refused', 'refused', 'stale_binding'))

    def test_the_intent_must_bind_this_replacement(self):
        changes = {'another action': ('action', 'review_start'), 'another role': ('destination', 'reviewer'),
                   'a verdict': ('prior_verdict', 7001), 'other evidence': ('evidence', None)}
        for name, (field, value) in changes.items():
            with self.subTest(name):
                self.setUp()
                intent = copy.deepcopy(self.intent)
                if field == 'evidence':
                    intent['evidence'][0]['digest'] = 'f' * 64
                else:
                    intent[field] = value
                intent['operation_key'] = reference.operation_key(intent)
                claim = dict(copy.deepcopy(self.claim), operation_key=intent['operation_key'])
                claim['ref'] = reference.claim_ref(claim)
                self.snapshot['intents'] = [copy.deepcopy(intent)]
                report = self.run_check(intent=intent, claim=claim)
                self.assertEqual(self.outcome(report), ('refused', 'refused', 'stale_binding'))

    def test_the_bench_must_use_the_current_limits(self):
        changed = copy.deepcopy(SETTINGS)
        changed['minutes']['fix_after_changes'] = 20
        self.bench = bench(wait(FIX1), wait(FIX2), settings=changed)
        for w in self.bench['waits']:
            w['limit_minutes'] = 20
        self.assertEqual(self.outcome(self.run_check()), ('refused', 'refused', 'stale_binding'))
        self.assertEqual(self.run_check(recorded=False)['decision'], 'refused')
        # An edited settings file is read on the next pass; an invalid one refuses the read.
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'limits.conf'
            path.write_text(''.join(f'{k}={v}\n' for k, v in changed['minutes'].items()))
            self.assertEqual(self.run_check(limits_path=path)['decision'], 'disabled')
            path.write_text('fix_after_changes=20\n')
            with self.assertRaises(ValueError):
                self.run_check(limits_path=path)

    def test_malformed_inputs_raise_instead_of_deciding(self):
        def mutate(fn):
            self.setUp()
            fn()
            with self.assertRaises(ValueError):
                self.run_check()
        mutate(lambda: self.bench.update(authority='ops'))
        mutate(lambda: self.bench.update(schema='closedwiz.journey.stage-bench.v2'))
        mutate(lambda: self.bench.update(misses=[FIX1]))
        mutate(lambda: self.bench['waits'].append(copy.deepcopy(self.bench['waits'][0])))
        mutate(lambda: self.bench['waits'][0].update(result='late'))
        mutate(lambda: self.bench['waits'][0].update(authority='ops'))
        mutate(lambda: self.bench['waits'][0].pop('gaps'))
        mutate(lambda: self.bench['waits'][0].update(tickets=[True]))
        mutate(lambda: self.bench['waits'][0].update(limit_minutes=31))
        mutate(lambda: self.bench['settings']['minutes'].update(merge=5.0))
        mutate(lambda: self.src.update(extra=1))
        mutate(lambda: self.src.update(complete=1))
        mutate(lambda: self.src.update(ticket=9002))
        mutate(lambda: self.src['incumbent'].update(activity='idle'))
        mutate(lambda: self.src['incumbent'].update(head='C' * 40))
        mutate(lambda: self.src['reviewer']['correction_rounds'].update(R1=True))
        mutate(lambda: self.src['reviewer'].pop('assignment'))
        mutate(lambda: self.snapshot.update(kind='intent'))
        self.setUp()
        with self.assertRaises(ValueError):
            self.run_check(claim=None)


if __name__ == '__main__':
    unittest.main(verbosity=1)
