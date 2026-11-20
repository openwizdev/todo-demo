#!/usr/bin/env python3
"""Run only #1273's failed CI groups, using their original test.sh assertions.

No copied expectations or production overrides. This selects 20 existing cases
(the 15 CI failures plus the setup/neighbor cases their groups need).
"""
import argparse
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--revision', help='read test.sh at this Git revision')
args = parser.parse_args()
source = subprocess.check_output(
    ['git', 'show', args.revision + ':skills/launch-fleet/scripts/test.sh'], cwd=ROOT, text=True
) if args.revision else (HERE / 'test.sh').read_text()


def section(start, end):
    begin = source.index(start)
    return source[begin:source.index(end, begin)]


# Retain the existing setup and assertion functions, leaving out its full-run
# worker launch. Every selected block below is unchanged source text.
prefix = source[:source.index('# A full run: the workers')]
prefix = re.sub(r'^HERE=.*$', 'HERE=' + shlex.quote(str(HERE)), prefix, count=1, flags=re.M)
parts = [prefix]
parts.append(section("expect 'a verdict after it was told again ends the check'", "expect 'told again on an older head"))
parts.append(section("expect 'K9: two approved pull requests change the same file at once", "expect 'K9: two approved at once, one with tests"))
parts.append(section("expect 'a closed ticket gets its builder and reviewer archived'", "expect 'needs-info: the question goes"))
parts.append(section("### The loop's script: a clone", "expect 'claim: the only claim goes'"))
parts.append(section('# The literal costs below', '# A quiet back-off:'))
# Select the quarter-allowance block by its distinct remaining allowance.
quarter = source.index("expect 'budget: a quarter of the allowance left still checks'")
quarter_start = source.rfind('ERR=', 0, quarter)
parts.append(source[quarter_start:source.index('ERR=', quarter)])
parts.append(section('# Several fleets: current measured costs', "expect 'budget: the first check reads the plan once'"))
parts.append(section("QUIET='all_closed", "expect 'budget: a spec with no open ticket"))
parts.append(section("expect 'budget: a quiet spec, before fleet.sh changes'", '# A closed ticket with a launch-fleet record'))
parts.append(section('S34=$(sha 34)', "expect 'wake: a pull request reads only"))
wake = source.index("expect 'wake: it reports its points:")
parts.append(source[source.rfind('ERR=', 0, wake):source.index('# The ticket of #31 relies', wake)])
parts.append(section('cache_case() {', "cache_case 'REST cache: changed PR heads"))
parts.append(section("SPEC40='.issues", "expect 'fleet: the check reads every spec"))
parts.append(section("### A fleet thread's loop (#192)", '### Token cuts (#694):'))
parts.append('''
only_reads "$tmp"/case-*/gh*.log "$tmp"/cache-*/gh.log "$tmp"/loop/log[0-9]
[ "$cases" = 20 ] || bad 'the scoped cases ran' "$cases cases ran, not 20"
printf '%s cases, %s failed\n' "$cases" "$fails"
[ "$fails" = 0 ]
''')
env = {k: v for k, v in os.environ.items() if k not in ('TEST_ONLY', 'TEST_WORKER', 'TEST_SHARED', 'TEST_PASS')}
with tempfile.TemporaryDirectory(prefix='1273-ci-cases-') as directory:
    script = Path(directory) / 'test.sh'
    script.write_text('\n'.join(parts))
    result = subprocess.run(['sh', str(script)], cwd=ROOT, env=env)
raise SystemExit(result.returncode)
