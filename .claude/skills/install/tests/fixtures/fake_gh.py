#!/usr/bin/env python3
"""A recording fake `gh` for the onboarding journey (#1108).

The demo repository's creation and default-branch read-back share one
synthetic GitHub world at $FAKE_GH_REPOS. Its onboarding switches: "create":
"ok" | "lost" | "fail", "fail_after_create": N (the N `repo view` reads after a
create fail as a network error would), "view_fails". A plain create makes an
empty repository with no branch, as GitHub does; `--add-readme` is GitHub's
initial commit: its default branch `main` holding one README.md. "lost" creates
the repository but exits 1 with no answer, as a timed-out create. Creation and
`repo view` calls are logged to $FAKE_GH_CREATE_LOG.

It also answers the launch's read of a spec's comments (#636: `api --paginate
repos/R/issues/N/comments?per_page=100 --jq EXPR`) from launch-fleet's synthetic
world, through jq as gh does, or fails it when $FAKE_GH_COMMENTS_FAIL is set.
Every other call goes to launch-fleet's fake gh unchanged, which refuses writes.
All values are synthetic.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FLEET_GH = Path(__file__).resolve().parents[3] / 'launch-fleet/scripts/fixtures/gh.py'
FIELDS = {'nameWithOwner', 'isPrivate', 'defaultBranchRef'}


def repository(owner, name, branches):
    """A repository as init's fake models it, created by this login."""
    return {'full_name': '%s/%s' % (owner, name), 'private': True, 'visibility': 'private',
            'default_branch': 'main', 'permissions': {'push': True}, 'owner': {'login': owner, 'type': 'User'},
            'description': None, 'homepage': None, 'labels': [], 'pulls': [], 'branches': branches}


def demo(argv):
    path = os.environ['FAKE_GH_REPOS']
    state = json.loads(Path(path).read_text())
    with open(os.environ['FAKE_GH_CREATE_LOG'], 'a') as log:
        log.write(json.dumps(argv) + '\n')
    if state.get('signed_out'):
        sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
        return 1
    name = argv[2]
    found = state['repos'].get(name.lower())
    if argv[1] == 'view' and state.get('view_fails', 0) > 0:
        state['view_fails'] -= 1
        Path(path).write_text(json.dumps(state))
        sys.stderr.write('synthetic network error\n')
        return 1
    if argv[1] == 'view':
        fields = argv[4].split(',') if argv[3:4] == ['--json'] and len(argv) == 5 else []
        if not fields or set(fields) - FIELDS or found is None or found.get('hidden'):
            sys.stderr.write("GraphQL: Could not resolve to a Repository with the name '%s'.\n" % name)
            return 1
        has = found['default_branch'] in found['branches']
        known = {'nameWithOwner': found['full_name'], 'isPrivate': found['private'],
                 'defaultBranchRef': {'name': found['default_branch'] if has else ''}}
        print(json.dumps({f: known[f] for f in fields}))
        return 0
    readme = argv[3:] == ['--private', '--add-readme']
    if not (readme or argv[3:] == ['--private']) or found is not None or state.get('create') == 'fail':
        sys.stderr.write('synthetic create refused\n')
        return 1
    owner, short = name.split('/')
    state['repos'][name.lower()] = repository(owner, short, {'main': {'README.md': '# %s\n' % short}} if readme else {})
    state['log'].append(['POST', 'user/repos'])
    state['view_fails'] = state.get('fail_after_create', 0)
    Path(path).write_text(json.dumps(state))
    if state.get('create') == 'lost':
        return 1
    print('https://github.com/%s' % name)
    return 0


def default_ref(target, name, branch):
    path = Path(os.environ['FAKE_GH_REPOS'])
    state = json.loads(path.read_text())
    state['log'].append(['GET', target])
    fault = next((entry for entry in state['faults']
                  if entry['method'] == 'GET' and entry['path'] == target
                  and entry['times'] > 0), None)
    if fault:
        fault['times'] -= 1
    path.write_text(json.dumps(state))
    if fault and fault['mode'] == 'drop':
        sys.stderr.write('synthetic connection reset\n')
        return 1
    repo = state['repos'].get(name.lower())
    if fault:
        status, body = fault['mode'], {'message': 'synthetic refusal'}
    elif repo and branch in repo['branches']:
        status, body = 200, {'object': {'sha': 'f' * 40}}
    else:
        status, body = 404, {'message': 'synthetic missing ref'}
    sys.stdout.write(f'HTTP/2.0 {status} Fixture\r\n\r\n{json.dumps(body)}')
    return 0 if status == 200 else 1


def main(argv):
    if argv == ['api', 'user', '--jq', '.login']:
        state = json.loads(Path(os.environ['FAKE_GH_REPOS']).read_text())
        if state.get('signed_out'):
            sys.stderr.write('To get started with GitHub CLI, please run: gh auth login\n')
            return 1
        print(state['user']['login'])
        return 0
    if argv[:2] == ['repo', 'create'] or (argv[:2] == ['repo', 'view'] and len(argv) > 2 and not argv[2].startswith('-')):
        return demo(argv)
    if len(argv) == 5 and argv[:4] == ['api', '--include', '-X', 'GET']:
        match = re.fullmatch(r'repos/([^/]+/[^/]+)/git/ref/heads/(.+)', argv[4])
        if match:
            return default_ref(argv[4], match[1], match[2])
    if argv[:2] == ['api', '--paginate'] and len(argv) == 5 and argv[3] == '--jq':
        match = re.fullmatch(r'repos/([^/]+/[^/]+)/issues/([0-9]+)/comments\?per_page=100', argv[2])
        world = json.loads(Path(os.environ['FAKE_GH_WORLD']).read_text())
        if not match or match[1] != world['repo'] or os.environ.get('FAKE_GH_COMMENTS_FAIL'):
            sys.stderr.write('synthetic: HTTP 404\n')
            return 1
        issue = [i for i in world['issues'] if i['number'] == int(match[2])]
        page = [{'body': c['body'], 'user': {'login': c.get('author', 'synthetic-factory[bot]')}
                 if c.get('author', 'synthetic-factory[bot]') is not None else None}
                for c in (issue[0]['comments'] if issue else [])]
        return subprocess.run(['jq', '-r', argv[4]], input=json.dumps(page), text=True).returncode
    os.execv(sys.executable, [sys.executable, '-I', '-S', str(FLEET_GH), *argv])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
