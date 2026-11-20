#!/bin/sh
# Prints the revision text of a spec's plan graph, as the plan-graph skill
# defines it ("Is an approval current?" in SKILL.md): the spec's body, and
# each of its tickets' number, blockers, body and title. Its SHA-256 is the
# fingerprint an approval records.
#
# Usage: sh revision.sh <spec issue number>
#   then: sha256sum on the output (on macOS: shasum -a 256)
# Runs only `gh issue view` reads. Exits 0 and prints the text; exits 1, and
# prints nothing on stdout, if any read fails; exits 2 on a bad argument.
set -u
spec=${1:-}
case $spec in
  '' | *[!0-9]*)
    echo "usage: sh revision.sh <spec issue number>" >&2
    exit 2
    ;;
esac
if command -v sha256sum > /dev/null 2>&1; then
  hash() { sha256sum < "$1" | cut -d' ' -f1; }
elif command -v shasum > /dev/null 2>&1; then
  hash() { shasum -a 256 < "$1" | cut -d' ' -f1; }
else
  echo "revision.sh: needs sha256sum or shasum" >&2
  exit 1
fi
fail() {
  echo "revision.sh: $*" >&2
  exit 1
}
work=$(mktemp -d) || fail "cannot make a temporary folder"
trap 'rm -rf "$work"' EXIT
tab=$(printf '\t')

# The spec's tickets: its sub-issues, as many as GitHub counts.
gh issue view "$spec" --json subIssues --jq '.subIssues.totalCount, (.subIssues.nodes[].number)' > "$work/members" ||
  fail "cannot read spec #$spec's tickets"
total=$(head -n 1 "$work/members")
tail -n +2 "$work/members" | sort -n > "$work/tickets" || fail "cannot sort the tickets"
count=$(wc -l < "$work/tickets" | tr -d ' ')
[ "$count" = "$total" ] || fail "spec #$spec has $total tickets, but $count were listed"

gh issue view "$spec" --json body --jq '.body' > "$work/body" || fail "cannot read spec #$spec's body"
body_hash=$(hash "$work/body")
[ "${#body_hash}" = 64 ] || fail "cannot hash spec #$spec's body"
{
  echo "plan-graph revision v1"
  echo "spec #$spec body sha256 $body_hash"
} > "$work/out" || fail "cannot write the text"

while read -r n; do
  gh issue view "$n" --json number,title,blockedBy --jq '"#\(.number)\t\([.blockedBy.nodes[].number] | sort | map("#" + tostring) | join(" ") | if . == "" then "none" else . end)\t\(.title)"' > "$work/meta" ||
    fail "cannot read ticket #$n"
  gh issue view "$n" --json body --jq '.body' > "$work/body" || fail "cannot read ticket #$n's body"
  IFS=$tab read -r number blockers title < "$work/meta" || fail "cannot read ticket #$n's title and blockers"
  [ "$number" = "#$n" ] && [ -n "$blockers" ] && [ -n "$title" ] || fail "ticket #$n's title or blockers are missing"
  body_hash=$(hash "$work/body")
  [ "${#body_hash}" = 64 ] || fail "cannot hash ticket #$n's body"
  printf 'ticket %s blocked-by %s body sha256 %s title %s\n' "$number" "$blockers" "$body_hash" "$title" >> "$work/out" ||
    fail "cannot write the text"
done < "$work/tickets"

cat "$work/out"
