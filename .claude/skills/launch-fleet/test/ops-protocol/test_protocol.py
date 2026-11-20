"""OB1's owning offline record/claim/refusal contract proofs. No live endpoint."""
import copy
import importlib.util
import json
import re
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


class AtomicRefs:
    """Recording endpoint with only the observed create-if-absent primitive."""
    def __init__(self):
        self.refs = {}
        self.calls = []

    def create(self, ref, commit):
        self.calls.append((ref, commit))
        if ref in self.refs:
            return "exists"
        self.refs[ref] = commit
        return "created"


class ProtocolProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = ROOT / "contracts/ops-dispatch.v1.schema.json"
        assert schema.is_file(), "OB1 exact record schema is not delivered"
        spec = importlib.util.spec_from_file_location("ops_protocol", HERE / "protocol.py")
        cls.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.api)
        cls.examples = json.loads((HERE / "examples.json").read_text())

    def example(self, kind):
        return copy.deepcopy(self.examples[kind])

    def read(self, value):
        return self.api.read_record(json.dumps(value))

    def test_every_record_variant_has_a_valid_synthetic_example(self):
        self.assertEqual(set(self.examples), {
            "envelope", "grant", "intent", "generation", "operation", "transport",
            "ack", "completion", "on1", "audit", "result", "snapshot", "admission",
        })
        for name, value in self.examples.items():
            with self.subTest(name=name):
                self.assertEqual(self.read(value), value)

    def test_every_object_refuses_missing_extra_and_positional_fields(self):
        def walk(value, path=()):
            if isinstance(value, dict):
                yield path, value
                for key, child in value.items():
                    yield from walk(child, path + (key,))
            if isinstance(value, list):
                for index, child in enumerate(value):
                    yield from walk(child, path + (index,))
        for name, value in self.examples.items():
            for path, obj in walk(value):
                for change in [dict(obj, planted=True), list(obj.values())] + [
                    {k: v for k, v in obj.items() if k != key} for key in obj
                ]:
                    candidate = copy.deepcopy(value)
                    if not path:
                        candidate = change
                    else:
                        parent = candidate
                        for key in path[:-1]:
                            parent = parent[key]
                        parent[path[-1]] = change
                    with self.subTest(record=name, path=path, change=type(change).__name__):
                        with self.assertRaises(ValueError):
                            self.read(candidate)

    def test_wire_duplicates_integers_and_unknown_versions_are_refused(self):
        raw = json.dumps(self.example("intent"))
        for bad in [raw.replace('"schema":', '"schema":"openwiz.ops-dispatch.v1","schema":', 1),
                    raw.replace('"revision": 3', '"revision": 3.0'),
                    raw.replace('"revision": 3', '"revision": true'),
                    raw.replace('"revision": 3', '"revision": "3"'),
                    raw.replace('openwiz.ops-dispatch.v1', 'openwiz.ops-dispatch.v9'),
                    raw.replace('"fingerprint":', '"fingerprint":"a","fingerprint":', 1)]:
            with self.subTest(bad=bad[:70]), self.assertRaises(ValueError):
                self.api.read_record(bad)

    def test_comment_binding_and_ambiguity_are_checked(self):
        value = self.example("intent")
        body = "Pending operation\n```json\n" + json.dumps(value) + "\n```"
        source = ("synthetic/ops", "issue", 9001)
        self.assertEqual(self.api.read_comment(body, source), value)
        for content, container in [(body + "\n```json\n{}\n```", source),
                                   (body, ("other/ops", "issue", 9001)),
                                   (body, ("synthetic/ops", "issue", 9002))]:
            with self.assertRaises(ValueError):
                self.api.read_comment(content, container)

    def test_exact_ref_names_are_disjoint_and_duplicate_admission_is_refused(self):
        refs, snapshot = AtomicRefs(), self.example("snapshot")
        generation = self.example("generation")
        before = copy.deepcopy(snapshot)
        before["generation"] = 0
        before["owner"] = None
        self.assertEqual(self.api.admit_claim(generation, before, "1" * 40, refs.create), "admitted")
        self.assertEqual(refs.calls[-1][0], "refs/heads/openwiz-ops/v1/s-9000/generations/g-1")
        self.assertEqual(self.api.admit_claim(generation, before, "2" * 40, refs.create), "duplicate")
        operation = self.example("operation")
        self.assertEqual(self.api.admit_claim(operation, snapshot, "3" * 40, refs.create), "admitted")
        self.assertIn("/operations/g-1/k-", refs.calls[-1][0])
        self.assertEqual(self.api.admit_claim(operation, snapshot, "4" * 40, refs.create), "duplicate")
        self.assertEqual(len(refs.refs), 2)

    def test_stale_incomplete_uncertain_claims_do_not_reach_ref_endpoint(self):
        for field, value, expected in [("generation", 2, "stale"), ("owner", "standby", "stale"),
                                       ("complete", False, "refused"),
                                       ("uncertain_keys", [self.example("intent")["operation_key"]], "reconcile")]:
            snapshot, refs = self.example("snapshot"), AtomicRefs()
            snapshot[field] = value
            self.assertEqual(self.api.admit_claim(self.example("operation"), snapshot, "3" * 40, refs.create), expected)
            self.assertEqual(refs.calls, [])
        refs, claim = AtomicRefs(), self.example("generation")
        claim["generation"] = 3
        with self.assertRaises(ValueError):
            self.api.admit_claim(claim, self.example("snapshot"), "3" * 40, refs.create)
        self.assertEqual(refs.calls, [])

    def test_unknown_create_reply_is_uncertain_without_retry(self):
        calls = []
        def lost_reply(ref, commit):
            calls.append(ref)
            raise TimeoutError("synthetic lost reply")
        self.assertEqual(self.api.admit_claim(self.example("operation"), self.example("snapshot"), "3" * 40, lost_reply), "uncertain")
        self.assertEqual(len(calls), 1)

    # A new approval/head can give a replacement a different operation key.
    # Existing tests used the same key and missed cross-revision uncertainty.
    def test_other_unresolved_ticket_key_cannot_admit_a_replacement(self):
        snapshot, refs = self.example("snapshot"), AtomicRefs()
        snapshot["uncertain_keys"] = ["f" * 64]
        self.assertEqual(self.api.admit_claim(self.example("operation"), snapshot, "3" * 40, refs.create), "reconcile")
        self.assertEqual(refs.calls, [])
        self.assertEqual(self.api.resume(self.example("intent"), self.example("operation"), [], snapshot, self.fail)["state"], "reconcile")

    def test_malformed_create_reply_remains_uncertain(self):
        calls = []
        def malformed_reply(ref, commit):
            calls.append(ref)
            return {"unexpected": "synthetic reply"}
        self.assertEqual(self.api.admit_claim(self.example("operation"), self.example("snapshot"), "3" * 40, malformed_reply), "uncertain")
        self.assertEqual(len(calls), 1)

    def test_all_unfenced_effects_stay_disabled_even_after_successful_ref_claim(self):
        for action in ["builder_start", "review_start", "delivery", "hold_release", "merge"]:
            intent = self.example("intent")
            intent["action"] = action
            intent["operation_key"] = self.api.operation_key(intent)
            claim = self.example("operation")
            claim["operation_key"] = intent["operation_key"]
            claim["ref"] = "refs/heads/openwiz-ops/v1/s-9000/operations/g-1/k-" + intent["operation_key"]
            snapshot = self.example("snapshot")
            snapshot["intents"] = [intent]
            refs, effects = AtomicRefs(), []
            self.assertEqual(self.api.admit_claim(claim, snapshot, "3" * 40, refs.create), "admitted")
            result = self.api.resume(intent, claim, [], snapshot, effects.append)
            self.assertEqual((result["state"], result["reason"], result["next"], result["effects"]),
                             ("disabled", "unfenced_effect", "end", []))
            self.assertEqual(effects, [])
            self.read(result)

    def test_worked_operation_identity_and_missing_intent_refuse(self):
        intent = self.example("intent")
        self.assertEqual(self.api.operation_key(intent), "122291124bad25e809fe86f73c91b3293f634593f3ea325c8a69a82942ca64a3")
        snapshot, refs = self.example("snapshot"), AtomicRefs()
        snapshot["intents"] = []
        self.assertEqual(self.api.admit_claim(self.example("operation"), snapshot, "3" * 40, refs.create), "refused")
        self.assertEqual(refs.calls, [])

    def test_pause_after_ref_check_rejects_stale_owner_without_effect(self):
        refs, effects = AtomicRefs(), []
        claim = self.example("operation")
        self.assertEqual(self.api.admit_claim(claim, self.example("snapshot"), "3" * 40, refs.create), "admitted")
        later = self.example("snapshot")
        later.update(generation=2, owner="standby")
        result = self.api.resume(self.example("intent"), claim, [], later, effects.append)
        self.assertEqual((result["state"], result["reason"]), ("refused", "stale_claim"))
        self.assertEqual(effects, [])

    def test_crash_after_effect_and_later_refusal_cannot_clear_uncertainty(self):
        for state in ["accepted", "uncertain"]:
            for advanced in [False, True]:
                for explicit_key in [False, True]:
                    for later_refusal in [False, True]:
                        with self.subTest(state=state, advanced=advanced, explicit_key=explicit_key,
                                          later_refusal=later_refusal):
                            transport = self.example("transport")
                            transport["state"] = state
                            snapshot = self.example("snapshot")
                            if advanced:
                                snapshot["approval"]["revision"] += 1
                            if explicit_key:
                                snapshot["uncertain_keys"] = [transport["operation_key"]]
                            history = [transport]
                            if later_refusal:
                                refused = self.example("transport")
                                refused.update(id="later-refusal", state="refused", created_at=20)
                                history.append(refused)
                            effects = []
                            result = self.api.resume(self.example("intent"), self.example("operation"),
                                                     history, snapshot, effects.append)
                            self.assertEqual((result["state"], result["reason"]),
                                             ("reconcile", "uncertain_outcome"))
                            self.assertEqual(effects, [])

    def test_uncertain_history_must_belong_to_the_recorded_operation(self):
        for field, value in [("repository", "other/ops"), ("ticket", 9002),
                             ("intent_id", "other-intent"),
                             ("approval", {"revision": 4, "fingerprint": "e" * 64, "comment": 9005})]:
            with self.subTest(field=field):
                transport = self.example("transport")
                transport[field] = value
                result = self.api.resume(self.example("intent"), self.example("operation"),
                                         [transport], self.example("snapshot"), self.fail)
                self.assertEqual((result["state"], result["reason"]), ("refused", "stale_binding"))

    def test_transport_acceptance_is_not_ack_and_forged_ack_does_not_authorize_effect(self):
        snapshot = self.example("snapshot")
        result = self.api.resume(self.example("intent"), self.example("operation"),
                                 [self.example("transport"), self.example("ack")], snapshot, self.fail)
        self.assertEqual(result["state"], "reconcile")
        snapshot["recipient_verified"] = True
        result = self.api.resume(self.example("intent"), self.example("operation"),
                                 [self.example("ack")], snapshot, self.fail)
        self.assertEqual(result["state"], "disabled")

    def test_changed_head_approval_supersession_order_and_intent_collision_refuse(self):
        intent, claim = self.example("intent"), self.example("operation")
        for field, value in [("head", "e" * 40), ("complete", False), ("next_sequence", 2),
                             ("paused", True), ("revoked", True)]:
            snapshot = self.example("snapshot")
            snapshot[field] = value
            result = self.api.resume(intent, claim, [], snapshot, self.fail)
            self.assertIn(result["state"], ["refused", "deferred"])
        snapshot = self.example("snapshot")
        snapshot["approval"]["fingerprint"] = "e" * 64
        self.assertEqual(self.api.resume(intent, claim, [], snapshot, self.fail)["state"], "refused")
        superseded = self.example("completion")
        superseded.update(state="superseded", superseded_by="f" * 64)
        self.assertEqual(self.api.resume(intent, claim, [superseded], self.example("snapshot"), self.fail)["state"], "superseded")
        collision = copy.deepcopy(intent)
        collision["action"] = "merge"
        with self.assertRaises(ValueError):
            self.api.resume(intent, claim, [collision], self.example("snapshot"), self.fail)

    def test_grants_expire_on_material_change_but_not_head_only_change(self):
        grant = self.example("grant")
        snapshot = self.example("snapshot")
        self.assertTrue(self.api.grant_current(grant, snapshot))
        snapshot["head"] = "e" * 40
        self.assertTrue(self.api.grant_current(grant, snapshot))
        for field in ["intent_digest", "evidence_digest", "ownership_digest", "purpose_digest", "rule_digest"]:
            snapshot = self.example("snapshot")
            snapshot["material"][field] = "f" * 64
            self.assertFalse(self.api.grant_current(grant, snapshot))
        for status in ["refused", "uncertain", "revoked", "completed", "replaced"]:
            grant["status"] = status
            self.assertFalse(self.api.grant_current(grant, self.example("snapshot")))
        grant = self.example("grant")
        grant["rule"]["name"] = "on1"
        self.assertFalse(self.api.grant_current(grant, self.example("snapshot")))

    def test_inclusive_cutoff_and_newer_holds_are_checked_without_release(self):
        on1, snapshot = self.example("on1"), self.example("snapshot")
        snapshot["rule"] = copy.deepcopy(on1["rule"])
        self.assertTrue(self.api.on1_current(on1, snapshot))
        for field, value in [("history_digest", "e" * 64), ("cutoff", "e" * 40),
                             ("holds", [9009, 9010]), ("complete", False),
                             ("cutoff_changes", []), ("consumers", [])]:
            current = copy.deepcopy(snapshot)
            current[field] = value
            self.assertFalse(self.api.on1_current(on1, current))
        for field, value in [("complete", False), ("inclusive", False)]:
            changed = copy.deepcopy(on1)
            changed["cutoff"][field] = value
            self.assertFalse(self.api.on1_current(changed, snapshot))

    def test_partial_audit_does_not_advance_and_complete_cursor_is_exact(self):
        audit = self.example("audit")
        self.assertEqual(self.api.audit_cursor(audit), {"created_at": 20, "comment": 9020})
        audit["complete"] = False
        self.assertEqual(self.api.audit_cursor(audit), {"created_at": 10, "comment": 9010})

    # Audit finding: existing ON1 cases changed cutoff/holds but never the rule.
    # A wrong rule must not be reported as current, despite disabled effects.
    def test_on1_wrong_or_revised_rule_is_not_current(self):
        record, snapshot = self.example("on1"), self.example("snapshot")
        record["rule"]["name"] = "dispatch"
        snapshot["rule"] = copy.deepcopy(record["rule"])
        self.assertFalse(self.api.on1_current(record, snapshot))
        record["rule"]["name"] = "on1"
        snapshot["rule"] = copy.deepcopy(record["rule"])
        snapshot["rule"]["revision"] = "e" * 64
        self.assertFalse(self.api.on1_current(record, snapshot))

    def test_grant_dispatch_rule_cannot_be_current_grant_authority(self):
        grant, snapshot = self.example("grant"), self.example("snapshot")
        grant["rule"]["name"] = "dispatch"
        snapshot["rule"] = copy.deepcopy(grant["rule"])
        self.assertFalse(self.api.grant_current(grant, snapshot))

    # Audit finding: JSON Schema pattern is a search, not Python fullmatch.
    # Shared structural cases need an independent literal oracle for both doors.
    def test_schema_pattern_does_not_accept_trailing_line_terminators(self):
        pattern = self.api.SCHEMA["$defs"]["approval"]["properties"]["fingerprint"]["pattern"]
        for value, expected in [("a" * 64, True), ("a" * 63, False),
                                ("A" * 64, False), ("a" * 64 + "\n", False),
                                ("a" * 64 + "\r\n", False), ("a" * 64 + "\r", False)]:
            self.assertEqual(re.search(pattern, value) is not None, expected)
            record = self.example("envelope")
            record["approval"]["fingerprint"] = value
            try:
                self.read(record)
                accepted = True
            except ValueError:
                accepted = False
            self.assertEqual(accepted, expected)

    # Self-sweep: structurally valid records used in the wrong handler slot
    # must be refused as invalid input, not lose the finite pass to a KeyError.
    def test_wrong_handler_record_kinds_are_refused(self):
        with self.assertRaises(ValueError):
            self.api.resume(self.example("intent"), self.example("operation"), [], self.example("intent"), self.fail)
        with self.assertRaises(ValueError):
            self.api.resume(self.example("intent"), self.example("operation"), [self.example("result")], self.example("snapshot"), self.fail)


if __name__ == "__main__":
    unittest.main()
