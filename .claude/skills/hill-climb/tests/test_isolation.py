"""Static proof of #597's written gate, not live sandbox enforcement."""
from pathlib import Path
import unittest


SKILL = Path(__file__).resolve().parents[1] / "SKILL.md"


class IsolationInstructions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        section = text.split("## Put the judge outside the climbers' reach\n", 1)[1]
        cls.section = " ".join(section.split("\n## ", 1)[0].split())

    def rule(self, text):
        self.assertTrue(text in self.section, f"Missing isolation rule: {text}")

    def test_unenforceable_credentials_require_audit_before_judging(self):
        self.rule(
            "When the runtime cannot enforce a credential boundary between "
            "climbers and the judge, the controller must audit each climber's "
            "complete command log and tool calls after every round, before "
            "judging any candidate.")
        self.assertNotIn("If the runtime cannot enforce that boundary, stop setup",
                         self.section)

    def test_either_prohibited_access_disqualifies_and_drops_candidate(self):
        self.rule(
            "Allow only `room-cli files wait`, CloudRoom's startup step; any "
            "other `room-cli` command, or any use of the bridge to the user's "
            "machines, including indirect calls through commands, scripts or "
            "tools, disqualifies the climber.")
        self.rule(
            "Drop that climber's candidate from judging and selection, and "
            "record the finding in the controller ledger.")

    def test_unreadable_activity_stops_run(self):
        self.rule(
            "If any climber's command log or tool-call record cannot be read "
            "completely, stop the run and report the blocker; never treat an "
            "unreadable log as clean.")

    def test_climber_briefs_never_mention_room_cli(self):
        self.rule("Climbers' briefs must never mention `room-cli`.")

    def test_filesystem_denied_read_write_probe_remains(self):
        self.rule("Verify isolation with a harmless denied read/write probe.")


if __name__ == "__main__":
    unittest.main()
