#!/usr/bin/env python3
"""frontier.py through its CLI, against a fake `gh` serving synthetic GraphQL.

Each case runs the script with PATH holding only the fake `gh` and python3,
so the real `gh` is never reached. All issue data is synthetic.

Usage: python3 -I skills/wayfind/test/test_frontier.py
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/frontier.py'
FAKE_GH = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ['FIXTURE_LOG'], 'a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:2] != ['api', 'graphql']:
    sys.exit(90)
values = dict(a.split('=', 1) for a in args if '=' in a and not a.startswith('query='))
query = next(a for a in args if a.startswith('query='))
# GitHub refuses a cursor bound to more than one connection (a nested one
# gets INVALID_CURSOR_ARGUMENTS) and a declared variable no field uses.
declared, uses = '$after: String' in query, query.count('after: $after')
if (declared, uses) not in ((False, 0), (True, 1)) or ('after' in values and not declared):
    print(json.dumps({'errors': [{'type': 'INVALID_CURSOR_ARGUMENTS'}]}))
    sys.exit(1)
key = values.get('number', 'fleet') + ('@' + values['after'] if 'after' in values else '')
served = json.load(open(os.environ['FIXTURE']))[key]
if served == 'fail':
    sys.exit(1)
print(json.dumps(served))
'''
URL = 'https://github.com/example/widgets/issues/{n}#issuecomment-{c}'


def conn(nodes, total=None, after=None):
    """One connection page; `after` is the cursor of the next page, if any."""
    return {'totalCount': len(nodes) if total is None else total, 'nodes': nodes,
            'pageInfo': {'hasNextPage': after is not None, 'endCursor': after}}


RECORDER = 'synthetic-recorder'
OUTSIDER = 'synthetic-outsider'


def comment(n, c, body, login=RECORDER, kind='User'):
    return {'url': URL.format(n=n, c=c), 'body': body,
            'author': {'__typename': kind, 'login': login}}


def question(n, kind='wayfind:grill', state='OPEN', blockers=(), comments=(), title=None):
    labels = [] if kind is None else [kind] if isinstance(kind, str) else list(kind)
    return {'number': n, 'title': title or f'Synthetic question {n}', 'state': state,
            'labels': conn([{'name': name} for name in labels]),
            'blockedBy': conn([{'number': b, 'state': s} for b, s in blockers]),
            'comments': conn([comment(n, *c) for c in comments])}


def served(issue):
    return {'data': {'repository': {'issue': issue}}}


def a_map(n, questions, total=None, after=None, labels=('wayfind:map',)):
    return served({'number': n, 'title': 'Synthetic map', 'state': 'OPEN',
                   'labels': conn([{'name': name} for name in labels]),
                   'subIssues': conn(questions, total, after)})


FLEET = ('# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
         '| Record authors | `synthetic-factory[bot]`, `Synthetic-Recorder` |\n')


def fleet(text=FLEET):
    return {'data': {'repository': {'object': None if text is None else {'text': text}}}}


CLAIM = 'wayfind: claimed'


class FrontierTest(unittest.TestCase):
    def run_script(self, fixture, *args):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tools = root / 'tools'
            tools.mkdir()
            (tools / 'python3').symlink_to(sys.executable)
            (tools / 'gh').write_text(FAKE_GH)
            (tools / 'gh').chmod(0o700)
            (root / 'fixture.json').write_text(json.dumps({'fleet': fleet(), **fixture}))
            result = subprocess.run(
                [sys.executable, '-I', str(SCRIPT), *args], capture_output=True, text=True,
                env={'PATH': str(tools), 'FIXTURE': str(root / 'fixture.json'),
                     'FIXTURE_LOG': str(root / 'log'), 'GH_REPO': 'example/widgets'})
            reads = [json.loads(line) for line in (root / 'log').read_text().splitlines()] \
                if (root / 'log').exists() else []
            return result, reads

    def test_map_lists_each_open_question_and_its_frontier_in_map_order(self):
        # catches: a closed, blocked, claimed or kind-less question offered as
        # frontier, or the map's order lost so "the first frontier" changes.
        fixture = {'1': a_map(1, [
            question(14, kind='wayfind:research', title='Which API limits apply?'),
            question(10, state='CLOSED'),
            question(11, blockers=[(10, 'CLOSED'), (12, 'OPEN'), (13, 'OPEN')]),
            question(12, comments=[(500, CLAIM)]),
            question(13, kind=None),
            question(15, kind=('wayfind:grill', 'wayfind:task')),
            question(16, blockers=[(10, 'CLOSED')]),
        ])}
        result, reads = self.run_script(fixture, 'map', '1')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, (
            '#14 frontier wayfind:research: Which API limits apply?\n'
            '#11 blocked by #12 #13: Synthetic question 11\n'
            '#12 held by 500: Synthetic question 12\n'
            '#13 no kind label: Synthetic question 13\n'
            '#15 no kind label: Synthetic question 15\n'
            '#16 frontier wayfind:grill: Synthetic question 16\n'))
        self.assertEqual(len(reads), 2)  # the record authors, then the map in one page

    def test_clear_map_says_so(self):
        # catches: an empty frontier read as "nothing to do" when questions
        # remain open, or a clear map mistaken for an unread one.
        result, _ = self.run_script({'2': a_map(2, [question(20, state='CLOSED')])}, 'map', '2')
        self.assertEqual((result.returncode, result.stdout), (0, 'no open question\n'))

    def test_an_issue_without_the_map_label_is_never_a_clear_map(self):
        # catches #1617: an ordinary issue (or one whose label is only a
        # question's kind) read as a map, so `no open question` admits to-spec.
        cases = {'ordinary issue': a_map(3, [], labels=()),
                 'other labels only': a_map(3, [question(30)], labels=('bug', 'wayfind:grill')),
                 'no labels field': served({'number': 3, 'subIssues': conn([])})}
        for name, issue in cases.items():
            with self.subTest(name):
                result, _ = self.run_script({'3': issue}, 'map', '3')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.startswith('frontier: '), result.stderr)
        result, _ = self.run_script({'3': a_map(3, [], labels=('bug', 'wayfind:map'))}, 'map', '3')
        self.assertEqual((result.returncode, result.stdout), (0, 'no open question\n'))

    def test_earliest_unreleased_claim_holds(self):
        # catches: a later claim, or a released one, treated as the holder;
        # the comment id taken from anything but the #issuecomment- suffix.
        for ids, holder in [([100, 101, 103], '100'), ([101, 103, 104], '103')]:
            with self.subTest(claims=ids):
                comments = [(c, CLAIM) for c in ids] + [(110, 'wayfind: released 101')]
                result, _ = self.run_script({'9': served(question(9, comments=comments))},
                                            'holder', '9')
                self.assertEqual((result.returncode, result.stdout), (0, f'held by {holder}\n'))
        result, _ = self.run_script({'9': served(question(9, comments=[
            (100, CLAIM), (101, 'wayfind: released 100'), (102, 'Synthetic note')]))}, 'holder', '9')
        self.assertEqual(result.stdout, 'unclaimed\n')

    def test_mine_says_yours_only_for_the_holding_claim(self):
        # catches: an agent working on a question an earlier claim holds.
        comments = [(100, CLAIM), (101, CLAIM)]
        fixture = {'9': served(question(9, comments=comments))}
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '100')[0].stdout, 'yours\n')
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '101')[0].stdout,
                         'held by 100\n')
        closed = {'9': served(question(9, state='CLOSED', comments=comments))}
        self.assertEqual(self.run_script(closed, 'holder', '9', '--mine', '100')[0].stdout, 'closed\n')

    def test_incomplete_or_unreadable_read_prints_nothing_and_exits_2(self):
        # catches: a partial read reported as a frontier or a holder, so a
        # claim on an unread comment page or an unread question is missed.
        cases = {
            'gh fails': ({'1': 'fail'}, 'map'),
            'graphql error': ({'1': {'errors': [{'message': 'Synthetic'}]}}, 'map'),
            'no such issue': ({'1': served(None)}, 'map'),
            'questions truncated': ({'1': a_map(1, [question(11)], total=101)}, 'map'),
            'comments truncated': ({'1': a_map(1, [dict(question(11), comments=conn([], 101))])}, 'map'),
            'blockers truncated': ({'1': served(dict(question(1), blockedBy=conn([], 101)))}, 'holder'),
            'claim without its id': ({'1': served(dict(question(1), comments=conn(
                [dict(comment(1, 5, CLAIM), url='https://github.com/example/widgets/issues/1')])))},
                                     'holder'),
        }
        for name, (fixture, verb) in cases.items():
            with self.subTest(name):
                result, _ = self.run_script(fixture, verb, '1')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.startswith('frontier: '), result.stderr)


    def test_only_record_authors_claim_or_release(self):
        # catches #1508: an outsider's comment reserving a question, or
        # releasing a record author's claim so a later claim reads `yours`.
        comments = [(98, CLAIM, 'synthetic-factory'), (99, CLAIM, OUTSIDER), (100, CLAIM), (101, 'wayfind: released 100', OUTSIDER),
                    (102, CLAIM, 'synthetic-factory', 'Bot')]
        fixture = {'9': served(question(9, comments=comments))}
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '102')[0].stdout,
                         'held by 100\n')
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '100')[0].stdout, 'yours\n')
        released = {'9': served(question(9, comments=comments + [(103, 'wayfind: released 100')]))}
        self.assertEqual(self.run_script(released, 'holder', '9', '--mine', '102')[0].stdout, 'yours\n')
        outside_only = {'1': a_map(1, [question(9, comments=[(99, CLAIM, OUTSIDER)])])}
        self.assertEqual(self.run_script(outside_only, 'map', '1')[0].stdout,
                         '#9 frontier wayfind:grill: Synthetic question 9\n')

    def test_unreadable_record_authors_trust_nobody(self):
        # catches #1508: a missing or malformed Record authors row read as
        # "anyone may claim" instead of refusing the read.
        for name, text in {'no fleet file': None, 'no row': '# Fleet\n\n## GitHub identity\n\n',
                           'malformed row': '# Fleet\n\n## GitHub identity\n\n| Record authors | x y |\n',
                           # catches #1696: an extra column after the logins read as their cell.
                           'extra column': FLEET.replace('`Synthetic-Recorder` |',
                                                         '`Synthetic-Recorder` | synthetic note |'),
                           'text after the row': FLEET.replace('`Synthetic-Recorder` |',
                                                               '`Synthetic-Recorder` | synthetic'),
                           }.items():
            with self.subTest(name):
                fixture = {'fleet': fleet(text), '9': served(question(9, comments=[(100, CLAIM)]))}
                result, _ = self.run_script(fixture, 'holder', '9', '--mine', '100')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.startswith('frontier: '), result.stderr)

    def test_a_blocked_or_kindless_question_is_never_yours(self):
        # catches #1567: the holder check returning `yours` for a question
        # whose blocker is still open, or that carries no single kind label.
        cases = [(question(9, blockers=[(7, 'CLOSED'), (8, 'OPEN')], comments=[(100, CLAIM)]),
                  'blocked by #8\n'),
                 (question(9, kind=None, comments=[(100, CLAIM)]), 'no kind label\n'),
                 (question(9, kind=('wayfind:grill', 'wayfind:task'), comments=[(100, CLAIM)]),
                  'no kind label\n'),
                 (question(9, blockers=[(7, 'CLOSED')], comments=[(100, CLAIM)]), 'yours\n')]
        for issue, expected in cases:
            with self.subTest(expected):
                result, _ = self.run_script({'9': served(issue)}, 'holder', '9', '--mine', '100')
                self.assertEqual((result.returncode, result.stdout), (0, expected))

    def test_every_page_is_read_in_order(self):
        # catches #1591: an open question with more than 100 comments making
        # the whole map unreadable, or a later page's claim missed or reordered.
        notes = [(1000 + i, 'Synthetic note') for i in range(99)]
        first = dict(question(9, comments=notes + [(2000, CLAIM)]))
        first['comments'] = dict(conn(first['comments']['nodes'], 102, 'c1'))
        second = served({'number': 9, 'comments': conn(
            [comment(9, 1500, CLAIM), comment(9, 1501, 'wayfind: released 1500')], 102)})
        fixture = {'1': a_map(1, [question(8), first]), '9@c1': second}
        result, reads = self.run_script(fixture, 'map', '1')
        self.assertEqual((result.returncode, result.stderr), (0, ''))
        self.assertEqual(result.stdout, '#8 frontier wayfind:grill: Synthetic question 8\n'
                                        '#9 held by 2000: Synthetic question 9\n')
        fixture['9'] = served(first)
        self.assertEqual(self.run_script(fixture, 'holder', '9', '--mine', '2000')[0].stdout, 'yours\n')
        # A map of more than 100 questions keeps the order across its pages.
        paged = {'1': a_map(1, [question(n) for n in range(10, 110)], 101, 'q1'),
                 '1@q1': a_map(1, [question(5)], 101)}
        result, _ = self.run_script(paged, 'map', '1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-2:], [
            '#109 frontier wayfind:grill: Synthetic question 109',
            '#5 frontier wayfind:grill: Synthetic question 5'])

    def test_inconsistent_pages_refuse(self):
        # catches #1591's other half: a page chain that stops short, repeats a
        # cursor or changes its total accepted as a complete read.
        def chain(total, after, second):
            return {'1': a_map(1, [question(n) for n in range(10, 110)], total, after), **second}
        cases = {
            'stops short': chain(102, 'q1', {'1@q1': a_map(1, [question(5)], 102)}),
            'repeats a cursor': chain(102, 'q1', {'1@q1': a_map(1, [question(5)], 102, 'q1')}),
            'total changes': chain(101, 'q1', {'1@q1': a_map(1, [question(5)], 102)}),
            'no cursor': chain(101, '', {}),
            'a node not an object': {'1': served(dict(question(1), labels=conn(['wayfind:grill'])))},
            'next page not a boolean': {'1': served({'number': 1, 'subIssues': dict(
                conn([question(9)]), pageInfo={'hasNextPage': 'false', 'endCursor': 'q1'})})},
        }
        for name, fixture in cases.items():
            with self.subTest(name):
                result, _ = self.run_script(fixture, 'holder' if name.startswith('a node') else 'map', '1')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertTrue(result.stderr.startswith('frontier: '), result.stderr)

if __name__ == '__main__':
    unittest.main()
