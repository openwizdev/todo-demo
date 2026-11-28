#!/usr/bin/env python3
"""Fixture tests for launch/check.py (read-only launch video caption check)."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest


LAUNCH_DIR = Path(__file__).resolve().parent
CHECK_SCRIPT = LAUNCH_DIR / "check.py"


FAKE_GH_SOURCE = r"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
log_path = os.environ["FAKE_GH_LOG"]
with open(log_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")

write_log = os.environ["FAKE_GH_WRITE_LOG"]

def reject_write(reason):
    with open(write_log, "a", encoding="utf-8") as fh:
        fh.write(f"{reason}: {args}\n")
    sys.stderr.write(f"refused write ({reason}): {args}\n")
    sys.exit(99)

# Refuse any write subcommand or mutating flag.
if not args:
    reject_write("empty args")

cmd = args[0]
sub = args[1] if len(args) > 1 else ""

if cmd == "issue" and sub not in ("view", "list"):
    reject_write(f"issue {sub}")
elif cmd == "pr" and sub not in ("view", "list"):
    reject_write(f"pr {sub}")
elif cmd == "api":
    for idx, token in enumerate(args[1:]):
        if token in ("-f", "-F", "--field", "--raw-field", "--input"):
            reject_write(f"api mutating flag {token}")
        if token in ("-X", "--method"):
            method = args[idx + 2] if idx + 2 < len(args) else ""
            if method.upper() != "GET":
                reject_write(f"api method {method}")
        if token.startswith("--method=") and token.split("=", 1)[1].upper() != "GET":
            reject_write(f"api method {token}")
        if token.startswith("-X") and len(token) > 2 and token[2:].upper() != "GET":
            reject_write(f"api method {token}")
elif cmd not in ("issue", "pr", "api"):
    reject_write(f"unexpected command {cmd}")

fixture_path = os.environ["FAKE_GH_FIXTURE"]
with open(fixture_path, "r", encoding="utf-8") as fh:
    fixture = json.load(fh)

def emit(entry):
    if entry.get("exit_code", 0) != 0:
        sys.stderr.write(entry.get("stderr", "simulated gh failure\n"))
        sys.exit(entry["exit_code"])
    if "raw_stdout" in entry:
        sys.stdout.write(entry["raw_stdout"])
    else:
        sys.stdout.write(json.dumps(entry["stdout"]))
    sys.exit(0)

if cmd == "issue" and sub == "view":
    emit(fixture["spec"])
if cmd == "api" and any("sub_issues" in a for a in args):
    emit(fixture["tickets"])
if cmd == "pr" and sub == "list":
    emit(fixture["prs"])

reject_write("unhandled read command")
"""


def default_fixture():
    return {
        "spec": {
            "stdout": {
                "number": 1,
                "title": "0.2.0 spec: To-do app",
                "url": "https://github.com/example/fresh-todo/issues/1",
                "createdAt": "2026-11-20T10:13:31Z",
            }
        },
        "tickets": {
            "stdout": [
                {
                    "number": 2,
                    "title": "TD1: task list",
                    "html_url": "https://github.com/example/fresh-todo/issues/2",
                    "state": "closed",
                },
                {
                    "number": 3,
                    "title": "TD2: add and complete",
                    "html_url": "https://github.com/example/fresh-todo/issues/3",
                    "state": "closed",
                },
            ]
        },
        "prs": {
            "stdout": [
                {
                    "number": 6,
                    "title": "#2: TD1",
                    "url": "https://github.com/example/fresh-todo/pull/6",
                    "mergedAt": "2026-11-20T10:46:40Z",
                    "closingIssuesReferences": [
                        {
                            "number": 2,
                            "repository": {
                                "owner": {"login": "example"},
                                "name": "fresh-todo",
                            },
                        }
                    ],
                },
                {
                    "number": 7,
                    "title": "#3: TD2",
                    "url": "https://github.com/example/fresh-todo/pull/7",
                    "mergedAt": "2026-11-20T11:25:15Z",
                    "closingIssuesReferences": [
                        {
                            "number": 3,
                            "repository": {
                                "owner": {"login": "example"},
                                "name": "fresh-todo",
                            },
                        }
                    ],
                },
                {
                    "number": 99,
                    "title": "Unrelated PR",
                    "url": "https://github.com/example/fresh-todo/pull/99",
                    "mergedAt": "2026-11-20T23:59:59Z",
                    "closingIssuesReferences": [
                        {
                            "number": 50,
                            "repository": {
                                "owner": {"login": "example"},
                                "name": "fresh-todo",
                            },
                        }
                    ],
                },
            ]
        },
    }


def parse_lines(stdout):
    parsed = {}
    for line in stdout.strip().splitlines():
        key, _, value = line.partition(":")
        parsed[key.strip()] = value.strip()
    return parsed


class CaptionCheckTests(unittest.TestCase):
    def run_check(self, fixture, extra_args=None):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            fake_gh = tmp / "gh"
            fake_gh.write_text(FAKE_GH_SOURCE, encoding="utf-8")
            fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IXUSR)

            fixture_file = tmp / "fixture.json"
            fixture_file.write_text(json.dumps(fixture), encoding="utf-8")
            log_file = tmp / "gh.log"
            write_log = tmp / "writes.log"

            env = os.environ.copy()
            env["PATH"] = f"{tmp}{os.pathsep}{env.get('PATH', '')}"
            env["FAKE_GH_FIXTURE"] = str(fixture_file)
            env["FAKE_GH_LOG"] = str(log_file)
            env["FAKE_GH_WRITE_LOG"] = str(write_log)

            cmd = [
                sys.executable,
                "-I",
                str(CHECK_SCRIPT),
                "--repo",
                "example/fresh-todo",
                "--spec",
                "1",
            ]
            if extra_args:
                cmd.extend(extra_args)

            proc = subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            calls = (
                [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
                if log_file.exists()
                else []
            )
            writes = write_log.read_text(encoding="utf-8") if write_log.exists() else ""
            return proc, calls, writes

    def test_caption_data_and_elapsed_time_with_explicit_first_prompt(self):
        proc, calls, writes = self.run_check(
            default_fixture(),
            extra_args=["--first-prompt", "2026-11-20T10:10:00Z"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(writes, "", f"unexpected write calls: {writes}")
        self.assertGreaterEqual(len(calls), 3)

        fields = parse_lines(proc.stdout)
        self.assertEqual(
            fields["spec"],
            "#1 0.2.0 spec: To-do app (https://github.com/example/fresh-todo/issues/1)",
        )
        self.assertEqual(fields["tickets"], "#2, #3")
        self.assertEqual(fields["merged_prs"], "#6, #7")
        self.assertEqual(fields["first_prompt"], "2026-11-20T10:10:00Z")
        self.assertEqual(fields["last_merge"], "2026-11-20T11:25:15Z")
        # 10:10:00Z -> 11:25:15Z = 1h 15m 15s = 4515s
        self.assertEqual(fields["elapsed"], "1h 15m 15s (4515s)")

    def test_elapsed_time_falls_back_to_spec_created_at(self):
        proc, _, writes = self.run_check(default_fixture())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(writes, "")

        fields = parse_lines(proc.stdout)
        self.assertEqual(fields["first_prompt"], "2026-11-20T10:13:31Z")
        self.assertEqual(fields["last_merge"], "2026-11-20T11:25:15Z")
        # 10:13:31Z -> 11:25:15Z = 1h 11m 44s = 4304s
        self.assertEqual(fields["elapsed"], "1h 11m 44s (4304s)")

    def test_failed_spec_read_prints_unknown_without_guessing(self):
        fixture = default_fixture()
        fixture["spec"] = {"exit_code": 1, "stderr": "network error\n"}

        proc, _, writes = self.run_check(fixture)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(writes, "")

        fields = parse_lines(proc.stdout)
        self.assertEqual(fields["spec"], "unknown")
        self.assertEqual(fields["tickets"], "#2, #3")
        self.assertEqual(fields["merged_prs"], "#6, #7")
        self.assertEqual(fields["first_prompt"], "unknown")
        self.assertEqual(fields["last_merge"], "2026-11-20T11:25:15Z")
        self.assertEqual(fields["elapsed"], "unknown")

    def test_failed_tickets_read_prints_unknown_for_tickets_and_prs(self):
        fixture = default_fixture()
        fixture["tickets"] = {"exit_code": 1, "stderr": "API failure\n"}

        proc, _, writes = self.run_check(
            fixture,
            extra_args=["--first-prompt", "2026-11-20T10:10:00Z"],
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(writes, "")

        fields = parse_lines(proc.stdout)
        self.assertIn("#1", fields["spec"])
        self.assertEqual(fields["tickets"], "unknown")
        self.assertEqual(fields["merged_prs"], "unknown")
        self.assertEqual(fields["first_prompt"], "2026-11-20T10:10:00Z")
        self.assertEqual(fields["last_merge"], "unknown")
        self.assertEqual(fields["elapsed"], "unknown")

    def test_failed_prs_read_prints_unknown_for_prs_and_elapsed(self):
        fixture = default_fixture()
        fixture["prs"] = {"exit_code": 1, "stderr": "rate limited\n"}

        proc, _, writes = self.run_check(
            fixture,
            extra_args=["--first-prompt", "2026-11-20T10:10:00Z"],
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(writes, "")

        fields = parse_lines(proc.stdout)
        self.assertIn("#1", fields["spec"])
        self.assertEqual(fields["tickets"], "#2, #3")
        self.assertEqual(fields["merged_prs"], "unknown")
        self.assertEqual(fields["last_merge"], "unknown")
        self.assertEqual(fields["elapsed"], "unknown")

    def test_malformed_json_prints_unknown(self):
        fixture = default_fixture()
        fixture["prs"] = {"raw_stdout": "not-json"}

        proc, _, writes = self.run_check(fixture)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(writes, "")

        fields = parse_lines(proc.stdout)
        self.assertEqual(fields["merged_prs"], "unknown")
        self.assertEqual(fields["last_merge"], "unknown")
        self.assertEqual(fields["elapsed"], "unknown")

    def test_never_invokes_write_commands_on_gh(self):
        proc, calls, writes = self.run_check(default_fixture())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(writes, "")
        for argv in calls:
            self.assertIn(argv[0], ("issue", "pr", "api"))
            if argv[0] in ("issue", "pr"):
                self.assertIn(argv[1], ("view", "list"))


if __name__ == "__main__":
    unittest.main()
