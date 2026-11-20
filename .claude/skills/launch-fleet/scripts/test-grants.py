"""OB2 synthetic boundary proofs; no endpoint effects or private fixture reads."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys

sys.dont_write_bytecode = True
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('grants', HERE / 'grants.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
EXAMPLES = json.loads((HERE.parent / 'test/ops-protocol/examples.json').read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


def fixture():
    records = copy.deepcopy(EXAMPLES)
    grant, envelope, intent, snap = [records[k] for k in ('grant', 'envelope', 'intent', 'snapshot')]
    sources = dict(intent='Approved synthetic refusal behaviour', evidence=[dict(evidence_class='fixture', source='fixture:synthetic/refusal', value='synthetic worked refusal')],
                   ownership=[{'path': 'tests/refusal.py', 'owner_ticket': 9001, 'shared_section': None}],
                   purposes=[dict(grant['paths'][0], path='tests/refusal.py')], rule='Synthetic narrow rule v1')
    material = {f'{"purpose" if k == "purposes" else k}_digest': digest(v) for k, v in sources.items()}
    grant['evidence'] = [dict(evidence_class='fixture', source='fixture:synthetic/refusal', digest=digest('synthetic worked refusal'))]
    envelope['evidence'] = copy.deepcopy(grant['evidence'])
    grant['paths'] = copy.deepcopy(sources['purposes'])
    grant['material'] = copy.deepcopy(material)
    grant['rule']['revision'] = material['rule_digest']
    snap['material'] = copy.deepcopy(material)
    snap['rule'] = copy.deepcopy(grant['rule'])
    snap['holds'] = []
    envelope['paths'][0]['path'] = 'src/refusal.py'
    intent.update(action='grant', destination='ops', assignment='ops-span-1', head=None)
    intent['operation_key'] = g.protocol.operation_key(intent)
    grant['operation_key'] = intent['operation_key']
    snap['intents'] = [copy.deepcopy(intent)]
    changes = [dict(path='tests/refusal.py', previous_path=None, resolved_path='tests/refusal.py',
                    owner_ticket=9001, shared_section=None, patch='+assert refused is True')]
    assessment = dict(role='ops', operation_key=grant['operation_key'], approval=copy.deepcopy(grant['approval']),
                      material=copy.deepcopy(material), head=snap['head'], diff_digest=digest(changes),
                      paths=copy.deepcopy(grant['paths']), findings=[])
    return grant, envelope, intent, snap, sources, assessment, changes, []


# #641: the factory's record authors; a comment by anyone else confers nothing.
FACTORY, OUTSIDER = 'synthetic-factory[bot]', 'synthetic-outsider'
AUTHORS = frozenset({FACTORY, 'synthetic-owner'})


def source_comment(record, number, author=FACTORY):
    return dict(id=number, created_at=record['created_at'], updated_at=record['created_at'],
                repository=record['repository'], subject=copy.deepcopy(record['subject']), author=author,
                body='```json\n' + json.dumps(record) + '\n```')


def collect(*args, **kwargs):
    return g.collect(*args, **kwargs, authors=AUTHORS)


def audit(*args):
    return g.audit(*args, authors=AUTHORS)


class GrantProof(unittest.TestCase):
    def check(self, args):
        return g.check_grant(*args)

    def test_exact_same_intent_grant_and_unchanged_plan(self):
        args = fixture()
        before = copy.deepcopy(args[3]['approval'])
        self.assertEqual(self.check(args), dict(purpose_current=True, diff_current=True, next='end', effects=[]))
        self.assertEqual(args[3]['approval'], before)

    def test_approved_support_can_be_checked_without_requesting_a_grant(self):
        grant, envelope, _, snap, sources, assessment, changes, _ = fixture()
        envelope['supporting'] = copy.deepcopy(grant['paths'])
        sources['purposes'] = copy.deepcopy(envelope['paths'] + envelope['supporting'])
        sources['ownership'].append(dict(path='src/refusal.py', owner_ticket=9001, shared_section=None))
        envelope['material'] = g.material(sources)
        envelope['rule']['revision'] = envelope['material']['rule_digest']
        snap.update(material=copy.deepcopy(envelope['material']), rule=copy.deepcopy(envelope['rule']))
        assessment.update(role='builder', operation_key='0'*64, material=copy.deepcopy(envelope['material']),
                          paths=copy.deepcopy(sources['purposes']))
        result = g.check_envelope(envelope, snap, sources, assessment, changes)
        self.assertEqual(result, dict(purpose_current=True, diff_current=True, next='end', effects=[]))
        assessment['role'] = 'reviewer'
        self.assertTrue(g.check_envelope(envelope, snap, sources, assessment, changes)['diff_current'])
        snap['head'] = assessment['head'] = None
        self.assertEqual(g.check_envelope(envelope, snap, sources, assessment, changes),
                         dict(purpose_current=True, diff_current=False, next='end', effects=[]))
        snap['approval']['comment'] = 9999
        self.assertFalse(g.check_envelope(envelope, snap, sources, assessment, changes)['purpose_current'])

    def test_record_evidence_and_readback_intent_match_the_checked_sources(self):
        for change in ('evidence', 'readback'):
            args = fixture()
            if change == 'evidence':
                args[0]['evidence'][0]['digest'] = 'f'*64
            else:
                args[3]['intents'] = []
            with self.subTest(change=change):
                self.assertFalse(self.check(args)['purpose_current'])

    def test_material_is_recomputed_from_independent_source_values(self):
        for name in ('intent', 'evidence', 'ownership', 'purposes', 'rule'):
            args = fixture()
            args[4][name] = ['Changed source']
            with self.subTest(source=name):
                self.assertFalse(self.check(args)['purpose_current'])

    def test_bindings_and_terminal_history_cannot_be_ignored(self):
        for field, value in [('repository', 'other/ops'), ('ticket', 9002), ('spec', 9004),
                             ('approval', dict(revision=4, fingerprint='f'*64, comment=9022)),
                             ('operation_key', 'f'*64), ('envelope_id', 'another-envelope')]:
            args = fixture()
            args[0][field] = value
            with self.subTest(field=field):
                self.assertFalse(self.check(args)['purpose_current'])
        for state in ('revoked', 'completed', 'replaced', 'refused', 'uncertain'):
            args = fixture()
            event = copy.deepcopy(args[0])
            event.update(id='grant-event-2', created_at=20, status=state, supersedes=args[0]['id'])
            args[-1].append(event)
            with self.subTest(state=state):
                self.assertFalse(self.check(args)['purpose_current'])
        for name in ('dispatch', 'on1'):
            args = fixture()
            args[0]['rule']['name'] = name
            with self.subTest(rule=name):
                self.assertFalse(self.check(args)['purpose_current'])

    def test_builder_cannot_grant_and_agent_scope_denials_are_binding(self):
        args = fixture()
        args[5]['role'] = 'builder'
        self.assertFalse(self.check(args)['diff_current'])
        cases = [
            ('tests/harmless.json', '+run_live()', 'deceptive filename hides live action'),
            ('tests/fixtures/setup.sh', '+chmod 777 /synthetic', 'executable fixture widens permission'),
            ('tests/refusal.py', '-assert refused is True', 'weakened assertion'),
            ('tests/refusal.py', '+new_unapproved_route()', 'mixed intent'),
        ] + [(f'tests/{gate}.py', '+protected_change()', gate) for gate in (
            'protected_policy', 'contracts', 'interfaces', 'dependencies', 'workflows', 'live',
            'spending', 'self_authorization')]
        for path, patch, finding in cases:
            args = fixture()
            args[6][0].update(path=path, resolved_path=path, patch=patch)
            # Even an exact path cannot erase the agent's adverse scope finding.
            args[0]['paths'][0]['path'] = path
            args[4]['purposes'][0]['path'] = path
            args[4]['ownership'][0]['path'] = path
            args[0]['material'] = g.material(args[4])
            args[0]['rule']['revision'] = args[0]['material']['rule_digest']
            args[3]['material'] = copy.deepcopy(args[0]['material'])
            args[3]['rule'] = copy.deepcopy(args[0]['rule'])
            args[5].update(material=copy.deepcopy(args[0]['material']), diff_digest=digest(args[6]),
                           paths=copy.deepcopy(args[0]['paths']), findings=[finding])
            with self.subTest(case=finding):
                self.assertFalse(self.check(args)['diff_current'])

    def test_whole_diff_rename_resolution_and_shared_ownership(self):
        for edit in [dict(previous_path='src/unowned.py'), dict(resolved_path='contracts/hidden.md'),
                     dict(owner_ticket=9002), dict(shared_section='other-ticket'),
                     dict(path='tests/../contract.py')]:
            args = fixture()
            args[6][0].update(edit)
            args[5]['diff_digest'] = digest(args[6])
            with self.subTest(edit=edit):
                self.assertFalse(self.check(args)['diff_current'])
        args = fixture()
        args[6].append(dict(args[6][0], path='src/unowned.py', resolved_path='src/unowned.py'))
        args[5]['diff_digest'] = digest(args[6])
        self.assertFalse(self.check(args)['diff_current'])

    def test_head_only_change_preserves_purpose_but_expires_review(self):
        args = fixture()
        args[3]['head'] = 'f' * 40
        result = self.check(args)
        self.assertTrue(result['purpose_current'])
        self.assertFalse(result['diff_current'])
        args[5]['head'] = 'f' * 40
        self.assertTrue(self.check(args)['diff_current'])
        args[6][0]['patch'] = '+different behaviour'
        self.assertFalse(self.check(args)['diff_current'])

    def test_null_head_preserves_grant_purpose_without_current_diff(self):
        args = fixture()
        args[3]['head'] = args[5]['head'] = None
        self.assertEqual(self.check(args),
                         dict(purpose_current=True, diff_current=False, next='end', effects=[]))

    def test_incomplete_paused_or_gated_sources_fail_closed(self):
        for key, value in [('complete', False), ('paused', True), ('revoked', True),
                           ('holds', [9009]), ('gates', ['dependency approval'])]:
            args = fixture()
            args[3][key] = value
            with self.subTest(key=key):
                self.assertFalse(self.check(args)['diff_current'])


class AuditProof(unittest.TestCase):
    def records(self):
        grant, envelope, intent, *_ = fixture()
        intent['created_at'] = 11
        grant['created_at'] = 12
        refusal = copy.deepcopy(grant)
        refusal.update(id='refusal-2', grant_id='refusal-2', status='refused', created_at=12)
        unknown = copy.deepcopy(intent)
        unknown.update(id='intent-2', sequence=2, created_at=12)
        unknown['operation_key'] = g.protocol.operation_key(unknown)
        refusal['operation_key'] = unknown['operation_key']
        return [source_comment(intent, 9011), source_comment(grant, 9012),
                source_comment(unknown, 9013), source_comment(refusal, 9014)]

    def template(self):
        template = copy.deepcopy(EXAMPLES['audit'])
        template.update(start=dict(created_at=10, comment=9010), end=dict(created_at=12, comment=9014), entries=[])
        return template

    def test_pagination_and_failure_do_not_lose_records(self):
        rows = self.records()
        pages = {1: (rows[:2], True), 2: (rows[2:], False)}
        self.assertEqual(collect(pages.__getitem__, 'synthetic/ops', ('issue', 9001)), rows)
        def broken(page):
            if page == 2:
                raise OSError('synthetic pagination failure')
            return pages[page]
        with self.assertRaises(OSError):
            collect(broken, 'synthetic/ops', ('issue', 9001))
        with self.assertRaises(ValueError):
            collect(pages.__getitem__, 'synthetic/ops', ('issue', 9001), page_budget=1)

    def test_source_metadata_edited_records_and_ambiguity(self):
        for edit in [dict(repository='other/ops'), dict(subject=dict(kind='issue', number=9002)),
                     dict(updated_at=99), dict(created_at=99)]:
            rows = self.records()
            rows[0].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                collect(lambda _: (rows, False), 'synthetic/ops', ('issue', 9001))
        rows = self.records()
        rows.append(copy.deepcopy(rows[0]))
        with self.assertRaises(ValueError):
            collect(lambda _: (rows, False), 'synthetic/ops', ('issue', 9001))

    def test_audit_covers_refusal_uncertainty_and_invalid_grant(self):
        rows = self.records()
        # One assessment per decision source, not just per operation: preserve events.
        assessments = {9012: dict(valid=False, final_diff_digest='d'*64),
                       9014: dict(valid=True, final_diff_digest=None)}
        report = audit(self.template(), rows, assessments)
        self.assertEqual(report['entries'], [
            dict(operation_key='5ba257bf032b87038f829c66b720028dd994ccd8194e41ca94551cba4bd57a5d',
                 decision='granted', grant_id='grant-1', final_diff_digest='d'*64, remediation='revoke_and_hold'),
            dict(operation_key='cd4ba0c9b58020e3f6a500699c9ba85b3a36ef480addc4e01c74bce04e998cff',
                 decision='refused', grant_id='refusal-2', final_diff_digest=None, remediation='none')])
        self.assertTrue(report['complete'])
        rows.pop()  # Intent with no outcome must remain visible as uncertain.
        report = audit(self.template(), rows, {9012: dict(valid=True, final_diff_digest=None)})
        self.assertEqual(report['entries'][-1]['decision'], 'uncertain')
        self.assertEqual(report['entries'][-1]['remediation'], 'escalate')

    def test_only_the_factory_records_confer_anything(self):
        """#641: a grant by an outsider, or by no one, is an ordinary comment."""
        decided = {9012: dict(valid=True, final_diff_digest=None), 9014: dict(valid=True, final_diff_digest=None)}
        for who in (OUTSIDER, None):
            rows = self.records()
            rows[1]['author'] = who  # the grant
            with self.subTest(author=who):
                entries = audit(self.template(), rows, decided)['entries']
                self.assertEqual([e['decision'] for e in entries], ['refused', 'uncertain'])
        self.assertEqual(g.audit(self.template(), self.records(), decided)['entries'], [])
        rows = self.records()
        rows[1]['author'] = 'Synthetic-Owner'
        self.assertEqual([e['decision'] for e in audit(self.template(), rows, decided)['entries']], ['granted', 'refused'])

    def test_record_authors_come_from_the_fleet_settings(self):
        fleet = json.loads((HERE / 'fixtures/check.json').read_text())['files']['docs/agents/fleet.md']
        self.assertEqual(g.record_authors(fleet), AUTHORS)
        for broken in (fleet.replace('| Record authors |', '| Record writers |'),
                       fleet.replace('`Synthetic-Owner`', '`synthetic owner`'),
                       # R1: a partly malformed cell refuses whole; its valid entries are not kept.
                       fleet.replace('`Synthetic-Owner`', 'Synthetic-Owner'),
                       fleet.replace('`synthetic-factory[bot]`, `Synthetic-Owner`', '`synthetic-factory[bot]` `Synthetic-Owner`'),
                       fleet.replace('`Synthetic-Owner`', '`Synthetic-Owner`; extra'),
                       # R3: anything after the value cell refuses the row, closing pipe or not.
                       fleet.replace(', `Synthetic-Owner` |', ' | `Synthetic-Owner`'),
                       fleet.replace('`synthetic-factory[bot]`, `Synthetic-Owner`', 'none'),
                       fleet.replace('## GitHub identity', '## Elsewhere')):
            with self.subTest(fleet=broken[-80:]), self.assertRaises(ValueError):
                g.record_authors(broken)

    def test_missing_assessment_and_backwards_cutoff_do_not_advance(self):
        report = audit(self.template(), self.records(), {})
        self.assertFalse(report['complete'])
        self.assertEqual(g.protocol.audit_cursor(report), dict(created_at=10, comment=9010))
        template = self.template()
        template['end'] = dict(created_at=9, comment=9009)
        with self.assertRaises(ValueError):
            audit(template, self.records(), {})

    def test_persist_report_before_cursor_and_idempotent_replay(self):
        report = audit(self.template(), self.records(), {
            9012: dict(valid=False, final_diff_digest='d'*64), 9014: dict(valid=True, final_diff_digest=None)})
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'cursor.json').write_text(json.dumps(report['start']))
            g.save_audit(tmp, report)
            self.assertEqual(json.loads((Path(tmp)/'cursor.json').read_text()), report['end'])
            saved = list((Path(tmp)/'reports').glob('*.json'))
            self.assertEqual(len(saved), 1)
            self.assertEqual(json.loads(saved[0].read_text()), report)
            g.save_audit(tmp, report)
            self.assertEqual(len(list((Path(tmp)/'reports').glob('*.json'))), 1)
            conflicting = copy.deepcopy(report)
            conflicting['entries'][0]['remediation'] = 'none'
            with self.assertRaises(ValueError):
                g.save_audit(tmp, conflicting)


    def test_audit_retains_later_uncertain_transport_and_lifecycle_events(self):
        rows = self.records()
        intent = json.loads(rows[0]['body'].split('\n')[1])
        transport = copy.deepcopy(EXAMPLES['transport'])
        transport.update(operation_key=intent['operation_key'], intent_id=intent['id'], created_at=13)
        rows.append(source_comment(transport, 9015))
        template = self.template()
        template['end'] = dict(created_at=13, comment=9015)
        report = audit(template, rows, {9012: dict(valid=True, final_diff_digest=None),
                                        9014: dict(valid=True, final_diff_digest=None),
                                        9015: dict(valid=None, final_diff_digest=None)})
        self.assertEqual(report['entries'][-1]['decision'], 'uncertain')
        self.assertEqual(report['entries'][-1]['remediation'], 'escalate')

    def test_a_later_refusal_does_not_erase_prior_transport_uncertainty(self):
        rows = self.records()
        intent = json.loads(rows[0]['body'].split('\n')[1])
        transport = copy.deepcopy(EXAMPLES['transport'])
        transport.update(operation_key=intent['operation_key'], intent_id=intent['id'], created_at=13)
        rows.append(source_comment(transport, 9015))
        completion = copy.deepcopy(EXAMPLES['completion'])
        completion.update(id='completion-2', operation_key=intent['operation_key'], intent_id=intent['id'],
                          state='refused', created_at=14)
        rows.append(source_comment(completion, 9016))
        template = self.template()
        template.update(start=dict(created_at=13, comment=9015), end=dict(created_at=14, comment=9016))
        report = audit(template, rows, {9016: dict(valid=True, final_diff_digest=None)})
        self.assertEqual(report['entries'][0]['decision'], 'uncertain')
        self.assertEqual(report['entries'][0]['remediation'], 'escalate')

    def test_revocation_is_audited_after_the_original_grant_cursor(self):
        rows = self.records()
        revoked = json.loads(rows[1]['body'].split('\n')[1])
        revoked.update(id='revocation-2', created_at=14, status='revoked', supersedes='grant-1')
        rows.append(source_comment(revoked, 9015))
        template = self.template()
        template.update(start=dict(created_at=12, comment=9014), end=dict(created_at=14, comment=9015))
        report = audit(template, rows, {9015: dict(valid=True, final_diff_digest=None)})
        self.assertEqual([entry['decision'] for entry in report['entries']], ['revoked'])
        self.assertEqual(report['entries'][0]['grant_id'], 'grant-1')

    def test_duplicate_ticket_revision_sequence_refuses_the_audit(self):
        rows = self.records()
        duplicate = json.loads(rows[0]['body'].split('\n')[1])
        duplicate.update(id='conflicting-sequence', head='f'*40)
        duplicate['operation_key'] = g.protocol.operation_key(duplicate)
        rows.append(source_comment(duplicate, 9017))
        with self.assertRaises(ValueError):
            audit(self.template(), rows, {})

    def test_corrupt_duplicate_cursor_keys_cannot_advance(self):
        report = self.template()
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'cursor.json').write_text('{"created_at":999,"created_at":10,"comment":9010}')
            with self.assertRaises(ValueError):
                g.save_audit(tmp, report)
            self.assertEqual((Path(tmp)/'cursor.json').read_text(), '{"created_at":999,"created_at":10,"comment":9010}')

    def test_missing_cursor_and_failed_report_write_never_skip_history(self):
        report = self.template()
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                g.save_audit(tmp, report)
            self.assertFalse((Path(tmp)/'cursor.json').exists())
            (Path(tmp)/'cursor.json').write_text(json.dumps(report['start']))
            (Path(tmp)/'reports').mkdir(exist_ok=True)
            (Path(tmp)/'reports'/f"{report['id']}.json").mkdir()
            with self.assertRaises((OSError, ValueError)):
                g.save_audit(tmp, report)
            self.assertEqual(json.loads((Path(tmp)/'cursor.json').read_text()), report['start'])


if __name__ == '__main__':
    unittest.main()
