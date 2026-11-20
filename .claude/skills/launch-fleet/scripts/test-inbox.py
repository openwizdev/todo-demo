#!/usr/bin/env python3
"""#1481 (OB6) inbox and recheck-routing proofs. Synthetic records, virtual time, no live I/O.

python3 -I skills/launch-fleet/scripts/test-inbox.py
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
FIX = HERE.parent / 'test/ops-inbox'
OLD, NEW, NEWER = 'a' * 40, 'b' * 40, 'c' * 40
# #641: the factory's record authors, and an outsider who can comment too.
FACTORY, OUTSIDER = 'synthetic-factory[bot]', 'synthetic-outsider'
AUTHORS = frozenset({FACTORY, 'synthetic-owner'})


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


inbox = load(HERE / 'inbox.py', 'ops_inbox')
effects = load(HERE / 'effects.py', 'ops_effects_for_inbox')
EXAMPLES = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())
APPROVAL = EXAMPLES['intent']['approval']
RULE = dict(EXAMPLES['intent']['rule'], name='inbox')
CONTEXT = {'repository': 'synthetic/ops', 'spec': 9000, 'approval': APPROVAL,
           'owners': {'builder:4301': 'builder-4301', 'orchestrator:4301': 'ops-4301'}}


def evidence(source):
    return [{'evidence_class': 'fixture', 'source': source, 'digest': 'd' * 64}]


def pr_view(**changes):
    """A PR whose reviewer span started at OLD, said CHANGES at OLD; the builder pushed NEW, CI green."""
    view = {
        'repository': 'synthetic/ops', 'spec': 9000, 'ticket': 9001, 'pull_request': 9101,
        'approval': copy.deepcopy(APPROVAL), 'rule': copy.deepcopy(RULE), 'complete': True,
        'head': NEW, 'ci': {'head': NEW, 'state': 'success'}, 'authors': AUTHORS,
        'records': [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD}],
        'verdicts': [{'comment': 502, 'author': FACTORY, 'verdict': 'CHANGES', 'head': OLD}],
        'builder': 'builder-9001', 'intents': [], 'now': 1000,
    }
    view.update(changes)
    return view


class Recheck(unittest.TestCase):
    """AC1: one correctly owned recheck per new green head after a verdict."""

    def decide(self, view):
        return inbox.recheck(view)

    def test_only_the_factory_records_and_verdicts_count(self):
        """#641: an outsider's or authorless record or verdict routes nothing."""
        for who in (OUTSIDER, None):
            with self.subTest(author=who):
                verdict = [{'comment': 502, 'author': who, 'verdict': 'CHANGES', 'head': OLD}]
                self.assertEqual(self.decide(pr_view(verdicts=verdict)), ('none', 'no verdict'))
                self.assertEqual(inbox.findings(pr_view(head=OLD, verdicts=verdict)), ('none', 'no verdict'))
                start = [{'comment': 501, 'author': who, 'line': 'launch-fleet: review started ' + OLD}]
                self.assertEqual(self.decide(pr_view(records=start)), ('refused', 'ambiguous reviewer'))
        # The owner's account is a record author too, in any case; a view with no authors trusts nobody.
        owner = [{'comment': 502, 'author': 'Synthetic-Owner', 'verdict': 'CHANGES', 'head': OLD}]
        self.assertEqual(self.decide(pr_view(verdicts=owner))[0], 'record')
        self.assertEqual(self.decide(pr_view(authors=frozenset())), ('refused', 'ambiguous reviewer'))

    def test_green_head_after_changes_or_approve_records_one_recheck_to_the_span(self):
        for verdict in ('CHANGES', 'APPROVE'):
            with self.subTest(verdict=verdict):
                state, intent = self.decide(pr_view(verdicts=[{'comment': 502, 'author': FACTORY, 'verdict': verdict, 'head': OLD}]))
                self.assertEqual(state, 'record')
                effects.read_record(json.dumps(intent))  # strict schema and key identity
                self.assertEqual(
                    {k: intent[k] for k in ('action', 'destination', 'assignment', 'prior_verdict', 'head', 'sequence')},
                    dict(action='delivery', destination='reviewer', assignment='review-span-501',
                         prior_verdict=502, head=NEW, sequence=1))
                self.assertEqual(intent['subject'], {'kind': 'pull_request', 'number': 9101})
                self.assertEqual(intent['rule']['name'], 'inbox')

    def test_recorded_recheck_is_a_duplicate_and_never_multiplies(self):
        _, intent = self.decide(pr_view())
        for times in (1, 2):
            state, again = self.decide(pr_view(intents=[intent] * times, now=2000))
            self.assertEqual((state, again), ('duplicate', intent))

    def test_the_legacy_tick_record_also_counts_as_sent(self):
        records = [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD},
                   {'comment': 503, 'author': FACTORY, 'line': 'launch-fleet: re-check sent ' + NEW}]
        self.assertEqual(self.decide(pr_view(records=records)), ('none', 'recheck already sent'))

    def test_nothing_is_due_without_a_new_green_head(self):
        self.assertEqual(self.decide(pr_view(head=OLD, ci={'head': OLD, 'state': 'success'})),
                         ('none', 'head unchanged since the verdict'))
        for ci in ({'head': NEW, 'state': 'failure'}, {'head': OLD, 'state': 'success'}, None):
            self.assertEqual(self.decide(pr_view(ci=ci)), ('none', 'ci not green at the head'))
        self.assertEqual(self.decide(pr_view(verdicts=[])), ('none', 'no verdict'))

    def test_superseded_verdicts_cannot_redirect_or_add_a_recheck(self):
        # The older verdict at OLD is superseded by the newer one at NEW: nothing is due at NEW.
        verdicts = [{'comment': 502, 'author': FACTORY, 'verdict': 'CHANGES', 'head': OLD},
                    {'comment': 504, 'author': FACTORY, 'verdict': 'APPROVE', 'head': NEW}]
        self.assertEqual(self.decide(pr_view(verdicts=verdicts)), ('none', 'head unchanged since the verdict'))
        # A verdict from before a fresh reviewer's start is not that reviewer's to recheck.
        records = [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD},
                   {'comment': 503, 'author': FACTORY, 'line': 'launch-fleet: review given up ' + OLD + ': quiet'},
                   {'comment': 505, 'author': FACTORY, 'line': 'launch-fleet: review started ' + NEW}]
        self.assertEqual(self.decide(pr_view(records=records, head=NEWER, ci={'head': NEWER, 'state': 'success'})),
                         ('none', 'verdict precedes the current reviewer span'))

    def test_retired_and_ambiguous_reviewers_are_refused(self):
        retired = [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD},
                   {'comment': 503, 'author': FACTORY, 'line': 'launch-fleet: review given up ' + OLD + ': quiet'}]
        self.assertEqual(self.decide(pr_view(records=retired)), ('refused', 'reviewer retired'))
        for records in (
            [],
            [{'comment': 499, 'author': FACTORY, 'line': 'launch-fleet: re-check sent ' + OLD}],
            [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD + ', thread ' + 'thr' + '_x'}],
            [{'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD},
             {'comment': 501, 'author': FACTORY, 'line': 'launch-fleet: review started ' + OLD}],
        ):
            with self.subTest(records=records):
                self.assertEqual(self.decide(pr_view(records=records)), ('refused', 'ambiguous reviewer'))

    def test_a_stale_approval_cannot_redirect_or_be_reused(self):
        stale = dict(APPROVAL, revision=APPROVAL['revision'] - 1)
        _, old = self.decide(pr_view(approval=stale))
        state, intent = self.decide(pr_view(intents=[old]))
        self.assertEqual(state, 'record')
        self.assertNotEqual(intent['operation_key'], old['operation_key'])
        self.assertEqual((intent['approval'], intent['assignment'], intent['sequence']), (APPROVAL, 'review-span-501', 1))

    def test_incomplete_reads_decide_nothing(self):
        self.assertEqual(self.decide(pr_view(complete=False)), ('refused', 'incomplete read'))

    def test_findings_to_builder_and_recheck_to_reviewer_are_separately_keyed(self):
        view = pr_view(head=OLD, ci={'head': OLD, 'state': 'success'})
        state, findings = inbox.findings(view)
        self.assertEqual(state, 'record')
        self.assertEqual((findings['destination'], findings['assignment'], findings['prior_verdict'], findings['head']),
                         ('builder', 'builder-9001', 502, OLD))
        state, recheck = self.decide(pr_view(intents=[findings]))
        self.assertEqual(state, 'record')
        self.assertEqual((recheck['destination'], recheck['sequence']), ('reviewer', 2))
        self.assertNotEqual(recheck['operation_key'], findings['operation_key'])
        self.assertEqual(inbox.findings(pr_view(head=OLD, ci=None, intents=[findings, recheck])), ('duplicate', findings))
        self.assertEqual(inbox.findings(pr_view(verdicts=[{'comment': 502, 'author': FACTORY, 'verdict': 'APPROVE', 'head': OLD}])),
                         ('none', 'no CHANGES at the head'))


def ops(record, **changes):
    value = copy.deepcopy(record)
    value.update(changes)
    if value['kind'] == 'intent':
        value['operation_key'] = effects.operation_key(value)
    return value


def event(kind, intent, ident, **changes):
    value = copy.deepcopy(EXAMPLES[kind])
    value.update({k: copy.deepcopy(intent[k]) for k in ('repository', 'spec', 'ticket', 'subject', 'operation_key',
                                                          'approval', 'rule')},
                 id=ident, intent_id=intent['id'], created_at=intent['created_at'] + 1)
    value.update(changes)
    return value


class Inbox(unittest.TestCase):
    """AC2-AC4: GitHub-first pending items, pulled and acknowledged by the intended recipient."""

    def setUp(self):
        base = pr_view()
        _, self.one = inbox.recheck(base)
        _, self.two = inbox.message(pr_view(intents=[self.one]), 'reviewer', 'review-span-501', None, NEW,
                                    evidence('fixture:ops-inbox/contract-note'), 'note')

    def view(self, records, **changes):
        view = {'repository': 'synthetic/ops', 'spec': 9000, 'ticket': 9001, 'approval': copy.deepcopy(APPROVAL),
                'head': NEW, 'complete': True, 'cursor': {'created_at': 0, 'comment': 0},
                'read_through': {'created_at': 3000, 'comment': 777}, 'records': records, 'authors': AUTHORS,
                'verdicts': [{'comment': 502, 'author': FACTORY, 'verdict': 'CHANGES', 'head': OLD}], 'verified_acks': set()}
        view.update(changes)
        return view

    def pull(self, records, own=(), **changes):
        return inbox.pull(self.view(records, **changes), 'reviewer', 'review-span-501', set(own))

    def states(self, result):
        return [(item['intent_id'], item['state'], item['reason']) for item in result['items']]

    def test_a_dropped_push_leaves_the_item_pending_for_a_fresh_reader(self):
        refused = event('transport', self.one, 'transport-9', state='refused', receipt_digest=None)
        result = self.pull([self.one, refused])
        self.assertEqual(self.states(result), [(self.one['id'], 'recorded', 'record_only')])
        self.assertEqual((result['complete'], result['cursor'], result['next']),
                         (True, {'created_at': 3000, 'comment': 777}, 'end'))

    def test_duplicate_and_reordered_wakes_keep_one_ordered_stream(self):
        result = self.pull([self.two, self.one, self.two, self.one])
        self.assertEqual(self.states(result), [(self.one['id'], 'recorded', 'record_only'),
                                               (self.two['id'], 'deferred', 'out_of_order')])

    def test_only_the_recipients_own_checked_ack_settles_an_item(self):
        accepted = event('transport', self.one, 'transport-9', state='accepted')
        ack = inbox.acknowledge(self.view([self.one, accepted]), 'reviewer', 'review-span-501', set(),
                                self.one['id'], 'ack-9', 2500, evidence('fixture:ops-inbox/ack'), 'e' * 64)
        effects.read_record(json.dumps(ack))
        self.assertEqual((ack['operation_key'], ack['recipient'], ack['assignment'], ack['sequence'], ack['checked_head']),
                         (self.one['operation_key'], 'reviewer', 'review-span-501', 1, NEW))
        # Accepted transport alone, or the same ack posted by another agent on the shared account, settles nothing.
        self.assertEqual(self.states(self.pull([self.one, accepted]))[0][1], 'recorded')
        self.assertEqual(self.states(self.pull([self.one, accepted, ack]))[0][1], 'recorded')
        result = self.pull([self.one, self.two, accepted, ack], own={'ack-9'})
        self.assertEqual(self.states(result), [(self.one['id'], 'acknowledged', 'record_only'),
                                               (self.two['id'], 'recorded', 'record_only')])

    def test_an_ack_cannot_skip_ahead_or_settle_a_superseded_item(self):
        with self.assertRaises(ValueError):
            inbox.acknowledge(self.view([self.one, self.two]), 'reviewer', 'review-span-501', set(),
                              self.two['id'], 'ack-9', 2500, evidence('fixture:ops-inbox/ack'), 'e' * 64)
        with self.assertRaises(ValueError):
            inbox.acknowledge(self.view([self.one], head=NEWER), 'reviewer', 'review-span-501', set(),
                              self.one['id'], 'ack-9', 2500, evidence('fixture:ops-inbox/ack'), 'e' * 64)

    def test_superseded_heads_and_decisions_are_ignored_but_uncertainty_stays_visible(self):
        self.assertEqual(self.states(self.pull([self.one], head=NEWER)),
                         [(self.one['id'], 'superseded', 'superseded')])
        done = event('completion', self.one, 'completion-9', state='superseded', superseded_by='f' * 64)
        self.assertEqual(self.states(self.pull([self.one, self.two, done])),
                         [(self.one['id'], 'superseded', 'superseded'), (self.two['id'], 'recorded', 'record_only')])
        unsure = event('transport', self.one, 'transport-9', state='uncertain', receipt_digest=None)
        self.assertEqual(self.states(self.pull([self.one, unsure], head=NEWER)),
                         [(self.one['id'], 'reconcile', 'uncertain_outcome')])

    def test_failed_or_partial_reads_keep_the_cursor_and_decide_nothing(self):
        start = {'created_at': 5, 'comment': 6}
        result = self.pull([self.one], complete=False, cursor=start)
        self.assertEqual((result['complete'], result['cursor'], result['items'], result['next']),
                         (False, start, [], 'end'))
        gap = ops(self.two, sequence=3)
        gap['id'] = 'note-gap'
        gap['operation_key'] = effects.operation_key(gap)
        result = self.pull([self.one, gap], cursor=start)
        self.assertEqual((result['complete'], result['cursor'], result['items']), (False, start, []))

    def test_conflicting_identities_and_sequences_refuse(self):
        forged = ops(self.one, head=NEWER)
        for records in ([self.one, forged], [self.one, ops(self.two, sequence=1, id='note-2')]):
            with self.subTest(records=len(records)):
                result = self.pull(records, cursor={'created_at': 1, 'comment': 1})
                self.assertEqual((result['complete'], result['items']), (False, []))

    def test_each_wake_ends_and_only_an_independent_pull_counts_toward_recovery(self):
        wake = inbox.wake(self.view([self.one]), 'reviewer', 'review-span-501', set(), 'independent')
        self.assertEqual((wake['next'], wake['source'], wake['due']), ('end', 'independent', [self.one['id']]))
        self.assertEqual(inbox.recovery([]), 'unverified')
        self.assertEqual(inbox.recovery([dict(wake, source='pc')]), 'unverified')
        idle = inbox.wake(self.view([]), 'reviewer', 'review-span-501', set(), 'independent')
        self.assertEqual(inbox.recovery([idle]), 'unverified')
        self.assertEqual(inbox.recovery([wake]), 'pull usable (synthetic)')
        partial = inbox.wake(self.view([self.one], complete=False), 'reviewer', 'review-span-501', set(), 'independent')
        self.assertEqual(inbox.recovery([partial]), 'unverified')


    def test_r1_records_bound_to_another_repository_spec_or_ticket_refuse_the_read(self):
        start = {'created_at': 4, 'comment': 4}
        for change in (dict(spec=9002), dict(repository='synthetic/other'), dict(ticket=9009)):
            with self.subTest(change=change):
                result = self.pull([ops(self.one, **change)], cursor=start)
                self.assertEqual((result['complete'], result['cursor'], result['items']), (False, start, []))
                with self.assertRaises(ValueError):
                    inbox.acknowledge(self.view([ops(self.one, **change)]), 'reviewer', 'review-span-501', set(),
                                      self.one['id'], 'ack-9', 2500, evidence('fixture:ops-inbox/ack'), 'e' * 64)

    def test_r2_a_newer_verdict_supersedes_the_older_verdict_item(self):
        verdicts = [{'comment': 502, 'author': FACTORY, 'verdict': 'CHANGES', 'head': OLD}, {'comment': 504, 'author': FACTORY, 'verdict': 'CHANGES', 'head': OLD}]
        _, newer = inbox.recheck(pr_view(intents=[self.one], verdicts=verdicts))
        self.assertEqual(self.states(self.pull([self.one, newer], verdicts=verdicts)),
                         [(self.one['id'], 'superseded', 'superseded'), (newer['id'], 'recorded', 'record_only')])
        unsure = event('transport', self.one, 'transport-9', state='uncertain', receipt_digest=None)
        self.assertEqual(self.states(self.pull([self.one, newer, unsure], verdicts=verdicts)),
                         [(self.one['id'], 'reconcile', 'uncertain_outcome'), (newer['id'], 'deferred', 'out_of_order')])

    def test_r3_an_unresolved_earlier_item_for_another_recipient_defers_this_one(self):
        first = ops(self.one, destination='orchestrator', assignment='ops-owner')
        self.assertEqual(self.states(self.pull([first, self.two])), [(self.two['id'], 'deferred', 'out_of_order')])
        # Its settlement counts only when that recipient's own ack was verified independently.
        theirs = event('ack', first, 'ack-7', recipient='orchestrator', assignment='ops-owner', sequence=1,
                       checked_head=NEW)
        self.assertEqual(self.states(self.pull([first, self.two, theirs])), [(self.two['id'], 'deferred', 'out_of_order')])
        self.assertEqual(self.states(self.pull([first, self.two, theirs], verified_acks={'ack-7'})),
                         [(self.two['id'], 'recorded', 'record_only')])


class Measures(unittest.TestCase):
    """AC6: eligible recheck delay and oldest pending age, with denominators and held time excluded."""

    def test_delays_and_ages_exclude_held_time_and_keep_denominators(self):
        _, one = inbox.recheck(pr_view(now=1000 * 60))
        ack = event('ack', one, 'ack-1', recipient='reviewer', assignment='review-span-501', sequence=1,
                    checked_head=NEW, created_at=1000 * 60 * 11)
        view = pr_view(head=NEWER, intents=[one])
        _, two = inbox.message(view, 'reviewer', 'review-span-501', 502, NEWER,
                               evidence('fixture:ops-inbox/second'), 'recheck', created_at=1000 * 60 * 20)
        result = inbox.measure(
            records=[one, ack, two], own={'ack-1'}, now=1000 * 60 * 40,
            eligible={NEW: 1000 * 60 * 1, NEWER: 1000 * 60 * 20}, held=[[1000 * 60 * 3, 1000 * 60 * 5]])
        self.assertEqual(result['recheck_delay'], {'eligible': 2, 'measured': 1, 'open': 1, 'unknown': 0,
                                                   'minutes': [8.0]})
        self.assertEqual(result['pending'], {'count': 1, 'oldest_minutes': 20.0})
        unknown = inbox.measure(records=[one], own=set(), now=1000 * 60 * 40, eligible={}, held=[])
        self.assertEqual(unknown['recheck_delay'], {'eligible': 1, 'measured': 0, 'open': 0, 'unknown': 1,
                                                    'minutes': []})


    def test_r5_only_a_bound_own_ack_or_a_settling_completion_settles(self):
        _, one = inbox.recheck(pr_view(now=60000))
        wrong = event('ack', one, 'ack-1', recipient='builder', assignment='review-span-501', sequence=1,
                      checked_head=NEW, created_at=600000)
        result = inbox.measure(records=[one, wrong], own={'ack-1'}, now=1200000, eligible={NEW: 60000}, held=[])
        self.assertEqual((result['recheck_delay']['measured'], result['recheck_delay']['open'], result['pending']['count']),
                         (0, 1, 1))
        for state in ('uncertain', 'refused', 'disabled', 'reconciled_not_executed'):
            with self.subTest(state=state):
                done = event('completion', one, 'completion-1', state=state)
                self.assertEqual(inbox.measure(records=[one, done], own=set(), now=1200000, eligible={},
                                               held=[])['pending']['count'], 1)
        done = event('completion', one, 'completion-1', state='completed', result_digest='9' * 64)
        self.assertEqual(inbox.measure(records=[one, done], own=set(), now=1200000, eligible={}, held=[])['pending'],
                         {'count': 0, 'oldest_minutes': None})

    def test_r7_overlapping_holds_are_subtracted_once_and_bad_holds_refuse(self):
        _, one = inbox.recheck(pr_view(now=0))
        result = inbox.measure(records=[one], own=set(), now=600000, eligible={}, held=[[0, 480000], [120000, 600000]])
        self.assertEqual(result['pending']['oldest_minutes'], 0.0)
        with self.assertRaises(ValueError):
            inbox.measure(records=[one], own=set(), now=600000, eligible={}, held=[[300000, 100000]])


class Limits(unittest.TestCase):
    """AC7: missed fix/answer goals route through the existing durable items; delivery is not completion."""

    def setUp(self):
        self.bench = json.loads((HERE.parent / 'test/ops-inbox/stage-waits-bench.json').read_text())
        self.settings = FIX / 'limits.conf'

    def test_missed_fix_and_answer_route_to_existing_roles_without_claiming_completion(self):
        fix = self.bench['waits'][[w['stage'] for w in self.bench['waits']].index('fix_after_changes')]
        opened = dict(copy.deepcopy(fix), key=fix['key'].replace('c6202', 'c6203'), end=None, support=[])
        self.bench['waits'].append(opened)
        findings = ops(EXAMPLES['intent'], id='findings-6202', subject={'kind': 'pull_request', 'number': 4401},
                       action='delivery', destination='builder', assignment='builder-4301', prior_verdict=6202,
                       head='1a' * 20, ticket=4301)
        due = inbox.due(self.settings, self.bench, [findings], decisions={6102}, context=CONTEXT)
        rows = {row['key']: row for row in due}
        self.assertEqual(set(rows), {'fix_after_changes:p4401:' + '1a' * 20 + ':c6202',
                                     'fix_after_changes:p4401:' + '1a' * 20 + ':c6203',
                                     'builder_question_answer:t4301:c6102'})
        ended = rows['fix_after_changes:p4401:' + '1a' * 20 + ':c6202']
        self.assertEqual((ended['route'], ended['operation_key'], ended['done']),
                         ('builder', findings['operation_key'], 'evidenced end s13'))
        still = rows['fix_after_changes:p4401:' + '1a' * 20 + ':c6203']
        self.assertEqual((still['route'], still['operation_key'], still['done']), ('builder', None, None))
        self.assertEqual(still['gap'], 'no durable findings item: record one before routing')
        question = rows['builder_question_answer:t4301:c6102']
        self.assertEqual((question['route'], question['exception'], question['done']),
                         ('orchestrator', 'needs a new decision from Jake', 'evidenced end s4'))

    def test_r6_only_a_current_bound_delivery_item_counts_as_the_durable_route(self):
        key = 'fix_after_changes:p4401:' + '1a' * 20 + ':c6202'
        good = ops(EXAMPLES['intent'], id='findings-6202', subject={'kind': 'pull_request', 'number': 4401},
                   action='delivery', destination='builder', assignment='builder-4301', prior_verdict=6202,
                   head='1a' * 20, ticket=4301)
        for change in (dict(action='merge'), dict(ticket=4302), dict(repository='synthetic/other'), dict(spec=9002),
                       dict(approval=dict(APPROVAL, revision=1)), dict(assignment='builder-other')):
            with self.subTest(change=change):
                rows = {r['key']: r for r in inbox.due(self.settings, self.bench, [ops(good, **change)],
                                                        decisions=set(), context=CONTEXT)}
                self.assertEqual((rows[key]['operation_key'], rows[key]['gap']),
                                 (None, 'no durable findings item: record one before routing'))
        question = ops(EXAMPLES['intent'], id='answer-6102', subject={'kind': 'issue', 'number': 4301}, ticket=4301,
                       action='delivery', destination='orchestrator', assignment='ops-4301', prior_verdict=6102, head=None)
        q = 'builder_question_answer:t4301:c6102'
        rows = {r['key']: r for r in inbox.due(self.settings, self.bench, [question], decisions=set(), context=CONTEXT)}
        self.assertEqual((rows[q]['operation_key'], rows[q]['gap']), (question['operation_key'], None))
        other = ops(question, ticket=4302, subject={'kind': 'issue', 'number': 4302})
        rows = {r['key']: r for r in inbox.due(self.settings, self.bench, [other], decisions=set(), context=CONTEXT)}
        self.assertEqual((rows[q]['operation_key'], rows[q]['gap']), (None, 'no durable answer item: record one before routing'))

    def test_settings_must_load_and_match_the_bench(self):
        with self.assertRaises(ValueError):
            inbox.due(FIX / 'limits-bad.conf', self.bench, [], decisions=set(), context=CONTEXT)
        changed = copy.deepcopy(self.bench)
        changed['settings']['minutes']['fix_after_changes'] = 31
        with self.assertRaises(ValueError):
            inbox.due(self.settings, changed, [], decisions=set(), context=CONTEXT)
        self.bench['authority'] = 'merge'
        with self.assertRaises(ValueError):
            inbox.due(self.settings, self.bench, [], decisions=set(), context=CONTEXT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
