#!/usr/bin/env python3
"""diagnose's loop helper. Python 3.10+ standard library; prints one short line.

  loop.py rate --runs N [--timeout SECONDS] -- COMMAND...
      Run COMMAND N times (no shell, output discarded, never echoed) and print
      `rate: F/N failed; exits <code>x<count>...; timeouts T`. Every run counts:
      a failure never stops the count and no run is retried. Exit 1 if any run
      failed or timed out, 0 if none did, 2 if COMMAND cannot start (an
      environment failure, never the symptom) or the arguments are wrong.
  loop.py tag
      Print a fresh debug prefix such as `[DEBUG-a4f2]`.
  loop.py clean PREFIX
      From the root of the Git work tree around the current directory, from
      any subdirectory, search tracked and untracked, not ignored, files for
      PREFIX, and the staged (index) copy of each tracked file too. Exit 0
      `clean: ...` when none is left, 1 `left: ...` naming each root-relative
      file:line, marked ` (staged)` when only the staged copy holds it, 2
      outside a Git tree, on a Git read error, or for a PREFIX that is not
      `[DEBUG-xxxx]`-shaped.
"""
import os
import re
import secrets
import signal
import subprocess
import sys
from collections import Counter

TAG = re.compile(r'\[DEBUG-[0-9A-Za-z]{2,16}\]')


def refuse(message):
    print(f'loop: {message}', file=sys.stderr)
    sys.exit(2)


def attempt(command, timeout):
    """One run's exit code, or None on a timeout. On POSIX the run gets its own
    process group, and a timeout or interruption kills that whole group, the
    workers it started included, before this returns."""
    posix = os.name == 'posix'  # start_new_session: Python 3.10's way to a new group
    proc = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, start_new_session=posix)
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None
    finally:
        if proc.returncode is None:
            try:
                if posix:
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            except ProcessLookupError:
                pass
            proc.wait()


def rate(args):
    runs, timeout = None, None
    if '--' not in args:
        refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND...')
    split = args.index('--')
    options, command = args[:split], args[split + 1:]
    while options:
        name, value, options = options[0], options[1] if len(options) > 1 else None, options[2:]
        try:
            if name == '--runs':
                runs = int(value)
            elif name == '--timeout':
                timeout = float(value)
            else:
                raise ValueError
        except (TypeError, ValueError):
            refuse(f'unreadable option {name}')
    if runs is None or runs < 1 or not command or (timeout is not None and timeout <= 0):
        refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND...')
    exits, timeouts = Counter(), 0
    for _ in range(runs):
        try:
            code = attempt(command, timeout)
        except OSError:
            refuse('cannot start the command: an environment failure, not the symptom')
        if code is None:
            timeouts += 1
        else:
            exits[code] += 1
    failed = timeouts + sum(n for code, n in exits.items() if code != 0)
    shown = ' '.join(f'{code}x{n}' for code, n in sorted(exits.items())) or 'none'
    print(f'rate: {failed}/{runs} failed; exits {shown}; timeouts {timeouts}')
    return 1 if failed else 0


def git(root, *args, input=None):
    done = subprocess.run(['git', *args], cwd=root, capture_output=True, input=input)
    if done.returncode != 0:
        refuse('cannot read the Git work tree or index')
    return done.stdout


def read_blobs(root, ids):
    """Each index blob's bytes, read in one `git cat-file --batch`."""
    ids = sorted(ids)
    out = subprocess.run(['git', 'cat-file', '--batch'], cwd=root, capture_output=True,
                         input=''.join(f'{i}\n' for i in ids).encode())
    if out.returncode != 0:
        refuse('cannot read the Git work tree or index')
    blobs, data = {}, out.stdout
    for blob in ids:
        header, _, data = data.partition(b'\n')
        parts = header.split()
        if len(parts) != 3 or parts[0].decode() != blob or parts[1] != b'blob':
            refuse('cannot read the Git work tree or index')
        size = int(parts[2])
        blobs[blob], data = data[:size], data[size + 1:]
    return blobs


def lines(content, prefix):
    """The 1-based numbers of the lines holding PREFIX, split as text mode reads them."""
    text = content.decode('utf-8', 'replace').replace('\r\n', '\n').replace('\r', '\n')
    return [n for n, line in enumerate(text.split('\n'), 1) if prefix in line]


def clean(args):
    if len(args) != 1 or not TAG.fullmatch(args[0]):
        refuse('usage: loop.py clean [DEBUG-xxxx]')
    prefix = args[0]
    top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True)
    if top.returncode != 0:
        refuse('not inside a Git work tree')
    root = os.fsdecode(top.stdout.rstrip(b'\n'))
    listed = git(root, 'ls-files', '-z', '--others', '--exclude-standard')
    staged = {}  # path -> index blob, for regular files only
    for entry in filter(None, git(root, 'ls-files', '-z', '--stage').split(b'\0')):
        info, _, path = entry.partition(b'\t')
        mode, blob, _stage = info.split()
        if mode in (b'100644', b'100755'):
            staged[os.fsdecode(path)] = blob.decode()
    paths = set(staged) | {os.fsdecode(p) for p in filter(None, listed.split(b'\0'))}
    # Only a staged copy that differs from its file can hold another tag. Hash
    # the files themselves: diff-files trusts index flags (sparse checkout,
    # assume-unchanged) and would skip those entries.
    present = sorted(p for p in staged if os.path.isfile(os.path.join(root, p)))
    hashed = git(root, 'hash-object', '--no-filters', '--stdin-paths',
                 input=''.join(f'{p}\n' for p in present).encode()).split()
    if len(hashed) != len(present):
        refuse('cannot read the Git work tree or index')
    same = {p for p, h in zip(present, hashed) if h.decode() == staged[p]}
    blobs = read_blobs(root, {blob for p, blob in staged.items() if p not in same})
    left = []
    for path in sorted(paths):
        try:
            with open(os.path.join(root, path), 'rb') as file:
                working = file.read()
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            working = None  # deleted from the work tree, or a submodule
        found = lines(working, prefix) if working is not None else []
        left += [f'{path}:{n}' for n in found]
        index = blobs.get(staged.get(path))
        if index is not None and index != working:
            left += [f'{path}:{n} (staged)' for n in lines(index, prefix) if n not in found]
    if left:
        print(f'left: {len(left)} {prefix} in {", ".join(left)}')
        return 1
    print(f'clean: no {prefix} left')
    return 0


def main(argv):
    command, args = (argv[0], argv[1:]) if argv else (None, [])
    if command == 'rate':
        return rate(args)
    if command == 'tag' and not args:
        print(f'[DEBUG-{secrets.token_hex(2)}]')
        return 0
    if command == 'clean':
        return clean(args)
    refuse('usage: loop.py rate --runs N [--timeout SECONDS] -- COMMAND... | tag | clean PREFIX')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
