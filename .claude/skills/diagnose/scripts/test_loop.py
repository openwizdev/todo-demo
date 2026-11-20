#!/usr/bin/env python3
"""diagnose's loop helper: rate, tag and clean, on synthetic commands and Git trees only."""
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

LOOP = Path(__file__).resolve().parent / 'loop.py'


def run(*args, cwd=None):
    return subprocess.run([sys.executable, '-I', str(LOOP), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=60)


def counter(tmp, fail_on):
    """A synthetic flaky command: run k (from a counter file) fails when k is in fail_on."""
    script = Path(tmp) / 'flaky.py'
    script.write_text(
        'import sys, pathlib\n'
        'p = pathlib.Path(sys.argv[1]); k = int(p.read_text() or 0) + 1 if p.exists() else 1\n'
        'p.write_text(str(k))\n'
        'print("SYNTHETIC_SECRET_OUTPUT"); print("SYNTHETIC_SECRET_ERR", file=sys.stderr)\n'
        f'sys.exit(3 if k in {sorted(fail_on)!r} else 0)\n')
    return [sys.executable, '-I', str(script), str(Path(tmp) / 'count')]


# Python 3.10's subprocess.Popen keyword parameters (its documented signature).
POPEN_3_10 = {'bufsize', 'executable', 'stdin', 'stdout', 'stderr', 'preexec_fn', 'close_fds',
              'shell', 'cwd', 'env', 'universal_newlines', 'startupinfo', 'creationflags',
              'restore_signals', 'start_new_session', 'pass_fds', 'user', 'group',
              'extra_groups', 'encoding', 'errors', 'text', 'umask', 'pipesize'}

ALIVE = ('def alive(pid):\n'
         '    try:\n'
         '        state = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[0]\n'
         '    except (FileNotFoundError, ProcessLookupError):\n'
         '        return False\n'
         '    return state != "Z"  # a zombie runs nothing\n')
exec(ALIVE)


def stop_workers(pids):
    """Kill any worker a failing run left behind, so a red run leaks nothing."""
    for pid in (int(p) for p in pids.read_text().split()) if pids.exists() else ():
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class Rate(unittest.TestCase):
    def test_every_run_counts_and_a_late_failure_is_red(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run('rate', '--runs', '6', '--', *counter(tmp, {6}))
            self.assertEqual(r.returncode, 1, r.stderr)
            self.assertEqual(r.stdout, 'rate: 1/6 failed; exits 0x5 3x1; timeouts 0\n')
            self.assertEqual((Path(tmp) / 'count').read_text(), '6')

    def test_all_passing_runs_are_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run('rate', '--runs', '3', '--', *counter(tmp, set()))
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stdout, 'rate: 0/3 failed; exits 0x3; timeouts 0\n')

    def test_a_failure_never_stops_the_count_or_retries_to_green(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run('rate', '--runs', '4', '--', *counter(tmp, {1, 3}))
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stdout, 'rate: 2/4 failed; exits 0x2 3x2; timeouts 0\n')
            self.assertEqual((Path(tmp) / 'count').read_text(), '4')

    def test_a_hang_is_a_failed_run(self):
        r = run('rate', '--runs', '2', '--timeout', '0.5', '--',
                sys.executable, '-I', '-c', 'import time; time.sleep(5)')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, 'rate: 2/2 failed; exits none; timeouts 2\n')

    @unittest.skipUnless(os.path.isdir('/proc/self'), 'reads process states from /proc')
    def test_a_timed_out_attempts_workers_are_stopped_before_the_next_attempt(self):
        # catches: a timeout that kills only the direct command, so its worker
        # still runs during the next attempt and after rate has exited.
        with tempfile.TemporaryDirectory() as tmp:
            script, pids, log = Path(tmp, 'runner.py'), Path(tmp, 'pids'), Path(tmp, 'log')
            script.write_text(
                'import os, subprocess, sys, time\n'
                f'{ALIVE}'
                'pids, log = sys.argv[1], sys.argv[2]\n'
                'seen = [int(p) for p in open(pids).read().split()] if os.path.exists(pids) else []\n'
                'open(log, "a").write("overlap\\n" if any(map(alive, seen)) else "start\\n")\n'
                'worker = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])\n'
                'open(pids, "a").write(f"{worker.pid}\\n")\n'
                'time.sleep(60)\n')
            self.addCleanup(stop_workers, pids)
            r = run('rate', '--runs', '2', '--timeout', '1.5', '--',
                    sys.executable, '-I', str(script), str(pids), str(log))
            self.assertEqual((r.returncode, r.stdout), (1, 'rate: 2/2 failed; exits none; timeouts 2\n'))
            self.assertEqual(log.read_text(), 'start\nstart\n')
            workers = [int(p) for p in pids.read_text().split()]
            self.assertEqual(len(workers), 2)
            deadline = time.monotonic() + 5  # a killed worker's exit is delivered, not instant
            while any(map(alive, workers)) and time.monotonic() < deadline:
                time.sleep(0.05)
            self.assertEqual([p for p in workers if alive(p)], [])

    def test_rate_runs_on_python_3_10s_subprocess(self):
        # catches: a Popen keyword newer than Python 3.10 (such as
        # process_group, 3.11), which crashes rate before its first run on a
        # host whose python3 is 3.10. Popen is narrowed to 3.10's parameters.
        launcher = (
            'import runpy, subprocess, sys\n'
            f'ALLOWED = {sorted(POPEN_3_10)!r}\n'
            'class Popen(subprocess.Popen):\n'
            '    def __init__(self, *args, **kwargs):\n'
            '        extra = sorted(set(kwargs) - set(ALLOWED))\n'
            '        if extra:\n'
            '            raise TypeError(f"Python 3.10 Popen has no {extra}")\n'
            '        super().__init__(*args, **kwargs)\n'
            'subprocess.Popen = Popen\n'
            'sys.argv = sys.argv[1:]\n'
            'runpy.run_path(sys.argv[0], run_name="__main__")\n')
        for timeout in ([], ['--timeout', '0.5']):
            r = subprocess.run([sys.executable, '-I', '-c', launcher, str(LOOP), 'rate', '--runs', '1',
                                *timeout, '--', sys.executable, '-I', '-c', 'import time; time.sleep(2)'],
                               capture_output=True, text=True, timeout=60)
            expected = 'rate: 1/1 failed; exits none; timeouts 1\n' if timeout else \
                'rate: 0/1 failed; exits 0x1; timeouts 0\n'
            self.assertEqual((r.stdout, r.stderr), (expected, ''), timeout)

    def test_command_output_is_never_echoed(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run('rate', '--runs', '2', '--', *counter(tmp, {1}))
            self.assertEqual(r.stdout, 'rate: 1/2 failed; exits 0x1 3x1; timeouts 0\n')
            self.assertNotIn('SYNTHETIC_SECRET', r.stdout + r.stderr)

    def test_missing_tool_is_an_environment_failure_not_red(self):
        r = run('rate', '--runs', '3', '--', '/nonexistent/synthetic-tool')
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, '')
        self.assertIn('cannot start', r.stderr)

    def test_bad_arguments_are_refused(self):
        for args in (['rate', '--runs', '0', '--', 'true'], ['rate', '--runs', '2'],
                     ['rate', '--runs', 'x', '--', 'true'], ['rate', '--', 'true'], ['other']):
            r = run(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertEqual(r.stdout, '', args)


def git_tree(tmp):
    def git(*a):
        subprocess.run(['git', *a], cwd=tmp, check=True, capture_output=True,
                       env={**os.environ, 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'})
    git('init', '-q')
    (Path(tmp) / '.gitignore').write_text('build/\n')
    (Path(tmp) / 'src').mkdir()
    (Path(tmp) / 'src/app.py').write_text('print("ready")\n')
    git('add', '.')
    git('-c', 'user.name=Synthetic', '-c', 'user.email=synthetic@example.invalid', 'commit', '-qm', 'init')


class Tag(unittest.TestCase):
    def test_tags_are_fresh_debug_prefixes(self):
        first, second = run('tag'), run('tag')
        self.assertEqual(first.returncode, 0)
        self.assertRegex(first.stdout, r'^\[DEBUG-[0-9a-f]{4}\]\n$')
        self.assertNotEqual(first.stdout, second.stdout)


class Clean(unittest.TestCase):
    def test_a_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (0, 'clean: no [DEBUG-a4f2] left\n'))

    def test_leftovers_in_tracked_and_untracked_files_are_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'src/app.py').write_text('print("ready")\nprint("[DEBUG-a4f2] x", x)\n')
            Path(tmp, 'src/probe.py').write_text('# [DEBUG-a4f2]\n')
            Path(tmp, 'build').mkdir()
            Path(tmp, 'build/out.log').write_text('[DEBUG-a4f2] ignored output\n')
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(r.stdout, 'left: 2 [DEBUG-a4f2] in src/app.py:2, src/probe.py:1\n')

    def test_a_tag_left_only_in_the_staged_copy_is_named(self):
        # catches: clean reading only the working copy, so a staged probe the
        # agent then removed from the file passes clean and is committed.
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'src/app.py').write_text('print("ready")\n# [DEBUG-a4f2]\n')
            subprocess.run(['git', 'add', 'src/app.py'], cwd=tmp, check=True)
            Path(tmp, 'src/app.py').write_text('print("ready")\n')
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (1, 'left: 1 [DEBUG-a4f2] in src/app.py:2 (staged)\n'))

    def test_a_staged_file_deleted_from_the_work_tree_is_still_read(self):
        # catches: skipping a path missing from the work tree while its staged
        # blob, which Git will commit, still holds the tag.
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'src/probe.py').write_text('# [DEBUG-a4f2]\n')
            subprocess.run(['git', 'add', 'src/probe.py'], cwd=tmp, check=True)
            Path(tmp, 'src/probe.py').unlink()
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (1, 'left: 1 [DEBUG-a4f2] in src/probe.py:1 (staged)\n'))

    def test_a_tag_removed_from_the_index_but_left_in_the_file_is_named_once(self):
        # catches: the staged scan replacing the working-copy scan, or naming a
        # line twice when the index and the file both hold it.
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'src/app.py').write_text('print("ready")\n# [DEBUG-a4f2]\n')
            Path(tmp, 'src/both.py').write_text('# [DEBUG-a4f2]\n')
            subprocess.run(['git', 'add', 'src/both.py'], cwd=tmp, check=True)
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (1, 'left: 2 [DEBUG-a4f2] in src/app.py:2, src/both.py:1\n'))

    def test_an_unreadable_staged_copy_is_never_called_clean(self):
        # catches: a staged blob Git cannot read being skipped, so clean
        # passes without having seen what Git would commit.
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'src/probe.py').write_text('# [DEBUG-a4f2]\n')
            subprocess.run(['git', 'add', 'src/probe.py'], cwd=tmp, check=True)
            blob = subprocess.run(['git', 'rev-parse', ':src/probe.py'], cwd=tmp, check=True,
                                  capture_output=True, text=True).stdout.strip()
            Path(tmp, '.git/objects', blob[:2], blob[2:]).unlink()
            Path(tmp, 'src/probe.py').write_text('print("ready")\n')
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (2, ''))
            self.assertIn('cannot read', r.stderr)

    def test_a_staged_tag_behind_index_flags_is_named(self):
        # catches: trusting `git diff-files` to list every staged copy that
        # differs from its file: it skips skip-worktree (sparse checkout) and
        # assume-unchanged entries, so their staged tags were called clean.
        for flag in ('sparse-checkout', 'assume-unchanged'):
            with self.subTest(flag), tempfile.TemporaryDirectory() as tmp:
                git_tree(tmp)
                Path(tmp, 'docs').mkdir()
                Path(tmp, 'docs/readme.md').write_text('notes\n')
                Path(tmp, 'src/app.py').write_text('print("ready")\n# [DEBUG-a4f2]\n')
                subprocess.run(['git', 'add', '.'], cwd=tmp, check=True)
                if flag == 'sparse-checkout':
                    subprocess.run(['git', 'sparse-checkout', 'set', 'docs'], cwd=tmp, check=True,
                                   capture_output=True)
                    self.assertFalse(Path(tmp, 'src/app.py').exists())
                else:
                    subprocess.run(['git', 'update-index', '--assume-unchanged', 'src/app.py'],
                                   cwd=tmp, check=True)
                    Path(tmp, 'src/app.py').write_text('print("ready")\n')
                r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
                self.assertEqual((r.returncode, r.stdout),
                                 (1, 'left: 1 [DEBUG-a4f2] in src/app.py:2 (staged)\n'))

    def test_a_leftover_outside_the_current_directory_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            Path(tmp, 'tests').mkdir()
            Path(tmp, 'tests/repro.py').write_text('# [DEBUG-a4f2]\n')
            r = run('clean', '[DEBUG-a4f2]', cwd=Path(tmp, 'src'))
            self.assertEqual((r.returncode, r.stdout), (1, 'left: 1 [DEBUG-a4f2] in tests/repro.py:1\n'))

    def test_a_prefix_that_would_match_ordinary_text_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            git_tree(tmp)
            for prefix in ('', 'print', '[DEBUG-]', 'DEBUG-a4f2'):
                r = run('clean', prefix, cwd=tmp)
                self.assertEqual(r.returncode, 2, prefix)

    def test_outside_a_git_tree_nothing_is_called_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = run('clean', '[DEBUG-a4f2]', cwd=tmp)
            self.assertEqual((r.returncode, r.stdout), (2, ''))


if __name__ == '__main__':
    unittest.main()
