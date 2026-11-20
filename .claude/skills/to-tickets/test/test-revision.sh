#!/bin/sh
# Tests ../revision.sh, version 2, on this folder's fake gh, with a synthetic
# spec #8 and tickets #9 to #12 built here, beside another spec's #4 to #7.
# Moved beside the skill from the evidence of ClosedWiz#155 (#191), with the
# same cases; it reads nothing outside this skill's folder.
# 1. The revision text is exactly the documented v2 format: each body hashed
#    with its ticked task boxes read as unticked. The expected text is built
#    here from literal bodies written unticked, never by the script's method.
# 2. Ticking or unticking a task box (in a ticket or in the spec; `-`, `*` or
#    `+`; `x` or `X`; nested; at a line's end; in a CRLF body) leaves the
#    fingerprint as it was. So do labels (`held` too), comments, closing and
#    the milestone.
# 3. Every other edit still changes it: the spec's body, a box's words, a box
#    added, dropped, turned to plain text, its bullet or indent changed, an
#    `[x]` that is not a task box, a title, a blocker, a ticket added or dropped.
# 4. A read that fails gives a non-zero exit and no text at all.
# 5. An approval recorded under v1 is stale under v2: v1's script
#    (revision-v1.sh here: ClosedWiz's main at 9f5b557, byte for byte) gives a
#    different fingerprint for the same plan.
# Usage, from anywhere: sh skills/to-tickets/test/test-revision.sh
#   (REVISION_SH=<script> tests another script in its place)
# Needs python3, jq and sha256sum (or shasum). Exits 0 only when every case
# ran and matches; 1 on any mismatch, a missing case or a setup failure.
set -u
here=$(cd "$(dirname "$0")" && pwd) || exit 1
script=${REVISION_SH:-$here/../revision.sh}
fake=$here/fake_gh.py
v1=$here/revision-v1.sh
[ -f "$script" ] || { echo "SETUP: no script at $script"; exit 1; }
[ -f "$fake" ] && [ -f "$v1" ] || { echo "SETUP: the fake gh or revision-v1.sh is missing"; exit 1; }
for tool in python3 jq; do
  command -v "$tool" > /dev/null 2>&1 || { echo "SETUP: $tool is missing"; exit 1; }
done
work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" || exit 1
printf '#!/bin/sh\nexec python3 -I "%s" "$@"\n' "$fake" > "$work/bin/gh" && chmod +x "$work/bin/gh" || exit 1
PATH="$work/bin:$PATH"
export PATH
CASES=42 # every case below; fewer run means one was skipped
cases=0
bad=0
args=8
if command -v sha256sum > /dev/null 2>&1; then
  sha() { sha256sum | cut -d' ' -f1; }
else
  sha() { shasum -a 256 | cut -d' ' -f1; }
fi
cr=$(printf '\r')

# ---- The base: another spec #4 and its tickets, then spec #8 and its #9 to #12 ----
spec_body='## Problem Statement

Synthetic.

- [ ] the spec has a box too
'
t9_body='## What to build

Synthetic nine. Marks are written `- [ ]` in its notes.

## Owned paths

`src/nine/`

## Acceptance criteria

- [ ] nine works
* [ ] nine is fast
+ [ ] nine is small
  - [ ] nine nests
- [ ]
'
# #10 arrives with its box already ticked; the revision reads it as unticked.
t10_body='## What to build

Synthetic ten.

## Owned paths

`contracts/ten.v1.md`

## Acceptance criteria

- [x] ten is written
'
t10_unticked='## What to build

Synthetic ten.

## Owned paths

`contracts/ten.v1.md`

## Acceptance criteria

- [ ] ten is written
'
t11_body='## What to build

Synthetic eleven.

## Owned paths

`src/eleven/`

## Relies on

`contracts/ten.v1.md`

## Acceptance criteria

- [ ] eleven works
- [ ] eleven is quiet
'
# #12's body has CRLF line ends, as a body saved from GitHub's web editor can.
t12_body=$(printf '## What to build\r\n\r\nSynthetic twelve.\r\n\r\n- [ ] twelve works\r\nx')
t12_body=${t12_body%x}
mkdir -p "$work/base" || exit 1
python3 -I - "$work/base/state.json" "$work/base.json" "$spec_body" "$t9_body" "$t10_body" "$t11_body" "$t12_body" <<'EOF' || { echo "SETUP: cannot write the base world"; exit 1; }
import json, sys
state, event, spec, t9, t10, t11, t12 = sys.argv[1:]
def old(n, title, parent, blocked):
    return {"number": n, "title": title, "body": "(synthetic: another spec's)\n", "state": "OPEN", "parent": parent,
            "milestone": "0.2.0", "blockedBy": blocked, "labels": ["ready-for-agent"] if parent else [], "comments": []}
json.dump({"next_issue": 8, "issues": [
    old(4, "0.2.0 spec: Settings", None, []),
    old(5, "0.2.0 T1: the settings.v1 contract", 4, []),
    old(6, "0.2.0 T2: reads its settings file", 4, [5]),
    old(7, "0.2.0 T3: a settings page", 4, [6]),
]}, open(state, "w"))
json.dump({"create": [
    {"title": "0.3.0 spec: Synthetic", "body": spec, "milestone": "0.3.0", "parent": None},
    {"title": "0.3.0 T1: nine", "body": t9, "milestone": "0.3.0", "parent": 8, "labels": ["ready-for-agent"]},
    {"title": "0.3.0 T2: ten", "body": t10, "milestone": "0.3.0", "parent": 8},
    {"title": "0.3.0 T3: eleven", "body": t11, "milestone": "0.3.0", "parent": 8, "blockedBy": [10, 9, 6]},
    {"title": "0.3.0 T4: twelve", "body": t12, "milestone": "0.3.0", "parent": 8},
]}, open(event, "w"))
EOF
FAKE_GH_STATE=$work/base python3 -I "$fake" --world "$work/base.json" || { echo "SETUP: base world event failed"; exit 1; }

# The text the documented v2 format gives for the base, built here from the
# literal bodies (each already unticked), not by the script.
h() { printf '%s\n' "$1" | sha; }
expected="plan-graph revision v2
spec #8 body sha256 $(h "$spec_body")
ticket #9 blocked-by none body sha256 $(h "$t9_body") title 0.3.0 T1: nine
ticket #10 blocked-by none body sha256 $(h "$t10_unticked") title 0.3.0 T2: ten
ticket #11 blocked-by #6 #9 #10 body sha256 $(h "$t11_body") title 0.3.0 T3: eleven
ticket #12 blocked-by none body sha256 $(h "$t12_body") title 0.3.0 T4: twelve"
case $t12_body in *"$cr"*) ;; *) echo "SETUP: #12's body has no CR"; exit 1 ;; esac

# run_ <name> [event.json] [script]: a fresh copy of the base, the event
# applied, then the script (the one under test unless given) with the
# arguments in $args. Sets got_exit, got_out (stdout) and got_fp.
run_() {
  rm -rf "$work/$1" && cp -R "$work/base" "$work/$1" || exit 1
  if [ -n "${2:-}" ]; then
    printf '%s\n' "$2" > "$work/$1.json" || exit 1
    FAKE_GH_STATE=$work/$1 python3 -I "$fake" --world "$work/$1.json" || { echo "SETUP: event for $1 failed"; exit 1; }
  fi
  # shellcheck disable=SC2086
  FAKE_GH_STATE=$work/$1 sh "${3:-$script}" $args > "$work/$1.out" 2> "$work/$1.err"
  got_exit=$?
  got_out=$(cat "$work/$1.out") || exit 1
  got_fp=$(sha < "$work/$1.out") || exit 1
}
ok() { echo "ok   $*"; }
no() { bad=$((bad + 1)); echo "MISMATCH $*"; }

# 1. The format, exactly, and the same twice.
cases=$((cases + 1))
run_ baseline
base_fp=$got_fp
if [ "$got_exit" = 0 ] && [ "$got_out" = "$expected" ]; then
  ok "baseline: exit 0, the documented v2 text exactly (fingerprint $base_fp)"
else
  no "baseline: exit $got_exit; the text differs from the documented v2 format:"
  printf '%s\n' "$expected" > "$work/expected.txt"
  diff "$work/expected.txt" "$work/baseline.out" | sed 's/^/    /'
fi
cases=$((cases + 1))
run_ again
if [ "$got_exit" = 0 ] && [ "$got_fp" = "$base_fp" ]; then ok "again: the same fingerprint"; else no "again: exit $got_exit, fingerprint $got_fp"; fi

# 2 and 3. changes <name> <yes|no> <event>: does the fingerprint move?
changes() {
  cases=$((cases + 1))
  run_ "$1" "$3"
  if [ "$got_exit" != 0 ]; then
    no "$1: exit $got_exit: $(cat "$work/$1.err")"
  elif [ "$2" = yes ] && [ "$got_fp" != "$base_fp" ]; then
    ok "$1: the fingerprint changes"
  elif [ "$2" = no ] && [ "$got_fp" = "$base_fp" ]; then
    ok "$1: the fingerprint stays the same"
  else
    no "$1: want a change: $2; got fingerprint $got_fp (base $base_fp)"
  fi
}
# Progress: a box ticked or unticked.
changes tick-ticket-box no '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- [x] eleven works"]}]}'
changes tick-capital-x no '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- [X] eleven works"]}]}'
changes tick-two-boxes no '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works\n- [ ] eleven is quiet", "- [x] eleven works\n- [x] eleven is quiet"]}]}'
changes untick-ticked-box no '{"edit": [{"issue": 10, "replace": ["- [x] ten is written", "- [ ] ten is written"]}]}'
changes tick-star-bullet no '{"edit": [{"issue": 9, "replace": ["* [ ] nine is fast", "* [x] nine is fast"]}]}'
changes tick-plus-bullet no '{"edit": [{"issue": 9, "replace": ["+ [ ] nine is small", "+ [x] nine is small"]}]}'
changes tick-nested-box no '{"edit": [{"issue": 9, "replace": ["  - [ ] nine nests", "  - [x] nine nests"]}]}'
changes tick-box-at-line-end no '{"edit": [{"issue": 9, "replace": ["- [ ]\n", "- [x]\n"]}]}'
changes tick-spec-box no '{"edit": [{"issue": 8, "replace": ["- [ ] the spec has a box too", "- [x] the spec has a box too"]}]}'
changes tick-crlf-box no '{"edit": [{"issue": 12, "replace": ["- [ ] twelve works\r", "- [x] twelve works\r"]}]}'
# Not plan changes (as in v1).
changes add-label no '{"labels": [{"issue": 10, "add": ["ready-for-agent"]}]}'
changes remove-label no '{"labels": [{"issue": 9, "remove": ["ready-for-agent"]}]}'
changes held-label-on no '{"labels": [{"issue": 9, "add": ["held"], "remove": ["ready-for-agent"]}]}'
changes comment-on-spec no '{"comment": [{"issue": 8, "body": "**Plan graph approved by Robin, 2026-10-31, revision 9:** \"approve\"\n"}]}'
changes public-approval-on-spec no '{"comment": [{"issue": 8, "body": "**Plan graph approved by Robin, 2026-10-31, revision 9:** approved as proposed.\nPrivate record: https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000002\n"}]}'
changes comment-on-ticket no '{"comment": [{"issue": 11, "body": "Progress: eleven works.\n"}]}'
changes close-ticket no '{"close": [9]}'
changes milestone no '{"edit": [{"issue": 9, "milestone": "0.2.0"}]}'
# Plan changes (as in v1), and the edits next to a box that are still plan changes.
changes spec-body yes '{"edit": [{"issue": 8, "replace": ["Synthetic.", "Synthetic, and one more promise."]}]}'
changes box-words yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- [ ] eleven works offline"]}]}'
changes tick-and-reword yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- [x] eleven works offline"]}]}'
changes box-added yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven is quiet", "- [ ] eleven is quiet\n- [ ] eleven is fast"]}]}'
changes box-dropped yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven is quiet\n", ""]}]}'
changes box-to-plain-text yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- eleven works"]}]}'
changes bullet-changed yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "* [ ] eleven works"]}]}'
changes indent-changed yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "  - [ ] eleven works"]}]}'
changes not-a-task-box yes '{"edit": [{"issue": 9, "replace": ["written `- [ ]` in", "written `- [x]` in"]}]}'
changes box-letter-y yes '{"edit": [{"issue": 11, "replace": ["- [ ] eleven works", "- [y] eleven works"]}]}'
changes owned-paths yes '{"edit": [{"issue": 11, "replace": ["`src/eleven/`", "`src/eleven/`, `src/shared/`"]}]}'
changes relies-on yes '{"edit": [{"issue": 11, "replace": ["`contracts/ten.v1.md`\n\n## Acceptance", "`contracts/ten.v2.md`\n\n## Acceptance"]}]}'
changes ticket-title yes '{"edit": [{"issue": 10, "title": "0.3.0 T2: ten, renamed"}]}'
changes add-blocker yes '{"add_blocked_by": [{"issue": 10, "blocker": 9}]}'
changes drop-ticket yes '{"remove_sub_issue": [10]}'
changes new-ticket yes '{"create": [{"title": "0.3.0 T5: thirteen", "body": "## What to build\n\nThirteen.\n", "milestone": "0.3.0", "parent": 8}]}'

# 4. Failed reads: non-zero, and no text that could pass for a revision.
fails() {
  cases=$((cases + 1))
  if [ "$got_exit" = "$2" ] && [ -z "$got_out" ]; then
    ok "$1: exit $got_exit, no text"
  else
    no "$1: want exit $2 and no text; got exit $got_exit and $(printf '%s' "$got_out" | wc -l | tr -d ' ') lines"
  fi
}
args=99
run_ no-such-spec
fails no-such-spec 1
args=8
run_ unreadable-ticket '{"unreadable": [10]}'
fails unreadable-ticket 1
run_ unreadable-spec '{"unreadable": [8]}'
fails unreadable-spec 1
args=
run_ no-argument
fails no-argument 2
args=8x
run_ not-a-number
fails not-a-number 2
args=8

# 5. A v1 approval of this same plan: v1's own script.
cases=$((cases + 1))
run_ v1 '' "$v1"
v1_head=$(head -n 1 "$work/v1.out")
if [ "$got_exit" = 0 ] && [ "$v1_head" = "plan-graph revision v1" ] && [ "$got_fp" != "$base_fp" ]; then
  ok "v1-approval-stale: v1's script prints a v1 text, with another fingerprint ($got_fp): a v1 approval is stale"
else
  no "v1-approval-stale: v1's script exited $got_exit, first line '$v1_head', fingerprint $got_fp (now $base_fp)"
fi

[ "$cases" = "$CASES" ] || no "every case ran: $cases ran, not $CASES"
echo "$cases cases, $bad mismatched"
[ "$bad" -eq 0 ]
