"""Public CLI proofs for the WCAG contrast helper. Colours are synthetic."""
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'contrast.py'


def run(*args):
    return subprocess.run([sys.executable, '-I', str(SCRIPT), *args],
                          capture_output=True, text=True, timeout=30)


class Contrast(unittest.TestCase):
    def test_known_ratios(self):
        # catches: a wrong luminance formula. Black on white is 21:1 by
        # definition; the rest are the dark craft example's recorded pairs.
        for fg, bg, ratio in [('#000000', '#ffffff', '21.00:1'),
                              ('#ffffff', '#ffffff', '1.00:1'),
                              ('#edf2f7', '#1b222b', '14.23:1'),
                              ('#aab7c4', '#283341', '6.27:1'),
                              ('#718399', '#1b222b', '4.13:1')]:
            with self.subTest(fg=fg, bg=bg):
                result = run(fg, bg)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, ratio + '\n')

    def test_order_does_not_matter(self):
        # catches: a ratio below 1 when the lighter colour comes second.
        self.assertEqual(run('#1b222b', '#edf2f7').stdout, '14.23:1\n')

    def test_threshold_passes_or_fails_by_exit_code(self):
        # catches: a pair under the project's threshold reported as passing.
        passing = run('#718399', '#1b222b', '--min', '3')
        self.assertEqual((passing.returncode, passing.stdout), (0, '4.13:1 pass (needs 3:1)\n'))
        failing = run('#718399', '#1b222b', '--min', '4.5')
        self.assertEqual((failing.returncode, failing.stdout), (1, '4.13:1 fail (needs 4.5:1)\n'))

    def test_threshold_compares_the_unrounded_ratio(self):
        # catches: 4.499:1 passing 4.5 because the shown value rounds to 4.50.
        # WCAG thresholds have no rounding.
        result = run('#7171ad', '#ffffff', '--min', '4.5')
        self.assertEqual((result.returncode, result.stdout), (1, '4.50:1 fail (needs 4.5:1)\n'))

    def test_bad_colours_are_refused(self):
        # catches: a token name or short form silently read as some colour.
        for args in [('gold', '#000000'), ('#fff', '#000000'), ('#gggggg', '#000000'),
                     ('#000000',), ('#000000', '#ffffff', '--min', '0')]:
            with self.subTest(args=args):
                result = run(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
