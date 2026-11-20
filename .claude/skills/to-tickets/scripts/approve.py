"""The machine plan approval (#1339, J202): check a plan graph and print its record.

    python3 -I approve.py --graph graph.json --revision revision.txt --grill <url>
        --number <N> [--changed <what changed>] [--date YYYY-MM-DD] [--root DIR]

graph.json is check-links.sh's graph read (`--read <spec>`); revision.txt is
revision.sh's text for the same spec. The checks, all of them every time:

  links        check-links.sh passes on the graph read
  relies       check-relies.sh passes on each open agent ticket's body, a path
               counting as planned when a direct blocker owns that file, or a
               folder or pattern containing it, in the ticket's own repository
               (the one all its owned paths name); --root is the checkout of
               the graph's repository, so a ticket in any other repository
               must have each Relies on file planned
  sizes        each open ticket says exactly one `Size: S`, `M` or `L`
  width        no cycle, and no arrow another chain of arrows already implies;
               the record reports the critical chain (the longest run of
               open work along hard edges, open blockers outside the spec
               included) and the widest start wave; a context-only file
               link is no hard edge (soft_link)
  owned paths  each open agent ticket owns exact repository paths, and no two
               tickets that can run at once own the same path, unless both
               bullets say `(shared`

Before any check, the revision text must name exactly the graph's tickets,
titles, blockers and bodies, so the fingerprint binds the plan checked.

Exit 0: every check passed; the record (decisions.v1, "Machine plan approval")
on stdout. 1: refused; nothing on stdout, one `approve: <check>: <why>` line per
failure on stderr. 2: bad arguments or an unreadable input. Writes nothing and
calls no network; it runs the two sibling checkers.
"""
import argparse
import datetime
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LINKS = HERE.parent / 'check-links.sh'
RELIES = HERE.parent / 'check-relies.sh'
GRILL = re.compile(r'https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*'
                   r'#issuecomment-[1-9][0-9]*')
REPO = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
TICKET_LINE = re.compile(r'ticket #([1-9][0-9]*) blocked-by (none|#[1-9][0-9]*(?: #[1-9][0-9]*)*) '
                         r'body sha256 ([0-9a-f]{64}) title (.+)')
TICKED = (re.compile(rb'^([ \t]*[-*+][ \t]+)\[[xX]\]$'), re.compile(rb'^([ \t]*[-*+][ \t]+)\[[xX]\]([ \t\r])'))


class Unreadable(Exception):
    """Exit 2: the input can't be read as asked."""


def unticked_sha256(text):
    """revision.sh's body hash: the body as `gh --jq .body` prints it (with one
    newline added), each ticked task box read as unticked."""
    lines = (text + '\n').encode().split(b'\n')
    out = []
    for line in lines:
        line = TICKED[0].sub(rb'\1[ ]', line)
        line = TICKED[1].sub(rb'\1[ ]\2', line)
        out.append(line)
    return hashlib.sha256(b'\n'.join(out)).hexdigest()


def section(body, heading):
    """The lines under `## <heading>` up to the next `## `, or None."""
    lines = body.split('\n')
    for i, line in enumerate(lines):
        if line.rstrip() == '## ' + heading:
            rest = []
            for after in lines[i + 1:]:
                if after.startswith('## '):
                    break
                rest.append(after)
            return rest
    return None


def human(ticket):
    return section(ticket['body'], 'Done by') is not None


def owned(ticket, default_repo):
    """[(repo, path, shared)] for each bullet's paths; raises ValueError."""
    lines = section(ticket['body'], 'Owned paths')
    if lines is None:
        raise ValueError('no `## Owned paths` section')
    bullets = [line[2:] for line in lines if line.startswith('- ')]
    if not bullets:
        raise ValueError('no owned path bullet')
    out = []
    for bullet in bullets:
        repos = re.findall(r'\bin `([^`]+)`', bullet)
        repo = default_repo
        if repos:
            if len(repos) != 1 or not REPO.fullmatch(repos[0]):
                raise ValueError(f'unclear repository in "{bullet}"')
            repo = repos[0]
        paths = [p for p in re.findall(r'`([^`]+)`', bullet) if p not in repos]
        if not paths:
            raise ValueError(f'a bullet names no exact path: "{bullet}"')
        for path in paths:
            parts = path.rstrip('/').split('/')
            if path.startswith('/') or any(part in ('', '.', '..') for part in parts) or ' ' in path:
                raise ValueError(f'`{path}` is not a repository-relative path')
            out.append((repo.lower(), path, '(shared' in bullet))
    return out


def overlap(a, b):
    """Two owned paths cover a common file: one is a folder holding the other,
    or a pattern segment matches the other's segment."""
    x, y = a.rstrip('/').split('/'), b.rstrip('/').split('/')
    return all(fnmatch.fnmatchcase(p, q) or fnmatch.fnmatchcase(q, p) for p, q in zip(x, y))


def contains(own, path):
    """An owned path holds a file: it is that file, or a folder or pattern
    whose every segment matches the file's leading segments. A path ending in
    `/` is a folder: it holds only what lies strictly below it."""
    x, y = own.rstrip('/').split('/'), path.split('/')
    longest = len(y) - 1 if own.endswith('/') else len(y)
    return len(x) <= longest and all(fnmatch.fnmatchcase(q, p) for p, q in zip(x, y))


def relies_paths(body):
    lines = [line for line in body.split('\n') if line.startswith('**Relies on:**')]
    return re.findall(r'`([^`]+)`', lines[0]) if len(lines) == 1 else []


def read_revision(text, graph):
    """Refusals where the revision text doesn't name exactly the graph read."""
    lines = text.split('\n')
    if lines[-1:] != [''] or len(lines) < 3 or lines[0] != 'plan-graph revision v2':
        return ['not revision.sh version 2 text']
    spec = graph['source'].get('spec')
    if not re.fullmatch(rf'spec #{spec} body sha256 [0-9a-f]{{64}}', lines[1]):
        return [f'its spec line is not spec #{spec}\'s']
    named = {}
    for line in lines[2:-1]:
        m = TICKET_LINE.fullmatch(line)
        if not m or int(m[1]) in named:
            return [f'unreadable or repeated line: "{line[:60]}"']
        named[int(m[1])] = m
    tickets = {t['number']: t for t in graph['tickets']}
    why = []
    if sorted(named) != sorted(tickets):
        why.append('its tickets are not the graph\'s tickets')
    for n in sorted(set(named) & set(tickets)):
        m, t = named[n], tickets[n]
        blockers = ' '.join(f'#{b}' for b in sorted(b['number'] for b in t['blocked_by'])) or 'none'
        if m[2] != blockers:
            why.append(f'#{n}\'s blockers differ')
        if m[4] != t['title']:
            why.append(f'#{n}\'s title differs')
        if m[3] != unticked_sha256(t['body']):
            why.append(f'#{n}\'s body differs')
    return why


def check_links(graph_text):
    out = subprocess.run(['sh', str(LINKS), '--graph', '-'], input=graph_text,
                         capture_output=True, text=True)
    if out.returncode == 2:
        raise Unreadable('check-links.sh could not read the graph: ' + out.stderr.strip()[:200])
    if out.returncode != 0:
        return [line.strip() for line in out.stderr.splitlines() if line.strip()] or ['check-links.sh refused']
    return []


def check_relies(tickets, owners, root, root_repo):
    why = []
    for t in tickets:
        blockers = [b['number'] for b in t['blocked_by']]
        repos = {repo for repo, _, _ in owners.get(t['number'], [])}
        planned, unplanned = [], []
        for path in relies_paths(t['body']):
            if len(repos) == 1 and any(repo in repos and contains(own, path)
                                       for b in blockers for repo, own, _ in owners.get(b, [])):
                planned += ['--planned', path]
            else:
                unplanned.append(path)
        # Only the graph repository has a checkout here: any other ticket's
        # files are form-checked only, and each must be planned.
        in_root = repos == {root_repo}
        checked = planned if in_root else planned + [a for p in unplanned for a in ('--planned', p)]
        out = subprocess.run(['sh', str(RELIES), '--root', str(root), *checked], input=t['body'],
                             capture_output=True, text=True)
        if out.returncode != 0:
            why.append(f'#{t["number"]}: ' + (out.stderr.strip().splitlines() or ['refused'])[-1])
        elif unplanned and not in_root:
            where = f'`{next(iter(repos))}`' if len(repos) == 1 else 'more than one repository'
            why.append(f'#{t["number"]}: Relies on: `{unplanned[0]}` is in {where}, which --root is not; '
                       'a direct blocker there must own it')
    return why


def check_sizes(tickets):
    why, counts = [], {'S': 0, 'M': 0, 'L': 0}
    for t in tickets:
        sizes = re.findall(r'\bSize: ([A-Za-z]+)\b', t['body'])
        if len(sizes) != 1 or sizes[0] not in counts:
            why.append(f'#{t["number"]} needs exactly one `Size: S`, `M` or `L`')
        else:
            counts[sizes[0]] += 1
    return why, counts


def chain_width(after, planned, done):
    """The critical chain, the widest start wave (both in tickets) and the
    tickets a cycle leaves unreached. `after` maps every ticket (planned and
    outside blockers) to the tickets it blocks. The chain is the longest run
    of arrows through work not yet done, outside blockers included; the waves
    count planned work only."""
    level, indegree = {}, {n: 0 for n in after}
    for n in after:
        for m in after[n]:
            indegree[m] += 1
    ready = sorted(n for n in after if indegree[n] == 0)
    for n in ready:
        level[n] = 0 if n in done else 1
    while ready:
        n = ready.pop(0)
        for m in sorted(after[n]):
            level[m] = max(level.get(m, 0), level[n] + (0 if m in done else 1))
            indegree[m] -= 1
            if indegree[m] == 0:
                ready.append(m)
    unreached = sorted(n for n in after if indegree[n] > 0)
    waves = {}
    for n in planned:
        if n not in done and n in level:
            waves[level[n]] = waves.get(level[n], 0) + 1
    return max(level.values(), default=0), max(waves.values(), default=0), unreached


FILE_PATH = re.compile(r'(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+/?')


def file_link_files(body, blocker):
    """The files of the ticket's one `file` line for this blocker, or None."""
    lines = [line.rstrip(' \t') for line in section(body, 'Links') or []]
    found = [line for line in lines if re.match(rf'- #{blocker} (real|file):', line)]
    if len(found) != 1 or not found[0].startswith(f'- #{blocker} file:'):
        return None
    files = [p for p in re.findall(r'`([^`]*)`', found[0])
             if FILE_PATH.fullmatch(p) and not any(part in ('.', '..') for part in p.rstrip('/').split('/'))]
    return files or None


def soft_link(ticket, blocker, default_repo):
    """F6 (#1353): a link adds no serial work only when it is a file link
    naming a file, into an open agent ticket, from a planned blocker whose
    owned paths are read, and neither the blocker's owned paths nor the
    link's files hold an input the ticket relies on, nor do the two
    tickets' owned paths collide. Anything else is a hard edge."""
    if ticket['state'] != 'OPEN' or human(ticket) or blocker is None or human(blocker):
        return False
    files = file_link_files(ticket['body'], blocker['number'])
    try:
        mine, theirs = owned(ticket, default_repo), owned(blocker, default_repo)
    except ValueError:
        return False
    if files is None:
        return False
    inputs = relies_paths(ticket['body'])
    if any(overlap(i, p) for i in inputs for p in files + [path for _, path, _ in theirs]):
        return False
    return not any(ra == rb and overlap(pa, pb) and not (sa and sb)
                   for ra, pa, sa in mine for rb, pb, sb in theirs)


def check_width(graph):
    """Refusals, the critical chain and the widest start wave, in tickets.
    The cycle and implied-arrow checks read every native arrow; the chain
    and the waves read only hard edges (soft_link)."""
    numbers = {t['number'] for t in graph['tickets']}
    tickets = {t['number']: t for t in graph['tickets']}
    after = {n: set() for n in numbers}  # n -> tickets it blocks
    hard = {n: set() for n in numbers}
    done = {t['number'] for t in graph['tickets'] if t['state'] != 'OPEN'}
    for t in graph['tickets']:
        for b in t['blocked_by']:
            after.setdefault(b['number'], set()).add(t['number'])
            hard.setdefault(b['number'], set())
            if not soft_link(t, tickets.get(b['number']), graph['repo']):
                hard[b['number']].add(t['number'])
            if b['number'] not in numbers and b['state'] != 'OPEN':
                done.add(b['number'])
    _, _, unreached = chain_width(after, numbers, done)
    chain, widest, _ = chain_width(hard, numbers, done)
    if unreached:
        return [f'a cycle: {" ".join(f"#{n}" for n in unreached)} can never start'], 0, 0
    why = []

    def reaches(start, goal, skip):
        stack, seen = [m for m in after[start] if m != skip], set()
        while stack:
            n = stack.pop()
            if n == goal:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(after[n])
        return False

    for b in sorted(numbers):
        for t in sorted(after[b]):
            if reaches(b, t, skip=t):
                why.append(f'the arrow #{b} -> #{t} is implied by another chain; drop it')
    return why, chain, widest


def check_owned(graph, agents):
    """Refusals and every open agent ticket's paths."""
    why, owners = [], {}
    for t in agents:
        try:
            owners[t['number']] = owned(t, graph['repo'])
        except ValueError as e:
            why.append(f'#{t["number"]}: {e}')
    before = {t['number']: {b['number'] for b in t['blocked_by']} for t in graph['tickets']}

    def ordered(a, b):
        stack, seen = list(before.get(b, ())), set()
        while stack:
            n = stack.pop()
            if n == a:
                return True
            if n not in seen:
                seen.add(n)
                stack.extend(before.get(n, ()))
        return False

    numbers = sorted(owners)
    for i, a in enumerate(numbers):
        for b in numbers[i + 1:]:
            if ordered(a, b) or ordered(b, a):
                continue
            for repo_a, path_a, shared_a in owners[a]:
                for repo_b, path_b, shared_b in owners[b]:
                    if repo_a == repo_b and overlap(path_a, path_b) and not (shared_a and shared_b):
                        why.append(f'#{a} and #{b} can run at once and both own `{path_a}` / `{path_b}`')
    return why, owners


def record(args, graph, revision, counts):
    links, relies, sizes, chain, widest, owned_count = counts
    rows = []
    for t in sorted(graph['tickets'], key=lambda t: t['number']):
        blockers = ' '.join(f'#{b}' for b in sorted(b['number'] for b in t['blocked_by'])) or 'none'
        label = 'none' if t['state'] != 'OPEN' else 'ready-for-human' if human(t) else 'ready-for-agent'
        title = t['title'].replace('|', '\\|')
        rows.append(f'| #{t["number"]} | {title} | {blockers} | {label} |')
    fingerprint = hashlib.sha256(revision.encode()).hexdigest()
    parts = [
        f'**Machine plan approval, {args.date}, revision {args.number}:** '
        'links, relies, sizes, width and owned paths passed.',
        f'Grill confirmed: {args.grill}',
        '',
        f'Checks: {len(graph["tickets"])} tickets; links {links}; relies {relies}; '
        f'sizes S {sizes["S"]}, M {sizes["M"]}, L {sizes["L"]}; width: chain {chain}, widest {widest}; '
        f'owned paths {owned_count}.',
        '',
    ]
    if args.number > 1:
        parts += [f'Changed since revision {args.number - 1}: {args.changed.rstrip(".")}.', '']
    parts += ['| Ticket | Title | Blocked by | Label |', '| --- | --- | --- | --- |', *rows, '',
              f'Fingerprint: `{fingerprint}`', '',
              '<details><summary>Revision text</summary>', '', '```text']
    return '\n'.join(parts) + '\n' + revision + '```\n\n</details>\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--graph', type=Path, required=True)
    parser.add_argument('--revision', type=Path, required=True)
    parser.add_argument('--grill', required=True)
    parser.add_argument('--number', type=int, required=True)
    parser.add_argument('--changed')
    parser.add_argument('--date', default=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d'))
    parser.add_argument('--root', type=Path, default=Path('.'))
    args = parser.parse_args()
    if (not GRILL.fullmatch(args.grill) or args.number < 1 or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', args.date)
            or (args.number > 1) != bool(args.changed and args.changed.strip())
            or (args.changed and '\n' in args.changed) or not args.root.is_dir()):
        print('approve: usage: a grill confirmation comment URL, revision number >= 1, a YYYY-MM-DD date, '
              'a root folder, and --changed exactly when the number is above 1', file=sys.stderr)
        return 2
    try:
        graph_text = args.graph.read_text(encoding='utf-8')
        revision = args.revision.read_text(encoding='utf-8')
        graph = json.loads(graph_text)
        if (not isinstance(graph, dict) or graph.get('kind') != 'graph' or not isinstance(graph.get('tickets'), list)
                or not graph['tickets'] or not isinstance(graph.get('source'), dict)):
            raise Unreadable('not a graph read')
        stale = read_revision(revision, graph)
        if stale:
            for why in stale:
                print(f'approve: revision: {why}', file=sys.stderr)
            return 1
        failures = [('links', why) for why in check_links(graph_text)]
        open_tickets = [t for t in graph['tickets'] if t['state'] == 'OPEN']
        agents = [t for t in open_tickets if not human(t)]
        owned_why, owners = check_owned(graph, agents)
        failures += [('relies', why) for why in check_relies(agents, owners, args.root.resolve(), graph['repo'].lower())]
        size_why, sizes = check_sizes(open_tickets)
        failures += [('sizes', why) for why in size_why]
        width_why, chain, widest = check_width(graph)
        failures += [('width', why) for why in width_why]
        failures += [('owned paths', why) for why in owned_why]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, Unreadable) as e:
        print(f'approve: unreadable input: {e}', file=sys.stderr)
        return 2
    if failures:
        for check, why in failures:
            print(f'approve: {check}: {why}', file=sys.stderr)
        return 1
    links = sum(len(t['blocked_by']) for t in open_tickets)
    sys.stdout.write(record(args, graph, revision, (links, len(agents), sizes, chain, widest, len(owners))))
    return 0


if __name__ == '__main__':
    sys.exit(main())
