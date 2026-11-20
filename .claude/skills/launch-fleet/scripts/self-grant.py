#!/usr/bin/env python3
"""Grant and record one of the fleet's four bounded self-grants (#1353, F4).

  self-grant.py OWNER/NAME TICKET KIND REASON [--spec SPEC]

KIND is one of:
  supporting-edit    a few-line supporting edit the ticket can't work without
  dependency-wiring  wiring an already-approved, small, pinned dependency
  read-route         a read route under the API rules
  spec-change        a truly necessary spec change (needs --spec): recorded on
                     the spec first, then on the ticket

Each grant is one public record on the ticket, written with post.py and read
back: `launch-fleet: granted <kind>: <reason>`. A model or effort change is
never a self-grant (ask Jake), and anything else goes to the orchestrator: both
exit 1 with `refused: ...` and write nothing. Prints post.py's lines; exit 1
with `unknown: ...` when a record can't be read back (a spec change then
records no grant); exit 2 on a bad command line.
"""
import argparse
import importlib.util
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('launch_fleet_post', HERE / 'post.py')
post = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(post)

KINDS = ('supporting-edit', 'dependency-wiring', 'read-route', 'spec-change')
NEVER = ('model', 'effort')


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('repo')
    parser.add_argument('ticket', type=int)
    parser.add_argument('kind')
    parser.add_argument('reason')
    parser.add_argument('--spec', type=int)
    args = parser.parse_args(argv)
    if args.kind in NEVER:
        print('refused: a model or effort change is never a self-grant; ask Jake')
        return 1
    if args.kind not in KINDS:
        print('refused: not a self-grant kind; ask the orchestrator')
        return 1
    reason = args.reason.strip()
    if (not post.REPO.fullmatch(args.repo) or args.ticket < 1 or not reason or '\n' in reason
            or (args.kind == 'spec-change') != (args.spec is not None)
            or (args.spec is not None and (args.spec < 1 or args.spec == args.ticket))):
        print('self-grant: usage: OWNER/NAME TICKET KIND REASON, one line of reason, '
              'and --spec SPEC (not the ticket) exactly for a spec-change', file=sys.stderr)
        return 2
    words = args.kind.replace('-', ' ')
    writes = []
    if args.spec is not None:
        writes.append((args.spec, f'launch-fleet: spec changed for #{args.ticket}: {reason}'))
        words += f' on #{args.spec}'
    writes.append((args.ticket, f'launch-fleet: granted {words}: {reason}'))
    try:
        for number, body in writes:
            print(post.comment(args.repo, number, body))
    except post.Stop as outcome:
        print(outcome)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
