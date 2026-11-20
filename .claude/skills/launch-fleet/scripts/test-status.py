#!/usr/bin/env python3
"""P4 (#1254, revision 4): status.py on a synthetic tracker with a fake `gh`.

Run: python3 -I skills/launch-fleet/scripts/test-status.py
Every value here is synthetic. The fake gh keeps the tracker in a JSON file,
logs every call, stamps GitHub's updated_at on each comment it writes, records
who added or removed each label (the issue's events), answers GraphQL's viewer
with the acting login, and refuses what GitHub refuses (editing another
author's comment). A world can make one call fail once (`fail_once`) or leave
comment ids out of comment reads (`unlisted`), as a flaky GitHub does. Expected notes,
labels and lines come from the contract, contracts/agent-status.v1.md, never
from status.py. Ages are 5 minutes (live) or 31 to 90 minutes (lapsed) against
the real clock, far from the 30-minute edge.
"""
from datetime import datetime, timedelta, timezone
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SCRIPT = HERE / 'status.py'
CONTRACT = ROOT / 'contracts/agent-status.v1.md'
SCHEMA = ROOT / 'contracts/agent-status.v1.schema.json'
REPO = 'example/tracker'
BOT = 'openwiz[bot]'
FLEET_MD = '# Fleet settings\n\n## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n| Record authors | `openwiz[bot]`, `synthetic-owner` |\n'
MARKER = '<!-- openwiz:status v1 -->'
# The installed package supplying status.py (this checkout). Inputs name its real
# version, so a release bump never turns a good value into an invented one.
VERSION = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())['version']
SKILLS = 'build-ticket@' + VERSION

FAKE_GH = r'''
import fcntl, json, os, sys
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs, unquote
args = sys.argv[1:]
world_path = os.environ['FAKE_GH_WORLD']
# One call at a time, as GitHub settles each write: a run's command edits the world too (#1447).
lock = open(world_path + '.lock', 'w'); fcntl.flock(lock, fcntl.LOCK_EX)
world = json.load(open(world_path))
def logged(it, kind, name, login):
    # A label event as GitHub's issue events list it: who, what and when, oldest first.
    it.setdefault('events', []).append({'event': kind, 'label': {'name': name}, 'actor': {'login': login},
                                        'created_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')})
def races(key):
    # #1592: what lands at that moment, as the world names it: an agent's edit of its note,
    # or a person adding a label (an event under that person's login).
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    for rival in world.pop(key, []):
        if 'fail_once' in rival:
            world.setdefault('fail_once', []).append(rival['fail_once'])
            continue
        it = next(i for i in world['issues'] if i['number'] == rival['issue'])
        if 'edit' in rival:
            c = next(x for x in it['comments'] if x['id'] == rival['edit'])
            c.setdefault('edits', [c['body']]).append(rival['body'])
            c.setdefault('edited_at', [c['updated']]).append(stamp)
            c['body'] = rival['body']; c['updated'] = stamp
        elif 'unlabel' in rival:
            if rival['unlabel'] in it['labels']:
                it['labels'].remove(rival['unlabel'])
                logged(it, 'unlabeled', rival['unlabel'], rival['by'])
        elif rival['label'] not in it['labels']:
            it['labels'].append(rival['label'])
            logged(it, 'labeled', rival['label'], rival['by'])
if args[:2] == ['issue', 'edit']:
    # launch-fleet's fix for an asking note without needs-info: gh issue edit N --repo R --add-label L.
    n, opts = int(args[2]), dict(zip(args[3::2], args[4::2]))
    assert opts['--repo'] == world['repo'] and set(opts) == {'--repo', '--add-label'}, args
    with open(os.environ['FAKE_GH_LOG'], 'a') as log:
        log.write(json.dumps({'method': 'EDIT', 'path': 'issue %d' % n, 'body': opts['--add-label']}) + '\n')
    races('race_label')
    it = next(i for i in world['issues'] if i['number'] == n)
    if opts['--add-label'] not in it['labels']:
        it['labels'].append(opts['--add-label'])
        logged(it, 'labeled', opts['--add-label'], world['login'])
    json.dump(world, open(world_path, 'w'), indent=1, sort_keys=True)
    sys.exit(0)
assert args[0] == 'api', args
args = args[1:]
method, path, accept, body = 'GET', None, None, None
i = 0
while i < len(args):
    a = args[i]
    if a == '--method': method = args[i + 1]; i += 2
    elif a == '-H': accept = args[i + 1]; i += 2
    elif a == '--input': assert args[i + 1] == '-'; body = json.loads(sys.stdin.read()); i += 2
    else: assert path is None, args; path = a; i += 1
with open(os.environ['FAKE_GH_LOG'], 'a') as log:
    log.write(json.dumps({'method': method, 'path': path, 'body': body}) + '\n')
size = int(os.environ.get('FAKE_GH_PAGE', '100'))
def fail(code, text):
    sys.stderr.write('gh: %s (HTTP %d)\n' % (text, code)); sys.exit(1)
if method + ' ' + path in world.get('fail_once', []):
    world['fail_once'].remove(method + ' ' + path)
    json.dump(world, open(world_path, 'w'), indent=1, sort_keys=True)
    fail(502, 'Bad Gateway')
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
def out(value):
    sys.stdout.write(json.dumps(value)); sys.exit(0)
def save():
    json.dump(world, open(world_path, 'w'), indent=1, sort_keys=True)
def issue(n):
    for it in world['issues']:
        if it['number'] == int(n): return it
    fail(404, 'Not Found')
def rest(c):
    return {'id': c['id'], 'node_id': 'IC_%d' % c['id'], 'user': {'login': c['author']} if c['author'] else None,
            'body': c['body'], 'updated_at': c['updated']}
def page(items, query):
    k = int(query.get('page', ['1'])[0]); n = min(int(query.get('per_page', ['30'])[0]), size)
    return items[(k - 1) * n:k * n]
parts = urlsplit(path); query = parse_qs(parts.query)
seg = [unquote(s) for s in parts.path.split('/')]
def edit(c, text):
    # GitHub keeps a comment's edit history: its first edit records the original too. A world
    # can leave an unchanged body unrecorded, no history entry and no new updated_at (#62 R4).
    if text == c['body'] and world.get('noop_unrecorded'):
        return
    c.setdefault('edits', [c['body']]).append(text)
    c.setdefault('edited_at', [c['updated']]).append(now)
    c['body'] = text; c['updated'] = now
if path == 'graphql' and 'userContentEdits' in body['query']:
    assert method == 'POST' and 'mutation' not in body['query'], body
    for it in world['issues']:
        for c in it['comments']:
            if 'IC_%d' % c['id'] == body['variables']['id'] and not world.get('history_fails'):
                # Newest first, each node the full body of that version, as GitHub answers.
                shown = list(reversed(list(zip(c.get('edits', []), c.get('edited_at', [])))))
                shown = shown[1 if world.get('history_stale') else 0:]
                out({'data': {'node': {'userContentEdits': {'nodes': [
                    {'diff': text, 'editedAt': at} for text, at in shown][:body['variables'].get('n', 2)]}}}})
    out({'data': {'node': None}})
if path == 'graphql' and 'viewer' in body['query']:
    assert method == 'POST' and 'mutation' not in body['query'], body
    if world.get('viewer_fails'): fail(403, 'Resource not accessible by integration')
    out({'data': {'viewer': {'login': world['login']}}})
if path == 'graphql':
    assert method == 'POST' and 'mutation' not in body['query'], body
    v = body['variables']; assert v['owner'] + '/' + v['name'] == world['repo']
    open_issues = [it for it in world['issues'] if it['state'] == 'open']
    start = int(v.get('cursor') or 0)
    chunk = open_issues[start:start + size]
    answer = ({'data': {'repository': {'issues': {
        'pageInfo': {'hasNextPage': start + size < len(open_issues), 'endCursor': str(start + size)},
        'nodes': [{'number': it['number'], 'labels': {'nodes': [{'name': l} for l in it['labels']]},
                   'comments': {'pageInfo': {'hasNextPage': len(it['comments']) > size},
                                'nodes': [{'databaseId': c['id'], 'author': {'login': c['author']} if c['author'] else None,
                                           'body': c['body'], 'updatedAt': c['updated']} for c in it['comments'][:size]]},
                   'closedByPullRequestsReferences': {'nodes': it.get('prs', [])}} for it in chunk]}}}})
    # What lands once the checker has read the tracker (#1592).
    if world.get('race_after_scan'):
        races('race_after_scan'); save()
    out(answer)
assert '/'.join(seg[:3]) == 'repos/' + world['repo'], path
seg = seg[3:]
if method == 'GET' and seg == ['contents', 'docs', 'agents', 'fleet.md']:
    assert accept == 'Accept: application/vnd.github.raw'
    if world.get('fleet_md') is None: fail(404, 'Not Found')
    sys.stdout.write(world['fleet_md']); sys.exit(0)
if seg[0] == 'issues' and len(seg) == 2 and method == 'GET':
    it = issue(seg[1]); out({'number': it['number'], 'state': it['state'], 'labels': [{'name': l} for l in it['labels']]})
if seg[0] == 'issues' and seg[2:] == ['labels'] and method == 'POST':
    races('race_label')
    it = issue(seg[1])
    for l in body['labels']:
        if l not in it['labels']:
            it['labels'].append(l)
            logged(it, 'labeled', l, world['login'])
    races('race_after_label')
    save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and len(seg) == 4 and seg[2] == 'labels' and method == 'DELETE':
    races('race_delete')
    it = issue(seg[1])
    if seg[3] not in it['labels']: fail(404, 'Label does not exist')
    it['labels'].remove(seg[3])
    logged(it, 'unlabeled', seg[3], world['login'])
    save(); out([{'name': l} for l in it['labels']])
if seg[0] == 'issues' and seg[2:] == ['events'] and method == 'GET':
    it = issue(seg[1]); out(page(it.get('events', []), query))
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'GET':
    it = issue(seg[1])
    # Comments GitHub's list doesn't show yet (a read-back that lags its write).
    shown = [c for c in it['comments'] if c['id'] not in world.get('unlisted', [])]
    out(page([rest(c) for c in shown], query))
if seg[0] == 'issues' and seg[2:] == ['comments'] and method == 'POST':
    it = issue(seg[1])
    # A rival agent's note that reached GitHub a moment before this one.
    for rival in world.pop('race', []):
        world['next_id'] += 1
        it['comments'].append(dict(rival, id=world['next_id'], updated=now))
    world['next_id'] += 1
    c = {'id': world['next_id'], 'author': world['login'], 'body': body['body'], 'updated': now}
    it['comments'].append(c); save(); out(rest(c))
if seg[:2] == ['issues', 'comments'] and len(seg) == 3 and method == 'DELETE':
    for it in world['issues']:
        for c in list(it['comments']):
            if c['id'] == int(seg[2]):
                if c['author'] != world['login']: fail(403, 'Must have admin rights to Repository.')
                it['comments'].remove(c); save(); sys.exit(0)
    fail(404, 'Not Found')
if seg[:2] == ['issues', 'comments'] and len(seg) == 3 and method == 'PATCH':
    for it in world['issues']:
        for c in it['comments']:
            if c['id'] == int(seg[2]):
                if c['author'] != world['login']: fail(403, 'Must have admin rights to Repository.')
                # What reached GitHub between the writer's read and this edit: a newer note,
                # or a sibling wake's edit of this same note.
                for rival in world.pop('race_edit', []):
                    if 'edit' in rival:
                        edit(next(x for x in it['comments'] if x['id'] == rival['edit']), rival['body'])
                    else:
                        world['next_id'] += 1
                        it['comments'].append(dict(rival, id=world['next_id'], updated=now))
                edit(c, body['body']); answer = rest(c)
                # What lands after this edit and before the writer reads back: a sibling's edit.
                for rival in world.pop('race_after_edit', []):
                    edit(next(x for x in it['comments'] if x['id'] == rival['edit']), rival['body'])
                save(); out(answer)
    fail(404, 'Not Found')
fail(404, 'Not Found: ' + method + ' ' + path)
'''


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime('%Y-%m-%dT%H:%M:%SZ')


def note(agent='builder', state='working', step='started the build', time='2030-01-02T03:00:00Z',
         pr=None, preview=None, harness='Claude Code', model='Opus 5.5 Medium', skills=SKILLS):
    """The text form the contract fixes, key by key."""
    lines = [MARKER, 'agent: ' + agent, 'state: ' + state, 'harness: ' + harness, 'model: ' + model,
             'skills: ' + skills, 'step: ' + step, 'time: ' + time]
    lines += ['pr: ' + pr] if pr else []
    lines += ['preview: ' + preview] if preview else []
    return '\n'.join(lines)


def comment(cid, author, body, minutes=5):
    return {'id': cid, 'author': author, 'body': body, 'updated': ago(minutes)}


def contract_example():
    text = CONTRACT.read_text()
    section = text.split('Example (synthetic):\n\n```text\n', 1)[1]
    # The example names the package version of its day; the writer names the installed one.
    return re.sub(r'(?m)^skills: build-ticket@[0-9.]+$', 'skills: ' + SKILLS, section.split('\n```', 1)[0])


class Tracker(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        (self.dir / 'bin').mkdir()
        (self.dir / 'gh.py').write_text(FAKE_GH)
        gh = self.dir / 'bin' / 'gh'
        gh.write_text('#!/bin/sh\nexec ' + sys.executable + ' -I -S ' + str(self.dir / 'gh.py') + ' "$@"\n')
        gh.chmod(0o755)
        self.world = {
            'repo': REPO, 'login': BOT, 'fleet_md': FLEET_MD, 'next_id': 9000,
            'issues': [{'number': 12, 'state': 'open', 'labels': ['ready-for-agent'], 'comments': [
                comment(101, 'synthetic-owner', 'launch-fleet: started'),
                # Anyone may comment on a public ticket: a planted marker is not a note.
                comment(102, 'synthetic-outsider', note()),
                comment(103, None, note()),
            ]}],
        }
        self.page = '100'

    def save(self):
        (self.dir / 'world.json').write_text(json.dumps(self.world))

    def load(self):
        return json.loads((self.dir / 'world.json').read_text())

    def calls(self):
        log = self.dir / 'gh.log'
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def writes(self):
        return [(c['method'], c['path']) for c in self.calls() if c['method'] != 'GET' and c['path'] != 'graphql']

    def run_status(self, *args):
        env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
                   FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   FAKE_GH_PAGE=self.page)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_REPO'):
            env.pop(key, None)
        return subprocess.run([sys.executable, '-I', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=60)

    def write(self, state, step, time, *extra, agent='builder'):
        return self.run_status('write', '--repo', REPO, '--ticket', '12', '--agent', agent, '--state', state,
                               '--harness', 'Claude Code', '--model', 'Opus 5.5 Medium',
                               '--skills', SKILLS, '--step', step, '--time', time, *extra)

    def ticket(self, world=None):
        return next(it for it in (world or self.load())['issues'] if it['number'] == 12)


class Write(Tracker):
    def test_second_run_edits_the_one_note_and_asking_sets_then_clears_needs_info(self):
        # catches: a second run posting another note, the skills the agent passed not written
        # as given, a stranger's planted marker taken as the agent's note, asking without needs-info, needs-info left after asking, or any
        # building or in-review label written.
        self.save()
        first = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((first.returncode, first.stdout, first.stderr),
                         (0, '#12: builder working, status note 9001 posted\n', ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.assertEqual(self.ticket()['comments'][3]['body'], note())

        asking = self.write('asking', 'asked which file to change', '2030-01-02T04:00:00Z', '--note', '9001')
        self.assertEqual((asking.returncode, asking.stdout, asking.stderr),
                         (0, '#12: builder asking, status note 9001 edited\n', ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

        pr = 'https://github.com/example/skills/pull/31'
        back = self.write('working', 'handed back; CI is green', '2030-01-02T05:00:00Z', '--note', '9001',
                          '--pr', pr, '--preview', 'https://31.example-site.pages.dev',
                          '--skills', f'build-ticket@{VERSION}, diagnose@{VERSION}')
        self.assertEqual((back.returncode, back.stdout), (0, '#12: builder working, status note 9001 edited\n'))
        world = self.load()
        self.assertEqual(self.ticket(world)['labels'], ['ready-for-agent'])
        self.assertEqual([c['id'] for c in self.ticket(world)['comments']], [101, 102, 103, 9001])
        self.assertEqual(self.ticket(world)['comments'][1]['body'], note())
        self.assertEqual(self.ticket(world)['comments'][3]['body'],
                         note(step='handed back; CI is green', time='2030-01-02T05:00:00Z', pr=pr,
                              preview='https://31.example-site.pages.dev', skills=f'build-ticket@{VERSION}, diagnose@{VERSION}'))
        self.assertEqual(self.writes(), [
            ('POST', 'repos/example/tracker/issues/12/comments'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
            ('POST', 'repos/example/tracker/issues/12/labels'),
            ('PATCH', 'repos/example/tracker/issues/comments/9001'),
            ('DELETE', 'repos/example/tracker/issues/12/labels/needs-info'),
        ])
        self.assertEqual([c['body'] for c in self.calls() if c['path'].endswith('/12/labels')], [{'labels': ['needs-info']}])

    def test_leaving_asking_keeps_a_needs_info_it_did_not_set(self):
        # catches: an agent leaving asking clearing a needs-info a person set, or any other
        # human-owned label touched.
        self.ticket(self.world)['labels'] = ['ready-for-agent', 'needs-info', 'held']
        self.ticket(self.world)['events'] = [
            {'event': 'labeled', 'label': {'name': 'needs-info'}, 'actor': {'login': BOT}},
            {'event': 'unlabeled', 'label': {'name': 'needs-info'}, 'actor': {'login': BOT}},
            {'event': 'labeled', 'label': {'name': 'needs-info'}, 'actor': {'login': 'synthetic-owner'}},
            {'event': 'labeled', 'label': {'name': 'held'}, 'actor': {'login': BOT}}]
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(state='asking')))
        self.save()
        done = self.write('done', 'merged', '2030-01-02T06:00:00Z', '--note', '104')
        self.assertEqual((done.returncode, done.stdout), (0, '#12: builder done, status note 104 edited\n'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info', 'held'])
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')])

    def test_needs_info_stays_while_any_agent_asks_and_a_failed_clear_recovers(self):
        # catches (R1): one agent leaving asking clearing the label another live agent's
        # question needs, or a failed label write that a retry or check never repairs.
        ticket = self.ticket(self.world)
        ticket['labels'] = ['ready-for-agent', 'needs-info']
        ticket['events'] = [{'event': 'labeled', 'label': {'name': 'needs-info'}, 'actor': {'login': BOT}}]
        ticket['comments'] += [comment(104, BOT, note(state='asking')),
                               comment(105, BOT, note(agent='reviewer', state='asking'))]
        self.save()
        builder = self.write('working', 'got the answer', '2030-01-02T04:00:00Z', '--note', '104')
        self.assertEqual((builder.returncode, builder.stdout), (0, '#12: builder working, status note 104 edited\n'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

        world = self.load()
        world['fail_once'] = ['DELETE repos/example/tracker/issues/12/labels/needs-info']
        self.world = world
        self.save()
        failed = self.write('done', 'reviewed', '2030-01-02T05:00:00Z', '--note', '105', agent='reviewer')
        self.assertEqual((failed.returncode, failed.stdout), (2, ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        retry = self.write('done', 'reviewed', '2030-01-02T05:00:00Z', '--note', '105', agent='reviewer')
        self.assertEqual((retry.returncode, retry.stdout), (0, '#12: reviewer done, status note 105 edited\n'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])

        world = self.load()
        world['fail_once'] = ['POST repos/example/tracker/issues/12/labels']
        self.world = world
        self.save()
        failed = self.write('asking', 'asked again', '2030-01-02T06:00:00Z', '--note', '104')
        self.assertEqual((failed.returncode, failed.stdout), (2, ''))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        retry = self.write('asking', 'asked again', '2030-01-02T06:00:00Z', '--note', '104')
        self.assertEqual(retry.returncode, 0, retry.stderr)
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        check = self.run_status('check', '--repo', REPO)
        self.assertEqual((check.returncode, check.stdout), (0, ''))

    def test_an_untrusted_posting_identity_never_counts_as_written(self):
        # catches (R4): a writable login outside the record authors posting a note the app
        # ignores, labelling the ticket, or reporting success; or a note GitHub doesn't
        # list back counted as written.
        self.world['login'] = 'synthetic-unlisted'
        self.save()
        refused = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z')
        self.assertEqual((refused.returncode, refused.stdout, self.writes()), (2, '', []))
        self.assertIn('not a record author', refused.stderr)
        self.assertEqual(self.load(), self.world)

        # Where the token can't name itself (an App), the posted note's author decides.
        self.world['viewer_fails'] = True
        self.save()
        (self.dir / 'gh.log').unlink()
        removed = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z')
        self.assertEqual((removed.returncode, removed.stdout), (2, ''))
        self.assertIn('not a record author', removed.stderr)
        self.assertEqual(self.writes(), [('POST', 'repos/example/tracker/issues/12/comments'),
                                         ('DELETE', 'repos/example/tracker/issues/comments/9001')])
        self.assertEqual([c['id'] for c in self.ticket()['comments']], [101, 102, 103])
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])

        self.world['login'] = BOT
        self.save()
        app = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((app.returncode, app.stdout), (0, '#12: builder working, status note 9001 posted\n'))

        self.world['viewer_fails'] = False
        self.world['unlisted'] = [9001]
        self.save()
        unread = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z')
        self.assertEqual((unread.returncode, unread.stdout), (2, ''))
        self.assertIn('note 9001 was posted but not read back', unread.stderr)
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])

    def test_a_note_past_the_first_page_is_found(self):
        # catches: reading only the first page of comments, so a claim or the agent's own note is missed.
        self.ticket(self.world)['comments'] += [comment(104, 'synthetic-owner', 'note'),
                                                comment(105, BOT, note(state='working')),
                                                comment(106, BOT, note(agent='fleet'))]
        self.save()
        self.page = '2'
        edit = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z', '--note', '105')
        self.assertEqual((edit.returncode, edit.stdout), (0, '#12: builder asking, status note 105 edited\n'))
        claim = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
        self.assertEqual((claim.returncode, claim.stdout), (3, ''))
        self.assertIn('note 105 holds the builder claim', claim.stderr)
        self.assertEqual([c['id'] for c in self.ticket()['comments']], [101, 102, 103, 104, 105, 106])

    def test_the_contract_example_is_what_the_writer_writes(self):
        # catches: the writer's text drifting from the contract the app parses.
        self.save()
        result = self.write('working', 'opened the pull request; CI is running', '2030-01-02T03:04:05Z',
                            '--pr', 'https://github.com/example/site/pull/42',
                            '--preview', 'https://42.example-site.pages.dev')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ticket()['comments'][-1]['body'], contract_example())

    def test_no_record_authors_refuses_before_any_write(self):
        # catches: a writer that trusts every commenter when the record authors can't be read.
        for fleet_md in (None, '# Fleet settings\n', FLEET_MD.replace('`openwiz[bot]`, `synthetic-owner`', '')):
            with self.subTest(fleet_md=fleet_md):
                self.world['fleet_md'] = fleet_md
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertIn('record authors', result.stderr)
                self.assertEqual([c['method'] for c in self.calls()], ['GET'])
                self.assertEqual(self.load(), self.world)


class Claims(Tracker):
    def test_the_oldest_live_note_of_a_kind_holds_the_claim(self):
        # catches: a second builder claiming a ticket another builder holds, a lapsed or
        # stopped note still blocking, another kind's note blocking a builder, or a note
        # without a well-formed skills line read as a claim.
        cases = [
            ('a live builder note blocks', [comment(104, BOT, note())], 3),
            ('an asking builder note blocks', [comment(104, 'Synthetic-Owner', note(state='asking'))], 3),
            ('a lapsed builder note does not', [comment(104, BOT, note(), minutes=31)], 0),
            ('a stopped builder note does not', [comment(104, BOT, note(state='stopped (lease expired)'))], 0),
            ('a done builder note does not', [comment(104, BOT, note(state='done'))], 0),
            ('a live fleet note does not', [comment(104, BOT, note(agent='fleet'))], 0),
            ('an unreadable note does not', [comment(104, BOT, MARKER + '\nagent: builder')], 0),
            ('a note without skills does not', [comment(104, BOT, note().replace('skills: ' + SKILLS + '\n', ''))], 0),
            ('a note with a bad skills line does not', [comment(104, BOT, note(skills='build-ticket'))], 0),
        ]
        base = json.loads(json.dumps(self.world))
        for name, planted, code in cases:
            with self.subTest(name):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'] += planted
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('working', 'started the build', '2030-01-02T03:00:00Z')
                self.assertEqual(result.returncode, code, result.stderr)
                if code:
                    self.assertEqual((result.stdout, self.writes()), ('', []))
                    self.assertEqual(self.load(), self.world)
                else:
                    self.assertEqual(self.writes(), [('POST', 'repos/example/tracker/issues/12/comments')])

    def test_the_fence_stops_a_writer_whose_note_is_no_longer_live(self):
        # catches: an agent writing on after its claim was stopped, lost or taken by another kind,
        # or a lapsed note reviving over the live note that replaced it (R2).
        cases = [
            ('stopped by the fleet', [comment(104, BOT, note(state='stopped (lease expired)'))], '104'),
            ('an older live claim', [comment(104, BOT, note()), comment(105, BOT, note())], '105'),
            ('gone', [], '104'),
            ('not a record author', [comment(104, 'synthetic-outsider', note())], '104'),
            ('another kind', [comment(104, BOT, note(agent='reviewer'))], '104'),
            ('not a note', [comment(104, BOT, 'launch-fleet: started')], '104'),
        ]
        base = json.loads(json.dumps(self.world))
        for name, planted, own in cases:
            with self.subTest(name):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'] += planted
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z', '--note', own)
                self.assertEqual((result.returncode, result.stdout), (3, ''))
                self.assertRegex(result.stderr, r'^status\.py: stop: ')
                self.assertEqual(self.writes(), [])
                self.assertEqual(self.load(), self.world)
        # R2: a lapsed note can't come back over the live note that replaced it, newer or not.
        self.world = json.loads(json.dumps(base))
        self.ticket(self.world)['comments'] += [comment(104, BOT, note(), minutes=90), comment(105, BOT, note())]
        self.save()
        (self.dir / 'gh.log').unlink(missing_ok=True)
        back = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((back.returncode, back.stdout, self.writes()), (3, '', []))
        self.assertIn('note 105 holds the builder claim', back.stderr)
        holder = self.write('working', 'pushed a fix', '2030-01-02T03:10:00Z', '--note', '105')
        self.assertEqual((holder.returncode, holder.stdout), (0, '#12: builder working, status note 105 edited\n'))
        # A lapsed note that nobody took over is still its agent's: an edit revives it.
        self.world = json.loads(json.dumps(base))
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(), minutes=90))
        self.save()
        revived = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((revived.returncode, revived.stdout), (0, '#12: builder working, status note 104 edited\n'))

    def test_a_writer_that_loses_the_race_stops_its_own_note(self):
        # catches: two builders both keeping a claim when their notes reach GitHub together.
        self.ticket(self.world)['labels'] = ['ready-for-agent']
        self.world['race'] = [{'author': BOT, 'body': note(step='a rival started')}]
        self.save()
        result = self.write('asking', 'asked a question', '2030-01-02T03:00:00Z')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertIn('note 9001 holds the builder claim', result.stderr)
        comments = self.ticket()['comments']
        self.assertEqual([c['id'] for c in comments], [101, 102, 103, 9001, 9002])
        self.assertEqual(comments[4]['body'], note(state='stopped (lost claim)', step='asked a question'))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.assertEqual(self.writes(), [('POST', 'repos/example/tracker/issues/12/comments'),
                                         ('PATCH', 'repos/example/tracker/issues/comments/9002')])



class EditRace(Tracker):
    """#1441: KN10's finding on the edit path, which re-read before but never after its write."""

    def test_a_lapsed_note_whose_edit_lands_after_a_newer_claim_steps_down(self):
        # catches: a lapsed builder's edit landing after a newer builder claimed and read back,
        # so the lapsed note holds again as the oldest (P2), two notes stay live (P4) and the
        # newer builder's succeeded claim no longer holds (P1).
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(), minutes=90))
        self.world['race_edit'] = [{'author': BOT, 'body': note(step='a newer builder claimed')}]
        self.save()
        result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertIn('note 9001 holds the builder claim; note 104 is stopped (lost claim)', result.stderr)
        comments = {c['id']: c['body'] for c in self.ticket()['comments']}
        self.assertEqual(comments[104], note(state='stopped (lost claim)', step='CI finished'))
        self.assertEqual(comments[9001], note(step='a newer builder claimed'))
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')] * 2)

    def test_an_edit_that_lands_over_a_sibling_release_puts_the_release_back(self):
        # catches: two overlapping wakes of one agent, where the one that read working edits
        # after its sibling released the note, and the release is lost (P3). A wake that read
        # its note done may still resume it (FleetRun's builder answering a review).
        base = json.loads(json.dumps(self.world))
        for final in ('done', 'stopped (lease expired)'):
            with self.subTest(final):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
                released = note(state=final, step='the sibling wake released it')
                self.world['race_edit'] = [{'edit': 104, 'body': released}]
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
                self.assertEqual((result.returncode, result.stdout), (3, ''))
                self.assertIn('note 104 was ' + final.split(' ')[0] + ' before this edit landed', result.stderr)
                self.assertEqual(self.ticket()['comments'][-1]['body'], released)
                self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')] * 2)

    def test_a_lost_release_is_put_back_even_when_a_later_edit_changed_the_note(self):
        # catches: a release lost for good when the read-back fails because a sibling wake,
        # reading the stale working note, edited it again before this wake read back (#1463 R1).
        self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
        released = note(state='done', step='the sibling wake handed back')
        self.world['race_edit'] = [{'edit': 104, 'body': released}]
        self.world['race_after_edit'] = [{'edit': 104, 'body': note(state='asking', step='the sibling asked')}]
        self.save()
        result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertIn('note 104 was done before this edit landed', result.stderr)
        self.assertEqual(self.ticket()['comments'][-1]['body'], released)
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')] * 2)

    def test_a_retry_after_an_unread_history_still_puts_the_release_back(self):
        # catches: a re-run of the same write (as exit 2 asks) whose edit sits on its own first
        # try, so the sibling's release under that try is skipped and lost (#57 review).
        self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
        released = note(state='done', step='the sibling wake handed back')
        self.world['race_edit'] = [{'edit': 104, 'body': released}]
        self.world['history_fails'] = True
        self.save()
        # The writer stamps time when it starts, before its read: here a minute before the release.
        first = self.write('working', 'CI finished', ago(1), '--note', '104')
        self.assertEqual((first.returncode, first.stdout), (2, ''))
        world = self.load()
        world['history_fails'] = False
        (self.dir / 'world.json').write_text(json.dumps(world))
        again = self.write('working', 'CI finished', ago(0), '--note', '104')
        self.assertEqual((again.returncode, again.stdout), (3, ''))
        self.assertIn('note 104 was done before this edit landed', again.stderr)
        self.assertEqual(self.ticket()['comments'][-1]['body'], released)

    def test_a_resumed_done_note_written_again_holds(self):
        # catches: the retry skip walking past this agent's own resume of a done note it read,
        # so writing the same step again (or re-running after exit 2) puts the done back and
        # exits 3, which stops build-ticket's fix round (#57 R1).
        base = json.loads(json.dumps(self.world))
        handed = note(state='done', step='handed back', pr='https://github.com/example/tracker/pull/31')
        for name in ('the same step again', 'a retry after exit 2'):
            with self.subTest(name):
                self.world = json.loads(json.dumps(base))
                self.ticket(self.world)['comments'].append(comment(104, BOT, handed))
                self.world['history_fails'] = name == 'a retry after exit 2'
                self.save()
                first = self.write('working', 'fixing review findings', ago(0), '--note', '104')
                self.assertEqual(first.returncode, 2 if self.world['history_fails'] else 0, first.stderr)
                world = self.load()
                world['history_fails'] = False
                (self.dir / 'world.json').write_text(json.dumps(world))
                again = self.write('working', 'fixing review findings', ago(0), '--note', '104')
                self.assertEqual((again.returncode, again.stdout),
                                 (0, '#12: builder working, status note 104 edited\n'), again.stderr)
                self.assertIn('state: working', self.ticket()['comments'][-1]['body'])

    def test_an_edit_steps_down_for_an_older_note_that_came_back_live(self):
        # catches: an edit read-back that steps down only for a newer note, leaving two live
        # notes when an older lapsed one was revived between this writer's read and its edit.
        self.ticket(self.world)['comments'] += [comment(104, BOT, note(step='a rival started'), minutes=90),
                                                comment(105, BOT, note())]
        self.world['race_edit'] = [{'edit': 104, 'body': note(step='the rival came back')}]
        self.save()
        result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '105')
        self.assertEqual((result.returncode, result.stdout), (3, ''))
        self.assertIn('note 104 holds the builder claim; note 105 is stopped (lost claim)', result.stderr)
        self.assertEqual(self.ticket()['comments'][-1]['body'], note(state='stopped (lost claim)', step='CI finished'))

    def test_an_edit_missing_from_its_history_fails(self):
        # catches: a read-back that trusts an edit history not yet holding this edit, and so
        # judges the wrong version as the one it replaced.
        self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
        self.world['history_stale'] = True
        self.save()
        result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn('note 104 was edited but its edit history does not hold the edit', result.stderr)
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')])

    def test_an_edit_whose_history_cannot_be_read_fails_closed(self):
        # catches: a claim edit reported written when the writer never saw what it replaced,
        # so a sibling's release could be lost without a word.
        self.ticket(self.world)['comments'].append(comment(104, BOT, note()))
        self.world['history_fails'] = True
        self.save()
        result = self.write('working', 'CI finished', '2030-01-02T03:00:00Z', '--note', '104')
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn('note 104 was edited but its edit history was not read', result.stderr)
        self.assertEqual(self.writes(), [('PATCH', 'repos/example/tracker/issues/comments/104')])


# Each value is refused before any call (exit 2, no gh call). A field's flag and a value.
PRIVATE = [
    ('--step', 'resumed thread thr_synbuilder1'),
    ('--step', 'ran it in /home/synthetic-dev/openwiz'),
    ('--model', 'Opus /Users/example/x'),
    ('--step', 'saved to ~/work/notes'),
    ('--step', r'copied C:\Users\example\x'),
    ('--step', 'logs in /tmp/synthetic-run'),
    ('--step', 'on /code/synthetic-repo'),
    # R3: an ordinary absolute path outside the old prefix list, and its other forms.
    ('--step', 'edited /etc/openwiz/config.toml'),
    ('--step', 'read /srv2/synthetic/settings.json'),
    ('--harness', 'Codex in $HOME/work'),
    ('--step', 'saved under ${HOME}/notes'),
    ('--step', r'saved under %USERPROFILE%\notes'),
    ('--step', r'copied from \\synthetic-server\share\x'),
    ('--step', 'opened file:///synthetic/x'),
    ('--harness', 'Codex on mch_synbox1'),
    ('--step', 'project prj_synfleet1'),
    ('--preview', 'https://example.invalid/thr_synpreview1'),
    ('--why', 'thread thr_synbuilder1 ended'),
    ('--skills', SKILLS + ', /home/synthetic-dev/skills/grill'),
    ('--skills', '~/skills/' + SKILLS),
    ('--skills', SKILLS + ', thr_synbuilder1'),
    ('--skills', '"' + SKILLS + '"'),
    # R3: credentials in any field, and in a preview link's path.
    ('--step', 'deployed with token=synthetic-value'),
    ('--step', 'set password: synthetic-value'),
    ('--step', 'used key AKIAIOSFODNN7EXAMPLE'),
    ('--step', 'sent Authorization: Bearer synthetic.value.123'),
    ('--preview', 'https://preview.example-site.pages.dev/s/sig=synthetic'),
    ('--step', 'Robin said "ship it"'),
    ('--step', 'Robin said \u201cship it\u201d'),
    ('--step', '> ship it'),
]
# The most skills that fit in 300 characters, and one more.
FITS = (300 + 2) // (len(SKILLS) + 2)
# Shape refusals: the schema refuses them too.
BAD_SHAPE = [
    ('--agent', 'helper'),
    ('--state', 'building'),
    ('--state', 'in-review'),
    ('--why', 'two (parts)'),
    ('--why', 'w' * 101),
    ('--step', ''),
    ('--step', 'two\nlines'),
    ('--step', 'tab\there'),
    ('--step', 'x' * 301),
    ('--model', 'm' * 61),
    ('--skills', 'build-ticket'),
    ('--skills', 'build-ticket@0.1'),
    ('--skills', 'build-ticket@v' + VERSION),
    ('--skills', 'Build-Ticket@' + VERSION),
    ('--skills', 'build_ticket@' + VERSION),
    ('--skills', SKILLS + ',review-ticket@' + VERSION),
    ('--skills', SKILLS + ', '),
    ('--skills', 'skills/' + SKILLS),
    ('--skills', 'https://github.com/example/skills@' + VERSION),
    ('--skills', ', '.join([SKILLS] * (FITS + 1))),
    ('--time', '2030-01-02 03:00:00'),
    ('--pr', 'https://github.com/example/skills/issues/31'),
    ('--pr', '#31'),
    ('--preview', 'javascript:alert(1)'),
    ('--preview', 'http://31.example-site.pages.dev'),
    ('--preview', 'https://example.invalid/<script>'),
    # R3: a preview link is a public https page with no credentials, query or fragment.
    ('--preview', 'https://synthetic:secret@31.example-site.pages.dev/app'),
    ('--preview', 'https://synthetic-token@31.example-site.pages.dev/app'),
    ('--preview', 'https://31.example-site.pages.dev/app?token=synthetic'),
    ('--preview', 'https://31.example-site.pages.dev/app?x=1'),
    ('--preview', 'https://31.example-site.pages.dev/app#access_token=synthetic'),
    ('--preview', 'https://localhost:8788/app'),
    ('--preview', 'https://127.0.0.1/app'),
    ('--preview', 'https://preview.synthetic.internal/app'),
    ('--preview', 'https://synthetic-box.local/app'),
]
GOOD_SHAPE = [
    ('--agent', 'reviewer'),
    ('--state', 'done'),
    ('--why', 'lease expired'),
    ('--step', 'x' * 300),
    ('--model', 'm' * 60),
    ('--skills', f'build-ticket@{VERSION}, review-ticket@{VERSION}'),
    ('--skills', ', '.join([SKILLS] * FITS)),
    ('--step', 'checked https://github.com/acme/home/pull/1 and a/home/b'),
    ('--step', 'changed skills/launch-fleet/scripts/status.py and/or its test'),
    ('--pr', 'https://github.com/example/skills/pull/31'),
    ('--preview', 'https://31.example-site.pages.dev/app/agents'),
    ('--preview', 'https://31.example-site.pages.dev:8443/'),
]
# R5: well-formed (the schema takes them) but not what the installed package holds.
UNBOUND = [
    'made-up-skill@' + VERSION,
    'build-ticket@9.9.9',
    f'build-ticket@{VERSION}, launch-fleet@10.20.30',
    'build-ticket@' + VERSION + '0',
]
FIELD = {'--agent': 'agent', '--state': 'state', '--why': 'state', '--harness': 'harness', '--model': 'model',
         '--skills': 'skills',
         '--step': 'step', '--time': 'time', '--pr': 'pr', '--preview': 'preview'}


def valid(schema, node, value):
    """The subset of JSON Schema 2020-12 the status schema uses."""
    if '$ref' in node:
        if not valid(schema, schema['$defs'][node['$ref'].split('/')[-1]], value):
            return False
    if node.get('type') == 'object':
        if not isinstance(value, dict) or set(node['required']) - set(value):
            return False
        if node.get('additionalProperties') is False and set(value) - set(node['properties']):
            return False
        return all(valid(schema, node['properties'][k], v) for k, v in value.items())
    if node.get('type') == 'string' and not isinstance(value, str):
        return False
    if 'enum' in node and value not in node['enum']:
        return False
    if 'minLength' in node and len(value) < node['minLength']:
        return False
    if 'maxLength' in node and len(value) > node['maxLength']:
        return False
    return 'pattern' not in node or re.search(node['pattern'], value) is not None


class Refuse(Tracker):
    def args(self, flag, value):
        values = {'--agent': 'builder', '--state': 'working', '--harness': 'Claude Code',
                  '--model': 'Opus 5.5 Medium', '--skills': SKILLS, '--step': 'started the build',
                  '--time': '2030-01-02T03:00:00Z'}
        if flag == '--why':
            values['--state'] = 'stopped'
        if value is None:
            del values[flag]
        else:
            values[flag] = value
        args = ['write', '--repo', REPO, '--ticket', '12']
        for key, item in values.items():
            args += [key, item]
        return args

    def test_reported_skills_are_bound_to_the_installed_package(self):
        # catches (R5): a mistyped skill or an invented release written as if the agent ran it.
        schema = json.loads(SCHEMA.read_text())
        manifest = json.loads((ROOT / '.claude-plugin/plugin.json').read_text())
        self.assertIn('./skills/build-ticket', manifest['skills'])
        self.save()
        for value in UNBOUND:
            with self.subTest(skills=value):
                # Well-formed, so only the package evidence can refuse it.
                self.assertTrue(valid(schema, schema['properties']['skills'], value))
                result = self.run_status(*self.args('--skills', value))
                self.assertEqual((result.returncode, result.stdout, self.calls()), (2, '', []))
                self.assertIn('installed package', result.stderr)
        listed = sorted(path.rsplit('/', 1)[1] for path in manifest['skills'])
        result = self.run_status(*self.args('--skills', ', '.join(f'{name}@{VERSION}' for name in listed[:5])))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_or_bad_text_is_refused_before_any_call(self):
        # catches: a thread id, machine path (any absolute one), CloudRoom id, credential,
        # quoted words or a bad shape reaching the public note (in any field, skills and
        # preview included), a note written with no skills line, or a refusal after a call.
        self.save()
        for flag, value in PRIVATE + BAD_SHAPE:
            with self.subTest(flag=flag, value=value):
                # Each value on a fresh tracker, so one leak can't hide or fake another.
                self.save()
                (self.dir / 'gh.log').unlink(missing_ok=True)
                result = self.run_status(*self.args(flag, value))
                self.assertEqual((result.returncode, result.stdout), (2, ''))
                self.assertRegex(result.stderr, r'^status\.py: refused: ' + FIELD[flag] + r': ')
                if value:
                    self.assertNotIn(value, result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.load(), self.world)
        missing = self.run_status(*self.args('--skills', None))
        self.assertEqual((missing.returncode, missing.stdout, self.calls()), (2, '', []))
        self.assertRegex(missing.stderr, r'^status\.py: refused: skills: missing')
        why = self.run_status(*self.args('--state', 'working') + ['--why', 'lease expired'])
        self.assertEqual((why.returncode, why.stdout, self.calls()), (2, '', []))
        self.assertRegex(why.stderr, r'^status\.py: refused: state: ')

    def test_the_schema_and_the_writer_agree_on_each_shape(self):
        # catches: the schema the app validates with and the writer accepting different values.
        schema = json.loads(SCHEMA.read_text())
        base = {'agent': 'builder', 'state': 'working', 'harness': 'Claude Code', 'model': 'Opus 5.5 Medium',
                'skills': SKILLS, 'step': 'started the build', 'time': '2030-01-02T03:00:00Z'}
        self.assertTrue(valid(schema, schema, base))
        for flag, value, good in [(f, v, False) for f, v in BAD_SHAPE] + [(f, v, True) for f, v in GOOD_SHAPE]:
            with self.subTest(flag=flag, value=value):
                self.save()
                result = self.run_status(*self.args(flag, value))
                self.assertEqual(result.returncode == 0, good, result.stderr)
                field = dict(base, state='stopped (%s)' % value) if flag == '--why' else dict(base, **{FIELD[flag]: value})
                self.assertEqual(valid(schema, schema, field), good)
        self.assertFalse(valid(schema, schema, {k: v for k, v in base.items() if k != 'skills'}))
        self.assertEqual(schema['$defs']['label']['enum'], ['spec', 'ready-for-agent', 'ready-for-human', 'needs-info', 'held'])
        self.assertEqual(schema['$defs']['state']['enum'], ['working', 'asking', 'done', 'stopped'])


class Check(Tracker):
    def test_check_lists_each_planted_mismatch_and_changes_nothing(self):
        # catches: a note GitHub contradicts or a lapsed claim the wake misses, a closed
        # ticket, a stranger's note or a finished note reported, a page skipped, or a write.
        def pr(n, state):
            return {'number': n, 'state': state, 'url': 'https://github.com/example/skills/pull/%d' % n}
        def it(n, comments, labels=('ready-for-agent',), prs=(), state='open'):
            return {'number': n, 'state': state, 'labels': list(labels), 'comments': comments, 'prs': list(prs)}
        self.world['issues'] = [
            it(20, [comment(201, BOT, note())], prs=[pr(30, 'CLOSED'), pr(31, 'MERGED')]),
            it(21, [comment(211, BOT, note(state='asking'), minutes=45)], labels=['ready-for-agent', 'needs-info']),
            it(22, [comment(221, BOT, note(state='asking'))]),
            it(23, [comment(231, BOT, note()), comment(232, BOT, note(agent='fleet')), comment(233, BOT, note())]),
            it(24, [comment(241, BOT, note(state='done'))], prs=[pr(34, 'MERGED')]),
            it(25, [comment(251, 'synthetic-outsider', note())], prs=[pr(35, 'MERGED')]),
            it(26, [comment(261, BOT, note(state='stopped (lease expired)'), minutes=90),
                    comment(262, BOT, note(state='asking'))], labels=['needs-info', 'held'], prs=[pr(36, 'OPEN')]),
            it(27, [comment(271, BOT, note())], prs=[pr(37, 'MERGED')], state='closed'),
            it(28, [comment(281, 'synthetic-owner', 'plain'), comment(282, BOT, 'plain'),
                    comment(283, BOT, note(agent='reviewer'), minutes=60)]),
        ]
        self.save()
        self.page = '2'
        before = (self.dir / 'world.json').read_bytes()
        result = self.run_status('check', '--repo', REPO)
        self.assertEqual((result.returncode, result.stderr), (1, ''))
        self.assertEqual(result.stdout,
                         '#20 note 201 builder working: pull request https://github.com/example/skills/pull/31 merged\n'
                         '#21 note 211 builder asking: lapsed, no edit for 30 minutes\n'
                         '#22 note 221 builder asking: no needs-info label\n'
                         '#23 note 233 builder working: note 231 holds the builder claim\n'
                         '#28 note 283 reviewer working: lapsed, no edit for 30 minutes\n')
        self.assertEqual((self.dir / 'world.json').read_bytes(), before)
        self.assertEqual({c['method'] for c in self.calls()}, {'GET', 'POST'})
        self.assertEqual({c['path'] for c in self.calls() if c['method'] == 'POST'}, {'graphql'})
        self.assertIn(('GET', 'repos/example/tracker/issues/28/comments?per_page=100&page=1'),
                      [(c['method'], c['path']) for c in self.calls()])

        self.world['issues'] = [it(24, [comment(241, BOT, note(state='done'))], prs=[pr(34, 'MERGED')]),
                                it(29, [], labels=['needs-info'])]
        self.save()
        clean = self.run_status('check', '--repo', REPO)
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, '', ''))

    def test_check_that_cannot_read_says_so(self):
        # catches: a failed read reported as "no mismatch".
        self.world['repo'] = 'example/other'
        self.save()
        result = self.run_status('check', '--repo', REPO)
        self.assertEqual((result.returncode, result.stdout), (2, ''))
        self.assertIn('could not read', result.stderr)



SKILLS_DIR = ROOT / 'skills'
# launch-fleet's status step, filled as the fleet fills it (#1592).
FLEET = {'<owner>/<repo>': REPO, '<harness>': 'Codex', '<model>': 'Sol 6.1 High', '<skills>': 'launch-fleet@' + VERSION}
LABELS = {'ready-for-agent', 'needs-info'}


def span(skill, pattern):
    """The one code span in SKILL.md matching PATTERN, or None."""
    found = re.findall(pattern, (SKILLS_DIR / skill / 'SKILL.md').read_text())
    return found[0] if len(found) == 1 else None


def filled(skill, text, values):
    """A skill's command with its placeholders filled and quoted, as a shell then reads it."""
    text = text.replace("<this skill's folder>", shlex.quote(str(SKILLS_DIR / skill)))
    for name, value in values.items():
        text = text.replace(name, shlex.quote(value))
    argv = shlex.split(text)
    assert argv[:2] == ['python3', '-I'] or argv[0] == 'gh', argv
    return [sys.executable] + argv[1:] if argv[0] == 'python3' else argv


class FleetRun(Tracker):
    """P4 (#1255): the status lines in build-ticket, review-ticket and launch-fleet, run as written."""

    def command(self, skill, kind):
        """The skill's status write, filled for one step: (state, step, *extra) -> argv."""
        base = span(skill, r'`(python3 -I [^`]*status\.py write [^`]*)`')
        self.assertIsNotNone(base, f'{skill} has no one status write line')
        self.assertIn(f' --agent {kind} ', base)
        values = {'<repo>': REPO, '<N>': '12', '<harness>': 'Claude Code', '<model>': 'Opus 5.5 Medium',
                  '<skills>': f'{skill}@{VERSION}'}
        self.assertEqual(set(re.findall('<[^<>]*>', base)) - {"<this skill's folder>"},
                         set(values) | {'<state>', '<step>'}, f'{skill}: a placeholder the agent cannot fill')
        return lambda state, step, *extra: filled(skill, base, dict(values, **{'<state>': state, '<step>': step})) + list(extra)

    def step(self, argv, *extra):
        env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
                   FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'),
                   FAKE_GH_PAGE=self.page)
        for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_REPO'):
            env.pop(key, None)
        return subprocess.run(argv + list(extra), env=env, capture_output=True, text=True, timeout=60)

    def states(self):
        """Each status note on #12 as (comment id, agent, state), read as the app reads the contract."""
        out = []
        for c in self.ticket()['comments']:
            lines = c['body'].split('\n')
            if lines[0] == MARKER and c['author'] == BOT:
                fields = dict(line.split(': ', 1) for line in lines[1:])
                out.append((c['id'], fields['agent'], fields['state']))
        return out

    def test_a_synthetic_fleet_run_moves_each_note_in_place_and_the_wake_fixes_or_reports(self):
        # catches: a skill with no status line, a line pointing at a status.py that isn't there
        # from its own folder, the wrong agent kind, a placeholder the agent can't fill, a later
        # step posting a second note instead of editing its own, any state label written, or a
        # wake that neither fixes an asking note's missing needs-info nor reports a lapsed claim.
        self.world['issues'] += [
            {'number': 13, 'state': 'open', 'labels': ['ready-for-agent'],
             'comments': [comment(201, BOT, note(state='asking'))]},
            {'number': 14, 'state': 'open', 'labels': ['ready-for-agent'],
             'comments': [comment(301, BOT, note(), minutes=45)]}]
        self.save()
        build = self.command('build-ticket', 'builder')
        review = self.command('review-ticket', 'reviewer')
        pr = 'https://github.com/example/tracker/pull/31'

        def run(command, state, step, *extra):
            result = self.step(command(state, step, *extra))
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout

        posted = run(build, 'working', 'claimed the ticket')
        builder = int(re.fullmatch(r'#12: builder working, status note ([0-9]+) posted\n', posted)[1])
        mine = ['--note', str(builder)]
        run(build, 'asking', 'asked which file to change', *mine)
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        run(build, 'working', 'got the answer', *mine)
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.world = self.load()
        self.ticket(self.world)['prs'] = [{'number': 31, 'state': 'OPEN', 'url': pr}]
        self.save()
        run(build, 'done', 'handed back; CI is green', *mine, '--pr', pr)

        posted = run(review, 'working', 'reviewing the head')
        reviewer = int(re.fullmatch(r'#12: reviewer working, status note ([0-9]+) posted\n', posted)[1])
        run(review, 'done', 'posted its verdict', '--note', str(reviewer))
        self.assertEqual(self.states(), [(builder, 'builder', 'done'), (reviewer, 'reviewer', 'done')])

        # The pull request merges while the builder is back at work: merged is GitHub's word.
        run(build, 'working', 'answering the review', *mine, '--pr', pr)
        self.world = self.load()
        self.ticket(self.world)['prs'][0]['state'] = 'MERGED'
        self.save()
        # #1592: the wake's one status call checks and fixes; its lines are the report.
        check = span('launch-fleet', r'`([^`]*status\.py repair[^`]*)`')
        self.assertIsNotNone(check, 'launch-fleet has no one status repair call')
        check = filled('launch-fleet', check, FLEET)
        seen = self.step(check)
        self.assertEqual(seen.returncode, 1, seen.stderr)
        self.assertEqual(sorted(seen.stdout.splitlines()), sorted([
            f'#12 note {builder} builder working: pull request {pr} merged',
            '#13 note 201 builder asking: needs-info added',
            '#14 note 301 builder working: lapsed, no edit for 30 minutes']))
        run(build, 'done', 'merged', *mine, '--pr', pr)

        again = self.step(check)
        self.assertEqual((again.returncode, again.stdout),
                         (1, '#14 note 301 builder working: lapsed, no edit for 30 minutes\n'))
        world = self.load()
        self.assertEqual([it['labels'] for it in world['issues']],
                         [['ready-for-agent'], ['ready-for-agent', 'needs-info'], ['ready-for-agent']])
        self.assertEqual([c['id'] for c in self.ticket(world)['comments']], [101, 102, 103, builder, reviewer])
        self.assertEqual(self.states(), [(builder, 'builder', 'done'), (reviewer, 'reviewer', 'done')])
        # Each agent edits only its own note, and no label but needs-info is ever written.
        # #1592: the fleet's own note on #13 records its repair, and ends done.
        fleet = [c for c in world['issues'][1]['comments'] if c['body'].startswith(MARKER + '\nagent: fleet\n')]
        self.assertEqual([c['body'].split('\n')[2] for c in fleet], ['state: done'])
        edits = [c['path'] for c in self.calls() if c['method'] == 'PATCH']
        self.assertEqual(sorted(set(edits)), sorted({f'repos/{REPO}/issues/comments/{builder}',
                                                     f'repos/{REPO}/issues/comments/{reviewer}',
                                                     f'repos/{REPO}/issues/comments/{fleet[0]["id"]}'}))
        added = [c['body'] for c in self.calls() if c['method'] == 'POST' and c['path'].endswith('/labels')]
        self.assertTrue(added)
        self.assertTrue(all(set(b['labels']) <= LABELS for b in added), added)


# #1447: the command under status.py run. It records its pid; `long` waits for the first beat
# and two more (or 30 seconds) and exits 7, and the others wait for the first beat, then change
# note 104 as another writer would, and keep running until stopped. Every value is synthetic.
ACTOR = r'''
import fcntl, json, os, sys, time
from datetime import datetime, timedelta, timezone
mode, out = sys.argv[1], sys.argv[2]
world, log = os.environ['FAKE_GH_WORLD'], os.environ['FAKE_GH_LOG']
open(out + '.pid', 'w').write(str(os.getpid()))
if mode == 'stubborn':
    # A worker that ignores SIGTERM, as some build and test runners do (#62 R1).
    import subprocess
    worker = subprocess.Popen([sys.executable, '-I', '-c',
                               'import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    open(out + '.worker', 'w').write(str(worker.pid))
    mode = 'lost'
def calls(what='\n'):
    return open(log).read().count(what) if os.path.exists(log) else 0
if mode == 'long':
    end = time.monotonic() + 30
    while calls('"PATCH"') < 3 and time.monotonic() < end:
        time.sleep(0.05)
    open(out + '.done', 'w').close(); sys.exit(7)
while calls('"PATCH"') < 1:
    time.sleep(0.05)
with open(world + '.lock', 'w') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    w = json.load(open(world)); it = w['issues'][0]
    mine = next(c for c in it['comments'] if c['id'] == 104)
    stamp = lambda m: (datetime.now(timezone.utc) - timedelta(minutes=m)).strftime('%Y-%m-%dT%H:%M:%SZ')
    if mode == 'lost':
        # The note lapsed (a long stall) and a newer builder claimed the ticket.
        mine['updated'] = stamp(40)
        it['comments'].append({'id': 105, 'author': 'openwiz[bot]', 'body': sys.argv[3], 'updated': stamp(0)})
    else:
        mine['body'] = mine['body'].replace('state: working', 'state: ' + mode); mine['updated'] = stamp(0)
    json.dump(w, open(world, 'w'))
    open(out + '.mark', 'w').write(str(calls()))
time.sleep(60)
'''


def gone(pid):
    """True when PID no longer runs: no such process, or only its exit status is left."""
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0] == 'Z'
    except FileNotFoundError:
        return True
    except OSError:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        return False


class Run(Tracker):
    def setUp(self):
        super().setUp()
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(), minutes=25))
        (self.dir / 'actor.py').write_text(ACTOR)
        self.out = str(self.dir / 'actor')

    def run_command(self, mode, *extra):
        self.save()
        started = datetime.now()
        result = self.run_status('run', '--repo', REPO, '--ticket', '12', '--agent', 'builder', '--note', '104',
                                 '--every', '1', '--', sys.executable, '-I', str(self.dir / 'actor.py'),
                                 mode, self.out, *extra)
        return result, (datetime.now() - started).total_seconds()

    def assert_stopped(self):
        pid = int(Path(self.out + '.pid').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        mark = int(Path(self.out + '.mark').read_text())
        self.assertEqual([c for c in self.calls()[mark:] if c['method'] == 'PATCH'], [])

    def test_run_keeps_the_note_live_across_a_long_command(self):
        # catches: a run whose note lapses during long work (no edit, or an edit GitHub would not
        # record), a beat that changes anything but time (asking rewritten as working), or a
        # lost exit status of the command.
        self.ticket(self.world)['comments'][3]['body'] = note(state='asking')
        result, _ = self.run_command('long')
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertTrue(Path(self.out + '.done').exists())
        beats = [c for c in self.calls() if c['method'] == 'PATCH']
        # The beat before the command, then one each second until the command sees the third.
        self.assertEqual(len(beats), 3, beats)
        self.assertTrue(all(c['path'] == f'repos/{REPO}/issues/comments/104' for c in beats), beats)
        mine = self.ticket()['comments'][3]
        beat = mine['body'].rsplit('time: ', 1)[1]
        self.assertEqual(mine['body'], note(state='asking', time=beat))
        for stamp in (beat, mine['updated']):  # the beat's time, and GitHub's updated_at
            self.assertLess(abs((datetime.now(timezone.utc) - datetime.strptime(
                stamp, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)).total_seconds()), 60)

    def test_run_stops_the_command_when_a_newer_builder_holds_the_claim(self):
        # catches: a heartbeat that keeps the work running, or takes the ticket back, after its
        # note lapsed and a newer builder claimed it (the fence exit).
        result, took = self.run_command('lost', note(step='claimed the ticket'))
        self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]),
                         (3, ['status.py: stop: note 105 holds the builder claim; the command is stopped']))
        self.assertLess(took, 30)
        self.assert_stopped()

    def test_a_heartbeat_never_reopens_a_done_or_stopped_note(self):
        # catches: a heartbeat that writes working on each beat, reopening a note its agent
        # released mid-run, or that keeps the work running after the release.
        for state in ('done', 'stopped'):
            with self.subTest(state=state):
                self.setUp()
                result, took = self.run_command(state)
                self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]), (3, [
                    f'status.py: stop: note 104 is {state}: a heartbeat never reopens it; the command is stopped']))
                self.assertLess(took, 30)
                self.assertEqual(self.ticket()['comments'][3]['body'].split('\n')[2], 'state: ' + state)
                self.assert_stopped()

    def test_a_stopped_run_stops_its_command_and_a_missing_command_is_a_failure(self):
        # catches: a run killed by its host (SIGTERM) that leaves its command running unwatched,
        # or a command that can't start ending in a traceback instead of exit 2.
        self.save()
        env = dict(os.environ, PATH=str(self.dir / 'bin') + ':' + os.environ['PATH'],
                   FAKE_GH_WORLD=str(self.dir / 'world.json'), FAKE_GH_LOG=str(self.dir / 'gh.log'))
        proc = subprocess.Popen([sys.executable, '-I', str(SCRIPT), 'run', '--repo', REPO, '--ticket', '12',
                                 '--agent', 'builder', '--note', '104', '--every', '1', '--', sys.executable,
                                 '-I', str(self.dir / 'actor.py'), 'long', self.out],
                                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        pid = Path(self.out + '.pid')
        for _ in range(600):
            if pid.exists() and pid.read_text():
                break
            time.sleep(0.05)
        proc.terminate()
        self.assertEqual(proc.wait(timeout=30), 143)
        with self.assertRaises(ProcessLookupError):
            os.kill(int(pid.read_text()), 0)
        missing = self.run_status('run', '--repo', REPO, '--ticket', '12', '--agent', 'builder', '--note', '104',
                                  '--', str(self.dir / 'no-such-command'))
        self.assertEqual((missing.returncode, missing.stderr.splitlines()[-1:]),
                         (2, ['status.py: command: could not start: No such file or directory']))

    def test_a_beat_that_lands_over_a_sibling_release_puts_it_back(self):
        # catches: a beat whose read showed working while a sibling wake released the note just
        # before the beat's edit landed, leaving working on top (#1441's read-back must cover beats).
        released = note(state='done', step='the sibling wake handed back')
        self.world['race_edit'] = [{'edit': 104, 'body': released}]
        result, _ = self.run_command('long')
        self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]), (3, [
            'status.py: stop: note 104 was done before this edit landed; the release is put back; '
            'the command was not started']))
        self.assertEqual(self.ticket()['comments'][3]['body'], released)
        self.assertFalse(Path(self.out + '.pid').exists())

    def test_a_stop_kills_a_worker_that_ignores_sigterm(self):
        # catches (#62 R1): cleanup that waits only for the command itself, so a worker in its
        # process group that ignores SIGTERM keeps running in the checkout after the fence exit.
        result, _ = self.run_command('stubborn', note(step='claimed the ticket'))
        self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]),
                         (3, ['status.py: stop: note 105 holds the builder claim; the command is stopped']))
        self.assertTrue(gone(int(Path(self.out + '.worker').read_text())))

    def test_a_lapsed_beat_steps_down_for_a_newer_holder_whatever_its_history(self):
        # catches (#62 R2): earlier beats, alike but for time, read as retries of this one, so a
        # full history (or one that can't be read) fails the read-back before the holder check,
        # and the old note, refreshed live, keeps the claim from the newer builder.
        for case in ('twenty earlier beats', 'an unreadable history', 'twenty earlier beats, no rival'):
            with self.subTest(case=case):
                self.setUp()
                stamps = [f'2030-01-01T00:{i:02d}:00Z' for i in range(20)]
                mine = self.ticket(self.world)['comments'][3]
                mine.update(body=note(time=stamps[-1]), updated=ago(40),
                            edits=[note(time=t) for t in stamps], edited_at=stamps)
                self.world['history_fails'] = case == 'an unreadable history'
                if case.endswith('no rival'):
                    # A long build's own beats are acknowledged, not retries: the beats go on.
                    mine['updated'] = ago(5)
                    result, _ = self.run_command('long')
                    self.assertEqual(result.returncode, 7, result.stderr)
                    self.assertEqual(self.ticket()['comments'][3]['body'].split('\n')[2], 'state: working')
                    continue
                self.world['race_edit'] = [{'author': BOT, 'body': note(step='a newer builder claimed')}]
                result, _ = self.run_command('long')
                self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]), (3, [
                    'status.py: stop: note 9001 holds the builder claim; note 104 is stopped (lost claim); '
                    'the command was not started']))
                self.assertEqual(self.ticket()['comments'][3]['body'].split('\n')[2], 'state: stopped (lost claim)')

    def test_beats_keep_the_lease_through_a_failed_beat(self):
        # catches (#62 R3): a schedule that waits a full interval after a failed beat, so with
        # 900-second beats and a slow GitHub the note lapses while the command still runs; or
        # one that keeps the command running once no beat can land inside the lease.
        spec = importlib.util.spec_from_file_location('status_under_test', SCRIPT)
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        lease = 1800
        for every in (1, 60, 600, 900):
            for fails in ([], [1], [1, 2, 3], list(range(1, 40))):
                with self.subTest(every=every, fails=fails):
                    # Each beat takes 1 second; beat n fails when n is in FAILS. Times in seconds.
                    t, ok_at, n, failed, stopped = 0, 0, 0, False, None
                    while t < 3 * lease and stopped is None:
                        wait = status.next_beat(t, ok_at, every, failed)
                        if wait is None:
                            stopped = t
                            break
                        t += wait
                        n += 1
                        started, t = t, t + 1
                        failed = n in fails
                        if not failed:
                            # The edit lands within the beat: GitHub's updated_at is at most t.
                            self.assertLess(t - ok_at, lease, (every, fails, n))
                            ok_at = started
                    if stopped is not None:
                        # The command stops while the last edit is still live, never after.
                        self.assertLess(stopped - ok_at, lease)
                        self.assertEqual(fails, list(range(1, 40)))

    def test_a_first_beat_in_the_notes_own_second_still_changes_the_body(self):
        # catches (#62 R4): a beat in the same UTC second as the note's time writes the same
        # body, which GitHub records as no edit, so the read-back fails and the work never starts.
        spec = importlib.util.spec_from_file_location('status_under_test', SCRIPT)
        status = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(status)
        pinned = datetime.now(timezone.utc).replace(microsecond=0)
        self.ticket(self.world)['comments'][3]['body'] = note(time=pinned.strftime('%Y-%m-%dT%H:%M:%SZ'))
        self.world['noop_unrecorded'] = True
        self.save()
        clock = {'slept': 0}

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return pinned + timedelta(seconds=clock['slept'])
        sleeper = type('Sleeper', (), {'sleep': staticmethod(lambda s: clock.update(slept=clock['slept'] + s)),
                                         'monotonic': staticmethod(time.monotonic)})
        env = {'PATH': str(self.dir / 'bin') + ':' + os.environ['PATH'], 'FAKE_GH_WORLD': str(self.dir / 'world.json'),
               'FAKE_GH_LOG': str(self.dir / 'gh.log'), 'FAKE_GH_PAGE': self.page}
        saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        err = io.StringIO()
        try:
            with mock.patch.dict(os.environ, env), mock.patch.object(status, 'datetime', Clock), \
                    mock.patch.object(status, 'time', sleeper, create=True), contextlib.redirect_stderr(err):
                code = status.main(['run', '--repo', REPO, '--ticket', '12', '--agent', 'builder', '--note', '104',
                                    '--', sys.executable, '-I', '-c', 'raise SystemExit(5)'])
        finally:
            for sig, handler in saved.items():
                signal.signal(sig, handler)
        self.assertEqual(code, 5, err.getvalue())
        beats = [c['body']['body'] for c in self.calls() if c['method'] == 'PATCH']
        self.assertEqual(beats, [note(time=(pinned + timedelta(seconds=1)).strftime('%Y-%m-%dT%H:%M:%SZ'))])

    def test_run_never_starts_the_command_on_a_released_note(self):
        # catches: a run that starts long work on a claim it no longer holds.
        self.ticket(self.world)['comments'][3]['body'] = note(state='done')
        result, _ = self.run_command('long')
        self.assertEqual((result.returncode, result.stderr.splitlines()[-1:]), (3, [
            'status.py: stop: note 104 is done: a heartbeat never reopens it; the command was not started']))
        self.assertFalse(Path(self.out + '.pid').exists())
        self.assertEqual(self.writes(), [])


class WakeRepair(Tracker):
    """#1592 (P4 R1, R2): the wake's status step, run as launch-fleet documents it, while the
    builder resumes. Expected labels come from the contract: needs-info only while a live note
    is asking, and a needs-info a person added last stays."""

    step = FleetRun.step

    def wake(self):
        """The wake's status step as SKILL.md documents it: its one status call, then the
        documented label fix for each asking line when it documents one. The report is
        what the call prints, which the wake passes on as its actions."""
        call = span('launch-fleet', r'`(python3 -I [^`]*status\.py (?:check|repair) [^`]*)`')
        self.assertIsNotNone(call, 'launch-fleet has no one status call')
        seen = self.step(filled('launch-fleet', call, FLEET))
        report = seen.stdout.splitlines()
        fix = span('launch-fleet', r'`(gh issue edit [^`]*--add-label needs-info[^`]*)`')
        for line in report if fix else ():
            if line.endswith(': no needs-info label'):
                n = line.split(' ')[0][1:]
                done = self.step(filled('launch-fleet', fix, {'<N>': n, '<owner>/<repo>': REPO}))
                self.assertEqual(done.returncode, 0, done.stderr)
        return seen.returncode, [x for x in report if not (fix and x.endswith(': no needs-info label'))]

    def test_a_builder_that_resumes_during_the_wake_is_never_marked_as_needing_the_user(self):
        # catches: the wake adding needs-info from its earlier read after the builder resumed
        # (#33 R1), or removing a needs-info a person added.
        asking = note(state='asking', step='asked which file to change')
        resumed = note(state='working', step='got the answer')
        resume = {'issue': 12, 'edit': 104, 'body': resumed}
        person = {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}
        # The ticket's label timeline, as GitHub shows and notifies it: (event, by whom).
        add, remove = ('labeled', BOT), ('unlabeled', BOT)
        cases = {
            # The reviewer's reproduction: the builder resumes after the check reads the tracker.
            # Not even a moment's needs-info: the app would show a false wait.
            'resumed after the read': ({'race_after_scan': [resume]}, ['ready-for-agent'], []),
            # The builder resumes as the label is written.
            'resumed at the label write': ({'race_label': [resume]}, ['ready-for-agent'], [add, remove]),
            # A person marks the ticket as the builder resumes: theirs stays.
            'a person added it': ({'race_label': [resume, person]}, ['ready-for-agent', 'needs-info'],
                                  [('labeled', 'synthetic-owner')]),
        }
        for name, (race, labels, timeline) in cases.items():
            with self.subTest(name):
                self.setUp()
                self.ticket(self.world)['comments'].append(comment(104, BOT, asking))
                self.world.update(race)
                self.save()
                self.wake()
                self.assertEqual(self.ticket()['labels'], labels)
                events = self.ticket().get('events', [])
                self.assertEqual([(e['event'], e['actor']['login']) for e in events], timeline)
                # The next wake sees nothing to fix or report on #12.
                code, report = self.wake()
                self.assertEqual((code, report), (0, []))
                self.assertEqual(self.ticket()['labels'], labels)

    def asking_on_12(self, **race):
        self.ticket(self.world)['comments'].append(comment(104, BOT, note(state='asking', step='asked which file to change')))
        self.world.update(race)
        self.save()

    def timeline(self):
        return [(e['event'], e['actor']['login']) for e in self.ticket().get('events', [])]

    def test_a_repair_whose_read_after_its_label_write_fails_is_settled_by_the_next_wake(self):
        # catches: a label the repair wrote as the builder resumed, left on the ticket because the
        # read after the write failed, and never looked at again (#68 R1). Changed by #1702: the
        # next wake no longer deletes it (a label from an earlier wake may be a person's hold),
        # so it reports it and leaves it. Keeper: this test, which still fails if it is never reported.
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        failing = {'fail_once': f'GET repos/{REPO}/issues/12/comments?per_page=100&page=1'}
        self.asking_on_12(race_label=[resume, failing])
        code, report = self.wake()
        self.assertEqual(code, 2)
        self.assertEqual(len(report), 1, report)
        self.assertRegex(report[0], r'^status check failed: could not repair #12: ')
        code, report = self.wake()
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info left on: ')
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual(self.timeline(), [('labeled', BOT)])
        self.assertEqual(self.wake(), (0, []))

    def test_a_person_who_reapplies_needs_info_as_the_repair_takes_it_off_keeps_it(self):
        # catches: the repair's DELETE landing on a needs-info a person removed and applied again
        # after the repair read who added it last (#68 R2).
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        again = [{'issue': 12, 'unlabel': 'needs-info', 'by': 'synthetic-owner'},
                 {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}]
        self.asking_on_12(race_label=[resume], race_delete=again)
        code, report = self.wake()
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info put back: ')
        self.assertEqual(self.timeline(), [('labeled', BOT), ('unlabeled', 'synthetic-owner'),
                                           ('labeled', 'synthetic-owner'), ('unlabeled', BOT), ('labeled', BOT)])
        # The next wake leaves the person's hold alone.
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def test_a_person_who_reapplies_needs_info_after_the_repair_added_it_keeps_it(self):
        # catches: the repair taking off a needs-info whose last application is a person's,
        # because it applied the label itself earlier in the same wake.
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        again = [{'issue': 12, 'unlabel': 'needs-info', 'by': 'synthetic-owner'},
                 {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}]
        self.asking_on_12(race_after_label=[resume] + again)
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual(self.timeline(), [('labeled', BOT), ('unlabeled', 'synthetic-owner'),
                                           ('labeled', 'synthetic-owner')])

    def test_a_repair_left_part_way_settles_only_its_own_application(self):
        # catches: the next wake treating an older cleanup in the timeline as this repair's,
        # and putting back a label nobody asked for now.
        old = [{'event': kind, 'label': {'name': 'needs-info'}, 'actor': {'login': who}, 'created_at': ago(60)}
               for kind, who in (('labeled', BOT), ('unlabeled', 'synthetic-owner'),
                                 ('labeled', 'synthetic-owner'), ('unlabeled', BOT))]
        self.ticket(self.world)['events'] = old
        self.asking_on_12(fail_once=[f'POST repos/{REPO}/issues/12/labels'])
        code, report = self.wake()
        self.assertEqual(code, 2, report)
        self.world = self.load()
        resumed = next(c for c in self.ticket(self.world)['comments'] if c['id'] == 104)
        resumed.update(body=note(state='working', step='got the answer'), updated=ago(1))
        self.save()
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent'])
        self.assertEqual(len(self.timeline()), 4)

    def test_a_retry_after_a_put_back_whose_note_edit_failed_keeps_the_hold(self):
        # catches: the next wake's retry taking the repair's put-back of a person's needs-info for
        # its own new application and deleting the person's hold (#1700, #68 R3).
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        again = [{'issue': 12, 'unlabel': 'needs-info', 'by': 'synthetic-owner'},
                 {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}]
        # The repair's fleet note is the next comment; its final edit (to done) fails once.
        self.world['fail_once'] = [f'PATCH repos/{REPO}/issues/comments/{self.world["next_id"] + 1}']
        self.asking_on_12(race_label=[resume], race_delete=again)
        code, report = self.wake()
        self.assertEqual(code, 2, report)
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        code, report = self.wake()
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info ')
        self.assertEqual(self.timeline()[-2:], [('unlabeled', BOT), ('labeled', BOT)])
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def test_with_one_login_a_needs_info_from_before_this_wake_is_never_deleted(self):
        # catches: while agents and Jake share one login, the repair deleting Jake's hand-added
        # needs-info because a repair from an earlier wake was left part way and the label's
        # application carries the repair's login (#1702 case 2).
        self.asking_on_12(fail_once=[f'POST repos/{REPO}/issues/12/labels'])
        code, report = self.wake()
        self.assertEqual(code, 2, report)
        self.world = self.load()
        it = self.ticket(self.world)
        # Jake marks the ticket by hand, under the fleet's own login, and the builder resumes.
        it['labels'].append('needs-info')
        it.setdefault('events', []).append({'event': 'labeled', 'label': {'name': 'needs-info'},
                                            'actor': {'login': BOT}, 'created_at': ago(0)})
        resumed = next(c for c in it['comments'] if c['id'] == 104)
        resumed.update(body=note(state='working', step='got the answer'), updated=ago(1))
        self.save()
        code, report = self.wake()
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info ')
        self.assertEqual(self.timeline(), [('labeled', BOT)])
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def test_a_needs_info_whose_application_is_not_listed_yet_stays_and_is_reported(self):
        # catches: a needs-info left on silently by a wake that settles an earlier wake's repair
        # while GitHub's event list doesn't show who applied the label yet (#1702).
        self.asking_on_12(fail_once=[f'POST repos/{REPO}/issues/12/labels'])
        self.assertEqual(self.wake()[0], 2)
        self.world = self.load()
        it = self.ticket(self.world)
        it['labels'].append('needs-info')
        resumed = next(c for c in it['comments'] if c['id'] == 104)
        resumed.update(body=note(state='working', step='got the answer'), updated=ago(1))
        self.save()
        code, report = self.wake()
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info left on: ')
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def shared_login(self, **race):
        # #1702 R1: the fleet acts as a person's own account (a record author), as it does
        # until the App rollout, so the person's label events carry the fleet's login.
        self.world['login'] = 'synthetic-owner'
        self.asking_on_12(**race)

    def test_with_a_shared_login_a_hold_added_just_before_the_repair_post_stays(self):
        # catches: under one shared login, the person's needs-info landing between the repair's
        # last read and its POST (a no-op POST) taken as the repair's and deleted (#82 R1).
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        person = {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}
        self.shared_login(race_label=[person, resume])
        code, report = self.wake()
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info left on: ')
        self.assertEqual(self.timeline(), [('labeled', 'synthetic-owner')])
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def test_with_a_shared_login_a_hold_reapplied_just_before_the_repair_delete_stays(self):
        # catches: under one shared login, the person removing and re-applying needs-info just
        # before the repair's DELETE, losing the hold because put-back only knows other logins (#82 R1).
        resume = {'issue': 12, 'edit': 104, 'body': note(state='working', step='got the answer')}
        again = [{'issue': 12, 'unlabel': 'needs-info', 'by': 'synthetic-owner'},
                 {'issue': 12, 'label': 'needs-info', 'by': 'synthetic-owner'}]
        self.shared_login(race_label=[resume], race_delete=again)
        code, report = self.wake()
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])
        self.assertEqual((code, len(report)), (1, 1), report)
        self.assertRegex(report[0], r'^#12: needs-info left on: ')
        self.assertNotIn(('DELETE', f'repos/{REPO}/issues/12/labels/needs-info'), self.writes())
        self.assertEqual(self.wake(), (0, []))
        self.assertEqual(self.ticket()['labels'], ['ready-for-agent', 'needs-info'])

    def test_a_repair_that_fails_part_way_still_reports_what_it_changed(self):
        # catches: a label written on one ticket and then left out of the report because a
        # later ticket's repair failed, so the wake never records that it changed anything.
        self.world['issues'] = [
            {'number': n, 'state': 'open', 'labels': ['ready-for-agent'],
             'comments': [comment(cid, BOT, note(state='asking'))]} for n, cid in ((12, 104), (13, 201))]
        self.world['fail_once'] = [f'POST repos/{REPO}/issues/13/labels']
        self.save()
        code, report = self.wake()
        self.assertEqual(code, 2)
        self.assertEqual(report[:1], ['#12 note 104 builder asking: needs-info added'])
        self.assertEqual(len(report), 2, report)
        self.assertRegex(report[1], r'^status check failed: could not repair #13: ')
        self.assertEqual([it['labels'] for it in self.load()['issues']],
                         [['ready-for-agent', 'needs-info'], ['ready-for-agent']])

    def test_a_wake_whose_check_cannot_read_reports_a_failed_check(self):
        # catches: a checker read failure (exit 2) passing as a clean wake with nothing to report (#33 R2).
        self.world['fleet_md'] = None
        self.save()
        code, report = self.wake()
        self.assertEqual(code, 2)
        self.assertEqual(len(report), 1, report)
        self.assertRegex(report[0], r'^status check failed: could not read: ')
        self.assertEqual(self.writes(), [])


if __name__ == '__main__':
    unittest.main()
