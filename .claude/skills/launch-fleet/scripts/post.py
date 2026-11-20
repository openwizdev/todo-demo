#!/usr/bin/env python3
"""Write one public fleet record on GitHub and read it back (WS8, #1181).

  post.py comment OWNER/NAME NUMBER BODY   a new comment on an issue or pull request
  post.py edit OWNER/NAME COMMENT_ID BODY  an edit of a record author's comment

Prints one line and exits 0 on `posted <id>` or `edited <id>`. Exits 1 with
`refused: <why>` and no write when the body is not a fleet record (its first
line starts `launch-fleet: ` or `**Needs you:**`), carries a private identity
(a thread or loop id, a token), or the project's Record authors row is
missing; with `unknown: <why>` when the write returned no receipt or
read-back cannot confirm it. A record counts as posted only by its returned
id, never by an identical new comment, which another wake may have written
(#1555). An unknown write may have happened: reconcile the thread before any
retry.
"""
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_grants', HERE / 'grants.py')
grants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(grants)

REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
PRIVATE = re.compile(r'\b(?:thr|loop)_[A-Za-z0-9]|\b(?:gh[opsur]_|github_pat_)[A-Za-z0-9_]')
FIRST = ('launch-fleet: ', '**Needs you:**')


class Stop(Exception):
    """A short outcome line: `refused: ...` or `unknown: ...`."""


def gh(*args):
    try:
        r = subprocess.run(['gh', *args], capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def read_json(*args):
    text = gh(*args)
    try:
        return None if text is None else json.loads(text)
    except ValueError:
        return None


def authors(repo):
    """The Record authors row, read whole from the default branch; refused when missing or malformed."""
    text = gh('api', f'repos/{repo}/contents/docs/agents/fleet.md', '-H', 'Accept: application/vnd.github.raw+json')
    try:
        return grants.record_authors(text or '')
    except ValueError:
        raise Stop('refused: docs/agents/fleet.md names no record authors, so no record can be read back')


def check(body):
    first = next((line for line in body.splitlines() if line.strip()), '')
    if not first.startswith(FIRST):
        raise Stop("refused: not a fleet record (its first line starts 'launch-fleet: ' or '**Needs you:**')")
    if PRIVATE.search(body):
        raise Stop('refused: the body carries a private identity; name the public ticket, pull request or commit')


def ours(item, auth):
    return isinstance(item, dict) and grants.authored((item.get('user') or {}).get('login'), auth)


def thread(repo, number):
    pages = read_json('api', '--paginate', '--slurp', f'repos/{repo}/issues/{number}/comments?per_page=100')
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        return None
    return [c for p in pages for c in p]


def comment(repo, number, body):
    check(body)
    auth = authors(repo)
    before = thread(repo, number)
    if before is None:
        raise Stop(f'unknown: #{number} could not be read before writing; nothing was written')
    seen = {c.get('id') for c in before}
    made = read_json('api', '--method', 'POST', f'repos/{repo}/issues/{number}/comments', '-f', f'body={body}')
    if not isinstance(made, dict) or type(made.get('id')) is not int:
        # Without a receipt nothing ties a new identical record to this write:
        # another wake may have posted it under the same login (#1555).
        raise Stop(f'unknown: the write on #{number} returned no receipt, so no record is adopted; '
                   f'reconcile #{number} before any retry')
    after = thread(repo, number) or []
    found = [c for c in after if c.get('id') == made['id'] and c.get('id') not in seen
             and c.get('body') == body and ours(c, auth)]
    if len(found) != 1:
        raise Stop(f'unknown: the record on #{number} could not be read back; read #{number} before any retry')
    return f"posted {found[0]['id']}"


def edit(repo, comment_id, body):
    check(body)
    auth = authors(repo)
    path = f'repos/{repo}/issues/comments/{comment_id}'
    current = read_json('api', path)
    if not isinstance(current, dict):
        raise Stop(f'unknown: comment {comment_id} could not be read; nothing was written')
    if not ours(current, auth):
        raise Stop(f'refused: comment {comment_id} is not a record author\'s')
    gh('api', '--method', 'PATCH', path, '-f', f'body={body}')
    back = read_json('api', path)
    if not (ours(back, auth) and back.get('body') == body):
        raise Stop(f'unknown: comment {comment_id} does not read back as the edit; read it before any retry')
    return f'edited {comment_id}'


def main(argv):
    if len(argv) != 4 or argv[0] not in ('comment', 'edit') or not REPO.fullmatch(argv[1]) \
            or not re.fullmatch(r'[1-9][0-9]{0,11}', argv[2]):
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    try:
        print((comment if argv[0] == 'comment' else edit)(argv[1], int(argv[2]), argv[3]))
    except Stop as outcome:
        print(outcome)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
