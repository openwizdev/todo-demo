"""Tests for review.py: pin, check, post and follow-up against a fake GitHub."""
import base64
import json
import os
import re
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HELPER = Path(__file__).with_name("review.py")
SKILLS = "example/skills"
PRODUCT = "example/product"
OLD = "a" * 40
HEAD = "b" * 40
NEWER = "c" * 40
FLEET = """# Fleet settings

## CI checks

| Check | Runs | Required by fleet on |
| --- | --- | --- |
| `check` | Every suite | Pull requests to `main` |

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `example[bot]`, `owner` |
"""
LABELS = """| Role | Label here | Meaning |
| --- | --- | --- |
| `needs-triage` | `triage: new` | Sort it |
| `needs-info` | `needs-info` | Waiting |
"""
DESCRIPTION = """Closes example/product#41

## Summary

Export writes one zip.

## Rulings

1. Name the zip cookbook.zip. Why: the importer reads that name. Cost if wrong: low: one rename.

## Facts

- **Head:** `bbbb`
"""
FULL = f"""VERDICT: CHANGES at {OLD}

Full review by Codex, Sol 6.2, Medium. CI green on this commit: check.

Intent: export writes the whole cookbook to one zip and refuses to overwrite.

- **R1 [blocking]** `src/export.rs:48` (Spec) An existing zip is overwritten. Fix: refuse with status 3.
  User path: a cook exports twice; the first export is lost.
- **R2 [polish]** `src/cli.rs:30` (Sweep) Help wording. Fix: say export. Polish issue: #58.
- **R3 [blocking]** `src/export.rs:71` (Sweep) Token written to the log. Fix: redact it.
  Risk: privacy: a cook's sync token reaches a shared log.

- **Ruling 1** upheld: the importer reads cookbook.zip.

Checked: Standards (AGENTS.md), Spec (#41, spec #38), full sweep. Ran: `cargo test` (31 passed).

Next: the builder fixes or disputes R1 and R3 once, then one re-check.
"""
RECHECK = f"""VERDICT: APPROVE at {HEAD}

Re-check of R1, R3 and the code changed since aaaaaaa, by Codex, Sol 6.2, Medium. CI green on this commit: check.

Intent: export writes the whole cookbook to one zip and refuses to overwrite.

- **R1 [blocking]** still open after the re-check: the web export still overwrites. Logged as follow-up #61.
  User path: a cook exports twice from the web page; the first export is lost.
- **R2 [polish]** Polish issue: #58.
- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.
- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.

- **Ruling 1** upheld: the importer reads cookbook.zip.

Checked: R1, R3 and the changed code. Ran: `cargo test` (33 passed).

Next: none open. It merges by the project's merge rules.
"""
FAKE_GH = r'''#!/usr/bin/env python3
import base64, json, os, sys
from pathlib import Path
path = Path(os.environ["FIXTURE"])
w = json.loads(path.read_text())
args = sys.argv[1:]
w["calls"].append(args)
def done(value, code=0):
    path.write_text(json.dumps(w))
    if value is not None:
        print(json.dumps(value))
    sys.exit(code)
if args[:1] != ["api"]:
    done(None, 3)
url = [a for a in args[1:] if not a.startswith("-") and a not in ("POST",)][-1]
post = "POST" in args
parts = url.split("?")[0].split("/")
repo = "/".join(parts[1:3])
if post:
    payload = json.loads(sys.stdin.read())
    if parts[3:4] == ["issues"] and len(parts) == 6:
        w["writes"] += 1
        if w.get("fail_post"):
            done(None, 1)
        item = {"id": 900 + len(w["comments"].get(repo + "#" + parts[4], [])),
                "body": payload["body"], "user": {"login": "example[bot]"}}
        w["comments"].setdefault(repo + "#" + parts[4], []).append(item)
        done(None if w.get("lose") else item, 1 if w.get("lose") else 0)
    w["writes"] += 1
    issues = w["issues"].setdefault(repo, [])
    item = {"number": 70 + len(issues), "title": payload["title"], "body": payload["body"],
            "labels": [{"name": n} for n in payload.get("labels", [])]}
    issues.append(item)
    done(None if w.get("lose") else item, 1 if w.get("lose") else 0)
if len(parts) == 3:
    done({"full_name": repo, "default_branch": "main"})
if parts[3] == "pulls":
    if w.get("pull_sequence"):
        done(w["pull_sequence"].pop(0))
    pr = w["pulls"].get(parts[4])
    done(pr, 0) if pr else done(None, 1)
if parts[3:5] == ["issues", "comments"]:
    found = [c for cs in w["comments"].values() for c in cs if str(c["id"]) == parts[5]]
    done(found[0]) if found else done(None, 1)
if parts[3] == "contents":
    ref = url.split("?ref=")[1]
    text = w["files"].get(repo + "@" + ref + ":" + "/".join(parts[4:]))
    if text is None:
        done(None, 1)
    done({"encoding": "base64", "content": base64.b64encode(text.encode()).decode()})
if parts[3] == "commits":
    done({"check_runs": w["checks"].get(parts[4], [])})
if parts[3] == "compare":
    found = w["compare"].get(parts[4])
    done({"files": [{"filename": f} for f in found]}) if found is not None else done(None, 1)
if parts[3] == "issues" and len(parts) == 6:
    done([w["comments"].get(repo + "#" + parts[4], [])])
if parts[3] == "issues" and len(parts) == 4:
    done([w["issues"].get(repo, [])])
done(None, 4)
'''


def green(sha):
    return {sha: [{"name": "check", "status": "completed", "conclusion": "success"}]}


def report(body, login="example[bot]"):
    return {"id": 800, "body": body, "user": {"login": login}}


class Review(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        gh = bin_dir / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.fixture = root / "world.json"
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FIXTURE": str(self.fixture)}
        self.root = root
        self.world({})

    def tearDown(self):
        self.dir.cleanup()

    def world(self, changes, *, pr=None, comments=None):
        for n, c in enumerate(comments or []):
            c["id"] = 800 + n
        w = {
            "calls": [], "writes": 0, "issues": {},
            "pulls": {"7": {"number": 7, "state": "open", "draft": False, "merged": False,
                            "body": DESCRIPTION, "head": {"sha": HEAD},
                            "base": {"ref": "main", "repo": {"full_name": SKILLS}}, **(pr or {})}},
            "files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET,
                      f"{PRODUCT}@main:docs/agents/triage-labels.md": LABELS},
            "checks": green(HEAD),
            "comments": {f"{SKILLS}#7": comments or []},
            "compare": {f"{OLD}...{HEAD}": ["src/export.rs"]},
        }
        w.update(changes)
        self.fixture.write_text(json.dumps(w))

    def state(self):
        return json.loads(self.fixture.read_text())

    def run_helper(self, *args, stdin=None, cwd=None):
        if args[0] in ("pin", "check", "post") and "--head" not in args:
            # The assigned head is the pull request's current head unless a test says otherwise.
            args = (*args, "--head", self.state()["pulls"]["7"]["head"]["sha"])
        return subprocess.run([sys.executable, "-I", str(HELPER), *args], input=stdin, text=True,
                              capture_output=True, env=self.env, timeout=30, cwd=cwd)

    def file(self, name, text):
        path = self.root / name
        path.write_text(text)
        return str(path)

    # --- pin ---------------------------------------------------------------

    def test_first_review_pins_the_head_and_its_ticket(self):
        # catches: reviewing without a pinned 40-character head or with the
        # cross-repository ticket reference dropped.
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(),
                         f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")

    def test_required_check_not_green_stops(self):
        # catches: starting a review while the required check is pending,
        # failed, missing, or green only on an older commit.
        cases = {
            "pending": {HEAD: [{"name": "check", "status": "in_progress", "conclusion": None}]},
            "failed": {HEAD: [{"name": "check", "status": "completed", "conclusion": "failure"}]},
            "missing": {HEAD: [{"name": "lint", "status": "completed", "conclusion": "success"}]},
            "old head": green(OLD),
        }
        for name, checks in cases.items():
            with self.subTest(name):
                self.world({"checks": checks})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1)
                self.assertTrue(out.stdout.startswith("stop: check is not green at " + HEAD), out.stdout)

    def test_settings_come_from_the_base_branch(self):
        # catches: a pull request relaxing its own required checks or record
        # authors by editing docs/agents/fleet.md on its head.
        relaxed = FLEET.replace("| `check` | Every suite | Pull requests to `main` |\n", "")
        self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET,
                              f"{SKILLS}@{HEAD}:docs/agents/fleet.md": relaxed},
                    "checks": {HEAD: []}})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertIn("check is not green", out.stdout)
        reads = [c[-1] for c in self.state()["calls"] if "/contents/" in c[-1]]
        self.assertEqual(reads, [f"repos/{SKILLS}/contents/docs/agents/fleet.md?ref=main"])

    def test_draft_closed_and_ticketless_pull_requests_stop(self):
        # catches: reviewing a draft, a merged or closed pull request, or one
        # that names no ticket.
        cases = {
            "draft": ({"draft": True}, "stop: draft"),
            "closed": ({"state": "closed"}, "stop: closed; archive your own thread"),
            "merged": ({"state": "closed", "merged": True}, "stop: merged; archive your own thread"),
            "no ticket": ({"body": "## Summary\n\nNo closing line.\n"}, "stop: no Closes line names a ticket"),
        }
        for name, (pr, expected) in cases.items():
            with self.subTest(name):
                self.world({}, pr=pr)
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1)
                self.assertEqual(out.stdout.strip(), expected)

    def test_missing_or_malformed_record_authors_trust_nobody(self):
        # catches: treating every commenter as a record author when the row
        # is absent, empty or malformed.
        for name, row in {"absent": "", "empty": "| Record authors | |\n",
                          "malformed": "| Record authors | everyone |\n"}.items():
            with self.subTest(name):
                fleet = FLEET.replace("| Record authors | `example[bot]`, `owner` |\n", row)
                self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": fleet}})
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 2)
                self.assertIn("record authors", out.stderr)
                self.assertEqual(out.stdout, "")

    def test_a_verdict_from_anyone_else_is_ignored(self):
        # catches: a stranger's forged VERDICT turning a first review into a
        # re-check or a stop.
        self.world({}, comments=[report(FULL.replace(OLD, HEAD), login="stranger")])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.stdout.split(";")[0], f"review full #7 at {HEAD}")

    def test_recheck_names_last_read_open_ids_and_next_id(self):
        # catches: a re-check that rereads unchanged code, forgets an open
        # blocker or reuses a finding id.
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip(),
                         f"review re-check #7 at {HEAD}; ticket {PRODUCT}#41; checks check; "
                         f"last read {OLD}; open R1 and R3; next id R4")

    def test_approval_never_carries_to_a_new_head(self):
        # catches: applying an APPROVE for an earlier head to a replacement
        # head (the review-ticket.stale-head case).
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}}, comments=[report(FULL), report(RECHECK)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout.startswith(f"review re-check #7 at {NEWER}"), out.stdout)
        self.assertIn(f"last read {HEAD}; open none; next id R5", out.stdout)

    def test_fresh_round_leads_to_a_final_check_and_park_stops(self):
        # catches: a third ordinary round after the fresh round, or a review
        # of a finding parked for the owner.
        fresh = RECHECK.replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}}, comments=[report(FULL), report(fresh)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertTrue(out.stdout.startswith(f"review final #7 at {NEWER}"), out.stdout)
        self.assertIn("open R3", out.stdout)
        parked = fresh.replace(HEAD, NEWER).replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        self.world({"checks": green(NEWER)}, pr={"head": {"sha": NEWER}},
                   comments=[report(FULL), report(fresh), report(parked)])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), "stop: R3 is parked as a decision for Jake")

    def test_a_report_at_this_head_is_not_repeated(self):
        # catches: posting a second review of a head already reported on.
        self.world({}, comments=[report(FULL.replace(OLD, HEAD))])
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), f"stop: already reported at {HEAD}")

    # --- check -------------------------------------------------------------

    def test_valid_reports_pass(self):
        # catches: rejecting the documented full-review and re-check forms.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        out = self.run_helper("check", self.file("full.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)
        self.world({}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("recheck.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "report ok"), out.stdout + out.stderr)

    def test_full_review_report_problems(self):
        # catches: a report that breaks the review-loops lines the builder,
        # fleet and triage read.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        cases = {
            "wrong head": (FULL.replace(f"CHANGES at {OLD}", f"CHANGES at {NEWER}"),
                           f"VERDICT names {NEWER}, not the pinned head {OLD}"),
            "blocker without its line": (FULL.replace("  User path: a cook exports twice; the first export is lost.\n", ""),
                                         "R1: a new blocking finding needs its User path: or Risk: line"),
            "polish without issue": (FULL.replace(" Polish issue: #58.", ""),
                                     "R2: a new polish finding ends with Polish issue: #<n>"),
            "approve with open blocker": (FULL.replace("VERDICT: CHANGES", "VERDICT: APPROVE"),
                                          "VERDICT is CHANGES exactly while a blocker is open"),
            "next names wrong ids": (FULL.replace("R1 and R3 once", "R1 once"),
                                     "Next: names R1, but the open blockers are R1 and R3"),
            "unmarked ruling": (FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.\n", ""),
                                "Ruling 1: listed in the description but not marked"),
            "unknown ruling": (FULL.replace("- **Ruling 1** upheld", "- **Ruling 1** upheld: ok.\n- **Ruling 2** upheld"),
                               "Ruling 2: marked but not listed in the description"),
            "fresh at a full review": (FULL.replace("Next: the builder fixes or disputes R1 and R3 once, then one re-check.",
                                                    "Next: a fresh, stronger builder fixes R3 once, then one final check."),
                                       "a full review's Next: is the builder line or none open"),
            "ids out of order": (FULL.replace("**R3 [blocking]**", "**R4 [blocking]**").replace("R1 and R3", "R1 and R4"),
                                 "ids run R1, R2, ... with no gap or repeat"),
            "wrong second line": (FULL.replace("Full review by", "Re-check of R1 by"),
                                  "the second paragraph starts Full review by"),
            "no intent": (FULL.replace("Intent: ", "Aim: "), "no Intent: paragraph"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problem, out.stdout.splitlines())

    def test_recheck_report_problems(self):
        # catches: a re-check that leaves a user-path blocker open instead of
        # logging it, logs a Risk: blocker, drops or renumbers an earlier id,
        # or reopens the builder round.
        self.world({}, comments=[report(FULL)])
        cases = {
            "user path left open": (RECHECK.replace(" Logged as follow-up #61.", "").replace(
                "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: a fresh, stronger builder fixes R1 once, then one final check."),
                "R1: only a Risk: blocker goes to the fresh round; log a User path: blocker"),
            "risk logged": (RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                            "- **R3 [blocking]** still open after the re-check: no. Logged as follow-up #62.\n"
                                            "  Risk: privacy: a cook's sync token reaches a shared log."),
                            "R3: a Risk: blocker is never logged"),
            "earlier id dropped": (RECHECK.replace("- **R2 [polish]** Polish issue: #58.\n", ""),
                                   "R2: a re-check gives every earlier id its status"),
            "earlier id as new": (RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                                  "- **R3 [polish]** `a.rs:1` (Sweep) New thing. Fix: x. Polish issue: #63."),
                                  "R3: an earlier id takes a status, not a new finding"),
            "builder line at re-check": (RECHECK.replace(" Logged as follow-up #61.", "").replace(
                "VERDICT: APPROVE", "VERDICT: CHANGES").replace(
                "Next: none open. It merges by the project's merge rules.",
                "Next: the builder fixes or disputes R1 once, then one re-check."),
                "a re-check's Next: is the fresh line or none open"),
        }
        for name, (text, problem) in cases.items():
            with self.subTest(name):
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problem, out.stdout.splitlines())

    def test_private_material_is_refused(self):
        # catches: a token or a thread id reaching a public report.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        for name, leak in {"token": "ghp_" + "A1b2C3d4E5f6G7h8", "thread": "thr_" + "a1b2c3d4"}.items():
            with self.subTest(name):
                text = FULL.replace("Ran: `cargo test`", f"Ran: `cargo test` {leak}")
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertIn("private material: a token or thread id", out.stdout.splitlines())

    def test_a_recheck_raises_new_findings_only_in_changed_code_or_as_a_stated_risk(self):
        # catches: a re-check that drips a new finding on code unchanged since
        # its last read (a second surprise round), or one that drops the stated
        # exception for a security, privacy or data-loss risk there.
        self.world({}, comments=[report(FULL)])
        unchanged = "- **R4 [polish]** `src/cli.rs:12` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        risk = ("- **R4 [blocking]** `src/cli.rs:12` (Sweep) The sync token is printed. Fix: redact it.\n"
                "  Risk: privacy: a cook's sync token reaches the terminal log.")
        fresh = ("VERDICT: CHANGES", "Next: a fresh, stronger builder fixes R4 once, then one final check.")
        old_r4 = "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60."
        merge = ("VERDICT: APPROVE", "Next: none open. It merges by the project's merge rules.")
        refused = ("R4: `src/cli.rs` is unchanged since aaaaaaa; a re-check raises a new finding there "
                   "only as a Risk: security, privacy or data-loss blocker")
        cases = {
            "polish on unchanged code": (unchanged, merge, 1, refused),
            "user path on unchanged code": (risk.replace("Risk: privacy: a cook's sync token reaches the terminal log.",
                                                         "User path: a cook sees the token in the terminal."),
                                            fresh, 1, refused),
            "stated risk on unchanged code": (risk, fresh, 0, "report ok"),
            "polish on changed code": (old_r4, merge, 0, "report ok"),
        }
        for name, (line, (verdict, nxt), code, expected) in cases.items():
            with self.subTest(name):
                text = (RECHECK.replace(old_r4, line).replace("VERDICT: APPROVE", verdict)
                        .replace("Next: none open. It merges by the project's merge rules.", nxt))
                out = self.run_helper("check", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, code, out.stdout + out.stderr)
                self.assertIn(expected, out.stdout.splitlines())
        self.assertIn(["api", f"repos/{SKILLS}/compare/{OLD}...{HEAD}"], self.state()["calls"])
        self.world({"compare": {}}, comments=[report(FULL)])
        out = self.run_helper("check", self.file("r.md", RECHECK), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 2, out.stdout)
        self.assertIn("cannot read", out.stderr)

    # --- self-check: the builder's own pass --------------------------------

    def hand_back(self, code_line):
        """A synthetic builder checkout: origin/main, then one green commit adding `code_line`."""
        upstream, work = self.root / "upstream", self.root / "work"

        def git(where, *args):
            return subprocess.run(["git", "-C", str(where), "-c", "user.name=Builder", "-c",
                                   "user.email=builder@example.com", *args],
                                  check=True, capture_output=True, text=True).stdout.strip()
        for d in (upstream, work):
            if d.exists():
                subprocess.run(["rm", "-rf", str(d)], check=True)
        upstream.mkdir()
        git(upstream, "init", "-q", "-b", "main")
        (upstream / "export.py").write_text("def export():\n    pass\n")
        git(upstream, "add", "-A")
        git(upstream, "commit", "-qm", "base")
        git(self.root, "clone", "-q", str(upstream), str(work))
        git(work, "checkout", "-qb", "room/41-export")
        (work / "export.py").write_text(f"def export():\n    {code_line}\n")
        git(work, "commit", "-qam", "#41 green: export refuses an existing zip")
        return work, git(work, "rev-parse", "HEAD")

    def builder_pass(self, work, description):
        """Run build-ticket's own self-check line, as a builder fills it in."""
        skill = HELPER.parent.parent.parent / "build-ticket"
        text = (skill / "SKILL.md").read_text()
        line = re.search(r"`(python3 -I <this skill's folder>/\.\./review-ticket/scripts/review\.py "
                         r"self-check <description file>)`", text)
        self.assertIsNotNone(line, "build-ticket's SKILL.md names no self-check line")
        argv = shlex.split(line[1].replace("<this skill's folder>", str(skill))
                           .replace("<description file>", self.file("description.md", description)))
        return subprocess.run(argv, text=True, capture_output=True, env=self.env, timeout=30, cwd=work)

    def test_the_builders_own_pass_catches_a_planted_checklist_miss(self):
        # catches: a hand-back that the reviewer's checklist would send back
        # (no ticket to admit, no Rulings to mark, stale Facts, no test-rule
        # line, a token or thread id in public text) reaching review because
        # the builder's pass missed it, or build-ticket pointing at a
        # self-check that is not there.
        clean = "raise FileExistsError('cookbook.zip')"
        work, head = self.hand_back(clean)

        def description(head):
            return (f"Closes example/product#41\n\n## Summary\n\nExport refuses an existing zip.\n\n"
                    f"## Rulings\n\n1. Name the zip cookbook.zip. Why: the importer reads that name. "
                    f"Cost if wrong: low: one rename.\n\n## Facts\n\n- **Head:** `{head}`\n"
                    f"- **Tests:** `test_export_refuses`. catches: a second export overwriting the first.\n")
        good = description(head)
        out = self.builder_pass(work, good)
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout + out.stderr)
        rulings = ("## Rulings\n\n1. Name the zip cookbook.zip. Why: the importer reads that name. "
                   "Cost if wrong: low: one rename.\n\n")
        planted = {  # each: the description for this head, the code line, the one miss expected
            "no Closes line": (lambda h: description(h).replace("Closes example/product#41\n", ""), clean,
                               "no Closes line names the ticket; the review cannot start"),
            "no Rulings section": (lambda h: description(h).replace(rulings, ""), clean,
                                   "no ## Rulings section with numbered rulings or exactly none"),
            "stale head": (lambda h: description(OLD), clean, "the description does not name the head {head}"),
            "no test-rule line": (lambda h: description(h).replace(" catches: a second export overwriting the first.",
                                                                   ""), clean,
                                  "no `catches: <the bug>` or `no new test: <why>` line"),
            "token in the diff": (description, "token = '" + "ghp_" + "A1b2C3d4E5f6G7h8'",
                                  "private material (a token or thread id) in export.py"),
            "thread id in the description": (lambda h: description(h).replace("## Summary", "## Summary " + "thr_" + "a1b2c3d4"),
                                             clean, "private material (a token or thread id) in the description"),
        }
        for name, (text, code_line, expected) in planted.items():
            with self.subTest(name):
                work, head = self.hand_back(code_line)
                out = self.builder_pass(work, text(head))
                self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                self.assertEqual(out.stdout.splitlines(), ["miss: " + expected.format(head=head), "self-check: 1 miss"])
        work, head = self.hand_back(clean)
        out = self.builder_pass(work, description(head).replace(rulings, "## Rulings\n\nnone\n\n"))
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "self-check: ok"), out.stdout)
        out = self.run_helper("self-check", self.file("d.md", description(head)), "--base", "origin/gone", cwd=work)
        self.assertEqual((out.returncode, out.stdout), (2, ""), out.stdout)
        self.assertIn("cannot read origin/gone...HEAD with git", out.stderr)

    # --- post --------------------------------------------------------------

    def test_post_writes_once_and_reads_back(self):
        # catches: a report that is posted without read-back or twice.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        path = self.file("r.md", FULL)
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "posted 900"), out.stdout + out.stderr)
        again = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(again.stdout.strip(), "already posted 900")
        self.assertEqual(self.state()["writes"], 1)

    def test_post_refuses_a_failing_report_with_zero_writes(self):
        # catches: publishing a report that breaks the contract lines.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}})
        out = self.run_helper("post", self.file("r.md", FULL.replace(" Polish issue: #58.", "")),
                              "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(self.state()["writes"], 0)

    def test_lost_response_is_recovered_by_read_back(self):
        # catches: retrying a POST whose response was lost, duplicating it.
        self.world({"checks": green(OLD), "lose": True}, pr={"head": {"sha": OLD}})
        path = self.file("r.md", FULL)
        out = self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.stdout.strip(), "posted 900", out.stdout + out.stderr)
        self.run_helper("post", path, "--repo", SKILLS, "--pr", "7")
        self.assertEqual(self.state()["writes"], 1)

    def test_unconfirmed_post_is_unknown(self):
        # catches: claiming a report is posted when read-back cannot find it.
        self.world({"checks": green(OLD), "fail_post": True}, pr={"head": {"sha": OLD}})
        out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 1)
        self.assertEqual(out.stdout.strip(), "unknown: not found on read-back; read the comments before posting again")

    # --- follow-up ---------------------------------------------------------

    def follow_up(self, *extra):
        finding = self.file("finding.md", "`src/cli.rs:30` (Sweep) Help wording. Fix: say export.")
        return self.run_helper("follow-up", "--repo", PRODUCT, "--ticket", "41", "--spec", "38",
                               "--pr", f"{SKILLS}#7", "--head", OLD, "--id", "R2",
                               "--title", "Help says zip archive file", "--finding", finding, *extra)

    def test_follow_up_is_filed_once_for_triage(self):
        # catches: a polish issue filed without the triage label or its
        # Follow-up header (which triage reads), or filed twice on a retry.
        out = self.follow_up()
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "filed #70"), out.stdout + out.stderr)
        issue = self.state()["issues"][PRODUCT][0]
        self.assertEqual(issue["title"], "Help says zip archive file (polish for #41, R2)")
        self.assertEqual([x["name"] for x in issue["labels"]], ["triage: new"])
        self.assertTrue(issue["body"].startswith("Follow-up of #41 (spec #38)\n\n"))
        self.assertIn(f"Found in pull request {SKILLS}#7 at {OLD}; it is polish", issue["body"])
        self.assertEqual(self.follow_up().stdout.strip(), "already filed #70")
        self.assertEqual(self.state()["writes"], 1)

    def test_logged_blocker_follow_up(self):
        # catches: a logged blocker filed with the polish wording or without
        # its User path: line.
        out = self.follow_up("--logged", "re-check", "--user-path", "a cook exports twice; one is lost")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "filed #70"), out.stdout + out.stderr)
        issue = self.state()["issues"][PRODUCT][0]
        self.assertEqual(issue["title"], "Help says zip archive file (follow-up for #41, R2)")
        self.assertIn("User path: a cook exports twice; one is lost\n", issue["body"])
        self.assertIn(f"Still open after the re-check of pull request {SKILLS}#7 at {OLD}; logged, "
                      "so it did not block the merge.", issue["body"])

    def test_follow_up_label_must_be_unique(self):
        # catches: filing under a guessed label when the settings name none
        # or two.
        for name, labels in {"none": LABELS.replace("| `needs-triage` | `triage: new` | Sort it |\n", ""),
                             "two": LABELS + "| `needs-triage` | `new` | Again |\n"}.items():
            with self.subTest(name):
                self.world({"files": {f"{PRODUCT}@main:docs/agents/triage-labels.md": labels,
                                      f"{SKILLS}@main:docs/agents/fleet.md": FLEET}})
                out = self.follow_up()
                self.assertEqual(out.returncode, 2)
                self.assertIn("needs-triage label", out.stderr)
                self.assertEqual(self.state()["writes"], 0)


    # --- re-check round fixes (WizSkills #19 review) -----------------------

    def parked_world(self, decision=None, head=NEWER, author="owner", extra=None):
        fresh = RECHECK.replace("VERDICT: APPROVE", "VERDICT: CHANGES").replace(
            "- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.").replace(
            "Next: none open. It merges by the project's merge rules.",
            "Next: a fresh, stronger builder fixes R3 once, then one final check.")
        parked = fresh.replace(HEAD, NEWER).replace("Re-check of R1, R3", "Final check of R3").replace(
            "Next: a fresh, stronger builder fixes R3 once, then one final check.",
            "Next: park R3 as a decision for Jake.")
        comments = [report(FULL), report(fresh), report(parked)]
        if decision:
            comments.append({"body": decision, "user": {"login": author}})
        comments += extra or []
        self.world({"checks": {**green(NEWER), **green("d" * 40)}}, pr={"head": {"sha": head}}, comments=comments)
        return parked

    def test_fix_once_more_decision_admits_a_check_of_the_new_head(self):
        # catches (R1): the park stop ignoring Jake's relayed fix-once-more
        # answer, so the reviewer can never check the requested fix.
        self.parked_world(f"**Orchestrator decision:** fix once more: R3 at {NEWER}. Why: one line.", head="d" * 40)
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith(f"review final #7 at {'d' * 40}"), out.stdout)
        self.assertIn(f"last read {NEWER}; open R3", out.stdout)

    def test_log_and_merge_decision_admits_one_same_head_polish_report(self):
        # catches (R1): the park stop refusing the authorized same-head report
        # that grades the parked finding as polish with the decision's issue.
        parked = self.parked_world(f"**Orchestrator decision:** log and merge: R3 at {NEWER}. Polish issues: #64. "
                                   "Why: the log stays local.")
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertTrue(out.stdout.startswith(f"review log-and-merge #7 at {NEWER}"), out.stdout)
        approve = parked.replace("VERDICT: CHANGES", "VERDICT: APPROVE").replace(
            "- **R3 [blocking]** still open after the re-check: still logged.\n"
            "  Risk: privacy: a cook's sync token reaches a shared log.",
            "- **R3 [polish]** Polish issue: #64.").replace(
            "Next: park R3 as a decision for Jake.", "Next: none open. It merges by the project's merge rules.").replace(
            "- **R4 [polish]** `src/export.rs:52` (Sweep) Typo. Fix: file exists. Polish issue: #60.",
            "- **R4 [polish]** Polish issue: #60.")
        posted = self.run_helper("post", self.file("approve.md", approve), "--repo", SKILLS, "--pr", "7")
        self.assertEqual(posted.stdout.strip(), "posted 904", posted.stdout + posted.stderr)
        wrong = approve.replace("Polish issue: #64.", "Polish issue: #65.")
        self.world({**self.state(), "comments": {f"{SKILLS}#7": self.state()["comments"][f"{SKILLS}#7"][:4]}})
        out = self.run_helper("check", self.file("wrong.md", wrong), "--repo", SKILLS, "--pr", "7")
        self.assertIn("R3: the decision grades it polish with Polish issue: #64", out.stdout.splitlines())

    def test_unmatched_or_unauthorized_decisions_keep_the_park(self):
        # catches (R1): a decision from a non-record author, for other ids or
        # for another head releasing a parked finding.
        for name, (decision, author) in {
            "stranger": (f"**Orchestrator decision:** fix once more: R3 at {NEWER}. Why: x.", "stranger"),
            "other ids": (f"**Orchestrator decision:** fix once more: R1 at {NEWER}. Why: x.", "owner"),
            "other head": (f"**Orchestrator decision:** fix once more: R3 at {HEAD}. Why: x.", "owner"),
        }.items():
            with self.subTest(name):
                self.parked_world(decision, head="d" * 40, author=author)
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout.strip()), (1, "stop: R3 is parked as a decision for Jake"))

    def test_an_earlier_blocker_cannot_be_closed_as_polish(self):
        # catches (R2): a re-check approving an unresolved Risk: blocker by
        # giving it a polish status or a polish grade.
        cases = {
            "polish status": RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                             "- **R3 [blocking]** Polish issue: #62."),
            "polish grade": RECHECK.replace("- **R3 [blocking]** resolved at bbbbbbb: the log line is redacted.",
                                            "- **R3 [polish]** Polish issue: #62."),
        }
        problems = {"polish status": "R3: a blocker's status is resolved, withdrawn, still open, disputed or logged",
                    "polish grade": "R3: keeps its earlier grade, blocking"}
        for name, text in cases.items():
            with self.subTest(name):
                self.world({}, comments=[report(FULL)])
                out = self.run_helper("post", self.file("r.md", text), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertIn(problems[name], out.stdout.splitlines())
                self.assertEqual(self.state()["writes"], 0)

    def test_v2_ruling_mark_refusals(self):
        # catches (R2): two rulings overturned as one finding, or Rulings:
        # none. beside a mark, both refused by the v2 check.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}, "body": DESCRIPTION.replace(
            "1. Name the zip", "2. Keep one zip. Why: one file. Cost if wrong: low: two files.\n1. Name the zip")})
        two = FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.",
                           "- **Ruling 1** overturned as R1: wrong.\n- **Ruling 2** overturned as R1: wrong.")
        out = self.run_helper("check", self.file("r.md", two), "--repo", SKILLS, "--pr", "7")
        self.assertIn("R1: named by two overturned rulings", out.stdout.splitlines())
        none = FULL.replace("- **Ruling 1** upheld: the importer reads cookbook.zip.",
                            "- **Ruling 1** upheld: ok.\n- **Ruling 2** upheld: ok.\n\nRulings: none.")
        out = self.run_helper("check", self.file("r.md", none), "--repo", SKILLS, "--pr", "7")
        self.assertIn("Rulings: none. stands beside a ruling mark", out.stdout.splitlines())

    def test_record_author_row_is_parsed_whole(self):
        # catches (R3): a malformed row with a missing comma, a second row or
        # an extra cell still supplying trusted authors.
        row = "| Record authors | `example[bot]`, `owner` |\n"
        for name, bad in {"missing comma": "| Record authors | `example[bot]` `owner` |\n",
                          "two rows": row + "| Record authors | `owner` |\n",
                          "extra cell": "| Record authors | `example[bot]`, `owner` | extra |\n"}.items():
            with self.subTest(name):
                self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": FLEET.replace(row, bad)}},
                           comments=[report(FULL.replace(OLD, HEAD))])
                out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
                self.assertEqual((out.returncode, out.stdout), (2, ""), out.stdout)
                self.assertIn("record authors", out.stderr)

    def test_additional_required_check_outside_the_table(self):
        # catches (R4): an OpenWiz-shaped fleet.md whose privacy gate is named
        # outside the table being reviewed with privacy failed.
        fleet = FLEET.replace("| `check` | Every suite | Pull requests to `main` |\n",
                              "| `ci` | Every lane | `main`, `release-*` |\n\n"
                              "**Additional public check: `privacy` (O3).** It checks the public tree.\n")
        checks = {HEAD: [{"name": "ci", "status": "completed", "conclusion": "success"},
                         {"name": "privacy", "status": "completed", "conclusion": "failure"}]}
        self.world({"files": {f"{SKILLS}@main:docs/agents/fleet.md": fleet}, "checks": checks})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (1, f"stop: privacy is not green at {HEAD}"))

    def test_identical_text_from_anyone_else_is_not_a_post(self):
        # catches (R5): an ordinary comment with the report's text ending the
        # post as already posted, leaving the fleet no recognized verdict.
        self.world({"checks": green(OLD)}, pr={"head": {"sha": OLD}},
                   comments=[{"body": FULL, "user": {"login": "stranger"}}])
        out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
        self.assertEqual((out.returncode, out.stdout.strip()), (0, "posted 901"), out.stdout + out.stderr)
        self.assertEqual(self.state()["writes"], 1)

    def test_commands_are_bound_to_the_assigned_head(self):
        # catches (R6): reviewing or posting for a head other than the one the
        # fleet assigned.
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--head", NEWER)
        self.assertEqual((out.returncode, out.stdout.strip()),
                         (1, f"stop: the head is {HEAD}, not the assigned {NEWER}"))

    def test_pin_reads_one_snapshot(self):
        # catches (R6): readiness and ticket from one pull-request read joined
        # with the head of a later read.
        later = {**self.state()["pulls"]["7"], "draft": True, "head": {"sha": NEWER}, "body": "Closes #99\n"}
        self.world({"pull_sequence": [self.state()["pulls"]["7"], later] * 3, "checks": {**green(HEAD), **green(NEWER)}})
        out = self.run_helper("pin", "--repo", SKILLS, "--pr", "7", "--head", HEAD)
        self.assertEqual(out.stdout.strip(), f"review full #7 at {HEAD}; ticket {PRODUCT}#41; checks check")

    def test_post_repeats_admission_before_writing(self):
        # catches (R6): handing back a verdict after the head became draft or
        # its required check failed.
        for name, (pr, checks) in {
            "draft": ({"draft": True, "head": {"sha": OLD}}, green(OLD)),
            "failed check": ({"head": {"sha": OLD}},
                             {OLD: [{"name": "check", "status": "completed", "conclusion": "failure"}]}),
        }.items():
            with self.subTest(name):
                self.world({"checks": checks}, pr=pr)
                out = self.run_helper("post", self.file("r.md", FULL), "--repo", SKILLS, "--pr", "7")
                self.assertEqual(out.returncode, 1, out.stdout)
                self.assertTrue(out.stdout.startswith("stop: "), out.stdout)
                self.assertEqual(self.state()["writes"], 0)


if __name__ == "__main__":
    unittest.main()
