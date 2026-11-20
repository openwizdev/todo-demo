import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/request.py'
META = {'id': 'synthetic-request', 'risk': 'ordinary', 'spec': 901,
        'summary': ['Review café / sample.'], 'headline': 'You can read a sample.'}
TICKETS = [{'number': 902, 'title': 'Synthetic reader', 'blockers': [900]},
           {'number': 903, 'title': 'Synthetic cards', 'blockers': [902]}]
REVISION = (
    'plan-graph revision v2\n'
    'spec #901 body sha256 ' + '1' * 64 + '\n'
    'ticket #902 blocked-by #900 body sha256 ' + '2' * 64 + ' title Synthetic reader\n'
    'ticket #903 blocked-by #902 body sha256 ' + '3' * 64 + ' title Synthetic cards\n'
)


def run(metadata, revision=None):
    with tempfile.TemporaryDirectory() as directory:
        args = [sys.executable, '-I', SCRIPT]
        if revision is not None:
            path = Path(directory) / 'revision.txt'
            path.write_bytes(revision.encode())
            args.extend(['--revision', path])
        return subprocess.run(args, input=json.dumps(metadata), text=True, capture_output=True)


class DecisionRequest(unittest.TestCase):
    def record(self, result):
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:1], ['```json'])
        self.assertEqual(lines[-1:], ['```'])
        return json.loads('\n'.join(lines[1:-1]))

    def test_spec_request_hashes_exact_public_wording(self):
        record = self.record(run(META))
        canonical = ('{"graph":[],"headline":"You can read a sample.","id":"synthetic-request",'
                     '"kind":"spec_confirmation","risk":"ordinary","schema":"openwiz.decisions.v1",'
                     '"spec":901,"summary":["Review café / sample."],"tickets":[]}')
        self.assertEqual(record['fingerprint'], hashlib.sha256(canonical.encode()).hexdigest())
        self.assertEqual(record['status'], 'open')

    def test_plan_request_binds_revision_bytes_and_derives_edges(self):
        record = self.record(run(dict(META, tickets=list(reversed(TICKETS))), REVISION))
        self.assertEqual(record['kind'], 'plan_approval')
        self.assertEqual(record['tickets'], TICKETS)
        self.assertEqual(record['graph'], [{'blocker': 900, 'ticket': 902},
                                           {'blocker': 902, 'ticket': 903}])
        self.assertEqual(record['fingerprint'], hashlib.sha256(REVISION.encode()).hexdigest())

    def test_stale_or_malformed_plan_produces_no_postable_record(self):
        for revision in [REVISION.replace('Synthetic reader', 'Changed reader'),
                         REVISION.replace('blocked-by #900', 'blocked-by none'),
                         REVISION.rstrip('\n'), REVISION.replace('revision v2', 'revision v1')]:
            with self.subTest(revision=revision):
                result = run(dict(META, tickets=TICKETS), revision)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
