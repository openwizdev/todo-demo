"""Council proofs (#1354). All identifiers, scores and references are synthetic."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "climb.py"
SKILL = ROOT / "SKILL.md"

JUDGES = [{"id": "J1", "family": "anthropic", "cost": 1},
          {"id": "J2", "family": "openai", "cost": 2},
          {"id": "J3", "family": "anthropic", "cost": 3}]
COUNCIL = ["J1", "J2", "J3"]


def grid(judge, marks):
    """marks: artifact -> (hierarchy, clarity) scores from one judge."""
    return [{"judge": judge, "artifact": artifact, "category": category,
             "score": score, "reason": "fixture"}
            for artifact, pair in marks.items()
            for category, score in zip(("hierarchy", "clarity"), pair)]


def round_of(number, marks_by_judge):
    return {"round": number, "judges": list(marks_by_judge),
            "scores": [row for judge, marks in marks_by_judge.items()
                       for row in grid(judge, marks)]}


# Round 0, the cheapest judge alone: A beats the reference R in both categories.
CHEAP = {"J1": {"A": (7, 8), "B": (5, 9), "R": (6, 6)}}
# The full council. Anthropic's judges favour A; OpenAI's ties A with R on
# hierarchy, so A beats R on the council mean but not in every family.
SPLIT = {"J1": {"A": (7, 8), "B": (5, 9), "R": (6, 6)},
         "J2": {"A": (6, 7), "B": (5, 5), "R": (6, 5)},
         "J3": {"A": (8, 8), "B": (4, 6), "R": (6, 7)}}
# Every family scores A above R in every category.
AGREED = {"J1": {"A": (7, 8), "B": (5, 9), "R": (6, 6)},
          "J2": {"A": (7, 7), "B": (5, 5), "R": (6, 5)},
          "J3": {"A": (8, 8), "B": (4, 6), "R": (6, 7)}}


def council(*rounds):
    return {"categories": ["hierarchy", "clarity"],
            "artifacts": [{"id": "A", "family": "openai"},
                          {"id": "B", "family": "openai"},
                          {"id": "R", "reference": "Synthetic Reference One"}],
            "judges": [dict(judge) for judge in JUDGES],
            "rounds": [round_of(i, marks) for i, marks in enumerate(rounds)]}


class CouncilCLI(unittest.TestCase):
    def call(self, command, data, *args):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            before = path.read_bytes()
            completed = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), command, str(path), *args],
                cwd=folder, capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=120)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["input.json"])
            return completed

    def good(self, data, window="2"):
        run = self.call("council", data, "--window", window)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        return json.loads(run.stdout)

    def bad(self, data, *args):
        run = self.call("council", data, *(args or ("--window", "2")))
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertIn("error:", run.stderr)

    def test_no_rounds_seats_only_the_cheapest_judge(self):
        result = self.good(council())
        self.assertEqual(result, {"rounds": [], "next_phase": "cheap", "next_judges": ["J1"],
                                  "consistent_rounds": 0, "leader": None,
                                  "stop": False, "reason": "continue"})

    def test_cheap_round_scores_per_category_and_seats_the_council_once_satisfied(self):
        result = self.good(council(CHEAP))
        (first,) = result["rounds"]
        self.assertEqual(first["round"], 0)
        self.assertEqual(first["phase"], "cheap")
        self.assertEqual(first["judges"], ["J1"])
        self.assertEqual(first["means"], {"A": {"clarity": 8, "hierarchy": 7},
                                          "B": {"clarity": 9, "hierarchy": 5},
                                          "R": {"clarity": 6, "hierarchy": 6}})
        self.assertEqual(first["references"], ["R"])
        # B wins clarity but loses hierarchy to R: only A beats R everywhere.
        self.assertEqual(first["leaders"], ["A"])
        self.assertEqual(first["top"], ["A"])
        self.assertEqual(first["best"], "A")
        self.assertEqual(result["next_phase"], "full")
        self.assertEqual(result["next_judges"], COUNCIL)
        # A cheap round never counts towards the stop.
        self.assertEqual(result["consistent_rounds"], 0)
        self.assertFalse(result["stop"])

    def test_an_unsatisfied_cheap_judge_keeps_the_council_waiting(self):
        unsatisfied = {"J1": {"A": (6, 8), "R": (6, 6)}}
        result = self.good(council(unsatisfied))
        self.assertEqual(result["rounds"][0]["leaders"], [])
        self.assertEqual(result["next_phase"], "cheap")
        self.assertEqual(result["next_judges"], ["J1"])

    def test_every_family_must_agree_not_only_the_council_mean(self):
        result = self.good(council(CHEAP, SPLIT))
        split = result["rounds"][1]
        self.assertEqual(split["phase"], "full")
        self.assertEqual(split["judges"], COUNCIL)
        self.assertAlmostEqual(split["means"]["A"]["hierarchy"], 7)
        self.assertAlmostEqual(split["means"]["A"]["clarity"], 23 / 3)
        self.assertAlmostEqual(split["means"]["R"]["hierarchy"], 6)
        self.assertAlmostEqual(split["family_means"]["anthropic"]["A"]["hierarchy"], 7.5)
        self.assertAlmostEqual(split["family_means"]["openai"]["A"]["hierarchy"], 6)
        self.assertEqual(split["leaders"], [])
        self.assertEqual(result["next_phase"], "full")
        self.assertEqual(result["consistent_rounds"], 0)

    def test_stop_needs_the_same_leader_for_the_window_of_full_rounds(self):
        once = self.good(council(CHEAP, AGREED))
        self.assertEqual(once["rounds"][1]["leaders"], ["A"])
        self.assertEqual((once["consistent_rounds"], once["leader"], once["stop"]),
                         (1, "A", False))
        twice = self.good(council(CHEAP, AGREED, AGREED))
        self.assertEqual((twice["consistent_rounds"], twice["leader"], twice["stop"],
                          twice["reason"]), (2, "A", True, "references"))
        # A full round without the leader resets the count.
        broken = self.good(council(CHEAP, AGREED, SPLIT, AGREED))
        self.assertEqual((broken["consistent_rounds"], broken["stop"]), (1, False))
        self.assertTrue(self.good(council(CHEAP, AGREED), window="1")["stop"])

    def test_a_changed_leader_restarts_the_count(self):
        b_leads = {judge: {"A": (6, 6), "B": (8, 8), "R": (6, 6)} for judge in COUNCIL}
        result = self.good(council(CHEAP, AGREED, b_leads))
        self.assertEqual(result["rounds"][2]["leaders"], ["B"])
        self.assertEqual((result["leader"], result["consistent_rounds"]), ("B", 1))

    def test_a_tied_best_is_not_a_winner(self):
        tied = {"J1": {"A": (7, 8), "B": (8, 7), "R": (6, 6)}}
        first = self.good(council(tied))["rounds"][0]
        self.assertEqual(first["leaders"], ["A", "B"])
        self.assertEqual(first["top"], ["A", "B"])
        self.assertIsNone(first["best"])

    def test_two_leaders_in_a_round_do_not_stop_the_run(self):
        tied = {judge: {"A": (8, 8), "B": (8, 8), "R": (5, 5)} for judge in COUNCIL}
        result = self.good(council(CHEAP, tied, tied))
        self.assertEqual(result["rounds"][2]["leaders"], ["A", "B"])
        self.assertEqual((result["leader"], result["consistent_rounds"], result["stop"]),
                         (None, 0, False))

    def test_a_leader_that_is_not_the_best_never_stops_the_run(self):
        # Review R1: B has the higher mean (8 against 7) and is kept, but ties R
        # on clarity; A beats R everywhere. The stop must certify the kept one.
        diverged = {"A": (7, 7), "B": (10, 6), "R": (6, 6)}
        result = self.good(council({"J1": diverged},
                                   *[{judge: diverged for judge in COUNCIL}] * 2))
        for row in result["rounds"]:
            self.assertEqual((row["leaders"], row["best"]), (["A"], "B"))
        self.assertEqual((result["leader"], result["consistent_rounds"], result["stop"],
                          result["reason"]), (None, 0, False, "continue"))

    def test_cheapest_judge_first_is_enforced(self):
        self.bad(council(SPLIT))  # the full council before the cheap judge is satisfied
        self.bad(council(CHEAP, CHEAP))  # the cheap judge alone after it was satisfied
        late = council({"J1": {"A": (6, 8), "R": (6, 6)}}, CHEAP)
        self.assertEqual(self.good(late)["next_judges"], COUNCIL)
        self.bad(council(CHEAP, AGREED, CHEAP))  # never back to the cheap seat

    def test_scores_must_be_complete_integers_from_one_to_ten(self):
        for change in ({"score": 0}, {"score": 11}, {"score": 7.5}, {"score": True},
                       {"score": "7"}, {"category": "typography"}, {"artifact": "Z"},
                       {"judge": "J2"}, {"reason": ""}, {"extra": 1}):
            data = council(CHEAP)
            data["rounds"][0]["scores"][0].update(change)
            with self.subTest(change=change):
                self.bad(data)
        for edit in (lambda rows: rows.pop(), lambda rows: rows.append(dict(rows[0]))):
            data = council(CHEAP)
            edit(data["rounds"][0]["scores"])
            self.bad(data)

    def test_references_are_scored_in_every_round_beside_a_candidate(self):
        self.bad(council({"J1": {"A": (7, 8)}}))
        self.bad(council({"J1": {"R": (7, 8)}}))
        data = council(CHEAP)
        data["artifacts"].pop()  # no reference at all
        data["rounds"] = []
        self.bad(data)

    def test_a_reference_named_candidate_is_still_a_reference(self):
        data = council({"J1": {"A": (7, 8), "B": (5, 9), "R": (6, 6)}})
        data["artifacts"][2]["reference"] = "candidate"
        self.assertEqual(self.good(data)["rounds"][0]["references"], ["R"])

    def test_the_panel_needs_three_judges_from_two_families(self):
        for judges in (JUDGES[:2], [{**judge, "family": "anthropic"} for judge in JUDGES],
                       [JUDGES[0], {**JUDGES[1], "cost": 1}, JUDGES[2]],
                       [JUDGES[0], {**JUDGES[1], "id": "J1"}, JUDGES[2]],
                       [{**JUDGES[0], "cost": 0}, *JUDGES[1:]],
                       [{**JUDGES[0], "cost": True}, *JUDGES[1:]],
                       [{**JUDGES[0], "model": "x"}, *JUDGES[1:]]):
            data = council()
            data["judges"] = judges
            with self.subTest(judges=judges):
                self.bad(data)

    def test_shape_is_exact(self):
        for change in ({"categories": []}, {"categories": ["hierarchy", "hierarchy"]},
                       {"categories": ["Hierarchy"]}, {"extra": 1},
                       {"artifacts": [{"id": "A", "family": "openai"},
                                      {"id": "R", "reference": ""}]},
                       {"artifacts": [{"id": "A", "family": "openai", "reference": "x"},
                                      {"id": "R", "reference": "y"}]}):
            with self.subTest(change=change):
                self.bad({**council(), **change})
        data = council(CHEAP)
        data["rounds"][0]["round"] = 1
        self.bad(data)
        data = council(CHEAP)
        data["rounds"][0]["judges"] = ["J1", "J1"]
        self.bad(data)
        self.bad(council(CHEAP), "--window", "0")
        run = self.call("council", council(CHEAP))
        self.assertEqual(run.returncode, 2)

    def test_table_prints_each_judges_scores_and_the_council_mean_per_round(self):
        run = self.call("table", council(CHEAP, SPLIT))
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stdout, "\n".join([
            "| Round | Phase | Judge | Artifact | hierarchy | clarity | Leader |",
            "| --- | --- | --- | --- | --- | --- | --- |",
            "| 0 | cheap | J1 (anthropic) | A | 7 | 8 |  |",
            "| 0 | cheap | J1 (anthropic) | B | 5 | 9 |  |",
            "| 0 | cheap | J1 (anthropic) | R (reference: Synthetic Reference One) | 6 | 6 |  |",
            "| 0 | cheap | council | A | 7.00 | 8.00 | yes |",
            "| 0 | cheap | council | B | 5.00 | 9.00 |  |",
            "| 0 | cheap | council | R (reference: Synthetic Reference One) | 6.00 | 6.00 |  |",
            "| 1 | full | J1 (anthropic) | A | 7 | 8 |  |",
            "| 1 | full | J1 (anthropic) | B | 5 | 9 |  |",
            "| 1 | full | J1 (anthropic) | R (reference: Synthetic Reference One) | 6 | 6 |  |",
            "| 1 | full | J2 (openai) | A | 6 | 7 |  |",
            "| 1 | full | J2 (openai) | B | 5 | 5 |  |",
            "| 1 | full | J2 (openai) | R (reference: Synthetic Reference One) | 6 | 5 |  |",
            "| 1 | full | J3 (anthropic) | A | 8 | 8 |  |",
            "| 1 | full | J3 (anthropic) | B | 4 | 6 |  |",
            "| 1 | full | J3 (anthropic) | R (reference: Synthetic Reference One) | 6 | 7 |  |",
            "| 1 | full | council | A | 7.00 | 7.67 |  |",
            "| 1 | full | council | B | 4.67 | 6.67 |  |",
            "| 1 | full | council | R (reference: Synthetic Reference One) | 6.00 | 6.00 |  |",
        ]) + "\n")
        self.assertEqual(run.stderr, "")


class CouncilInstructions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text = SKILL.read_text(encoding="utf-8")
        cls.text = " ".join(text.split())
        parts = text.split("## Council judging\n", 1)
        cls.section = " ".join(parts[1].split("\n## ", 1)[0].split()) if len(parts) == 2 else ""

    def rule(self, text):
        self.assertIn(text, self.section, f"Missing council rule: {text}")

    def test_council_is_the_default_for_design_and_pairwise_stays_an_option(self):
        self.rule("The council is the default for design work.")
        self.rule("Pairwise judging with Bradley-Terry ranking stays available as an option")

    def test_three_judges_from_two_families_score_one_to_ten_per_category(self):
        self.rule("three judges from at least two model families")
        self.rule("score every artifact from 1 to 10 in each category")
        self.rule("**Design:** hierarchy, typography, color and contrast, consistency, clarity.")
        self.rule("A ticket may name its own categories")

    def test_references_share_the_round_and_the_stop_is_relative(self):
        self.rule("Named reference products are scored in the same round, with the same rubric")
        self.rule("beats every reference in every category, consistently")
        self.rule("and is also the round's `best`, for `--window` consecutive full-council rounds")

    def test_judges_never_see_the_target(self):
        self.rule("Judges never see the score being aimed for")
        # R3: a brief that names the stop tells judges what their scores trigger.
        self.rule("A judge's brief holds the frozen rubric, the 1–10 scale, the categories "
                  "and the blind artifacts; never the stop condition")

    def test_cheapest_judge_first_with_each_judges_scores_recorded(self):
        self.rule("Run the cheapest judge alone until it is satisfied, then seat the whole council")
        self.rule("Record each judge's scores for every round")

    def test_checkpoint_shows_annotated_before_and_after_and_the_score_table(self):
        self.assertIn("before and after images with arrows and short notes on what changed, "
                      "plus the per-round score table", self.text)

    def test_council_chart_keeps_reference_series_and_per_judge_table(self):
        # R2: a chart of candidate scores alone hides the comparison with the
        # named benchmarks round by round.
        self.assertIn("each category's council mean per round for the round's best candidate "
                      "and for each reference", self.text)
        self.assertIn("keep the per-judge `table` output behind it", self.text)


if __name__ == "__main__":
    unittest.main()
