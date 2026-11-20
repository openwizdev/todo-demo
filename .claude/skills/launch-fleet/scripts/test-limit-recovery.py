"""TL3 (#2338) synthetic recovery proofs; no endpoint effect, no private reads.

Run: python3 -I skills/launch-fleet/scripts/test-limit-recovery.py

Each case starts from one complete synthetic open miss (TL2's stage-bench row)
and the ops agent's derived pull request facts, changes one thing, and checks
which fix helper TL3 selects, what it records before any dispatch and what the
finite pass decides. The effect callback must never run (OB-A1), and no refusal,
disabled or uncertain result is ever counted as a recovery.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import unittest

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recovery = load('limit_recovery', HERE / 'limit-recovery.py')
effects = load('ops_effects', HERE / 'effects.py')
EXAMPLES = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())
FIXTURE = json.loads((HERE.parent / 'test/limit-recovery/misses.json').read_text())
HEAD = '1a' * 20
NEWER = '2b' * 20
DISPATCH = dict(name='dispatch', revision='b' * 64, comment=9004)
SOURCE = 'fixture:limit-recovery/synthetic'


def miss(stage='fix', **changes):
    return dict(copy.deepcopy(FIXTURE['misses'][stage]), **changes)


def facts(**changes):
    return dict(copy.deepcopy(FIXTURE['facts']), **changes)


class Selection(unittest.TestCase):
    """Which helper an open, evidenced miss selects, from TL2's row and the PR facts."""

    def pick(self, row, value):
        return recovery.select(row, value)

    def assertHelper(self, row, value, role):
        chosen = self.pick(row, value)
        self.assertEqual((chosen['role'], chosen['reason']), (role, 'eligible'), chosen)

    def assertRefused(self, row, value, reason):
        chosen = self.pick(row, value)
        self.assertEqual((chosen['role'], chosen['reason']), (None, reason), chosen)

    def test_open_fix_miss_with_no_push_selects_findings_fix(self):
        self.assertHelper(miss(), facts(), 'findings-fix')

    def test_open_fix_miss_with_red_ci_on_a_newer_head_selects_ci_fix(self):
        self.assertHelper(miss(), facts(head=NEWER, ci='failure'), 'ci-fix')

    def test_open_fix_miss_with_a_conflicting_newer_head_selects_conflict_fix(self):
        self.assertHelper(miss(), facts(head=NEWER, ci='success', conflict=True), 'conflict-fix')

    def test_open_merge_miss_that_conflicts_with_main_selects_conflict_fix(self):
        self.assertHelper(miss('merge'), facts(conflict=True), 'conflict-fix')

    def test_merge_miss_without_conflict_stays_with_the_merge_owner(self):
        self.assertRefused(miss('merge'), facts(), 'existing_owner')

    def test_builder_reviewer_and_question_misses_stay_with_their_owners(self):
        for stage in ('builder_start', 'reviewer_start', 'builder_question_answer'):
            with self.subTest(stage=stage):
                self.assertRefused(miss(stage), facts(), 'existing_owner')

    def test_only_an_open_measured_miss_is_eligible(self):
        for result in ('not missed', 'pending', 'unknown', 'gated', 'stale'):
            with self.subTest(result=result):
                self.assertRefused(miss(result=result), facts(), 'not_missed')
        # An ended miss is already over: the fix landed late, nothing to recover.
        self.assertRefused(miss(end='s13'), facts(), 'already_ended')

    def test_a_miss_with_source_gaps_is_unknown_history(self):
        self.assertRefused(miss(gaps=['edited record']), facts(), 'unknown_history')

    def test_an_incomplete_read_refuses(self):
        self.assertRefused(miss(), facts(complete=False), 'incomplete_read')

    def test_an_active_or_unknown_owner_gets_no_competing_helper(self):
        self.assertRefused(miss(), facts(owner='active'), 'active_owner')
        self.assertRefused(miss(), facts(owner='unknown'), 'unknown_history')

    def test_held_or_question_labels_refuse(self):
        for labels in (['ready-for-agent', 'held'], ['ready-for-agent', 'needs-info'], ['held'], []):
            with self.subTest(labels=labels):
                self.assertRefused(miss(), facts(labels=labels), 'held')

    def test_an_unknown_builder_family_refuses(self):
        # The helper must stay in the builder's family, or the reviewer family breaks.
        self.assertRefused(miss(), facts(family=None), 'unknown_history')

    def test_a_closed_or_merged_pull_request_refuses(self):
        for state in ('closed', 'merged'):
            with self.subTest(state=state):
                self.assertRefused(miss(), facts(pr_state=state), 'not_open')

    def test_red_or_pending_ci_without_a_missed_stage_has_no_timer_of_its_own(self):
        # A newer head waiting on CI, with no conflict, is the builder's: no sixth limit.
        self.assertRefused(miss(), facts(head=NEWER, ci='pending'), 'no_cause')
        self.assertRefused(miss(), facts(head=NEWER, ci='success'), 'no_cause')

    def test_unknown_ci_or_conflict_on_a_newer_head_is_unknown(self):
        self.assertRefused(miss(), facts(head=NEWER, ci='unknown'), 'unknown_history')
        self.assertRefused(miss(), facts(head=NEWER, ci='success', conflict=None), 'unknown_history')
        self.assertRefused(miss('merge'), facts(conflict=None), 'unknown_history')

    def test_a_merge_miss_whose_head_moved_is_stale(self):
        self.assertRefused(miss('merge'), facts(head=NEWER, conflict=True), 'stale_head')

    def test_another_pull_request_is_not_this_miss(self):
        self.assertRefused(miss(), facts(pull_request=9102), 'stale_binding')

    def test_malformed_rows_and_facts_raise(self):
        for row, value in ((dict(miss(), extra=1), facts()), (miss(), dict(facts(), extra=1)),
                           (miss(key='fix_after_changes:p9101:zz:c6202'), facts()),
                           (miss(), facts(complete='true')), (miss(), facts(ci='green')),
                           (miss(gaps=[1]), facts()), (miss(), facts(labels=[None])),
                           (miss(tickets=[True]), facts()), (miss(limit_minutes=30.0), facts()),
                           (dict(miss(), stage='sixth'), facts())):
            with self.assertRaises(ValueError):
                self.pick(row, value)


class Recording(unittest.TestCase):
    """The intent is recorded before dispatch; the finite pass decides; nothing executes."""

    def setUp(self):
        self.called = []
        self.generation = dict(EXAMPLES['generation'])

    def snapshot(self, intents=(), **changes):
        base = dict(copy.deepcopy(EXAMPLES['snapshot']), head=HEAD, holds=[], intents=list(intents),
                    next_sequence=1)
        return dict(base, **changes)

    def case(self, row=None, value=None, snapshot=None, claim=None, history=(), intent_id='intent-tl3-1'):
        return dict(miss=row or miss(), facts=value or facts(), rule=copy.deepcopy(DISPATCH), source=SOURCE,
                    created_at=40, intent_id=intent_id, snapshot=snapshot or self.snapshot(),
                    claim=claim, history=list(history))

    def run_pass(self, cases, generation=1, owner='primary', generations=None):
        view = dict(generations=generations or [self.generation], **{'pass': dict(generation=generation, owner=owner)})
        records = recovery.recover(view, cases, lambda *args: self.called.append(args))
        self.assertEqual(self.called, [], 'the effect boundary must never be called')
        for record in records:
            self.assertFalse(recovery.counted(record), record)
        return records

    def claim_for(self, intent, generation=1, owner='primary'):
        claim = dict(copy.deepcopy(EXAMPLES['operation']), id='claim-tl3-1', generation=generation,
                     previous_generation=generation - 1, owner=owner, intent_id=intent['id'],
                     operation_key=intent['operation_key'], subject=intent['subject'], rule=intent['rule'])
        claim['ref'] = effects.claim_ref(claim)
        return claim

    def recorded(self, **changes):
        """First pass: the proposed intent, as the ops agent records and reads it back."""
        [first] = self.run_pass([self.case(**changes)])
        self.assertEqual(first['state'], 'record_intent', first)
        return first['intent']

    def test_an_eligible_miss_first_proposes_an_intent_and_dispatches_nothing(self):
        [record] = self.run_pass([self.case()])
        self.assertEqual((record['state'], record['role'], record['result']), ('record_intent', 'findings-fix', None))
        intent = effects.read_record(json.dumps(record['intent']))
        self.assertEqual(intent['operation_key'], effects.operation_key(intent))
        self.assertEqual((intent['subject'], intent['head'], intent['prior_verdict'], intent['sequence']),
                         ({'kind': 'pull_request', 'number': 9101}, HEAD, 6202, 1))
        self.assertEqual((intent['repository'], intent['spec'], intent['ticket']), ('synthetic/ops', 9000, 9001))
        self.assertEqual(intent['rule'], DISPATCH)
        self.assertTrue(intent['assignment'].startswith('findings-fix-'))
        self.assertEqual([e['source'] for e in intent['evidence']], [SOURCE])

    def test_ci_and_conflict_intents_carry_no_prior_verdict(self):
        for value, role in ((facts(head=NEWER, ci='failure'), 'ci-fix'),
                            (facts(head=NEWER, conflict=True), 'conflict-fix')):
            with self.subTest(role=role):
                intent = self.recorded(value=value, snapshot=self.snapshot(head=NEWER))
                self.assertEqual((intent['head'], intent['prior_verdict']), (NEWER, None))
                self.assertTrue(intent['assignment'].startswith(role + '-'))

    def test_a_recorded_intent_without_its_claim_waits_for_admission(self):
        intent = self.recorded()
        [record] = self.run_pass([self.case(snapshot=self.snapshot([intent], next_sequence=2))])
        self.assertEqual((record['state'], record['intent']), ('admit_claim', intent))

    def test_a_recorded_claimed_intent_is_disabled_never_executed(self):
        intent = self.recorded()
        [record] = self.run_pass([self.case(snapshot=self.snapshot([intent]), claim=self.claim_for(intent))])
        self.assertEqual((record['state'], record['reason']), ('disabled', 'unfenced_effect'))
        self.assertEqual(record['result']['effects'], [])

    def test_the_same_miss_read_again_reuses_its_intent(self):
        intent = self.recorded()
        # A later wake: the sequence counter moved on, the miss is the same miss.
        again = self.case(snapshot=self.snapshot([intent], next_sequence=5))
        [record] = self.run_pass([again])
        self.assertEqual((record['state'], record['intent']), ('admit_claim', intent))
        # A different facts read of the same miss still names the same operation.
        proposed = self.run_pass([self.case(value=facts(labels=['ready-for-agent', 'polish']))])[0]['intent']
        self.assertEqual(proposed['operation_key'], intent['operation_key'])

    def test_duplicate_wakes_in_one_pass_admit_one_copy(self):
        intent = self.recorded()
        copy_a = self.case(snapshot=self.snapshot([intent]), claim=self.claim_for(intent))
        records = self.run_pass([copy_a, copy.deepcopy(copy_a)])
        self.assertEqual([(r['state'], r['reason']) for r in records],
                         [('disabled', 'unfenced_effect'), ('duplicate', 'record_only')])

    def test_two_proposals_for_one_miss_in_one_pass_propose_once(self):
        records = self.run_pass([self.case(), self.case(intent_id='intent-tl3-2')])
        self.assertEqual([r['state'] for r in records], ['record_intent', 'duplicate'])

    def test_a_head_change_after_recording_refuses_the_old_intent(self):
        intent = self.recorded()
        moved = self.snapshot([intent], head=NEWER)
        [record] = self.run_pass([self.case(value=facts(head=NEWER, ci='failure'), snapshot=moved,
                                            claim=self.claim_for(intent))])
        # The old findings-fix intent no longer matches the selected work: the builder moved.
        self.assertEqual(record['state'], 'record_intent')
        self.assertNotEqual(record['intent']['operation_key'], intent['operation_key'])
        # Replaying the old intent against the moved head is refused, not executed.
        [old] = self.run_pass([self.case(snapshot=moved, claim=self.claim_for(intent))])
        self.assertEqual(old['state'], 'refused', old)

    def test_a_stale_owner_after_takeover_is_refused(self):
        intent = self.recorded()
        standby = dict(self.generation, id='generation-2', generation=2, previous_generation=1, owner='standby')
        standby['ref'] = effects.claim_ref(standby)
        [record] = self.run_pass([self.case(snapshot=self.snapshot([intent]), claim=self.claim_for(intent))],
                                 generations=[self.generation, standby])
        self.assertEqual((record['state'], record['reason']), ('refused', 'stale_claim'))

    def test_uncertain_earlier_effects_reconcile_and_never_retry(self):
        intent = self.recorded()
        claim = self.claim_for(intent)
        transport = dict(copy.deepcopy(EXAMPLES['transport']), id='transport-tl3-1', intent_id=intent['id'],
                         operation_key=intent['operation_key'], subject=intent['subject'], rule=intent['rule'])
        completed = dict(copy.deepcopy(EXAMPLES['completion']), id='completion-tl3-1', intent_id=intent['id'],
                         operation_key=intent['operation_key'], subject=intent['subject'], rule=intent['rule'],
                         state='completed', result_digest='5' * 64)
        for history, snap in (([transport], self.snapshot([intent])),
                              ([completed], self.snapshot([intent])),
                              ([], self.snapshot([intent], uncertain_keys=['9' * 64]))):
            with self.subTest(history=[r['kind'] for r in history]):
                [record] = self.run_pass([self.case(snapshot=snap, claim=claim, history=history)])
                self.assertEqual((record['state'], record['reason']), ('reconcile', 'uncertain_outcome'))
                self.assertEqual(record['intent'], intent)

    def test_another_helper_recorded_at_this_head_blocks_a_second(self):
        intent = self.recorded()
        other = self.case(row=miss('merge'), value=facts(conflict=True), snapshot=self.snapshot([intent]))
        [record] = self.run_pass([other])
        self.assertEqual((record['state'], record['reason']), ('refused', 'another_helper'))

    def test_held_snapshot_or_pause_refuses(self):
        intent = self.recorded()
        for changes in (dict(holds=[9009]), dict(paused=True), dict(gates=['live gate'])):
            with self.subTest(changes=changes):
                [record] = self.run_pass([self.case(snapshot=self.snapshot([intent], **changes),
                                                    claim=self.claim_for(intent))])
                self.assertEqual((record['state'], record['reason']), ('refused', 'paused_or_revoked'))

    def test_a_refused_selection_records_no_intent(self):
        [record] = self.run_pass([self.case(value=facts(owner='active'))])
        self.assertEqual((record['state'], record['reason'], record['intent']), ('refused', 'active_owner', None))

    def test_r1_a_snapshot_or_facts_for_another_ticket_propose_nothing(self):
        # Review R1: the snapshot's ticket and approval must be the miss's ticket.
        [record] = self.run_pass([self.case(snapshot=self.snapshot(ticket=9999))])
        self.assertEqual((record['state'], record['reason'], record['intent']), ('refused', 'stale_binding', None))
        self.assertEqual(recovery.select(miss(), facts(ticket=9999))['reason'], 'stale_binding')
        [record] = self.run_pass([self.case(value=facts(ticket=9999), snapshot=self.snapshot(ticket=9999))])
        self.assertEqual((record['state'], record['reason'], record['intent']), ('refused', 'stale_binding', None))

    def test_r2_two_misses_at_one_head_propose_one_helper(self):
        # Review R2: an unrecorded proposal reserves its PR head for the rest of the pass.
        conflicted = facts(conflict=True)
        records = self.run_pass([self.case(value=conflicted), self.case(row=miss('merge'), value=conflicted,
                                                                         intent_id='intent-tl3-2')])
        self.assertEqual([(r['state'], r['reason'], r['role']) for r in records],
                         [('record_intent', 'eligible', 'findings-fix'), ('refused', 'another_helper', 'conflict-fix')])
        self.assertIsNone(records[1]['intent'])

    def test_r3_no_claim_with_unsettled_history_reconciles_instead_of_admitting(self):
        # Review R3: a lost claim read-back is never a reason to admit again.
        intent = self.recorded()
        bind = dict(intent_id=intent['id'], operation_key=intent['operation_key'], subject=intent['subject'],
                    rule=intent['rule'])
        admission = dict(copy.deepcopy(EXAMPLES['admission']), id='admission-tl3-1', state='uncertain',
                         **{k: v for k, v in bind.items() if k != 'intent_id'})
        transport = dict(copy.deepcopy(EXAMPLES['transport']), id='transport-tl3-1', **bind)
        snap = self.snapshot([intent])
        for history, changes in (([admission], {}), ([transport], {}), ([], dict(uncertain_keys=['9' * 64]))):
            with self.subTest(history=[r['kind'] for r in history], changes=changes):
                [record] = self.run_pass([self.case(snapshot=dict(snap, **changes), history=history)])
                self.assertEqual((record['state'], record['reason'], record['intent']),
                                 ('reconcile', 'uncertain_outcome', intent))
        # An admitted claim that was not read back is an incomplete read, not a second admission.
        admitted = dict(admission, state='admitted')
        [record] = self.run_pass([self.case(snapshot=snap, history=[admitted])])
        self.assertEqual((record['state'], record['reason']), ('refused', 'incomplete_read'))
        # Clear history still asks for the one admission.
        [record] = self.run_pass([self.case(snapshot=snap)])
        self.assertEqual(record['state'], 'admit_claim')
        with self.assertRaises(ValueError):
            self.run_pass([self.case(snapshot=snap, history=[dict(transport, kind='bogus')])])

    def test_r3_round2_ambiguous_or_foreign_history_never_requests_admission(self):
        # Review R3, round 2: OB3's identity and binding checks apply before admit_claim too.
        intent = self.recorded()
        snap = self.snapshot([intent])
        bind = dict(intent_id=intent['id'], operation_key=intent['operation_key'], subject=intent['subject'],
                    rule=intent['rule'])
        done = dict(copy.deepcopy(EXAMPLES['transport']), id='transport-tl3-1', state='refused', **bind)
        conflicting = dict(done, created_at=done['created_at'] + 1)
        for history in ([done, copy.deepcopy(done)], [done, conflicting], [dict(done, id=intent['id'])]):
            with self.subTest(history=[(r['id'], r['created_at']) for r in history]):
                [record] = self.run_pass([self.case(snapshot=snap, history=history)])
                self.assertEqual((record['state'], record['reason']), ('refused', 'incomplete_read'))
        for foreign in (dict(done, intent_id='intent-other'), dict(done, subject={'kind': 'issue', 'number': 9001}),
                        dict(done, approval=dict(done['approval'], revision=4))):
            with self.subTest(foreign={k: foreign[k] for k in ('intent_id', 'subject')}):
                [record] = self.run_pass([self.case(snapshot=snap, history=[foreign])])
                self.assertEqual((record['state'], record['reason']), ('refused', 'stale_binding'))
        # A settled record that does belong to this intent still allows the one admission.
        [record] = self.run_pass([self.case(snapshot=snap, history=[done])])
        self.assertEqual(record['state'], 'admit_claim')
        # One ambiguous case refuses alone: an unrelated case in the same pass still proceeds.
        records = self.run_pass([self.case(snapshot=snap, history=[done, conflicting]),
                                 self.case(value=facts(head=NEWER, conflict=True),
                                           snapshot=self.snapshot(head=NEWER), intent_id='intent-tl3-9')])
        self.assertEqual([r['state'] for r in records], ['refused', 'record_intent'])

    def test_r4_an_intent_recorded_under_another_rule_is_stale(self):
        # Review R4: reuse requires the current dispatch rule, not just the same work.
        intent = self.recorded()
        newer = dict(DISPATCH, revision='c' * 64, comment=9005)
        for claim in (None, self.claim_for(intent)):
            with self.subTest(claim=claim is not None):
                case = self.case(snapshot=self.snapshot([intent]), claim=claim)
                case['rule'] = newer
                [record] = self.run_pass([case])
                self.assertEqual((record['state'], record['reason']), ('refused', 'stale_binding'))

    def test_a_rule_other_than_dispatch_raises(self):
        bad = self.case()
        bad['rule'] = dict(DISPATCH, name='narrow-grant')
        with self.assertRaises(ValueError):
            recovery.recover(dict(generations=[self.generation], **{'pass': dict(generation=1, owner='primary')}),
                             [bad], lambda *args: self.called.append(args))
        self.assertEqual(self.called, [])


class Outcome(unittest.TestCase):
    """Only a separately verified complete result counts as a recovery."""

    def record(self, state, reason='record_only'):
        result = dict(EXAMPLES['result'], state=state, reason=reason)
        return dict(state=state, reason=reason, role='ci-fix', intent=EXAMPLES['intent'], result=result)

    def test_nothing_but_a_complete_result_counts(self):
        for state in ('recorded', 'duplicate', 'disabled', 'refused', 'reconcile', 'acknowledged',
                      'superseded', 'deferred'):
            with self.subTest(state=state):
                self.assertFalse(recovery.counted(self.record(state)))
        self.assertTrue(recovery.counted(self.record('complete', 'already_complete')))
        for state in ('record_intent', 'admit_claim'):
            self.assertFalse(recovery.counted(dict(state=state, reason='eligible', role='ci-fix',
                                                   intent=EXAMPLES['intent'], result=None)))


if __name__ == '__main__':
    unittest.main(verbosity=1)
