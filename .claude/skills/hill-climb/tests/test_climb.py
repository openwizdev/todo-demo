"""Public CLI proofs. All identifiers and observations here are synthetic."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "climb.py"


def manifest():
    return {"candidates": [{"id": "A", "family": "openai"},
                           {"id": "B", "family": "openai"}],
            "judge_family": "anthropic"}


def series(a="A", b="B", first="left", second="right"):
    # The two records are the same pair shown in opposite orders.
    return [{"left": a, "right": b, "winner": first, "reason": "fixture"},
            {"left": b, "right": a, "winner": second, "reason": "fixture"}]


def results(rows=None):
    return {**manifest(), "comparisons": series() if rows is None else rows}


def improving_history(rounds):
    data = {**manifest(), "candidates": [{"id": "R0", "family": "openai"}],
            "comparisons": []}
    incumbent = "R0"
    for round_number in range(1, rounds + 1):
        fresh = [f"R{round_number}x{k}" for k in range(3)]
        data["candidates"].extend({"id": name, "family": "openai"} for name in fresh)
        pool = [incumbent, *fresh]
        for i, left in enumerate(pool):
            for right in pool[i + 1:]:
                winner = fresh[0] if fresh[0] in (left, right) else left
                data["comparisons"].extend(series(
                    left, right, "left" if winner == left else "right",
                    "right" if winner == left else "left"))
        incumbent = fresh[0]
    return data


class CLI(unittest.TestCase):
    def call(self, command, data, *args, raw=False):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            if isinstance(data, bytes):
                path.write_bytes(data)
            else:
                path.write_text(data if raw else json.dumps(data), encoding="utf-8")
            before = path.read_bytes()
            completed = subprocess.run(
                [sys.executable, "-B", str(SCRIPT), command, str(path), *args],
                cwd=folder, capture_output=True, text=True,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=120)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(folder).iterdir()), ["input.json"])
            return completed

    def good(self, command, data, *args):
        run = self.call(command, data, *args)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        return json.loads(run.stdout)

    def bad(self, command, data, *args, raw=False):
        run = self.call(command, data, *args, raw=raw)
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertIn("error:", run.stderr)

    def test_pairs_emits_each_order_exactly_once(self):
        data = manifest()
        data["candidates"].append({"id": "C", "family": "openai"})
        self.assertEqual(self.good("pairs", data), {"tasks": [
            {"left": "A", "right": "B"}, {"left": "B", "right": "A"},
            {"left": "A", "right": "C"}, {"left": "C", "right": "A"},
            {"left": "B", "right": "C"}, {"left": "C", "right": "B"}]})

    def test_pairs_refuses_same_family_including_mixed_pool(self):
        for candidate in (0, 1):
            data = manifest()
            data["candidates"][candidate]["family"] = "anthropic"
            self.bad("pairs", data)

    def test_pairs_refuses_unknown_shape_or_identity(self):
        cases = [[], {}, {**manifest(), "extra": 1}]
        for value in ([], ["A", "B"], [{"id": "A", "family": "openai"}],
                      [{"id": "A", "family": "openai"}] * 2,
                      [{"id": "A", "family": "OpenAI"},
                       {"id": "B", "family": "openai"}]):
            cases.append({**manifest(), "candidates": value})
        for value in (None, "", "Anthropic", {"anthropic": None}, True):
            cases.append({**manifest(), "judge_family": value})
        for data in cases:
            with self.subTest(data=data):
                self.bad("pairs", data)

    def test_two_candidate_worked_bradley_terry_strengths(self):
        # A wins 3 of 4 observations. Half a prior win each -> 3.5:1.5 -> .7:.3.
        rows = series() + series(first="left", second="left")
        ranked = self.good("rank", results(rows))
        self.assertEqual(ranked["winner"], "A")
        self.assertEqual(ranked["top"], ["A"])
        self.assertEqual(ranked["observations"], 4)
        self.assertEqual(ranked["position_splits"], 1)
        self.assertEqual(ranked["prior_wins_per_pair"], 0.5)
        self.assertAlmostEqual(ranked["ranking"][0]["strength"], 0.7, places=7)
        self.assertAlmostEqual(ranked["ranking"][1]["strength"], 0.3, places=7)

    def test_all_history_counts_and_order_does_not(self):
        rows = series() + series(first="right", second="left") * 3
        original = self.good("rank", results(rows))
        self.assertEqual(original["winner"], "B")
        self.assertEqual(original, self.good("rank", results(list(reversed(rows)))))
        self.assertAlmostEqual(original["ranking"][0]["strength"], 6.5 / 9, places=7)

    def test_position_bias_and_explicit_ties_do_not_invent_winner(self):
        for rows, splits in ((series(first="left", second="left"), 1),
                             (series(first="tie", second="tie"), 0)):
            ranked = self.good("rank", results(rows))
            self.assertIsNone(ranked["winner"])
            self.assertEqual(ranked["top"], ["A", "B"])
            self.assertEqual(ranked["position_splits"], splits)
            self.assertEqual([r["strength"] for r in ranked["ranking"]], [0.5, 0.5])

    def test_equal_cycle_is_equal_and_separated_wins_are_finite(self):
        data = results(series("A", "B") + series("B", "C") + series("C", "A"))
        data["candidates"].append({"id": "C", "family": "openai"})
        ranked = self.good("rank", data)
        self.assertIsNone(ranked["winner"])
        self.assertEqual(ranked["top"], ["A", "B", "C"])
        for row in ranked["ranking"]:
            self.assertAlmostEqual(row["strength"], 1 / 3, places=7)
        unanimous = self.good("rank", results())
        self.assertAlmostEqual(unanimous["ranking"][0]["strength"], 5 / 6, places=7)

    def test_eighty_improving_rounds_remain_rankable(self):
        ranked = self.good("rank", improving_history(80))
        self.assertEqual(ranked["winner"], "R80x0")
        self.assertEqual(ranked["top"], ["R80x0"])
        self.assertEqual(ranked["observations"], 960)
        self.assertEqual(len(ranked["ranking"]), 241)
        self.assertAlmostEqual(sum(row["strength"] for row in ranked["ranking"]), 1)
        self.assertTrue(all(math.isfinite(row["log_strength"]) for row in ranked["ranking"]))

    def test_log_strength_preserves_a_tail_that_underflows(self):
        # Each independent chain edge has two wins plus half a prior win
        # against half a prior loss: exactly 5:1, so the log gap is log(5).
        names = [f"C{i:04d}" for i in range(501)]
        data = {**manifest(),
                "candidates": [{"id": name, "family": "openai"} for name in names],
                "comparisons": [row for a, b in zip(names, names[1:])
                                for row in series(a, b, "right", "left")]}
        ranked = self.good("rank", data)
        self.assertEqual(ranked["winner"], "C0500")
        self.assertEqual([row["id"] for row in ranked["ranking"]], list(reversed(names)))
        self.assertAlmostEqual(ranked["ranking"][0]["log_strength"], -0.2231435513142097, places=7)
        self.assertAlmostEqual(ranked["ranking"][-1]["log_strength"], -804.9420997683644, places=6)
        self.assertEqual(ranked["ranking"][-1]["strength"], 0)
        for left, right in zip(ranked["ranking"], ranked["ranking"][1:]):
            self.assertAlmostEqual(left["log_strength"] - right["log_strength"],
                                   1.6094379124341003, places=7)

    def test_odds_against_the_baseline_come_from_the_fit(self):
        # catches: chart odds computed by dividing display strengths, or
        # against the wrong baseline. A won 3.5:1.5 with the prior (.7:.3).
        rows = series() + series(first="left", second="left")
        odds = self.good("odds", results(rows), "--baseline", "B")
        self.assertEqual(odds["baseline"], "B")
        self.assertEqual([row["id"] for row in odds["odds"]], ["A", "B"])
        self.assertAlmostEqual(odds["odds"][0]["beats_baseline"], 0.7, places=7)
        self.assertEqual(odds["odds"][1]["beats_baseline"], 0.5)

    def test_odds_stay_finite_when_display_strengths_underflow(self):
        # catches: 0/0 or NaN when both strengths underflow to zero. Each
        # chain step is exactly 5:1, so C0001 beats C0000 with 5/6.
        names = [f"C{i:04d}" for i in range(501)]
        data = {**manifest(),
                "candidates": [{"id": name, "family": "openai"} for name in names],
                "comparisons": [row for a, b in zip(names, names[1:])
                                for row in series(a, b, "right", "left")]}
        odds = {row["id"]: row["beats_baseline"]
                for row in self.good("odds", data, "--baseline", "C0000")["odds"]}
        self.assertAlmostEqual(odds["C0001"], 5 / 6, places=7)
        self.assertEqual(odds["C0500"], 1.0)
        self.assertTrue(all(0 <= value <= 1 for value in odds.values()))

    def test_odds_refuse_an_unknown_or_missing_baseline(self):
        # catches: a chart against a baseline that is not in the stretch.
        self.bad("odds", results(), "--baseline", "Z")
        self.bad("odds", results())

    def test_rank_refuses_missing_reverse_and_unbalanced_repeats(self):
        for rows in ([], series()[:1], series() + series()[:1]):
            self.bad("rank", results(rows))
        data = results()
        data["candidates"].append({"id": "C", "family": "openai"})
        self.bad("rank", data)  # disconnected candidate is not rankable

    def test_rank_refuses_bad_rows_and_family(self):
        for change in ({"left": "A", "right": "A"}, {"left": "Z"},
                       {"winner": "A"}, {"winner": {"left": None}},
                       {"reason": ""}, {"extra": 1}):
            data = results()
            data["comparisons"][0].update(change)
            self.bad("rank", data)
        data = results()
        data["judge_family"] = "openai"
        self.bad("rank", data)

    def test_stall_boundary_counts_unchanged_transitions(self):
        # --window 2 means two completed rounds after selecting A: A,A,A.
        data = {"rounds": [{"round": 0, "winner": "A"},
                           {"round": 1, "winner": "A"}], "stopped_by_jake": False}
        self.assertEqual(self.good("stall", data, "--window", "2"),
                         {"stop": False, "reason": "continue", "unchanged_rounds": 1})
        data["rounds"].append({"round": 2, "winner": "A"})
        self.assertEqual(self.good("stall", data, "--window", "2"),
                         {"stop": True, "reason": "stall", "unchanged_rounds": 2})

    def test_changes_ties_and_unknown_rounds_break_a_stall(self):
        for winners in (["A", "A", "B"], ["A", "B", "A"],
                        ["A", None, "A"], ["A", "A", None], [None, None, None], ["A"]):
            data = {"rounds": [{"round": i, "winner": w} for i, w in enumerate(winners)],
                    "stopped_by_jake": False}
            self.assertFalse(self.good("stall", data, "--window", "2")["stop"])
        self.bad("stall", {"rounds": [{"round": 0, "winner": "A"},
                                      {"round": 2, "winner": "A"}],
                           "stopped_by_jake": False}, "--window", "2")

    def test_jake_can_stop_before_any_round(self):
        self.assertEqual(self.good("stall", {"rounds": [], "stopped_by_jake": True},
                                   "--window", "2"),
                         {"stop": True, "reason": "jake", "unchanged_rounds": 0})

    def test_stall_requires_explicit_valid_window_and_exact_history(self):
        data = {"rounds": [], "stopped_by_jake": False}
        self.bad("stall", data)
        for window in ("0", "-1", "1.5", "true"):
            self.bad("stall", data, "--window", window)
        for value in ({**data, "stopped_by_jake": "false"},
                      {**data, "rounds": [{"round": True, "winner": "A"}]},
                      {**data, "rounds": [{"round": 0, "winner": []}]},
                      {**data, "rounds": [{"round": 0, "winner": "A", "extra": 1}]},
                      {**data, "rounds": [{"round": 1, "winner": "A"}]}):
            self.bad("stall", value, "--window", "2")

    def test_bad_json_never_yields_partial_success(self):
        for raw in ('{"candidates":[],"candidates":[]}', '{"x":NaN}',
                    '{"x":Infinity}', '{} trailing', b'\xff', '[1,2]'):
            self.bad("pairs", raw, raw=True)


if __name__ == "__main__":
    unittest.main()
