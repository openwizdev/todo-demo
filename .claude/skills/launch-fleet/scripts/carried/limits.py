#!/usr/bin/env python3
"""Read factory stage goals; settings alone authorize no action."""
import argparse
import json
from pathlib import Path
import re
import sys

STAGES = ('builder_start', 'reviewer_start', 'merge', 'fix_after_changes',
          'builder_question_answer')


def read(path):
    """Return all five explicit goals or raise ValueError/OSError; no fallback."""
    content = Path(path).read_text(encoding='ascii')
    if not re.fullmatch(r'[\t\r\n\x20-\x7e]*', content):
        raise ValueError('invalid stage-limit settings')
    minutes = {}
    for line in content.splitlines():
        line = line.strip(' \t')
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([a-z_]+)[ \t]*=[ \t]*([1-9][0-9]*)', line)
        if match is None:
            raise ValueError('invalid stage-limit settings')
        key, value = match.groups()
        if key not in STAGES or key in minutes:
            raise ValueError('invalid stage-limit settings')
        minutes[key] = int(value)
    if set(minutes) != set(STAGES):
        raise ValueError('invalid stage-limit settings')
    return {'schema': 'closedwiz.factory-limits.v1', 'minutes': minutes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path,
                        default=Path(__file__).resolve().with_name('limits.conf'))
    args = parser.parse_args()
    try:
        settings = read(args.settings)
    except (OSError, ValueError):
        print('limits: invalid settings', file=sys.stderr)
        return 1
    print(json.dumps(settings, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
