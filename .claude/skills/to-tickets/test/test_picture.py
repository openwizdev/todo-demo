import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/picture.py'


def render(tickets, links):
    return subprocess.run([sys.executable, '-I', SCRIPT], capture_output=True, text=True,
                          input=json.dumps({'tickets': tickets, 'links': links}))


def card(name, title, size, state, role='builder'):
    return dict(id=name, title=title, size=size, state=state, role=role)


def link(blocker, ticket, kind='real', reason='Provides the read interface'):
    return dict(blocker=blocker, ticket=ticket, kind=kind, reason=reason)


class TicketPicture(unittest.TestCase):
    def test_render_shows_state_size_and_human_gates(self):
        result = render([
            card('#10', 'Draft', 'S', 'merged'),
            card('#11', 'Reader', 'M', 'building'),
            card('#12', 'Exporter', 'L', 'waiting'),
            card('#13', 'Pilot decision', 'S', 'waiting', 'jake'),
            card('#14', 'Release go', 'S', 'waiting', 'release'),
        ], [])
        self.assertEqual(result.returncode, 0, result.stderr)
        for row in [
            'T0["#35;10 · S · Draft"]:::merged',
            'T1["#35;11 · M · Reader"]:::building',
            'T2["#35;12 · L · Exporter"]:::waiting',
            'T3(["#35;13 · S · Pilot decision"]):::jake',
            'T4(["#35;14 · S · Release go"]):::jake',
            'classDef merged fill:#dcfce7,stroke:#15803d',
            'classDef building fill:#dbeafe,stroke:#1d4ed8',
            'classDef waiting fill:#f3f4f6,stroke:#6b7280',
            'classDef jake fill:#f3e8ff,stroke:#7e22ce',
        ]:
            self.assertIn(row, result.stdout)

    def test_render_groups_fanout_and_bolds_the_longest_chain(self):
        result = render([card(name, name, 'M', 'waiting') for name in 'ABCD'],
                        [link('A', 'B'), link('A', 'C', 'file', 'shared.md'), link('B', 'D')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('T0 --> B0', result.stdout)
        self.assertIn('B0 ---|real: Provides the read interface| T1', result.stdout)
        self.assertIn('B0 -.-|file: shared.md| T2', result.stdout)
        self.assertIn('T1 -->|real: Provides the read interface| T3', result.stdout)
        self.assertIn('linkStyle 0,1,3 stroke-width:4px', result.stdout)
        self.assertIn('Longest chain: 2 links (A → B → D).', result.stdout)
        self.assertNotIn('T0 -->|', result.stdout)

    def test_render_refuses_a_cycle_or_missing_prerequisite(self):
        cards = [card(name, name, 'S', 'waiting') for name in 'AB']
        for links, message in [([link('A', 'B'), link('B', 'A')], 'cycle'),
                               ([link('X', 'A')], 'unknown ticket')]:
            with self.subTest(message=message):
                result = render(cards, links)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn(message, result.stderr)

    def test_render_escapes_issue_text_as_data(self):
        result = render([card('A', 'Read "] <img> `draft`', 'S', 'waiting'),
                         card('B', 'Use it', 'S', 'waiting')],
                        [link('A', 'B', reason='Use | and <tags>')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Read #34;#93; #60;img#62; #96;draft#96;', result.stdout)
        self.assertIn('|real: Use #124; and #60;tags#62;|', result.stdout)

    def test_a_file_link_neither_lengthens_the_chain_nor_holds_a_start(self):
        # catches (review R5 of #1353): a context-only file link counted as
        # serial work, so the picture says fewer tickets can start than F6
        # starts. A person's ticket still waits for every blocker.
        result = render([card(name, name, 'S', 'waiting') for name in 'ABC'] + [card('J', 'J', 'S', 'waiting', 'jake')],
                        [link('A', 'B', 'file', 'shared.md'), link('B', 'C'), link('C', 'J', 'file', 'notes.md')])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Longest chain: 2 links (B → C → J).', result.stdout)
        self.assertIn('Can start at approval: 2 of 4.', result.stdout)


if __name__ == '__main__':
    unittest.main()
