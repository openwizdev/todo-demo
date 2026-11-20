#!/bin/sh
# #379: ticketless research snapshot/check. gh and jq only, GET requests only.
# REST shapes: https://docs.github.com/en/rest/branches/branches#list-branches
# https://docs.github.com/en/rest/pulls/pulls#list-pull-requests
# Snapshot files contain private repository metadata: keep outside Git.
# Exit 0 = checked surfaces unchanged or explicitly acknowledged;
# 1 = unexplained changes; 2 = incomplete check. Neither 1 nor 2 is clean.
set -u
fail() { printf 'check-workers.sh: %s\n' "$*" >&2; exit 2; }
usage() { fail 'usage: check-workers.sh snapshot | check SNAPSHOT [--allow EXACT-CHANGES.json]'; }
command -v gh >/dev/null 2>&1 || fail 'gh is required'
command -v jq >/dev/null 2>&1 || fail 'jq is required'
work=$(mktemp -d) || fail 'cannot create temporary directory'
trap 'rm -rf "$work"' EXIT
trap 'exit 2' HUP INT TERM
mode=${1:-}
allow=''
case $mode in
  snapshot)
    [ "$#" = 1 ] || usage
    repo=${GH_REPO:-}
    if [ -z "$repo" ]; then
      repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner) || fail 'cannot read repository'
    fi ;;
  check)
    [ "$#" = 2 ] || [ "$#" = 4 ] || usage
    if [ "$#" = 4 ]; then
      [ "$3" = '--allow' ] || usage
      allow=$4
    fi
    # Validate the saved snapshot before using its repository or contents.
    jq -e -s 'length == 1 and (.[0] | type == "object" and keys == ["items", "repo", "version"]
      and .version == 1 and (.repo | type) == "string" and (.items | type) == "object"
      and all(.items | to_entries[];
        if .key | startswith("branch ") then (.value | type) == "string" and (.value | test("^[0-9a-f]{40}$"))
        elif .key | test("^pull request #[1-9][0-9]*$") then (.value | type) == "object"
        elif .key | test("^(review )?comment [1-9][0-9]*$") then (.value | type) == "object"
        else false end))' "$2" >/dev/null 2>&1 || fail 'invalid snapshot'
    cat "$2" > "$work/before" || fail 'cannot read snapshot'
    repo=$(jq -r .repo "$work/before") || fail 'cannot read snapshot repository' ;;
  *) usage ;;
esac
case $repo in
  */*/* | /* | */ | *[!A-Za-z0-9._/-]* | '') fail 'repository must be owner/name' ;;
  ?*/?*) ;;
  *) fail 'repository must be owner/name' ;;
esac

# --slurp retains page boundaries, so even an empty or malformed page is checked.
# Do not use updated_at on PRs: unrelated CI activity can update it.
lib='
def number: type == "number" and . > 0 and . == floor;
def text: type == "string";
def nullable_text: . == null or text;
def sha: text and test("^[0-9a-f]{40}$");
def side: type == "object" and (.ref | text) and (.sha | sha)
  and (.repo == null or ((.repo | type) == "object" and (.repo.full_name | text)));
def unique_items: if (map(.key) | unique | length) == length then from_entries else error("duplicate identity") end;
def pages: if type == "array" and length > 0 and all(.[]; type == "array") then add else error("incomplete pages") end;
'
read_list() {
  name=$1 endpoint=$2 filter=$3
  gh api --method GET --paginate --slurp "repos/$repo/$endpoint" > "$work/raw" 2> "$work/error" \
    || fail "cannot read $name (gh failed)"
  jq -e -c "$lib pages | $filter | unique_items" "$work/raw" > "$work/$name" 2> "$work/error" \
    || fail "cannot read $name (invalid or incomplete JSON)"
  # More than one outer JSON value is also an incomplete/ambiguous read.
  jq -e -s 'length == 1' "$work/$name" >/dev/null || fail "cannot read $name (multiple responses)"
}
read_list branches 'branches?per_page=100' 'map(
  if type == "object" and (.name | text) and (.name | length) > 0
     and (.commit | type) == "object" and (.commit.sha | sha)
  then {key: ("branch " + .name), value: .commit.sha} else error("invalid branch") end)'
read_list pulls 'pulls?state=all&per_page=100' 'map(
  if type == "object" and (.number | number) and (.state == "open" or .state == "closed")
     and has("merged_at") and (.merged_at | nullable_text) and (.draft | type) == "boolean"
     and (.title | text) and has("body") and (.body | nullable_text)
     and (.head | side) and (.base | type) == "object" and (.base.ref | text)
     and (.base.repo.full_name | text)
  then {key: "pull request #\(.number)", value: {state, merged_at, draft, title, body,
    head: {ref: .head.ref, sha: .head.sha, repo: .head.repo.full_name},
    base: {ref: .base.ref, repo: .base.repo.full_name}}} else error("invalid pull request") end)'
comments='map(if type == "object" and (.id | number) and (.body | text) and (.updated_at | text)
  then {key: ($kind + " \(.id)"), value: {body, updated_at}} else error("invalid comment") end)'
read_list comments 'issues/comments?per_page=100' "\"comment\" as \$kind | $comments"
read_list review-comments 'pulls/comments?per_page=100' "\"review comment\" as \$kind | $comments"
jq -c -n --arg repo "$repo" --slurpfile b "$work/branches" --slurpfile p "$work/pulls" \
  --slurpfile c "$work/comments" --slurpfile r "$work/review-comments" \
  '{version: 1, repo: $repo, items: ($b[0] + $p[0] + $c[0] + $r[0])}' > "$work/after" || fail 'cannot assemble snapshot'
if [ "$mode" = snapshot ]; then
  cat "$work/after"
  exit $?
fi
if [ -n "$allow" ]; then
  jq -e -s 'length == 1 and (.[0] | type == "object")' "$allow" >/dev/null 2>&1 || fail 'invalid allowance file'
  cat "$allow" > "$work/allow" || fail 'cannot read allowance file'
else
  printf '{}\n' > "$work/allow"
fi
jq -r -n --slurpfile b "$work/before" --slurpfile a "$work/after" --slurpfile allow "$work/allow" '
  $b[0].items as $before | $a[0].items as $after | $allow[0] as $allowed
  | [($before + $after | keys[]) as $key | select($before[$key] != $after[$key]) | $key] as $changed
  | if all($allowed | to_entries[]; .key as $key
      | ($changed | index($key)) != null and .value == $after[$key]) then .
    else error("allowance must name an actual change and its exact resulting value (null for deletion)") end
  | $changed[] | . as $key | select($allowed | has($key) | not)
  | "hit research: \(.)"
' > "$work/hits" 2> "$work/error" || fail 'allowance does not match observed changes'
if [ -s "$work/hits" ]; then
  cat "$work/hits"
  exit 1
fi
printf 'clean research: no unexplained changes in checked GitHub surfaces\n'
