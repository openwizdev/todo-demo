import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).with_name("records.py")
REPO = "example/private"
FILE = "docs/grills/2099-01-01-notebook.md"
HEAD = "a" * 40
ROUND = """# Grill: Notebook (2099-01-01)

**Private.** Status: **open**. Feeds: the notebook spec.

## Round 1
Risk: ordinary

**N1 - Which order?** Synthetic café, /notes.
➡️ Use date order.

**N2 - Which export?** The notebook has two formats.
➡️ Use text.
"""
FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
path = Path(os.environ["FIXTURE"])
s = json.loads(path.read_text())
args = sys.argv[1:]
if args[:1] != ["api"]:
    sys.exit(3)
url = args[-1]
repo = "repos/example/private"
if url == repo:
    response = {"full_name": "example/private", "private": s["private"],
                "visibility": s["visibility"]}
elif url == repo + "/pulls/7":
    response = {"number": 7, "state": s["pr_state"], "head": {"sha": s["head"], "repo": {"full_name": s["head_repo"]}}}
elif url.startswith(repo + "/contents/") and url.endswith("?ref=" + s["head"]):
    file = url.removeprefix(repo + "/contents/").split("?ref=")[0]
    if file not in (s["file"], s.get("other_file")):
        sys.exit(4)
    response = {"encoding": "base64", "content": s["source"], "path": file}
elif url == repo + "/issues/7/comments":
    if args[1:3] == ["-X", "POST"]:
        s["writes"] += 1
        response = {"id": 81 + len(s["comments"]), "issue_url": "https://api.github.com/" + repo + "/issues/7",
                    **json.load(sys.stdin)}
        if not s["drop"]:
            s["comments"].append(response)
        path.write_text(json.dumps(s))
        if s["lose"]:
            sys.exit(1)
    else:
        response = [s["comments"]]
elif url.startswith(repo + "/issues/comments/"):
    index = int(url.rsplit("/", 1)[1]) - 81
    if args[1:3] == ["-X", "PATCH"]:
        s["writes"] += 1
        s["comments"][index].update(json.load(sys.stdin))
        path.write_text(json.dumps(s))
    response = s["comments"][index]
else:
    sys.exit(4)
print(json.dumps(response))
'''


class Records(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin",
                        "https://github.com/" + REPO + ".git"], check=True)
        gh = self.root / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o700)
        self.fixture = self.root / "fixture.json"
        self.write_state(private=True, writes=0, comments=[], lose=False, drop=False,
                         pr_state="open", visibility="private", head_repo=REPO, file=FILE,
                         head=HEAD, source=self.encoded(ROUND))

    @staticmethod
    def encoded(source):
        return base64.b64encode(source.encode()).decode()

    def state(self):
        return json.loads(self.fixture.read_text())

    def write_state(self, **changes):
        before = self.state() if self.fixture.exists() else {}
        self.fixture.write_text(json.dumps(before | changes))

    def call(self, action, *args, file=FILE):
        return subprocess.run(
            [sys.executable, "-I", str(HELPER), REPO, "7", file, action, *args],
            cwd=self.root, capture_output=True,
            env=os.environ | {"FIXTURE": str(self.fixture),
                              "PATH": str(self.root) + os.pathsep + os.environ["PATH"]},
        )

    def publish(self, request="round-one"):
        result = self.call("publish", request)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.state()["comments"][0]["body"].split("\n")[1])

    def contextual(self, record, payload, **changes):
        context = {
            "subject": {"repository": REPO, "kind": "pull_request", "number": 7},
            "comment_id": 81, "request_id": record["id"], "request_kind": record["kind"],
            "fingerprint": record["fingerprint"], "grill_file": FILE,
        }
        if record["kind"] == "grill_round":
            context.update(round=record["round"], question_id="N2")
        message = self.root / "message"
        message.write_bytes(b"openwiz decision answer v1\n" +
                            json.dumps(context | changes, separators=(",", ":")).encode() +
                            b"\n\n" + payload)
        return str(message)

    def test_new_round_binds_saved_wording_and_risk(self):
        record = self.publish()
        self.assertEqual(record["questions"], [
            {"id": "N1", "decides": "Which order?", "context": "Synthetic café, /notes.",
             "recommendation": "Use date order."},
            {"id": "N2", "decides": "Which export?", "context": "The notebook has two formats.",
             "recommendation": "Use text."},
        ])
        canonical = (
            '{"grill_file":"docs/grills/2099-01-01-notebook.md","id":"round-one",'
            '"kind":"grill_round","questions":[{"context":"Synthetic café, /notes.",'
            '"decides":"Which order?","id":"N1","recommendation":"Use date order."},'
            '{"context":"The notebook has two formats.","decides":"Which export?",'
            '"id":"N2","recommendation":"Use text."}],"risk":"ordinary","round":1,'
            '"schema":"openwiz.decisions.v1"}'
        )
        self.assertEqual(record["fingerprint"], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(record["answered"], [])
        self.assertEqual(self.state()["writes"], 1)

    def test_cold_restart_reuses_post_after_lost_response(self):
        self.write_state(lose=True)
        self.publish()
        self.publish()
        self.assertEqual(self.state()["writes"], 1)

    def test_unknown_privacy_writes_nothing(self):
        self.write_state(private=None)
        result = self.call("publish", "round-one")
        self.assertEqual(result.returncode, 2)
        self.assertIn(b"privacy", result.stderr)
        self.assertEqual(self.state()["writes"], 0)

    def test_context_extracts_only_exact_payload_and_one_question(self):
        record = self.publish()
        payload = b"  N2 yes\r\n\nopenwiz decision answer v1\nN1 no\n\n"
        output = self.root / "answer"
        result = self.call("match", self.contextual(record, payload), str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"matched N2\n")
        self.assertEqual(output.read_bytes(), payload)
        self.assertEqual(self.state()["writes"], 1)

    def test_stale_round_and_cross_subject_answer_are_refused(self):
        record = self.publish()
        path = str(self.root / "answer")
        wrong = {"repository": REPO, "kind": "pull_request", "number": 8}
        later = ROUND[ROUND.index("## Round"):].replace("Round 1", "Round 2")
        for source, context in [(ROUND, {"subject": wrong}), (ROUND + later, {})]:
            with self.subTest(context=context):
                self.write_state(source=self.encoded(source))
                result = self.call("match", self.contextual(record, b"yes", **context), path)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse(Path(path).exists())

    def test_corrected_summary_cannot_accept_previous_fingerprint(self):
        summary = "\n## Summary (shown to Test User for confirmation)\nRisk: ordinary\n\n1. Use text.\n"
        self.write_state(source=self.encoded(ROUND + summary))
        previous = self.publish("summary-one")
        corrected = summary.replace("Summary ", "Summary, corrected ").replace("text", "CSV")
        self.write_state(source=self.encoded(ROUND + summary + corrected))
        output = self.root / "answer"
        self.assertEqual(self.call("match", self.contextual(previous, b"confirm"),
                                   str(output)).returncode, 2)
        self.assertFalse(output.exists())

    def test_unknown_saved_risk_never_accepts_an_answer(self):
        self.write_state(source=self.encoded(ROUND.replace("Risk: ordinary\n", "")))
        record = self.publish()
        self.assertEqual(record["risk"], "unknown")
        output = self.root / "answer"
        self.assertEqual(self.call("match", self.contextual(record, b"yes"),
                                   str(output)).returncode, 2)
        self.assertFalse(output.exists())

    def test_partial_progress_requires_saved_settled_ids_and_preserves_comment(self):
        record = self.publish()
        body = self.state()["comments"][0]["body"]
        comments = self.state()["comments"]
        comments[0]["body"] = "Synthetic note.\n\n" + body
        self.write_state(comments=comments)
        premature = self.call("advance", "81", "N2")
        self.assertEqual(premature.returncode, 2)
        self.assertEqual(self.state()["writes"], 1)
        saved = ROUND + "\n**Test User:**\n> N2 yes\n\nSettled: N2. Open: N1.\n"
        self.write_state(source=self.encoded(saved))
        result = self.call("advance", "81", "N2")
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = self.state()["comments"][0]["body"]
        self.assertTrue(updated.startswith("Synthetic note.\n\n"))
        self.assertEqual(json.loads(updated.split("\n")[3]),
                         record | {"answered": ["N2"]})
        self.assertEqual(self.state()["writes"], 2)


    def test_restart_reports_progress_without_resetting_answers(self):
        self.publish()
        saved = ROUND + "\n**Test User:**\n> N2 yes\n\nSettled: N2. Open: N1.\n"
        self.write_state(source=self.encoded(saved))
        self.assertEqual(self.call("advance", "81", "N2").returncode, 0)
        result = self.call("publish", "round-one")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, b"verified request 81 (open)\n")
        self.assertEqual(self.state()["writes"], 2)

    def test_same_id_refuses_a_changed_or_superseded_request(self):
        # catches #1252: a reused request id reporting `verified request` for
        # a saved proposal whose wording changed, or one already superseded.
        changed = ROUND.replace("Use text.", "Use CSV.")
        for name in ("changed wording", "superseded"):
            with self.subTest(name):
                self.setUp()
                self.publish()
                if name == "superseded":
                    self.assertEqual(self.call("supersede", "81").returncode, 0)
                else:
                    self.write_state(source=self.encoded(changed))
                writes = self.state()["writes"]
                result = self.call("publish", "round-one")
                self.assertEqual((result.returncode, result.stdout), (2, b""))
                self.assertIn(b"existing request differs", result.stderr)
                self.assertEqual(self.state()["writes"], writes)
                self.assertEqual(len(self.state()["comments"]), 1)

    def test_ambiguous_absent_response_never_issues_second_post(self):
        self.write_state(lose=True, drop=True)
        for _ in range(2):
            result = self.call("publish", "round-one")
            self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.state()["writes"], 1)
        self.assertEqual(self.state()["comments"], [])

    def test_park_keeps_pending_request_but_refuses_answers(self):
        record = self.publish()
        self.write_state(source=self.encoded(
            ROUND.replace("**open**.", "**parked** by Test User, 2099-01-02.")))
        output = self.root / "answer"
        self.assertEqual(self.call("match", self.contextual(record, b"yes"),
                                   str(output)).returncode, 2)
        self.assertFalse(output.exists())
        self.assertEqual(self.state()["writes"], 1)
        self.write_state(pr_state="closed")
        self.assertEqual(self.call("supersede", "81").returncode, 0)
        updated = json.loads(self.state()["comments"][0]["body"].split("\n")[1])
        self.assertEqual(updated, record | {"status": "superseded"})

    def test_simplified_question_keeps_id_and_context_with_a_new_request(self):
        old = self.publish()
        replacement = ROUND[ROUND.index("## Round"):].replace("Round 1", "Round 2")
        replacement = replacement[0:replacement.index("**N1")] + replacement[replacement.index("**N2"):]
        replacement = replacement.replace("N2 - Which export?", "N2, re-asked - Save as text?")
        self.write_state(source=self.encoded(ROUND + replacement))
        self.assertEqual(self.call("supersede", "81").returncode, 0)
        result = self.call("publish", "round-two")
        self.assertEqual(result.returncode, 0, result.stderr)
        previous, current = [json.loads(c["body"].split("\n")[1])
                             for c in self.state()["comments"]]
        self.assertEqual(previous, old | {"status": "superseded"})
        self.assertEqual(current["questions"],
                         [old["questions"][1] | {"decides": "Save as text?"}])
        self.assertNotEqual(current["fingerprint"], old["fingerprint"])
        self.assertEqual(current["answered"], [])


    def test_internal_visibility_cannot_receive_exact_records(self):
        self.write_state(visibility="internal")
        result = self.call("publish", "round-one")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.state()["writes"], 0)

    def test_foreign_pr_head_cannot_supply_saved_wording(self):
        self.write_state(head_repo="example/other")
        result = self.call("publish", "round-one")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(self.state()["writes"], 0)

    def test_context_follows_one_grill_even_if_answer_names_another(self):
        record = self.publish()
        payload = b"N2 yes\nP2 yes"
        other = str(self.root / "other-answer")
        message = self.contextual(record, payload)
        other_file = "docs/grills/2099-01-01-other.md"
        self.write_state(other_file=other_file)
        result = self.call("match", message, other, file=other_file)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn(b"decision identity", result.stderr)
        self.assertFalse(Path(other).exists())
        output = self.root / "own-answer"
        result = self.call("match", message, str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output.read_bytes(), payload)


    def test_notebook_fixture_records_dependent_round_and_confirmed_summary(self):
        self.publish()
        source = ROUND + "\n**Test User:**\n> N1 yes\n> N2 yes\n\nSettled: N1, N2. Open: none.\n"
        self.write_state(source=self.encoded(source))
        self.assertEqual(self.call("advance", "81", "N1", "N2").returncode, 0)
        source += (
            "\n## Round 2\nRisk: ordinary\n\n"
            "**N3 - Which header?** Text export was settled in round one.\n"
            "➡️ Include the notebook title.\n"
        )
        self.write_state(source=self.encoded(source))
        self.assertEqual(self.call("publish", "round-two").returncode, 0)
        source += "\n**Test User:**\n> N3 no: keep it blank.  \n\nSettled: N3. Open: none.\n"
        self.write_state(source=self.encoded(source))
        self.assertEqual(self.call("advance", "82", "N3").returncode, 0)
        source += ("\n## Summary (shown to Test User for confirmation)\nRisk: ordinary\n\n"
                   "1. Sort by date.\n2. Export text.\n3. Leave the header blank.\n")
        self.write_state(source=self.encoded(source))
        self.assertEqual(self.call("publish", "summary-one").returncode, 0)
        self.assertEqual(self.call("advance", "83", "confirmed").returncode, 2)
        source = source.replace("**open**.", "**confirmed** by Test User, 2099-01-02.")
        source += "\n**Test User:**\n> Confirm.\n"
        self.write_state(source=self.encoded(source))
        self.assertEqual(self.call("advance", "83", "confirmed").returncode, 0)
        records = [json.loads(c["body"].split("\n")[1]) for c in self.state()["comments"]]
        self.assertEqual([(r["round"], r["answered"], r["status"]) for r in records[:2]],
                         [(1, ["N1", "N2"], "resolved"), (2, ["N3"], "resolved")])
        self.assertEqual(records[2]["summary"],
                         ["Sort by date.", "Export text.", "Leave the header blank."])
        self.assertEqual(records[2]["status"], "resolved")
        self.assertEqual(self.state()["writes"], 6)


if __name__ == "__main__":
    unittest.main()
