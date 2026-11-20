#!/usr/bin/env python3
"""OB3 owning boundary proofs. Synthetic fixtures, virtual transitions, no live I/O."""
import copy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EffectsProof(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.api = load(HERE / "effects.py", "ops_effects")
        cls.examples = json.loads((HERE.parent / "test/ops-protocol/examples.json").read_text())

    def setUp(self):
        self.intent = copy.deepcopy(self.examples["intent"])
        self.claim = copy.deepcopy(self.examples["operation"])
        self.snapshot = self.clean_snapshot()
        self.effects = []

    def clean_snapshot(self):
        snapshot = copy.deepcopy(self.examples["snapshot"])
        # The shared example carries an ON1 hold. Ordinary dispatch controls
        # have none; the hold negative below explicitly puts one back.
        snapshot["holds"] = []
        return snapshot

    def resume(self, history=()):
        return self.api.resume(self.intent, self.claim, list(history), self.snapshot,
                               lambda *args: self.effects.append(args))

    def test_stale_executor_after_takeover(self):
        # Pause after the earlier generation check, advance virtual ownership,
        # then enter the actual OB3 handler. No sleep or callback-based fence.
        self.assertEqual(self.resume()["state"], "disabled")
        self.snapshot.update(generation=2, owner="standby")
        result = self.resume()
        self.assertEqual((result["state"], result["reason"]), ("refused", "stale_claim"))
        self.assertEqual((result["next"], result["effects"], self.effects), ("end", [], []))

    def test_all_actions_remain_disabled_with_schema_valid_results(self):
        reference = load(HERE.parent / "test/ops-protocol/protocol.py", "reference")
        for action in ("builder_start", "review_start", "delivery", "hold_release", "merge", "grant", "audit"):
            with self.subTest(action=action):
                self.intent["action"] = action
                self.intent["operation_key"] = reference.operation_key(self.intent)
                self.claim["operation_key"] = self.intent["operation_key"]
                self.claim["ref"] = reference.claim_ref(self.claim)
                self.snapshot["intents"] = [copy.deepcopy(self.intent)]
                result = self.resume()
                self.assertEqual(reference.read_record(json.dumps(result)), result)
                self.assertEqual((result["state"], result["reason"], self.effects),
                                 ("disabled", "unfenced_effect", []))

    def test_strict_schema_reader_matches_contract_examples_and_rejects_bad_wire(self):
        for name, example in self.examples.items():
            with self.subTest(name=name):
                self.assertEqual(self.api.read_record(json.dumps(example)), example)
                for bad in (dict(example, enabled=True), list(example.values()),
                            {k: v for k, v in example.items() if k != "schema"}):
                    with self.assertRaises(ValueError):
                        self.api.read_record(json.dumps(bad))
        raw = json.dumps(self.intent)
        for bad in (raw.replace('"sequence": 1', '"sequence": true'),
                    raw.replace('"sequence": 1', '"sequence": 1.0'),
                    raw.replace('"sequence": 1', '"sequence": 9007199254740992'),
                    raw.replace('"sequence": 1', '"sequence": NaN'),
                    raw.replace('"schema":', '"schema":"openwiz.ops-dispatch.v1","schema":', 1),
                    raw.replace('openwiz.ops-dispatch.v1', 'openwiz.ops-dispatch.v9')):
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                self.api.read_record(bad)
        self.assertEqual(self.api.operation_key(self.intent),
                         "122291124bad25e809fe86f73c91b3293f634593f3ea325c8a69a82942ca64a3")

    def test_current_binding_and_durable_intent_are_required(self):
        changes = (("complete", False, "incomplete_read"), ("head", "e" * 40, "stale_binding"),
                   ("intents", [], "stale_binding"), ("paused", True, "paused_or_revoked"),
                   ("revoked", True, "paused_or_revoked"), ("gates", ["manual"], "paused_or_revoked"),
                   ("holds", [9010], "paused_or_revoked"), ("next_sequence", 2, "out_of_order"))
        for field, value, reason in changes:
            with self.subTest(field=field):
                self.snapshot = self.clean_snapshot()
                self.snapshot[field] = value
                result = self.resume()
                expected_state = "deferred" if reason == "out_of_order" else "refused"
                self.assertEqual((result["state"], result["reason"]), (expected_state, reason))
        self.assertEqual(self.effects, [])

    def test_foreign_claim_and_changed_intent_cannot_gain_admission(self):
        for field, value in (("intent_id", "other"), ("operation_key", "1" * 64),
                             ("subject", {"kind": "pull_request", "number": 9002}),
                             ("repository", "other/ops")):
            with self.subTest(field=field):
                self.claim = copy.deepcopy(self.examples["operation"])
                self.claim[field] = value
                if field == "operation_key":
                    self.claim["ref"] = self.claim["ref"].split("/k-")[0] + "/k-" + value
                self.assertEqual(self.resume()["reason"], "stale_binding")
        self.claim = copy.deepcopy(self.examples["operation"])
        self.snapshot["intents"][0]["evidence"][0]["digest"] = "e" * 64
        self.assertEqual(self.resume()["reason"], "stale_binding")
        self.assertEqual(self.effects, [])

    def test_uncertain_history_survives_new_approval_head_owner_ack_and_later_refusal(self):
        # These records model interruption after dispatch and before a reply or
        # outcome save. They are observations supplied to the real handler,
        # never an endpoint mock that manufactures a successful recovery.
        for kind, states in (("transport", ("accepted", "uncertain")),
                             ("completion", ("uncertain", "completed", "reconciled_not_executed")),
                             ("admission", ("uncertain", "reconcile"))):
            for state in states:
                for advance in (False, True):
                    with self.subTest(kind=kind, state=state, advance=advance):
                        self.snapshot = self.clean_snapshot()
                        event = copy.deepcopy(self.examples[kind])
                        event["state"] = state
                        later = copy.deepcopy(self.examples["completion"])
                        later.update(id="later-refusal", state="refused")
                        ack = copy.deepcopy(self.examples["ack"])
                        if advance:
                            self.snapshot.update(generation=2, owner="standby", head="e" * 40)
                            self.snapshot["approval"]["revision"] = 4
                        result = self.resume([event, ack, later])
                        self.assertEqual((result["state"], result["reason"]),
                                         ("reconcile", "uncertain_outcome"))
        self.assertEqual(self.effects, [])

    def test_other_key_for_same_ticket_blocks_replacement_but_not_another_ticket(self):
        event = copy.deepcopy(self.examples["transport"])
        event.update(operation_key="f" * 64, intent_id="old-intent", state="accepted")
        self.assertEqual(self.resume([event])["state"], "reconcile")
        event["ticket"] = 9002
        event["subject"]["number"] = 9002
        self.assertEqual(self.resume([event])["state"], "disabled")
        self.assertEqual(self.effects, [])

    def test_pending_before_dispatch_refused_transport_and_supersession(self):
        for state in ("not_attempted", "refused"):
            event = copy.deepcopy(self.examples["transport"])
            event["state"] = state
            self.assertEqual(self.resume([event])["state"], "disabled")
        event = copy.deepcopy(self.examples["completion"])
        event.update(state="superseded", superseded_by="f" * 64)
        self.assertEqual(self.resume([event])["state"], "superseded")
        self.snapshot["uncertain_keys"] = ["f" * 64]
        self.assertEqual(self.resume([event])["state"], "reconcile")

    def test_forged_merge_ack_cannot_enable_merge_or_clear_uncertainty(self):
        reference = load(HERE.parent / "test/ops-protocol/protocol.py", "reference")
        self.intent.update(action="merge", destination="ops")
        self.intent["operation_key"] = reference.operation_key(self.intent)
        self.claim.update(operation_key=self.intent["operation_key"])
        self.claim["ref"] = reference.claim_ref(self.claim)
        self.snapshot["intents"] = [copy.deepcopy(self.intent)]
        self.snapshot["recipient_verified"] = False
        ack = copy.deepcopy(self.examples["ack"])
        ack.update(operation_key=self.intent["operation_key"], recipient="ops")
        self.assertEqual(self.resume([ack])["state"], "disabled")
        self.snapshot["head"] = "e" * 40
        self.assertEqual(self.resume([ack])["reason"], "stale_binding")
        self.assertEqual(self.effects, [])

    def test_duplicate_conflicting_and_wrong_record_kinds_fail_closed(self):
        event = copy.deepcopy(self.examples["transport"])
        for history in ([event, event], [self.examples["grant"]]):
            with self.subTest(history=history), self.assertRaises(ValueError):
                self.resume(history)
        for field in ("claim", "intent", "snapshot"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                original = getattr(self, field)
                setattr(self, field, copy.deepcopy(self.examples["grant"]))
                try:
                    self.resume()
                finally:
                    setattr(self, field, original)
        # R1: immutable identity includes the separately supplied records too.
        # Normal-looking ACK, supersession and uncertain outcomes must not
        # classify a conflicting reuse of either supplied identity.
        for supplied in (self.intent, self.claim):
            for kind in ("ack", "completion", "transport"):
                event = copy.deepcopy(self.examples[kind])
                event["id"] = supplied["id"]
                if kind == "completion":
                    event.update(state="superseded", superseded_by="f" * 64)
                with self.subTest(supplied=supplied["kind"], kind=kind), self.assertRaises(ValueError):
                    self.resume([event])
        edited = copy.deepcopy(self.intent)
        edited["evidence"][0]["digest"] = "e" * 64
        with self.subTest(kind="edited intent"), self.assertRaises(ValueError):
            self.resume([edited])
        original_id = self.claim["id"]
        self.claim["id"] = self.intent["id"]
        try:
            with self.subTest(kind="supplied collision"), self.assertRaises(ValueError):
                self.resume()
        finally:
            self.claim["id"] = original_id
        # One identical durable copy is valid; duplicate source IDs in history
        # still refuse, even when those copies are identical.
        self.assertEqual(self.resume([copy.deepcopy(self.intent)])["state"], "disabled")
        with self.assertRaises(ValueError):
            self.resume([self.intent, copy.deepcopy(self.intent)])
        self.assertEqual(self.effects, [])

    def test_resume_does_not_mutate_records_or_route_to_unrelated_effect(self):
        history = [copy.deepcopy(self.examples["ack"])]
        before = copy.deepcopy([self.intent, self.claim, history, self.snapshot])
        self.resume(history)
        self.assertEqual([self.intent, self.claim, history, self.snapshot], before)
        self.assertEqual(self.effects, [])


    def test_history_with_same_key_but_foreign_binding_is_refused(self):
        for field, value in (("repository", "other/ops"), ("ticket", 9002),
                             ("intent_id", "other-intent"),
                             ("approval", {"revision": 4, "fingerprint": "e" * 64, "comment": 9005})):
            with self.subTest(field=field):
                event = copy.deepcopy(self.examples["transport"])
                event[field] = value
                self.assertEqual(self.resume([event])["reason"], "stale_binding")

    def test_atomic_generation_and_operation_records_have_one_winner(self):
        refs = {}

        def create(ref, commit):
            if ref in refs:
                return "exists"
            refs[ref] = commit
            return "created"

        generation = copy.deepcopy(self.examples["generation"])
        self.snapshot.update(generation=0, owner=None)
        self.assertEqual(self.api.admit_claim(generation, self.snapshot, "a" * 40, create), "admitted")
        competitor = dict(generation, id="standby-claim", owner="standby")
        self.assertEqual(self.api.admit_claim(competitor, self.snapshot, "b" * 40, create), "duplicate")
        self.assertEqual(refs, {"refs/heads/openwiz-ops/v1/s-9000/generations/g-1": "a" * 40})
        self.snapshot.update(generation=1, owner="primary")
        self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "c" * 40, create), "admitted")
        self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "d" * 40, create), "duplicate")
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[self.claim["ref"]], "c" * 40)
        self.assertEqual(self.resume()["state"], "disabled")
        self.assertEqual(self.effects, [])

    def test_admission_requires_current_verified_durable_intent(self):
        writes = []

        def create(*args):
            writes.append(args)
            return "created"

        for field, value, expected in (("complete", False, "refused"), ("intents", [], "refused"),
                                       ("owner", "standby", "stale"), ("generation", 2, "stale"),
                                       ("uncertain_keys", ["f" * 64], "reconcile"),
                                       ("paused", True, "refused"), ("revoked", True, "refused"),
                                       ("head", "e" * 40, "refused")):
            with self.subTest(field=field):
                self.snapshot = self.clean_snapshot()
                self.snapshot[field] = value
                self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "a" * 40, create), expected)
        self.snapshot = self.clean_snapshot()
        self.claim["subject"]["number"] = 9002
        self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "a" * 40, create), "refused")
        self.assertEqual(writes, [])

    def test_lost_record_reply_is_uncertain_and_recovery_cannot_blindly_create(self):
        refs = {}
        attempts = []

        def lost(ref, commit):
            attempts.append(ref)
            refs[ref] = commit
            raise TimeoutError("synthetic lost reply after record create")

        self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "a" * 40, lost), "uncertain")
        # The consumer saves the unresolved key before ending. A fresh pass
        # reconstructs it, rather than taking lease expiry as non-execution.
        self.snapshot["uncertain_keys"] = [self.intent["operation_key"]]
        self.snapshot.update(generation=2, owner="standby")
        self.claim.update(generation=2, previous_generation=1, owner="standby")
        self.claim["ref"] = self.api.claim_ref(self.claim)
        self.assertEqual(self.api.admit_claim(self.claim, self.snapshot, "b" * 40, lost), "reconcile")
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(refs), 1)
        self.assertEqual(self.resume()["state"], "reconcile")
        for reply in (None, True, {"created": True}, "updated", "unknown"):
            with self.subTest(reply=reply):
                snapshot = self.clean_snapshot()
                snapshot.update(generation=2, owner="standby")
                self.assertEqual(self.api.admit_claim(self.claim, snapshot, "b" * 40,
                                                      lambda *_: reply), "uncertain")

    def test_comments_bind_to_actual_container_and_reject_extra_fences(self):
        raw = json.dumps(self.intent)
        body = "```json\n" + raw + "\n```"
        container = ("synthetic/ops", "issue", 9001)
        self.assertEqual(self.api.read_comment(body, container), self.intent)
        for text, source in ((body, ("other/ops", "issue", 9001)),
                             (body, ("synthetic/ops", "pull_request", 9001)),
                             (body, ("synthetic/ops", "issue", 9002)),
                             (body + "\n" + body, container), (raw, container)):
            with self.subTest(source=source), self.assertRaises(ValueError):
                self.api.read_comment(text, source)


    def test_invalid_claim_records_cannot_reach_storage(self):
        writes = []
        for field, value in (("ref", "refs/heads/main"), ("previous_generation", 1),
                             ("intent_id", None), ("generation", True)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                claim = dict(self.claim, **{field: value})
                self.api.admit_claim(claim, self.snapshot, "a" * 40, writes.append)
        for commit in (None, "main", "a" * 39, "a" * 40 + "\n"):
            with self.subTest(commit=commit), self.assertRaises(ValueError):
                self.api.admit_claim(self.claim, self.snapshot, commit, writes.append)
        self.assertEqual(writes, [])

    def test_canonical_paths_and_required_protected_gates_match_ob1_reader(self):
        reference = load(HERE.parent / "test/ops-protocol/protocol.py", "reference")
        for path in ("../other.md", "tests/./case.json", "tests//case.json"):
            example = copy.deepcopy(self.examples["envelope"])
            example["paths"][0]["path"] = path
            with self.subTest(path=path):
                for reader in (reference.read_record, self.api.read_record):
                    with self.assertRaises(ValueError):
                        reader(json.dumps(example))
        example = copy.deepcopy(self.examples["envelope"])
        example["protected"].remove("self_authorization")
        with self.assertRaises(ValueError):
            self.api.read_record(json.dumps(example))
        example = copy.deepcopy(self.examples["envelope"])
        example["supporting"] = copy.deepcopy(example["paths"])
        with self.assertRaises(ValueError):
            self.api.read_record(json.dumps(example))


if __name__ == "__main__":
    unittest.main()
