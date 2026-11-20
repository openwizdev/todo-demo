"""Keep the better of two cuts of one spec (#1353, F6): the shorter critical
chain, and the wider graph when the chains are equal.

    python3 -I prefer.py <cut A> <cut B>

Each cut is tickets.md's picture data (`tickets` with `id`, `state` and
`role`; `links` with `blocker` and `ticket`). The chain and the width are
approve.py's: the chain is the longest run of work not yet merged along hard
edges, outside (`external`) blockers included, and the width is the largest
start wave of the spec's own work. A `file` link into a builder's ticket only
shares context (F6) and is no hard edge; every link into a person's is. Prints one `cut <file>: chain C, widest W` line per cut, then
`prefer <file>: <why>`; on a tie it keeps the first. Exit 0, or 2 with one
`prefer: <file>: <why>` line when a cut can't be read or has a cycle.
"""
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location('approve', HERE / 'approve.py')
approve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(approve)


def measure(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    tickets, links = data['tickets'], data['links']
    if not isinstance(tickets, list) or not isinstance(links, list) or not tickets:
        raise ValueError('needs `tickets` and `links` lists')
    after, planned, done, roles = {}, set(), set(), {}
    for t in tickets:
        if not isinstance(t['id'], str) or t['id'] in after:
            raise ValueError(f'unreadable or repeated ticket id {t["id"]!r}')
        after[t['id']] = set()
        roles[t['id']] = t['role']
        if t['role'] != 'external':
            planned.add(t['id'])
        if t['state'] == 'merged':
            done.add(t['id'])
    for link in links:
        if link['blocker'] not in after or link['ticket'] not in after:
            raise ValueError(f'a link names an unknown ticket: {link["blocker"]} -> {link["ticket"]}')
        # F6: a file link into a builder's ticket only shares context; into
        # a person's (or any other) ticket every link holds it.
        if link['kind'] != 'file' or roles[link['ticket']] != 'builder':
            after[link['blocker']].add(link['ticket'])
    chain, widest, unreached = approve.chain_width(after, planned, done)
    if unreached:
        raise ValueError(f'a cycle: {" ".join(unreached)} can never start')
    return chain, widest


def main():
    if len(sys.argv) != 3:
        print('prefer: usage: prefer.py <cut A> <cut B>', file=sys.stderr)
        return 2
    measured = []
    for path in sys.argv[1:]:
        name = Path(path).name
        try:
            measured.append((name, *measure(path)))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
            print(f'prefer: {name}: {e}', file=sys.stderr)
            return 2
    for name, chain, widest in measured:
        print(f'cut {name}: chain {chain}, widest {widest}')
    (a, chain_a, wide_a), (b, chain_b, wide_b) = measured
    if chain_a != chain_b:
        print(f'prefer {a if chain_a < chain_b else b}: the shorter critical chain')
    elif wide_a != wide_b:
        print(f'prefer {a if wide_a > wide_b else b}: the same chain, and the wider graph')
    else:
        print(f'prefer {a}: the same chain and width; keep the first')
    return 0


if __name__ == '__main__':
    sys.exit(main())
