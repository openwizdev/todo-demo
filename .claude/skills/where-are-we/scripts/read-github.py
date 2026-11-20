#!/usr/bin/env python3
"""Collect compact GitHub status sources through explicit GETs; never infer activity.

  read-github.py        milestones, open issues and open pull requests
  read-github.py runs   queued and in-progress CI runs
"""
import json
import subprocess
import sys

ENDPOINTS = {
    'milestones': 'repos/{owner}/{repo}/milestones?state=all&per_page=100',
    'issues': 'repos/{owner}/{repo}/issues?state=open&per_page=100',
    'pulls': 'repos/{owner}/{repo}/pulls?state=open&per_page=100',
}
RUNS = {
    'queued': 'repos/{owner}/{repo}/actions/runs?status=queued&per_page=100',
    'in_progress': 'repos/{owner}/{repo}/actions/runs?status=in_progress&per_page=100',
}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def invalid_constant(_value):
    raise ValueError('non-JSON constant')


def field(item, key, expected):
    value = item[key]
    if type(value) is not expected:
        raise ValueError('unexpected field type')
    return value


def project(source, item):
    if source in RUNS:
        return {key: field(item, key, expected) for key, expected in
                [('id', int), ('name', str), ('status', str), ('head_sha', str)]}
    if source == 'issues' and 'pull_request' in item:
        return None
    compact = {'number': field(item, 'number', int), 'title': field(item, 'title', str)}
    if source == 'milestones':
        compact.update({key: field(item, key, expected) for key, expected in
                        [('state', str), ('open_issues', int), ('closed_issues', int)]})
    elif source == 'issues':
        milestone = item['milestone']
        compact.update(labels=[field(label, 'name', str) for label in field(item, 'labels', list)],
                       milestone=None if milestone is None else field(milestone, 'number', int))
    else:
        compact.update(draft=field(item, 'draft', bool),
                       head={'sha': field(field(item, 'head', dict), 'sha', str)},
                       base={'ref': field(field(item, 'base', dict), 'ref', str)})
    return compact


def gh_pages(endpoint):
    """The pages through `gh`, with the caller's own repository placeholders."""
    try:
        result = subprocess.run(
            ['gh', 'api', '--method', 'GET', '--paginate', '--slurp', endpoint],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except UnicodeError:
        return None, 'invalid paginated JSON'
    except (OSError, subprocess.TimeoutExpired):
        return None, 'gh unavailable or timed out'
    if result.returncode:
        return None, f'gh exited {result.returncode}'
    return json.loads(result.stdout, object_pairs_hook=unique_object, parse_constant=invalid_constant), None


def read(source, endpoint):
    try:
        pages, reason = gh_pages(endpoint)
        if reason:
            return {'state': 'unconfirmed', 'reason': reason}
        if source in RUNS:  # run pages are objects, each holding one list of runs
            if not isinstance(pages, list) or any(not isinstance(page, dict) for page in pages):
                raise ValueError('expected run pages')
            pages = [page.get('workflow_runs') for page in pages]
        if (not isinstance(pages, list) or not pages
                or any(not isinstance(page, list) for page in pages)
                or any(not isinstance(item, dict) for page in pages for item in page)):
            raise ValueError('expected pages of objects')
    except (ValueError, RecursionError, UnicodeError):
        return {'state': 'unconfirmed', 'reason': 'invalid paginated JSON'}
    try:
        items = []
        for page in pages:
            for item in page:
                compact = project(source, item)
                if compact is not None:
                    items.append(compact)
    except (KeyError, TypeError, ValueError):
        return {'state': 'unconfirmed', 'reason': 'invalid source record'}
    return {'state': 'read', 'items': items}


def main(argv):
    if argv not in ([], ['runs']):
        print('usage: read-github.py [runs]', file=sys.stderr)
        return 2
    endpoints = RUNS if argv else ENDPOINTS
    sources = {name: read(name, endpoint) for name, endpoint in endpoints.items()}
    print(json.dumps(sources, separators=(',', ':')))
    return 2 if any(source['state'] == 'unconfirmed' for source in sources.values()) else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
