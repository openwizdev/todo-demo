"""O10/P4: the instructions agents copy to the public tracker obey the contract.

A stale approval template would publish exact user words; a stale wayfind claim
would publish a thread id or let one holder release another. Existing skill
checks cover installation and older wording, not these public record forms.
These are instruction-contract checks, not the O3 privacy checker or live proof.
"""
from pathlib import Path
import json
import re
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[3]


class PublicTrackerInstructions(unittest.TestCase):
    def test_standalone_approval_template_has_decision_and_private_pointer(self):
        text = (ROOT / "skills/triage/SKILL.md").read_text()
        templates = re.findall(r"\*\*Approved on its own by <user>, <YYYY-MM-DD>:\*\*[^\n]*", text)
        self.assertTrue(templates, "standalone approval template missing")
        for template in templates:
            self.assertNotRegex(template, r'["“”]', "public approval quotes exact words")
        block = next(b for b in re.findall(r"```markdown\n(.*?)```", text, re.S)
                     if "**Approved on its own by" in b)
        lines = block.splitlines()
        i = next(i for i, line in enumerate(lines) if line.startswith("**Approved on its own by"))
        self.assertEqual(i, 0, "public approval must be the first line")
        self.assertEqual(lines[i + 1], "Private record: <pointer>")
        self.assertIn("<decision>", lines[i])

    def test_builder_answer_and_batch_keep_exact_words_private(self):
        text = (ROOT / "skills/triage/SKILL.md").read_text()
        answer = text.split("## Answer a builder\n", 1)[1].split("## Nothing starts", 1)[0]
        batch = text.split("### Record a batch decision\n", 1)[1].split("## Tell the user", 1)[0]
        self.assertNotIn("post their exact words on the ticket", answer)
        self.assertNotIn("quoting the user's exact words", batch)
        self.assertNotIn("Quote the same user's exact words", batch)
        self.assertIn("private record", answer)
        self.assertIn("private record", batch)

    def test_wayfind_claim_is_released_by_its_comment_id(self):
        text = (ROOT / "skills/wayfind/SKILL.md").read_text()
        commands = [line for line in text.splitlines() if line.startswith("gh issue comment <question> --body ")]
        self.assertEqual(commands, [
            'gh issue comment <question> --body "wayfind: claimed"',
            'gh issue comment <question> --body "wayfind: released <claim comment id>"',
        ])
        claims = text.split("- **A claim is a comment,**", 1)[1].split("- **The frontier**", 1)[0]
        self.assertIn("comment id", claims)
        self.assertNotIn("<your thread>", claims)
        self.assertNotIn("<the same thread>", claims)
        self.assertIn("earliest", claims)
        self.assertIn("private", claims)


    def test_wayfind_reader_preserves_claim_identity_for_releases(self):
        # R1/P4: the exact documented reader must distinguish histories with
        # identical bodies but different holders. The wording-only test never
        # executed this projection, so discarding comment identity went unseen.
        text = (ROOT / "skills/wayfind/SKILL.md").read_text()
        reader = next(line for line in text.splitlines()
                      if line.startswith("gh issue view <question> --json labels,blockedBy,comments --jq "))
        expression = shlex.split(reader)[-1]

        def comment(number, body):
            return {
                "id": f"IC_synthetic_{number}",  # GitHub's node id is not the numeric comment id.
                "url": f"https://github.com/synthetic-owner/synthetic-repo/issues/9#issuecomment-{number}",
                "body": body,
            }

        for ids, expected_holder in [([100, 101, 103], "100"), ([101, 103, 104], "103")]:
            with self.subTest(claim_ids=ids):
                source = {
                    "labels": [{"name": "wayfind:grill"}],
                    "blockedBy": {"nodes": []},
                    "comments": [comment(n, "wayfind: claimed") for n in ids]
                    + [comment(110, "wayfind: released 101")],
                }
                result = subprocess.run(
                    ["jq", "-c", expression], input=json.dumps(source),
                    capture_output=True, text=True, timeout=10, check=True,
                )
                records = json.loads(result.stdout)["claims"]
                self.assertEqual(len(records), 4)
                active = {}
                for record in records:
                    self.assertIsInstance(record, dict, "reader discarded comment identity")
                    self.assertRegex(record["url"], r"#issuecomment-[1-9][0-9]*$")
                    if record["body"] == "wayfind: claimed":
                        identity = record["url"].rsplit("#issuecomment-", 1)[1]
                        active[identity] = record
                    else:
                        active.pop(record["body"].removeprefix("wayfind: released "), None)
                self.assertEqual(next(iter(active)), expected_holder)


if __name__ == "__main__":
    unittest.main()
