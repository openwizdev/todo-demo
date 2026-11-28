import json
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
REPO = 'example/fresh-todo'
PROMPT = '2030-01-02T10:00:00Z'
SPEC = 10


def connection(field, nodes, more=False, cursor=None, number=SPEC):
    return {'data': {'repository': {
        'nameWithOwner': REPO, 'defaultBranchRef': {'name': 'main'},
        'issue': {'number': number, 'title': 'Spec: a to-do list', 'createdAt': '2030-01-02T10:10:00Z',
                  field: {'nodes': nodes, 'pageInfo': {'hasNextPage': more, 'endCursor': cursor}}},
    }}}


def ticket(number, repo=REPO):
    return {'number': number, 'title': f'Ticket {number}', 'repository': {'nameWithOwner': repo}}


def pr(number, at, repo=REPO, base='main'):
    return {'number': number, 'mergedAt': at, 'baseRefName': base,
            'repository': {'nameWithOwner': repo}}


class LaunchTest(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.log = self.root / 'calls'
        self.answers = self.root / 'answers.json'
        self.gh = self.root / 'gh'
        self.gh.write_text(f"""#!{sys.executable}
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['FAKE_CALLS']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] == ['repo', 'create']:
    sys.exit(0)
if args[:2] != ['api', 'graphql'] or '--paginate' not in args or '--slurp' not in args:
    sys.exit('unexpected command')
query = next(a for a in args if a.startswith('query='))
number = next(a.split('=', 1)[1] for a in args if a.startswith('number='))
field = 'subIssues' if 'subIssues(' in query else 'closedByPullRequestsReferences'
responses = json.loads(Path(os.environ['FAKE_ANSWERS']).read_text())
print(json.dumps(responses[field + ':' + number]))
""")
        self.gh.chmod(0o755)
        self.env = {'PATH': str(self.root), 'FAKE_CALLS': str(self.log), 'FAKE_ANSWERS': str(self.answers)}

    def run_check(self, replies, prompt=PROMPT):
        self.answers.write_text(json.dumps(replies))
        return subprocess.run(
            [sys.executable, '-I', str(HERE / 'check.py'), '--repo', REPO, '--spec', str(SPEC),
             '--first-prompt', prompt],
            env=self.env, capture_output=True, text=True, timeout=10,
        )

    def calls(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_caption_uses_all_tickets_and_the_last_verified_merge(self):
        replies = {
            'subIssues:10': [
                connection('subIssues', [ticket(11)], more=True, cursor='next'),
                connection('subIssues', [ticket(12)]),
            ],
            'closedByPullRequestsReferences:11': [connection('closedByPullRequestsReferences', [
                pr(20, None), pr(21, '2030-01-02T12:00:00Z', base='scratch'),
                pr(22, '2030-01-02T12:00:00Z', repo='example/other'),
                pr(23, '2030-01-02T10:20:00Z'),
            ], number=11)],
            'closedByPullRequestsReferences:12': [
                connection('closedByPullRequestsReferences', [pr(24, '2030-01-02T10:25:00Z')],
                           more=True, cursor='next', number=12),
                connection('closedByPullRequestsReferences', [pr(25, '2030-01-02T10:30:01Z')], number=12),
            ],
        }
        result = self.run_check(replies)
        self.assertEqual(result.returncode, 0, result.stderr)
        caption = json.loads(result.stdout)
        self.assertEqual(caption['spec'], {
            'number': 10, 'title': 'Spec: a to-do list', 'url': 'https://github.com/example/fresh-todo/issues/10',
        })
        self.assertEqual([row['number'] for row in caption['tickets']], [11, 12])
        self.assertEqual([[pull['number'] for pull in row['merged_pull_requests']]
                          for row in caption['tickets']], [[23], [24, 25]])
        self.assertEqual(caption['first_prompt_at'], PROMPT)
        self.assertEqual(caption['last_merge_at'], '2030-01-02T10:30:01Z')
        self.assertEqual(caption['elapsed_seconds'], 1801)
        self.assertEqual(len(self.calls()), 3)
        self.assertTrue(all(call[:2] == ['api', 'graphql'] for call in self.calls()))

    def test_incomplete_fleet_produces_no_caption(self):
        result = self.run_check({
            'subIssues:10': [connection('subIssues', [ticket(11)])],
            'closedByPullRequestsReferences:11': [connection('closedByPullRequestsReferences', [pr(20, None)], number=11)],
        })
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertIn('ticket #11 has no merged closing PR', result.stderr)

    def test_truncated_and_errored_reads_produce_no_caption(self):
        for pages in ([connection('subIssues', [ticket(11)], more=True, cursor='next')],
                      [{'errors': [{'message': 'synthetic read failure'}]}]):
            with self.subTest(pages=pages):
                result = self.run_check({'subIssues:10': pages})
                self.assertEqual((result.returncode, result.stdout), (1, ''))
                self.assertIn('could not read spec #10', result.stderr)

    def test_first_prompt_cannot_follow_spec_creation(self):
        result = self.run_check({'subIssues:10': [connection('subIssues', [ticket(11)])]},
                                '2030-01-02T10:11:00Z')
        self.assertEqual((result.returncode, result.stdout), (1, ''))
        self.assertIn('first prompt must be at or before spec creation', result.stderr)

    def test_reset_prints_the_plan_before_an_explicit_yes(self):
        with subprocess.Popen(['/bin/sh', str(HERE / 'reset.sh'), REPO], env=self.env,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as reset:
            try:
                with selectors.DefaultSelector() as ready:
                    ready.register(reset.stdout, selectors.EVENT_READ)
                    self.assertTrue(ready.select(timeout=5), 'reset did not print its plan before reading stdin')
                plan = reset.stdout.readline()
                self.assertIn(f'Create empty private GitHub repository {REPO}', plan)
                self.assertEqual(self.calls(), [])
                _, err = reset.communicate('yes\n', timeout=10)
            finally:
                if reset.poll() is None:
                    reset.kill()
        self.assertEqual(reset.returncode, 0, err)
        self.assertEqual(self.calls(), [['repo', 'create', REPO, '--private']])

    def test_reset_refuses_no_eof_and_option_like_names(self):
        for name, response in ((REPO, 'no\n'), (REPO, ''), (REPO, 'y\n'), ('--public', 'yes\n')):
            with self.subTest(name=name, response=response):
                result = subprocess.run(['/bin/sh', str(HERE / 'reset.sh'), name], env=self.env,
                                        input=response, capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])


if __name__ == '__main__':
    unittest.main()
