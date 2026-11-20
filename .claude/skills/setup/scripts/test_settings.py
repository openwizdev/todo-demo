#!/usr/bin/env python3
"""settings.py check: the read-back setup's last step relies on (#1183).

Each case writes a synthetic docs/agents/ folder, runs the public command and
reads only its exit code and short result.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'settings.py'
SKILLS = Path(__file__).resolve().parents[2]


def reader(path):
    """A consumer of the settings, loaded from its own skill so this test reads its real rules."""
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def table(title, provider, model):
    return ('## %s\n\nOne line.\n\n| Setting | Value | `room-cli thread spawn` flag |\n| --- | --- | --- |\n'
            '| Harness | Synthetic | `--provider %s` |\n| Model | Synthetic | `--model %s` |\n'
            '| Effort | High | `--reasoning-level high` |\n\nSource: synthetic decision.\n\n' % (title, provider, model))


FLEET = ('# Fleet settings\n\nIntro.\n\n'
         + table('Builder', 'claude-code', 'syn-claude-1')
         + table('Builder for small tickets', 'codex', 'syn-codex-1')
         + table('Reviewer for Claude-built', 'codex', 'syn-codex-1')
         + table('Reviewer for GPT-built', 'claude-code', 'syn-claude-1')
         + '## Test commands\n\n| # | Folder | Command | CI check |\n| --- | --- | --- | --- |\n'
           '| 1 | root | `make test` | `build` |\n\nSource: synthetic workflow.\n\n'
           '## CI checks\n\n| Check | Runs | Required on |\n| --- | --- | --- |\n| `build` | 1 | `main` |\n\n'
           'Source: synthetic workflow.\n\n'
           '## Standing merge rules\n\nNone yet: every merge waits for the user.\n\nSource: synthetic.\n\n'
           '## GitHub identity\n\n| Setting | Value |\n| --- | --- |\n'
           '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n\nSource: synthetic.\n')
ROLES = ('needs-triage', 'needs-info', 'ready-for-agent', 'ready-for-human', 'wontfix')
LABELS = ('# Triage labels\n\n## Labels\n\n| Role | Label here | Meaning |\n| --- | --- | --- |\n'
          + ''.join('| `%s` | `%s` | Synthetic |\n' % (r, r) for r in ROLES))
FILES = {'fleet.md': FLEET, 'triage-labels.md': LABELS,
         'issue-tracker.md': '# Issue tracker: GitHub\n\nSynthetic.\n', 'domain.md': '# Domain docs\n\nSynthetic.\n'}


class Check(unittest.TestCase):

    def project(self, **changes):
        root = Path(tempfile.mkdtemp(prefix='setup-check-'))
        self.addCleanup(shutil.rmtree, root, True)
        (root / 'docs/agents').mkdir(parents=True)
        for name, text in dict(FILES, **changes).items():
            if text is not None:
                (root / 'docs/agents' / name).write_text(text)
        return root

    def check(self, root, *args):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'check', '--root', str(root), *args],
                                capture_output=True, text=True, timeout=60)
        return result.returncode, result.stdout

    def test_complete_settings_read_back_verified(self):
        # catches: a correct project refused, so no fleet can start after setup.
        code, out = self.check(self.project())
        self.assertEqual(code, 0, out)
        self.assertEqual(out.splitlines()[-1], 'Settings: verified (4 files).')

    def test_a_missing_setting_is_named_and_repair_reads_back(self):
        # catches: setup reporting done while a setting every fleet reads is gone
        # (the setup.repair case), or a repaired file still refused.
        broken = FLEET.replace('| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n', '')
        root = self.project(**{'fleet.md': broken})
        code, out = self.check(root)
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: GitHub identity: no Record authors row', out)
        (root / 'docs/agents/fleet.md').write_text(FLEET)
        self.assertEqual(self.check(root)[0], 0)

    def test_every_required_file_and_section_is_named_when_missing(self):
        # catches: a missing settings file or section passed over silently.
        code, out = self.check(self.project(**{'domain.md': None, 'fleet.md': FLEET.replace('## CI checks', '## Checks')}))
        self.assertEqual(code, 5, out)
        self.assertIn('domain.md: missing', out)
        self.assertIn('fleet.md: no ## CI checks section', out)

    def test_a_linked_settings_file_is_refused(self):
        # catches: a settings file read through a link to somewhere outside the project.
        root = self.project()
        outside = Path(tempfile.mkdtemp(prefix='setup-outside-'))
        self.addCleanup(shutil.rmtree, outside, True)
        (outside / 'fleet.md').write_text(FLEET)
        (root / 'docs/agents/fleet.md').unlink()
        os.symlink(outside / 'fleet.md', root / 'docs/agents/fleet.md')
        code, out = self.check(root)
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: not a regular file', out)

    def test_a_reviewer_from_the_builders_family_is_refused(self):
        # catches: a same-family reviewer table, which breaks the builder-reviewer split.
        same = FLEET.replace(table('Reviewer for Claude-built', 'codex', 'syn-codex-1'),
                             table('Reviewer for Claude-built', 'claude-code', 'syn-claude-1'))
        code, out = self.check(self.project(**{'fleet.md': same}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Reviewer for Claude-built: claude-code is not from another model family', out)

    def test_an_unfilled_template_value_is_refused(self):
        # catches: a template placeholder shipped as a setting.
        placeholder = FLEET.replace('`--model syn-codex-1`', '`--model <id>`', 1)
        code, out = self.check(self.project(**{'fleet.md': placeholder}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder for small tickets: unfilled <id>', out)

    def test_each_triage_role_has_one_label_that_exists_once(self):
        # catches: a role with no label or two, and a label missing from (or
        # repeated in) the tracker, which leaves triage unable to sort.
        twice = LABELS + '| `needs-info` | `waiting` | Synthetic |\n'
        code, out = self.check(self.project(**{'triage-labels.md': twice}))
        self.assertEqual(code, 5, out)
        self.assertIn('triage-labels.md: needs-info: mapped 2 times', out)
        root = self.project()
        saved = root / 'labels.json'
        saved.write_text(json.dumps([{'name': n} for n in ROLES if n != 'wontfix'] + [{'name': 'needs-info'}]))
        code, out = self.check(root, '--labels', str(saved))
        self.assertEqual(code, 5, out)
        self.assertIn('triage-labels.md: wontfix: label wontfix is not in the tracker', out)
        self.assertIn('triage-labels.md: needs-info: label needs-info is in the tracker 2 times', out)

    def test_a_second_record_authors_row_is_refused_and_named(self):
        # catches: setup verifying a repair that left two Record authors rows,
        # which the review helper then refuses, so no review is admitted (#1500).
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |\n'
        old = '| Record authors | `synthetic-old` |\n'
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace(row, row + old)}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: GitHub identity: Record authors row 2 of 2: %s' % old.strip(), out)
        # A second GitHub identity section is read as the readers read it, not skipped.
        code, out = self.check(self.project(**{'fleet.md': FLEET + '\n## GitHub identity\n\n' + old}))
        self.assertEqual(code, 5, out)
        self.assertIn('Record authors row 2 of 2', out)

    def test_a_record_authors_cell_is_validated_whole(self):
        # catches: a row the readers refuse whole (text beside the logins, an extra
        # cell) passed because each backticked login parsed on its own.
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |'
        for bad in (row.replace(', `synthetic-owner`', ' and `synthetic-owner`'), row + ' note |'):
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(row, bad)}))
            self.assertEqual(code, 5, bad + '\n' + out)
            self.assertIn('fleet.md: GitHub identity: Record authors needs one or more exact logins', out)

    def test_a_duplicate_or_malformed_spawn_flag_is_refused_and_named(self):
        # catches: setup verifying an agent table the first-fleet launch reader
        # refuses: a second --model left in a note, or a value that is not one token (#1520).
        for title, provider, model in (('Builder', 'claude-code', 'syn-claude-1'),
                                       ('Builder for small tickets', 'codex', 'syn-codex-1'),
                                       ('Reviewer for Claude-built', 'codex', 'syn-codex-1'),
                                       ('Reviewer for GPT-built', 'claude-code', 'syn-claude-1')):
            good = table(title, provider, model)
            noted = good.replace('Source: synthetic decision.', 'Was `--model syn-old`. Source: synthetic decision.')
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, noted)}))
            self.assertEqual(code, 5, out)
            self.assertIn('fleet.md: %s: --model appears 2 times' % title, out)
            split = good.replace('`--reasoning-level high`', '`--reasoning-level high extra`')
            code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, split)}))
            self.assertEqual(code, 5, out)
            self.assertIn('fleet.md: %s: malformed `--reasoning-level high extra`' % title, out)
        # A repeated section heading adds its flags to the same section, as launch reads it.
        extra = '## Builder\n\nOld: `--provider codex`.\n\n'
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace('## Test commands', extra + '## Test commands')}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder: --provider appears 2 times', out)

    def test_each_fixer_row_carries_each_flag_once(self):
        # catches: a Fixer family row with a leftover second --model, or a
        # malformed flag, verified although the fresh round cannot pick one model (R1).
        fixer = ('## Fixer\n\nOne line.\n\n| Builder family | Harness | Model | Effort | `room-cli thread spawn` flags |\n'
                 '| --- | --- | --- | --- | --- |\n'
                 '| Claude | Claude Code | Syn | High | `--provider claude-code --model syn-claude-1 --reasoning-level high` |\n'
                 '| GPT | Codex | Syn | XHigh | `--provider codex --model syn-codex-1 --reasoning-level xhigh` |\n\n')
        valid = FLEET.replace('## Test commands', fixer + '## Test commands')
        code, out = self.check(self.project(**{'fleet.md': valid}))
        self.assertEqual(code, 0, out)
        twice = valid.replace('--model syn-claude-1 ', '--model syn-claude-1 --model syn-old ')
        code, out = self.check(self.project(**{'fleet.md': twice}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Fixer: Claude: --model appears 2 times', out)
        self.assertNotIn('Fixer: GPT', out)
        missing = valid.replace(' --reasoning-level xhigh', ' --reasoning-level')
        code, out = self.check(self.project(**{'fleet.md': missing}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Fixer: GPT: malformed --reasoning-level', out)

    def test_a_malformed_flag_is_counted_beside_an_old_note(self):
        # catches: a tab-separated new flag skipped, so an old well-formed flag
        # in a note is read as the only one and launch picks the old model (R2).
        good = table('Builder', 'claude-code', 'syn-claude-1')
        bad = good.replace('`--model syn-claude-1`', '`--model\tsyn-new`').replace(
            'Source: synthetic decision.', 'Was `--model syn-claude-1`. Source: synthetic decision.')
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace(good, bad)}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: Builder: --model appears 2 times', out)

    def test_the_identity_heading_is_read_exactly_as_review_reads_it(self):
        # catches: `##  GitHub identity` (an extra space) verified although the
        # review helper finds no record authors there and admits no review (R3).
        code, out = self.check(self.project(**{'fleet.md': FLEET.replace('## GitHub identity', '##  GitHub identity')}))
        self.assertEqual(code, 5, out)
        self.assertIn('fleet.md: no ## GitHub identity section', out)

    def test_setup_never_verifies_settings_the_readers_refuse(self):
        # catches: setup verifying a file the real review or launch reader then
        # refuses (#1500, #1520). Setup may be stricter: on a tab-separated flag
        # beside an old note, launch reads the old model, so setup refuses (R2).
        review = reader(SKILLS / 'review-ticket/scripts/review.py')
        launch = reader(SKILLS / 'install/scripts/first_fleet.py')
        row = '| Record authors | `synthetic-factory[bot]`, `synthetic-owner` |'
        builder = table('Builder', 'claude-code', 'syn-claude-1')
        cases = [FLEET]
        cases += [FLEET.replace(row, bad) for bad in (
            row + '\n| Record authors | `synthetic-old` |', row.replace('`, `', '` and `'), row + ' x |',
            row.replace('synthetic-owner', 'synthetic--owner'), '| Record authors | |')]
        cases += [FLEET.replace(builder, bad) for bad in (
            builder + 'Was `--model syn-old`.\n', builder.replace('`--provider claude-code`', '`--provider claude code`'),
            builder.replace('`--model syn-claude-1`', '`--model  syn-claude-1`'),
            builder.replace('`--model syn-claude-1`', '`--model\tsyn-new`') + 'Was `--model syn-claude-1`.\n')]
        cases.append(FLEET.replace('## GitHub identity', '##  GitHub identity'))
        for text in cases:
            try:
                review.record_authors(text)
                authors = True
            except review.Refusal:
                authors = False
            sections = {}
            for line in text.split('\n'):
                if line.startswith('## '):
                    name = line[3:].strip()
                    sections.setdefault(name, [])
                elif sections:
                    sections[name].append(line)
            tables = all(launch.agent(sections[t]) for t in ('Builder', 'Builder for small tickets',
                                                             'Reviewer for Claude-built', 'Reviewer for GPT-built'))
            code, out = self.check(self.project(**{'fleet.md': text}))
            self.assertTrue(code != 0 or (authors and tables), text + '\n' + out)

    def test_usage_errors_exit_2(self):
        # catches: a mistyped command read as a verified project.
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), 'verify'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertTrue(result.stdout.startswith('usage: settings.py check'), result.stdout)


if __name__ == '__main__':
    unittest.main()
