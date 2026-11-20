"""ask-wiz routes to exactly the skills the package ships (#1186)."""
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / 'skills' / 'ask-wiz' / 'SKILL.md'
PLUGIN = ROOT / '.claude-plugin' / 'plugin.json'
NAME = re.compile(r'`([a-z0-9]+(?:-[a-z0-9]+)*)`')


def routed(text):
    """Every backticked skill-shaped name in a table row of the router."""
    names = set()
    for line in text.splitlines():
        if line.startswith('|') and not set(line) <= set('|-: '):
            names.update(NAME.findall(line))
    return names


class Routes(unittest.TestCase):
    def test_router_names_exactly_the_shipped_catalog(self):
        shipped = {entry.removeprefix('./skills/')
                   for entry in json.loads(PLUGIN.read_text())['skills']}
        names = routed(SKILL.read_text())
        self.assertEqual(sorted(shipped - names), [], 'shipped skills ask-wiz does not route')
        self.assertEqual(sorted(names - shipped), [], 'routes to skills the package does not ship')


if __name__ == '__main__':
    unittest.main()
