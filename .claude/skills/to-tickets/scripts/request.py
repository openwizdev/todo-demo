"""Build one decision request from verified public wording and source inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def object_once(items):
    result = dict(items)
    if len(result) != len(items):
        raise ValueError('duplicate field')
    return result


def issue_number(value):
    return type(value) is int and value > 0


def wording(value):
    return isinstance(value, str) and bool(value.strip()) and '\r' not in value and '\n' not in value


def plan(metadata, revision):
    tickets = metadata['tickets']
    if not isinstance(tickets, list) or not tickets:
        raise ValueError('provide the complete read-back ticket table')
    ids = set()
    for row in tickets:
        if (not isinstance(row, dict) or row.keys() != {'number', 'title', 'blockers'}
                or not issue_number(row['number']) or not wording(row['title'])
                or not isinstance(row['blockers'], list) or not all(map(issue_number, row['blockers']))
                or len(row['blockers']) != len(set(row['blockers']))
                or row['number'] in row['blockers'] or row['number'] in ids):
            raise ValueError('invalid ticket table')
        ids.add(row['number'])
        row['blockers'].sort()
    tickets.sort(key=lambda row: row['number'])
    lines = revision.decode('utf-8').split('\n')
    spec = metadata['spec']
    if (len(lines) != len(tickets) + 3 or lines[0] != 'plan-graph revision v2' or lines[-1]
            or not re.fullmatch(rf'spec #{spec} body sha256 [0-9a-f]{{64}}', lines[1])):
        raise ValueError('expected the complete revision-v2 bytes for this spec')
    for row, line in zip(tickets, lines[2:-1]):
        blockers = ' '.join(f'#{number}' for number in row['blockers']) or 'none'
        prefix = f'ticket #{row["number"]} blocked-by {blockers} body sha256 '
        if not re.fullmatch(re.escape(prefix) + r'[0-9a-f]{64} title ' + re.escape(row['title']), line):
            raise ValueError('ticket table disagrees with the revision')
    graph = [{'blocker': blocker, 'ticket': ticket} for blocker, ticket in sorted(
        (blocker, row['number']) for row in tickets for blocker in row['blockers'])]
    return tickets, graph


def request(metadata, revision):
    required = {'id', 'risk', 'spec', 'summary', 'headline'}
    if revision is not None:
        required.add('tickets')
    if (not isinstance(metadata, dict) or metadata.keys() != required
            or not isinstance(metadata['id'], str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', metadata['id'])
            or metadata['risk'] not in ('ordinary', 'live', 'release', 'publish', 'unknown')
            or not issue_number(metadata['spec']) or not wording(metadata['headline'])
            or not isinstance(metadata['summary'], list) or not 1 <= len(metadata['summary']) <= 10
            or not all(map(wording, metadata['summary']))):
        raise ValueError('invalid request metadata')
    record = {**metadata, 'schema': 'openwiz.decisions.v1'}
    if revision is None:
        record.update(kind='spec_confirmation', tickets=[], graph=[])
        source = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    else:
        tickets, graph = plan(metadata, revision)
        record.update(kind='plan_approval', tickets=tickets, graph=graph)
        source = revision
    return {**record, 'status': 'open', 'fingerprint': hashlib.sha256(source).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', type=Path)
    args = parser.parse_args()
    try:
        revision = args.revision.read_bytes() if args.revision else None
        record = request(json.load(sys.stdin, object_pairs_hook=object_once), revision)
        print('```json\n' + json.dumps(record, indent=2, ensure_ascii=False) + '\n```')
    except (OSError, ValueError) as error:
        reason = str(error) if type(error) is ValueError else 'invalid input or unreadable revision'
        print(f'request: {reason}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
