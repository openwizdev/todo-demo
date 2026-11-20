#!/usr/bin/env bash
# Adapted from Matt Pocock's diagnosing-bugs @ 4ae2317. MIT notice below.
# Usage: bash hitl-loop.template.sh 'scenario step' 'exact symptom question'
# The human signs in themselves and reports only a y/n observation.
# Exit 1 = symptom present, 0 = absent, 2 = inconclusive; never eval input.
set -euo pipefail

if [[ $# != 2 || -z ${1-} || -z ${2-} ]]; then
  printf '%s\n' 'usage: bash hitl-loop.template.sh "scenario step" "exact symptom question"' >&2
  exit 2
fi

inconclusive() {
  printf '%s\n' 'inconclusive: a completed step and an explicit y or n observation are required' >&2
  exit 2
}

printf '\n>>> %s\n' "$1"
printf '%s\n' '    Follow the step yourself; do not enter credentials here. Press Enter when done.'
IFS= read -r completed || inconclusive
printf '\n>>> %s\n' "$2"
printf '%s\n' '    Symptom present? Enter y or n only; no secrets or raw error text.'
IFS= read -r answer || inconclusive
case "$answer" in
  y) printf '%s\n' 'SYMPTOM_PRESENT=yes'; exit 1 ;;
  n) printf '%s\n' 'SYMPTOM_PRESENT=no'; exit 0 ;;
  *) inconclusive ;;
esac

# Copyright (c) 2026 Matt Pocock
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
