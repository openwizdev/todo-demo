"""Review mechanics for review-ticket: pin the head, check and post the report, file a follow-up.

  pin --repo O/R --pr N --head SHA           which review is due at the assigned head, or why none is
  check REPORT --repo O/R --pr N --head SHA  admission, then the report's contract lines
  post REPORT --repo O/R --pr N --head SHA   admission and check again, post once, read back
  follow-up --repo TICKET_REPO ...   file one polish issue or logged blocker for triage, once
  self-check DESCRIPTION [--base REF]       the builder's own pass on its checkout, before any review

Each command reads one pull-request snapshot and admits it (open, ready, a
ticket, the assigned head, every required check green there) before anything
else (self-check reads only the local checkout and description, before a pull
request exists). Settings are read from the base branch, never the pull request's head.
Only comments by the `Record authors` row of docs/agents/fleet.md count. Exit 0
done, 1 a stop, report problems or an unknown write, 2 a refusal (unreadable
or invalid settings, arguments). Python 3.11+ standard library and `gh`.
"""
import argparse
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

SHA = re.compile(r"[0-9a-f]{40}")
VERDICT = re.compile(r"VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})")
FINDING = re.compile(r"- \*\*(R[1-9][0-9]*) \[([a-z]+)\]\*\* (.*)")
NEW = re.compile(r"`[^`\s]+:[1-9][0-9]*` \((?:Standards|Spec|Sweep)\) \S")
STATUSES = ("resolved at ", "withdrawn: ", "still open after the ", "disputed, kept: ", "Polish issue: #")
BLOCKER_STATUSES = ("resolved at ", "withdrawn: ", "still open after the ", "disputed, kept: ")
POLISH_STATUSES = ("Polish issue: #", "withdrawn: ")
OPEN = ("still open after the ", "disputed, kept: ")
USER = re.compile(r"User path: \S.*")
RISK = re.compile(r"Risk: (?:security|privacy|data loss): \S.*")
POLISH = re.compile(r"Polish issue: #[1-9][0-9]*\.?$")
LOGGED = re.compile(r".*\bLogged as follow-up #[1-9][0-9]*\.$")
MARK = re.compile(r"- \*\*Ruling ([1-9][0-9]*)\*\* (?:upheld|overturned as (R[1-9][0-9]*)): \S.*")
IDS = r"R[1-9][0-9]*(?:(?:, R[1-9][0-9]*)* and R[1-9][0-9]*)?"
NEXT = {"builder": rf"Next: the builder fixes or disputes ({IDS}) once, then one re-check\.",
        "fresh": rf"Next: a fresh, stronger builder fixes ({IDS}) once, then one final check\.",
        "park": rf"Next: park ({IDS}) as a decision for Jake\.",
        "merge": r"Next: none open\. It merges by the project's merge rules\."}
ROUNDS = {"full": ("Full review by ", ("builder", "merge"), "the builder line or none open"),
          "re-check": ("Re-check of ", ("fresh", "merge"), "the fresh line or none open"),
          "final": ("Final check of ", ("park", "merge"), "the park line or none open"),
          "log-and-merge": ("Final check of ", ("merge",), "none open")}
DECISION = re.compile(rf"\*\*Orchestrator decision:\*\* (fix once more|log and merge): ({IDS}) at ([0-9a-f]{{40}})\."
                      r"(?: Polish issues: (#[1-9][0-9]*(?:, #[1-9][0-9]*)*)\.)? Why: \S.*", re.S)
ADDITIONAL = re.compile(r"\*\*Additional\b[^*\n]*? check: `([^`]+)`")
CLOSES = re.compile(r"(?im)^\s*(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+((?:[\w.-]+/[\w.-]+)?#[1-9][0-9]*)\b")
LOGIN = r"`[A-Za-z0-9](?:-?[A-Za-z0-9])*(?:\[bot\])?`"
# The whole cell, as launch-fleet's grants.py reads it: backticked logins separated by commas.
AUTHORS_CELL = re.compile(rf"\s*{LOGIN}(?:\s*,\s*{LOGIN})*\s*")
TEST_RULE = re.compile(r"\b(?:catches|no new test): \S")
PRIVATE = re.compile(r"\b(?:gh[pousr]_|github_pat_|sk-)[A-Za-z0-9_-]{8,}|\bthr_[A-Za-z0-9]{4,}|(?i:\bbearer\s+[A-Za-z0-9._-]{8,})")


class Refusal(Exception):
    pass


class Stop(Exception):
    pass


def gh(*args, data=None):
    try:
        out = subprocess.run(["gh", "api", *args], input=data, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return 1, None
    try:
        return out.returncode, json.loads(out.stdout) if out.stdout.strip() else None
    except json.JSONDecodeError:
        return 1, None


def get(url):
    code, value = gh(url)
    if code or value is None:
        raise Refusal(f"cannot read {url.split('?')[0]}")
    return value


def pages(url):
    code, value = gh("--paginate", "--slurp", url)
    if code or not isinstance(value, list):
        raise Refusal(f"cannot read {url.split('?')[0]}")
    return [item for page in value for item in page]


def setting(repo, ref, path):
    data = get(f"repos/{repo}/contents/{path}?ref={quote(ref, safe='')}")
    return base64.b64decode(data["content"]).decode()


def section(text, heading):
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = line.strip() == heading
        elif inside:
            lines.append(line)
    return lines


def cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")] if line.strip().startswith("|") else []


def record_authors(fleet):
    """Lowercase logins from the one Record authors row, read whole as launch-fleet reads it, or a refusal."""
    heading, rows = None, []
    for line in fleet.splitlines():
        if line.startswith("## "):
            heading = line.strip()
        elif heading == "## GitHub identity" and re.match(r"\| *Record authors *\|", line):
            rows.append(line)
    row = rows[0].split("|") if len(rows) == 1 else []
    if not (len(row) == 4 and not row[3].strip() and AUTHORS_CELL.fullmatch(row[2])):
        raise Refusal("docs/agents/fleet.md has no single valid record authors row; trust nobody and ask on the ticket")
    return {x.lower() for x in re.findall(r"`([^`]*)`", row[2])}


def required_checks(fleet):
    """Every check the ## CI checks section requires: the table's names and any **Additional ... check: `x`**."""
    lines = section(fleet, "## CI checks")
    names = [m[1] for line in lines if (row := cells(line)) and (m := re.fullmatch(r"`([^`]+)`", row[0]))]
    names += [n for n in ADDITIONAL.findall("\n".join(lines)) if n not in names]
    if not names:
        raise Refusal("docs/agents/fleet.md's ## CI checks names no required check")
    return names


def ids_text(ids):
    ids = list(ids)
    return "none" if not ids else ids[0] if len(ids) == 1 else ", ".join(ids[:-1]) + " and " + ids[-1]


def parse(text):
    lines = text.replace("\r\n", "\n").split("\n")
    paras = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
    verdict = VERDICT.fullmatch(lines[0].strip()) if lines else None
    findings = []
    for i, raw in enumerate(lines):
        m = FINDING.fullmatch(raw.strip())
        if not m:
            continue
        more = []
        for line in lines[i + 1:]:
            if not line.strip() or not line[:1].isspace():
                break
            more.append(line.strip())
        rest = m[3]
        findings.append({"id": m[1], "grade": m[2], "new": bool(NEW.match(rest)), "text": rest,
                         "status": next((s for s in STATUSES if rest.startswith(s)), None),
                         "user": any(USER.fullmatch(x) for x in more), "risk": any(RISK.fullmatch(x) for x in more),
                         "polish": bool(POLISH.search(rest)), "logged": bool(LOGGED.fullmatch(rest))})
    nxt = paras[-1] if paras and paras[-1].startswith("Next:") else None
    state = next((s for s, p in NEXT.items() if nxt and re.fullmatch(p, nxt)), None)
    named = re.findall(r"R[1-9][0-9]*", nxt or "") if state != "merge" else []
    return {"verdict": verdict[1] if verdict else None, "head": verdict[2] if verdict else None,
            "paras": paras, "findings": findings, "state": state, "named": named,
            "marks": [(int(m[1]), m[2]) for x in lines if (m := MARK.fullmatch(x.strip()))],
            "no_rulings": any(x.strip() == "Rulings: none." for x in lines),
            "none": any(x.strip() == "No findings." for x in lines)}


def open_blockers(report):
    return [f["id"] for f in report["findings"] if f["grade"] == "blocking" and not f["logged"]
            and (f["new"] or (f["status"] or "").startswith(OPEN))]


def rulings_lines(text):
    """The stripped lines of the description's first unfenced ## Rulings section, or None without one."""
    lines, fenced, fence = text.splitlines(), [], False
    for line in lines:
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
        fenced.append(fence)
    heads = [i for i, x in enumerate(lines) if x.strip() == "## Rulings" and not fenced[i]]
    if not heads:
        return None
    out = []
    for line, quoted in zip(lines[heads[0] + 1:], fenced[heads[0] + 1:]):
        if re.match(r"#{1,2} ", line) and not quoted:
            break
        out.append(line.strip())
    return out


def description_rulings(text):
    return [int(m[1]) for line in rulings_lines(text) or [] if (m := re.match(r"([1-9][0-9]*)\. ", line))]


def check(text, description, mode, head, earlier, decision=None, changed=None):
    """Every contract line the report breaks; empty when it passes."""
    r, problems = parse(text), []
    if r["verdict"] is None:
        problems.append("the first line is VERDICT: APPROVE or CHANGES at the 40-character head")
    elif r["head"] != head:
        problems.append(f"VERDICT names {r['head']}, not the pinned head {head}")
    start, allowed, wording = ROUNDS[mode]
    second = r["paras"][1] if len(r["paras"]) > 1 else ""
    if not second.startswith(start):
        problems.append(f"the second paragraph starts {start.strip()}")
    elif "CI green on this commit: " not in second:
        problems.append("the second paragraph says CI green on this commit: <the required checks>")
    if not any(p.startswith("Intent: ") for p in r["paras"]):
        problems.append("no Intent: paragraph")
    ids = [f["id"] for f in r["findings"]]
    if not ids and not r["none"]:
        problems.append("no findings and no No findings. line")
    if ids != [f"R{n}" for n in range(1, len(ids) + 1)]:
        problems.append("ids run R1, R2, ... with no gap or repeat")
    before = {f["id"]: f for f in earlier["findings"]} if earlier else {}
    logged_ids = set(decision["ids"]) if decision and decision["kind"] == "log and merge" else set()
    problems += [f"{i}: a re-check gives every earlier id its status"
                 for i in sorted(set(before) - set(ids), key=lambda x: int(x[1:]))]
    for f in r["findings"]:
        i, blocking = f["id"], f["grade"] == "blocking"
        if f["grade"] not in ("blocking", "polish"):
            problems.append(f"{i}: the grade is blocking or polish")
        elif i in before and f["new"]:
            problems.append(f"{i}: an earlier id takes a status, not a new finding")
        elif i in before and not (f["status"] or f["logged"]):
            problems.append(f"{i}: an earlier id takes one status from the table")
        elif i not in before and not f["new"]:
            problems.append(f"{i}: a new finding names `file:line` and its check (Standards, Spec or Sweep)")
        elif f["new"] and blocking and not (f["user"] or f["risk"]):
            problems.append(f"{i}: a new blocking finding needs its User path: or Risk: line")
        elif f["new"] and not blocking and not f["polish"]:
            problems.append(f"{i}: a new polish finding ends with Polish issue: #<n>")
        where = re.match(r"`([^`\s]+):[1-9][0-9]*`", f["text"]) if f["new"] and i not in before else None
        if where and changed is not None and where[1] not in changed and not f["risk"]:
            problems.append(f"{i}: `{where[1]}` is unchanged since {earlier['head'][:7]}; a re-check raises a new "
                            "finding there only as a Risk: security, privacy or data-loss blocker")
        old = before.get(i)
        if i in logged_ids:
            if not (f["grade"] == "polish" and f["status"] == "Polish issue: #"
                    and re.search(r"#[1-9][0-9]*", f["text"])[0] in decision["polish"]):
                problems.append(f"{i}: the decision grades it polish with Polish issue: {' or '.join(decision['polish'])}")
            continue
        if old and f["grade"] != old["grade"] and f["grade"] in ("blocking", "polish"):
            problems.append(f"{i}: keeps its earlier grade, {old['grade']}")
        elif old and blocking and f["status"] and f["status"] not in BLOCKER_STATUSES:
            problems.append(f"{i}: a blocker's status is resolved, withdrawn, still open, disputed or logged")
        elif old and not blocking and f["status"] and f["status"] not in POLISH_STATUSES:
            problems.append(f"{i}: a polish finding's status is Polish issue: #<n> or withdrawn")
        if old and old["risk"] and f["user"] and not f["risk"]:
            problems.append(f"{i}: keeps its Risk: line")
        if f["logged"] and (f["risk"] or not blocking):
            problems.append(f"{i}: a Risk: blocker is never logged" if f["risk"] else f"{i}: only a blocker is logged")
        elif blocking and not f["new"] and (f["logged"] or (f["status"] or "").startswith(OPEN)) \
                and not (f["user"] or f["risk"]):
            problems.append(f"{i}: an open or logged blocker restates its User path: or Risk: line")
    opened = open_blockers(r)
    risky = {f["id"] for f in r["findings"] if f["risk"]}
    if mode != "full":
        problems += [f"{i}: only a Risk: blocker goes to the fresh round; log a User path: blocker"
                     for i in opened if i not in risky]
    if r["verdict"] and (r["verdict"] == "CHANGES") != bool(opened):
        problems.append("VERDICT is CHANGES exactly while a blocker is open")
    if r["state"] is None:
        problems.append("the last paragraph is one of the four Next: lines")
    elif r["state"] not in allowed:
        problems.append(f"a {'full review' if mode == 'full' else mode.replace('final', 'final check')}'s "
                        f"Next: is {wording}")
    elif set(r["named"]) != set(opened):
        problems.append(f"Next: names {ids_text(r['named'])}, but the open blockers are {ids_text(opened)}")
    listed, marked = description_rulings(description), [n for n, _ in r["marks"]]
    problems += [f"Ruling {n}: listed in the description but not marked" for n in listed if n not in marked]
    problems += [f"Ruling {n}: marked but not listed in the description" for n in sorted(set(marked) - set(listed))]
    problems += [f"Ruling {n}: marked twice" for n in sorted({n for n in marked if marked.count(n) > 1})]
    problems += [f"Ruling {n}: overturned as {i}, which is not a finding" for n, i in r["marks"] if i and i not in ids]
    named = [i for _, i in r["marks"] if i]
    problems += [f"{i}: named by two overturned rulings" for i in sorted({i for i in named if named.count(i) > 1})]
    if r["no_rulings"] and marked:
        problems.append("Rulings: none. stands beside a ruling mark")
    if not listed and not r["no_rulings"]:
        problems.append("with no rulings listed, the report says Rulings: none.")
    if PRIVATE.search(text):
        problems.append("private material: a token or thread id")
    return problems


def authored(comment, authors):
    return ((comment.get("user") or {}).get("login") or "").lower() in authors


def same(comment, text):
    return (comment.get("body") or "").replace("\r\n", "\n").strip() == text.strip()


def admit(repo, number, assigned, skip=None):
    """One snapshot of the pull request, admitted at the assigned head, and the review it is due."""
    pr = get(f"repos/{repo}/pulls/{number}")
    head = pr["head"]["sha"]
    if pr.get("state") != "open":
        raise Stop(f"stop: {'merged' if pr.get('merged') else 'closed'}; archive your own thread")
    if pr.get("draft"):
        raise Stop("stop: draft")
    ticket = CLOSES.search(pr.get("body") or "")
    if not ticket:
        raise Stop("stop: no Closes line names a ticket")
    if head != assigned:
        raise Stop(f"stop: the head is {head}, not the assigned {assigned}")
    fleet = setting(repo, pr["base"]["ref"], "docs/agents/fleet.md")
    authors, names = record_authors(fleet), required_checks(fleet)
    runs = get(f"repos/{repo}/commits/{head}/check-runs?per_page=100").get("check_runs", [])
    bad = []
    for name in names:
        mine = [x for x in runs if x.get("name") == name]
        latest = max(mine, key=lambda x: (x.get("started_at") or "", x.get("id") or 0), default=None)
        if not latest or (latest.get("status"), latest.get("conclusion")) != ("completed", "success"):
            bad.append(name)
    if bad:
        raise Stop(f"stop: {', '.join(bad)} is not green at {head}")
    comments = pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
    records = [c for c in comments if authored(c, authors)]
    reports = [(n, parse(c["body"].replace("\r\n", "\n"))) for n, c in enumerate(records)
               if (c.get("body") or "").startswith("VERDICT: ") and not (skip and same(c, skip))]
    at, last = reports[-1] if reports else (None, None)
    decision, mode = None, "full"
    if last is not None and last["state"] == "park":
        for c in records[at + 1:]:
            m = DECISION.fullmatch((c.get("body") or "").strip())
            if m and m[3] == last["head"] and set(re.findall(r"R[1-9][0-9]*", m[2])) == set(last["named"]):
                decision = {"kind": m[1], "ids": last["named"], "id": c.get("id"),
                            "polish": re.findall(r"#[1-9][0-9]*", m[4] or "")}
        if decision is None or (decision["kind"] == "log and merge" and not decision["polish"]):
            raise Stop(f"stop: {ids_text(last['named'])} is parked as a decision for Jake")
        if decision["kind"] == "log and merge":
            if head != last["head"]:
                raise Stop(f"stop: the log-and-merge decision is for {last['head']}, not {head}")
            mode = "log-and-merge"
        else:
            mode = "final"
    elif last is not None and last["state"] is None:
        raise Stop("stop: the last report has no Next: line; ask the orchestrator")
    elif last is not None:
        mode = "final" if last["state"] == "fresh" else "re-check"
    if last is not None and last["head"] == head and mode != "log-and-merge":
        raise Stop(f"stop: already reported at {head}")
    ref = ticket[1] if not ticket[1].startswith("#") else repo + ticket[1]
    return {"pr": pr, "head": head, "ticket": ref, "checks": names, "authors": authors,
            "comments": comments, "last": last, "mode": mode, "decision": decision}


def pin(repo, number, assigned):
    s = admit(repo, number, assigned)
    line = f"review {s['mode']} #{number} at {s['head']}; ticket {s['ticket']}; checks {', '.join(s['checks'])}"
    if s["last"] is not None:
        ids = [int(f["id"][1:]) for f in s["last"]["findings"]]
        line += (f"; last read {s['last']['head']}; open {ids_text(open_blockers(s['last']))}; "
                 f"next id R{max(ids, default=0) + 1}")
    return line


def changed_since(repo, last, head):
    """Every file the compare from the last read head to this one changes; unreadable or truncated refuses."""
    files = get(f"repos/{repo}/compare/{last}...{head}").get("files")
    if not isinstance(files, list) or len(files) >= 300:  # GitHub lists at most 300 files
        raise Refusal(f"cannot read every file changed since {last[:7]}")
    return {x["filename"] for x in files}


def report_problems(path, repo, number, assigned):
    text = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    s = admit(repo, number, assigned, skip=text)
    changed = changed_since(repo, s["last"]["head"], s["head"]) if s["mode"] in ("re-check", "final") else None
    return text, s, check(text, s["pr"].get("body") or "", s["mode"], s["head"], s["last"], s["decision"], changed)


def git(*args):
    try:
        out = subprocess.run(["git", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out is None or out.returncode:
        raise Refusal(f"cannot read {args[-1]} with git")
    return out.stdout


def self_check(path, base):
    """The reviewer's mechanical checks on the builder's own hand-back: each miss, then the tally."""
    try:
        description = Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")
    except (OSError, UnicodeDecodeError):
        raise Refusal(f"cannot read {path}")
    head = git("rev-parse", "--verify", "HEAD^{commit}").strip()
    diff = git("-c", "core.quotePath=false", "diff", "--unified=0", "--no-color", "--no-ext-diff", f"{base}...HEAD")
    misses, rulings = [], rulings_lines(description)
    if not CLOSES.search(description):
        misses.append("no Closes line names the ticket; the review cannot start")
    if rulings is None or not (description_rulings(description) or {"none", "`none`"} & set(rulings)):
        misses.append("no ## Rulings section with numbered rulings or exactly none")
    if head not in description:
        misses.append(f"the description does not name the head {head}")
    if not TEST_RULE.search(description):
        misses.append("no `catches: <the bug>` or `no new test: <why>` line")
    leaks = ["the description"] if PRIVATE.search(description) else []
    name, header = None, False
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            header = True
        elif header and line.startswith("+++ "):
            name = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("@@"):
            header = False
        elif not header and line.startswith("+") and PRIVATE.search(line) and name not in leaks:
            leaks.append(name)
    misses += [f"private material (a token or thread id) in {x}" for x in leaks]
    lines = [f"miss: {m}" for m in misses]
    return lines + [f"self-check: {len(misses)} miss{'es' if len(misses) != 1 else ''}" if misses else "self-check: ok"]


def post(path, repo, number, assigned):
    text, s, problems = report_problems(path, repo, number, assigned)
    mine = [c for c in s["comments"] if authored(c, s["authors"]) and same(c, text)]
    if mine:  # this exact report, naming this head, already stands as a record
        return f"already posted {mine[0]['id']}"
    if problems:
        raise Stop("\n".join(problems))
    before = {c.get("id") for c in s["comments"]}
    code, made = gh("-X", "POST", f"repos/{repo}/issues/{number}/comments", "--input", "-",
                    data=json.dumps({"body": text}))
    if code == 0 and isinstance(made, dict) and made.get("id") is not None:
        back = gh(f"repos/{repo}/issues/comments/{made['id']}")[1]
        found = back if isinstance(back, dict) and same(back, text) else None
    else:  # the response was lost: only a new comment of this report counts
        found = next((c for c in pages(f"repos/{repo}/issues/{number}/comments?per_page=100")
                      if c.get("id") not in before and same(c, text)), None)
    if not found:
        raise Stop("unknown: not found on read-back; read the comments before posting again")
    if not authored(found, s["authors"]):
        raise Stop(f"posted {found['id']} by an account that is not a record author; it will not count")
    return f"posted {found['id']}"


def follow_up(a):
    repo = a.repo
    labels = setting(repo, get(f"repos/{repo}")["default_branch"], "docs/agents/triage-labels.md")
    found = [row[1].strip("` ") for line in labels.splitlines()
             if len(row := cells(line)) >= 2 and row[0] == "`needs-triage`"]
    if len(found) != 1 or not found[0]:
        raise Refusal("docs/agents/triage-labels.md names no single needs-triage label; the project needs the setup skill")
    if re.search(r"[`$\"]", a.title):
        raise Refusal("keep backticks, $ and double quotes out of the title")
    finding = Path(a.finding).read_text(encoding="utf-8").strip()
    finding += "" if finding.endswith(".") else "."
    head = f"Follow-up of #{a.ticket} (spec #{a.spec})\n\n"
    if a.logged:
        if not a.user_path:
            raise Refusal("a logged blocker carries its --user-path")
        title = f"{a.title} (follow-up for #{a.ticket}, {a.id})"
        body = (head + f"{finding}\nUser path: {a.user_path}\n\nStill open after the {a.logged} of pull request "
                f"{a.pr} at {a.head}; logged, so it did not block the merge.\n")
    else:
        title = f"{a.title} (polish for #{a.ticket}, {a.id})"
        body = head + f"{finding} Found in pull request {a.pr} at {a.head}; it is polish and did not block the merge.\n"
    if PRIVATE.search(title + body):
        raise Refusal("private material: a token or thread id")
    url = f"repos/{repo}/issues?state=all&per_page=100&labels={quote(found[0], safe='')}"

    def existing():
        return next((i for i in pages(url) if i.get("title") == title), None)
    if issue := existing():
        return f"already filed #{issue['number']}"
    gh("-X", "POST", f"repos/{repo}/issues", "--input", "-",
       data=json.dumps({"title": title, "body": body, "labels": [found[0]]}))
    if issue := existing():
        return f"filed #{issue['number']}"
    raise Stop("unknown: not found on read-back; list the issues before filing again")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("pin", "check", "post"):
        c = sub.add_parser(name)
        if name != "pin":
            c.add_argument("report")
        c.add_argument("--repo", required=True)
        c.add_argument("--pr", required=True, type=int)
        c.add_argument("--head", required=True, help="the assigned head, all 40 characters")
    f = sub.add_parser("follow-up")
    for name in ("repo", "ticket", "spec", "pr", "head", "id", "title", "finding"):
        f.add_argument("--" + name, required=True)
    f.add_argument("--logged", choices=("re-check", "final check"))
    f.add_argument("--user-path")
    c = sub.add_parser("self-check")
    c.add_argument("description", help="the pull request description you will hand back, as a file")
    c.add_argument("--base", default="origin/main")
    a = p.parse_args(argv)
    try:
        if a.command == "self-check":
            lines = self_check(a.description, a.base)
            print("\n".join(lines))
            return 0 if lines == ["self-check: ok"] else 1
        if a.command == "pin":
            print(pin(a.repo, a.pr, a.head))
        elif a.command == "check":
            problems = report_problems(a.report, a.repo, a.pr, a.head)[2]
            print("\n".join(problems) if problems else "report ok")
            return 1 if problems else 0
        elif a.command == "post":
            print(post(a.report, a.repo, a.pr, a.head))
        else:
            print(follow_up(a))
    except Stop as e:
        print(e)
        return 1
    except Refusal as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
