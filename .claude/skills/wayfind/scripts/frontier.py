#!/usr/bin/env python3
"""Read a wayfind map's frontier, or who holds one question's claim.

  python3 -I frontier.py map <map>
      <map> is the map's issue number. The issue must carry the `wayfind:map`
      label; any other issue refuses. One line per open question, in the
      map's order:
        #<n> frontier <kind label>: <title>
        #<n> blocked by #<a> #<b>: <title>
        #<n> held by <claim comment id>: <title>
        #<n> no kind label: <title>      (not exactly one wayfind: kind)
      or `no open question` when every question is closed.
  python3 -I frontier.py holder <question> [--mine <claim comment id>]
      <question> is the question's issue number. `closed`, `no kind label`,
      `blocked by #<a> #<b>`, else `unclaimed`, `held by <id>` or `yours`
      (your claim holds and nothing blocks it).
      Work only on `yours`; on anything else release your claim and stop.

A claim is a comment whose body is `wayfind: claimed`; its id is the
numeric `#issuecomment-` suffix of its URL. `wayfind: released <id>` after
it releases that claim. The earliest unreleased claim holds the question.
Only a record author's claim or release counts: a login in the Record
authors row of the `## GitHub identity` table of docs/agents/fleet.md on
the repository's default branch. Anyone else's comment is ignored; a
missing or malformed row (anything but `| Record authors | <logins> |`)
trusts nobody and refuses the read.

Every connection is read page by page, in order, through its cursors; a
page chain that stops short, repeats a cursor or changes its total refuses.
Exits 2 with the reason on stderr and nothing on stdout when any part of
the read fails or is incomplete. Never read that as an empty frontier.
Needs gh (signed in). Every issue number names an issue in one repository:
GH_REPO when set, else the current clone's.
"""
import json
import re
import subprocess
import sys

MAP = 'wayfind:map'
KINDS = ('wayfind:grill', 'wayfind:research', 'wayfind:prototype', 'wayfind:task')
CLAIM = 'wayfind: claimed'
RELEASE = re.compile(r'wayfind: released ([1-9][0-9]*)')
COMMENT_ID = re.compile(r'#issuecomment-([1-9][0-9]*)')
LOGIN = re.compile(r'[a-z0-9][a-z0-9-]{0,38}(?:\[bot\])?')
# Only the connection being advanced binds the cursor; every other one, nested
# ones included, starts at its first page (GitHub refuses a shared cursor).
PAGE = '%s(first: 100%s) { totalCount pageInfo { hasNextPage endCursor } nodes { %s } }'
FIELDS = {'labels': 'name', 'blockedBy': 'number state',
          'comments': 'url body author { __typename login }'}
QUESTION = 'number title state ' + ' '.join(PAGE % (f, '', n) for f, n in FIELDS.items())
FIELDS['subIssues'] = QUESTION
QUERY = '''query($owner: String!, $repo: String!, $number: Int!%s) {
  repository(owner: $owner, name: $repo) { issue(number: $number) { %s } }
}'''
FLEET = '''query($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    object(expression: "HEAD:docs/agents/fleet.md") { ... on Blob { text } }
  }
}'''


class Refuse(Exception):
    pass


def graphql(what, query, values):
    try:
        out = subprocess.run(
            ['gh', 'api', 'graphql', '-F', 'owner={owner}', '-F', 'repo={repo}',
             *values, '-f', 'query=' + query],
            capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Refuse(f'gh could not run: {error}')
    if out.returncode != 0:
        raise Refuse(f'gh failed reading {what}')
    try:
        data = json.loads(out.stdout)
    except ValueError:
        raise Refuse(f'gh returned no JSON for {what}')
    if not isinstance(data, dict) or data.get('errors'):
        raise Refuse(f'GitHub returned an error for {what}')
    repository = (data.get('data') or {}).get('repository')
    return repository if isinstance(repository, dict) else {}


def read(number, fields, after=None):
    values = ['-F', f'number={number}'] + ([] if after is None else ['-f', f'after={after}'])
    query = QUERY % ('' if after is None else ', $after: String', fields)
    issue = graphql(f'#{number}', query, values).get('issue')
    if not isinstance(issue, dict):
        raise Refuse(f'#{number} is not a readable issue')
    return issue


def record_authors():
    blob = graphql('docs/agents/fleet.md', FLEET, []).get('object')
    text = blob.get('text') if isinstance(blob, dict) else None
    if not isinstance(text, str):
        raise Refuse('no docs/agents/fleet.md on the default branch: trust nobody')
    inside, rows = False, []
    for row in text.splitlines():
        if row.startswith('## '):
            inside = row.strip().lower() == '## github identity'
        elif inside and re.match(r'\|\s*Record authors\s*\|', row):
            rows.append(row)
    if len(rows) != 1:
        raise Refuse('no single Record authors row in the GitHub identity table: trust nobody')
    columns = rows[0].split('|')
    if len(columns) != 4 or columns[3].strip():
        raise Refuse('malformed Record authors row: trust nobody')
    cells = [cell.strip() for cell in columns[2].split(',')]
    logins = [cell[1:-1].lower() if len(cell) > 2 and cell[0] == cell[-1] == '`' else ''
              for cell in cells]
    if not all(LOGIN.fullmatch(login) for login in logins):
        raise Refuse('malformed Record authors row: trust nobody')
    return set(logins)


def nodes(issue, field):
    """Every node of one connection, in order, following and checking its cursors."""
    if ('all', field) in issue:
        return issue[('all', field)]
    connection, found, cursors, total = issue.get(field), [], set(), None
    while True:
        if not isinstance(connection, dict) or not isinstance(connection.get('nodes'), list) \
                or not all(isinstance(node, dict) for node in connection['nodes']) \
                or not isinstance(connection.get('pageInfo'), dict) \
                or not isinstance(connection['pageInfo'].get('hasNextPage'), bool):
            raise Refuse(f'#{issue.get("number")} has no readable {field}')
        if found and connection.get('totalCount') != total:
            raise Refuse(f'#{issue.get("number")} changed its {field} while being read')
        total = connection.get('totalCount')
        found += connection['nodes']
        cursor = connection['pageInfo'].get('endCursor')
        if not connection['pageInfo']['hasNextPage']:
            break
        if not isinstance(cursor, str) or not cursor or cursor in cursors:
            raise Refuse(f'#{issue.get("number")} has a broken page chain in its {field}')
        cursors.add(cursor)
        connection = read(issue['number'], PAGE % (field, ', after: $after', FIELDS[field]), cursor).get(field)
    if total != len(found):
        raise Refuse(f'#{issue.get("number")} has more {field} than its pages return')
    issue[('all', field)] = found
    return found


def author(comment):
    """The comment's login as fleet.md writes it (an App as `<name>[bot]`), or None."""
    who = comment.get('author')
    login = who.get('login') if isinstance(who, dict) else None
    if not isinstance(login, str):
        return None
    login = login.lower()
    return login + '[bot]' if who.get('__typename') == 'Bot' and not login.endswith('[bot]') else login


def holder(issue, authors):
    claims = []
    for comment in nodes(issue, 'comments'):
        if author(comment) not in authors:
            continue
        body = (comment.get('body') or '').strip()
        if body == CLAIM:
            found = COMMENT_ID.search(comment.get('url') or '')
            if not found or not comment['url'].endswith(found.group(0)):
                raise Refuse(f'#{issue["number"]} has a claim without its comment id')
            claims.append(found.group(1))
        elif RELEASE.fullmatch(body) and RELEASE.fullmatch(body).group(1) in claims:
            claims.remove(RELEASE.fullmatch(body).group(1))
    return claims[0] if claims else None


def standing(question):
    """Why nobody may work on this question now, or its kind label when they may."""
    kinds = [l['name'] for l in nodes(question, 'labels') if str(l.get('name')).startswith('wayfind:')]
    blockers = [b['number'] for b in nodes(question, 'blockedBy') if b.get('state') != 'CLOSED']
    if len(kinds) != 1 or kinds[0] not in KINDS:
        return False, 'no kind label'
    if blockers:
        return False, 'blocked by ' + ' '.join(f'#{n}' for n in blockers)
    return True, kinds[0]


def line(question, authors):
    held = holder(question, authors)
    eligible, what = standing(question)
    if eligible:
        what = f'held by {held}' if held else f'frontier {what}'
    return f'#{question["number"]} {what}: {question["title"]}'


def main(argv):
    if len(argv) == 2 and argv[0] == 'map' and argv[1].isdigit():
        authors = record_authors()
        issue = read(int(argv[1]), 'number ' + PAGE % ('labels', '', FIELDS['labels'])
                     + ' ' + PAGE % ('subIssues', '', QUESTION))
        if MAP not in [label.get('name') for label in nodes(issue, 'labels')]:
            raise Refuse(f'#{argv[1]} has no {MAP} label: not a map')
        lines = [line(q, authors) for q in nodes(issue, 'subIssues') if q.get('state') == 'OPEN']
        return '\n'.join(lines) if lines else 'no open question'
    if len(argv) in (2, 4) and argv[0] == 'holder' and argv[1].isdigit() and \
            (len(argv) == 2 or (argv[2] == '--mine' and argv[3].isdigit())):
        authors = record_authors()
        issue = read(int(argv[1]), QUESTION)
        held, (eligible, why) = holder(issue, authors), standing(issue)
        if issue.get('state') != 'OPEN':
            return 'closed'
        if not eligible:
            return why
        if held is None:
            return 'unclaimed'
        return 'yours' if len(argv) == 4 and held == argv[3] else f'held by {held}'
    raise Refuse('usage: frontier.py map <map> | holder <question> [--mine <claim comment id>]')


if __name__ == '__main__':
    try:
        print(main(sys.argv[1:]))
    except Refuse as error:
        print(f'frontier: {error}', file=sys.stderr)
        sys.exit(2)
