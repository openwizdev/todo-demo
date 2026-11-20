#!/bin/sh
# index.sh on synthetic grill files (ClosedWiz#317). Run from anywhere:
#   sh skills/grill/scripts/test.sh
# Each case writes grill files to a fresh folder, runs index.sh on it, and
# asserts its exact exit status, its exact stdout and, on a refusal, the exact
# reason on stderr. Any mismatch, any setup step that fails and any missing
# case is counted, and the run exits 1. INDEX_SH=<file> runs the same cases
# against another script.
set -u
HERE=$(cd "$(dirname "$0")" && pwd) || exit 1
INDEX=${INDEX_SH:-$HERE/index.sh}
CASES=30 # every case below; fewer run means one was skipped
fails=0
cases=0

tmp=$(mktemp -d) || { echo "FAIL no temporary folder"; exit 1; }
trap 'rm -rf "$tmp"' EXIT

HEAD='| Grill | Status | Feeds |
| --- | --- | --- |'

# A fresh, empty grills folder for the next case.
fresh() { rm -rf "$tmp/g" && mkdir "$tmp/g" || { echo "FAIL setup"; exit 1; }; }

# grill FILE TITLE STATUS-PARAGRAPH: a grill file shaped as the skill's template.
grill() {
  printf '%s\n\n%s\n\n## Round 1\n\n**Z1 - A question?** Status: **open**. Feeds: nothing.\n' "$2" "$3" > "$tmp/g/$1" ||
    { echo "FAIL setup: $1"; exit 1; }
}

# expect NAME STATUS STDOUT [STDERR]: runs index.sh on the folder and compares.
expect() {
  cases=$((cases + 1))
  out=$(sh "$INDEX" "$tmp/g" 2> "$tmp/err")
  code=$?
  err=$(cat "$tmp/err")
  if [ "$code" != "$2" ] || [ "$out" != "$3" ] || [ "$err" != "${4:-}" ]; then
    fails=$((fails + 1))
    echo "FAIL $1: exit $code (want $2)"
    printf '  stdout:\n%s\n  want:\n%s\n  stderr:\n%s\n  want:\n%s\n' "$out" "$3" "$err" "${4:-}"
  else
    echo "ok $1"
  fi
}

P='**Private.** Every question exactly as asked.'

# --- Good folders ---

fresh
expect empty 0 "$HEAD"

fresh
grill 2026-01-02-alpha.md '# Grill: alpha (2026-01-02)' "$P Status: **open**. Feeds: the alpha spec."
expect open 0 "$HEAD
| [alpha](2026-01-02-alpha.md) | **open** | the alpha spec |"

fresh
grill 2026-01-02-alpha.md '# Grill: alpha (2026-01-02)' "$P Status: **confirmed** by Robin, 2026-01-05. Feeds: the alpha spec, \`docs/ROADMAP.md\`."
expect confirmed 0 "$HEAD
| [alpha](2026-01-02-alpha.md) | **confirmed** (2026-01-05) | the alpha spec, \`docs/ROADMAP.md\` |"

fresh
grill 2026-01-02-alpha.md '# Grill: alpha (2026-01-02)' "$P Status: **parked** by Robin, 2026-01-04. Feeds: the alpha spec."
expect parked 0 "$HEAD
| [alpha](2026-01-02-alpha.md) | **parked** (2026-01-04) | the alpha spec |"

# Every shape today's grill files have: a note after the date, "Feeds" with no
# colon, another sentence after the feeds, a pipe to escape; README.md is not
# a grill; rows come in file-name order.
fresh
grill 2026-01-03-b.md '# Grill: the `b` | c skill (2026-01-03)' "$P Status: **confirmed** by Robin, 2026-01-03 (\"ok\"). Feeds the b specs (no version, ADR 0001)."
grill 2026-01-01-a.md '# Grill: a (2026-01-01)' "$P Status: **confirmed** by Robin, 2026-01-02, with every grill. Feeds: the a spec (not yet written). Glossary: [G](../../G.md)."
printf '# Grills\n\nStatus: **open**. Feeds: nothing.\n' > "$tmp/g/README.md" || { echo "FAIL setup"; exit 1; }
printf 'not a grill\n' > "$tmp/g/notes.txt" || { echo "FAIL setup"; exit 1; }
expect shapes 0 "$HEAD
| [a](2026-01-01-a.md) | **confirmed** (2026-01-02) | the a spec (not yet written) |
| [the \`b\` \\| c skill](2026-01-03-b.md) | **confirmed** (2026-01-03) | the b specs (no version, ADR 0001) |"

# --- Refusals: nothing on stdout, the reason on stderr, exit 1 ---

fresh
grill 2026-01-02-alpha.md '# Grill: alpha (2026-01-02)' "$P Status: **open**. Feeds: the alpha spec."
grill 2026-01-03-beta.md '# Grill: beta' "$P Status: **open**. Feeds: the beta spec."
expect no-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 1 is not \`# Grill: <topic> (<YYYY-MM-DD>)\`"

fresh
grill 2026-01-03-beta.md '# Beta (2026-01-03)' "$P Status: **open**. Feeds: the beta spec."
expect no-title 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 1 is not \`# Grill: <topic> (<YYYY-MM-DD>)\`"

fresh
printf '# Grill: beta (2026-01-03)\n\n## Round 1\n\n%s Status: **open**. Feeds: x.\n' "$P" > "$tmp/g/2026-01-03-beta.md"
expect status-late 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **done**. Feeds: the beta spec."
expect status-unknown 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **confirmed** by Robin. Feeds: the beta spec."
expect confirmed-no-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **parked**. Feeds: the beta spec."
expect parked-no-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **open**. Status: **confirmed** by Robin, 2026-01-04. Feeds: the beta spec."
expect two-statuses 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has more than one \`Status:\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **open** **confirmed** by Robin, 2026-01-04. Feeds: the beta spec."
expect open-then-more 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **open**."
expect no-feeds 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Feeds\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **open**. Feeds: ."
expect empty-feeds 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Feeds\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-13-40)' "$P Status: **open**. Feeds: the beta spec."
expect title-bad-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 1 is not \`# Grill: <topic> (<YYYY-MM-DD>)\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-04)' "$P Status: **open**. Feeds: the beta spec."
expect title-other-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: the file name's date is not the title's"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **confirmed** by Robin, 2026-02-30. Feeds: the beta spec."
expect status-bad-date 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

fresh
grill 2026-01-03-beta.md '# Grill: beta (2026-01-03)' "$P Status: **open**.x Feeds: the beta spec."
expect open-glued 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

for name in '2026-01-03 beta.md' '2026-01-03-Beta.md' '2026-1-3-beta.md' '2026-01-03-.md' 'beta.md'; do
  fresh
  grill "$name" '# Grill: beta (2026-01-03)' "$P Status: **open**. Feeds: the beta spec."
  expect "name '$name'" 1 '' "index.sh: $tmp/g/$name: the file name is not \`<YYYY-MM-DD>-<topic>.md\` (lowercase letters, digits, dots and hyphens)"
done

# A topic's brackets can't open a second link inside the row's.
fresh
grill 2026-01-03-beta.md '# Grill: [beta](x.md) (2026-01-03)' "$P Status: **open**. Feeds: the [beta](y.md) spec."
expect brackets 0 "$HEAD
| [\\[beta\\](x.md)](2026-01-03-beta.md) | **open** | the [beta](y.md) spec |"

# Every bad file is named, not only the first.
fresh
grill 2026-01-03-beta.md '# Beta' "$P Status: **open**. Feeds: x."
grill 2026-01-04-gamma.md '# Grill: gamma (2026-01-04)' "$P Status: **gone**. Feeds: x."
expect every-bad-file 1 '' "index.sh: $tmp/g/2026-01-03-beta.md: line 1 is not \`# Grill: <topic> (<YYYY-MM-DD>)\`
index.sh: $tmp/g/2026-01-04-gamma.md: line 3 has no \`Status: **open**\`, \`**parked** by <User>, <YYYY-MM-DD>\` or \`**confirmed** by <User>, <YYYY-MM-DD>\`"

# --- Unreadable: exit 2 ---

fresh
rm -rf "$tmp/g"
expect no-folder 2 '' "index.sh: cannot read the folder $tmp/g"

fresh
grill 2026-01-02-alpha.md '# Grill: alpha (2026-01-02)' "$P Status: **open**. Feeds: the alpha spec."
chmod 000 "$tmp/g/2026-01-02-alpha.md"
if [ -r "$tmp/g/2026-01-02-alpha.md" ]; then
  # root reads any file: the case can't be built here, so it counts as a fail.
  cases=$((cases + 1)) fails=$((fails + 1))
  echo "FAIL unreadable-file: this user can read a file with mode 000 (run as a user other than root)"
else
  expect unreadable-file 2 '' "index.sh: cannot read $tmp/g/2026-01-02-alpha.md"
fi
chmod 644 "$tmp/g/2026-01-02-alpha.md"

# --- The default folder, docs/grills, is the consumer's and optional (E7) ---

# expect_default NAME STATUS STDOUT [STDERR]: index.sh with no folder, from $tmp/p.
expect_default() {
  cases=$((cases + 1))
  out=$(cd "$tmp/p" && sh "$INDEX" 2> "$tmp/err")
  code=$?
  err=$(cat "$tmp/err")
  if [ "$code" != "$2" ] || [ "$out" != "$3" ] || [ "$err" != "${4:-}" ]; then
    fails=$((fails + 1))
    echo "FAIL $1: exit $code (want $2)"
    printf '  stdout:\n%s\n  want:\n%s\n  stderr:\n%s\n  want:\n%s\n' "$out" "$3" "$err" "${4:-}"
  else
    echo "ok $1"
  fi
}

rm -rf "$tmp/p" && mkdir "$tmp/p" || { echo "FAIL setup"; exit 1; }
expect_default default-absent 0 '' 'index.sh: this project has no docs/grills folder, so there is no grill index'

mkdir -p "$tmp/p/docs/grills" || { echo "FAIL setup"; exit 1; }
printf '%s\n\n%s\n' '# Grill: alpha (2026-01-02)' "$P Status: **open**. Feeds: the alpha spec." > "$tmp/p/docs/grills/2026-01-02-alpha.md"
expect_default default-present 0 "$HEAD
| [alpha](2026-01-02-alpha.md) | **open** | the alpha spec |"

if [ "$cases" -ne "$CASES" ]; then
  echo "FAIL ran $cases cases, want $CASES"
  fails=$((fails + 1))
fi
if [ "$fails" -ne 0 ]; then
  echo "FAIL $fails of $cases"
  exit 1
fi
echo "PASS $cases cases"
