"""The collector's public command seam, with synthetic, recording gh only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'read-github.py'
ENDPOINTS = {
    'milestones': 'repos/{owner}/{repo}/milestones?state=all&per_page=100',
    'issues': 'repos/{owner}/{repo}/issues?state=open&per_page=100',
    'pulls': 'repos/{owner}/{repo}/pulls?state=open&per_page=100',
}
# synthetic_assumptions: minimal REST-shaped records with invented values and
# oversized bodies; this fixture was not captured from a live account.
SOURCES = {
    'milestones': [
        {'number': 1, 'title': 'Version one', 'state': 'open', 'open_issues': 2, 'closed_issues': 3, 'body': 'PRIVATE_BODY_SENTINEL'},
        {'number': 11, 'title': 'Version eleven', 'state': 'closed', 'open_issues': 0, 'closed_issues': 4},
    ],
    'issues': [
        {'number': 2, 'title': 'Build one', 'labels': [{'name': 'ready-for-agent', 'color': 'ffffff', 'description': 'NESTED_SENTINEL'}],
         'milestone': {'number': 1, 'title': 'Version one', 'description': 'NESTED_SENTINEL'}, 'body': 'PRIVATE_BODY_SENTINEL'},
        {'number': 12, 'title': 'Build eleven', 'labels': [], 'milestone': None},
    ],
    'pulls': [
        {'number': 3, 'title': 'Change one', 'draft': False, 'head': {'sha': 'synthetic-head-one', 'repo': {'description': 'NESTED_SENTINEL'}},
         'base': {'ref': 'main', 'repo': {'description': 'NESTED_SENTINEL'}}, 'body': 'PRIVATE_BODY_SENTINEL'},
        {'number': 13, 'title': 'Change eleven', 'draft': True, 'head': {'sha': 'synthetic-head-eleven'}, 'base': {'ref': 'main'}},
    ],
}
EXPECTED = {
    'milestones': [
        {'number': 1, 'title': 'Version one', 'state': 'open', 'open_issues': 2, 'closed_issues': 3},
        {'number': 11, 'title': 'Version eleven', 'state': 'closed', 'open_issues': 0, 'closed_issues': 4},
    ],
    'issues': [
        {'number': 2, 'title': 'Build one', 'labels': ['ready-for-agent'], 'milestone': 1},
        {'number': 12, 'title': 'Build eleven', 'labels': [], 'milestone': None},
    ],
    'pulls': [
        {'number': 3, 'title': 'Change one', 'draft': False, 'head': {'sha': 'synthetic-head-one'}, 'base': {'ref': 'main'}},
        {'number': 13, 'title': 'Change eleven', 'draft': True, 'head': {'sha': 'synthetic-head-eleven'}, 'base': {'ref': 'main'}},
    ],
}
FAKE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
answers = json.loads(Path(os.environ['ANSWERS']).read_text())
key = args[-1] if args else ''
if args[:5] != ['api', '--method', 'GET', '--paginate', '--slurp'] or len(args) != 6 or key not in answers:
    sys.exit(91)
answer = answers[key]
if key == os.environ.get('INVALID_ENDPOINT'):
    os.write(2 if os.environ['INVALID_STREAM'] == 'stderr' else 1, bytes([255]))
if isinstance(answer, str):
    print(answer)
else:
    print(json.dumps(answer))
if key == os.environ.get('FAIL_ENDPOINT'):
    print('synthetic private diagnostic', file=sys.stderr)
    sys.exit(7)
'''


class ReadGithub(unittest.TestCase):
    def run_collector(self, replacements=None, fail=None, missing=False, invalid=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / 'gh'
            binary.write_text(FAKE)
            binary.chmod(0o755)
            answers = {endpoint: [[copy.deepcopy(item)] for item in SOURCES[name]]
                       for name, endpoint in ENDPOINTS.items()}
            if replacements:
                answers.update(replacements)
            (root / 'answers.json').write_text(json.dumps(answers))
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            # No configured installation (#2317, Assumption A1): these cases
            # are the gh route, whatever the machine's own state holds.
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       ANSWERS=str(root / 'answers.json'), CALLS=str(root / 'calls'),
                       OPENWIZ_STATE_DIR=str(root / 'no-installation'))
            if fail:
                env['FAIL_ENDPOINT'] = fail
            if invalid:
                env['INVALID_ENDPOINT'] = ENDPOINTS['issues']
                env['INVALID_STREAM'] = invalid
            if missing:
                binary.unlink()
                # Prevent falling through to a real authenticated gh.
                env['PATH'] = tmp
            result = subprocess.run([sys.executable, '-B', str(SCRIPT)], cwd=root,
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
            after = {p.name: p.read_bytes() for p in root.iterdir() if p.name != 'calls'}
            if missing:
                before.pop('gh')
            self.assertEqual(before, after, 'collector wrote to its working directory')
            return result, calls

    def assert_calls(self, calls):
        self.assertEqual(calls, [['api', '--method', 'GET', '--paginate', '--slurp', endpoint]
                                 for endpoint in ENDPOINTS.values()])

    def test_all_pages_and_only_get_reads(self):
        result, calls = self.run_collector()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assert_calls(calls)
        self.assertEqual(json.loads(result.stdout), {
            name: {'state': 'read', 'items': EXPECTED[name]} for name in ENDPOINTS})

    def test_compact_records_drop_bodies_metadata_and_pr_issue_entries(self):
        entries = copy.deepcopy(SOURCES['issues'])
        entries.insert(1, {'number': 99, 'pull_request': {'url': 'synthetic-pr'},
                           'title': 'DUPLICATE_PR_SENTINEL', 'body': 'PRIVATE_BODY_SENTINEL'})
        result, calls = self.run_collector({ENDPOINTS['issues']: [entries[:2], entries[2:]]})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calls(calls)
        self.assertNotIn('PRIVATE_BODY_SENTINEL', result.stdout)
        self.assertNotIn('NESTED_SENTINEL', result.stdout)
        self.assertNotIn('DUPLICATE_PR_SENTINEL', result.stdout)
        self.assertEqual(json.loads(result.stdout), {
            name: {'state': 'read', 'items': EXPECTED[name]} for name in ENDPOINTS})

    def test_broad_fixture_fits_without_dropping_status_records(self):
        # Invented collection sizes (not counts from any real project), large
        # enough to need a second issues page, with about 1 MiB of bodies. This
        # proves a representative fixture, not a universal cap.
        milestones = [dict(copy.deepcopy(SOURCES['milestones'][0]), number=n)
                      for n in range(1, 8)]
        issues = [dict(copy.deepcopy(SOURCES['issues'][0]), number=n,
                       body='PRIVATE_BODY_SENTINEL' + 'x' * 8192) for n in range(1, 132)]
        duplicates = [{'number': n, 'pull_request': {}, 'body': 'DUPLICATE_PR_SENTINEL'}
                      for n in range(301, 324)]
        pulls = [dict(copy.deepcopy(SOURCES['pulls'][0]), number=n,
                      body='PRIVATE_BODY_SENTINEL' + 'x' * 8192) for n in range(301, 324)]
        result, calls = self.run_collector({
            ENDPOINTS['milestones']: [milestones],
            ENDPOINTS['issues']: [issues[:100], issues[100:] + duplicates],
            ENDPOINTS['pulls']: [pulls],
        })
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calls(calls)
        self.assertLess(len(result.stdout.encode()), 30_000)
        self.assertNotIn('PRIVATE_BODY_SENTINEL', result.stdout)
        self.assertNotIn('DUPLICATE_PR_SENTINEL', result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual([item['number'] for item in data['milestones']['items']], list(range(1, 8)))
        self.assertEqual([item['number'] for item in data['issues']['items']], list(range(1, 132)))
        self.assertEqual([item['number'] for item in data['pulls']['items']], list(range(301, 324)))

    def test_malformed_selected_fields_leave_only_their_source_unconfirmed(self):
        for source, field, value in [
            ('milestones', 'title', None),
            ('milestones', 'open_issues', True),
            ('issues', 'labels', [{'name': {'body': 'NESTED_SENTINEL'}}]),
            ('issues', 'milestone', {'number': '1'}),
            ('pulls', 'head', None),
            ('pulls', 'draft', 'false'),
        ]:
            with self.subTest(source=source, field=field):
                items = copy.deepcopy(SOURCES[source])
                items[0][field] = value
                result, calls = self.run_collector({ENDPOINTS[source]: [items]})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assert_calls(calls)
                data = json.loads(result.stdout)
                self.assertEqual(data[source], {'state': 'unconfirmed', 'reason': 'invalid source record'})
                for other in ENDPOINTS.keys() - {source}:
                    self.assertEqual(data[other], {'state': 'read', 'items': EXPECTED[other]})

    def test_empty_pages_are_confirmed_empty(self):
        result, calls = self.run_collector({endpoint: [[]] for endpoint in ENDPOINTS.values()})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_calls(calls)
        self.assertEqual(json.loads(result.stdout), {
            name: {'state': 'read', 'items': []} for name in ENDPOINTS})

    def test_failed_read_discards_partial_output_but_keeps_other_sources(self):
        result, calls = self.run_collector(fail=ENDPOINTS['issues'])
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assert_calls(calls)
        data = json.loads(result.stdout)
        self.assertEqual(data['issues'], {'state': 'unconfirmed', 'reason': 'gh exited 7'})
        self.assertEqual(data['milestones']['items'], EXPECTED['milestones'])
        self.assertEqual(data['pulls']['items'], EXPECTED['pulls'])
        self.assertNotIn('private diagnostic', result.stdout + result.stderr)

    def test_bad_json_or_collection_shape_never_becomes_empty_success(self):
        for bad in ['not JSON', {}, [None], [[1]], [], '[[{"number":1,"number":2}]]', 'NaN']:
            with self.subTest(bad=bad):
                result, calls = self.run_collector({ENDPOINTS['issues']: bad})
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assert_calls(calls)
                data = json.loads(result.stdout)
                self.assertEqual(data['issues'], {'state': 'unconfirmed', 'reason': 'invalid paginated JSON'})
                self.assertEqual(data['pulls']['state'], 'read')

    def test_invalid_utf8_preserves_independent_reads(self):
        for stream in ['stdout', 'stderr']:
            with self.subTest(stream=stream):
                result, calls = self.run_collector(invalid=stream)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assert_calls(calls)
                data = json.loads(result.stdout)
                self.assertEqual(data['issues'], {'state': 'unconfirmed', 'reason': 'invalid paginated JSON'})
                self.assertEqual(data['milestones']['items'], EXPECTED['milestones'])
                self.assertEqual(data['pulls']['items'], EXPECTED['pulls'])

    def test_missing_gh_is_unconfirmed_for_every_source(self):
        result, calls = self.run_collector(missing=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(calls, [])
        self.assertEqual(json.loads(result.stdout), {
            name: {'state': 'unconfirmed', 'reason': 'gh unavailable or timed out'}
            for name in ENDPOINTS})


RUNS = {
    'queued': 'repos/{owner}/{repo}/actions/runs?status=queued&per_page=100',
    'in_progress': 'repos/{owner}/{repo}/actions/runs?status=in_progress&per_page=100',
}


def run_record(n, status):
    # Synthetic REST-shaped run with invented values and fields the view drops.
    return {'id': n, 'name': f'check {n}', 'status': status, 'head_sha': f'synthetic-head-{n}',
            'head_branch': f'branch-{n}', 'html_url': 'NESTED_SENTINEL', 'head_commit': {'message': 'PRIVATE_BODY_SENTINEL'}}


def run_pages(status, numbers, size=2):
    runs = [run_record(n, status) for n in numbers]
    return [{'total_count': len(runs), 'workflow_runs': runs[i:i + size]}
            for i in range(0, max(len(runs), 1), size)]


def compact_run(n, status):
    return {'id': n, 'name': f'check {n}', 'status': status, 'head_sha': f'synthetic-head-{n}'}


class ReadRuns(unittest.TestCase):
    """`read-github.py runs`: queued and in-progress CI runs, every page (#1186)."""

    def run_runs(self, answers, fail=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'gh').write_text(FAKE)
            (root / 'gh').chmod(0o755)
            (root / 'answers.json').write_text(json.dumps(answers))
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       ANSWERS=str(root / 'answers.json'), CALLS=str(root / 'calls'),
                       OPENWIZ_STATE_DIR=str(root / 'no-installation'))
            if fail:
                env['FAIL_ENDPOINT'] = fail
            result = subprocess.run([sys.executable, '-B', str(SCRIPT), 'runs'], cwd=root,
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
            return result, calls

    def test_runs_reads_every_page_of_both_states(self):
        result, calls = self.run_runs({RUNS['queued']: run_pages('queued', [1, 2, 3]),
                                       RUNS['in_progress']: run_pages('in_progress', [])})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [['api', '--method', 'GET', '--paginate', '--slurp', endpoint]
                                 for endpoint in RUNS.values()])
        self.assertNotIn('SENTINEL', result.stdout)
        self.assertEqual(json.loads(result.stdout), {
            'queued': {'state': 'read', 'items': [compact_run(n, 'queued') for n in (1, 2, 3)]},
            'in_progress': {'state': 'read', 'items': []},
        })

    def test_an_unread_run_state_is_unconfirmed_not_empty(self):
        good = run_pages('in_progress', [4])
        for name, answer, fail, reason in [
            ('failed read', run_pages('queued', [1]), RUNS['queued'], 'gh exited 7'),
            ('list pages', [[run_record(1, 'queued')]], None, 'invalid paginated JSON'),
            ('no runs key', [{'total_count': 0}], None, 'invalid paginated JSON'),
            ('bad record', [{'total_count': 1, 'workflow_runs': [{'id': '1'}]}], None, 'invalid source record'),
        ]:
            with self.subTest(name):
                result, _ = self.run_runs({RUNS['queued']: answer, RUNS['in_progress']: good}, fail=fail)
                self.assertEqual(result.returncode, 2, result.stderr)
                data = json.loads(result.stdout)
                self.assertEqual(data.get('queued'), {'state': 'unconfirmed', 'reason': reason})
                self.assertEqual(data.get('in_progress'), {'state': 'read', 'items': [compact_run(4, 'in_progress')]})


class NoInstallationRoute(unittest.TestCase):
    """The installation read route is removed (#1238); gh is the only route (#1186)."""

    def test_a_configured_installation_still_reads_through_gh(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'gh').write_text(FAKE)
            (root / 'gh').chmod(0o755)
            answers = {endpoint: [[copy.deepcopy(item)] for item in SOURCES[name]]
                       for name, endpoint in ENDPOINTS.items()}
            (root / 'answers.json').write_text(json.dumps(answers))
            marker = root / 'state' / 'service' / 'github-reads' / 'installation.json'
            marker.parent.mkdir(parents=True)
            marker.write_text('{}')
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'],
                       ANSWERS=str(root / 'answers.json'), CALLS=str(root / 'calls'),
                       OPENWIZ_STATE_DIR=str(root / 'state'), GH_REPO='example-org/example-repo')
            result = subprocess.run([sys.executable, '-B', str(SCRIPT)], cwd=root,
                                    env=env, capture_output=True, text=True)
            calls = [json.loads(line) for line in (root / 'calls').read_text().splitlines()] if (root / 'calls').exists() else []
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(calls, [['api', '--method', 'GET', '--paginate', '--slurp', endpoint]
                                 for endpoint in ENDPOINTS.values()])
        self.assertEqual(json.loads(result.stdout), {
            name: {'state': 'read', 'items': EXPECTED[name]} for name in ENDPOINTS})


if __name__ == '__main__':
    unittest.main()
