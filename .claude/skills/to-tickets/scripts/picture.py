"""Render the proposed or read-back ticket graph as one Mermaid picture."""
from collections import deque
import json
import re
import sys

COLORS = {
    'merged': ('#dcfce7', '#15803d'),
    'building': ('#dbeafe', '#1d4ed8'),
    'waiting': ('#f3f4f6', '#6b7280'),
    'jake': ('#f3e8ff', '#7e22ce'),
}
ROLES = ('builder', 'jake', 'release', 'external')
ESCAPED = '#&<>[](){}"`|\\'


def object_once(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError('duplicate field')
    return result


def fields(value, expected):
    return isinstance(value, dict) and value.keys() == set(expected.split())


def line(value):
    return (isinstance(value, str) and bool(value.strip())
            and value.splitlines() == [value] and value.isprintable())


def label(value):
    return ''.join(f'#{ord(char)};' if char in ESCAPED else char for char in value)


def read_graph(data):
    if (not fields(data, 'tickets links') or not isinstance(data['tickets'], list)
            or not data['tickets'] or not isinstance(data['links'], list)):
        raise ValueError('provide tickets and links')
    cards = {}
    for card in data['tickets']:
        if (not fields(card, 'id title size state role') or not line(card['title'])
                or not isinstance(card['id'], str)
                or not re.fullmatch(r'(?:#[1-9][0-9]*|[A-Za-z][A-Za-z0-9_-]*)', card['id'])
                or card['size'] not in ('S', 'M', 'L')
                or card['state'] not in ('merged', 'building', 'waiting')
                or card['role'] not in ROLES):
            raise ValueError('invalid ticket card')
        if card['id'] in cards:
            raise ValueError('duplicate ticket')
        cards[card['id']] = card

    outgoing = {name: {} for name in cards}
    incoming = {name: [] for name in cards}
    for edge in data['links']:
        if (not fields(edge, 'blocker ticket kind reason') or not line(edge['reason'])
                or edge['kind'] not in ('real', 'file')
                or not isinstance(edge['blocker'], str) or not isinstance(edge['ticket'], str)):
            raise ValueError('invalid link')
        blocker, ticket = edge['blocker'], edge['ticket']
        if blocker not in cards or ticket not in cards:
            raise ValueError('link names an unknown ticket')
        if ticket in outgoing[blocker]:
            raise ValueError('duplicate link')
        outgoing[blocker][ticket] = edge
        incoming[ticket].append(blocker)
    return cards, outgoing, incoming


def critical_path(outgoing, incoming):
    remaining = {ticket: len(blockers) for ticket, blockers in incoming.items()}
    ready = deque(ticket for ticket, count in remaining.items() if not count)
    paths = {ticket: (ticket,) for ticket in ready}
    visited = 0
    while ready:
        parent = ready.popleft()
        visited += 1
        for ticket in outgoing[parent]:
            path = paths[parent] + (ticket,)
            if len(path) > len(paths.get(ticket, ())):
                paths[ticket] = path
            remaining[ticket] -= 1
            if remaining[ticket] == 0:
                ready.append(ticket)
    if visited != len(incoming):
        raise ValueError('dependency cycle')
    return max(paths.values(), key=len)


def picture(data):
    cards, outgoing, incoming = read_graph(data)
    critical_path(outgoing, incoming)  # every link: refuses a cycle
    # F6 (#1353): a file link into a builder's ticket only shares context, so
    # the chain and the start count read hard links alone; a person's ticket
    # waits for every link.
    hard_out = {b: {t: e for t, e in out.items() if e['kind'] != 'file' or cards[t]['role'] != 'builder'}
                for b, out in outgoing.items()}
    hard_in = {t: [b for b in blockers if t in hard_out[b]] for t, blockers in incoming.items()}
    path = critical_path(hard_out, hard_in)
    bold_edges = dict(zip(path, path[1:]))
    ids = {ticket: index for index, ticket in enumerate(cards)}
    rows = ['```mermaid', 'flowchart LR']
    for ticket, card in cards.items():
        text = label(f'{ticket} · {card["size"]} · {card["title"]}')
        if card['role'] in ('jake', 'release'):
            rows.append(f'  T{ids[ticket]}(["{text}"]):::jake')
        else:
            rows.append(f'  T{ids[ticket]}["{text}"]:::{card["state"]}')

    count = 0
    bold = []
    for ticket, children in outgoing.items():
        index = ids[ticket]
        source = f'T{index}'
        grouped = len(children) > 1
        if grouped:
            rows.append(f'  B{index}["#93;"]:::bracket')
            rows.append(f'  {source} --> B{index}')
            if ticket in bold_edges:
                bold.append(count)
            count += 1
            source = f'B{index}'
        for child, edge in children.items():
            kind = edge['kind']
            if grouped:
                connector = '---' if kind == 'real' else '-.-'
            else:
                connector = '-->' if kind == 'real' else '-.->'
            rows.append(f'  {source} {connector}|{kind}: {label(edge["reason"])}| T{ids[child]}')
            if bold_edges.get(ticket) == child:
                bold.append(count)
            count += 1

    for name, (fill, stroke) in COLORS.items():
        rows.append(f'  classDef {name} fill:{fill},stroke:{stroke},color:#111827')
    rows.append('  classDef bracket fill:transparent,stroke:transparent,font-weight:bold')
    if bold:
        rows.append(f'  linkStyle {",".join(map(str, bold))} stroke-width:4px')
    ready = sum(card['role'] == 'builder' and card['state'] == 'waiting'
                and all(cards[blocker]['state'] == 'merged' for blocker in hard_in[ticket])
                for ticket, card in cards.items())
    total = sum(card['role'] != 'external' for card in cards.values())
    rows.extend(['```', '', f'Longest chain: {len(path) - 1} links ({" → ".join(path)}).',
                 f'Can start at approval: {ready} of {total}.'])
    return '\n'.join(rows)


def main():
    try:
        print(picture(json.load(sys.stdin, object_pairs_hook=object_once)))
    except json.JSONDecodeError:
        print('picture: invalid JSON', file=sys.stderr)
        return 1
    except ValueError as error:
        print(f'picture: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
