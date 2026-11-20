"""A fake `gh` for revision.sh's test: `gh issue view` over a synthetic
repository, as GitHub and gh answer it. Synthetic only; it never reaches a
network.

It answers only `gh issue view <n> --json <fields> [--jq <expr>]`, with the
fields revision.sh reads (number, title, body, blockedBy, subIssues). Any
other command, flag or field is refused (exit 2), so the test fails if the
script ever asks GitHub anything else. An issue that does not exist, or one
a world event made unreadable, fails as gh does (exit 1). The output is
jq's, passed on byte for byte: GitHub keeps a body's CRLF line ends.

    FAKE_GH_STATE=<dir> python3 -I fake_gh.py <gh arguments>
    FAKE_GH_STATE=<dir> python3 -I fake_gh.py --world <event.json>

<dir>/state.json is the repository: {"next_issue": n, "issues": [{"number",
"title", "body", "state", "parent", "milestone", "blockedBy": [n, ...],
"labels": [...], "comments": [...]}]}. A read never writes it. `--world`
applies an event that is not a call of revision.sh (an edit, a label, a
comment, a closed ticket, a blocker, a ticket added or dropped, a planted
read error) and saves it.

From the plan-graph dry run's fake (ClosedWiz#99) and #155's, cut down to
revision.sh's one command when its test moved beside the skill (#191).
"""

import json
import os
import subprocess
import sys

STATE_DIR = os.environ.get("FAKE_GH_STATE", "")
FIELDS = {"number", "title", "body", "blockedBy", "subIssues"}


class Refused(Exception):
    """A call revision.sh never makes: exit 2."""


class NotFound(Exception):
    """A read GitHub would fail: exit 1, as gh does."""


def load():
    with open(os.path.join(STATE_DIR, "state.json"), encoding="utf-8") as f:
        return json.load(f)


def save(state):
    path = os.path.join(STATE_DIR, "state.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(path + ".tmp", path)


def issue(state, n):
    for i in state["issues"]:
        if i["number"] == n:
            return i
    raise NotFound(f"Could not resolve to an issue or pull request with the number of {n}.")


def node(state, n):
    i = issue(state, n)
    return {"number": n, "state": i["state"], "title": i["title"]}


def shape(state, i, fields):
    out = {}
    for field in fields:
        if field not in FIELDS:
            raise Refused(f"--json field {field} is not one revision.sh reads")
        if field == "blockedBy":
            nodes = [node(state, n) for n in i["blockedBy"]]
            out[field] = {"nodes": nodes, "totalCount": len(nodes)}
        elif field == "subIssues":
            subs = [node(state, s["number"]) for s in state["issues"] if s["parent"] == i["number"]]
            out[field] = {"nodes": subs, "totalCount": len(subs)}
        else:
            out[field] = i[field]
    return out


def emit(value, jq):
    text = json.dumps(value).encode("utf-8")
    if jq is None:
        sys.stdout.buffer.write(text + b"\n")
        return
    run = subprocess.run(["jq", "-r", jq], input=text, capture_output=True, check=False)
    if run.returncode != 0:
        raise Refused(f"jq failed: {run.stderr.decode('utf-8', 'replace').strip()}")
    sys.stdout.buffer.write(run.stdout)


def view(state, args):
    if args[:2] != ["issue", "view"]:
        raise Refused("a gh command revision.sh does not use")
    rest, found, words = args[2:], {}, []
    while rest:
        if rest[0].startswith("-"):
            if rest[0] not in ("--json", "--jq") or rest[0] in found or len(rest) < 2:
                raise Refused(f"flag {rest[0]}: only --json <fields> and --jq <expr>, once each")
            found[rest[0]] = rest[1]
            rest = rest[2:]
        else:
            words.append(rest[0])
            rest = rest[1:]
    if len(words) != 1 or not words[0].isdigit() or "--json" not in found:
        raise Refused("issue view <n> --json <fields> [--jq <expr>] only")
    n = int(words[0])
    if n in state.get("unreadable", []):
        raise NotFound(f"#{n} could not be read (a planted read error)")
    emit(shape(state, issue(state, n), found["--json"].split(",")), found.get("--jq"))


def world(state, path):
    """Each key is optional; every issue it names must exist."""
    with open(path, encoding="utf-8") as f:
        event = json.load(f)
    for n in event.get("close", []):
        issue(state, n)["state"] = "CLOSED"
    for c in event.get("comment", []):
        issue(state, c["issue"])["comments"].append({"body": c["body"]})
    for e in event.get("edit", []):
        target = issue(state, e["issue"])
        for key in ("title", "body", "milestone"):
            if key in e:
                target[key] = e[key]
        if "replace" in e:
            old, new = e["replace"]
            if old not in target["body"]:
                raise NotFound(f"world edit: #{e['issue']}'s body has no {old!r}")
            target["body"] = target["body"].replace(old, new, 1)
    for e in event.get("add_blocked_by", []):
        issue(state, e["blocker"])
        issue(state, e["issue"])["blockedBy"].append(e["blocker"])
    for n in event.get("remove_sub_issue", []):
        issue(state, n)["parent"] = None
    for e in event.get("create", []):
        n = state["next_issue"]
        state["next_issue"] += 1
        new = {"number": n, "blockedBy": [], "labels": [], "state": "OPEN", "comments": [], "parent": None, "milestone": None}
        new.update(e)
        state["issues"].append(new)
    for e in event.get("labels", []):
        target = issue(state, e["issue"])
        target["labels"] = [x for x in target["labels"] if x not in e.get("remove", [])] + e.get("add", [])
    state["unreadable"] = state.get("unreadable", []) + event.get("unreadable", [])


def main():
    if not STATE_DIR:
        print("fake gh: FAKE_GH_STATE is not set", file=sys.stderr)
        return 2
    args = sys.argv[1:]
    try:
        state = load()
        if args[:1] == ["--world"] and len(args) == 2:
            world(state, args[1])
            save(state)
        else:
            view(state, args)
    except Refused as why:
        print(f"fake gh: refused: {why}: gh {' '.join(args)}", file=sys.stderr)
        return 2
    except NotFound as why:
        print(f"GraphQL: {why}", file=sys.stderr)
        return 1
    except (OSError, KeyError, ValueError) as why:
        print(f"fake gh: {why!r}: gh {' '.join(args)}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
