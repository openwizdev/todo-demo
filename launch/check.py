#!/usr/bin/env python3
"""Print caption data for one completed launch demo using read-only GitHub queries."""

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys


REPO = re.compile(r'([A-Za-z0-9][A-Za-z0-9-]*)/([A-Za-z0-9._-]+)')
UTC = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z')
QUERY = '''query($owner: String!, $repo: String!, $number: Int!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    nameWithOwner
    defaultBranchRef { name }
    issue(number: $number) {
      number title createdAt
      %s { nodes { %s } pageInfo { hasNextPage endCursor } }
    }
  }
}'''
SUB_ISSUES = 'subIssues(first: 100, after: $endCursor)'
CLOSING_PRS = 'closedByPullRequestsReferences(first: 100, after: $endCursor, includeClosedPrs: true)'


def timestamp(value):
    if not isinstance(value, str) or not UTC.fullmatch(value):
        raise ValueError('expected a UTC timestamp in YYYY-MM-DDTHH:MM:SSZ form')
    return datetime.fromisoformat(value[:-1]).replace(tzinfo=timezone.utc)


def unique_object(pairs):
    result = dict(pairs)
    if len(result) != len(pairs):
        raise ValueError('repeated JSON key')
    return result


def read(repo, number, connection, fields, subject):
    owner, name = repo.split('/')
    query = QUERY % (connection, fields)
    field = connection.split('(', 1)[0]
    command = ['gh', 'api', 'graphql', '--hostname', 'github.com', '--paginate', '--slurp',
               '-f', f'query={query}', '-f', f'owner={owner}', '-f', f'repo={name}',
               '-F', f'number={number}']
    nodes, cursors = [], set()
    expected = None
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL, timeout=60)
        pages = json.loads(output, object_pairs_hook=unique_object)
        if not isinstance(pages, list) or not pages:
            raise ValueError
        for index, page in enumerate(pages):
            if not isinstance(page, dict) or page.get('errors'):
                raise ValueError
            repository = page['data']['repository']
            issue = repository['issue']
            branch = repository['defaultBranchRef']['name']
            if (repository['nameWithOwner'].lower() != repo.lower() or type(issue['number']) is not int
                    or issue['number'] != number or not isinstance(issue['title'], str)
                    or not issue['title'] or not isinstance(branch, str) or not branch):
                raise ValueError
            identity = issue['title'], timestamp(issue['createdAt']), branch
            if expected is None:
                expected = identity
            elif identity != expected:
                raise ValueError
            rows = issue[field]['nodes']
            info = issue[field]['pageInfo']
            has_more = index < len(pages) - 1
            if not isinstance(rows, list) or info['hasNextPage'] is not has_more:
                raise ValueError
            if has_more:
                cursor = info['endCursor']
                if not isinstance(cursor, str) or not cursor or cursor in cursors:
                    raise ValueError
                cursors.add(cursor)
            nodes.extend(rows)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError, AttributeError):
        raise ValueError(f'could not read {subject} #{number} from GitHub') from None
    return (*expected, nodes)


def caption(repo, spec, first_prompt):
    start = timestamp(first_prompt)
    title, created, branch, children = read(repo, spec, SUB_ISSUES, 'number title repository { nameWithOwner }', 'spec')
    if start > created:
        raise ValueError('first prompt must be at or before spec creation')
    if not children:
        raise ValueError(f'spec #{spec} has no tickets')

    url = f'https://github.com/{repo}'
    tickets, ticket_numbers = [], set()
    last_merge = None
    for child in children:
        number, ticket_title = child['number'], child['title']
        if (type(number) is not int or number < 1 or number == spec or number in ticket_numbers
                or not isinstance(ticket_title, str) or not ticket_title
                or child['repository']['nameWithOwner'].lower() != repo.lower()):
            raise ValueError(f'spec #{spec} has an invalid, repeated, or cross-repository ticket')
        ticket_numbers.add(number)
        _, _, ticket_branch, pulls = read(
            repo, number, CLOSING_PRS, 'number mergedAt baseRefName repository { nameWithOwner }', 'ticket',
        )
        if ticket_branch != branch:
            raise ValueError('the repository default branch changed during the read')
        merged = {}
        for pull in pulls:
            pull_number, merged_at = pull['number'], pull['mergedAt']
            if pull['repository']['nameWithOwner'].lower() != repo.lower() or pull['baseRefName'] != branch:
                continue
            if merged_at is None:
                continue
            merged_time = timestamp(merged_at)
            if type(pull_number) is not int or pull_number < 1 or merged_time < created:
                raise ValueError(f'ticket #{number} has an invalid merge record')
            merged[pull_number] = {'number': pull_number, 'url': f'{url}/pull/{pull_number}', 'merged_at': merged_at}
            last_merge = merged_time if last_merge is None else max(last_merge, merged_time)
        if not merged:
            raise ValueError(f'ticket #{number} has no merged closing PR into {branch}')
        tickets.append({'number': number, 'title': ticket_title, 'url': f'{url}/issues/{number}',
                        'merged_pull_requests': [merged[key] for key in sorted(merged)]})
    return {
        'spec': {'number': spec, 'title': title, 'url': f'{url}/issues/{spec}'},
        'tickets': sorted(tickets, key=lambda ticket: ticket['number']),
        'first_prompt_at': first_prompt,
        'last_merge_at': last_merge.isoformat().replace('+00:00', 'Z'),
        'elapsed_seconds': int((last_merge - start).total_seconds()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, help='demo repository as OWNER/NAME')
    parser.add_argument('--spec', required=True, type=int, help='demo spec issue number')
    parser.add_argument('--first-prompt', required=True, help='UTC time recorded at the first prompt')
    args = parser.parse_args()
    match = REPO.fullmatch(args.repo)
    if not match or match[2] in ('.', '..') or args.spec < 1:
        parser.error('give a GitHub OWNER/NAME and a positive spec issue number')
    try:
        result = caption(args.repo, args.spec, args.first_prompt)
    except ValueError as error:
        print(f'check: {error}', file=sys.stderr)
        return 1
    except (TypeError, KeyError, AttributeError):
        print('check: GitHub returned malformed ticket or merge data', file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
