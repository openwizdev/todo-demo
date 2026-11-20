#!/usr/bin/env python3
"""WCAG 2 contrast of two sRGB colours, as `ratio:1`.

python3 contrast.py '#edf2f7' '#1b222b' [--min 4.5]

Colours are six-digit hex. Prints the ratio rounded to two places; with --min
it adds pass or fail and exits 1 on a fail. Exit 2 refuses bad input with
nothing on stdout. It measures one flat pair, not a gradient, an image or a
whole page.
"""
import argparse
import math
import re
import sys


def luminance(colour):
    def linear(channel):
        c = channel / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(int(colour[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def colour(value):
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise argparse.ArgumentTypeError('colour must be six-digit hex, like #1b222b')
    return value


def threshold(value):
    number = float(value)
    if not math.isfinite(number) or not 1 <= number <= 21:
        raise argparse.ArgumentTypeError('--min must be from 1 to 21')
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('foreground', type=colour)
    parser.add_argument('background', type=colour)
    parser.add_argument('--min', type=threshold, help="the project's required ratio")
    args = parser.parse_args()
    light, dark = sorted((luminance(args.foreground), luminance(args.background)), reverse=True)
    ratio = (light + 0.05) / (dark + 0.05)
    shown = f'{ratio:.2f}:1'
    if args.min is None:
        print(shown)
        return 0
    ok = ratio >= args.min  # WCAG thresholds are never rounded
    print(f"{shown} {'pass' if ok else 'fail'} (needs {args.min:g}:1)")
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
