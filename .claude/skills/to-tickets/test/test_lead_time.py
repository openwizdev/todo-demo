"""lead_time.py: spec lead time, from the spec's creation (to-spec writes it
from the confirmed grill with no step between, J202) to its last ticket's
merge, read from the war-room collector's `flow` fact. Unknown stays unknown:
never zero, never a partial span."""
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

LEAD = Path(__file__).resolve().parent.parent / "scripts" / "lead_time.py"


def ticket(n, spec, state, merged_at=None):
    return {"ticket": n, "spec": spec, "pull_requests": [n + 100] if merged_at else [], "state": state,
            "claimed_at": None, "merged_at": merged_at, "elapsed_seconds": None}


def spec(n, members, created, last, span):
    return {"spec": n, "tickets": members, "created_at": created, "last_merge_at": last, "span_seconds": span}


def snapshot(specs, tickets, state="partial", schema="openwiz.war-room.collector.v1"):
    """A collector document (synthetic) with only the facts lead time reads."""
    flow = {"fact": "flow", "state": state, "read": None, "point": None, "window": None, "fresh_until": None,
            "freshness": "unknown", "source": None, "evidence": [],
            "prerequisites": [] if state == "known" else ["synthetic gap"],
            "value": None if state == "unavailable" else {"tickets": tickets, "specs": specs}}
    stamp = "collected_at" if schema.endswith("collector.v1") else "requested_at"
    return {"schema": schema, "repository": "synthetic-owner/synthetic-repo", stamp: "2026-11-19T20:00:00Z",
            "factory": {"flow": flow}, "ci": {}}


TICKETS = [ticket(4101, 4001, "merged", "2026-11-19T10:30:00Z"), ticket(4102, 4001, "merged", "2026-11-19T12:15:00Z"),
           ticket(4103, 4002, "merged", "2026-11-19T11:00:00Z"), ticket(4104, 4002, "open"),
           ticket(4105, 4003, "unknown"), ticket(4106, 4005, "merged", "2026-11-19T13:00:00Z")]
SPECS = [spec(4001, [4101, 4102], "2026-11-19T09:00:00Z", "2026-11-19T12:15:00Z", 11700),
         spec(4002, [4103, 4104], "2026-11-19T09:30:00Z", None, None),
         spec(4003, [4105], "2026-11-19T09:45:00Z", None, None),
         spec(4004, None, None, None, None),
         spec(4005, [4106], None, "2026-11-19T13:00:00Z", None)]


class LeadTime(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def run_lead(self, document, *args):
        path = self.tmp / "collector.json"
        path.write_text(document if isinstance(document, str) else json.dumps(document))
        return subprocess.run(["python3", "-I", str(LEAD), str(path), *args], capture_output=True, text=True)

    def rows(self, document, *args):
        out = self.run_lead(document, *args)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        return json.loads(out.stdout)

    def test_each_spec_gets_its_lead_time_or_why_it_is_unknown(self):
        # catches: a lead time measured to an earlier merge while a member is
        # still open, an unknown read as zero, or a spec with unknown
        # membership or start given a number.
        report = self.rows(snapshot(SPECS, TICKETS))
        self.assertEqual(report.get("flow"), "partial")
        self.assertEqual(report["specs"], [
            {"spec": 4001, "lead_time_seconds": 11700, "from": "2026-11-19T09:00:00Z",
             "until": "2026-11-19T12:15:00Z", "unknown": None},
            {"spec": 4002, "lead_time_seconds": None, "from": "2026-11-19T09:30:00Z", "until": None,
             "unknown": "#4104 is open"},
            {"spec": 4003, "lead_time_seconds": None, "from": "2026-11-19T09:45:00Z", "until": None,
             "unknown": "#4105's state is unknown"},
            {"spec": 4004, "lead_time_seconds": None, "from": None, "until": None,
             "unknown": "its tickets are unknown"},
            {"spec": 4005, "lead_time_seconds": None, "from": None, "until": "2026-11-19T13:00:00Z",
             "unknown": "its creation time is unknown"},
        ])

    def test_asked_specs_the_collector_could_not_read_stay_unknown(self):
        # catches: an unavailable flow fact or an unread spec reported as no
        # lead time at all, or as zero, instead of unknown.
        unknown = lambda n, why: {"spec": n, "lead_time_seconds": None, "from": None, "until": None, "unknown": why}
        report = self.rows(snapshot(SPECS, TICKETS, schema="openwiz.war-room.collector.read.v1"),
                           "--spec", "4001", "--spec", "4999")
        self.assertEqual([r["spec"] for r in report["specs"]], [4001, 4999])
        self.assertEqual(report["specs"][1], unknown(4999, "not in the collector's flow fact"))
        report = self.rows(snapshot(None, None, state="unavailable"), "--spec", "4001")
        self.assertEqual(report, {"flow": "unavailable", "specs": [unknown(4001, "the flow fact is unavailable")]})
        older = snapshot(None, None)
        del older["factory"]["flow"]
        self.assertEqual(self.rows(older), {"flow": "unavailable", "specs": []})

    def test_facts_that_disagree_or_cannot_be_read_are_refused(self):
        # catches: a lead time printed from a span the collector's own times
        # contradict, or from a document that isn't the collector's.
        wrong = [dict(SPECS[0], span_seconds=600)]
        early = [dict(SPECS[0], last_merge_at="2026-11-19T11:00:00Z", span_seconds=7200)]
        for bad in (snapshot(wrong, TICKETS[:2]), snapshot(early, TICKETS[:2]),
                    dict(snapshot(SPECS, TICKETS), schema="openwiz.war-room.v2"), "{", "[]"):
            with self.subTest(bad=str(bad)[:60]):
                out = self.run_lead(bad)
                self.assertEqual((out.returncode, out.stdout), (2, ""))
                self.assertTrue(out.stderr.startswith("lead_time: "), out.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
