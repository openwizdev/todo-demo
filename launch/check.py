#!/usr/bin/env python3
"""Read-only caption data check for a launch demo repository.

Reads the spec, its tickets (sub-issues), their merged pull requests, and the
elapsed time from first prompt to last merge using the owner's `gh`. Never
writes to GitHub. Prints `unknown` for any line whose read fails.
"""

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys


REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9._-]+$")


def parse_utc(value):
    """Parse an ISO-8601 UTC timestamp into a timezone-aware datetime."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc)


def format_utc(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_elapsed(seconds):
    total = int(seconds)
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes or hours:
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return f"{' '.join(parts)} ({total}s)"


def run_gh_read(args):
    """Run a read-only `gh` command and return stdout, or None on any failure."""
    try:
        proc = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def parse_json_object(raw):
    if raw is None:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def parse_json_array_stream(raw):
    """Parse one or more concatenated JSON arrays (as emitted by `gh api --paginate`)."""
    if raw is None:
        return None
    decoder = json.JSONDecoder()
    idx = 0
    length = len(raw)
    items = []
    saw_any = False
    while idx < length:
        while idx < length and raw[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            chunk, next_idx = decoder.raw_decode(raw, idx)
        except ValueError:
            return None
        if not isinstance(chunk, list):
            return None
        items.extend(chunk)
        saw_any = True
        idx = next_idx
    return items if saw_any else None


def read_spec(repo, spec_number):
    raw = run_gh_read(
        [
            "issue",
            "view",
            str(spec_number),
            "-R",
            repo,
            "--json",
            "number,title,url,createdAt",
        ]
    )
    data = parse_json_object(raw)
    if data is None:
        return None
    if not isinstance(data.get("number"), int) or not isinstance(data.get("title"), str):
        return None
    return data


def read_tickets(repo, spec_number):
    raw = run_gh_read(
        [
            "api",
            "--paginate",
            f"repos/{repo}/issues/{spec_number}/sub_issues",
        ]
    )
    items = parse_json_array_stream(raw)
    if items is None:
        return None
    tickets = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("number"), int):
            return None
        tickets.append(item)
    tickets.sort(key=lambda item: item["number"])
    return tickets


def read_merged_prs(repo):
    raw = run_gh_read(
        [
            "pr",
            "list",
            "-R",
            repo,
            "--state",
            "merged",
            "--limit",
            "200",
            "--json",
            "number,title,url,mergedAt,closingIssuesReferences",
        ]
    )
    items = parse_json_array_stream(raw)
    if items is None:
        return None
    prs = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("number"), int):
            return None
        prs.append(item)
    return prs


def pr_closes_ticket(pr, ticket_numbers, repo):
    refs = pr.get("closingIssuesReferences")
    if not isinstance(refs, list):
        return False
    expected_repo = repo.lower()
    for ref in refs:
        if not isinstance(ref, dict):
            continue
        if ref.get("number") not in ticket_numbers:
            continue
        repo_info = ref.get("repository")
        if isinstance(repo_info, dict):
            owner = repo_info.get("owner")
            owner_login = owner.get("login") if isinstance(owner, dict) else None
            name = repo_info.get("name")
            if isinstance(owner_login, str) and isinstance(name, str):
                if f"{owner_login}/{name}".lower() != expected_repo:
                    continue
        return True
    return False


def build_report(repo, spec_number, first_prompt_arg=None):
    spec = read_spec(repo, spec_number)
    tickets = read_tickets(repo, spec_number)
    all_merged_prs = read_merged_prs(repo)

    if spec is not None:
        url = spec.get("url")
        if isinstance(url, str) and url:
            spec_line = f"#{spec['number']} {spec['title']} ({url})"
        else:
            spec_line = f"#{spec['number']} {spec['title']}"
    else:
        spec_line = "unknown"

    if tickets is not None:
        ticket_numbers = {t["number"] for t in tickets}
        tickets_line = ", ".join(f"#{t['number']}" for t in tickets) if tickets else "none"
    else:
        ticket_numbers = None
        tickets_line = "unknown"

    matching_prs = None
    if tickets is not None and all_merged_prs is not None:
        matching_prs = [
            pr for pr in all_merged_prs if pr_closes_ticket(pr, ticket_numbers, repo)
        ]
        matching_prs.sort(key=lambda pr: pr["number"])
        merged_prs_line = (
            ", ".join(f"#{pr['number']}" for pr in matching_prs)
            if matching_prs
            else "none"
        )
    else:
        merged_prs_line = "unknown"

    first_prompt_dt = None
    if first_prompt_arg is not None:
        first_prompt_dt = parse_utc(first_prompt_arg)
    elif spec is not None:
        first_prompt_dt = parse_utc(spec.get("createdAt"))

    first_prompt_line = format_utc(first_prompt_dt) if first_prompt_dt else "unknown"

    last_merge_dt = None
    if matching_prs:
        parsed_merges = [parse_utc(pr.get("mergedAt")) for pr in matching_prs]
        if all(dt is not None for dt in parsed_merges):
            last_merge_dt = max(parsed_merges)

    last_merge_line = format_utc(last_merge_dt) if last_merge_dt else "unknown"

    if first_prompt_dt is not None and last_merge_dt is not None:
        delta = (last_merge_dt - first_prompt_dt).total_seconds()
        elapsed_line = format_elapsed(delta) if delta >= 0 else "unknown"
    else:
        elapsed_line = "unknown"

    report = {
        "spec": spec_line,
        "tickets": tickets_line,
        "merged_prs": merged_prs_line,
        "first_prompt": first_prompt_line,
        "last_merge": last_merge_line,
        "elapsed": elapsed_line,
    }
    return report


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Print read-only launch video caption data for a demo repository."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repository in owner/name form.",
    )
    parser.add_argument(
        "--spec",
        required=True,
        type=int,
        help="Spec issue number in the demo repository.",
    )
    parser.add_argument(
        "--first-prompt",
        default=None,
        help="UTC timestamp (YYYY-MM-DDTHH:MM:SSZ) of the first prompt. Defaults to spec createdAt.",
    )
    args = parser.parse_args(argv)
    if not REPO_RE.fullmatch(args.repo):
        parser.error("invalid --repo value; expected owner/name")
    if args.spec <= 0:
        parser.error("--spec must be a positive integer")
    return args


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    report = build_report(args.repo, args.spec, first_prompt_arg=args.first_prompt)
    for key in ("spec", "tickets", "merged_prs", "first_prompt", "last_merge", "elapsed"):
        print(f"{key}: {report[key]}")
    if any(value == "unknown" for value in report.values()):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
