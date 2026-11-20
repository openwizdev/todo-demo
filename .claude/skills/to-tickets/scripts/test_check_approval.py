#!/usr/bin/env python3
"""Synthetic posted-approval and machine-approval fixtures; no network or live
session data.

Run: python3 skills/to-tickets/scripts/test_check_approval.py
CHECK_APPROVAL_SH can name another checker (including an always-pass mutant).
The two six-ticket shapes reproduce #172/#330's bad and corrected records;
people, titles, comment IDs and fingerprints below are synthetic.
"""
import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
CHECKER = Path(os.environ.get("CHECK_APPROVAL_SH", HERE / "check-approval.sh"))
LABELS = """# Triage labels

## Labels

| Role | Label here | Meaning |
| --- | --- | --- |
| `ready-for-agent` | `ready-for-agent` | Agent ticket |
| `ready-for-human` | `ready-for-human` | Human ticket |
"""
# #717: the factory's identity, the Record authors row launch-fleet reads.
FLEET = """# Fleet settings

## GitHub identity

| Setting | Value |
| --- | --- |
| App | Synthetic App |
| Record authors | `openwiz[bot]`, `synthetic-owner` |

## Standing merge rules
"""
FACTORY = {"login": "openwiz[bot]"}
OUTSIDER = {"login": "synthetic-outsider"}


def fixture(spec, label="ready-for-agent"):
    numbers = [173, 174, 176, 177, 180, 181] if spec == 172 else list(range(332, 338))
    rows = [f"| #{n} | Synthetic ticket {n} | none | {label} |" for n in numbers]
    body = (
        '**Plan graph approved by Robin, 2026-11-01, revision 2:** approved as proposed.\n'
        'Private record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002\n\n'
        "| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n"
        + "\n".join(rows)
        + "\n\nFingerprint: `" + "a" * 64 + "`\n\n"
        '<details><summary>Revision text</summary>\n\n```text\n'
        'plan-graph revision v2\n```\n\n</details>\n'
    )
    return {
        "graph": {"subIssues": {"totalCount": 6, "nodes": [{"number": n} for n in numbers]}},
        "comments": [[{"id": 100, "user": dict(FACTORY), "body": body}]],
        "labels_doc": LABELS,
        "fleet_doc": FLEET,
        "tracker_doc": "# Tracker\n\n- **Private records:** `jparker2006/ClosedWiz`, permanently private.\n",
        "repo": {"isPrivate": False},
    }


def state_table(world):
    body = world["comments"][0][0]["body"]
    lines = []
    for line in body.splitlines():
        if line.startswith("| Ticket |"):
            line = "| Ticket | Title | State |"
        elif line.startswith("| ---"):
            line = "| --- | --- | --- |"
        elif line.startswith("| #"):
            cols = line.split("|")
            # #172's shape has five closed and one open ticket; #330 is all open.
            state = "closed" if "#17" in cols[1] or "#180" in cols[1] else "open"
            line = f"| {cols[1].strip()} | {cols[2].strip()} | {state} |"
        lines.append(line)
    world["comments"][0][0]["body"] = "\n".join(lines) + "\n"
    return world


FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
w = json.loads(Path(os.environ["FAKE_WORLD"]).read_text())
n = os.environ["FAKE_SPEC"]
if args == ["repo", "view", "--json", "isPrivate"]:
    key = "repo"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"]:
    key = "labels_doc"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"]:
    key = "tracker_doc"
elif args == ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"]:
    key = "fleet_doc"
elif args == ["issue", "view", n, "--json", "subIssues"]:
    key = "graph"
elif args == ["api", "--paginate", "repos/{owner}/{repo}/issues/" + n + "/comments?per_page=100"]:
    key = "comments"
else:
    sys.exit("unexpected gh call: " + repr(args))
if w.get("fail") == key:
    sys.exit("planted read failure")
if w.get("empty") == key:
    sys.exit(0)
if key in ("tracker_doc", "fleet_doc"):
    print(w[key], end="")
elif key == "labels_doc":
    print(Path(os.environ["FAKE_LABELS_FILE"]).read_text() if "FAKE_LABELS_FILE" in os.environ else w[key], end="")
elif key == "comments":
    for page in w[key]:
        print(json.dumps(page))
else:
    print(json.dumps(w[key]))
'''


class ApprovalTest(unittest.TestCase):
    def test_documented_handoff_from_plugin_consumer(self):
        with tempfile.TemporaryDirectory(prefix="approval-consumer-") as folder:
            tmp = Path(folder)
            installed = tmp / "plugin cache" / "to-tickets"
            (installed / "scripts").mkdir(parents=True)
            shutil.copy2(HERE.parent / "SKILL.md", installed / "SKILL.md")
            shutil.copy2(CHECKER, installed / "scripts" / "check-approval.sh")
            commands = re.findall(r'`(sh [^`]*scripts/check-approval\.sh"? <spec>)`',
                                  (installed / "SKILL.md").read_text())
            self.assertEqual(len(commands), 1)
            command = commands[0].replace("<this skill's folder>", str(installed)).replace("<spec>", "172")

            consumer = tmp / "consumer"
            settings = consumer / "docs" / "agents" / "triage-labels.md"
            settings.parent.mkdir(parents=True)
            settings.write_text(LABELS.replace("| `ready-for-agent` | `ready-for-agent` |",
                                               "| `ready-for-agent` | `consumer-ready` |"))
            world = fixture(172)
            world["comments"][0][0]["body"] = world["comments"][0][0]["body"].replace(
                "ready-for-agent", "consumer-ready")
            (consumer / "world.json").write_text(json.dumps(world))
            self.assertFalse((consumer / "skills").exists())
            fake_bin = tmp / "bin"
            fake_bin.mkdir()
            (fake_bin / "gh").write_text(FAKE_GH)
            (fake_bin / "gh").chmod(0o700)
            env = dict(os.environ, PATH=str(fake_bin) + os.pathsep + os.environ["PATH"],
                       FAKE_WORLD="world.json", FAKE_LOG=str(tmp / "calls"), FAKE_SPEC="172",
                       FAKE_LABELS_FILE="docs/agents/triage-labels.md")
            result = subprocess.run(["sh", "-c", command], cwd=consumer, env=env,
                                    text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "check-approval.sh: #172 approval table is valid\n")
            self.assertEqual(result.stderr, "")
            self.assertEqual([json.loads(line) for line in (tmp / "calls").read_text().splitlines()], [
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"],
                ["issue", "view", "172", "--json", "subIssues"],
                ["api", "--paginate", "repos/{owner}/{repo}/issues/172/comments?per_page=100"],
                ["repo", "view", "--json", "isPrivate"],
            ])

    def run_check(self, world, spec=172, status=0, reason=None, argument=None):
        with tempfile.TemporaryDirectory(prefix="approval-fixture-") as folder:
            tmp = Path(folder)
            (tmp / "gh").write_text(FAKE_GH)
            (tmp / "gh").chmod(0o700)
            (tmp / "world.json").write_text(json.dumps(world))
            env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ["PATH"],
                       FAKE_WORLD=str(tmp / "world.json"), FAKE_LOG=str(tmp / "calls"),
                       FAKE_SPEC=str(spec))
            result = subprocess.run(["sh", str(CHECKER), str(spec) if argument is None else argument],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, status, result.stdout + result.stderr)
            if status == 0:
                self.assertEqual(result.stdout, f"check-approval.sh: #{spec} approval table is valid\n")
                self.assertEqual(result.stderr, "")
            else:
                self.assertEqual(result.stdout, "")
                self.assertIn(reason, result.stderr)
            calls = [json.loads(line) for line in (tmp / "calls").read_text().splitlines()] if (tmp / "calls").exists() else []
            if status == 0:
                self.assertEqual(calls, [
                    ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/triage-labels.md"],
                    ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/issue-tracker.md"],
                ["api", "-H", "Accept: application/vnd.github.raw+json", "repos/{owner}/{repo}/contents/docs/agents/fleet.md"],
                    ["issue", "view", str(spec), "--json", "subIssues"],
                    ["api", "--paginate", f"repos/{{owner}}/{{repo}}/issues/{spec}/comments?per_page=100"],
                    ["repo", "view", "--json", "isPrivate"],
                ])
            return calls

    def test_configured_records_repository_differs_from_current_repository(self):
        w = fixture(172)
        w['tracker_doc'] = '# Tracker\n\n- **Private records:** `synthetic-records/archive`, permanently private.\n'
        w['comments'][0][0]['body'] = w['comments'][0][0]['body'].replace(
            'jparker2006/ClosedWiz', 'synthetic-records/archive')
        self.run_check(w)
        w['comments'][0][0]['body'] = w['comments'][0][0]['body'].replace(
            'synthetic-records/archive', 'unrelated-owner/archive')
        self.run_check(w, status=1, reason='public approval form')

    def test_missing_malformed_or_unreadable_records_configuration_refuses(self):
        for text in ('', '- **Private records:** `owner`\n',
                     '- **Private records:** `../archive`\n',
                     '- **Private records:** `owner/repo`\n' * 2):
            w = fixture(172)
            w['tracker_doc'] = text
            self.run_check(w, status=1, reason='private records')
        w = fixture(172)
        w['fail'] = 'tracker_doc'
        self.run_check(w, status=1, reason='private records')

    def test_public_and_private_approval_forms(self):
        public = fixture(172)["comments"][0][0]["body"]
        legacy = public.replace(
            "approved as proposed.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002",
            '\"approve\"')
        for private in (False, True):
            for body in (public, legacy):
                with self.subTest(private=private, legacy=body == legacy):
                    w = fixture(172)
                    w["repo"] = {"isPrivate": private}
                    w["comments"][0][0]["body"] = body
                    refused = not private and body == legacy
                    self.run_check(w, status=int(refused), reason="public approval form")

    def test_public_form_refusals(self):
        public = fixture(172)["comments"][0][0]["body"]
        pointer = "https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002"
        for before, after in (
            ("approved as proposed.", '\"approve\"'),
            ("approved as proposed.", "“approve”"),
            ("approved as proposed.", " "),
            ("Private record: " + pointer, ""),
            ("Private record: " + pointer, "\nPrivate record: " + pointer),
            (pointer, pointer.replace("ClosedWiz", "OpenWiz")),
            (pointer, pointer.replace("9001#", "09001#")),
            (pointer, pointer.replace("9000000002", "09000000002")),
            (pointer, pointer.split("#")[0]),
            (pointer, pointer + " extra"),
            ("2026-11-01", "today"),
            ("revision 2", "revision 0"),
        ):
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = public.replace(before, after, 1)
                self.run_check(w, status=1, reason="public approval form")
        for tail in ('\nRobin: \"approve\"\n', '\n**Robin:**\n> approve\n',
                     '\nThread thr_synapproval1\n'):
            with self.subTest(tail=tail):
                w = fixture(172)
                w["comments"][0][0]["body"] += tail
                self.run_check(w, status=1, reason="public approval form")
        w = fixture(172)
        w["comments"][0][0]["body"] = public.replace("/issues/9001#", "/pull/9001#")
        self.run_check(w)

    def test_attributed_quote_forms_throughout_comment(self):
        # R1: these are private records even after a valid public opening.
        # Check all T2 double-quote spellings, including escaped wire-like text.
        for lead in ("Robin:", "**Robin:**",
                     "**Plan graph approved by Robin, 2026-11-01, revision 1:**"):
            for quote in ('"', '“', '”', '\\"', '\\“', '\\”'):
                for private in (False, True, None):
                    with self.subTest(lead=lead, quote=quote, private=private):
                        w = fixture(172)
                        w["repo"] = {} if private is None else {"isPrivate": private}
                        w["comments"][0][0]["body"] += f"\n{lead} {quote}approve{quote}\n"
                        self.run_check(w, status=0 if private else 1,
                                       reason="public approval form")

    def test_unknown_visibility_is_public(self):
        for value in ({}, {"isPrivate": "true"}, {"isPrivate": None}, [],
                      [{"isPrivate": True}]):
            with self.subTest(value=value):
                w = fixture(172)
                w["repo"] = value
                self.run_check(w)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                    "approved as proposed.", '\"approve\"')
                self.run_check(w, status=1, reason="public approval form")
        for fault in ("fail", "empty"):
            w = fixture(172)
            w[fault] = "repo"
            self.run_check(w)
            w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                "approved as proposed.", '\"approve\"')
            self.run_check(w, status=1, reason="public approval form")

    def test_latest_quoting_record_cannot_fall_back(self):
        w = fixture(172)
        latest = copy.deepcopy(w["comments"][0][0])
        latest["id"] = 102
        latest["body"] = latest["body"].replace("approved as proposed.", '\"approve\"')
        w["comments"].append([latest, {"id": 103, "user": dict(FACTORY), "body": "Progress only"}])
        self.run_check(w, status=1, reason="public approval form")

    def test_public_comment_templates(self):
        root = HERE.parents[2]
        found = []
        for name in ("to-spec", "to-tickets", "grill", "handoff", "setup"):
            for path in (root / "skills" / name).rglob("*.md"):
                text = path.read_text()
                self.assertNotIn('"<their words, exactly>"', text, str(path))
                if name == "to-tickets" and path.name == "changes.md":
                    c2 = text.split("**A wording-only change (C2).**", 1)[1].split(
                        "\nThe merges and their files,", 1)[0]
                    with self.subTest(path=str(path), rule="C2 source"):
                        self.assertNotRegex(c2, r'Jake[^"\n]*: *["“”]')
                    with self.subTest(path=str(path), rule="C2 standing approval"):
                        self.assertNotRegex(c2, r'["“”][^"“”]+["“”] as the user.s words')
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if re.search(r"\*\*(?:Spec confirmed|Plan graph approved|Approved on its own) by ", line):
                        with self.subTest(path=str(path), line=i + 1):
                            found.append(line)
                            self.assertTrue(line.startswith("**"), "approval templates need their own lines")
                            self.assertNotRegex(line, '["“”]')
                            self.assertTrue(lines[i + 1].startswith("Private record: "))
        self.assertEqual(len(found), 5)

    def test_historical_shapes(self):
        for spec in (172, 330):
            with self.subTest(spec=spec, shape="State"):
                self.run_check(state_table(fixture(spec)), spec, 1, "columns")
            with self.subTest(spec=spec, shape="corrected"):
                self.run_check(fixture(spec), spec)

    def test_trailing_table_whitespace(self):
        for suffix in (" ", "\t", " \t\r"):
            with self.subTest(suffix=repr(suffix)):
                w = fixture(172)
                w["comments"][0][0]["body"] = "\n".join(
                    line + suffix if line.startswith("|") else line
                    for line in w["comments"][0][0]["body"].splitlines())
                self.run_check(w)

    def test_escaped_title_pipes(self):
        for title in (r"Synthetic left \| right", r"Synthetic left \| middle \| right",
                      r"Synthetic backslashes \\\| right"):
            with self.subTest(title=title):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
                    "Synthetic ticket 173", title)
                self.run_check(w)

    def test_unescaped_extra_cells_and_escaped_closing_pipe(self):
        for before, after in (
            ("Synthetic ticket 173", "Synthetic left | right"),
            ("Synthetic ticket 173", r"Synthetic backslashes \\| right"),
            ("none | ready-for-agent |", "none | ready-for-agent \\|"),
        ):
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason="table")

    def test_complete_unique_ticket_set(self):
        for name, edit in [
            ("missing", lambda lines: lines.pop(5)),
            ("duplicate", lambda lines: lines.insert(5, lines[5])),
            ("foreign", lambda lines: lines.__setitem__(5, lines[5].replace("#173", "#999"))),
        ]:
            with self.subTest(name=name):
                w = fixture(172)
                lines = w["comments"][0][0]["body"].splitlines()
                edit(lines)
                w["comments"][0][0]["body"] = "\n".join(lines)
                self.run_check(w, status=1, reason="tickets")

    def test_labels_and_columns(self):
        for before, after in [
            ("ready-for-agent", "open"),
            ("ready-for-agent", "ready-for-agent-extra"),
            ("ready-for-agent", "ready-for-\u0430gent"),
            ("ready-for-agent", "Held"),
            ("ready-for-agent", "held-extra"),
            ("ready-for-agent", "h\u0435ld"),
            ("ready-for-agent", "`held`"),
            ("Blocked by | Label", "Label | Blocked by"),
            ("Blocked by | Label", "Blocked by | State | Label"),
            ("none | ready-for-agent", "none | open | ready-for-agent"),
            ("| #173", "| [#173](https://example.invalid/173)"),
            ("| #173", "| #0173"),
        ]:
            with self.subTest(after=after):
                w = fixture(172)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason="table")
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace("ready-for-agent", "ready-for-human", 1)
        self.run_check(w)

    def test_held_row_is_valid(self):
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
            "ready-for-agent", "held", 1)
        self.run_check(w)

    def test_mixed_and_all_held_rows(self):
        w = fixture(172)
        w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(
            "ready-for-agent", "held", 1).replace("ready-for-agent", "ready-for-human", 1)
        self.run_check(w)
        self.run_check(fixture(172, label="held"))

    def test_held_does_not_mask_invalid_fields(self):
        for before, after, reason in (
            ("Synthetic ticket 173", "", "row needs"),
            ("none | held", " | held", "row needs"),
            ("| #173", "| #0173", "row needs"),
            ("| #173", "| #174", "tickets"),
            ("| #173", "| #999", "tickets"),
            ("| #173 | Synthetic ticket 173 | none | held |\n", "", "tickets"),
            ("Blocked by | Label", "Label | Blocked by", "columns"),
            ("#issuecomment-9000000002", "", "public approval form"),
        ):
            with self.subTest(after=after, reason=reason):
                w = fixture(172, label="held")
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(before, after)
                self.run_check(w, status=1, reason=reason)
        for read in ("labels_doc", "graph", "comments"):
            with self.subTest(read=read):
                w = fixture(172, label="held")
                w["fail"] = read
                self.run_check(w, status=1, reason="cannot read")
        w = fixture(172, label="held")
        w["labels_doc"] = ""
        self.run_check(w, status=1, reason="labels")

    def test_project_ready_label_mapping(self):
        for role, name in (("ready-for-agent", "ready: agent"), ("ready-for-human", "ready: human")):
            with self.subTest(role=role, shape="mapped label"):
                w = fixture(172)
                w["labels_doc"] = LABELS.replace(f"| `{role}` | `{role}` |", f"| `{role}` | `{name}` |")
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace("ready-for-agent", name)
                self.run_check(w)
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(name, "held", 1)
                self.run_check(w)
            with self.subTest(role=role, shape="unmapped role name"):
                w["comments"][0][0]["body"] = w["comments"][0][0]["body"].replace(name, role)
                self.run_check(w, status=1, reason="ready label")

    def test_ready_label_mapping_must_be_readable_and_complete(self):
        for doc in ("", LABELS.replace("## Labels", "## Example"),
                    LABELS.replace("| `ready-for-human` | `ready-for-human` | Human ticket |", ""),
                    LABELS.replace("| `ready-for-agent` | `ready-for-agent` |", "| `ready-for-agent` | `` |"),
                    LABELS + "| `ready-for-agent` | `other` | Duplicate |\n"):
            with self.subTest(doc=doc):
                w = fixture(172)
                w["labels_doc"] = doc
                self.run_check(w, status=1, reason="labels")
        w = fixture(172)
        w["fail"] = "labels_doc"
        self.run_check(w, status=1, reason="labels")

    def test_only_operative_labels_table_is_read(self):
        w = fixture(172)
        w["labels_doc"] = ("# Examples\n| `ready-for-agent` | `wrong` | Example |\n" + LABELS
                           + "\n## References\n| `ready-for-human` | `wrong` | Example |\n")
        self.run_check(w)

    def test_latest_approval_not_latest_comment_or_revision(self):
        w = fixture(172)
        old = copy.deepcopy(w["comments"][0][0])
        state_table(w)
        # A later revision number in an older approval must not hide the bad newest record.
        old["id"] = 99
        old["body"] = old["body"].replace("revision 2", "revision 9")
        w["comments"] = [[w["comments"][0][0]], [old, {"id": 101, "user": dict(FACTORY), "body": "Progress only"}]]
        self.run_check(w, status=1, reason="columns")
        w["comments"][1].append({"id": 102, "user": dict(FACTORY), "body": fixture(172)["comments"][0][0]["body"]})
        self.run_check(w)

    def test_no_or_multiple_or_fenced_tables(self):
        for mode in ("no-approval", "no-table", "twice", "fenced", "indented"):
            with self.subTest(mode=mode):
                w = fixture(172)
                body = w["comments"][0][0]["body"]
                if mode == "no-approval":
                    w["comments"] = [[]]
                elif mode == "no-table":
                    w["comments"][0][0]["body"] = body.split("\n\n")[0]
                elif mode == "twice":
                    w["comments"][0][0]["body"] = body + "\n" + body
                elif mode == "fenced":
                    w["comments"][0][0]["body"] = body.split("\n\n")[0] + "\n\n```md\n" + body + "\n```"
                else:
                    w["comments"][0][0]["body"] = body.replace("\n|", "\n |")
                self.run_check(w, status=1, reason="approval" if mode == "no-approval" else "table")

    def test_unreadable_or_partial_reads(self):
        cases = []
        for read in ("graph", "comments"):
            for fault in ("fail", "empty"):
                w = fixture(172)
                w[fault] = read
                cases.append((f"{fault}-{read}", w))
        for graph in ({}, {"subIssues": {"totalCount": 7, "nodes": [{"number": 173}]}},
                      {"subIssues": {"totalCount": 2, "nodes": [{"number": 173}, {"number": 173}]}}):
            w = fixture(172)
            w["graph"] = graph
            cases.append(("graph-shape", w))
        for comments in ([], [{"message": "error"}], [[{"id": 1}]],
                         [[{"id": 1, "body": "Progress"}], [{"id": 1, "body": "Progress"}]]):
            w = fixture(172)
            w["comments"] = comments
            cases.append(("comments-shape", w))
        for name, w in cases:
            with self.subTest(name=name):
                self.run_check(w, status=1, reason="cannot read")

    def test_only_record_authors_approve(self):
        # #717 catches: a plan approval posted by anyone who can comment on a
        # public spec counted, so an outsider could approve a plan graph, or
        # hide the factory's refusal behind a newer valid-looking approval.
        good = fixture(172)["comments"][0][0]["body"]
        bad = state_table(fixture(172))["comments"][0][0]["body"]
        # REST names the App `openwiz[bot]`: a bare `openwiz`, even typed Bot,
        # is never the App on this REST read (orchestrator ruling on #717).
        for user in (OUTSIDER, {"login": "openwiz"}, {"login": "openwiz", "type": "Bot"},
                     {"login": "openwiz[bot]x"}, {"login": None},
                     {}, None, "openwiz[bot]", "missing"):
            with self.subTest(user=user, case="the outsider's approval is the only one"):
                w = fixture(172)
                if user == "missing":
                    del w["comments"][0][0]["user"]
                else:
                    w["comments"][0][0]["user"] = user
                self.run_check(w, status=1, reason="no posted plan graph approval")
            with self.subTest(user=user, case="a newer outsider approval hides a refused one"):
                w = fixture(172)
                w["comments"][0][0]["body"] = bad
                w["comments"].append([{"id": 101, "user": user, "body": good}])
                if user == "missing":
                    del w["comments"][1][0]["user"]
                self.run_check(w, status=1, reason="columns")
        # The factory's own records still count, its logins in any case.
        for login in ("openwiz[bot]", "OpenWiz[bot]", "synthetic-owner", "SYNTHETIC-OWNER"):
            with self.subTest(login=login):
                w = fixture(172)
                w["comments"][0][0]["user"] = {"login": login}
                w["comments"].append([{"id": 101, "user": OUTSIDER, "body": bad}])
                self.run_check(w)

    def test_record_authors_setting_must_be_whole(self):
        # #717 catches: a reader that trusts everyone, or keeps the logins
        # that did parse, when the Record authors row is missing or malformed.
        row = "| Record authors | `openwiz[bot]`, `synthetic-owner` |"
        for doc in ("", FLEET.replace(row + "\n", ""),
                    FLEET.replace("## GitHub identity", "## Example"),
                    FLEET.replace(row, "| Record authors | |"),
                    FLEET.replace(row, "| Record authors | openwiz[bot] |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`, synthetic-owner |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`; `synthetic-owner` |"),
                    FLEET.replace(row, "| Record authors | `openwiz[bot]`, `-bad` |"),
                    FLEET.replace(row, row + " extra |"),
                    FLEET.replace(row, row + "\n" + row)):
            with self.subTest(doc=doc):
                w = fixture(172)
                w["fleet_doc"] = doc
                self.run_check(w, status=1, reason="record authors")
        w = fixture(172)
        w["fail"] = "fleet_doc"
        self.run_check(w, status=1, reason="record authors")

    def test_bad_arguments_never_read(self):
        for argument in ("0", "-1", "172x", "01", ""):
            self.assertEqual(self.run_check(fixture(172), status=2, reason="usage:", argument=argument), [])


# The machine plan approval (#1339, J202): a plan cut from a synthetic grill
# by to-spec and to-tickets, approved by approve.py's own checks with no human
# step. Its revision text comes from the real revision.sh over the folder's
# fake gh, so the fingerprint is never computed the way approve.py computes it.
APPROVE = HERE / "approve.py"
REVISION = HERE.parent / "revision.sh"
FAKE_REVISION_GH = HERE.parent / "test" / "fake_gh.py"
GRILL = "https://github.com/synthetic-owner/synthetic-private/issues/77#issuecomment-7700000001"
SPEC = 9100
SPEC_BODY = ("## Problem Statement\n\nFrom the synthetic grill `docs/grills/2026-11-19-export.md`: "
             "a user can't take their widgets out.\n\n## Solution\n\nAn export button and an export command.\n")


def body(n, size, owned, relies="nothing", links=(), done_by=None):
    """One ticket body as tickets.md asks for it."""
    parts = [f"## Parent\n\nTicket of spec #{SPEC}. Size: {size}.\n",
             f"## What to build\n\nSynthetic work for #{n}.\n"]
    if done_by:
        parts.append(f"## Done by\n\n{done_by}\n")
    else:
        parts.append("## Owned paths\n\n" + "".join(f"- {line}\n" for line in owned)
                     + f"\n**Relies on:** {relies}\n")
    parts.append("## Links\n\n" + ("".join(f"- {line}\n" for line in links) if links else "none\n"))
    parts.append("## Acceptance criteria\n\n- [ ] Synthetic criterion.\n")
    return "\n".join(parts)


def plan():
    """The synthetic plan: a contract first, two builders on it, a chained
    builder inside a blocker's folder, two parallel tickets on separate lines
    of one shared file, and a person's live check last."""
    tickets = [
        (9101, "Write the export contract", [], body(9101, "S", ["`contracts/export.v1.md`"])),
        (9102, "Show the export button", [9101],
         body(9102, "M", ["`app/export/` in `synthetic-owner/synthetic-repo`"], "`contracts/export.v1.md`",
              ["#9101 real: the export record shape, which the button writes"])),
        (9103, "Add the export command", [9101],
         body(9103, "M", ["`cli/export.py`"], "`docs/existing.md`",
              ["#9101 real: the export record shape, which the command prints"])),
        (9104, "List export in the fleet settings", [],
         body(9104, "S", ["`docs/agents/fleet.md` (shared: the export row only)"])),
        (9105, "List import in the fleet settings", [],
         body(9105, "S", ["`docs/agents/fleet.md` (shared: the import row only)"])),
        (9106, "Add the export page", [9102],
         body(9106, "L", ["`app/export/page.ts`"], links=["#9102 real: the button's route, which the page opens"])),
        (9107, "Try the export live", [9103, 9106],
         body(9107, "S", [], done_by="Synthetic owner, on their own account.",
              links=["#9103 real: the command the owner runs", "#9106 real: the page the owner opens"])),
    ]
    return [{"number": n, "title": title, "state": "OPEN", "labels": [], "milestone": "Synthetic",
             "parent": SPEC, "blocked_by": [{"number": b, "state": "OPEN"} for b in blockers],
             "body": text, "start_recorded": False, "pull_requests": []}
            for n, title, blockers, text in tickets]


def graph_read(tickets):
    return {"schema": "openwiz.plan-links.v1", "kind": "graph", "repo": "synthetic-owner/synthetic-repo",
            "read_at": "2026-11-19T12:00:00Z", "source": {"kind": "spec", "spec": SPEC}, "tickets": tickets}


def find(tickets, n):
    return next(t for t in tickets if t["number"] == n)


class MachineApproval(unittest.TestCase):
    """approve.py: a plan that passes every check gets one machine approval
    record bound to its revision fingerprint; a plan that fails any check gets
    none."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.root = self.tmp / "root"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs/existing.md").write_text("Synthetic interface.\n")

    def revision(self, tickets):
        """The revision text revision.sh prints for this plan on a fake GitHub."""
        state = self.tmp / "gh"
        (state / "bin").mkdir(parents=True, exist_ok=True)
        issues = [{"number": SPEC, "title": "Synthetic spec", "body": SPEC_BODY, "state": "OPEN",
                   "parent": None, "milestone": "Synthetic", "blockedBy": [], "labels": [], "comments": []}]
        issues += [{"number": t["number"], "title": t["title"], "body": t["body"], "state": t["state"],
                    "parent": SPEC, "milestone": "Synthetic", "blockedBy": [b["number"] for b in t["blocked_by"]],
                    "labels": [], "comments": []} for t in tickets]
        planned = {t["number"] for t in tickets}
        issues += [{"number": n, "title": f"Another spec's #{n}", "body": "", "state": state, "parent": None,
                    "milestone": "Synthetic", "blockedBy": [], "labels": [], "comments": []}
                   for n, state in sorted({(b["number"], b["state"]) for t in tickets for b in t["blocked_by"]
                                           if b["number"] not in planned})]
        (state / "state.json").write_text(json.dumps({"next_issue": 9200, "issues": issues}))
        gh = state / "bin/gh"
        gh.write_text(f'#!/bin/sh\nexec python3 -I "{FAKE_REVISION_GH}" "$@"\n')
        gh.chmod(0o755)
        env = dict(os.environ, FAKE_GH_STATE=str(state), PATH=f"{state / 'bin'}:{os.environ['PATH']}")
        out = subprocess.run(["sh", str(REVISION), str(SPEC)], capture_output=True, text=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def approve(self, tickets, revision=None, *extra):
        (self.tmp / "graph.json").write_text(json.dumps(graph_read(tickets)))
        (self.tmp / "revision.txt").write_text(self.revision(tickets) if revision is None else revision)
        return subprocess.run(
            ["python3", "-I", str(APPROVE), "--graph", str(self.tmp / "graph.json"),
             "--revision", str(self.tmp / "revision.txt"), "--grill", GRILL, "--number", "1",
             "--date", "2026-11-19", "--root", str(self.root), *extra],
            capture_output=True, text=True)

    def test_a_plan_that_passes_every_check_gets_a_record_bound_to_its_fingerprint(self):
        # catches: an approval that isn't bound to the exact revision checked,
        # or one that needs a human reply first.
        tickets = plan()
        revision = self.revision(tickets)
        out = self.approve(tickets, revision)
        self.assertEqual(out.returncode, 0, out.stderr)
        fingerprint = __import__("hashlib").sha256(revision.encode()).hexdigest()
        lines = out.stdout.split("\n")
        self.assertEqual(lines[0], "**Machine plan approval, 2026-11-19, revision 1:** "
                                   "links, relies, sizes, width and owned paths passed.")
        self.assertEqual(lines[1], "Grill confirmed: " + GRILL)
        self.assertIn("Checks: 7 tickets; links 5; relies 6; sizes S 4, M 2, L 1; "
                      "width: chain 4, widest 3; owned paths 6.", lines)
        table = [line for line in lines if line.startswith("| ")]
        self.assertEqual(table, [
            "| Ticket | Title | Blocked by | Label |",
            "| --- | --- | --- | --- |",
            "| #9101 | Write the export contract | none | ready-for-agent |",
            "| #9102 | Show the export button | #9101 | ready-for-agent |",
            "| #9103 | Add the export command | #9101 | ready-for-agent |",
            "| #9104 | List export in the fleet settings | none | ready-for-agent |",
            "| #9105 | List import in the fleet settings | none | ready-for-agent |",
            "| #9106 | Add the export page | #9102 | ready-for-agent |",
            "| #9107 | Try the export live | #9103 #9106 | ready-for-human |",
        ])
        self.assertIn(f"Fingerprint: `{fingerprint}`", lines)
        self.assertIn("```text\n" + revision + "```\n", out.stdout)
        # Not a human record: launch-fleet's and check-approval.sh's readers
        # never take it for one.
        self.assertFalse(out.stdout.startswith("**Plan graph approved by"))
        self.assertNotIn("Private record:", out.stdout)

    def test_revision_two_needs_what_changed(self):
        # catches: a re-cut recorded without saying what changed since the last one.
        tickets = plan()
        (self.tmp / "graph.json").write_text(json.dumps(graph_read(tickets)))
        (self.tmp / "revision.txt").write_text(self.revision(tickets))
        base = ["python3", "-I", str(APPROVE), "--graph", str(self.tmp / "graph.json"),
                "--revision", str(self.tmp / "revision.txt"), "--grill", GRILL,
                "--date", "2026-11-19", "--root", str(self.root), "--number", "2"]
        missing = subprocess.run(base, capture_output=True, text=True)
        self.assertEqual((missing.returncode, missing.stdout), (2, ""))
        given = subprocess.run(base + ["--changed", "the export page split off"], capture_output=True, text=True)
        self.assertEqual(given.returncode, 0, given.stderr)
        self.assertIn("\nChanged since revision 1: the export page split off.\n", given.stdout)

    def test_a_plan_that_fails_any_check_gets_no_record(self):
        # catches: a check that lets a bad plan through, so the fleet would
        # start on it with nobody watching.
        def edit(n, old, new):
            def change(tickets):
                t = find(tickets, n)
                self.assertIn(old, t["body"])
                t["body"] = t["body"].replace(old, new)
            return change

        def block(n, blocker, line):
            def change(tickets):
                t = find(tickets, n)
                t["blocked_by"].append({"number": blocker, "state": "OPEN"})
                t["body"] = (t["body"].replace("## Links\n\nnone\n", "## Links\n\n")
                             .replace("## Links\n\n", f"## Links\n\n- {line}\n"))
            return change

        cases = {
            "links": [edit(9102, "- #9101 real: the export record shape, which the button writes\n", "")],
            "relies": [edit(9103, "`docs/existing.md`", "`docs/missing.md`"),
                       edit(9104, "**Relies on:** nothing", "**Relies on:** `cli/export.py`")],
            "sizes": [edit(9101, "Size: S.", "Size: XL."), edit(9101, "Size: S.", "Sized small."),
                      edit(9101, "Size: S.", "Size: S. Size: M.")],
            "width": [block(9107, 9102, "#9102 real: the button the owner presses"),
                      block(9101, 9106, "#9106 real: the page the contract describes")],
            "owned paths": [edit(9103, "`cli/export.py`", "`app/export/cli.py`"),
                            edit(9104, " (shared: the export row only)", ""),
                            edit(9103, "`cli/export.py`", "`app/*/page.ts`"),
                            edit(9103, "- `cli/export.py`\n", "- the command's files\n"),
                            edit(9103, "- `cli/export.py`\n", ""),
                            edit(9103, "`cli/export.py`", "`../export.py`")],
        }
        for check, changes in cases.items():
            for i, change in enumerate(changes):
                with self.subTest(check=check, case=i):
                    tickets = plan()
                    change(tickets)
                    out = self.approve(tickets)
                    self.assertEqual(out.returncode, 1, out.stdout + out.stderr)
                    self.assertEqual(out.stdout, "")
                    self.assertIn(f"approve: {check}:", out.stderr)

    def test_a_fingerprint_of_another_plan_gets_no_record(self):
        # catches: an approval whose fingerprint names a revision other than
        # the graph that was checked (a ticket edited between the two reads).
        tickets = plan()
        revision = self.revision(tickets)
        find(tickets, 9103)["body"] += "\nA late edit.\n"
        out = self.approve(tickets, revision)
        self.assertEqual((out.returncode, out.stdout), (1, ""))
        self.assertIn("approve: revision:", out.stderr)
        for stale in (revision.replace("#9101", "#9109", 1), revision.replace("title Add the", "title Add a"),
                      revision.replace("ticket #9105 blocked-by none", "ticket #9105 blocked-by #9104"),
                      "\n".join(l for l in revision.split("\n") if "#9104 " not in l.split("blocked-by")[0])):
            with self.subTest(stale=stale[-80:]):
                out = self.approve(plan(), stale)
                self.assertEqual((out.returncode, out.stdout), (1, ""))
                self.assertIn("approve: revision:", out.stderr)

    def test_the_critical_chain_counts_open_outside_blockers_and_never_merged_work(self):
        # catches: a chain length that leaves out an open blocker in another
        # spec, or counts tickets already merged, so the record reports a
        # critical chain shorter or longer than the work still ahead.
        def chain(tickets):
            out = self.approve(tickets)
            self.assertEqual(out.returncode, 0, out.stderr)
            return next(l for l in out.stdout.split("\n") if l.startswith("Checks: ")).split("; ")[4]

        self.assertEqual(chain(plan()), "width: chain 4, widest 3")
        tickets = plan()
        first = find(tickets, 9101)
        first["blocked_by"].append({"number": 8001, "state": "OPEN"})
        first["body"] = first["body"].replace(
            "## Links\n\nnone\n", "## Links\n\n- #8001 real: another spec's record shape, which the contract extends\n")
        self.assertEqual(chain(tickets), "width: chain 5, widest 2")
        first["blocked_by"][0]["state"] = "CLOSED"
        self.assertEqual(chain(tickets), "width: chain 4, widest 3")
        first["state"] = "CLOSED"
        (self.root / "contracts").mkdir()
        (self.root / "contracts/export.v1.md").write_text("The merged synthetic contract.\n")
        self.assertEqual(chain(tickets), "width: chain 3, widest 4")

    def test_a_context_file_link_adds_no_serial_work_but_a_needed_input_does(self):
        # catches (review R5 of #1353): a file link that F6 starts past
        # counted in the critical chain, or one whose blocker owns an input
        # the ticket relies on left out of it.
        def chain(tickets):
            out = self.approve(tickets)
            self.assertEqual(out.returncode, 0, out.stderr)
            return next(l for l in out.stdout.split("\n") if l.startswith("Checks: ")).split("; ")[4]

        def file_blocked(relies):
            tickets = plan()
            first = find(tickets, 9101)
            first["blocked_by"].append({"number": 9105, "state": "OPEN"})
            first["body"] = first["body"].replace("**Relies on:** nothing", f"**Relies on:** {relies}").replace(
                "## Links\n\nnone\n", "## Links\n\n- #9105 file: `docs/agents/fleet.md`\n")
            return tickets

        self.assertEqual(chain(file_blocked("nothing")), "width: chain 4, widest 3")
        self.assertEqual(chain(file_blocked("`docs/agents/fleet.md`")), "width: chain 5, widest 2")


PREFER = HERE / "prefer.py"


def cut(tickets, links):
    """One proposed cut in tickets.md's picture data: (id, state, role) and (blocker, ticket)."""
    return {"tickets": [{"id": i, "title": f"Synthetic {i}", "size": "S", "state": state, "role": role}
                        for i, state, role in tickets],
            "links": [{"blocker": b, "ticket": t, "kind": "real", "reason": "Synthetic behaviour"} for b, t in links]}


class PreferCut(unittest.TestCase):
    """prefer.py: of two cuts of one spec, keep the shorter critical chain,
    and the wider graph when the chains are equal."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)

    def prefer(self, a, b):
        for name, data in (("a.json", a), ("b.json", b)):
            (self.tmp / name).write_text(json.dumps(data))
        return subprocess.run(["python3", "-I", str(PREFER), str(self.tmp / "a.json"), str(self.tmp / "b.json")],
                              capture_output=True, text=True, cwd=self.tmp)

    def test_the_shorter_chain_wins_then_the_wider_graph(self):
        # catches: a planner that keeps the first or the narrower cut when
        # another cut finishes the spec sooner or starts more tickets at once.
        w = "waiting", "builder"
        line = cut([("A", *w), ("B", *w), ("C", *w), ("D", *w)], [("A", "B"), ("B", "C"), ("C", "D")])
        fan = cut([("A", *w), ("B", *w), ("C", *w), ("D", *w)], [("A", "B"), ("A", "C"), ("A", "D")])
        pair = cut([("A", *w), ("B", *w), ("C", *w), ("D", *w)], [("A", "B"), ("C", "D")])
        out = self.prefer(line, fan)
        self.assertEqual((out.returncode, out.stderr), (0, ""))
        self.assertEqual(out.stdout, "cut a.json: chain 4, widest 1\ncut b.json: chain 2, widest 3\n"
                                     "prefer b.json: the shorter critical chain\n")
        out = self.prefer(pair, fan)
        self.assertEqual(out.stdout, "cut a.json: chain 2, widest 2\ncut b.json: chain 2, widest 3\n"
                                     "prefer b.json: the same chain, and the wider graph\n")
        out = self.prefer(fan, pair)
        self.assertEqual(out.stdout.splitlines()[-1], "prefer a.json: the same chain, and the wider graph")
        out = self.prefer(pair, pair)
        self.assertEqual(out.stdout.splitlines()[-1], "prefer a.json: the same chain and width; keep the first")

    def test_the_chain_counts_open_outside_blockers_and_never_merged_work(self):
        # catches: a comparison that ignores an outside blocker still open,
        # or counts merged tickets, and so keeps the cut that finishes later.
        w = "waiting", "builder"
        outside = cut([("#10", "waiting", "external"), ("A", *w), ("B", *w), ("C", *w)],
                      [("#10", "A"), ("A", "B"), ("C", "B")])
        merged = cut([("#10", "merged", "external"), ("A", "merged", "builder"), ("B", *w), ("C", *w), ("D", *w)],
                     [("#10", "A"), ("A", "B"), ("B", "C"), ("B", "D")])
        out = self.prefer(outside, merged)
        self.assertEqual(out.stdout, "cut a.json: chain 3, widest 1\ncut b.json: chain 2, widest 2\n"
                                     "prefer b.json: the shorter critical chain\n")

    def test_a_file_link_is_context_except_into_a_persons_ticket(self):
        # catches (review R5 of #1353): a cut whose tickets only share files
        # rated as a serial chain, so the slower cut with a real dependency wins.
        w = "waiting", "builder"
        shared = {"tickets": cut([("A", *w), ("B", *w), ("C", *w)], [])["tickets"],
                  "links": [{"blocker": "A", "ticket": "B", "kind": "file", "reason": "shared.md"},
                            {"blocker": "B", "ticket": "C", "kind": "file", "reason": "shared.md"}]}
        serial = cut([("A", *w), ("B", *w), ("C", *w)], [("A", "B")])
        out = self.prefer(serial, shared)
        self.assertEqual(out.stdout, "cut a.json: chain 2, widest 2\ncut b.json: chain 1, widest 3\n"
                                     "prefer b.json: the shorter critical chain\n")
        person = {"tickets": cut([("A", *w), ("J", "waiting", "jake")], [])["tickets"],
                  "links": [{"blocker": "A", "ticket": "J", "kind": "file", "reason": "notes.md"}]}
        out = self.prefer(person, person)
        self.assertEqual(out.stdout.splitlines()[0], "cut a.json: chain 2, widest 1")

    def test_an_unusable_cut_is_refused(self):
        # catches: a cycle or a link to an unknown ticket read as a short
        # chain, so a cut that can never finish wins.
        w = "waiting", "builder"
        fine = cut([("A", *w)], [])
        for bad in (cut([("A", *w), ("B", *w)], [("A", "B"), ("B", "A")]), cut([("A", *w)], [("Z", "A")]),
                    {"tickets": "A"}):
            with self.subTest(bad=bad):
                out = self.prefer(fine, bad)
                self.assertEqual((out.returncode, out.stdout), (2, ""))
                self.assertIn("prefer: b.json:", out.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
