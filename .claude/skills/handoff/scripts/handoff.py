#!/usr/bin/env python3
"""The handoff page's exact checks: target privacy, page shape and read-back.

  handoff.py private <owner/repo>              exit 0 private ok, 1 refused, 2 unknown
  handoff.py check <page-file>                 exit 0 page ok, 1 each problem, 2 unreadable
  handoff.py landed <owner/repo> <path> <file> exit 0 landed, 1 refused or not landed, 2 unknown

Reads GitHub only through `gh api --method GET`; never writes. Prints one short
line per result and never echoes a matched secret or a raw response.
"""
import base64
import binascii
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote

PAGE = Path(__file__).resolve().parents[1] / 'page.md'
REPOSITORY = re.compile(r'[A-Za-z0-9-]+/[A-Za-z0-9_.-]+')
PAGE_PATH = re.compile(r'[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*')
# Mechanical subset only; the skill's privacy guard covers what a pattern can't.
SECRETS = [
    ('a GitHub token', re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,})')),
    ('an API key', re.compile(r'\b(?:sk-[A-Za-z0-9_-]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})')),
    ('a bearer token', re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{16,}')),
    ('a private key', re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----')),
    ('an email address', re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+')),
    ('a thread id', re.compile(r'\bthr_[A-Za-z0-9]{6,}\b')),
]


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def invalid_constant(_value):
    raise ValueError('non-JSON constant')


def gh_get(endpoint):
    try:
        result = subprocess.run(['gh', 'api', '--method', 'GET', endpoint], capture_output=True,
                                text=True, timeout=60, check=False, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None, 'gh unavailable or timed out'
    if result.returncode:
        return None, f'gh exited {result.returncode}'
    try:
        data = json.loads(result.stdout, object_pairs_hook=unique_object, parse_constant=invalid_constant)
    except ValueError:
        return None, 'invalid JSON'
    if not isinstance(data, dict):
        return None, 'unexpected response'
    return data, None


def target(repo):
    """(default branch, None) for a verified private repository, else (None, (exit, line))."""
    if not REPOSITORY.fullmatch(repo):
        return None, (2, f'unknown: {repo!r} is not owner/name')
    data, reason = gh_get(f'repos/{repo}')
    if reason is None and (type(data.get('private')) is not bool
                           or not isinstance(data.get('default_branch'), str)):
        reason = 'unexpected response'
    if reason:
        return None, (2, f'unknown: {repo} visibility ({reason})')
    if not data['private']:
        return None, (1, f'refused: {repo} is not private')
    return data['default_branch'], None


def private(repo):
    _, stop = target(repo)
    return stop or (0, f'private ok: {repo}')


def sections():
    """The page's title and `##` headings, in order, from the template."""
    lines = PAGE.read_text(encoding='utf-8').splitlines()
    title = next(line for line in lines if line.startswith('# '))
    heads = [line for line in lines if line.startswith('## ')]
    pattern = lambda head: re.compile(re.sub(r'<[^>]*>', '.+', re.escape(head)) + r'\Z')
    return title, [(head, pattern(head)) for head in heads]


def check(file):
    try:
        lines = Path(file).read_text(encoding='utf-8').splitlines()
    except (OSError, UnicodeError):
        return 2, f'unreadable: {file}'
    title, heads = sections()
    problems = []
    first = next((line for line in lines if line.strip()), '')
    if first != title:
        problems.append(f'line 1: the page opens with `{title}`')
    if not any(line.startswith('**Snapshot: ') for line in lines):
        problems.append('no `**Snapshot: <UTC date and time>, <why>.**` line')
    found = [(n, line) for n, line in enumerate(lines, 1) if line.startswith('## ')]
    if len(found) != len(heads) or not all(p.match(line) for (_, p), (_, line) in zip(heads, found)):
        problems.append('the sections are exactly, in order: ' + '; '.join(h[3:] for h, _ in heads))
    for i, (n, line) in enumerate(found):
        end = found[i + 1][0] - 1 if i + 1 < len(found) else len(lines)
        if not any(text.strip() for text in lines[n:end]):
            problems.append(f'line {n}: `{line}` is empty; write "None."')
    for n, line in enumerate(lines, 1):
        for name, pattern in SECRETS:
            if pattern.search(line):
                problems.append(f'line {n}: {name}; remove it')
    if problems:
        return 1, '\n'.join(problems)
    return 0, 'page ok'


def landed(repo, path, file):
    if not PAGE_PATH.fullmatch(path) or '..' in path.split('/'):
        return 2, f'unknown: {path!r} is not a repository path'
    try:
        local = Path(file).read_bytes()
    except OSError:
        return 2, f'unknown: {file} is unreadable'
    branch, stop = target(repo)
    if stop:
        return stop
    data, reason = gh_get(f'repos/{repo}/contents/{path}?ref={quote(branch, safe="")}')
    if reason is None:
        try:
            if data.get('encoding') != 'base64' or not isinstance(data.get('sha'), str):
                raise ValueError
            remote = base64.b64decode(''.join(data['content'].split()), validate=True)
        except (KeyError, TypeError, ValueError, binascii.Error):
            reason = 'unexpected response'
    if reason:
        return 2, f'unknown: {path} on {branch} ({reason})'
    if remote != local:
        return 1, f'not landed: {path} on {branch} differs from {file}'
    return 0, f'landed: {path} on {branch} at {data["sha"]}'


def main(argv):
    commands = {'private': (private, 1), 'check': (check, 1), 'landed': (landed, 3)}
    if not argv or argv[0] not in commands or len(argv) - 1 != commands[argv[0]][1]:
        print('\n'.join(__doc__.splitlines()[2:5]), file=sys.stderr)
        return 2
    code, line = commands[argv[0]][0](*argv[1:])
    print(line)
    return code


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
