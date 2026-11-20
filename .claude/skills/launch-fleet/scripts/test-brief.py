#!/usr/bin/env python3
"""brief.py (WS8, #1181): every brief the fleet sends, printed literally.

python3 -I skills/launch-fleet/scripts/test-brief.py
"""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
HEAD = '0123456789abcdef0123456789abcdef01234567'
OLD = 'fedcba9876543210fedcba9876543210fedcba98'


def brief(*args):
    r = subprocess.run([sys.executable, '-I', str(HERE / 'brief.py'), *map(str, args)],
                       capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout.rstrip('\n')


def lookup(skill):
    return ("Verify .claude-plugin/plugin.json manifest name openwiz and entry ./skills/%s; report missing, "
            "unreadable or ambiguous matches, otherwise read the unique matching file and follow it" % skill)


class Brief(unittest.TestCase):
    def test_the_fleet_thread_brief_is_the_one_install_sends(self):
        spec = importlib.util.spec_from_file_location('first_fleet', ROOT / 'skills/install/scripts/first_fleet.py')
        first_fleet = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(first_fleet)
        self.assertEqual(brief('fleet', 4001, 'synthetic-owner/synthetic-repo'),
                         (0, first_fleet.brief(4001, 'synthetic-owner/synthetic-repo')))

    def test_each_brief_points_at_its_own_work_and_skill(self):
        cases = [
            (('builder', 12), 'You are the builder for #12. Use the build-ticket skill.', 'build-ticket'),
            (('reviewer', 31, HEAD), 'You are the reviewer for pull request #31 at %s.' % HEAD, 'review-ticket'),
            (('re-check', 31, HEAD, OLD, 'R1,R2', 'none'),
             'Re-check pull request #31 at %s: use the review-ticket skill.' % HEAD, 'review-ticket'),
            (('fresh', 12, 31, 'room/12-synthetic', HEAD),
             'You are the fresh builder for #12: one fresh round on pull request #31, on its branch '
             'room/12-synthetic, after the report at %s.' % HEAD, 'build-ticket'),
            (('diagnose',), 'Use the diagnose skill.', 'diagnose'),
            (('tick', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             'You are a launch-fleet tick for synthetic-owner/synthetic-repo. Use the launch-fleet skill.', 'launch-fleet'),
            (('wakes', 'synthetic-owner/synthetic-repo', 'thr_synorch1'),
             "You are a launch-fleet tick for synthetic-owner/synthetic-repo, woken by GitHub's messages.",
             'launch-fleet'),
            (('wake', 4001, 'synthetic-owner/synthetic-repo'),
             'Fleet wake for synthetic-owner/synthetic-repo spec #4001. Use the launch-fleet skill.', 'launch-fleet'),
        ]
        for args, start, skill in cases:
            with self.subTest(kind=args[0]):
                code, text = brief(*args)
                self.assertEqual(code, 0)
                self.assertTrue(text.startswith(start), text)
                self.assertIn(lookup(skill), text)
        code, text = brief('tick', 'synthetic-owner/synthetic-repo', 'thr_synorch1')
        self.assertTrue(text.endswith("do its Each wake section for the due lines below. "
                                      "The orchestrator's thread is thr_synorch1."), text)
        code, text = brief('re-check', 31, HEAD, OLD, 'R1,R2', 'none')
        self.assertIn('Open findings: R1,R2. Changed since %s: git diff %s %s' % (OLD, OLD, HEAD), text)

    def test_malformed_targets_print_no_brief(self):
        for args in (('builder', '12; rm -rf /'), ('reviewer', 31, 'abc123'), ('fresh', 12, 31, 'main branch', HEAD),
                     ('re-check', 31, HEAD, OLD, 'R1', 'thr_synthetic'), ('fleet', 1, 'not a repo'), ('tick', 'synthetic-owner/synthetic-repo', 'me'), ('nope',)):
            with self.subTest(args=args):
                self.assertEqual(brief(*args), (2, ''))


if __name__ == '__main__':
    unittest.main()
