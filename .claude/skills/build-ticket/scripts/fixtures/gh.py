#!/usr/bin/env python3
"""Synthetic `gh` for ticket.py's tests. State is the JSON file in FAKE_GH_WORLD.

Answers only the calls ticket.py makes; anything else exits 9 so a test sees it.
Comments are kept per issue or pull request number.
"""
import json
import os
import re
import sys
import time

path = os.environ['FAKE_GH_WORLD']
with open(path, encoding='utf-8') as f:
    world = json.load(f)
args = sys.argv[1:]
world.setdefault('calls', []).append(args)


def save():
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(world, f)


def answer(value, code=0):
    save()
    print(json.dumps(value))
    sys.exit(code)


def number(api_path):
    return re.search(r'/(?:issues|pulls)/(\d+)', api_path).group(1)


if args[:2] == ['issue', 'view']:
    issue = world.get('issues', {}).get(args[2])
    if issue is None or world.get('fail_reads'):
        save()
        sys.exit(1)
    answer(issue)
if args[:2] == ['repo', 'view']:
    answer({'nameWithOwner': world['checkout_repo']})
if args == ['api', 'user']:
    answer(world['user'])
if args[:1] == ['api'] and args[-1].endswith('/comments') and '--paginate' in args:
    if world.get('fail_reads'):
        save()
        sys.exit(1)
    comments = world.get('comments', {}).get(number(args[-1]), [])
    answer([comments[:2], comments[2:]] if '--slurp' in args else comments)
if args[:1] == ['api'] and '/pulls/' in args[-1]:
    answer({'head': {'sha': world['pr_head']}})
if args[:3] == ['api', '--method', 'POST']:
    target = next(a for a in args if a.startswith('repos/'))
    body = next(a[len('body='):] for a in args if a.startswith('body='))
    if world.get('refuse_post'):
        save()
        sys.exit(1)
    comments = world.setdefault('comments', {}).setdefault(number(target), [])
    comment = {'id': 9000 + len(comments), 'user': {'login': world.get('poster', 'owner-1')},
               'body': body}
    comments.append(comment)
    lost = world.pop('lose_post_response', None)
    if world.get('fail_reads_after_post'):
        world['fail_reads'] = True
    save()
    if lost == 'timeout':
        time.sleep(float(world.get('hang_seconds', 60)))
    if lost:
        sys.exit(1)
    print(json.dumps(comment))
    sys.exit(0)
save()
sys.exit(9)
