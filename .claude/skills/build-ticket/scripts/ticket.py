#!/usr/bin/env python3
"""build-ticket's lookups and records. Python 3.11+ standard library, `gh`, `git`.

  ticket.py read REPO N                     owned paths, links, blockers, fleet start, readiness
  ticket.py scope REPO N [--base REF] [--supporting PATH]... [--owned PATH]...
                                            every changed path: owned, supporting or OUT
  ticket.py records REPO N [--ticket] [--comment ID] [--fleet-ref REF]
                                            trusted verdict, bound decision and fleet record on pull
                                            request N, or with --ticket the fleet record on ticket N;
                                            --comment checks that one named comment on N is trusted
  ticket.py author                          set git's author to the GitHub user's noreply
  ticket.py push RECEIPT -- PUSH-COMMAND... run the push; keep the first success's receipt
  ticket.py post-receipt REPO PR RECEIPT    post the receipt once as a record author, read back

Exit 0 done, 1 refused (the last line says why), 2 an input it cannot read.
It prints a short result, never a log, and writes only what its command names.
Record authors come only from the `## GitHub identity` table of docs/agents/fleet.md
at the fleet ref (default origin/main); without one valid row it trusts nobody.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

LOGIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})(?:\[bot\])?')
REPO_NAME = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
VERDICT = re.compile(r'VERDICT: (APPROVE|CHANGES) at ([0-9a-f]{40})')
FINDINGS = r'R\d+(?:(?:, R\d+)* and R\d+)?'
DECISION = re.compile(r'\*\*Orchestrator decision:\*\* (?:(fix once more)|(log and merge)): '
                      rf'({FINDINGS}) at ([0-9a-f]{{40}})\. '
                      r'(?(2)Polish issues: #\d+(?:, #\d+)*\. )Why: \S.*')
PARK = re.compile(rf'Next: park ({FINDINGS}) as a decision for Jake\.')
START = re.compile(r'launch-fleet: (?:started|start checked)\b')
POST_TIMEOUT = 30


class Unreadable(Exception):
    pass


def run(argv, what, timeout=120):
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise Unreadable(f'cannot read {what}')
    if r.returncode:
        raise Unreadable(f'cannot read {what}')
    return r.stdout


def gh_json(argv, what):
    try:
        return json.loads(run(['gh', *argv], what))
    except ValueError:
        raise Unreadable(f'cannot read {what}: not JSON')


def section(text, heading):
    lines, inside = [], False
    for line in text.splitlines():
        if line.startswith('## '):
            inside = line[3:].strip().lower() == heading
            continue
        if inside:
            lines.append(line)
    return lines


def owned_bullets(body, ticket_repo):
    """[{'text', 'paths': [(path, repo)], 'annotated', 'note'}] for each `## Owned paths` bullet.

    A path is bound to the bullet's `in `owner/repo`` qualifier, else to the ticket's
    repository. A bullet with words besides its paths, qualifiers and one note is
    annotated: its paths are listed, and their conditions stay with the builder.
    """
    out = []
    for line in section(body, 'owned paths'):
        if not line.startswith('- '):
            continue
        text = line[2:].strip()
        tokens = list(re.finditer(r'`([^`]*)`', text))
        repos = {m.group(1).lower() for m in tokens
                 if REPO_NAME.fullmatch(m.group(1)) and text[:m.start()].endswith('in ')}
        paths = [m.group(1) for m in tokens
                 if m.group(1).lower() not in repos and m.group(1).strip() == m.group(1)
                 and m.group(1) and ' ' not in m.group(1) and not m.group(1).startswith('/')
                 and '..' not in m.group(1).split('/') and '<' not in m.group(1)]
        if len(repos) > 1:
            paths = []
        repo = next(iter(repos)) if repos else ticket_repo.lower()
        rest = re.sub(r'`[^`]*`', '', text)
        notes = re.findall(r'\([^()]*\)', rest)
        rest = re.sub(r'\([^()]*\)', '', rest)
        plain = not re.sub(r'\b(in|and)\b|[,\s]', '', rest)
        out.append({'text': text, 'paths': [(p, repo) for p in paths],
                    'annotated': bool(paths) and not plain,
                    'note': notes[0] if plain and len(paths) == 1 and len(notes) == 1 else ''})
    return out


def ticket(repo, n):
    data = gh_json(['issue', 'view', str(n), '--repo', repo, '--json',
                    'number,title,state,labels,body,blockedBy,blocking,parent'], f'ticket #{n}')
    if not isinstance(data, dict) or not isinstance(data.get('body'), str):
        raise Unreadable(f'cannot read ticket #{n}: unexpected shape')
    return data


def links(data, key):
    value = data.get(key)
    nodes = value.get('nodes') if isinstance(value, dict) else None
    if (not isinstance(nodes, list) or not all(isinstance(x, dict) for x in nodes)
            or value.get('totalCount') != len(nodes)):
        raise Unreadable(f'cannot read ticket links: incomplete blocker data in {key}')
    return nodes


def blocker_reason(node):
    m = re.match(r'https://github\.com/([^/]+/[^/]+)/issues/\d+$', str(node.get('url', '')))
    if not m:
        raise Unreadable(f'cannot read blocker #{node.get("number")}: no repository')
    data = gh_json(['issue', 'view', str(node['number']), '--repo', m.group(1), '--json',
                    'state,stateReason'], f'blocker #{node["number"]}')
    return data.get('state'), data.get('stateReason')


def record_authors(ref):
    text = run(['git', 'show', f'{ref}:docs/agents/fleet.md'], f'docs/agents/fleet.md at {ref}')
    rows = [l for l in section(text, 'github identity') if re.match(r'\|\s*Record authors\s*\|', l)]
    if len(rows) != 1:
        raise Unreadable('no single Record authors row in the GitHub identity table: trust nobody')
    cell = rows[0].split('|')[2].strip()
    logins = [x.strip() for x in cell.split(',')] if cell else []
    names = [x[1:-1] if len(x) > 1 and x[0] == x[-1] == '`' else '' for x in logins]
    if not names or not all(LOGIN.fullmatch(x) for x in names):
        raise Unreadable('malformed Record authors row: trust nobody')
    return [x.lower() for x in names]


def comments(repo, number):
    pages = gh_json(['api', '--paginate', '--slurp', f'repos/{repo}/issues/{number}/comments'],
                    f'comments on #{number}')
    if not isinstance(pages, list) or not all(isinstance(p, list) for p in pages):
        raise Unreadable(f'cannot read comments on #{number}: unexpected shape')
    return [c for page in pages for c in page if isinstance(c, dict)]


def author_of(comment):
    user = comment.get('user')
    login = user.get('login') if isinstance(user, dict) else None
    return login.lower() if isinstance(login, str) else None


def first_line(comment):
    return next((l.strip() for l in str(comment.get('body', '')).splitlines() if l.strip()), '')


def cmd_read(repo, n, ref):
    t = ticket(repo, n)
    blockers, blocking = links(t, 'blockedBy'), links(t, 'blocking')
    labels = sorted(l.get('name', '') for l in t.get('labels', []))
    print(f'ticket #{t["number"]}: {t["title"]}')
    print(f'state: {t["state"]}; labels: {", ".join(labels) or "none"}')
    parent = t.get('parent') or {}
    print(f'spec: #{parent["number"]}' if parent.get('number') else 'spec: none')
    bullets = owned_bullets(t['body'], repo)
    for b in bullets:
        if not b['paths']:
            print(f'owned, not a path: {b["text"]}')
        for path, prepo in b['paths']:
            if b['annotated']:
                print(f'owned, check the bullet: {path} in {prepo}')
            else:
                print(f'owned: {path} in {prepo}' + (f' {b["note"]}' if b['note'] else ''))
        if b['annotated']:
            print(f'bullet: {b["text"]}')
    for line in t['body'].splitlines():
        if line.startswith('**Relies on:**'):
            print('relies on: ' + line[len('**Relies on:**'):].strip())
    reasons = {}
    for b in blockers:
        reasons[b.get('number')] = blocker_reason(b) if b.get('state') == 'CLOSED' else (b.get('state'), None)
        print(f'blocked by: #{b.get("number")} {" ".join(x for x in reasons[b.get("number")] if x)}')
    for b in blocking:
        print(f'blocks: #{b.get("number")} {b.get("state")}')
    authors = record_authors(ref)
    starts = [c for c in comments(repo, n) if author_of(c) in authors and START.match(first_line(c))]
    if starts:
        print(f'start: comment {starts[-1].get("id")} by {author_of(starts[-1])}: {first_line(starts[-1])}')
    open_blockers = [b for b in blockers if reasons[b.get('number')][0] != 'CLOSED']
    unfinished = [b for b in blockers if reasons[b.get('number')][0] == 'CLOSED'
                  and reasons[b.get('number')][1] != 'COMPLETED']
    if t['state'] != 'OPEN':
        why = f'the ticket is {t["state"]}'
    elif 'ready-for-agent' not in labels:
        why = 'no ready-for-agent label'
    elif 'needs-info' in labels:
        why = 'needs-info is open'
    elif open_blockers:
        why = ', '.join(f'#{b.get("number")}' for b in open_blockers) + ' is open'
    elif unfinished:
        b = unfinished[0]
        why = f'#{b.get("number")} was closed as {reasons[b.get("number")][1] or "unknown"}'
    elif not any(b['paths'] for b in bullets):
        why = 'no owned paths'
    elif not starts:
        why = 'no launch-fleet start record from a record author'
    else:
        print('ready: yes')
        return 0
    print(f'ready: no: {why}')
    return 1


def covers(rule, path):
    return path.startswith(rule) if rule.endswith('/') else path == rule


def changed(base):
    run(['git', 'rev-parse', '--verify', '--quiet', base + '^{commit}'], f'base {base}')
    paths = set()
    fields = run(['git', 'diff', '--name-status', '-z', '--find-renames', f'{base}...HEAD'],
                 'the diff').split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        count = 2 if fields[i][:1] in ('R', 'C') else 1
        paths.update(fields[i + 1:i + 1 + count])
        i += 1 + count
    fields = run(['git', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
                 'git status').split('\0')
    i = 0
    while i < len(fields) and fields[i]:
        entry = fields[i]
        paths.add(entry[3:])
        if entry[:1] in ('R', 'C') or entry[1:2] in ('R', 'C'):
            i += 1
            paths.add(fields[i])
        i += 1
    return sorted(p for p in paths if p)


def cmd_scope(repo, n, base, supporting, by_hand):
    here = gh_json(['repo', 'view', '--json', 'nameWithOwner'], 'the checkout repository')
    here = here.get('nameWithOwner', '') if isinstance(here, dict) else ''
    if not REPO_NAME.fullmatch(here):
        raise Unreadable('cannot read the checkout repository')
    here = here.lower()
    bullets = owned_bullets(ticket(repo, n)['body'], repo)
    plain = [p for b in bullets if not b['annotated'] for p, r in b['paths'] if r == here]
    annotated = [p for b in bullets if b['annotated'] for p, r in b['paths'] if r == here]
    if by_hand and not any(b['annotated'] and any(r == here for _, r in b['paths']) for b in bullets):
        raise Unreadable('--owned: no annotated owned bullet for this repository: ask first')
    outside = 0
    for path in changed(base):
        if any(covers(rule, path) for rule in plain):
            print(f'owned: {path}')
        elif any(covers(rule, path) for rule in annotated):
            print(f'owned, check the bullet: {path}')
        elif any(covers(rule, path) for rule in by_hand):
            print(f'owned, resolved by hand: {path}')
        elif any(covers(rule, path) for rule in supporting):
            print(f'supporting: {path}')
        else:
            print(f'OUT: {path}')
            outside += 1
    if outside:
        print(f'scope: {outside} path(s) outside the owned paths: ask first')
        return 1
    print('scope: ok')
    return 0


def ids(text):
    found = re.findall(r'R\d+', text)
    return set(found) if len(found) == len(set(found)) else None


def last_line(comment):
    return next((l.strip() for l in reversed(str(comment.get('body', '')).splitlines()) if l.strip()), '')


def binding(c, at, verdict, head):
    """Why decision `c` (index `at` among trusted comments) does not bind, or None if it does.

    It binds only after the newest trusted verdict, when that verdict's terminal line parks
    findings at the current head and the decision's complete line names exactly them there.
    """
    m = DECISION.fullmatch(first_line(c))
    if not m or ids(m.group(3)) is None:
        return 'not a decision line'
    if verdict is None or at < verdict[0]:
        return 'it precedes the newest verdict'
    park = PARK.fullmatch(last_line(verdict[1]))
    if not park or ids(park.group(1)) is None:
        return 'the newest verdict parks nothing'
    if m.group(4) != head:
        return f'{m.group(4)} is not the current head'
    if verdict[2] != head:
        return f'the park report is at {verdict[2]}, not the current head'
    parked, named = ids(park.group(1)), ids(m.group(3))
    if named - parked:
        return f'{", ".join(sorted(named - parked))} was not parked at {head}'
    if parked - named:
        return f'{", ".join(sorted(parked - named))} parked at {head} is not named'
    return None


def cmd_records(repo, n, ref, on_ticket, named):
    authors = record_authors(ref)
    items = comments(repo, n)
    trusted = [c for c in items if author_of(c) in authors]
    print('authors: ' + ', '.join(authors))
    if named is not None:
        c = next((c for c in items if str(c.get('id')) == named), None)
        if c is None:
            print(f'comment {named}, trusted: no: not on #{n}')
            return 1
        line = f'comment {named} by {author_of(c)}: {first_line(c)}, trusted: '
        print(line + ('yes' if c in trusted else 'no: not a record author'))
        return 0 if c in trusted else 1
    fleet = [c for c in trusted if first_line(c).startswith('launch-fleet:')]
    c = fleet[-1] if fleet else None
    print(f'launch-fleet: comment {c.get("id")} by {author_of(c)}: {first_line(c)}' if c
          else 'launch-fleet: none')
    if on_ticket:
        print(f'ignored: {len(items) - len(trusted)} comment(s) not by a record author')
        return 0
    pr = gh_json(['api', f'repos/{repo}/pulls/{n}'], f'pull request #{n}')
    head = (pr.get('head') or {}).get('sha') if isinstance(pr, dict) else None
    if not isinstance(head, str) or not re.fullmatch(r'[0-9a-f]{40}', head):
        raise Unreadable(f'cannot read the head of pull request #{n}')
    verdicts = [(i, c, VERDICT.fullmatch(first_line(c))) for i, c in enumerate(trusted)]
    verdicts = [(i, c, m) for i, c, m in verdicts if m]
    verdict = None
    if verdicts:
        i, c, m = verdicts[-1]
        verdict = (i, c, m.group(2))
        current = 'yes' if m.group(2) == head else f'no ({head})'
        print(f'verdict: comment {c.get("id")} by {author_of(c)}: {m.group(1)} at {m.group(2)}, '
              f'current head: {current}')
        nxt = last_line(c)
        print('next: ' + (nxt if nxt.startswith('Next:') else 'none'))
    else:
        print('verdict: none')
    decisions = [(i, c) for i, c in enumerate(trusted)
                 if first_line(c).startswith('**Orchestrator decision:**')]
    if decisions:
        reasons = [(c, binding(c, i, verdict, head)) for i, c in decisions]
        c, why = next(((c, why) for c, why in reversed(reasons) if why is None), reasons[-1])
        m = DECISION.fullmatch(first_line(c))
        summary = f'{m.group(1) or m.group(2)} {m.group(3)} at {m.group(4)}' if m else first_line(c)
        print(f'decision: comment {c.get("id")} by {author_of(c)}: {summary}, '
              f'bound: {"yes" if why is None else "no: " + why}')
    else:
        print('decision: none')
    print(f'ignored: {len(items) - len(trusted)} comment(s) not by a record author')
    return 0


def cmd_author():
    user = gh_json(['api', 'user'], 'the GitHub user')
    login, uid = user.get('login'), user.get('id')
    if not (isinstance(login, str) and LOGIN.fullmatch(login) and isinstance(uid, int)):
        raise Unreadable('cannot read the GitHub user: unexpected shape')
    email = f'{uid}+{login}@users.noreply.github.com'
    run(['git', 'config', 'user.name', login], 'git config')
    run(['git', 'config', 'user.email', email], 'git config')
    print(f'author: {login} <{email}>')
    return 0


def outside_checkout(path):
    top = Path(run(['git', 'rev-parse', '--show-toplevel'], 'the checkout').strip()).resolve()
    target = Path(path)
    if not target.is_absolute():
        raise Unreadable('the receipt needs an absolute path outside the checkout')
    resolved = target.parent.resolve() / target.name
    if resolved == top or top in resolved.parents:
        raise Unreadable('the receipt needs an absolute path outside the checkout')
    return target


def earlier_push(branch):
    """True when origin's branch already holds work not on origin/main, None if unknown."""
    try:
        out = run(['git', 'ls-remote', 'origin', f'refs/heads/{branch}'], 'the remote branch')
    except Unreadable:
        return None
    sha = out.split()[0] if out.split() else None
    if sha is None:
        return False
    known = subprocess.run(['git', 'cat-file', '-e', f'{sha}^{{commit}}'], capture_output=True)
    if known.returncode:
        return True
    base = subprocess.run(['git', 'merge-base', '--is-ancestor', sha, 'origin/main'], capture_output=True)
    return base.returncode == 1 if base.returncode in (0, 1) else None


def cmd_push(receipt, command):
    target = outside_checkout(receipt)
    if not command:
        raise Unreadable('no push command after --')
    branch = run(['git', 'symbolic-ref', '--short', 'HEAD'], 'the current branch').strip()
    earlier = None if target.exists() else earlier_push(branch)
    if subprocess.run(command).returncode:
        print('push failed: no receipt')
        return 1
    if target.exists():
        print(f'receipt kept: {target.read_text(encoding="utf-8").strip()}')
        return 0
    if earlier is not False:
        why = f'an earlier push to {branch} has no receipt' if earlier else \
            f'cannot tell whether {branch} was pushed before'
        print(f'receipt unknown: {why}; record none')
        return 0
    at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    head = run(['git', 'rev-parse', 'HEAD'], 'HEAD').strip()
    line = f'First successful push: {head} at {at}\n'
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, 'x', encoding='utf-8') as f:
        f.write(line)
    print('receipt saved: ' + line.strip())
    return 0


def cmd_post_receipt(repo, pr, receipt, ref):
    try:
        body = Path(receipt).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        raise Unreadable('cannot read the receipt file')
    if not re.fullmatch(r'First successful push: [0-9a-f]{40} at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\n', body):
        raise Unreadable('the receipt file is not one receipt line')
    authors = record_authors(ref)

    def existing():
        return next((c for c in comments(repo, pr)
                     if c.get('body') == body and author_of(c) in authors), None)

    found = existing()
    if found:
        print(f'receipt reused: comment {found.get("id")}')
        return 0
    try:
        subprocess.run(['gh', 'api', '--method', 'POST', f'repos/{repo}/issues/{pr}/comments',
                        '-f', 'body=' + body], capture_output=True, timeout=POST_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        found = existing()
    except Unreadable:
        print('receipt unknown: read the pull request before posting again')
        return 1
    if found:
        print(f'receipt posted: comment {found.get("id")}')
        return 0
    print('receipt not posted: no copy by a record author; keep the file and run post-receipt again')
    return 1


def main(argv):
    try:
        args, flags = [], {'--base': [], '--supporting': [], '--owned': [], '--fleet-ref': [],
                           '--comment': []}
        ticket_mode, rest = False, list(argv)
        if '--' in rest:
            rest, command = rest[:rest.index('--')], rest[rest.index('--') + 1:]
        else:
            command = None
        while rest:
            item = rest.pop(0)
            if item == '--ticket':
                ticket_mode = True
            elif item in flags and rest:
                flags[item].append(rest.pop(0))
            elif item.startswith('--'):
                raise ValueError
            else:
                args.append(item)
        ref = flags['--fleet-ref'][-1] if flags['--fleet-ref'] else 'origin/main'
        name = args[:1]
        if command is not None and name != ['push']:
            raise ValueError
        if name == ['read'] and len(args) == 3 and not ticket_mode:
            return cmd_read(args[1], int(args[2]), ref)
        if name == ['scope'] and len(args) == 3 and not ticket_mode and len(flags['--base']) <= 1:
            base = flags['--base'][0] if flags['--base'] else 'origin/main'
            return cmd_scope(args[1], int(args[2]), base, flags['--supporting'], flags['--owned'])
        if name == ['records'] and len(args) == 3 and len(flags['--comment']) <= 1:
            named = flags['--comment'][0] if flags['--comment'] else None
            if named is not None and not named.isdigit():
                raise ValueError
            return cmd_records(args[1], int(args[2]), ref, ticket_mode, named)
        if name == ['author'] and len(args) == 1:
            return cmd_author()
        if name == ['push'] and len(args) == 2 and command:
            return cmd_push(args[1], command)
        if name == ['post-receipt'] and len(args) == 4:
            return cmd_post_receipt(args[1], int(args[2]), args[3], ref)
        raise ValueError
    except ValueError:
        print(__doc__.split('\n\n')[1], file=sys.stderr)
        return 2
    except Unreadable as e:
        print(f'ticket.py: {e}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
