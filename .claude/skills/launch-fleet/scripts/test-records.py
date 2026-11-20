#!/usr/bin/env python3
"""P4: public templates and fleet decisions, on synthetic process boundaries."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SHA = '31' * 20
NEW = ('31f' * 14)[:40]
THREAD = 'thr_synreviewer'


class PublicRecords(unittest.TestCase):
    def test_record_table_uses_the_contract_public_forms_word_for_word(self):
        contract = (ROOT / 'contracts/open-development.v1.md').read_text()
        section = contract.split('## Fleet records\n')[1].split('\n**Finding')[0]
        forms = re.findall(r'^\| `[^`]+` \| `([^`]+)` \|$', section, re.M)
        self.assertEqual(len(forms), 9)
        table = (HERE.parent / 'SKILL.md').read_text().split('## Records\n')[1].split('\n## ')[0]
        for form in forms:
            with self.subTest(form=form):
                # Continuation alternatives in the skill repeat the common prefix implicitly.
                self.assertIn('`' + form.removeprefix('launch-fleet: ') + '`', table.replace('`launch-fleet: ', '`'))
        self.assertNotRegex(table, r', thread <|fleet thread <id>|old builder archived, thread')


class Fleet(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.world = json.loads((HERE / 'fixtures/check.json').read_text())
        self.world['private'] = False
        self.world['repo'] = 'example/public'
        for issue in self.world['issues']:
            issue['comments'] = [c for c in issue['comments'] if issue['number'] == 10]
        ticket = self.issue(12)
        ticket['comments'] = [dict(id=1201, at='2026-11-01T09:40:00Z',
            body='launch-fleet: start checked, branch room/12-synthetic')]
        self.world['pulls'].append(dict(number=31, state='OPEN', draft=False, base='main', head=SHA,
            committed='2026-11-01T10:30:00Z', headline='#12: green', closes=[12], rollup='SUCCESS',
            checks=[dict(name=n, status='COMPLETED', conclusion='SUCCESS', run='2026-11-01T11:00:00Z') for n in ['build','test']],
            mergedAt=None, updatedAt='2026-11-01T11:00:00Z', comments=[], files=[]))
        self.pr = self.world['pulls'][-1]
        self.threads = [dict(id='thr_synbuilder', title='#12: Synthetic', branch='room/12-synthetic', archivedAt=None),
                        dict(id=THREAD, title='Review #31 at ' + SHA[:8], branch=None, archivedAt=None)]
        (self.dir / 'bin').mkdir()
        for name, source in [('gh', HERE / 'fixtures/gh.py'), ('room-cli', HERE / 'fixtures/room.py')]:
            (self.dir / 'bin' / name).write_text('#!/bin/sh\nexec ' + sys.executable + ' -I -S ' + str(source) + ' "$@"\n')
            (self.dir / 'bin' / name).chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
            GH_REPO=self.world['repo'], FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'),
            LAUNCH_FLEET_NOW='1793534400', LAUNCH_FLEET_CACHE=str(self.dir / 'cache'),
            LAUNCH_FLEET_REVISION=str(HERE / 'fixtures/revision.sh'), FLEET_THREADS=str(self.dir / 'threads.json'))

    def issue(self, n):
        return next(i for i in self.world['issues'] if i['number'] == n)

    def say(self, body, n=3101, at='11:10'):
        self.pr['comments'].append(dict(id=n, at='2026-11-01T' + at + ':00Z', body='launch-fleet: ' + body))

    def run_fleet(self, *args):
        (self.dir / 'world.json').write_text(json.dumps(self.world))
        (self.dir / 'threads.json').write_text(json.dumps(self.threads))
        r = subprocess.run(['sh', os.environ.get('FLEET_SH', str(HERE / 'fleet.sh')), *args], env=self.env, cwd=self.dir, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_builder_with_a_driver_run_is_told_through_its_driver(self):
        # #1371: a builder host.py started has no CloudRoom thread; its saved run is its identity.
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        self.threads = self.threads[1:]
        runs = self.dir / 'runs.json'
        self.env['LAUNCH_FLEET_RUNS'] = str(runs)
        runs.write_text(json.dumps({'repo': 'example/public', 'runs': {'12': {'host': 'local', 'run': 'run-0a1b'}}}))
        self.assertEqual(self.run_fleet('wake', '12'), f'CI failed #31 for #12 at {SHA}: tell its builder, thread run:12\n')
        runs.write_text(json.dumps({'repo': 'example/other', 'runs': {}}))  # not this repository's: trust no run
        self.assertEqual(self.run_fleet('wake', '12'), 'look #12: the private runs file is unreadable\n')
        # R2: a wake that did not restore the private run map says so, rather than a bare thread miss.
        runs.unlink()
        self.assertEqual(self.run_fleet('wake', '12'), 'look #12: the private run map LAUNCH_FLEET_RUNS was not '
                                                       'restored from the private state\n')
        del self.env['LAUNCH_FLEET_RUNS']
        self.assertEqual(self.run_fleet('wake', '12'), 'look #12: no thread matches builder:12, and no private run '
                                                       'map LAUNCH_FLEET_RUNS was restored\n')

    def test_builder_found_by_title_and_checked_branch(self):
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        self.assertEqual(self.run_fleet('wake', '12'), f'CI failed #31 for #12 at {SHA}: tell its builder, thread thr_synbuilder\n')

    def test_recheck_finds_original_reviewer(self):
        for private, suffix in [(False, ''), (True, ''),
                                (True, '\nSynthetic note'), (True, ' (synthetic note)')]:
            with self.subTest(private=private, suffix=suffix):
                self.world.update(private=private, repo='example/private' if private else 'example/public')
                self.env['GH_REPO'] = self.world['repo']
                self.env['LAUNCH_FLEET_NOW'] = '1793534400'
                self.pr['comments'] = []
                self.say('review started ' + SHA + (', thread ' + THREAD if private else '') + suffix)
                self.pr['head'] = NEW
                self.assertEqual(self.run_fleet('wake', '12'),
                    f're-check #31 for #12 at {NEW}: tell its reviewer, thread {THREAD}\n')
                self.say('re-check sent ' + NEW, 3102, '11:59')
                self.assertEqual(self.run_fleet('wake', '12'), '')
                self.env['LAUNCH_FLEET_NOW'] = '1793536200'
                self.assertEqual(self.run_fleet('wake', '12'),
                    f'check review #31 for #12 at {NEW}: no verdict 30 minutes after '
                    f'"re-check sent {NEW}"; read thread {THREAD} and tell it again (its record: comment 3102)\n')

    def test_quiet_reviewer_then_told_again(self):
        self.say('review started ' + SHA)
        out = self.run_fleet('wake', '12')
        self.assertIn('read thread ' + THREAD + ' and tell it again', out)
        self.say('review told again ' + SHA, 3102, '11:20')
        self.assertIn('archive thread ' + THREAD + ' and record review given up', self.run_fleet('wake', '12'))

    def test_given_up_at_later_commit_closes_whole_span(self):
        for private in [False, True]:
            with self.subTest(private=private):
                self.pr['comments'] = []
                self.say('review started ' + SHA)
                self.say('review given up ' + NEW + ': no verdict', 3102, '11:20')
                self.say('review told again ' + NEW, 3103, '11:30')
                self.pr['head'] = NEW
                if private:
                    path = self.dir / 'state.json'
                    path.write_text(json.dumps({'repo': self.world['repo'], 'threads': {f'review:31:{SHA}': THREAD, f'review:31:{NEW}': THREAD}}))
                    self.env['LAUNCH_FLEET_STATE'] = str(path)
                out = self.run_fleet('wake', '12')
                self.assertIn('a fresh reviewer', out)
                self.assertNotIn(THREAD, out)

    def test_edited_give_up_keeps_retired_identity_for_closure_only(self):
        # The start claim can be edited at B after starting at A. A replacement
        # may also start at B, overwriting the commit alias but never the claim.
        for replacement in (SHA, NEW):
            for discovery in (True, False):
                with self.subTest(replacement=replacement, discovery=discovery):
                    self.pr['comments'] = []
                    self.pr.update(state='OPEN', mergedAt=None, head=replacement)
                    self.issue(12)['state'] = 'OPEN'
                    self.say('review given up ' + replacement + ': archive failed')
                    self.say('review told again ' + replacement, 3102, '11:20')
                    self.say('review started ' + replacement, 3103, '11:30')
                    fresh = 'thr_synfresh'
                    self.threads = [dict(id='thr_synbuilder', title='#12: Synthetic', branch='room/12-synthetic', archivedAt=None),
                        dict(id=THREAD, title='Review #31 at ' + SHA[:8], branch=None, archivedAt=None),
                        dict(id=fresh, title='Review #31 at ' + replacement[:8], branch=None, archivedAt=None)] if discovery else []
                    path = self.dir / 'private.json'
                    path.write_text(json.dumps({'repo': self.world['repo'], 'threads': {
                        'builder:12': 'thr_synbuilder',
                        'review:31:claim:3101': THREAD,
                        'review:31:claim:3103': fresh,
                        'review:31:' + replacement: fresh}}))
                    self.env['LAUNCH_FLEET_STATE'] = str(path)
                    active = self.run_fleet('wake', '12')
                    self.assertNotIn(THREAD, active)
                    self.pr['head'] = '42' * 20
                    self.assertEqual(self.run_fleet('wake', '12'),
                        f're-check #31 for #12 at {"42" * 20}: tell its reviewer, thread {fresh}\n')
                    self.issue(12)['state'] = 'CLOSED'
                    self.pr.update(state='MERGED', mergedAt='2026-11-01T11:58:00Z')
                    self.assertEqual(self.run_fleet('wake', '12'),
                        f'archive #12: closed; archive thr_synbuilder, {fresh}, {THREAD}\n')

    def test_replacement_edited_to_given_up_keeps_its_own_archive_identity(self):
        self.say('review started ' + SHA)
        self.say('review given up ' + SHA + ': archive failed', 3102, '11:15')
        self.say('review given up ' + SHA + ': replacement archive failed', 3103, '11:20')
        self.say('review told again ' + SHA, 3104, '11:25')
        self.say('review started ' + SHA, 3105, '11:30')
        second, fresh = 'thr_synsecond', 'thr_synfresh'
        self.threads.extend(dict(id=t, title='Review #31 at ' + SHA[:8], branch=None, archivedAt=None)
                            for t in (second, fresh))
        path = self.dir / 'private.json'
        path.write_text(json.dumps({'repo': self.world['repo'], 'threads': {
            'review:31:claim:3101': THREAD, 'review:31:claim:3103': second,
            'review:31:claim:3105': fresh, 'review:31:' + SHA: fresh}}))
        self.env['LAUNCH_FLEET_STATE'] = str(path)
        self.pr['head'] = NEW
        self.assertEqual(self.run_fleet('wake', '12'),
            f're-check #31 for #12 at {NEW}: tell its reviewer, thread {fresh}\n')
        self.issue(12)['state'] = 'CLOSED'
        self.pr.update(state='MERGED', mergedAt='2026-11-01T11:58:00Z')
        self.assertEqual(self.run_fleet('wake', '12'),
            f'archive #12: closed; archive thr_synbuilder, {fresh}, {THREAD}, {second}\n')

    def test_edited_give_up_can_archive_from_older_commit_map(self):
        self.issue(12)['state'] = 'CLOSED'
        self.pr.update(state='MERGED', mergedAt='2026-11-01T11:58:00Z', head=NEW)
        self.say('review given up ' + SHA + ': archive failed')
        self.say('review started ' + NEW, 3102, '11:20')
        fresh = 'thr_synfresh'
        self.threads.append(dict(id=fresh, title='Review #31 at ' + NEW[:8], branch=None, archivedAt=None))
        path = self.dir / 'private.json'
        path.write_text(json.dumps({'repo': self.world['repo'], 'threads': {
            'review:31:' + SHA: THREAD, 'review:31:' + NEW: fresh}}))
        self.env['LAUNCH_FLEET_STATE'] = str(path)
        self.assertEqual(self.run_fleet('wake', '12'),
            f'archive #12: closed; archive thr_synbuilder, {fresh}, {THREAD}\n')

    def test_ambiguous_builder_becomes_thread_free_look(self):
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        self.threads.append(dict(self.threads[0], id='thr_synduplicate'))
        out = self.run_fleet('wake', '12')
        self.assertIn('look #12:', out)
        self.assertNotRegex(out, r'\bthr_[A-Za-z0-9]')
        self.assertNotIn('tell its builder', out)

    def test_private_map_and_discovery_disagreement_is_a_look(self):
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        path = self.dir / 'state.json'
        path.write_text(json.dumps({'repo': self.world['repo'], 'threads': {'builder:12': 'thr_synother'}}))
        self.env['LAUNCH_FLEET_STATE'] = str(path)
        out = self.run_fleet('wake', '12')
        self.assertIn('look #12: private state and CloudRoom disagree', out)
        self.assertNotRegex(out, r'\bthr_[A-Za-z0-9]')

    def test_helper_titles_and_wrong_branches_are_not_builder_matches(self):
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        self.threads[0]['title'] = '#12 helper scout'
        out = self.run_fleet('wake', '12')
        self.assertIn('look #12: no thread matches builder:12', out)
        self.threads[0]['title'] = '#12: Builder'
        self.threads[0]['branch'] = 'room/12-wrong'
        self.assertIn('look #12: no thread matches builder:12', self.run_fleet('wake', '12'))

    def test_public_repo_refuses_legacy_record(self):
        self.issue(12)['comments'][0]['body'] = 'launch-fleet: started, thread thr_synbuilder'
        self.pr['checks'][0]['conclusion'] = 'FAILURE'
        out = self.run_fleet('wake', '12')
        self.assertIn('look #12: legacy thread record is not accepted in public', out)
        self.assertNotRegex(out, r'\bthr_[A-Za-z0-9]')

    def test_public_nightly_claim_is_reconciled_without_repeating_delivery(self):
        self.world['runs'] = [dict(id=801, run_attempt=1, head_sha='81' * 20, head_branch='main', path='.github/workflows/ci.yml', event='schedule', status='completed', conclusion='failure')]
        self.world['commitComments'] = [dict(id=9001, commit_id='81' * 20, body='launch-fleet: nightly telling 801 attempt 1')]
        out = self.run_fleet('check')
        self.assertIn('; reconcile comment 9001; sender in private state', out)
        self.world['commitComments'].append(dict(id=9002, commit_id='81' * 20, body='launch-fleet: nightly uncertain 801 attempt 1'))
        self.assertNotIn('nightly red', self.run_fleet('check'))

    def test_public_resume_claim_wins_once(self):
        self.issue(12)['comments'] += [dict(id=1202, at='2026-11-01T11:00:00Z', body='launch-fleet: waiting for #11'),
            dict(id=1203, at='2026-11-01T11:59:00Z', body='launch-fleet: resume starting 1202 for #11')]
        self.assertEqual(self.run_fleet('claim', '12', '1203'), 'go #12\n')


def load(path, name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpsPass(unittest.TestCase):
    """#1456: finite primary/standby passes on the real record reader and OB3 boundary."""
    ACTIONS = ('builder_start', 'review_start', 'delivery', 'hold_release', 'merge')

    @classmethod
    def setUpClass(cls):
        cls.records = load(HERE / 'records.py', 'fleet_records')
        cls.effects = load(HERE / 'effects.py', 'fleet_effects')
        cls.examples = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())

    def setUp(self):
        self.refs = {}       # the synthetic create-if-absent reference store
        self.called = []     # the effect boundary must never be called
        self.generations = [self.generation(1, 'primary')]

    def generation(self, n, owner):
        claim = dict(self.examples['generation'], id=f'generation-{n}', generation=n,
                     previous_generation=n - 1, owner=owner)
        claim['ref'] = self.effects.claim_ref(claim)
        return claim

    def snapshot(self, generation, owner, intents=()):
        snapshot = dict(self.examples['snapshot'], generation=generation, owner=owner, holds=[],
                        intents=list(intents))
        return snapshot

    def operation(self, action, generation, owner, sequence=1, ticket=None):
        intent = dict(self.examples['intent'], id=f'intent-{action.replace("_", "-")}', action=action,
                      sequence=sequence)
        if ticket:
            intent['ticket'] = ticket
        intent['operation_key'] = self.effects.operation_key(intent)
        claim = dict(self.examples['operation'], id=f'claim-{action.replace("_", "-")}-g{generation}',
                     generation=generation, previous_generation=generation - 1, owner=owner,
                     intent_id=intent['id'], operation_key=intent['operation_key'], ticket=intent['ticket'])
        claim['ref'] = self.effects.claim_ref(claim)
        return dict(intent=intent, claim=claim, history=[], snapshot=self.snapshot(generation, owner, [intent]))

    def create(self, ref, commit):
        if ref in self.refs:
            return 'exists'
        self.refs[ref] = commit
        return 'created'

    def run_pass(self, generation, owner, operations):
        view = {'pass': {'generation': generation, 'owner': owner},
                'generations': self.generations, 'operations': operations}
        return self.records.ops_pass(view, lambda *args: self.called.append(args))

    def states(self, results):
        return [(r['state'], r['reason']) for r in results]

    def take_over(self):
        # The standby admits generation 2 through OB3's one record-storage attempt.
        claim = self.generation(2, 'standby')
        snapshot = self.snapshot(1, 'primary')
        self.assertEqual(self.effects.admit_claim(claim, snapshot, 'e' * 40, self.create), 'admitted')
        rival = dict(claim, id='generation-2-rival', owner='primary')
        self.assertEqual(self.effects.admit_claim(rival, snapshot, 'f' * 40, self.create), 'duplicate')
        self.generations.append(claim)

    def test_takeover_fences_the_old_generation_before_every_effect(self):
        primary = [self.operation(a, 1, 'primary') for a in self.ACTIONS]
        self.assertEqual(self.states(self.run_pass(1, 'primary', primary)), [('disabled', 'unfenced_effect')] * 5)
        self.take_over()
        # The old primary resumes after the takeover: refused before any effect,
        # release and merge paths included.
        self.assertEqual(self.states(self.run_pass(1, 'primary', primary)), [('refused', 'stale_claim')] * 5)
        standby = [self.operation(a, 2, 'standby') for a in self.ACTIONS]
        self.assertEqual(self.states(self.run_pass(2, 'standby', standby)), [('disabled', 'unfenced_effect')] * 5)
        # A pass claiming the current number under another owner is stale too.
        self.assertEqual(self.states(self.run_pass(2, 'primary', standby)), [('refused', 'stale_claim')] * 5)
        # A snapshot read before the takeover cannot carry the new owner's work.
        stale_read = self.operation('builder_start', 2, 'standby')
        stale_read['snapshot'] = dict(stale_read['snapshot'], generation=1, owner='primary')
        self.assertEqual(self.states(self.run_pass(2, 'standby', [stale_read])), [('refused', 'stale_claim')])
        self.assertEqual(self.called, [])

    def test_project_and_spec_paths_cannot_both_dispatch_one_operation(self):
        project = self.operation('review_start', 1, 'primary')
        spec = self.operation('review_start', 1, 'primary')
        self.assertEqual(project['intent']['operation_key'], spec['intent']['operation_key'])
        results = self.run_pass(1, 'primary', [project, spec])
        self.assertEqual(self.states(results), [('disabled', 'unfenced_effect'), ('duplicate', 'record_only')])
        self.assertEqual(len({r['operation_key'] for r in results}), 1)
        # Across passes, both paths name one claim ref: the second admission is a duplicate.
        self.assertEqual(project['claim']['ref'], spec['claim']['ref'])
        for path, want in ((project, 'admitted'), (spec, 'duplicate')):
            admit = self.effects.admit_claim(path['claim'], path['snapshot'], 'e' * 40, self.create)
            self.assertEqual(admit, want)
        self.assertEqual(self.called, [])

    def test_takeover_keeps_intentional_stops_and_uncertain_starts(self):
        self.take_over()
        paused = self.operation('builder_start', 2, 'standby')
        paused['snapshot']['paused'] = True
        uncertain = self.operation('builder_start', 2, 'standby', ticket=9002)
        uncertain['snapshot'] = dict(uncertain['snapshot'], ticket=9002)
        # The old primary's start was accepted by transport but never completed.
        transport = dict(self.examples['transport'], intent_id=uncertain['intent']['id'], ticket=9002,
                         operation_key=uncertain['intent']['operation_key'], state='accepted', generation=1)
        uncertain['history'] = [transport]
        self.assertEqual(self.states(self.run_pass(2, 'standby', [paused, uncertain])),
                         [('refused', 'paused_or_revoked'), ('reconcile', 'uncertain_outcome')])
        self.assertEqual(self.called, [])

    def test_failed_operation_does_not_block_unrelated_due_work(self):
        broken = self.operation('delivery', 1, 'primary', ticket=9002)
        broken['intent'] = dict(broken['intent'], sequence=0)
        later = self.operation('review_start', 1, 'primary')
        results = self.run_pass(1, 'primary', [broken, later])
        self.assertEqual(self.states(results), [('refused', 'incomplete_read'), ('disabled', 'unfenced_effect')])

    def test_incomplete_or_forked_generation_history_selects_no_owner(self):
        for history in ([self.generation(1, 'primary'), self.generation(3, 'standby')],
                        [self.generation(1, 'primary'), self.generation(1, 'standby')],
                        [dict(self.generation(1, 'primary'), scope='operation')]):
            with self.subTest(history=[(c['generation'], c['owner']) for c in history]):
                self.generations = history
                with self.assertRaises(ValueError):
                    self.run_pass(1, 'primary', [self.operation('builder_start', 1, 'primary')])
        self.generations = []
        self.assertEqual(self.states(self.run_pass(0, None, [self.operation('builder_start', 1, 'primary')])),
                         [('refused', 'stale_claim')])

    def test_r5_owner_from_another_fleet_is_foreign(self):
        for field, value in (('spec', 9999), ('repository', 'synthetic/other')):
            with self.subTest(field=field):
                foreign = dict(self.generation(1, 'primary'), **{field: value})
                foreign['ref'] = self.effects.claim_ref(foreign)
                self.generations = [foreign]
                results = self.run_pass(1, 'primary', [self.operation(a, 1, 'primary') for a in self.ACTIONS])
                self.assertEqual(self.states(results), [('refused', 'stale_claim')] * 5)
        self.assertEqual(self.called, [])

    def accepted(self, operation, generation=1):
        return dict(self.examples['transport'], intent_id=operation['intent']['id'],
                    operation_key=operation['intent']['operation_key'], state='accepted', generation=generation)

    def test_r6_uncertainty_wins_over_stale_and_duplicate_classification(self):
        # The old primary's start was accepted, then the standby took over.
        old = self.operation('builder_start', 1, 'primary')
        old['history'] = [self.accepted(old)]
        self.take_over()
        self.assertEqual(self.states(self.run_pass(1, 'primary', [old])), [('reconcile', 'uncertain_outcome')])
        # A later copy of one operation carries the uncertainty: it is not a duplicate.
        first = self.operation('review_start', 2, 'standby')
        second = self.operation('review_start', 2, 'standby')
        second['history'] = [self.accepted(second, 2)]
        self.assertEqual(self.states(self.run_pass(2, 'standby', [first, second])),
                         [('reconcile', 'uncertain_outcome'), ('duplicate', 'record_only')])
        self.assertEqual(self.called, [])

    def test_r6_malformed_first_copy_does_not_consume_the_key(self):
        bad = self.operation('delivery', 1, 'primary')
        bad['claim'] = dict(bad['claim'], generation=7)
        good = self.operation('delivery', 1, 'primary')
        self.assertEqual(self.states(self.run_pass(1, 'primary', [bad, good])),
                         [('refused', 'incomplete_read'), ('disabled', 'unfenced_effect')])
        # A well-formed claim bound to another intent is refused by OB3 and consumes nothing either.
        mismatched = self.operation('delivery', 1, 'primary')
        mismatched['claim'] = dict(mismatched['claim'], intent_id='intent-other')
        self.assertEqual(self.states(self.run_pass(1, 'primary', [mismatched, good])),
                         [('refused', 'stale_binding'), ('disabled', 'unfenced_effect')])

    def test_r6_stale_or_mismatched_first_copy_never_hides_current_work(self):
        # Review round 2: only a valid, current copy consumes its key.
        self.take_over()
        stale = self.operation('delivery', 1, 'primary')
        current = self.operation('delivery', 2, 'standby')
        self.assertEqual(stale['intent']['operation_key'], current['intent']['operation_key'])
        self.assertEqual(self.states(self.run_pass(2, 'standby', [stale, current])),
                         [('refused', 'stale_claim'), ('disabled', 'unfenced_effect')])
        # A mismatched copy carrying the operation's uncertainty: the uncertainty
        # stays, on the first valid copy, and the mismatched copy consumes nothing.
        mismatched = self.operation('review_start', 2, 'standby')
        mismatched['claim'] = dict(mismatched['claim'], intent_id='intent-other')
        mismatched['history'] = [self.accepted(mismatched, 2)]
        valid = self.operation('review_start', 2, 'standby')
        self.assertEqual(self.states(self.run_pass(2, 'standby', [mismatched, valid])),
                         [('refused', 'stale_binding'), ('reconcile', 'uncertain_outcome')])
        self.assertEqual(self.called, [])

    def test_r6_stale_claim_with_a_current_snapshot_consumes_nothing(self):
        # Review round 3: a generation-1 claim paired with the current snapshot is
        # refused by OB3 and must not hide the valid generation-2 copy.
        self.take_over()
        stale = self.operation('delivery', 1, 'primary')
        current = self.operation('delivery', 2, 'standby')
        stale['snapshot'] = current['snapshot']
        self.assertEqual(self.states(self.run_pass(2, 'standby', [stale, current])),
                         [('refused', 'stale_claim'), ('disabled', 'unfenced_effect')])
        self.assertEqual(self.called, [])

    def test_standby_reconstructs_builder_and_reviewer_routes_from_durable_state(self):
        saved = {'builder:12': 'thr_synbuilder', f'review:31:{SHA}': THREAD}
        threads = [dict(id='thr_synbuilder', title='#12: Synthetic', branch='room/12-synthetic'),
                   dict(id=THREAD, title='Review #31 at ' + SHA[:8], branch=None)]
        for discovered in (threads, None):  # the standby may not reach CloudRoom discovery
            self.assertEqual(self.records.builder_thread(12, 'room/12-synthetic', discovered, saved),
                             ('thr_synbuilder', None))
            self.assertEqual(self.records.reviewer_thread(31, SHA, discovered, saved), (THREAD, None))
        # Without the private map and without discovery it names no replacement builder.
        self.assertEqual(self.records.builder_thread(12, 'room/12-synthetic', None, {}),
                         (None, 'thread discovery is out of reach'))

    def test_command_line_pass_prints_one_result_per_operation(self):
        view = {'pass': {'generation': 1, 'owner': 'primary'}, 'generations': self.generations,
                'operations': [self.operation('merge', 1, 'primary')]}
        done = subprocess.run([sys.executable, '-I', str(HERE / 'records.py'), 'ops-pass'],
                              input=json.dumps(view), capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        [line] = done.stdout.splitlines()
        result = self.effects.read_record(line)
        self.assertEqual((result['state'], result['reason'], result['effects']), ('disabled', 'unfenced_effect', []))
        view['generations'] = [self.generation(2, 'standby')]
        done = subprocess.run([sys.executable, '-I', str(HERE / 'records.py'), 'ops-pass'],
                              input=json.dumps(view), capture_output=True, text=True, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (2, ''))


if __name__ == '__main__':
    unittest.main()
