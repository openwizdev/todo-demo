#!/usr/bin/env python3
"""Offline pair plans, Bradley-Terry fits, chart odds, council scores and stall decisions.

No model calls. Reads one UTF-8 JSON file, prints one result, writes nothing.
Exit 2 is a refusal with nothing on stdout. Exact keys only: duplicate keys,
wrong types, unknown enums and non-JSON constants are refused.

rank: smoothed Bradley-Terry over every comparison, with half a prior win per
side of each observed pair, so unanimous records stay finite. Damped Newton
steps in log space solve the pinned graph Laplacian until the largest gradient
entry is below 1e-9; a singular, nonfinite or stalled solve is refused. Strengths
are relative and sum to one; order and ties use log strengths, and a gap within
1e-8 is a tie. The pair graph must be connected and every pair needs equally
many orders. position_splits is the minimum count of verdicts that disagree
across the two orders.

odds: each candidate's probability of beating --baseline, from the same fit's
log-strength gap, for the climb chart.
"""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import re
import sys


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def object_keys(value, keys):
    require(type(value) is dict and set(value) == set(keys),
            "object must have exactly: " + ", ".join(keys))


def token(value):
    require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9-]*", value),
            "family must be a canonical lowercase token")
    return value


def identity(value):
    require(type(value) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value),
            "candidate id must be an ASCII label")
    return value


def unique_keys(items):
    obj = {}
    for key, value in items:
        require(key not in obj, "duplicate object key")
        obj[key] = value
    return obj


def reject_constant(value):
    raise Invalid("non-JSON constant: " + value)


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique_keys, parse_constant=reject_constant)


def candidates(data):
    judge = token(data["judge_family"])
    entries = data["candidates"]
    require(type(entries) is list and len(entries) >= 2, "at least two candidates required")
    ids = []
    for entry in entries:
        object_keys(entry, ("id", "family"))
        name = identity(entry["id"])
        require(name not in ids, "duplicate candidate")
        require(token(entry["family"]) != judge, "judge must be from a different family")
        ids.append(name)
    return sorted(ids)


def pairs(data):
    object_keys(data, ("candidates", "judge_family"))
    ids = candidates(data)
    return {"tasks": [{"left": a, "right": b}
                      for i, left in enumerate(ids) for right in ids[i + 1:]
                      for a, b in ((left, right), (right, left))]}


def solve(matrix, rhs):
    """Gaussian elimination with partial pivoting, on the pinned Laplacian."""
    size = len(rhs)
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(matrix[row][column]))
        require(math.isfinite(matrix[pivot][column]) and matrix[pivot][column] != 0,
                "singular Bradley-Terry fit")
        matrix[column], matrix[pivot] = matrix[pivot], matrix[column]
        rhs[column], rhs[pivot] = rhs[pivot], rhs[column]
        diagonal = matrix[column][column]
        for row in range(column + 1, size):
            if matrix[row][column] == 0:
                continue
            factor = matrix[row][column] / diagonal
            matrix[row][column] = 0.0
            for j in range(column + 1, size):
                matrix[row][j] -= factor * matrix[column][j]
            rhs[row] -= factor * rhs[column]
    solution = [0.0] * size
    for row in range(size - 1, -1, -1):
        remainder = math.fsum(matrix[row][j] * solution[j] for j in range(row + 1, size))
        solution[row] = (rhs[row] - remainder) / matrix[row][row]
    require(all(math.isfinite(value) for value in solution), "nonfinite fit step")
    return solution


def fit(ids, edges):
    """Fit log strengths; pin one coordinate to remove additive ambiguity."""
    index = {name: i for i, name in enumerate(ids)}
    games = [(index[a], index[b], wins, total) for (a, b), (wins, total) in edges.items()]
    size = len(ids)
    theta = [0.0] * size
    previous = None

    def likelihood(values):
        terms = []
        for a, b, wins, total in games:
            difference = values[a] - values[b]
            # Stable log-sigmoids, without exponentiating an absolute strength.
            tail = math.log1p(math.exp(-abs(difference)))
            terms.append(-wins * (max(-difference, 0) + tail)
                         - (total - wins) * (max(difference, 0) + tail))
        return math.fsum(terms)

    while True:
        terms = [[] for _ in ids]
        laplacian = [[0.0] * (size - 1) for _ in range(size - 1)]
        for a, b, wins, total in games:
            difference = theta[a] - theta[b]
            tail = math.exp(-abs(difference))
            probability = 1 / (1 + tail) if difference >= 0 else tail / (1 + tail)
            residual = wins - total * probability
            terms[a].append(residual)
            terms[b].append(-residual)
            weight = total * tail / (1 + tail) ** 2
            for i in (a, b):
                if i:
                    laplacian[i - 1][i - 1] += weight
            if a and b:
                laplacian[a - 1][b - 1] -= weight
                laplacian[b - 1][a - 1] -= weight
        gradient = [math.fsum(values) for values in terms]
        if max(abs(value) for value in gradient) < 1e-9:
            break
        step = solve(laplacian, gradient[1:])
        gain = math.fsum(g * delta for g, delta in zip(gradient[1:], step))
        require(math.isfinite(gain) and gain > 0, "nonascending fit step")
        current = likelihood(theta)
        scale = 1.0
        while True:
            trial = [0.0] + [value + scale * delta for value, delta in zip(theta[1:], step)]
            require(all(math.isfinite(value) for value in trial), "nonfinite fit")
            require(trial != theta and trial != previous,
                    "Bradley-Terry fit stalled numerically; no ranking published")
            # Damping protects the likelihood; allow only floating-point roundoff.
            if likelihood(trial) >= current + 1e-4 * scale * gain - 1e-12 * (1 + abs(current)):
                break
            scale /= 2
        previous, theta = theta, trial

    maximum = max(theta)
    normalizer = math.log(math.fsum(math.exp(value - maximum) for value in theta))
    logs = {name: theta[i] - maximum - normalizer for i, name in enumerate(ids)}
    require(all(math.isfinite(value) for value in logs.values()), "nonfinite log strength")
    return logs


def rank(data):
    object_keys(data, ("candidates", "judge_family", "comparisons"))
    ids = candidates(data)
    rows = data["comparisons"]
    require(type(rows) is list and rows, "comparisons must be a nonempty list")
    # Aggregate counts, never update ratings in observation order.
    counts = defaultdict(Counter)
    for row in rows:
        object_keys(row, ("left", "right", "winner", "reason"))
        a, b, winner = row["left"], row["right"], row["winner"]
        require(type(a) is str and type(b) is str and a in ids and b in ids and a != b,
                "comparison must name two distinct known candidates")
        require(type(winner) is str and winner in ("left", "right", "tie"),
                "winner must be left, right or tie")
        require(type(row["reason"]) is str and row["reason"].strip(), "reason required")
        counts[(a, b)][winner] += 1

    edges = {}
    splits = 0
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            forward, reverse = counts[(a, b)], counts[(b, a)]
            n = sum(forward.values())
            require(n == sum(reverse.values()), "every pair needs equally many orders")
            if not n:
                continue
            # Minimum number of verdicts that disagree across presentation orders.
            same = (min(forward["left"], reverse["right"]) +
                    min(forward["right"], reverse["left"]) +
                    min(forward["tie"], reverse["tie"]))
            splits += n - same
            a_wins = forward["left"] + reverse["right"]
            ties = forward["tie"] + reverse["tie"]
            # Half-win symmetric smoothing keeps unanimous records finite.
            edges[(a, b)] = (a_wins + ties / 2 + 0.5, 2 * n + 1)

    seen = {ids[0]}
    while True:
        expanded = seen | {v for a, b in edges for u, v in ((a, b), (b, a)) if u in seen}
        if expanded == seen:
            break
        seen = expanded
    require(len(seen) == len(ids), "comparison graph must be connected")

    logs = fit(ids, edges)
    ordered = sorted(ids, key=lambda name: (-logs[name], name))
    best = logs[ordered[0]]
    top = sorted(name for name in ids if math.isclose(logs[name], best, rel_tol=0, abs_tol=1e-8))
    return {"ranking": [{"id": name, "strength": math.exp(logs[name]),
                         "log_strength": logs[name]} for name in ordered],
            "top": top, "winner": top[0] if len(top) == 1 else None,
            "observations": len(rows), "position_splits": splits,
            "prior_wins_per_pair": 0.5}


def category(value):
    require(type(value) is str and re.fullmatch(r"[a-z][a-z0-9]*(?:[ -][a-z0-9]+)*", value),
            "category must be lowercase words")
    return value


def panel(data):
    """The council's categories, candidates, references and judges."""
    categories = data["categories"]
    require(type(categories) is list and categories, "categories must be a nonempty list")
    require(len(set(map(category, categories))) == len(categories), "duplicate category")
    kinds = {}
    for entry in data["artifacts"] if type(data["artifacts"]) is list else [None]:
        require(type(entry) is dict and len(entry) == 2 and "id" in entry,
                "artifact must be {id, family} or {id, reference}")
        name = identity(entry["id"])
        require(name not in kinds, "duplicate artifact")
        if "family" in entry:
            token(entry["family"])
            kinds[name] = None  # a candidate; a reference keeps its product name
        else:
            object_keys(entry, ("id", "reference"))
            require(type(entry["reference"]) is str and entry["reference"].strip(),
                    "reference needs its product's name")
            kinds[name] = entry["reference"]
    require(None in kinds.values(), "at least one candidate required")
    require(any(kind is not None for kind in kinds.values()),
            "at least one named reference required")
    judges = {}
    for entry in data["judges"] if type(data["judges"]) is list else [None]:
        object_keys(entry, ("id", "family", "cost"))
        name = identity(entry["id"])
        require(name not in judges, "duplicate judge")
        require(type(entry["cost"]) is int and entry["cost"] > 0,
                "judge cost must be a positive integer rank")
        judges[name] = (token(entry["family"]), entry["cost"])
    require(len(judges) >= 3, "a council needs at least three judges")
    require(len({family for family, _ in judges.values()}) >= 2,
            "a council needs at least two model families")
    cheapest = min(cost for _, cost in judges.values())
    cheap = sorted(name for name, (_, cost) in judges.items() if cost == cheapest)
    require(len({judges[name][0] for name in cheap}) == 1,
            "the cheapest judges must be from one family")
    return categories, kinds, judges, cheap


def mean(values):
    return math.fsum(values) / len(values)


def score_round(row, categories, kinds, judges, seat):
    object_keys(row, ("round", "judges", "scores"))
    seated = row["judges"]
    require(type(seated) is list and all(type(name) is str for name in seated) and
            len(set(seated)) == len(seated) and set(seated) == set(seat),
            "round must seat exactly: " + ", ".join(seat))
    rows = row["scores"]
    require(type(rows) is list and rows, "scores must be a nonempty list")
    marks = {}
    for mark in rows:
        object_keys(mark, ("judge", "artifact", "category", "score", "reason"))
        key = (mark["judge"], mark["artifact"], mark["category"])
        require(all(type(value) is str for value in key) and
                mark["judge"] in seat and mark["artifact"] in kinds and
                mark["category"] in categories, "score must name a seated judge, "
                "a known artifact and a rubric category")
        require(type(mark["score"]) is int and 1 <= mark["score"] <= 10,
                "score must be an integer from 1 to 10")
        require(type(mark["reason"]) is str and mark["reason"].strip(), "reason required")
        require(key not in marks, "duplicate score")
        marks[key] = mark["score"]
    present = sorted({artifact for _, artifact, _ in marks})
    references = [name for name in present if kinds[name] is not None]
    candidates_ = [name for name in present if kinds[name] is None]
    require(len(references) == sum(kind is not None for kind in kinds.values()),
            "every reference is scored in every round")
    require(candidates_, "every round scores at least one candidate")
    require(len(marks) == len(seat) * len(present) * len(categories),
            "every seated judge scores every artifact in every category")

    def means(group):
        return {name: {cat: mean([marks[(judge, name, cat)] for judge in group])
                       for cat in categories} for name in present}

    families = sorted({judges[name][0] for name in seat})
    by_family = {family: means([j for j in seat if judges[j][0] == family])
                 for family in families}
    leaders = [name for name in candidates_
               if all(by_family[f][name][cat] > by_family[f][ref][cat]
                      for f in families for cat in categories for ref in references)]
    council = means(seat)
    overall = {name: mean(list(council[name].values())) for name in candidates_}
    best = max(overall.values())
    top = [name for name in candidates_
           if math.isclose(overall[name], best, rel_tol=0, abs_tol=1e-9)]
    return {"round": row["round"], "judges": sorted(seat), "means": council,
            "family_means": by_family, "references": references, "leaders": leaders,
            "top": top, "best": top[0] if len(top) == 1 else None}, marks


def council_rounds(data):
    object_keys(data, ("categories", "artifacts", "judges", "rounds"))
    categories, kinds, judges, cheap = panel(data)
    rounds = data["rounds"]
    require(type(rounds) is list, "rounds must be a list")
    phase, results = "cheap", []
    for expected, row in enumerate(rounds):
        require(type(row) is dict and type(row.get("round")) is int and
                row["round"] == expected, "rounds must be contiguous from round 0")
        seat = cheap if phase == "cheap" else sorted(judges)
        result, marks = score_round(row, categories, kinds, judges, seat)
        results.append(({"phase": phase, **result}, marks))
        # The cheapest judge alone until it is satisfied, then the whole council.
        if result["leaders"]:
            phase = "full"
    return categories, kinds, judges, cheap, phase, results


def council(data, window):
    _, _, judges, cheap, phase, results = council_rounds(data)
    leader, streak = None, 0
    for result, _ in results:
        if result["phase"] != "full":
            continue
        # Count a round only when the kept candidate is its one leader (#1354 R1).
        only = result["best"] if result["leaders"] == [result["best"]] else None
        streak = streak + 1 if only is not None and only == leader else int(only is not None)
        leader = only
    stop = streak >= window
    return {"rounds": [result for result, _ in results], "next_phase": phase,
            "next_judges": cheap if phase == "cheap" else sorted(judges),
            "consistent_rounds": streak, "leader": leader,
            "stop": stop, "reason": "references" if stop else "continue"}


def table(data):
    categories, kinds, judges, _, _, results = council_rounds(data)

    def label(name):
        if kinds[name] is None:
            return name
        return f"{name} (reference: {kinds[name]})".replace("|", "\\|")

    lines = ["| " + " | ".join(["Round", "Phase", "Judge", "Artifact", *categories,
                                "Leader"]) + " |",
             "|" + " --- |" * (len(categories) + 5)]
    for result, marks in results:
        head = [str(result["round"]), result["phase"]]
        for judge in result["judges"]:
            for name in result["means"]:
                cells = [str(marks[(judge, name, cat)]) for cat in categories]
                lines.append("| " + " | ".join([*head, f"{judge} ({judges[judge][0]})",
                                                label(name), *cells, ""]) + " |")
        for name, values in result["means"].items():
            cells = [f"{values[cat]:.2f}" for cat in categories]
            lead = "yes" if name in result["leaders"] else ""
            lines.append("| " + " | ".join([*head, "council", label(name), *cells, lead]) + " |")
    return "\n".join(lines)


def stall(data, window):
    object_keys(data, ("rounds", "stopped_by_jake"))
    require(type(data["stopped_by_jake"]) is bool, "stopped_by_jake must be Boolean")
    rounds = data["rounds"]
    require(type(rounds) is list, "rounds must be a list")
    unchanged = 0
    previous = None
    for expected, row in enumerate(rounds):
        object_keys(row, ("round", "winner"))
        require(type(row["round"]) is int and row["round"] == expected,
                "rounds must be contiguous from baseline round 0")
        winner = row["winner"]
        if winner is not None:
            identity(winner)
        unchanged = unchanged + 1 if winner is not None and winner == previous else 0
        previous = winner
    reason = "jake" if data["stopped_by_jake"] else "stall" if unchanged >= window else "continue"
    return {"stop": reason != "continue", "reason": reason, "unchanged_rounds": unchanged}


def odds(data, baseline):
    ranked = rank(data)
    logs = {row["id"]: row["log_strength"] for row in ranked["ranking"]}
    require(baseline in logs, "baseline must be a known candidate")

    def beats(gap):
        # Logistic of the log-strength gap, stable at either extreme, so
        # strengths that underflow to zero never divide 0 by 0.
        return 1 / (1 + math.exp(-gap)) if gap >= 0 else math.exp(gap) / (1 + math.exp(gap))
    return {"baseline": baseline,
            "odds": [{"id": row["id"], "beats_baseline": beats(logs[row["id"]] - logs[baseline])}
                     for row in ranked["ranking"]]}


def positive(value):
    require(re.fullmatch(r"[1-9][0-9]*", value), "window must be a positive integer")
    return int(value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    windows = {"stall": "unchanged completed rounds after the winner was selected",
               "council": "consecutive full-council rounds the same leader must lead"}
    for name in ("pairs", "rank", "stall", "council", "table", "odds"):
        child = commands.add_parser(name)
        child.add_argument("input", help="UTF-8 JSON file (read only)")
        if name in windows:
            child.add_argument("--window", required=True, type=positive, help=windows[name])
        if name == "odds":
            child.add_argument("--baseline", required=True, help="the stretch's fixed baseline id")
    try:
        args = parser.parse_args()
        data = load(args.input)
        if args.command == "table":
            output = table(data)
        else:
            command = globals()[args.command]
            if args.command == "odds":
                result = odds(data, args.baseline)
            else:
                result = command(data, args.window) if args.command in windows else command(data)
            output = json.dumps(result, allow_nan=False, sort_keys=True)
    except (OSError, ValueError, UnicodeError, OverflowError) as error:
        parser.error(str(error))
    print(output)


if __name__ == "__main__":
    main()
