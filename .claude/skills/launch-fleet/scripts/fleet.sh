#!/bin/sh
# launch-fleet's helper (OpenWiz 0.0.5, ClosedWiz#102). It reads a project's
# fleets from GitHub with `gh` and `jq`, and prints what is due. It never
# writes to GitHub: the agent that reads its lines does the work. Successful
# REST responses are cached locally and revalidated with conditional GETs.
#
#   sh fleet.sh [check]               every item due now, one line each; nothing when nothing is
#   sh fleet.sh frontier              every ticket that may start now: "#N title"
#                                     (a ticket of an approved plan graph, or an
#                                     issue approved on its own, its blockers merged)
#   sh fleet.sh holds                 every contract change note due for a builder
#   sh fleet.sh claim N COMMENT_ID    after a tick posts a claim on ticket or pull request N:
#                                     "go #N" if the claim is the oldest live one and N is
#                                     still due, else "withdraw #N: <why>"
#   sh fleet.sh wake N...             after GitHub's messages name issues and pull requests
#                                     N...: the lines due on those alone, read alone, and
#                                     "wake fleet #S: ..." for a spec with a fleet thread
#   sh fleet.sh spec S                a fleet thread's check (ClosedWiz#192): the lines
#                                     due on spec S alone, read as the check reads it
#   sh fleet.sh every                 the check's lines on every spec, fleet threads'
#                                     too: a fleet thread's read before a merge
#
# The repository is $GH_REPO (owner/name), else the clone you are in. It reads
# docs/agents/fleet.md (the CI checks) and docs/agents/triage-labels.md (the
# labels) from the default branch. The files of merged pull requests are cached
# in $LAUNCH_FLEET_CACHE (default ~/.cache/launch-fleet): they never change.
# The same sandbox cache holds ETagged REST answers, revalidated on every read.
# Before a ticket of a spec may start, the spec's latest plan graph approval
# must be current: to-tickets’ revision.sh ($LAUNCH_FLEET_REVISION, default
# ../../to-tickets/revision.sh from this file) prints the plan as it is now,
# and its SHA-256 must be the approval's fingerprint.
# $LAUNCH_FLEET_NOW (seconds since 1970) stands in for the clock in tests.
#
# GitHub's allowance (ClosedWiz#189): every agent on the account shares its
# GraphQL points, so the check asks as little as it can. Each spec is read in
# one query that asks for as many tickets as it has. A spec with no open
# ticket is skipped once a check found nothing due on it, until it changes
# (its updatedAt or its ticket counts).
# A spec's fingerprint is reused from the cache until the spec's updatedAt or
# anything revision.sh reads changes. On stderr it prints one line: the points
# used (GitHub's cost for each of its reads, and one for each question
# revision.sh asks), the questions asked, and the points GitHub says are left.
# When fewer than a quarter of the hour's points are left, or none, it backs
# off instead: one line on stderr, nothing on stdout, exit 0. A read that
# fails after the first still fails loudly.
#
# A wake (ClosedWiz#259) reads only what GitHub's messages named: one read
# for each number (a pull request with the tickets it closes, a ticket with
# its spec's approval, an issue approved on its own), a spec in full, and the
# spec of a ticket that could start, for its approval. It prints the check's
# lines about those items. A claim reads only its own ticket or pull request,
# the same way.
#
# One fleet thread per spec (ClosedWiz#192, ADR 0011). A spec's fleet thread
# records itself on the spec: "launch-fleet: fleet active, loop <id>"; the
# latest such record names the spec's fleet. The check and a wake leave a spec
# with a fleet thread to it: only `spec S` prints that spec's lines. A wake
# naming anything in such a spec prints one line instead (GI2, #2544),
# "wake fleet #S: room-cli loop run <loop id>", for the tick to run that
# thread's own loop now; a record naming no loop, or a loop another spec of
# the wake also names, gets no line, as before. In `spec
# S`, a builder or reviewer recorded (its record last edited) before the fleet
# thread's record was started by an earlier fleet or tick, so the fleet can't
# reach it: the check asks the orchestrator to archive that builder, then has
# the fleet start its own on the same branch, and gives up on that reviewer
# at once, so a fresh one starts. `spec S` on an issue that is no open spec
# prints "fleet done #S".
#
# Exit 0 with the answer on stdout. Exit 2 on any error, with the reason on
# stderr; never 1, which a CloudRoom loop's check takes as "nothing due".

die() { printf 'fleet.sh: %s\n' "$*" >&2; exit 2; }
usage() { die "usage: fleet.sh [check | frontier | holds | every | claim NUMBER COMMENT_ID | wake NUMBER... | spec NUMBER]"; }
is_number() { case $1 in '' | *[!0-9]*) return 1 ;; esac; }

cmd=${1:-check}
[ $# -gt 0 ] && shift
# CS5 is a finite pre-effect guard over the orchestrator's existing reads.
# No API, authentication or cache machinery runs on this path. Unknown input
# refuses new work, while completion and reconciliation remain available.
if [ "$cmd" = overload ]; then
  [ $# -eq 1 ] || die "overload needs one action"
  [ -n "${GH_REPO:-}" ] && [ -n "${LAUNCH_FLEET_OVERLOAD_STATE:-}" ] \
    || die "overload needs GH_REPO and LAUNCH_FLEET_OVERLOAD_STATE"
  # MT6 (#825): with LAUNCH_FLEET_OVERLOAD_SUPPLY (an OpenWiz checkout's
  # absolute tools/ci-overload/supply.py), new work reads the collector's queue
  # now into this call's own private file, which only this call's guard reads;
  # the caller's input is never used then. A supplier that fails, or can't
  # start, leaves the guard a missing input, so it refuses as unknown.
  # Completion and reconciliation read nothing more.
  input=${LAUNCH_FLEET_OVERLOAD_INPUT:-/nonexistent-overload-observation}
  case $1 in merge-batch | automatic-refresh | nonessential-poll)
    if [ -n "${LAUNCH_FLEET_OVERLOAD_SUPPLY:-}" ]; then
      case $LAUNCH_FLEET_OVERLOAD_SUPPLY in /*) ;;
        *) die "LAUNCH_FLEET_OVERLOAD_SUPPLY must be absolute" ;;
      esac
      input=/nonexistent-overload-observation
      if own=$(mktemp -d 2> /dev/null); then
        trap 'rm -rf "$own"' EXIT
        trap 'exit 2' HUP INT TERM
        python3 -I "$LAUNCH_FLEET_OVERLOAD_SUPPLY" --repository "$GH_REPO" \
          --output "$own/observation.json" < /dev/null > /dev/null 2>&1 \
          && input=$own/observation.json
      fi
    fi ;;
  esac
  python3 -I "$(dirname "$0")/carried/alarm.py" \
    --repository "$GH_REPO" --state "$LAUNCH_FLEET_OVERLOAD_STATE" --input "$input" \
    --now "${LAUNCH_FLEET_NOW:-$(date -u +%s)}" --action "$1"
  exit $?
fi
case $cmd in
  check | frontier | holds | every) [ $# -eq 0 ] || usage ;;
  claim) [ $# -eq 2 ] && is_number "$1" && [ ${#1} -le 9 ] && is_number "$2" || usage
    CLAIM_N=$1 CLAIM_ID=$2 WAKE=$1 ;;
  wake) [ $# -gt 0 ] || usage
    for n in "$@"; do is_number "$n" && [ ${#n} -le 9 ] || usage; done
    WAKE=$(printf '%s\n' "$@" | sort -n -u) ;;
  spec) [ $# -eq 1 ] && is_number "$1" && [ ${#1} -le 9 ] || usage
    case $1 in 0*) usage ;; esac
    SPEC=$1 ;;
  *) usage ;;
esac

GH=$(command -v gh 2> /dev/null) || die "gh is not installed"
case $GH in /*) ;; *) GH=$(pwd)/$GH ;; esac
command -v jq > /dev/null 2>&1 || die "jq is not installed"
if command -v sha256sum > /dev/null 2>&1; then SHA=sha256sum
elif command -v shasum > /dev/null 2>&1; then SHA='shasum -a 256'
else die "neither sha256sum nor shasum is installed"; fi
REVISION=${LAUNCH_FLEET_REVISION:-$(cd "$(dirname "$0")" && pwd)/../../to-tickets/revision.sh}
# F6 (#1353): the plan-links parser, to-tickets'"'"' check-links.sh, labels each link.
LINKS=${LAUNCH_FLEET_LINKS:-$(cd "$(dirname "$0")" && pwd)/../../to-tickets/check-links.sh}

NOW=${LAUNCH_FLEET_NOW:-$(date -u +%s)}
is_number "$NOW" || die "LAUNCH_FLEET_NOW must be a number of seconds"

TMP=$(mktemp -d) || die "can't make a temporary folder"
trap 'rm -rf "$TMP"' EXIT
trap 'exit 2' HUP INT TERM

# Every question to GitHub, this script's and revision.sh's, goes through a
# `gh` that counts it in $LAUNCH_FLEET_ASKED, for the points line; each 304
# is counted in $COUNTS/unchanged. A replay (GI1, #2543: the unchanged spec
# check's second process, below) asks through its parent's `gh` and counts.
REPLAY=${LAUNCH_FLEET_REPLAY:-}
if [ -n "$REPLAY" ]; then
  [ "$cmd" = spec ] && [ -d "$REPLAY/snap" ] && [ -f "$REPLAY/unchanged" ] || die "a replay is a spec check's own"
  COUNTS=$REPLAY
  : > "$TMP/asked-revision" && : > "$TMP/rate.txt" || die "can't count the questions"
else
  COUNTS=$TMP
  mkdir "$TMP/bin" && printf '%s\n' '#!/bin/sh' 'printf ".\n" >> "$LAUNCH_FLEET_ASKED" || exit 1' \
    'exec "$LAUNCH_FLEET_GH" "$@"' > "$TMP/bin/gh" && chmod +x "$TMP/bin/gh" && : > "$TMP/unchanged" \
    && : > "$TMP/asked" && : > "$TMP/asked-revision" && : > "$TMP/rate.txt" || die "can't count the questions"
  LAUNCH_FLEET_GH=$GH LAUNCH_FLEET_ASKED=$TMP/asked PATH=$TMP/bin:$PATH
  export LAUNCH_FLEET_GH LAUNCH_FLEET_ASKED PATH
fi
RECORD=''


REPO=${GH_REPO:-}
if [ -z "$REPO" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner) || die "set GH_REPO=owner/name, or run inside a clone"
fi
case $REPO in
  */*/* | /* | */ | *[!A-Za-z0-9._/-]*) die "GH_REPO must be owner/name, not '$REPO'" ;;
  ?*/?*) ;;
  *) die "GH_REPO must be owner/name, not '$REPO'" ;;
esac
OWNER=${REPO%%/*}
NAME=${REPO#*/}

# The cache: the files of merged pull requests (they never change), each
# spec's last fingerprint, and the specs found quiet. Without it, nothing is
# reused. Quiet/fingerprint entries hold only for this script's exact text
# ($SELF); raw HTTP entries use their request and cache-format version.
CACHE=${LAUNCH_FLEET_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/launch-fleet}/$OWNER/$NAME
umask 077
mkdir -p "$CACHE" 2> /dev/null || CACHE=''
SELF=$($SHA < "$0" 2> /dev/null | cut -c1-64)
case $SELF in *[!0-9a-f]* | '') CACHE='' ;; esac

# ---- GitHub reads ----

# The fields of a ticket, and of an issue approved on its own.
TICKET='number
        lastEditedAt editor { __typename login }
        timelineItems(itemTypes: [LABELED_EVENT], last: 20) { nodes { ... on LabeledEvent { createdAt actor { __typename login } label { name } } } }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: true) {
          pageInfo { hasNextPage }
          nodes {
            number state isDraft merged mergedAt closedAt baseRefName headRefOid
            commits(last: 1) {
              nodes {
                commit {
                  oid message committedDate
                  statusCheckRollup {
                    state
                    contexts(first: 20) {
                      totalCount
                      pageInfo { hasNextPage endCursor }
                      nodes {
                        __typename
                        ... on CheckRun { id name status conclusion databaseId checkSuite { workflowRun { createdAt databaseId } } }
                        ... on StatusContext { id context state createdAt }
                      }
                    }
                  }
                }
              }
            }
          }
        }'

# A ticket's spec, as a wake reads it with the ticket: enough for its approval.
PARENT='parent {
          number state subIssuesSummary { total }
        }'

query() {
  case $1 in
    Specs) printf '%s\n' 'query Specs($owner: String!, $name: String!) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    databaseId
    defaultBranchRef { name }
  }
}' ;;
    Spec) printf '%s\n' 'query Spec($owner: String!, $name: String!, $number: Int!, $size: Int!) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      number
      subIssues(first: $size) {
        pageInfo { hasNextPage }
        nodes {' "$TICKET" '}
      }
    }
  }
}' ;;
    Blockers) printf '%s\n' 'query Blockers($ids: [ID!]!) {
  rateLimit { cost remaining limit resetAt }
  nodes(ids: $ids) { ... on Issue {
    id number stateReason repository { nameWithOwner }
    labels(first: 100) { pageInfo { hasNextPage } nodes { name } }
    closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { number merged baseRefName } }
  } }
}' ;;
    Nodes) printf '%s\n' 'query Nodes($ids: [ID!]!) {
  rateLimit { cost remaining limit resetAt }
  nodes(ids: $ids) {
    ... on Issue {
      parent { number }
      subIssuesSummary { total }' "$TICKET" '}
  }
}' ;;
    Item) printf '%s\n' 'query Item($owner: String!, $name: String!, $number: Int!, $size: Int!, $cursor: String) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    databaseId
    defaultBranchRef { name }
    issueOrPullRequest(number: $number) {
      __typename
      ... on Issue {' "$PARENT" '
        subIssuesSummary { total }' "$TICKET" '}
      ... on PullRequest {
        number state
        closingIssuesReferences(first: $size, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {' "$PARENT" '
            subIssuesSummary { total }' "$TICKET" '}
        }
      }
    }
  }
}' ;;
    Checks) printf '%s\n' 'query Checks($owner: String!, $name: String!, $oid: GitObjectID!, $cursor: String!) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    object(oid: $oid) { ... on Commit {
      oid
      statusCheckRollup {
        contexts(first: 20, after: $cursor) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes {
            __typename
            ... on CheckRun { id name status conclusion databaseId checkSuite { workflowRun { createdAt databaseId } } }
            ... on StatusContext { id context state createdAt }
          }
        }
      }
    } }
  }
}' ;;
    Writer) printf '%s\n' 'query Writer($owner: String!, $name: String!, $login: String!) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    collaborators(query: $login, first: 10) { edges { permission node { login } } }
  }
}' ;;
    Merged) printf '%s\n' 'query Merged($owner: String!, $name: String!, $cursor: String) {
  rateLimit { cost remaining limit resetAt }
  repository(owner: $owner, name: $name) {
    pullRequests(states: MERGED, first: 50, after: $cursor, orderBy: {field: UPDATED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes { number mergedAt updatedAt baseRefName mergeCommit { oid } closingIssuesReferences(first: 10) { nodes { number } } }
    }
  }
}' ;;
  esac
}

# back_off WHY: stop quietly, since GitHub's allowance is low: one line on
# stderr, nothing on stdout, exit 0.
back_off() { printf 'fleet.sh: backing off: %s\n' "$*" >&2; exit 0; }

# gql OP OUT [gh api arguments...]: one GraphQL read, checked, with what it
# cost and the points left after it in rate.txt. GitHub answers a spent
# allowance with an error of type RATE_LIMIT (observed live, 2026-11-01;
# RATE_LIMITED is the spelling GitHub's clients also check), which `gh` exits
# 1 on: on the check's first read that backs off; on a later one the read is
# partial, and the check fails.
reads=0
gql() {
  op=$1 out=$2
  shift 2
  case $op in
    Blockers | Nodes) ;;
    *) set -- -F owner="$OWNER" -F name="$NAME" "$@" ;;
  esac
  # GI1: a full read of `spec S` keeps each answer, by its whole request; a
  # replay answers from them and asks GitHub nothing (the probe has shown
  # nothing they read has changed). No saved answer stops the replay.
  key=$(printf '%s\n' 'launch-fleet GraphQL v1' "$op" "$@" | hash) && [ ${#key} = 64 ] || die "can't hash the GitHub query $op"
  if [ -n "$REPLAY" ]; then
    [ -f "$REPLAY/snap/gql-$key.json" ] && cp "$REPLAY/snap/gql-$key.json" "$out" || die "the saved full read has no answer to $op"
  # An empty answer is never a spent allowance, nor anything else: jq -e takes
  # an empty file as true (jq 1.6).
  elif ! gh api graphql -f query="$(query "$op")" "$@" > "$out" 2> "$out.err"; then
    if [ $reads = 0 ] && [ -s "$out" ] && jq -e 'any(.errors[]?.type; . == "RATE_LIMIT" or . == "RATE_LIMITED")' "$out" > /dev/null 2>&1; then
      back_off "GitHub's allowance has run out, until it resets"
    fi
    # A number a wake names that is no issue or pull request (deleted, or
    # never there): GitHub answers NOT_FOUND for it alone (observed live,
    # 2026-11-01), and nothing is due on it.
    if [ "$op" = Item ] && [ -s "$out" ] && jq -e '.data.repository.issueOrPullRequest == null and (.errors | length) > 0
         and all(.errors[]; .type == "NOT_FOUND" and .path == ["repository", "issueOrPullRequest"])' "$out" > /dev/null 2>&1; then
      jq 'del(.errors)' "$out" > "$out.found" && mv "$out.found" "$out" || die "can't read the GitHub query $op"
    else
      die "the GitHub query $op failed: $(head -n 1 "$out.err" | head -c 300)"
    fi
  fi
  [ -s "$out" ] || die "the GitHub query $op answered nothing"
  jq -e '(.errors // []) == [] and (.data | type) == "object" and all(.data[]; type == "object" or type == "array")' "$out" > /dev/null 2>&1 \
    || die "the GitHub query $op answered with errors: $(jq -c '.errors' "$out" 2> /dev/null | head -c 300)"
  if [ -z "$REPLAY" ]; then
    jq -er '.data.rateLimit | select(type == "object")
      | select(all(.cost, .remaining, .limit; type == "number" and . >= 0 and . == floor) and .limit > 0
               and (.resetAt | type) == "string" and (.resetAt | test("^[0-9T:Z-]+$")))
      | "\(.cost) \(.remaining) \(.limit) \(.resetAt)"' "$out" >> "$TMP/rate.txt" 2> /dev/null \
      || die "the GitHub query $op did not say what it cost and what is left"
    [ -z "$RECORD" ] || { kept=$(mktemp "$RECORD/gql-$key.XXXXXX") && cp "$out" "$kept"; } || RECORD=''
  fi
  reads=$((reads + 1))
  case $op in Specs | Item)
    REPO_ID=$(jq -er '.data.repository.databaseId | select(type == "number" and . > 0 and . == floor)' "$out") \
      || die "the GitHub query $op did not identify the repository" ;;
  esac
  case $op in
    Nodes | Item)
      [ "$reads" -gt 1 ] || allowance
      # Comments are read only with the record authors known (#641), so a
      # wake's first Item read takes the settings first, once.
      settings
      hydrate "$out" || die "can't read REST issue facts for the GitHub query $op"
      ;;
  esac
}

# last_rate: the latest read's "cost remaining limit resetAt", into $cost,
# $left, $limit and $reset.
last_rate() {
  read -r cost left limit reset << EOF
$(tail -n 1 "$TMP/rate.txt")
EOF
}

# allowance: after the first read, back off when fewer than a quarter of the
# hour's points are left: the rest is kept for builders and reviewers.
allowance() {
  [ -z "$REPLAY" ] || return 0
  last_rate
  keep=$((limit / 4))
  [ "$left" -ge "$keep" ] || back_off "$left of $limit GitHub points left, under the $keep kept for builders and reviewers, until $reset"
}

# points: the points line, on stderr. Each question revision.sh asks is a
# small GraphQL read, which GitHub charges one point.
points() {
  used=$(awk '{ s += $1 } END { print s + 0 }' "$TMP/rate.txt") && asked=$(wc -l < "$TMP/asked") \
    && by_revision=$(wc -l < "$TMP/asked-revision") || die "can't count the questions"
  unchanged=$(wc -l < "$TMP/unchanged") || die "can't count the questions"
  if [ -s "$TMP/rate.txt" ]; then
    last_rate
    left="$left of $limit left"
  else left='no GraphQL read'; fi
  printf 'fleet.sh: used %s GitHub points in %s questions, %s unchanged; %s\n' \
    $((used + by_revision)) $((asked + by_revision)) $((unchanged)) "$left" >&2
}

# FILES: a jq filter over `gh api --paginate .../pulls/N/files` pages (read
# with -s): the files, each {filename, status, previous_filename}, or an
# error unless every page is a list and every entry has a nonempty filename,
# one of GitHub'"'"'s statuses and, when renamed, a nonempty previous_filename
# (K9, #337: one dropped name can hide a clash).
FILES='if all(.[]; type == "array") then add // []
    | if all(.[]; type == "object" and (.filename | type) == "string" and .filename != ""
             and (.status | IN("added", "removed", "modified", "renamed", "copied", "changed", "unchanged"))
             and (if .status == "renamed" then (.previous_filename | type) == "string" and .previous_filename != ""
                  else (.previous_filename | type) == "string" or .previous_filename == null end))
      then map({filename, status, previous_filename}) else error("a file without a name, status or old name") end
  else error("not a list") end'

# hash: stdin's SHA-256, 64 hex digits.
hash() { $SHA | cut -c1-64; }
# cached ENTRY: the cache entry's line, or nothing.
cached() { [ -n "$CACHE" ] && [ -f "$CACHE/$1" ] && head -n 1 "$CACHE/$1" 2> /dev/null; }
# keep ENTRY LINE: LINE as the cache entry, whole or not at all (a failed
# write leaves the entry as it was, or empty, and an empty entry matches nothing).
keep() {
  [ -n "$CACHE" ] || return 0
  printf '%s\n' "$2" > "$TMP/keep" && mv -f "$TMP/keep" "$CACHE/$1" 2> /dev/null || : > "$CACHE/$1" 2> /dev/null || :
}

# A conditional GET caches the entire successful HTTP response atomically.
# Snapshot and hash-check the entry before sending its ETag: a lost, damaged
# or unreadable cache is a miss, never a source of fleet facts. A 304 from gh
# exits 1; it succeeds here only with the exact response we revalidated.
http_get() (
  endpoint=$1 destination=$2 media=${3:-application/vnd.github+json}
  # Like `gh api` without --paginate: the first page only.
  request=$(printf '%s\n' 'launch-fleet REST v1' "${GH_HOST:-github.com}" "$endpoint" "$media" | hash) || exit 1
  entry=$CACHE/rest-$request.json
  work=$(mktemp -d "$TMP/rest.XXXXXX") && rm -f "$destination.304" || exit 1
  etag=''
  if [ -n "$CACHE" ] && [ -f "$entry" ] && [ ! -L "$entry" ] && cp "$entry" "$work/entry" 2> /dev/null \
    && jq --stream -serj --arg r "$request" '[.[] | select(length == 2)] as $fields
      | select(([.[] | select(length == 1)] | length) == 1
        and ($fields | length) == 4 and all($fields[]; (.[0] | length) == 1)
        and ([$fields[][0][0]] | sort) == ["etag", "request", "response", "sha256"])
      | $fields | map({key: .[0][0], value: .[1]}) | from_entries
      | select(.request == $r and (.etag | type == "string" and test("^(W/)?\\\"[!#-~]{1,250}\\\"$"))
        and (.response | type == "string") and (.sha256 | type == "string" and test("^[0-9a-f]{64}$")))
      | .etag, "\n", .sha256, "\n", .response' "$work/entry" > "$work/checked" 2> /dev/null \
    && { IFS= read -r saved_tag && IFS= read -r saved_digest && cat > "$work/saved"; } < "$work/checked" \
    && [ "$(hash < "$work/saved")" = "$saved_digest" ] \
    && [ "$(http_status "$work/saved")" = 200 ] \
    && [ "$(http_etag "$work/saved")" = "$saved_tag" ]; then
    etag=$saved_tag
  fi
  set -- api --include -H "Accept: $media"
  [ -z "$etag" ] || set -- "$@" -H "If-None-Match: $etag"
  if gh "$@" "$endpoint" > "$work/http" 2> "$work/error"; then ok=yes; else ok=no; fi
  status=$(http_status "$work/http")
  if [ "$status" = 304 ]; then
    [ -n "$etag" ] || { printf 'fleet.sh: unexpected 304 without a readable cached response\n' >&2; exit 1; }
    printf '.\n' >> "$COUNTS/unchanged" && : > "$destination.304" || exit 1
    # A page body may be unchanged while another page was appended. Fresh
    # 304 metadata replaces cached metadata (HTTP cache revalidation).
    awk 'NR == FNR { if (tolower($1) == "link:") link=$0; next }
      !body && tolower($1) == "link:" && link != "" { next }
      !body && /^\r?$/ { if (link != "") print link; body=1 }
      { print }' "$work/http" "$work/saved" > "$work/restored" \
      && mv "$work/restored" "$work/http" || exit 1
    # Most revalidations change no bytes, including pagination metadata.
    # The snapshot was already verified; retain its atomic cache entry.
    if cmp -s "$work/http" "$work/saved"; then
      cp "$work/http" "$destination"
      exit $?
    fi
    ok=yes status=200
  fi
  cp "$work/http" "$destination" || exit 1
  if [ "$ok" != yes ] || [ "$status" != 200 ]; then cat "$work/error" >&2; exit 1; fi
  # A replay stands only on unchanged answers. The open issues list is the
  # whole repository's; the replay reads it afresh, as a full read does, and
  # the spec's own changes show in its own issue's answers.
  changed=no
  if [ -n "$REPLAY" ] && [ ! -f "$destination.304" ]; then
    case $endpoint in
      "repos/$REPO/issues?state=open&per_page=100" | "repositories/$REPO_ID/issues?state=open&per_page=100&page="*) ;;
      *) changed=yes ;;
    esac
  fi
  tag=$(http_etag "$work/http")
  if [ -n "$CACHE" ] && [ ! -d "$entry" ] && printf '%s\n' "$tag" | LC_ALL=C grep -qE '^(W/)?"[!#-~]{1,250}"$'; then
    digest=$(hash < "$work/http") || exit 1
    # Temporary file lives beside its destination, so rename is atomic even
    # when the sandbox's temporary directory is on another filesystem.
    pending=$(mktemp "$CACHE/.rest.XXXXXX" 2> /dev/null) || exit 0
    if jq -cn --arg request "$request" --arg etag "$tag" --arg sha256 "$digest" \
      --rawfile response "$work/http" '{request: $request, etag: $etag, response: $response, sha256: $sha256}' > "$pending"; then
      mv -f "$pending" "$entry" 2> /dev/null || rm -f "$pending"
    else rm -f "$pending"; fi
  fi
  # Some readers take a failed read as a fact (an incomplete history), so
  # the replay also checks this mark before it prints anything.
  [ "$changed" = no ] || { : > "$TMP/changed"; printf 'fleet.sh: %s changed since the saved full read\n' "$endpoint" >&2; exit 1; }
  exit 0
)
http_status() {
  awk 'NR == 1 { sub(/\r$/, "");
    if ($1 ~ /^HTTP\/[0-9]+([.][0-9]+)?$/ && $2 ~ /^[0-9][0-9][0-9]$/) print $2; exit }' "$1"
}
http_etag() { awk 'tolower($1) == "etag:" { sub(/^[^:]*:[ ]*/, ""); sub(/\r$/, ""); print; exit }' "$1"; }
http_body() { awk 'body { print } /^\r?$/ { body=1 }' "$1"; }

rest() (
  media=${3:-application/vnd.github+json}
  http_get "$1" "$2.http" "$media" && http_body "$2.http" > "$2" || exit 1
  [ "$media" = application/vnd.github.raw+json ] || jq -se 'length == 1' "$2" > /dev/null
)

# Follow GitHub's next-page link, including after a 304. Cache each page by
# its full endpoint; the cached response includes its original Link header.
next_page() {
  link=$(awk 'tolower($1) == "link:" { sub(/^[^:]*:[ ]*/, ""); sub(/\r$/, ""); print }' "$1") || return 1
  case $link in *'rel="next"'*) ;; *) return 0 ;; esac
  next=$(printf '%s\n' "$link" | tr ',' '\n' | sed -n 's/^[ ]*<\([^>]*\)>; *rel="next"[ ]*$/\1/p')
  case $next in '' | *'
'*) return 1 ;; esac
  host=${GH_HOST:-github.com}
  if [ "$host" = github.com ]; then prefix=https://api.github.com/; else prefix=https://$host/api/v3/; fi
  case $next in "$prefix"*) next=${next#"$prefix"} ;; *) return 1 ;; esac
  case $next in "repos/$REPO/"* | "repositories/$REPO_ID/"* | search/issues\?*) printf '%s\n' "$next" ;; *) return 1 ;; esac
}
rest_pages() (
  endpoint=$1 destination=$2
  : > "$destination" || exit 1
  page=0
  while [ -n "$endpoint" ]; do
    page=$((page + 1))
    [ "$page" -le 1000 ] || exit 1
    rest "$endpoint" "$destination.page" || exit 1
    cat "$destination.page" >> "$destination" || exit 1
    endpoint=$(next_page "$destination.page.http") || exit 1
  done
)

# Run independent REST facts in sixty-four lanes. A free lane keeps reading
# while another waits on a slow response. Each owns its output files, and
# pagination stays serial inside a lane. Drain every lane on a read failure,
# so no worker can outlive the check's temp files.
# The initial allowance gate runs before this pool; its rate records are
# reduced on the main shell after every worker has finished.
parallel_reads() (
  reader=$1 list=$2
  lanes=$(mktemp -d "$TMP/readers.XXXXXX") || exit 1
  awk -v prefix="$lanes/lane-" '{ print > (prefix ((NR - 1) % 64)) }' "$list" || exit 1
  pids='' failed=0
  for lane in "$lanes"/lane-*; do
    [ -f "$lane" ] || continue
    (
      while read -r number kind; do
        "$reader" "$number" "$kind" || exit 1
      done < "$lane"
    ) &
    pids="$pids $!"
  done
  for pid in $pids; do wait "$pid" || failed=1; done
  [ "$failed" = 0 ]
)

# #641: the comments the factory wrote, by the record authors settings() read
# (in $TMP/authors.json, passed as $a). GitHub's login is case-insensitive. A
# comment by anyone else, or with no readable author, is dropped here, at each
# read, so no record reader ever sees it: fail closed.
AUTHORED='def authored($a): map(select(((.user | if type == "object" then .login else null end)
  | if type == "string" then ascii_downcase else null end) as $l | $l != null and any($a[]; . == $l)));'

# Ordinary issue fields and comments have REST equivalents. PR metadata
# stays with its head and combined CI rollup in GraphQL. Closing relationships
# and labelled-event selection also stay there: REST references/check lists
# alone do not establish the same facts.
# Per-check memoization avoids re-reading an issue reached through two specs.
comment_facts() (
  n=$1
  [ ! -f "$TMP/comments-$n.json" ] || exit 0
  # REST already walks the whole history. Never cap it at the former
  # GraphQL window, and never interpret a partially read history as facts.
  # The existing incomplete-history guard prints look for this item alone.
  if rest_pages "repos/$REPO/issues/$n/comments?per_page=100" "$TMP/comments-$n.raw" 2> /dev/null \
    && jq -se --slurpfile a "$TMP/authors.json" "$AUTHORED"'select(length > 0 and all(.[]; type == "array")) | add
      | select(all(.[]; type == "object" and (.id | type) == "number"
          and (.body | type) == "string" and (.created_at | type) == "string"
          and (.updated_at | type) == "string"))
      | {pageInfo: {hasPreviousPage: false},
         nodes: (authored($a[0]) | map({databaseId: .id, createdAt: .created_at, updatedAt: .updated_at, body, author: (.user.login | ascii_downcase)}))}' \
      "$TMP/comments-$n.raw" > "$TMP/comments-$n.json" 2> /dev/null; then
    exit 0
  fi
  printf '%s\n' '{"pageInfo":{"hasPreviousPage":true},"nodes":[]}' > "$TMP/comments-$n.json"
)
# Each issue's three REST resources are independent too. Fetch them in the
# same pool before constructing facts, so one issue never serializes them.
issue_read() (
  n=$1 part=$2
  case $part in
    comments) comment_facts "$n" ;;
    detail) rest "repos/$REPO/issues/$n" "$TMP/facts-issue-$n.json.detail" ;;
    blockers) rest_pages "repos/$REPO/issues/$n/dependencies/blocked_by?per_page=100" "$TMP/facts-issue-$n.json.blockers" ;;
    *) exit 1 ;;
  esac
)
issue_facts() (
  n=$1 kind=$2
  facts=$TMP/facts-$kind-$n.json
  [ ! -f "$facts" ] || exit 0
  comment_facts "$n" || exit 1
  if [ "$kind" = pr ]; then
    # The head, its CI rollup and the PR metadata stay together in the one
    # GraphQL answer. Mixing later REST metadata could borrow another head's
    # passing checks. Only the PR's comments need a separate REST read.
    jq -cn --argjson n "$n" --slurpfile c "$TMP/comments-$n.json" '{number: $n, comments: $c[0]}' > "$facts"
    exit $?
  fi
  if [ "$kind" = issue ]; then
    jq -se 'select(length > 0) | add | select(type == "array" and all(.[];
      (.number | type) == "number" and (.node_id | type) == "string" and (.state | IN("open", "closed"))))
      | {pageInfo: {hasNextPage: (length > 20)}, nodes: (.[0:20] | map({number, node_id, state: (.state | ascii_upcase)}))}' \
      "$facts.blockers" > "$facts.dependencies" || exit 1
  else printf '{"nodes": []}' > "$facts.dependencies" || exit 1; fi
  jq -ce --argjson n "$n" --slurpfile c "$TMP/comments-$n.json" --slurpfile b "$facts.dependencies" '
    select(type == "object" and .number == $n and (.title | type) == "string"
      and (.body == null or (.body | type) == "string") and (.state | IN("open", "closed")))
    |         select((.labels | type) == "array" and all(.labels[]; (.name | type) == "string")
          and (.updated_at | type) == "string")
        | {number, title, state: (.state | ascii_upcase), body: (.body // ""), updatedAt: .updated_at,
           stateReason: (.state_reason | if type == "string" then ascii_upcase else null end),
           labels: {pageInfo: {hasNextPage: ((.labels | length) > 20)}, nodes: (.labels[:20] | map({name}))}}
      | . + {comments: $c[0], blockedBy: $b[0]}' "$facts.detail" > "$facts" || { rm -f "$facts"; exit 1; }
)
# Node IDs are global and opaque; issue numbers are local to a repository.
# Hash the identity for a filename without interpreting any of its bytes.
closure_file() (
  key=$(printf '%s' "$1" | hash) || exit 1
  [ ${#key} = 64 ] || exit 1
  case $key in *[!0-9a-f]*) exit 1 ;; esac
  printf '%s/closure-%s.json\n' "$TMP" "$key"
)
# Complete each open PR's contexts before any admission decision. Continuations
# address the immutable commit OID from the original PR snapshot, never a later
# PR head. Counts, identities and cursors must reconcile across every page.
check_contexts() (
  source=$1
  jq -c '
    def valid_pr: (.headRefOid | type == "string" and test("^[0-9a-f]{40}$"))
      and (.commits.nodes | type == "array" and length == 1)
      and .commits.nodes[0].commit.oid == .headRefOid
      and (.commits.nodes[0].commit | has("statusCheckRollup"));
    [.. | objects | select(has("headRefOid") and .state == "OPEN")]
    | if all(.[]; valid_pr) then group_by(.number)[]
      | if (map(.headRefOid) | unique | length) == 1
          and (map(.commits.nodes[0].commit.statusCheckRollup) | unique | length) == 1
        then .[0] else error("conflicting PR check snapshots") end
      else error("invalid PR commit identity") end' "$source" > "$source.prs" || exit 1
  : > "$source.checks" || exit 1
  while IFS= read -r pr; do
    printf '%s\n' "$pr" > "$source.pr" || exit 1
    oid=$(jq -r '.headRefOid' "$source.pr") || exit 1
    jq '.commits.nodes[0].commit.statusCheckRollup' "$source.pr" > "$source.rollup" || exit 1
    # A commit with no rollup has no successful required CI to borrow.
    [ "$(cat "$source.rollup")" != null ] || continue
    jq '.contexts' "$source.rollup" > "$source.contexts" || exit 1
    printf '[]' > "$source.nodes" && printf '[]' > "$source.cursors" || exit 1
    total=$(jq '.totalCount' "$source.contexts") || exit 1
    while :; do
      jq -e --argjson total "$total" --slurpfile seen "$source.nodes" --slurpfile cursors "$source.cursors" '
        type == "object" and .totalCount == $total
        and (.totalCount | type == "number" and . >= 0 and . == floor)
        and (.pageInfo.hasNextPage | type == "boolean")
        and (.nodes | type == "array")
        and (.pageInfo | has("endCursor"))
        and (if (.nodes | length) == 0 then .pageInfo.endCursor == null
          else (.pageInfo.endCursor | type == "string" and length > 0)
            and (.pageInfo.endCursor as $c | $cursors[0] | index($c) == null) end)
        and all(.nodes[];
          (.id | type == "string" and length > 0)
          and (if .__typename == "CheckRun" then
            (.name | type == "string" and length > 0)
            and (.databaseId | type == "number" and . > 0 and . == floor)
            and (.status | type == "string")
            and (.conclusion == null or (.conclusion | type) == "string")
          elif .__typename == "StatusContext" then
            (.context | type == "string" and length > 0)
            and (.state | type == "string") and (.createdAt | type == "string" and length > 0)
          else false end))
        and (($seen[0] + .nodes) as $all | ($all | length) == ($all | unique_by(.id) | length)
          and ([$all[] | select(.__typename == "CheckRun")] as $runs
            | ($runs | length) == ($runs | unique_by(.databaseId) | length)))
        and (($seen[0] | length) + (.nodes | length)) <= $total
        and (if .pageInfo.hasNextPage then
          (.nodes | length) > 0 and (($seen[0] | length) + (.nodes | length)) < $total
        else (($seen[0] | length) + (.nodes | length)) == $total end)' \
        "$source.contexts" > /dev/null || exit 1
      jq --slurpfile seen "$source.nodes" '$seen[0] + .nodes' "$source.contexts" > "$source.next-nodes" \
        && mv "$source.next-nodes" "$source.nodes" || exit 1
      [ "$(jq '.pageInfo.hasNextPage' "$source.contexts")" = true ] || break
      cursor=$(jq -r '.pageInfo.endCursor' "$source.contexts") || exit 1
      jq --arg c "$cursor" '. + [$c]' "$source.cursors" > "$source.next-cursors" \
        && mv "$source.next-cursors" "$source.cursors" || exit 1
      gql Checks "$source.check-page" -f oid="$oid" -f cursor="$cursor"
      jq -e --arg oid "$oid" '.data.repository.object.oid == $oid' "$source.check-page" > /dev/null || exit 1
      jq '.data.repository.object.statusCheckRollup.contexts' "$source.check-page" > "$source.contexts" || exit 1
    done
    jq --slurpfile nodes "$source.nodes" --slurpfile page "$source.contexts" \
      '.contexts = $page[0] | .contexts.nodes = $nodes[0]' "$source.rollup" > "$source.complete" || exit 1
    jq --slurpfile rollup "$source.complete" '{number, rollup: $rollup[0]}' "$source.pr" >> "$source.checks" || exit 1
  done < "$source.prs"
  jq -s 'map({key: (.number | tostring), value: .rollup}) | from_entries' "$source.checks" > "$source.rollups" || exit 1
  jq --slurpfile r "$source.rollups" 'walk(if type == "object" and has("headRefOid")
      and .state == "OPEN" and $r[0][(.number | tostring)] != null
    then .commits.nodes[0].commit.statusCheckRollup = $r[0][(.number | tostring)] else . end)' \
    "$source" > "$source.next" && mv "$source.next" "$source"
)
hydrate() (
  source=$1 extra_comments=${2:-}
  check_contexts "$source" || exit 1
  jq -r '[.. | objects | select(has("number"))
    | select(.closedByPullRequestsReferences.pageInfo != null or has("subIssues")
        or has("subIssuesSummary") or has("commits"))
    | {n: .number, k: (if has("commits") then "pr" else "issue" end)}]
    | unique_by([.n, .k])[] | "\(.n) \(.k)"' "$source" > "$source.wanted" || exit 1
  # Validate every work item before launching any readers, then assemble
  # their facts once instead of spawning jq again for every issue.
  : > "$source.requests" || exit 1
  set --
  while read -r n kind; do
    case $n in '' | *[!0-9]*) exit 1 ;; esac
    case $kind in issue | pr) ;; *) exit 1 ;; esac
    set -- "$@" "$TMP/facts-$kind-$n.json"
    [ ! -f "$TMP/facts-$kind-$n.json" ] || continue
    [ -f "$TMP/comments-$n.json" ] || printf '%s comments\n' "$n" >> "$source.requests" || exit 1
    if [ "$kind" = issue ]; then
      printf '%s detail\n%s blockers\n' "$n" "$n" >> "$source.requests" || exit 1
    fi
  done < "$source.wanted"
  if [ -n "$extra_comments" ]; then
    while read -r n; do
      is_number "$n" || exit 1
      [ -f "$TMP/comments-$n.json" ] || printf '%s comments\n' "$n" >> "$source.requests" || exit 1
    done < "$extra_comments"
  fi
  sort -u "$source.requests" > "$source.jobs" || exit 1
  parallel_reads issue_read "$source.jobs" || exit 1
  parallel_reads issue_facts "$source.wanted" || exit 1
  if [ $# -gt 0 ]; then
    jq -s 'map({key: (.number | tostring), value: .}) | from_entries' "$@" > "$source.facts" || exit 1
  else printf '{}' > "$source.facts" || exit 1; fi
  jq -r '[.[] | .blockedBy.nodes[]? | select(.state == "CLOSED") | .node_id]
    | unique[]' "$source.facts" > "$source.blockers" || exit 1
  set --
  while IFS= read -r id; do
    file=$(closure_file "$id") || exit 1
    [ ! -f "$file" ] || continue
    set -- "$@" -f "ids[]=$id"
    [ $# -lt 100 ] || { blocker_closures "$@" || exit 1; set --; }
  done < "$source.blockers"
  [ $# -eq 0 ] || blocker_closures "$@" || exit 1
  if [ -s "$source.blockers" ]; then
    jq -s 'map({key: .id, value: {closedByPullRequestsReferences, labels, comments, repository, stateReason}}) | from_entries' \
      "$TMP"/closure-*.json > "$source.closures" || exit 1
  else printf '{}' > "$source.closures" || exit 1; fi
  jq --slurpfile c "$source.closures" 'with_entries(.value |=
    (if has("blockedBy") then .blockedBy.nodes |= map(. +
      ($c[0][.node_id] // {closedByPullRequestsReferences: {nodes: []}}) | del(.node_id)) else . end))' \
    "$source.facts" > "$source.next" && mv "$source.next" "$source.facts" || exit 1
  jq --slurpfile facts "$source.facts" 'walk(if type == "object" and has("number")
    and (.closedByPullRequestsReferences.pageInfo != null or has("subIssues")
      or has("subIssuesSummary") or has("commits"))
    then . + $facts[0][(.number | tostring)] else . end)' "$source" > "$source.next" \
    && mv "$source.next" "$source"
)

# A REST dependency is not proof of a merge. Only the GraphQL closing
# relationship supplies that fact; batch the actual closed blockers, once per
# check, instead of asking for 20 blockers times 5 PRs on every ticket.
blocker_closures() {
  gql Blockers "$TMP/closures-answer.json" "$@"
  printf '%s\n' "$@" | sed -n 's/^ids\[\]=//p' | jq -Rn '[inputs] | sort' > "$TMP/closures-ids" || return 1
  jq -e --slurpfile ids "$TMP/closures-ids" '.data.nodes
    | (map(.id) | sort) == $ids[0] and all(.[]; (.number | type) == "number"
      and (.closedByPullRequestsReferences.nodes | type) == "array"
      and all(.closedByPullRequestsReferences.nodes[];
        (.merged | type) == "boolean" and (.baseRefName | type) == "string"))' \
    "$TMP/closures-answer.json" > /dev/null || return 1
  jq -c '.data.nodes[]' "$TMP/closures-answer.json" > "$TMP/closures-lines" || return 1
  while IFS= read -r closure; do
    id=$(printf '%s' "$closure" | jq -er .id) || return 1
    file=$(closure_file "$id") || return 1
    printf '%s\n' "$closure" > "$file" || return 1
    # Only person blockers need issue-comment evidence. Address their own
    # repository from the exact node, never a same-number local issue.
    # Settings precede every comment read (#641). The final blocker
    # guard always uses the configured role labels.
    human_label=$(jq -er '."ready-for-human"' "$TMP/labels.json") || return 1
    if jq -e --arg human "$human_label" '.labels.pageInfo.hasNextPage == false and any(.labels.nodes[]?;
        .name == $human or .name == "person" or ($human == "" and .name != "ready-for-agent"))' "$file" > /dev/null; then
      repo=$(jq -er '.repository.nameWithOwner | strings
        | select(test("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"))' "$file") || return 1
      n=$(jq -er .number "$file") || return 1
      if rest_pages "repos/$repo/issues/$n/comments?per_page=100" "$file.raw" 2> /dev/null \
        && jq -se --slurpfile a "$TMP/authors.json" "$AUTHORED"'select(length > 0 and all(.[]; type == "array")) | add
          | select(all(.[]; type == "object" and (.body | type) == "string"))
          | {nodes: (authored($a[0]) | map({body}))}' "$file.raw" > "$file.comments"; then
        jq --slurpfile c "$file.comments" '. + {comments: $c[0]}' "$file" > "$file.next" \
          && mv "$file.next" "$file" || return 1
      fi
    fi
  done < "$TMP/closures-lines"
}

# raw PATH OUT: a file from the default branch.
raw() {
  rest "repos/$REPO/contents/$1" "$2" application/vnd.github.raw+json \
    || die "can't read $1 from the default branch: run the setup skill first"
}

settings() {
  [ ! -f "$TMP/settings.done" ] || return 0
  raw docs/agents/fleet.md "$TMP/fleet.md"
  raw docs/agents/triage-labels.md "$TMP/labels.md"
  awk '/^## /{on = ($0 == "## CI checks")} on && /^[|] *`[^`]+` *[|]/' "$TMP/fleet.md" \
    | sed 's/^| *`\([^`]*\)`.*/\1/' > "$TMP/checks.txt" || die "can't read the CI checks"
  [ -s "$TMP/checks.txt" ] || die "docs/agents/fleet.md lists no CI checks (its \"## CI checks\" table)"
  jq -Rn '[inputs]' < "$TMP/checks.txt" > "$TMP/checks.json" || die "can't read the CI checks"
  # #641: the factory's own identity, the one place that names it: the logins
  # that write its records (its App, and the account it falls back to). Every
  # comment read below by anyone else, or by no one, is dropped before any
  # reader sees it. The row must be exactly "| Record authors | <cell> |" and
  # the whole cell backticked logins separated by commas: no row, an empty
  # one, any malformed or extra entry, or anything after the value cell stops
  # the check, never keeping only the logins that did parse.
  awk '/^## /{on = ($0 == "## GitHub identity")} on && /^[|] *Record authors *[|]/' "$TMP/fleet.md" > "$TMP/authors.txt" \
    && jq -Rse 'split("\n") | map(select(length > 0)) | select(length == 1) | .[0]
      | split("|") | select(length == 4 and (.[3] | test("^\\s*$"))) | .[2]
      | "`[A-Za-z0-9](-?[A-Za-z0-9])*(\\[bot\\])?`" as $login
      | select(test("^\\s*" + $login + "(\\s*,\\s*" + $login + ")*\\s*$"))
      | [scan("`([^`]*)`") | .[0] | ascii_downcase]' "$TMP/authors.txt" > "$TMP/authors.json" 2> /dev/null \
    || die "docs/agents/fleet.md names no record authors (its \"## GitHub identity\" table's \"Record authors\" row)"
  awk '/^## /{on = ($0 == "## Labels")} on && /^[|] *`[^`]+` *[|] *`[^`]+` *[|]/' "$TMP/labels.md" \
    | sed 's/^| *`\([^`]*\)` *| *`\([^`]*\)`.*/\1`\2/' > "$TMP/labels.txt" || die "can't read the labels"
  jq -Rn '[inputs | split("`") | {key: .[0], value: .[1]}] | from_entries' < "$TMP/labels.txt" > "$TMP/labels.json" \
    || die "can't read the labels"
  jq -e '. as $l | ["ready-for-agent", "needs-info", "needs-triage", "ready-for-human", "wontfix"]
    | all(.[]; . as $r | $l[$r] | type == "string")' "$TMP/labels.json" > /dev/null \
    || die "docs/agents/triage-labels.md does not map all five roles (its \"## Labels\" table)"
  : > "$TMP/settings.done" || die "can't write"
}

# specs_list: every open issue with sub-issues (a spec), as "<number>
# <tickets> <closed tickets> <updatedAt>", into spec-list.txt; every open
# follow-up filed outside its spec (its body's first line "Follow-up of
# #<ticket> (spec #<spec>)"), into followups.json; and the default branch into
# $DEFAULT. Its first read is the check's first: it says how much of GitHub's
# allowance is left.
specs_list() {
  : > "$TMP/spec-list.txt"
  : > "$TMP/followups.txt"
  gql Specs "$TMP/repository.json"
  allowance
  DEFAULT=$(jq -er '.data.repository.defaultBranchRef.name' "$TMP/repository.json") || die "no default branch"
  endpoint="repos/$REPO/issues?state=open&per_page=100"
  pages=0
  while [ -n "$endpoint" ]; do
    pages=$((pages + 1))
    [ $pages -le 50 ] || die "more than 5000 open issues: too many to read in one check"
    rest "$endpoint" "$TMP/issues-page.json" || die "can't read the open issues"
    jq -ce 'select(type == "array")
      | [.[] | select(has("pull_request") | not)
         | {number, updatedAt: .updated_at, body, subIssuesSummary: .sub_issues_summary}]
      | if all(.[]; (.subIssuesSummary | type) == "object"
          and all(.subIssuesSummary.total, .subIssuesSummary.completed; type == "number" and . >= 0 and . == floor))
        then {data: {repository: {issues: {nodes: .}}}}
        else error("missing sub-issue counts") end' \
      "$TMP/issues-page.json" > "$TMP/page.json" || die "can't read the open issues"
    jq -e '[.data.repository.issues.nodes[] | select(.subIssuesSummary.total > 0)]
      | all(.[]; (.number, .subIssuesSummary.total, .subIssuesSummary.completed | type == "number")
                 and (.updatedAt | type == "string" and test("^[0-9T:Z.-]+$")))' "$TMP/page.json" > /dev/null \
      || die "can't read the open issues"
    jq -r '.data.repository.issues.nodes[] | select(.subIssuesSummary.total > 0)
      | "\(.number) \(.subIssuesSummary.total) \(.subIssuesSummary.completed) \(.updatedAt)"' "$TMP/page.json" \
      >> "$TMP/spec-list.txt" || die "can't read the open issues"
    jq -c '.data.repository.issues.nodes[]
      | ((.body // "") | gsub("\r"; "") | split("\n") | map(select(test("\\S"))) | (first // "") | sub("^\\s+"; "")) as $l
      | ([$l | capture("^Follow-up of #[0-9]+ \\(spec #(?<s>[0-9]+)\\)") | .s | tonumber] | first) as $spec
      | select($spec != null) | {number, spec: $spec}' "$TMP/page.json" >> "$TMP/followups.txt" || die "can't read the open issues"
    endpoint=$(next_page "$TMP/issues-page.json.http") || die "can't read the open issues pagination"
  done
  sort -n -u -k1,1 "$TMP/spec-list.txt" > "$TMP/spec-list.sorted" || die "can't read the open issues"
  jq -s '.' "$TMP/followups.txt" > "$TMP/followups.json" || die "can't read the follow-ups"
}

# quiet_key NUMBER TICKETS CLOSED UPDATED: a spec with no open ticket as the
# open issues list it, with this script. Polish follow-ups never affect it.
quiet_key() {
  printf 'launch-fleet quiet v2 %s %s %s %s %s\n' "$SELF" "$1" "$2" "$3" "$4" | hash
}

# specs: each spec read in one query, asking for as many tickets as the list
# gives it (or 100, if more were added since), into specs.json. A spec with no
# open ticket is skipped while its quiet key is the one cached by the last
# check that read it and found nothing due; a wake or a claim reads the
# specs it names whatever the cache says.
# Each worker inherits a completed first-read allowance gate. Its rate
# record is appended atomically; the main shell sums every worker's cost.
read_spec() (
  spec_number=$1 spec_size=$2
  gql Spec "$TMP/spec-$spec_number.json" -F number="$spec_number" -F size="$spec_size"
  if [ "$spec_size" -lt 100 ] && [ "$(jq -r '.data.repository.issue.subIssues.pageInfo.hasNextPage' "$TMP/spec-$spec_number.json")" = true ]; then
    gql Spec "$TMP/spec-$spec_number.json" -F number="$spec_number" -F size=100
  fi
)
specs() {
  : > "$TMP/spec-reads.txt" || die "can't write"
  while read -r s total closed updated; do
    if [ "$cmd" != claim ] && [ "$cmd" != wake ] && [ "$total" = "$closed" ] && [ -n "$CACHE" ]; then
      k=$(quiet_key "$s" "$total" "$closed" "$updated") || die "can't hash spec #$s"
      [ ${#k} = 64 ] && [ "$(cached "spec-$s.quiet")" = "$k" ] && continue
    fi
    size=$total
    [ "$size" -le 100 ] || size=100
    printf '%s %s\n' "$s" "$size" >> "$TMP/spec-reads.txt" || die "can't write"
  done < "$TMP/spec-list.sorted"
  parallel_reads read_spec "$TMP/spec-reads.txt" || die "can't read the specs"
  printf '[' > "$TMP/specs.json" || die "can't write"
  sep=''
  while read -r s size; do
    { printf '%s' "$sep" && jq -c '.data.repository.issue' "$TMP/spec-$s.json"; } >> "$TMP/specs.json" \
      || die "can't read spec #$s"
    sep=','
  done < "$TMP/spec-reads.txt"
  printf ']' >> "$TMP/specs.json" || die "can't write"
  jq -e 'type == "array" and all(.[]; type == "object")' "$TMP/specs.json" > /dev/null || die "a spec could not be read"
  # A full check shares its REST pool with the archive scan in singles().
  # A targeted wake/claim, and a fleet thread's check, have no archive scan
  # and hydrate their specs here.
  case $cmd in wake | claim | spec)
    hydrate "$TMP/specs.json" || die "can't read REST issue facts for the GitHub query Spec" ;;
  esac
}

# quiet: after a check, each spec it read with nothing due and every ticket
# closed and settled gets its quiet key cached; every other spec it read gets
# an empty entry, which matches nothing. A closed ticket is settled when it can
# owe no line however it changes: archived (an "archived" record ends its
# archive line for good), or with no launch-fleet record on it or on its pull
# requests (nothing starts on a closed ticket). Any other record can still
# turn into a thread (a start or review claim edited to started) without
# moving the spec's key (Sol R1 on #248).
quiet() {
  [ -n "$CACHE" ] || return 0
  jqw 'def settled: any(records[]; .r | test("^archived\\b"))
         or ((.comments.pageInfo.hasPreviousPage | not) and (records | length) == 0
             and (.closedByPullRequestsReferences.pageInfo.hasNextPage | not)
             and all(.closedByPullRequestsReferences.nodes[]; (.comments.pageInfo.hasPreviousPage | not) and (records | length) == 0));
       $W.specs[] | select((latest(.) == null or planned_done(.)) and all(.subIssues.nodes[]; .state == "CLOSED" and settled) and ([spec_lines] | length) == 0) | .number' \
    > "$TMP/quiet.txt" || die "can't list the quiet specs"
  while read -r s total closed updated; do
    jq -e --argjson s "$s" 'any(.[]; .number == $s)' "$TMP/specs.json" > /dev/null || continue
    k=''
    if [ "$total" = "$closed" ] && grep -qx "$s" "$TMP/quiet.txt"; then
      k=$(quiet_key "$s" "$total" "$closed" "$updated") || k=''
    fi
    keep "spec-$s.quiet" "$k"
  done < "$TMP/spec-list.sorted"
}

# items: each number a wake names, read alone, into items.txt: an issue as it
# is, or every ticket a pull request closes (ClosedWiz#259). A pull request's
# first read asks for 2 of the issues it closes (1 point); if it closes more,
# the rest are read 5 at a time (2 points each), every one of them, so a ticket
# past the first page is never lost to a wake or a claim (Sol R2 on #357).
# Its first read is the wake's first: it says how much of GitHub's allowance
# is left.
items() {
  : > "$TMP/items.txt"
  for n in $WAKE; do
    gql Item "$TMP/item.json" -F number="$n" -F size=2
    [ $reads -gt 1 ] || allowance
    DEFAULT=$(jq -er '.data.repository.defaultBranchRef.name' "$TMP/item.json") || die "no default branch"
    pages=1
    while :; do
      jq -ce '.data.repository.issueOrPullRequest
        | if . == null then true
          elif .__typename == "PullRequest" and (.closingIssuesReferences.nodes | type) == "array" then true
          elif .__typename == "Issue" then (.number | type) == "number"
          else false end' "$TMP/item.json" > /dev/null || die "can't read #$n"
      jq -c '.data.repository.issueOrPullRequest // empty
        | if .__typename == "PullRequest" then .closingIssuesReferences.nodes[] else select(.__typename == "Issue") end' \
        "$TMP/item.json" >> "$TMP/items.txt" || die "can't read #$n"
      more=$(jq -r '.data.repository.issueOrPullRequest.closingIssuesReferences.pageInfo.hasNextPage // false' "$TMP/item.json") \
        || die "can't read #$n"
      [ "$more" = true ] || break
      pages=$((pages + 1))
      [ $pages -le 21 ] || die "#$n closes more than 100 issues: too many to read"
      cursor=$(jq -er '.data.repository.issueOrPullRequest.closingIssuesReferences.pageInfo.endCursor | strings' "$TMP/item.json") \
        || die "can't read the issues #$n closes"
      gql Item "$TMP/item.json" -F number="$n" -F size=5 -f cursor="$cursor"
    done
  done
}

# wake_world: what a wake read, as the check would have it, into specs.json,
# singles.json and followups.json. An open spec it names is read in full, as
# the check reads it. A ticket of an open spec goes under its spec, which is
# then only part of one ("partial": its approval and the tickets named),
# unless a ticket named could start: its approval is checked against the plan,
# which revision.sh reads in full anyway, so its spec is read in full too, and
# only the tickets named have lines ("named"). An issue labelled
# ready-for-agent outside any spec is a single; anything else is outside the
# fleets.
wake_world() {
  label=$(jq -er '."ready-for-agent"' "$TMP/labels.json") || die "can't read the labels"
  jq -s '[.[] | select(.subIssuesSummary.total > 0 and .state == "OPEN") | .number] | unique | .[]' "$TMP/items.txt" \
    > "$TMP/full.txt" || die "can't read the issues named"
  jq -s --slurpfile full "$TMP/full.txt" '[.[] | select(.subIssuesSummary.total == 0 and .parent != null and .parent.state == "OPEN")
      | select(.parent.number as $p | any($full[]; . == $p) | not)]
    | group_by(.parent.number)
    | map(.[0].parent as $p | {number: $p.number, state: $p.state, comments: $p.comments, total: $p.subIssuesSummary.total,
        partial: true, subIssues: {pageInfo: {hasNextPage: false}, nodes: (map(del(.parent)) | unique_by(.number))}})' \
    "$TMP/items.txt" > "$TMP/partial.json" || die "can't read the tickets named"
  jq -s --arg l "$label" '[.[] | select(.parent == null and .subIssuesSummary.total == 0 and (any(.labels.nodes[]; .name == $l or .name == "held")
        or any(.comments.nodes[]; (.body | split("\n")[0]) | test("^launch-fleet: release starting "))))]
    | unique_by(.number)' "$TMP/items.txt" > "$TMP/singles.json" || die "can't read the issues named"
  # The specs of the tickets named that could start.
  cp "$TMP/partial.json" "$TMP/specs.json" && printf '[]' > "$TMP/followups.json" || die "can't write"
  world "$TMP/checks.json" "$TMP/labels.json" "$TMP/singles.json"
  jqw 'to_check' > "$TMP/upgrade.txt" || die "can't list the specs to check"
  # A spec named is read as the check reads it, after the list of open issues
  # (its follow-ups); the spec of a ticket that could start is read alone,
  # sized by the count its ticket's read gave (the list's other fields are
  # for the quiet cache, which a wake never uses).
  : > "$TMP/spec-list.want" || die "can't write"
  if [ -s "$TMP/full.txt" ]; then
    specs_list
    awk 'NR == FNR { want[$1] = 1; next } want[$1]' "$TMP/full.txt" "$TMP/spec-list.sorted" >> "$TMP/spec-list.want" \
      || die "can't read the specs named"
  fi
  jq -r --slurpfile up "$TMP/upgrade.txt" '.[] | select(.number as $n | any($up[]; . == $n)) | "\(.number) \(.total) - -"' \
    "$TMP/partial.json" >> "$TMP/spec-list.want" || die "can't read the specs to check"
  sort -n -u -k1,1 "$TMP/spec-list.want" > "$TMP/spec-list.sorted" || die "can't read the specs to read"
  if [ -s "$TMP/spec-list.sorted" ]; then specs; else printf '[]' > "$TMP/specs.json" || die "can't write"; fi
  jq --slurpfile part "$TMP/partial.json" --slurpfile up "$TMP/upgrade.txt" '
      [.[] | .number as $n | ([$part[0][] | select(.number == $n)] | first) as $p
       | if $p != null and any($up[]; . == $n) then . + {named: [$p.subIssues.nodes[].number]} else . end]
      + [$part[0][] | select(.number as $n | any($up[]; . == $n) | not)]' "$TMP/specs.json" > "$TMP/specs2.json" \
    && mv "$TMP/specs2.json" "$TMP/specs.json" || die "can't read the specs named"
}

# singles: the issues labelled ready-for-agent outside any spec, which only
# an approval on their own can start, into singles.json: every open one, and
# every closed one whose agents may still need archiving. GitHub's search lists
# them, open and closed, and leaves sub-issues out (#259: a list of the open
# ones held every open ticket too, at 20 points a check); each is read in full,
# by its id, unless it is closed and its last comment is its "archived" record.
# A search that lists fewer than it counts stops the check, so no start or
# archive is ever dropped.
singles() {
  label=$(jq -er '."ready-for-agent"' "$TMP/labels.json") || die "can't read the labels"
  : > "$TMP/singles.txt"
  : > "$TMP/single-ids.txt"
  : > "$TMP/search-items.txt"
  for single_label in "$label" held; do
    q="repo:$REPO is:issue label:\"$single_label\" no:parent-issue"
    cursor='' pages=0 listed=0 total=0
    encoded=$(jq -rn --arg q "$q" '$q | @uri') || die "can't encode the issues search"
    endpoint="search/issues?q=$encoded&per_page=100"
    while [ -n "$endpoint" ]; do
      pages=$((pages + 1))
      [ $pages -le 11 ] || die "the search for issues outside specs did not end"
      rest "$endpoint" "$TMP/search.json" || die "can't read the issues outside specs"
      jq -e 'type == "object" and .incomplete_results == false
        and (.total_count | type == "number" and . >= 0 and . == floor)
        and (.items | type) == "array" and all(.items[];
          (.node_id | type) == "string" and (.number | type) == "number" and (.state | IN("open", "closed")))' \
        "$TMP/search.json" > /dev/null || die "can't read the issues outside specs"
      total=$(jq .total_count "$TMP/search.json") || die "can't read the issues outside specs"
      n=$(jq '.items | length' "$TMP/search.json") || die "can't read the issues outside specs"
      listed=$((listed + n))
      jq -r '.items[] | "\(.number) \(.node_id) \(.state)"' "$TMP/search.json" >> "$TMP/search-items.txt" \
        || die "can't read the issues outside specs"
      endpoint=$(next_page "$TMP/search.json.http") || die "can't read the issues search pagination"
    done
    [ "$listed" = "$total" ] || die "the search listed $listed of $total issues outside specs, so a start or an archive could be missed"
  done
  sort -u "$TMP/search-items.txt" > "$TMP/search-items.sorted" \
    && mv "$TMP/search-items.sorted" "$TMP/search-items.txt" || die "can't deduplicate the issues outside specs"
  # All search pages share one pool; a slow page cannot strand readers.
  awk '$3 == "closed" { print $1 }' "$TMP/search-items.txt" | sort -n -u > "$TMP/closed-singles.txt" \
    || die "can't read the issues outside specs"
  hydrate "$TMP/specs.json" "$TMP/closed-singles.txt" || die "can't read the issues outside specs"
  # Inspect the freshly revalidated comments in one jq process,
  # rather than starting another process for every archived issue.
  set --
  while read -r n; do set -- "$@" "$TMP/comments-$n.json"; done < "$TMP/closed-singles.txt"
  archived=''
  if [ $# -gt 0 ]; then
    archived=$(jq -r 'select((.nodes[-1].body // "") | gsub("\r"; "") | split("\n")
        | map(select(test("\\S"))) | (first // "") | test("^\\s*launch-fleet:\\s*archived\\b"))
      | input_filename | capture("comments-(?<n>[0-9]+)[.]json$").n' "$@") \
      || die "can't read the issues outside specs"
  fi
  while read -r n id state; do
    if [ "$state" = closed ]; then
      case "
$archived
" in *"
$n
"*) continue ;; esac
    fi
    printf '%s\n' "$id" >> "$TMP/single-ids.txt" || die "can't read the issues outside specs"
  done < "$TMP/search-items.txt"
  set --
  while read -r id; do
    set -- "$@" -f "ids[]=$id"
    [ $# -lt 100 ] || { single_nodes "$@"; set --; }
  done < "$TMP/single-ids.txt"
  [ $# -eq 0 ] || single_nodes "$@"
  jq -s '[.[] | select(.parent == null and .subIssuesSummary.total == 0)]' "$TMP/singles.txt" > "$TMP/singles.json" \
    || die "can't read the issues"
}

# active: F6'"'"'s collision scope for a start claim (#1353): every open issue of
# the repository labelled ready-for-agent, in a spec or not, read in full into
# active.json, so the claim sees running and claimed work of every fleet. A
# search that lists fewer than it counts stops the claim.
active() {
  label=$(jq -er '."ready-for-agent"' "$TMP/labels.json") || die "can't read the labels"
  q="repo:$REPO is:issue is:open label:\"$label\""
  encoded=$(jq -rn --arg q "$q" '$q | @uri') || die "can't encode the open work search"
  endpoint="search/issues?q=$encoded&per_page=100" pages=0 listed=0 total=0
  : > "$TMP/active-ids.txt" && : > "$TMP/singles.txt" || die "can't write"
  while [ -n "$endpoint" ]; do
    pages=$((pages + 1))
    [ $pages -le 11 ] || die "the search for open work did not end"
    rest "$endpoint" "$TMP/search.json" || die "can't read the open work"
    jq -e 'type == "object" and .incomplete_results == false and (.total_count | type == "number")
      and (.items | type) == "array" and all(.items[]; (.node_id | type) == "string" and (.number | type) == "number")' \
      "$TMP/search.json" > /dev/null || die "can't read the open work"
    total=$(jq .total_count "$TMP/search.json") && n=$(jq '.items | length' "$TMP/search.json") || die "can't read the open work"
    listed=$((listed + n))
    jq -r '.items[].node_id' "$TMP/search.json" >> "$TMP/active-ids.txt" || die "can't read the open work"
    endpoint=$(next_page "$TMP/search.json.http") || die "can't read the open work search pagination"
  done
  [ "$listed" = "$total" ] || die "the search listed $listed of $total open tickets, so a colliding start could be missed"
  set --
  while read -r id; do
    set -- "$@" -f "ids[]=$id"
    [ $# -lt 100 ] || { single_nodes "$@"; set --; }
  done < "$TMP/active-ids.txt"
  [ $# -eq 0 ] || single_nodes "$@"
  jq -s . "$TMP/singles.txt" > "$TMP/active.json" && hydrate "$TMP/active.json" || die "can't read the open work"
}

# links_read: F6 (#1353): every link of every ticket read, labelled by
# to-tickets'"'"' check-links.sh, into the world as links {"T:B": {kind, files}}.
# A read the parser can't take labels nothing: every blocker stays hard.
links_read() {
  jq --arg repo "$REPO" '{schema: "openwiz.plan-links.v1", kind: "graph", repo: $repo, read_at: (.now | todate),
      source: {kind: "board"},
      tickets: ([.specs[].subIssues.nodes[], .singles[], .active[]] | map(select(.blockedBy != null)) | unique_by(.number)
        | map({number, title: (if (.title // "") == "" then "#\(.number)" else .title end), state,
               labels: ([.labels.nodes[]?.name] | unique), milestone: null, parent: null,
               blocked_by: ([.blockedBy.nodes[] | {number, state}] | unique_by(.number)),
               body: (.body // "" | gsub("\r"; "")), start_recorded: false, pull_requests: []}))}' \
    "$TMP/world.json" > "$TMP/graph.json" || die "can't build the links read"
  sh "$LINKS" --json --graph - < "$TMP/graph.json" > "$TMP/links.json" 2> "$TMP/links.err"
  status=$?
  [ $status -le 1 ] || printf '{"links": []}' > "$TMP/links.json" || die "can't write"
  jq --slurpfile r "$TMP/links.json" '.links = ($r[0].links | map({key: "\(.ticket):\(.blocker)", value: {kind, files}}) | from_entries)' \
    "$TMP/world.json" > "$TMP/w2.json" && mv "$TMP/w2.json" "$TMP/world.json" || die "can't read the links"
}

# selection: F6'"'"'s start set, admitted in number order, into the world.
selection() {
  jqw -j 'start_selection | tojson' > "$TMP/selected.json" \
    && jq --slurpfile s "$TMP/selected.json" '.selected = $s[0]' "$TMP/world.json" > "$TMP/w2.json" \
    && mv "$TMP/w2.json" "$TMP/world.json" || die "can't work out the start set"
}

# single_nodes -f ids[]=ID...: issues read in full, by id, into singles.txt.
single_nodes() {
  gql Nodes "$TMP/nodes.json" "$@"
  jq -e --argjson n $(($# / 2)) '.data.nodes | length == $n and all(.[]; type == "object" and has("number"))' "$TMP/nodes.json" > /dev/null \
    || die "can't read every issue the search listed"
  jq -c '.data.nodes[]' "$TMP/nodes.json" >> "$TMP/singles.txt" || die "can't read the issues outside specs"
}

# The shared rules, in jq. $W is the world: {now, default, checks, labels,
# specs, singles, followups, claim, fingerprints, branches, merged, prfiles}. $s is a ticket's spec, or null for
# an issue approved on its own.
LIB='
def lines: gsub("\r"; "") | split("\n");
def first_line: ([lines[] | select(test("\\S"))] | first) // "";
def rec: (first_line | sub("^\\s+"; "")) as $l
  | if ($l | startswith("launch-fleet:")) then ($l | ltrimstr("launch-fleet:") | sub("^\\s+"; "") | sub("\\s+$"; "")) else null end;
# In a claim ($W.claim: {n, id}), the claimed issue'"'"'s records are those older
# than the claim: the state the claim was made against.
def records: .number as $n | [.comments.nodes[] | {id: .databaseId, at: .createdAt, edited: (.updatedAt // .createdAt), thread: .resolvedThread, archiveThread: .archiveThread, error: .recordError, closed: (.reviewClosed // false), givenUp: (.givenUp // false), r: (.body | rec)} | select(.r != null)
  | select($W.claim == null or $n != $W.claim.n or .id < $W.claim.id)];
def plain: [.comments.nodes[] | select((.body | rec) == null)];
def kind($k): select(.r | test("^(" + $k + ")(\\b|$)"));
def age: $W.now - (.at | fromdateiso8601);
def thread: if .error != null then null else .thread // (.r | capture("thread (?<t>[^ ,;]+)") | .t) // null end;
# A reviewer that went quiet, as its claim was edited: "review failed <commit>,
# thread <id>: <why>". That thread is never re-checked or told again.
def failed_thread: if .error != null then null else .thread // (.r | capture("^review failed [0-9a-f]{40}, thread (?<t>[^ ,;:]+)") | .t) // null end;
def commits: [scan("\\b[0-9a-f]{40}\\b")];
def names($c): commits | any(.[]; . == $c);
def among($xs): . as $x | any($xs[]; . == $x);
# Run IDs distinguish reruns even when a newer job is still queued (no
# startedAt). Legacy statuses carry their own creation time. Never rely on
# context order or the aggregate state, which includes unrelated checks.
def latest_check:
  if length <= 1 then .[0]
  elif all(.[]; .__typename == "CheckRun" and (.databaseId | type) == "number") then max_by(.databaseId)
  elif all(.[]; .__typename == "StatusContext" and (.createdAt | type) == "string") then
    group_by(.createdAt) | last | unique | if length == 1 then .[0] else null end
  else null end;
def required_ci:
  . as $r
  | [$W.checks[] as $n
     | [$r.contexts.nodes[]? | select((.name // .context) == $n)] | latest_check
     | if . == null then "pending"
       elif .__typename == "CheckRun" and .status != "COMPLETED" then "pending"
       else (.conclusion // .state) as $s
         | if $s == "SUCCESS" then "green"
           elif ($s | among(["FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"])) then "failed"
           else "pending" end end] as $states
  | if any($states[]; . == "failed") then "failed"
    elif all($states[]; . == "green") then "green"
    else "pending" end;

# A start or review CloudRoom refused is tried again 10 minutes after the
# refusal, not sooner (ClosedWiz#259): the refusal'"'"'s record is itself one of
# GitHub'"'"'s messages, so a wake would otherwise retry at once, again and again.
# The refusal is the edit that made a claim one, so the wait runs from the
# comment'"'"'s last edit (its updatedAt), not from the claim (Sol R1 on #357).
# One probe per batch (#694): when a batch'"'"'s first start is refused, each
# other claim of that batch is recorded "start not tried: <why>" instead of
# being tried, and waits the same 10 minutes, so the batch retries together.
def refused_lately($last; $k): $last != null and ($last.r | test("^" + $k + " (refused|not tried)\\b"))
  and ($W.now - ($last.edited | fromdateiso8601)) < 600;
# A "look" line for #$n, unless one was raised already (its record "look: <why>").
def look($n; $rs; $why): ($why | gsub("\\bthr_[A-Za-z0-9][A-Za-z0-9_-]*"; "[private thread]")) as $why | if any($rs[]; (.r | gsub("\\bthr_[A-Za-z0-9][A-Za-z0-9_-]*"; "[private thread]")) == "look: \($why)") then empty else "look #\($n): \($why)" end;

# A spec'"'"'s approved plan graph: its latest comment that starts
# "**Plan graph approved by" (the to-tickets skill'"'"'s record), or to-tickets'"'"'
# machine plan approval (#1340, decisions.v1), read whole: its header, grill
# line, checks summary, optional changed line, table, fingerprint and revision
# text, in that layout, the table naming exactly the revision text'"'"'s tickets,
# titles and blockers. Anything less is no approval. Either has the revision
# number, a table with one row per ticket (| #<n> | <title> | <blocked by> |
# <label> |), and "Fingerprint: <the SHA-256 of the revision text>"; a machine
# record also its revision text, which the check hashes ($W.machine_text).
def at_($l; $i): $l[$i] // "";
def machine_record($ls): ($ls | until(length == 0 or .[-1] != ""; .[:-1])) as $l
  | (at_($l; 0) | capture("^\\*\\*Machine plan approval, [0-9]{4}-[0-9]{2}-[0-9]{2}, revision (?<n>[1-9][0-9]*):\\*\\* links, relies, sizes, width and owned paths passed\\.$") | .n | tonumber) as $n
  | select(at_($l; 1) | test("^Grill confirmed: https://github\\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*$"))
  | select(at_($l; 2) == "" and at_($l; 4) == "")
  | (at_($l; 3) | capture("^Checks: (?<t>[1-9][0-9]*) tickets; links [0-9]+; relies [0-9]+; sizes S [0-9]+, M [0-9]+, L [0-9]+; width: chain [0-9]+, widest [0-9]+; owned paths [0-9]+\\.$") | .t | tonumber) as $t
  | (if $n > 1 then (select((at_($l; 5) | test("^Changed since revision \($n - 1): .+\\.$")) and at_($l; 6) == "") | 7) else 5 end) as $k
  | select(at_($l; $k) == "| Ticket | Title | Blocked by | Label |" and at_($l; $k + 1) == "| --- | --- | --- | --- |")
  | ($k + 2 + $t) as $j
  | [$l[$k + 2:$j][] | capture("^\\| #(?<n>[1-9][0-9]*) \\| (?<title>.+) \\| (?<b>none|#[1-9][0-9]*(?: #[1-9][0-9]*)*) \\| (?<label>ready-for-agent|ready-for-human|none) \\|$")
     | {number: (.n | tonumber), title: (.title | gsub("\\\\\\|"; "|")), blockers: .b, label: .label}] as $rows
  | select(($rows | length) == $t and at_($l; $j) == "")
  | (at_($l; $j + 1) | capture("^Fingerprint: `(?<f>[0-9a-f]{64})`$") | .f) as $f
  | select(at_($l; $j + 2) == "" and at_($l; $j + 3) == "<details><summary>Revision text</summary>"
      and at_($l; $j + 4) == "" and at_($l; $j + 5) == "```text"
      and ($l | length) >= $j + 9 and $l[-3] == "```" and $l[-2] == "" and $l[-1] == "</details>")
  | $l[$j + 6:-3] as $rev
  | select(at_($rev; 0) == "plan-graph revision v2" and (at_($rev; 1) | test("^spec #[1-9][0-9]* body sha256 [0-9a-f]{64}$")))
  | [$rev[2:][] | capture("^ticket #(?<n>[1-9][0-9]*) blocked-by (?<b>none|#[1-9][0-9]*(?: #[1-9][0-9]*)*) body sha256 [0-9a-f]{64} title (?<title>.+)$")
     | {number: (.n | tonumber), title, blockers: .b}] as $named
  | select(($named | length) == ($rev | length) - 2
      and ($named | sort_by(.number)) == ($rows | map({number, title, blockers}) | sort_by(.number)))
  | {revision: $n, fingerprint: $f, text: (($rev | join("\n")) + "\n"), rows: ($rows | map({number, label: .label}))};
def approval: (.body | lines) as $ls | ($ls | map(select(test("\\S"))) | first // "" | sub("^\\s+"; "")) as $head
  | if ($head | startswith("**Plan graph approved by")) then
      {id: .databaseId, at: .createdAt, machine: false,
       revision: ([$head | capture(", revision (?<n>[0-9]+):\\*\\*") | .n | tonumber] | first),
       fingerprint: ([$ls[] | capture("^\\s*Fingerprint:\\s*`?(?<f>[0-9a-f]{64})`?\\s*$") | .f] | first),
       rows: [$ls[] | select(test("^\\|\\s*#[0-9]+\\s*\\|")) | split("|") | map(sub("^\\s+"; "") | sub("\\s+$"; "")) | .[1:-1]
              | select(length >= 4) | {number: (.[0] | ltrimstr("#") | tonumber), label: .[-1]}]}
    else (.databaseId as $id | .createdAt as $at | [machine_record($ls)] | first // empty | {id: $id, at: $at, machine: true} + .) end;
def latest($s): [$s.comments.nodes[] | approval] | max_by(.id);
def subs($s): [$s.subIssues.nodes[].number];
def row($s): . as $t | [latest($s).rows[]? | select(.number == $t.number)] | first;
# Current: the latest approval'"'"'s fingerprint is the one to-tickets'"'"'s
# revision.sh gives the plan now ($W.fingerprints, read only for a spec with a
# ticket that could start). Anything else is stale: nothing under it starts.
def plan_current($s): latest($s) as $a | $a.fingerprint as $f | $f != null and $f == $W.fingerprints["\($s.number)"]
  and (($a.machine | not) or $f == ($W.machine_text // {})["\($s.number)"]);
# R1: a contract hold is released by the owner'"'"'s approval (or a C2 record in
# its form), never by a machine revision.
def owner_at($s): [$s.comments.nodes[] | approval | select(.machine | not)] | max_by(.id) | .at;
# #1340: to-spec'"'"'s steering video is the spec'"'"'s latest comment that is exactly
# its link line, a blank line and "Comment here to steer: stop, reset, or
# anything else." (R3), or since WS33 (#1736) "Steering by comment is off for
# now: tell your orchestrator what to change (stop, reset, or anything else)."
# R2 (decision 7030919773): no comment on it steers, in
# any mode and whoever posted the video, until #1402'"'"'s identity separation is
# verified: no author can yet prove a comment is the owner'"'"'s. A spec with a
# video gets one look saying so (steer_lines); the owner steers through the
# orchestrator.
def video: [.comments.nodes[] | select(.body | gsub("\r"; "") | sub("\\s+$"; "")
  | test("^\\[Watch the narrated spec\\]\\(https://[^\\s<>()\\\\`]+\\)\n\n(Comment here to steer: stop, reset, or anything else|Steering by comment is off for now: tell your orchestrator what to change \\(stop, reset, or anything else\\))\\.$"))] | max_by(.databaseId);
def current($s): plan_current($s);
def spec_rec($s; $re): any($s | records[]; .r | test($re));
# The latest fleet record routes the spec to its loop. Fresh wakes keep the
# existing assignments, including agents whose records predate the loop.
def fleet($s): [($s.comments.nodes // [])[] | {id: .databaseId, at: .createdAt, body, error: .recordError} | select(.error == null) | . as $c
  | ((.body | rec) // "" | capture("^(?:fleet active, loop (?<loop>[A-Za-z0-9_-]+)|fleet thread (?<t>[A-Za-z0-9_][A-Za-z0-9_-]{0,127})(, loop (?<l>[A-Za-z0-9_][A-Za-z0-9_-]{0,127}))?)$"))
  | {id: $c.id, at: $c.at, thread: (.t // "private fleet"), loop: (.loop // .l),
     fresh: (.loop != null and ($c.body | split("\n") | index("Wake mode: fresh") != null))}] | max_by(.id);
# Only a legacy retained fleet thread uses the takeover cutoff.
def fleet_of($s): if $s != null and $W.spec == $s.number then (fleet($s) | if .fresh then null else . end) else null end;
# A record last edited before the fleet thread'"'"'s record, or in the same
# second: the agent it names was started by an earlier fleet thread or tick,
# so this one can'"'"'t reach it. A tie counts as before: a fleet thread records
# itself before it starts anything.
def inherited($f): $f != null and .edited <= $f.at;
# A recorded evidence gap waits for a newer verification on the spec.
def live_check_missing($s): [$s | records[] | select(.r == "look: live check not recorded as passed")] | max_by(.id);
def live_check_waiting($s): live_check_missing($s) as $missing
  | ([$s | records[] | select(.r | test("^live check passed\\b")) | .id] | max) as $passed
  | $missing != null and ($passed == null or $passed < $missing.id);
# An issue outside any spec starts only on the user'"'"'s approval of it alone
# (the triage skill'"'"'s record): "**Approved on its own by <user>, <date>:**".
def own: [.comments.nodes[] | select(.body | lines | any(.[]; test("^\\s*\\*\\*Approved on its own by "))) | .createdAt] | max;
def is_approved($s): if $s == null then own != null else row($s).label == $W.labels["ready-for-agent"] end;
def approved_at($s): if $s == null then own else latest($s).at end;
# A person'"'"'s ticket: its row says ready-for-human. Never started, but held like any other.
def is_person($s): $s != null and row($s).label == $W.labels["ready-for-human"];
def is_planned($s): is_approved($s) or is_person($s);
def where($s): if $s == null then "approved on its own" else "spec #\($s.number)" end;

# A ticket.
def labels: [.labels.nodes[].name];
def has_role($role): $W.labels[$role] as $l | any(labels[]; . == $l);
# An unapproved sub-issue can be new planned work, not a low follow-up.
def follow_up($s): any(labels[]; . == "polish")
  or ((.body // "" | first_line | sub("^\\s+"; ""))
      | test("^Follow-up of #[0-9]+ \\(spec #\($s.number)\\)"));
# The fleet contract'"'"'s (contracts/fleet.v1.md) "held" label: a held ticket never starts.
def labelled_held: any(labels[]; . == "held");
def verified_merge: any(.closedByPullRequestsReferences.nodes[]?; .merged == true and .baseRefName == $W.default);
def merged_ok: .state == "CLOSED" and verified_merge;
# A person can finish a blocker without a PR, with evidence on that ticket.
# Agent tickets retain the verified-merge requirement, even with both labels.
def person_labelled: .labels.pageInfo.hasNextPage == false
  and (any(.labels.nodes[]?; .name == $W.labels["ready-for-agent"]) | not)
  and any(.labels.nodes[]?; .name == $W.labels["ready-for-human"] or .name == "person");
def completion_record: any(.comments.nodes[]?; (.body | rec // "") | test("^complete:\\s*\\S"));
# #641: only a close as completed can complete person work. Not planned,
# duplicate, or a reason that could not be read, completes nothing.
def closed_completed: .state == "CLOSED" and .stateReason == "COMPLETED";
def blocker_done: merged_ok or (closed_completed and person_labelled and completion_record);
def completion_request:
  if .state == "CLOSED" and person_labelled and (closed_completed | not) then
    records as $rs | look(.number; $rs; "closed person ticket was closed as \(.stateReason // "unknown" | ascii_downcase | gsub("_"; " ")), so it completes nothing")
  elif .state == "CLOSED" and person_labelled and (.comments.nodes | type) == "array"
      and .comments.pageInfo.hasPreviousPage != true and (completion_record | not) then
    records as $rs | look(.number; $rs; "closed person ticket needs launch-fleet: complete: <evidence>")
  else empty end;

# Every approved row must still exist. Human work (including a live check) is
# recorded complete by its owner; a builder ticket also needs a verified merge.
def planned_done($s): latest($s) as $a
  | $a != null and ($a.rows | length) > 0
    and all($a.rows[]; . as $r
      | any($s.subIssues.nodes[]; .number == $r.number and .state == "CLOSED"
          and (if $r.label == $W.labels["ready-for-human"] then true
               else $r.label == $W.labels["ready-for-agent"] and verified_merge end)));
def stall_why($s; $r): if any($s.subIssues.nodes[]; .number == $r.number) | not then "planned #\($r.number) is not a sub-issue of the spec"
  else $s.subIssues.nodes[] | select(.number == $r.number)
    | if .state == "CLOSED" and (verified_merge | not) then "planned #\(.number) is closed without a verified merge"
      else empty end
  end;
# A stalled planned row, once: only a "look: <the same reason>" record settles
# it, so an unrelated historical look never hides a stall.
def stall_lines($a): . as $s | records as $rs
  | [$rs[].r | select(startswith("look: ")) | ltrimstr("look: ")] as $said
  | if $a == null then empty else [$a.rows[] | select(.label == $W.labels["ready-for-agent"])] as $rows
    | $rows[] | stall_why($s; .) | select(. != null)
    | select((. | among($said)) | not)
    | "look #\($s.number): \(.)"
    end;

def open_prs: [.closedByPullRequestsReferences.nodes[] | select(.state == "OPEN")];
def start: records as $rs
  | [$rs[] | kind("started|start checked")] as $live
  | [$rs[] | kind("starting")] as $claims
  | if ($live | length) > 1 then {state: "duplicate", rec: $live[0]}
    elif ($live | length) == 1 then {state: (if $live[0].r | test("^start checked") then "checked" else "started" end), rec: $live[0]}
    elif ($claims | length) > 0 then {state: "claimed", rec: ($claims | min_by(.id))}
    else {state: "queued", last: ([$rs[] | kind("start refused|start not tried|start failed")] | max_by(.id))} end;
def builder: start as $st | if $st.rec then ($st.rec | thread) else null end;
def bthread: builder as $b | if $b then ", thread \($b)" else "" end;
def building: start.state != "queued" or (open_prs | length) > 0;
# A new wait replaces the previous one. Read the explicit record, or the
# legacy orchestrator instruction that stranded builders on #326 (#467).
def waiting: [.comments.nodes[] | . as $c | (.body | first_line) as $line
  | ([(.body | rec // "") | capture("^waiting for #(?<n>[1-9][0-9]{0,8})$")]
     + [$line | capture("^Orchestrator(?: \\([^\\r\\n]*\\))?: \\*\\*(?:(?:yes|confirmed)[,:] )?wait for #(?<n>[1-9][0-9]{0,8})\\.?\\*\\*(?:\\s|$)")])[]
  | {id: $c.databaseId, number: (.n | tonumber)}] | max_by(.id);
def pending_wait: waiting as $w | records as $rs
  | if $w != null and (any($rs[]; .r == "resume sent \($w.id) for #\($w.number)") | not) then $w else null end;

def resume_claim($w): [records[] | select(.r | test("^resume starting \($w.id) for #\($w.number)(, thread thr_[A-Za-z0-9_-]+)?$"))] | min_by(.id);

def looks: [
  (records[] | select(.error != null) | .error),
  (if .comments.pageInfo.hasPreviousPage then "comment history could not be read in full" else empty end),
  (if .labels.pageInfo.hasNextPage then "more than 20 labels" else empty end),
  (if .blockedBy.pageInfo.hasNextPage then "more than 20 blockers" else empty end),
  (if .closedByPullRequestsReferences.pageInfo.hasNextPage then "more than 5 linked pull requests" else empty end),
  (if start.state == "duplicate" then "more than one builder is recorded as started" else empty end),
  (open_prs as $o | if ($o | length) > 1 then "more than one open pull request: \($o | map("#\(.number)") | join(", "))" else empty end)];

# Contracts: inline declarations and historical plan-graph heading sections.
# Keep reading both forms until the orchestrator migrates the old tickets;
# a later Markdown heading ends the legacy section.
def relies: reduce ((.body // "") | lines[]) as $line
    ({section: false, paths: []};
     if ($line | test("^## Relies on\\s*$")) then .section = true
     elif ($line | test("^#{1,6}\\s")) then .section = false
     elif .section or ($line | test("^\\s*\\**Relies on:")) then
       .paths += [$line | scan("`([^`]+)`") | .[0]]
     else . end)
  | .paths | unique;
def matches($p): . as $f
  | if ($p | endswith("/")) then ($f | startswith($p))
    elif ($p | contains("*")) then ($f | test("^" + ($p | gsub("(?<c>[.+?^${}()|\\[\\]\\\\])"; "\\\(.c)") | gsub("\\*"; "[^/]*")) + "$"))
    else $f == $p end;
def cutoff($s): approved_at($s);
def hits($s): . as $t | cutoff($s) as $c | relies as $ps
  | if $c == null or ($ps | length) == 0 then [] else
      [$W.merged[] | select(.closes as $cl | .mergedAt > $c and ($t.number | among($cl) | not))
       | {pr: .number, files: ([.files[] | select(.status != "added") | (.filename, .previous_filename)
           | select(. != null) | select(. as $f | any($ps[]; . as $p | $f | matches($p)))] | unique)}
       | select(.files | length > 0)] | sort_by(.pr) end;
def due_notes($s): records as $rs | [hits($s)[] | .pr as $p | select(any($rs[]; .r | test("^(held for|noted) #\($p)\\b")) | not)];
def held($s): ([records[] | kind("held for") | select(.r | startswith("held for ordering:") | not) | .at] | max) as $h | (if $s == null then own else owner_at($s) end) as $a
  | $h != null and ($a == null or $h > $a);
# Every hold comment of any kind, as read: a `held ...` record (contract,
# ordering, manual, live), an `Orchestrator: **held` instruction, or a plain
# comment whose first line mentions a hold or being held.
def hold_comments: [.comments.nodes[]
  | . as $c | (.body | first_line) as $l | (.body | rec // "") as $r
  | select(($r | test("^held\\b"))
      or ($l | test("^Orchestrator(?: \\([^)]*\\))?: \\*\\*held"))
      or (($c.body | rec) == null and ($l | test("(?i)\\bhold|\\bheld\\b"))))
  | {id: $c.databaseId, at: $c.createdAt, line: $l, r: $r}];
# A hold of launch-fleet'"'"'s own that a newer approval has released. The held
# label on the ticket is launch-fleet'"'"'s only when launch-fleet'"'"'s "held for"
# record is no older than the label'"'"'s latest going on (its timeline): a held
# label put on later, by to-tickets or anyone, is theirs to take off.
def held_since: [.timelineItems.nodes[]? | select(.label.name == "held") | .createdAt] | max;
# The newest unresolved hold of any kind decides, failing closed (#2218): every
# hold comment since the label last went on must be a contract `held for #<P>`
# record. A manual, live, ordering or plain hold there, newer or older than the
# approval, keeps it held: each keeps its own release evidence.
def released($s): held_since as $since | (if $s == null then own else owner_at($s) end) as $a
  | ([records[] | kind("held for") | select(.r | startswith("held for ordering:") | not) | .at | select($since != null and . >= $since)] | max) as $h
  | $h != null and $a != null and $a > $h
    and all(hold_comments[] | select(.at >= $since); .r | test("^held for #[1-9][0-9]{0,8}(\\b|$)"));

# An ordering hold is explicit and exclusive. A newer hold record replaces it,
# including manual/contract/live records and ambiguous plain hold instructions.
# Plain prose can revoke ownership, but grants no release authority.
# The legacy ordering-only form used before structured records is deliberately
# narrow: the prerequisite in its release sentence must be the same issue.
def ordering_hold:
  (hold_comments | max_by(.id)) as $h
  | if $h == null then null else
      ([$h.r | capture("^held for ordering: (?<kind>issue|PR) #(?<n>[1-9][0-9]{0,8}) merges to main$")]
       + [$h.line | capture("^Orchestrator: \\*\\*held for ordering only; the plan and its approval are unchanged\\.\\*\\* #(?<n>[1-9][0-9]{0,8}) .+ Released \\(`ready-for-agent` back, `held` off\\) as soon as #(?<release>[1-9][0-9]{0,8}) merges\\.$")
          | select(.n == .release) | . + {kind: "issue"}] | first) as $parsed
      | if $parsed == null then null else $h + {kind: $parsed.kind, number: ($parsed.n | tonumber)} end end;
def ordering_done($h): any(.comments.nodes[]; (.body | rec) == "released ordering \($h.id)");
def ordering_claim($h): [records[] | select(.r | test("^release starting \($h.id)(, thread thr_[A-Za-z0-9_-]+)?$"))] | min_by(.id);
def ordering_owned($h): $h != null and labelled_held and held_since != null and $h.at >= held_since;
def ordering_open_claims: . as $t
  | [.comments.nodes[] | . as $c | (.body | rec // "") as $r
     | [$r | capture("^release starting (?<h>[0-9]+)(, thread thr_[A-Za-z0-9_-]+)?$")][]
     | (.h | tonumber) as $id | select($t | ordering_done({id: $id}) | not)
     | {id: $c.databaseId, hold: $id, at: $c.createdAt, edited: ($c.updatedAt // $c.createdAt), r: $r}];
def ordering_inflight: (ordering_open_claims | length) > 0;
# An existing contract hold needs a newer approval, exclusive hold ownership,
# and no unresolved release claim. The plan fingerprint is checked for each candidate.
def release_candidate($s): labelled_held and released($s) and (ordering_inflight | not);
def release_due($s): release_candidate($s)
  and ($s == null or (current($s) and $W.fingerprint_agreement["\($s.number)"] == true));
# F6 (#1353): only a hard blocker holds a start. A native blocker is context,
# and holds nothing, only when to-tickets'"'"' check-links.sh (the plan-links
# parser, $W.links) reads its one line as a `file` line naming a file, its
# blocker is read here with owned paths, neither the blocker'"'"'s owned paths
# nor the line'"'"'s files hold an input the ticket relies on, and the two
# tickets'"'"' owned paths don'"'"'t clash. Anything else is hard.
def scope_tickets: [$W.specs[].subIssues.nodes[], $W.singles[], ($W.active // [])[]];
# Owned paths exactly as to-tickets'"'"' approve.py reads them: the lines under
# `## Owned paths` to the next `## `, each `- ` bullet'"'"'s backticked paths, in
# its one `in \`owner/repo\`` repository or this one, shared when the bullet
# says `(shared`. [] when the ticket has no such section (a legacy ticket
# claims no path); null when the section can'"'"'t be read as approval reads it.
def owned_paths: ((.body // "") | split("\n")) as $l
  | ([range(0; $l | length) | select($l[.] | rtrimstr("\r") | test("^## Owned paths\\s*$"))] | first) as $h
  | if $h == null then [] else
      ([$l[$h + 1:][] | rtrimstr("\r")] | (([to_entries[] | select(.value | startswith("## ")) | .key] | first) // length) as $e | .[:$e]
       | map(select(startswith("- ")) | .[2:])) as $bullets
      | if ($bullets | length) == 0 then null else
          [$bullets[] | . as $b | [scan("\\bin `([^`]+)`") | .[0]] as $repos
           | if ($repos | length) > 1 or any($repos[]; test("^[A-Za-z0-9-]+/[A-Za-z0-9_.-]+$") | not) then {bad: true}
             else ([scan("`([^`]+)`") | .[0] | select(. as $p | any($repos[]; . == $p) | not)]) as $ps
               | if ($ps | length) == 0 then {bad: true}
                 else $ps[] | (rtrimstr("/") | split("/")) as $parts
                   | if startswith("/") or any($parts[]; . == "" or . == "." or . == "..") or contains(" ") then {bad: true}
                     else {repo: (if ($repos | length) == 1 then $repos[0] | ascii_downcase else $W.repo end),
                           path: ., shared: ($b | contains("(shared"))} end end end]
          | if any(.[]; .bad) then null else . end end end;
# fnmatch.fnmatchcase, as approve.py matches a path segment: * ? [seq] [!seq].
def glob_re: explode as $c | ($c | length) as $n
  | {i: 0, out: "^"} | until(.i >= $n;
      $c[.i] as $ch
      | if $ch == 42 then .out += ".*" | .i += 1
        elif $ch == 63 then .out += "." | .i += 1
        elif $ch == 91 then
          (.i + 1) as $j0 | (if $j0 < $n and $c[$j0] == 33 then $j0 + 1 else $j0 end) as $j1
          | (if $j1 < $n and $c[$j1] == 93 then $j1 + 1 else $j1 end) as $j2
          | ([range($j2; $n) | select($c[.] == 93)] | first) as $close
          | if $close == null then .out += "\\[" | .i += 1
            else ($c[.i + 1:$close] | implode | gsub("\\\\"; "\\\\") | gsub("(?<x>[&~|])"; "\\\(.x)")) as $body
              | .out += "[" + (if ($body | startswith("!")) then "^" + $body[1:]
                               elif ($body | test("^[\\^\\[]")) then "\\" + $body else $body end) + "]"
              | .i = $close + 1 end
        else ([$ch] | implode) as $x
          | .out += (if ($x | test("[.+?^${}()|\\[\\]\\\\]")) then "\\" + $x else $x end) | .i += 1 end)
  | .out + "$";
def segment($p): . as $f | $f | test($p | glob_re);
def overlaps($a; $b): ($a | rtrimstr("/") | split("/")) as $x | ($b | rtrimstr("/") | split("/")) as $y
  | all(range([($x | length), ($y | length)] | min); $x[.] as $p | $y[.] as $q | ($p | segment($q)) or ($q | segment($p)));
# Two tickets'"'"' owned paths clash: one claims no path ([]) never clashes; an
# unreadable side (null) always does; otherwise an overlap in one repository
# where not both bullets say `(shared`.
def paths_clash($a; $b): if $a == [] or $b == [] then false elif $a == null or $b == null then true
  else any($a[]; . as $x | any($b[]; .repo == $x.repo and overlaps(.path; $x.path) and ((.shared and $x.shared) | not))) end;
def context_blocker($n): . as $t | $W.links["\($t.number):\($n)"] as $link
  | ([scope_tickets[] | select(.number == $n)] | first) as $b
  | $link != null and $link.kind == "file" and ($link.files | length) > 0 and $b != null
    and (($b | owned_paths) as $bp | $bp != null and ($bp | length) > 0
      and ([$t | relies[]] as $in | any($in[]; . as $i | any(($bp | map(.path))[], $link.files[]; overlaps($i; .))) | not)
      and (paths_clash($t | owned_paths; $bp) | not));
def hard_blockers_done: . as $t | all(.blockedBy.nodes[]; blocker_done or (.number as $n | $t | context_blocker($n)));
# Same ordinary start guards, before requiring a ready label or no held label.
# The release path must be able to check these while ready is still removed.
def start_clear($s):
  ([has_role("needs-info"), has_role("needs-triage"), has_role("ready-for-human"), has_role("wontfix")] | any | not)
  and hard_blockers_done
  and start.state == "queued"
  and (open_prs | length) == 0
  and (held($s) | not);
def ready_but_current($s): has_role("ready-for-agent") and start_clear($s)
  and (labelled_held | not) and (ordering_inflight | not);
# KN13 (#1448): the text of a ticket is an order only from people the project
# trusts. The latest labelled event of the ready label must be by a maintainer (a
# record author, or a collaborator with write access, read only for a ticket
# that could otherwise start), and the body unedited since, by anyone; else a
# maintainer must put the label on again. GraphQL names the bot of an App without
# "[bot]". Who added it can'"'"'t be read (not in the last 20 labelled events,
# or no actor) refuses too.
def login_of: if type != "object" or (.login | type) != "string" then null
  elif .__typename == "Bot" then "\(.login)[bot]" else .login end
  | if . == null then null else ascii_downcase end;
def approval_label: $W.labels["ready-for-agent"] as $l | [.timelineItems.nodes[]? | select(.label.name == $l)] | max_by(.createdAt);
def maintainer: . != null and (among($W.authors) or among($W.writers));
def approver_why: approval_label as $e | $W.labels["ready-for-agent"] as $l
  | if $e == null then "who added \($l) can'"'"'t be read"
    elif ($e.actor | login_of | maintainer | not) then "\($l) was last added at \($e.createdAt) by someone who is not a maintainer"
    elif .lastEditedAt != null and .lastEditedAt > $e.createdAt then "the ticket was edited at \(.lastEditedAt), after \($l) was added at \($e.createdAt)"
    # GitHub'"'"'s times are to the second: an edit in the label'"'"'s own second
    # may have come after it (R1 on WizSkills#67).
    elif .lastEditedAt != null and .lastEditedAt == $e.createdAt then "the ticket was edited at \(.lastEditedAt), the same second \($l) was added, so which came first can'"'"'t be read"
    else null end
  | if . == null then null else "start refused: \(.); a maintainer must add it again" end;
def ready_unchecked($s): ready_but_current($s) and ($s == null or current($s));
def ready($s): ready_unchecked($s) and approver_why == null;
def unrefused_ready($s): ready($s) and (refused_lately(start.last; "start") | not);
# F6 (#1353): a running ticket is an open one with a builder (or a claim) or
# a pull request. The start set is admitted in number order: each ready ticket
# whose owned paths clash with no running ticket'"'"'s and no ticket admitted
# before it ($W.selected, worked out once a read, after the fingerprints).
# An unreadable Owned paths section is never admitted.
def running_clash: . as $t | owned_paths as $mine
  | any(scope_tickets[] | select(.number != $t.number and .state == "OPEN" and building); paths_clash($mine; owned_paths));
def may_start($s): unrefused_ready($s) and (.number as $n | any(($W.selected // [])[]; . == $n));
# A fleet thread'"'"'s takeover (ClosedWiz#192) starts a builder too, so it keeps
# every gate of an ordinary start (Sol R1 on #1517): approved and current,
# ready, no other triage label, its blockers merged and no hold.
# Only the gates a takeover is already past are left out: a
# recorded builder and its open pull request.
def takeover_clear($s): has_role("ready-for-agent")
  and ([has_role("needs-info"), has_role("needs-triage"), has_role("ready-for-human"), has_role("wontfix")] | any | not)
  and hard_blockers_done and (running_clash | not)
  and (held($s) | not) and (labelled_held | not) and (ordering_inflight | not);
def takeover_ready($s): takeover_clear($s) and current($s);
# The orchestrator archived the old builder: "old builder archived, thread <id>".
def old_archived: any(records[]; .r | test("^old builder archived, (thread |start [0-9]+$)"));
# A builder from before the fleet thread, archived, so the fleet may start its own.
def takeover_start($s): fleet_of($s) as $f | start as $st
  | $f != null and ($st.state == "started" or $st.state == "checked") and ($st.rec | inherited($f))
    and (($st.rec | thread) as $x | $x != null and any(records[]; (.r == "old builder archived, thread \($x)" or .r == "old builder archived, start \($st.rec.id)")));
# A takeover start CloudRoom refused, or that failed: the ticket has no builder
# now, with or without a pull request (Sol R2 on #1517).
def taking_over($s): fleet_of($s) != null and start.state == "queued" and start.last != null and old_archived;
# A takeover that would start a builder now, for the approval check.
def takeover_due($s): (takeover_start($s) or (taking_over($s) and (refused_lately(start.last; "start") | not)))
  and takeover_clear($s);
def ordering_candidate($s): ordering_hold as $h
  | .state == "OPEN" and is_approved($s) and (looks | length) == 0
    and ordering_owned($h) and (ordering_done($h) | not) and start_clear($s)
    and (refused_lately(start.last; "start") | not);
def ordering_merged($h):
  if $h.kind == "issue" then $W.waited["\($h.number)"] as $b
    | $b != null and $b.closedByPullRequestsReferences.pageInfo.hasNextPage == false and ($b | merged_ok)
  else $W.waited["PR:\($h.number)"] as $b
    | $b != null and $b.state == "closed" and $b.merged == true and $b.base.ref == $W.default end;
def ordering_due($s): ordering_hold as $h
  | ordering_candidate($s) and ordering_merged($h)
    and all(ordering_open_claims[]; .hold == $h.id)
    and ($s == null or (current($s) and $W.fingerprint_agreement["\($s.number)"] == true));
def ordering_lines($s): (ordering_open_claims | min_by(.id)) as $claim
  | if $claim != null then
      if ($W.now - ($claim.edited | fromdateiso8601)) >= 600 then
        "reconcile release #\(.number): ordering hold \($claim.hold); reconcile comment \($claim.id), thread \($claim | thread)"
      else empty end
    else ordering_hold as $h
      | if $h != null and ordering_due($s) then
          "release #\(.number): ordering hold \($h.id); \($h.kind) #\($h.number) merged to main; restore ready-for-agent and remove held"
        else empty end end;
# Held ordering candidates must reach both full-plan wake upgrades and current
# fingerprints before a release can be offered. Labels/merges are never cached
# as approval evidence.
def to_check: [$W.specs[] as $s | select(latest($s) != null)
  | select(any($s.subIssues.nodes[]; .state == "OPEN" and is_approved($s) and (looks | length) == 0
               and ((ready_but_current($s) and (refused_lately(start.last; "start") | not)) or ordering_candidate($s)
                    or takeover_due($s))
               or (.state == "OPEN" and (looks | length) == 0 and release_candidate($s))))
  | $s.number] | unique | .[];

# The re-test guard (K9, #337), under M1 (the #326 lesson): an approved,
# green head merges only when main has changed nothing it may clash with
# since the main its CI provably tested; otherwise CI runs again on the
# latest main first. Each required check counts its latest workflow run
# (by createdAt; a re-run keeps its run'"'"'s), which must be green.
# - What its CI tested: GitHub builds a pull request'"'"'s test merge lazily,
#   and a reopen or a re-run can reuse an old one (#258'"'"'s first reopen
#   tested a main three merges old), so a run'"'"'s time proves nothing. A test
#   merge is always built after its head exists, so by default its CI tested
#   at least main as of the head'"'"'s committedDate. The loop'"'"'s own re-test
#   claims "re-test starting <head>", reopens, reads the base B its new CI
#   run R checked out and edits the claim to "re-test sent <head> on <B> in
#   run <R>": once every required check'"'"'s latest run is R, created after the
#   claim, the CI is credited with B (when main merged B, by $W.merged), so
#   with every merge up to B'"'"'s. Checks from any other run earn no credit.
# - A pull request closed within 10 minutes of its own unfinished re-test claim
#   ("re-test starting <head>", not yet sent or failed), and not reopened, gets
#   a "reopen" line, so a re-test cut short never strands it. A closure after
#   a finished re-test, or later, is someone'"'"'s choice and is left alone.
# - A clash: a merge into main after that whose files and the pull
#   request'"'"'s share one (renames both ways), or, until a test-read map exists
#   (K15), where one side changed a test file (under tests/, test/, spec/,
#   __tests__/ or fixtures/; test.sh, test_*, *_test.*, *.test.*, *_spec.*,
#   *.spec.*) and the other anything but docs (*.md, docs/) (Q2 A on #337).
#   A re-test with no full base recorded earns no credit. The same goes for two heads ready to merge in one
#   check: only the lower number gets its merge line.
# - A clash merged before the re-test'"'"'s claim yet missing from B means
#   GitHub reused an old test merge: its builder merges main in instead, asked
#   once ("merge main asked <head>").
# A merge in the same second counts as after, as in doubt. The first pass
# prints "guard #P <time>" for the check to read the pull request'"'"'s files
# ($W.prfiles) and main'"'"'s merges since <time> ($W.merged); the second has them.
def file_names: [.[] | .filename, .previous_filename | select(. != null)] | unique;
def is_test: test("(^|/)(tests?|spec|__tests__|fixtures)/|(^|/)test\\.sh$|(^|/)test_[^/]+$|[_.](test|spec)\\.[^/]+$");
def is_doc: test("\\.md$") or startswith("docs/");
# What $theirs changed that may clash with $mine (both lists of names), and why.
def clash($mine; $theirs):
  [$theirs[] | select(among($mine))] as $same
  | if ($same | length) > 0 then {files: $same, why: ""}
    elif any($mine[]; is_test) and any($theirs[]; is_doc | not) then
      {files: [$theirs[] | select(is_doc | not)], why: " (its tests may read them)"}
    elif any($theirs[]; is_test) and any($mine[]; is_doc | not) then
      {files: [$theirs[] | select(is_test)], why: " (tests that may read its files)"}
    else null end;
def guard($p; $at; $rs; $head; $c):
  # Each required check'"'"'s latest run, as required_ci picks it (latest_check).
  [$W.checks[] as $n | [$c.statusCheckRollup.contexts.nodes[]? | select((.name // .context) == $n)] | latest_check] as $latest
  | if any($latest[]; . == null or (.conclusion // .state) != "SUCCESS") then empty
    elif any($latest[]; (.checkSuite.workflowRun.createdAt | type) != "string") then
      look($p.number; $rs; "a required check on its head names no workflow run, so main'"'"'s moves since its CI can'"'"'t be checked")
    elif ($c.committedDate | type) != "string" then
      look($p.number; $rs; "its head has no commit time, so main'"'"'s moves since its CI can'"'"'t be checked")
    else
      ( ([$latest[].checkSuite.workflowRun.createdAt] | min) as $ran
        | ([$c.committedDate, $ran] | min) as $t0
        | $W.prfiles["\($p.number)"] as $mine
        | if $mine == null then "guard #\($p.number) \($t0)"
          else
            ($mine | file_names) as $names
            | ([$rs[] | select(.r | test("^re-test (starting|sent) " + $head + "\\b"))] | max_by(.id)) as $claim
            | ($claim != null and $ran > $claim.at) as $rerun
            | ([$claim.r // "" | capture("^re-test sent [0-9a-f]{40} on (?<b>[0-9a-f]{40}) in run (?<run>[1-9][0-9]{0,19})\\b")] | first) as $rec
            | (if $rerun and $rec != null
                  and all($latest[]; (.checkSuite.workflowRun.databaseId | tostring) == $rec.run)
               then $rec.b else null end) as $b
            | ([$W.merged[] | select($b != null and .commit == $b)] | first) as $base
            | (if $base != null then [$t0, $base.mergedAt] | max else $t0 end) as $since
            | [$W.merged[] | select(.mergedAt >= $since and (.commit == $b | not))
                | {pr: .number, at: .mergedAt} + (clash($names; .files | file_names) // {files: []})
                | select(.files | length > 0)] | sort_by(.pr)
            | . as $clashes
            | ($clashes | map("\(.files | join(", ")) in #\(.pr)\(.why)") | join("; ")) as $what
            | if length == 0 then
                if any($W.prfiles | to_entries[]; (.key | tonumber) < $p.number
                       and clash($names; .value | file_names) != null) then empty
                else "merge \($at): APPROVE and CI green" end
              elif $base != null and any($clashes[]; .at < $claim.at) then
                (if any($rs[]; .r | test("^merge main asked " + $head + "\\b")) then empty
                 else "merge main in \($at): its re-test ran on main at \($b), without \($what); tell its builder to merge main in" end)
              elif $claim != null and ($rerun | not) and ($claim | age) < 1800 then empty
              else "re-test \($at): main changed \($what) after \($since), which its CI may not have tested; run its CI again on the latest main"
                + (if $claim != null and ($rerun | not) then " (again: no new run 30 minutes after it was claimed)" else "" end)
              end
          end)
    end;

# A reviewer from before the fleet thread is out of its reach: give it up at
# once, as a quiet one is, so a fresh reviewer starts (ClosedWiz#192).
def out_of_reach($at; $th; $f; $rec):
  "check review \($at): its reviewer, thread \($th), was started before fleet thread \($f.thread), so it is out of reach; record review given up (its record: comment \($rec.id))";

# What each part of a spec has due.
def ticket_lines_now($s): . as $t
  | if .comments.pageInfo.hasPreviousPage then look(.number; []; "comment history could not be read in full")
    elif .state == "CLOSED" and any(.closedByPullRequestsReferences.nodes[]; .comments.pageInfo.hasPreviousPage) then
      (.closedByPullRequestsReferences.nodes[] | select(.comments.pageInfo.hasPreviousPage)
       | look(.number; []; "comment history could not be read in full"))
    elif .state == "CLOSED" then
      completion_request,
      ([(records[] | kind("started|start checked") | thread),
        (.closedByPullRequestsReferences.nodes[] | records[] | (kind("review started") | thread), (kind("review failed") | failed_thread), (select(.givenUp) | .archiveThread))]
       | map(select(. != null)) | unique) as $th
      | if ($th | length) > 0 and (any(records[]; .r | test("^archived\\b")) | not)
        then "archive #\(.number): closed; archive \($th | join(", "))" else empty end
    elif (is_planned($s) | not) then empty
    elif (looks | length) > 0 then records as $rs | looks[] | look($t.number; $rs; .)
    elif is_person($s) then
      (if release_due($s) then "release #\(.number): approved again since its hold; take the held label off" else empty end),
      (if has_role("ready-for-human") and (labelled_held | not) and (held($s) | not)
          and all(.blockedBy.nodes[]; blocker_done) and (.blockedBy.pageInfo.hasNextPage | not)
          and (any(records[]; .r | test("^told the user\\b")) | not)
       then "person #\(.number): \(.title) (spec #\($s.number)) is ready, and only the user can do it" else empty end)
    else
      ordering_lines($s),
      (if release_due($s) and (ordering_hold == null) then "release #\(.number): approved again since its hold; take the held label off" else empty end),
      (if building then due_notes($s)[]
        | "note #\($t.number): \(.files | join(", ")) changed in #\(.pr); tell its builder\($t | bthread)"
        else empty end),
      (pending_wait as $w
       | if builder == null or $w == null then empty
         else $W.waited["\($w.number)"] as $b | resume_claim($w) as $claim
           | if $b.closedByPullRequestsReferences.pageInfo.hasNextPage == true then
               records as $rs | look(.number; $rs; "waited-on #\($w.number) has more than 5 linked pull requests")
             elif ($b | merged_ok) then
               if $claim == null then "resume #\(.number): #\($w.number) merged; tell its builder\(bthread) (wait comment \($w.id))"
               elif ($W.now - ($claim.edited | fromdateiso8601)) >= 600 then
                 "reconcile resume #\(.number): wait comment \($w.id) for #\($w.number); reconcile comment \($claim.id), thread \($claim | thread)"
               else empty end
             else empty end end),
      (if has_role("needs-info") then
         # A question or answer edited since it was asked counts as new (R1 on #1442).
         ([plain[] | .updatedAt // .createdAt] | max) as $q | ([records[] | kind("asked the orchestrator|granted") | .at] | max) as $a
         | if $a == null or ($q != null and $q > $a) then "needs-info #\(.number): a question for the orchestrator" else empty end
       else empty end),
      (start as $st
       | if $st.state == "queued" then
           (if may_start($s) then "start #\(.number): \(.title) (\(where($s))"
              + (if $st.last then "; retry after \"\($st.last.r)\"" else "" end) + ")"
            elif ready_unchecked($s) and (refused_lately(start.last; "start") | not) and approver_why != null then
              records as $rs | look(.number; $rs; approver_why)
            else empty end)
         elif $st.state == "claimed" then
           # From the edit that made it a claim: a takeover edits an older record
           # to "starting" (Sol R3 on #1517); a new claim'"'"'s edit is its creation.
           (if ($W.now - ($st.rec.edited | fromdateiso8601)) >= 600 then "reconcile start #\(.number): claimed at \($st.rec.edited), no outcome after 10 minutes" else empty end)
         elif $st.state == "started" then
           ($W.branches["\(.number)"] // []) as $br
           | if ($br | length) > 0 then "check start #\(.number): thread \($st.rec | thread), branch \($br | join(", "))"
             elif ($st.rec | age) < 1800 then empty
             elif has_role("needs-info") then
               # One wake per unchanged blocker (#694): a builder blocked on its
               # scope question has no branch to show. Its state key is the
               # start record and the latest plain comment activity (the
               # question or an answer, written or edited; never launch-fleet'"'"'s
               # own records): the look is raised once per key, and again only
               # when an answer, an edit, a new start or the label coming off
               # changes it (R1 on #1442).
               records as $rs
               | ([plain[] | {id: .databaseId, at: (.updatedAt // .createdAt)}] | max_by([.at, .id])) as $act
               | look(.number; $rs; "blocked on scope \($st.rec.id)/\(if $act == null then "none" else "\($act.id)@\($act.at)" end): thread \($st.rec | thread) has no branch")
             else "check start #\(.number): thread \($st.rec | thread), no branch 30 minutes after the start" end
         else empty end),
      (open_prs | map(select(.isDraft | not)) | first // empty | . as $p | .headRefOid as $head
       | records as $rs
       | "#\(.number) for #\($t.number) at \($head)" as $at
       | (.commits.nodes[0].commit // {}) as $c
       | if .baseRefName != $W.default then look(.number; $rs; "its base is \(.baseRefName), not \($W.default)")
         elif .comments.pageInfo.hasPreviousPage then look(.number; $rs; "comment history could not be read in full")
         elif any($rs[]; .error != null) then ([$rs[] | select(.error != null) | .error] | unique[] | look($p.number; $rs; .))
         elif $c.statusCheckRollup != null and $c.statusCheckRollup.contexts.pageInfo.hasNextPage != false then look(.number; $rs; "check contexts could not be read in full")
         # GitHub shortens messageHeadline; the hand-back marker may be beyond
         # its ellipsis. Read the full subject, never a green word in the body.
         elif (($c.message // "" | split("\n")[0] // "") | test("\\bgreen\\b"; "i") | not) then empty
         else
           ($c.statusCheckRollup | required_ci) as $ci
           | ([$p.comments.nodes[] | select(.body | startswith("VERDICT: "))] | max_by(.databaseId)) as $v
           | ([$v.body // "" | first_line | capture("^VERDICT: (?<verdict>APPROVE|CHANGES) at (?<commit>[0-9a-f]{40})\\s*$")] | first) as $verdict
           | if $ci == "failed" then
               (if any($rs[]; (.r | test("^CI failure sent\\b")) and (.r | names($head))) then empty
                else "CI failed \($at): tell its builder\($t | bthread)" end)
             elif $ci != "green" then empty
             elif $v != null and $verdict == null then look($p.number; $rs; "its latest VERDICT line is not \"VERDICT: APPROVE|CHANGES at <the full commit>\"")
             elif $verdict != null and $verdict.commit == $head then
               (if $verdict.verdict == "APPROVE" then
                  ([$rs[] | kind("merge blocked") | select(.r | names($head))] | max_by(.id)) as $block
                  # A reopen asks CI to run again on this same approved head.
                  # Once its checks are green, that retry is due again (#467),
                  # and the re-test guard (#337) still decides the merge.
                  | (if $block != null and (($block.r | test("^merge blocked \($head): base moved, reopened for fresh CI(?:[.;](?:\\s|$)|$)")) | not) then empty
                     else guard($p; $at; $rs; $head; $c) end)
                else
                  (if any($rs[]; (.r | test("^findings sent\\b")) and (.r | names($head))) then empty
                   else "findings \($at): tell its builder\($t | bthread)" end) end)
             else
               [$rs[] | select(.r | names($head))] as $here
               | ([$here[] | kind("review started|re-check sent") | select(.closed | not)] | max_by(.id)) as $live
               | if $live != null then
                   # A reviewer at work on this head, and no verdict on it yet: after 30
                   # minutes, tell it again once; 30 minutes after that, it has failed.
                   ($live | thread) as $th
                   | ([$here[] | kind("review told again") | select(thread == $th)] | max_by(.id)) as $told
                   | fleet_of($s) as $f
                   | if $th != null and ($live | inherited($f)) then out_of_reach($at; $th; $f; $live)
                     elif $th == null then look($p.number; $rs; "\"\($live.r)\" names no thread, so its reviewer can'"'"'t be checked")
                     elif $told == null then
                       (if ($live | age) >= 1800 then "check review \($at): no verdict 30 minutes after \"\($live.r)\"; read thread \($th) and tell it again (its record: comment \($live.id))" else empty end)
                     elif ($told | age) >= 1800 then "check review \($at): still no verdict 30 minutes after it was told again; archive thread \($th) and record review given up (its record: comment \($live.id))"
                     else empty end
                 elif any($here[]; .r | test("^review starting\\b")) then
                   ([$here[] | select(.r | test("^review starting\\b"))] | min_by(.id)) as $cl
                   | if ($cl | age) >= 600 then "reconcile review \($at): claimed at \($cl.at), no outcome after 10 minutes" else empty end
                 else
                   [$rs[] | select(.givenUp or (.r | test("^review failed [0-9a-f]{40}, thread "))) | (.thread // failed_thread // "given up")] as $quiet
                   | ([$rs[] | kind("review started") | select(.closed | not) | select(thread | among($quiet) | not)] | max_by(.id)) as $first
                   | ([$here[] | kind("review refused|review failed|review given up")] | max_by(.id)) as $last
                   | (if $last == null then "" else " (retry after \"\($last.r)\")" end) as $retry
                   | fleet_of($s) as $f
                   | if refused_lately($last; "review") then empty
                     elif $first != null and ($first | thread) != null and ($first | inherited($f)) then
                       out_of_reach($at; $first | thread; $f; $first)
                     elif $first != null then "re-check \($at): tell its reviewer, thread \($first | thread)\($retry)"
                     elif ($quiet | length) > 0 then "review \($at): a fresh reviewer\($retry)"
                     else "review \($at): first review\($retry)" end
                 end
             end
         end),
      (if (open_prs | length) > 0 then empty else
         .closedByPullRequestsReferences.nodes[] | select(.state == "CLOSED") | . as $q
         | ([records[] | select(.r | test("^re-test (starting|sent|failed) " + $q.headRefOid + "\\b"))] | max_by(.id)) as $cl
         # Only an unfinished claim ("starting", not yet edited to sent or failed)
         # owns a closure, and only one within 10 minutes of it: the loop
         # closes right after claiming. Any other closure is someone'"'"'s choice.
         | select($cl != null and ($cl.r | test("^re-test starting ")) and ($q.closedAt | type) == "string"
                  and $q.closedAt >= $cl.at and (($q.closedAt | fromdateiso8601) - ($cl.at | fromdateiso8601)) < 600)
         | "reopen #\($q.number) for #\($t.number) at \($q.headRefOid): closed by its re-test (comment \($cl.id)) and not reopened; reopen it" end)
    end;

# A builder from before the fleet thread (ClosedWiz#192): the fleet asks the
# orchestrator to archive it, through a look record; once the orchestrator
# records "old builder archived, thread <id>", the fleet starts its own
# builder on the same branch. Until then, nothing goes to the old builder.
def take_over($s; $f; $rec): records as $rs | ($rec | thread) as $x
  | if $x == null then look(.number; $rs; "\"\($rec.r)\" names no thread, so its builder can'"'"'t be taken over")
    elif any($rs[]; (.r == "old builder archived, thread \($x)" or .r == "old builder archived, start \($rec.id)")) then
      if takeover_ready($s) | not then empty else
      ([$rec.r | capture("branch (?<b>[^ ,;]+)") | .b] + ($W.branches["\(.number)"] // []) | unique) as $br
      | if ($br | length) > 1 then look(.number; $rs; "builder thread \($x) has more than one branch: \($br | join(", "))")
        else "take over #\(.number): builder thread \($x) is archived; start a builder to "
          + (if ($br | length) == 1 then "continue branch \($br[0])" else "build it, as it has no branch yet" end)
          + " (its record: comment \($rec.id))" end end
    else look(.number; $rs; "archive thread \($x): its builder, started before fleet thread \($f.thread)") end;
# A takeover start CloudRoom refused, or that failed, left the ticket with an
# open pull request and no builder: try it again, 10 minutes after a refusal
# and at once after a failure, as any start is.
def take_over_again($s; $st): records as $rs
  | ([$rs[] | select(.r | startswith("old builder archived, thread "))] | max_by(.id) | .r
     | ltrimstr("old builder archived, thread ")) as $x
  | ($W.branches["\(.number)"] // []) as $br
  | if refused_lately($st.last; "start") or (takeover_ready($s) | not) then empty
    elif ($br | length) > 1 then look(.number; $rs; "builder thread \($x) has more than one branch: \($br | join(", "))")
    else "take over #\(.number): builder thread \($x) is archived; start a builder to "
      + (if ($br | length) == 1 then "continue branch \($br[0])" else "build it, as it has no branch yet" end)
      + " (its record: comment \($st.last.id); retry after \"\($st.last.r)\")" end;
def to_builder: test("^(note|resume|reconcile resume|check start|CI failed|findings|merge main in) ");
def ticket_lines($s):
  (if .state == "OPEN" and is_planned($s) and (looks | length) == 0 then
     .blockedBy.nodes[]? | completion_request
   else empty end),
  (fleet_of($s) as $f | start as $st
  | if $f != null and .state == "OPEN" and is_approved($s) and (looks | length) == 0
       and ($st.state == "started" or $st.state == "checked") and ($st.rec | inherited($f))
    then take_over($s; $f; $st.rec), (ticket_lines_now($s) | select(to_builder | not))
    elif .state == "OPEN" and is_approved($s) and (looks | length) == 0 and taking_over($s)
    then take_over_again($s; $st), (ticket_lines_now($s) | select((to_builder or startswith("start #")) | not))
    else ticket_lines_now($s) end);

# A spec'"'"'s approval: a look when it lists no tickets, a re-approve when the
# plan changed since.
def approval_lines: . as $s | records as $srs | latest($s) as $a
  | if $a == null then empty
    elif ($a.rows | length) == 0 then look(.number; $srs; "its latest plan graph approval lists no tickets")
    else
      ($W.fingerprints["\($s.number)"] // null) as $now
      | if $now == null or plan_current($s) then empty
        elif $a.machine and $a.fingerprint == $now then look($s.number; $srs; "its latest machine plan approval'"'"'s revision text is not the plan its fingerprint names")
        else "changed since revision \($a.revision // "?") (fingerprint now \($now[:12]))" as $what
        | if any($s | records[]; .r == "needs approval: \($what)") then empty
          else "re-approve #\($s.number): \($what)" end end
    end;

# R2 (decision 7030919773): with a video, one look, once: its "look: <reason>"
# record settles it. Comments on the video steer nothing.
def steer_lines: .number as $n | records as $srs
  | if video != null then look($n; $srs; "comments on the video steer nothing until the identity separation of OpenWiz #1402 is verified; the owner steers through the orchestrator") else empty end;

def spec_lines: . as $s | records as $srs
  | if .subIssues.pageInfo.hasNextPage then look(.number; $srs; "more than 100 tickets, so its graph can'"'"'t all be read")
    elif .comments.pageInfo.hasPreviousPage then look(.number; $srs; "comment history could not be read in full")
    else
      latest($s) as $a
      | approval_lines, steer_lines,
        ($s.subIssues.nodes[] | ticket_lines($s)),
        (if $a == null or ($a.rows | length) == 0 then empty
         else [$s.subIssues.nodes[] | select(.state == "OPEN" and row($s) == null and (follow_up($s) | not)) | .number] as $pending
           | ($pending[] | look($s.number; $srs; "open sub-issue #\(.) is not in the approved plan")),
             ($s | stall_lines($a)),
             (if planned_done($s) then
                if ($pending | length) > 0 then empty
                elif live_check_waiting($s) then
                  (live_check_missing($s).id) as $since
                  | ($s | plain | sort_by(.databaseId) | .[] | select(.databaseId > $since))
                  | look($s.number; $srs; "live check evidence to verify in comment \(.databaseId)")
                elif spec_rec($s; "^spec summary\\b") | not then
                  ([$s.subIssues.nodes[] | select(.state == "OPEN" and follow_up($s)) | .number] + [$W.followups[] | select(.spec == $s.number) | .number]
                   | unique) as $f
                  | "spec done #\($s.number): every planned ticket is done; "
                    + (if ($f | length) == 0 then "no follow-ups" else "open polish follow-ups: \($f | map("#\(.)") | join(" "))" end)
             elif ([$s.subIssues.nodes[] | select(row($s) != null) | ticket_lines($s) | select(startswith("archive ") or startswith("look "))] | length) == 0
             then "close spec #\($s.number): every planned ticket is done; follow-ups go to polish"
             else empty end
           else empty end)
         end)
    end;

# A spec as a wake reads it for the tickets it names (ClosedWiz#259), part of
# it or all of it: what the check prints for those tickets, with the same
# guards on the spec.
def wakes_for: has("partial") or has("named");
def is_named($s): ($s | has("named") | not) or (.number | among($s.named));
def part_lines: . as $s | records as $srs
  | if .subIssues.pageInfo.hasNextPage or (.total // 0) > 100 then look(.number; $srs; "more than 100 tickets, so its graph can'"'"'t all be read")
    elif .comments.pageInfo.hasPreviousPage then look(.number; $srs; "comment history could not be read in full")
    else approval_lines, steer_lines, (.subIssues.nodes[] | select(is_named($s)) | ticket_lines($s)) end;

def candidates: ($W.specs[] as $s | $s.subIssues.nodes[] | select(is_named($s)) | {t: ., s: $s}),
  ($W.singles[] | {t: ., s: null});
def start_selection: [candidates | .s as $s | .t
    | select(.state == "OPEN" and is_approved($s) and (looks | length) == 0 and unrefused_ready($s))
    | {number, paths: owned_paths} as $c | select($c.paths != null and (running_clash | not)) | $c]
  | unique_by(.number) | reduce .[] as $c ([]; if any(.[]; paths_clash(.paths; $c.paths)) then . else . + [$c] end)
  | map(.number);
# The users who labelled a ticket that could otherwise start, not record
# authors: their write access is read (Writer), once each.
def writers_wanted: [candidates | .s as $s | .t
  | select(.state == "OPEN" and is_approved($s) and (looks | length) == 0 and ready_unchecked($s))
  | approval_label | .actor | select(type == "object" and .__typename == "User") | login_of
  | select(. != null and (among($W.authors) | not))] | unique | .[];
# Only existing, readable builders can be resumed; this never starts one.
def waiters: candidates | .s as $s | .t
  | select(.state == "OPEN" and is_approved($s) and (looks | length) == 0 and builder != null)
  | pending_wait // empty;
def once: reduce .[] as $l ([]; . as $acc | if $l | among($acc) then . else . + [$l] end) | .[];
# A spec with a fleet thread is that thread'"'"'s alone (ClosedWiz#192): only its
# own check, `spec S`, prints its lines.
def check: [($W.specs | sort_by(.number)[] | select(fleet(.) == null) | spec_lines), ($W.singles | sort_by(.number)[] | ticket_lines(null))] | once;
def spec: [$W.specs[] | select(.number == $W.spec) | spec_lines] | once;
# Every spec'"'"'s lines, fleet threads'"'"' too: what a fleet thread reads before it
# merges, so the re-test guard sees approved heads in every spec.
def every: [($W.specs | sort_by(.number)[] | spec_lines), ($W.singles | sort_by(.number)[] | ticket_lines(null))] | once;
# GI2 (#2544): a wake on a spec with a fleet thread runs that thread'"'"'s own
# loop now, once however many of its numbers the messages name, and prints
# none of its lines: its loop'"'"'s check (`spec S`, cached as GI1 made it) does.
# Only a spec whose latest fleet record names a loop no other spec of the
# wake names is routed; any other spec is left as before. (A comment history
# read only in part has no records at all, so it has no fleet record either.)
# The loop id goes on a printed command, so only an id that starts with a
# letter, digit or underscore, never one room-cli would read as a flag, runs.
def fleet_loop($s): fleet($s).loop | if . != null and test("^[A-Za-z0-9_][A-Za-z0-9_-]{0,127}$") then . else null end;
def routed: fleet_loop(.) as $l | $l != null and ([$W.specs[] | select(fleet_loop(.) == $l)] | length) == 1;
def wake: [($W.specs | sort_by(.number)[]
             | if routed then "wake fleet #\(.number): room-cli loop run \(fleet_loop(.))"
               elif fleet(.) != null then empty
               elif wakes_for then part_lines else spec_lines end),
           ($W.singles | sort_by(.number)[] | ticket_lines(null))] | once;
def frontier: [candidates | .s as $s | .t
  | select(.state == "OPEN" and is_approved($s) and (looks | length) == 0 and may_start($s))
  | {number, title}] | unique_by(.number) | .[] | "#\(.number) \(.title)";
def holds: check | select(startswith("note #"));
# The claim rule: a tick that posted a claim goes only if no older claim is
# still live (starting, started, start checked; or for a review, starting,
# started or re-check sent on the same commit), no builder or pull request is
# there, and the item is still due. A claim keeps its item as it is edited on.
def claim: $W.claim.n as $n | $W.claim.id as $id
  | ([candidates | select(.t.number == $n)] | first) as $c
  | if $c != null then
      ([$c.t.comments.nodes[] | select(.databaseId == $id)] | first) as $cm
      | if $cm == null then "error can'"'"'t find comment \($id) on #\($n)"
        elif (($cm.body | rec // "") | test("^release starting [0-9]+(, thread thr_[A-Za-z0-9_-]+)?$")) then
          ($cm.body | rec | capture("^release starting (?<h>[0-9]+)(,|$)").h | tonumber) as $hold
          | $c.s as $s | $c.t | ordering_hold as $h
          | if $h != null and $h.id == $hold and ordering_due($s) and ordering_claim($h) == null
            then "go #\($n)" else "withdraw #\($n): that ordering release is not due or an older claim holds it" end
        elif (($cm.body | rec // "") | test("^resume starting [0-9]+ for #[1-9][0-9]{0,8}(, thread thr_[A-Za-z0-9_-]+)?$")) then
          ($cm.body | rec | capture("^resume starting (?<w>[0-9]+) for #(?<n>[0-9]+)(,|$)")) as $request
          | $c.s as $s | $c.t | pending_wait as $w
          | if .state == "OPEN" and is_approved($s) and (looks | length) == 0
               and ($s == null or ($s.comments.pageInfo.hasPreviousPage == false
                 and $s.subIssues.pageInfo.hasNextPage == false and ($s.total // 0) <= 100))
               and builder != null and $w != null
               and ($w.id | tostring) == $request.w and ($w.number | tostring) == $request.n
               and ($W.waited["\($w.number)"] | merged_ok)
               and $W.waited["\($w.number)"].closedByPullRequestsReferences.pageInfo.hasNextPage == false
               and resume_claim($w) == null
            then "go #\($n)" else "withdraw #\($n): that resume is not due or an older claim holds it" end
        elif ($cm.body | rec) != "starting" then "error comment \($id) on #\($n) is not a \"launch-fleet: starting\" claim"
        else $c.s as $s | $c.t | start as $st
          | if .state != "OPEN" then "withdraw #\($n): it is closed"
            elif (is_approved($s) | not) then "withdraw #\($n): it is not approved"
            elif $st.state != "queued" then "withdraw #\($n): an older claim or builder: \"\($st.rec.r)\""
            elif (open_prs | length) > 0 then "withdraw #\($n): pull request #\(open_prs[0].number) is open"
            elif (looks | length) > 0 then "withdraw #\($n): \(looks[0])"
            elif refused_lately($st.last; "start") then "withdraw #\($n): its start was refused less than 10 minutes ago"
            elif ready_unchecked($s) and approver_why != null then "withdraw #\($n): \(approver_why)"
            elif ready($s) then
              # F6 (#1353): the gate every builder start passes. $W.active is
              # every open ready ticket of the repository; a clash with one
              # running, or claimed by an older claim, withdraws this one.
              owned_paths as $mine
              | ([scope_tickets[] | select(.number != $n and .state == "OPEN" and paths_clash($mine; owned_paths))
                  | select((open_prs | length) > 0 or (start | .state != "queued" and (.state != "claimed" or .rec.id < $id)))
                  | .number] | unique | first) as $m
              | if $mine == null then "withdraw #\($n): its owned paths can'"'"'t be read as the plan approval reads them"
                elif $m != null then "withdraw #\($n): its owned paths collide with #\($m), which is running or claimed first"
                else "go #\($n)" end
            else "withdraw #\($n): it is not on the frontier now" end end
    else
      ([candidates | .s as $s | .t | select(.state == "OPEN" and is_approved($s)) | . as $t
        | .closedByPullRequestsReferences.nodes[] | select(.number == $n and .state == "OPEN") | {p: ., t: $t, s: $s}] | first) as $x
      | if $x == null then "error #\($n) is neither a ticket nor an open pull request of an approved ticket"
        else ([$x.p.comments.nodes[] | select(.databaseId == $id)] | first) as $cm
          | if $cm == null then "error can'"'"'t find comment \($id) on #\($n)"
            elif (($cm.body | rec // "") | test("^review starting [0-9a-f]{40}$") | not) then
              "error comment \($id) on #\($n) is not a \"launch-fleet: review starting <commit>\" claim"
            else ($cm.body | rec | capture("(?<c>[0-9a-f]{40})").c) as $sha
              | if $x.p.headRefOid != $sha then "withdraw #\($n): the head is now \($x.p.headRefOid)"
                else ([$x.p | records[] | select((.r | test("^(review starting|review started|re-check sent)\\b")) and (.r | names($sha)))]
                      | min_by(.id)) as $older
                  | if $older != null then "withdraw #\($n): an older review claim: \"\($older.r)\""
                    elif any($x.t | ticket_lines($x.s); startswith("review #\($n) for #\($x.t.number) at \($sha)")
                                                        or startswith("re-check #\($n) for #\($x.t.number) at \($sha)"))
                    then "go #\($n)"
                    else "withdraw #\($n): it is not due a review at \($sha)" end end end end end;
'

# jqw [-j] PROGRAM: run PROGRAM on the world, with the shared rules; -j
# prints raw text with no newline added.
jqw() {
  flag=-r
  if [ "$1" = -j ]; then flag=-j; shift; fi
  since=''
  if [ "$1" = --arg ]; then since=$3; shift 3; fi
  jq -n "$flag" --arg since "$since" --slurpfile w "$TMP/world.json" "\$w[0] as \$W | $LIB $1"
}

# world CHECKS LABELS SINGLES: what was read, as one JSON file.
world() {
  jq -n --argjson now "$NOW" --arg default "$DEFAULT" --arg repo "$REPO" --slurpfile specs "$TMP/specs.json" \
    --slurpfile checks "$1" --slurpfile labels "$2" --slurpfile singles "$3" --arg claim "${CLAIM_N:+$CLAIM_N $CLAIM_ID}" \
    --slurpfile followups "$TMP/followups.json" --arg spec "${SPEC:-}" --slurpfile authors "$TMP/authors.json" \
    '{now: $now, default: $default, repo: ($repo | ascii_downcase), specs: $specs[0], singles: $singles[0], checks: $checks[0], labels: $labels[0],
      followups: $followups[0], authors: $authors[0], writers: [], spec: (if $spec == "" then null else ($spec | tonumber) end),
      claim: (if $claim == "" then null else ($claim | split(" ") | {n: (.[0] | tonumber), id: (.[1] | tonumber)}) end),
      fingerprints: {}, branches: {}, merged: [], prfiles: {}, active: [], links: {}, selected: null}' > "$TMP/world.json" || die "can't build the world"
}

# writers: KN13 (#1448). The write access of each user writers_wanted names,
# into the world's writers: one small GraphQL read each, only for a ticket
# that could otherwise start and that no record author labelled. A read that
# fails or answers anything else grants nothing: that ticket is refused.
writers() {
  printf '[]' > "$TMP/writers.json" && jqw 'writers_wanted' > "$TMP/writers-wanted.txt" \
    || die "can't list who labelled the tickets"
  while IFS= read -r login; do
    case $login in '' | -* | *[!a-z0-9-]*) continue ;; esac
    if ( gql Writer "$TMP/writer.json" -f login="$login" ) 2> /dev/null \
      && jq -e --arg l "$login" 'any(.data.repository.collaborators.edges[]?; (.node.login | ascii_downcase) == $l
           and (.permission | IN("ADMIN", "MAINTAIN", "WRITE")))' "$TMP/writer.json" > /dev/null 2>&1; then
      jq --arg l "$login" '. + [$l]' "$TMP/writers.json" > "$TMP/writers.next" && mv "$TMP/writers.next" "$TMP/writers.json" \
        || die "can't write"
    fi
  done < "$TMP/writers-wanted.txt"
  jq --slurpfile w "$TMP/writers.json" '.writers = $w[0]' "$TMP/world.json" > "$TMP/world.next" \
    && mv "$TMP/world.next" "$TMP/world.json" || die "can't write"
}

# unticked_hash FILE: FILE's SHA-256 as to-tickets’ revision.sh hashes a body:
# each ticked task box read as unticked, bytes not characters.
TAB=$(printf '\t') CR=$(printf '\r')
unticked_hash() {
  LC_ALL=C sed -E -e "s/^([ $TAB]*[-*+][ $TAB]+)\[[xX]\]$/\1[ ]/" \
    -e "s/^([ $TAB]*[-*+][ $TAB]+)\[[xX]\]([ $TAB$CR])/\1[ ]\2/" "$1" | hash
}

# revision_text SPEC: the revision text to-tickets’ revision.sh prints for
# SPEC, made from what this check read, the same read as its fingerprint key.
# A fingerprint is kept only when revision.sh printed exactly this, so a plan
# edited between the two reads is never cached under the wrong key (Sol R2 on
# #248). Any difference only costs a revision.sh run on the next check.
revision_text() {
  jq -r --argjson s "$1" '[.[] | select(.number == $s)] | first | .body // ""' "$TMP/specs.json" > "$TMP/rt-body" || return 1
  rt_h=$(unticked_hash "$TMP/rt-body") && [ ${#rt_h} = 64 ] || return 1
  printf 'plan-graph revision v2\nspec #%s body sha256 %s\n' "$1" "$rt_h"
  jq -r --argjson s "$1" '[.[] | select(.number == $s)] | first | [.subIssues.nodes[].number] | sort[]' "$TMP/specs.json" \
    > "$TMP/rt-tickets" || return 1
  while read -r rt_n; do
    jq -r --argjson s "$1" --argjson n "$rt_n" '[.[] | select(.number == $s)] | first | .subIssues.nodes[] | select(.number == $n)
      | .body // ""' "$TMP/specs.json" > "$TMP/rt-body" || return 1
    jq -r --argjson s "$1" --argjson n "$rt_n" '[.[] | select(.number == $s)] | first | .subIssues.nodes[] | select(.number == $n)
      | "#\(.number)\t\([.blockedBy.nodes[].number] | sort | map("#" + tostring) | join(" ") | if . == "" then "none" else . end)\t\(.title)"' \
      "$TMP/specs.json" > "$TMP/rt-meta" || return 1
    rt_h=$(unticked_hash "$TMP/rt-body") && [ ${#rt_h} = 64 ] || return 1
    IFS=$TAB read -r rt_number rt_blockers rt_title < "$TMP/rt-meta" || return 1
    printf 'ticket %s blocked-by %s body sha256 %s title %s\n' "$rt_number" "$rt_blockers" "$rt_h" "$rt_title"
  done < "$TMP/rt-tickets"
}

# fingerprint_key SPEC: everything revision.sh reads for SPEC, as this check
# read it (the spec's body, and each ticket's number, title, body and
# blockers), with the spec's updatedAt, this script and revision.sh's own
# text; nothing when the check could not read all of it.
fingerprint_key() {
  { printf 'launch-fleet fingerprint v1 %s %s\n' "$SELF" "$REVISION_SELF"
    jq -ce --argjson s "$1" '[.[] | select(.number == $s)] | first
      | select(.subIssues.pageInfo.hasNextPage == false and all(.subIssues.nodes[]; .blockedBy.pageInfo.hasNextPage == false))
      | {number, updatedAt, body, tickets: ([.subIssues.nodes[]
          | {number, title, body, blockers: ([.blockedBy.nodes[].number] | sort)}] | sort_by(.number))}' "$TMP/specs.json"
  } > "$TMP/key-$1.txt" || return 1
  hash < "$TMP/key-$1.txt"
}

# Each spec with a ticket that could start: its plan as it is now, from
# to-tickets’ revision.sh, and that text's SHA-256; or the fingerprint
# cached for the same key, when nothing revision.sh reads has changed. Only a
# fingerprint whose revision text is the plan this check read is cached. A
# read that fails stops the check: nothing starts on a guess.
fingerprints() {
  jqw 'to_check' > "$TMP/to-check.txt" || die "can't list the specs to check"
  printf '{' > "$TMP/fingerprints.json" || die "can't write"
  sep=''
  for s in $(sort -n -u "$TMP/to-check.txt"); do
    [ -f "$REVISION" ] || die "can't find to-tickets’ revision.sh at $REVISION, so no approval can be checked"
    REVISION_SELF=$(hash < "$REVISION") && [ ${#REVISION_SELF} = 64 ] || die "can't hash to-tickets’ revision.sh"
    k='' f='' agreed=false
    [ -z "$CACHE" ] || k=$(fingerprint_key "$s") || k=''
    if [ ${#k} = 64 ]; then
      c=$(cached "spec-$s.fingerprint")
      [ "${c%% *}" = "$k" ] && f=${c#* }
    fi
    case $f in *[!0-9a-f]*) f='' ;; esac
    [ ${#f} != 64 ] || agreed=true
    if [ ${#f} != 64 ]; then
      [ -z "$REPLAY" ] || die "the saved full read has no fingerprint for #$s"
      LAUNCH_FLEET_ASKED=$TMP/asked-revision sh "$REVISION" "$s" > "$TMP/revision-$s.txt" \
        || die "to-tickets’ revision.sh failed on #$s, so its approval can't be checked"
      f=$(hash < "$TMP/revision-$s.txt") || die "can't hash the revision of #$s"
      case $f in *[!0-9a-f]* | '') die "can't hash the revision of #$s" ;; esac
      [ ${#f} = 64 ] || die "can't hash the revision of #$s"
      if revision_text "$s" > "$TMP/derived-$s.txt" && cmp -s "$TMP/derived-$s.txt" "$TMP/revision-$s.txt"; then
        agreed=true
        [ ${#k} != 64 ] || keep "spec-$s.fingerprint" "$k $f"
      fi
    fi
    # #1340 R4: a machine approval'"'"'s own revision text, hashed, so its table
    # and text are bound to the plan its fingerprint names.
    t=''
    if jqw -j "[\$W.specs[] | select(.number == $s)] | first | latest(.) | select(.machine) | .text" > "$TMP/machine-$s.txt"; then
      [ ! -s "$TMP/machine-$s.txt" ] || t=$(hash < "$TMP/machine-$s.txt") || die "can't hash the machine approval of #$s"
    else die "can't read the machine approval of #$s"; fi
    case $t in *[!0-9a-f]*) t='' ;; esac
    printf '%s"%s":{"hash":"%s","agreed":%s,"text":"%s"}' "$sep" "$s" "$f" "$agreed" "$t" >> "$TMP/fingerprints.json" || die "can't write"
    sep=','
  done
  printf '}' >> "$TMP/fingerprints.json" || die "can't write"
  jq --slurpfile f "$TMP/fingerprints.json" '.fingerprints = ($f[0] | with_entries(.value = .value.hash))
    | .fingerprint_agreement = ($f[0] | with_entries(.value = .value.agreed))
    | .machine_text = ($f[0] | with_entries(.value = .value.text))' "$TMP/world.json" > "$TMP/w2.json" \
    && mv "$TMP/w2.json" "$TMP/world.json" || die "can't record the fingerprints"
}

# Nightly CI (#257): only check reads it, after the allowance gate. Ask for
# the latest completed scheduled CI run on the default branch: newer queued
# work is not a successful nightly. REST reads count as questions, not GraphQL
# points. Delivery records live on the run's commit, keyed by run and attempt,
# not in a local cache or on an arbitrarily chosen spec.
nightly() {
  branch=$(jq -rn --arg b "$DEFAULT" '$b | @uri') || die "can't encode the default branch"
  # The transport status distinguishes an absent workflow from other errors;
  # a JSON message or status field must never turn a failed read into quiet.
  if http_get "repos/$REPO/actions/workflows/ci.yml/runs?event=schedule&branch=$branch&status=completed&per_page=1" \
    "$TMP/nightly.http" 2> "$TMP/nightly.err"; then nightly_ok=yes; else nightly_ok=no; fi
  nightly_status=$(awk 'NR == 1 { sub(/\r$/, "");
    if ($1 ~ /^HTTP\/[0-9]+([.][0-9]+)?$/ && $2 ~ /^[0-9][0-9][0-9]$/) print $2; exit }' "$TMP/nightly.http") \
    || die "can't read nightly CI HTTP status"
  [ "$nightly_status" != 404 ] || return 0
  if [ "$nightly_ok" != yes ] || [ "$nightly_status" != 200 ]; then
    cat "$TMP/nightly.err" >&2
    die "can't read nightly CI runs"
  fi
  awk 'body { print } /^\r?$/ { body=1 }' "$TMP/nightly.http" > "$TMP/nightly.raw" \
    || die "can't read nightly CI response body"
  jq -se --arg d "$DEFAULT" '
    def natural: type == "number" and . >= 0 and . == floor;
    def positive: natural and . > 0;
    if length != 1 then error("not one response") else .[0] end
    | select(type == "object" and (.total_count | natural) and (.workflow_runs | type) == "array")
    | select(if .total_count == 0 then .workflow_runs == [] else (.workflow_runs | length) == 1 end)
    | .workflow_runs
    | if length == 0 then {} else .[0]
      | select(type == "object" and (.id | positive) and (.run_attempt | positive)
        and (.head_sha | type) == "string" and (.head_sha | test("^[0-9a-f]{40}$"))
        and .head_branch == $d and .event == "schedule" and .status == "completed"
        and (.path == ".github/workflows/ci.yml" or .path == ".github/workflows/ci.yml@" + $d)
        and (.conclusion | IN("success", "failure", "cancelled", "timed_out", "action_required",
          "neutral", "skipped", "stale", "startup_failure"))) end' \
    "$TMP/nightly.raw" > "$TMP/nightly.json" || die "invalid nightly CI runs"
  conclusion=$(jq -er '.conclusion // "success"' "$TMP/nightly.json") || die "invalid nightly CI runs"
  case $conclusion in
    failure | timed_out | startup_failure | action_required) ;;
    *) return 0 ;; # Known non-red conclusions were validated above.
  esac
  sha=$(jq -r .head_sha "$TMP/nightly.json") || die "invalid nightly CI runs"
  rest_pages "repos/$REPO/commits/$sha/comments?per_page=100" "$TMP/nightly-comments.raw" || die "can't read nightly CI notification records"
  jq -se --arg s "$sha" --slurpfile a "$TMP/authors.json" "$AUTHORED"'
    select(length > 0 and all(.[]; type == "array")) | add
    | select(all(.[]; type == "object" and (.id | type) == "number" and .id > 0 and .id == (.id | floor)
        and .commit_id == $s and (.body | type) == "string"))
    | authored($a[0])' \
    "$TMP/nightly-comments.raw" > "$TMP/nightly-comments.json" || die "invalid nightly CI notification records"
  jq -nr --arg repo "$REPO" --argjson private "$private" --slurpfile run "$TMP/nightly.json" --slurpfile comments "$TMP/nightly-comments.json" '
    $run[0] as $r | "\($r.id) attempt \($r.run_attempt)" as $key
    | $comments[0] as $cs
    | if any($cs[]; .body == "launch-fleet: nightly told " + $key
        or .body == "launch-fleet: nightly uncertain " + $key) then empty
      else "nightly red \($key) at \($r.head_sha): https://github.com/\($repo)/actions/runs/\($r.id) (\($r.conclusion))" as $line
        | ([$cs[] | select($private or (.body | test("\\bthr_[A-Za-z0-9]") | not)) | select(.body | test("^launch-fleet: nightly telling " + $key + "(, thread thr_[A-Za-z0-9_-]+)?$"))
            | . + {thread: (.body | ltrimstr("launch-fleet: nightly telling " + $key + ", thread "))}
            | .thread = (if (.thread | test("^thr_[A-Za-z0-9_-]+$")) then .thread else null end)] | min_by(.id)) as $claim
        | $line + (if $claim == null then "" else "; reconcile comment \($claim.id)" + (if $claim.thread then ", thread \($claim.thread)" else "; sender in private state" end) end)
      end' > "$TMP/nightly-out.txt" || die "can't work out the nightly CI alert"
}

# A waiting builder may name a ticket outside its native blockedBy edges
# or its spec. Read each referenced issue once; a closed issue alone is not
# a verified merge. Missing issues and PR numbers cannot resume a builder.
waits() {
  jqw '[(waiters | .number), (candidates | .s as $s | .t | select(ordering_candidate($s))
    | ordering_hold | select(.kind == "issue") | .number)] | unique[]' > "$TMP/waiting.txt" || die "can't read the waits"
  printf '{}' > "$TMP/waited.json" || die "can't write"
  while read -r n; do
    gql Item "$TMP/wait.json" -F number="$n" -F size=2
    jq -e --arg d "$DEFAULT" --argjson n "$n" '
      .data.repository | select(.defaultBranchRef.name == $d) | .issueOrPullRequest
      | if . == null then true
        elif .__typename == "PullRequest" then true
        elif .__typename == "Issue" then
          .number == $n and (.state | IN("OPEN", "CLOSED"))
          and (.closedByPullRequestsReferences.pageInfo.hasNextPage | type) == "boolean"
          and (.closedByPullRequestsReferences.nodes | type) == "array"
          and all(.closedByPullRequestsReferences.nodes[];
            (.merged | type) == "boolean" and (.baseRefName | type) == "string")
        else false end' "$TMP/wait.json" > /dev/null || die "can't verify the merge of #$n"
    jq --argjson n "$n" --slurpfile answer "$TMP/wait.json" '
      .["\($n)"] = ($answer[0].data.repository.issueOrPullRequest
        | if .__typename == "Issue" then . else null end)' \
      "$TMP/waited.json" > "$TMP/waited2.json" && mv "$TMP/waited2.json" "$TMP/waited.json" \
      || die "can't record the waits"
  done < "$TMP/waiting.txt"
  # PR prerequisites are read directly: an Issue closing relationship cannot
  # stand in for a different PR, and REST merged/base facts are sufficient here.
  jqw '[candidates | .s as $s | .t | select(ordering_candidate($s))
    | ordering_hold | select(.kind == "PR") | .number] | unique[]' > "$TMP/ordering-prs.txt" \
    || die "can't read the ordering prerequisites"
  while read -r n; do
    rest "repos/$REPO/pulls/$n" "$TMP/ordering-pr.json" || die "can't read ordering PR #$n"
    jq -e --argjson n "$n" 'type == "object" and .number == $n
      and (.state | IN("open", "closed"))' "$TMP/ordering-pr.json" > /dev/null \
      || die "can't verify ordering PR #$n"
    jq --arg n "PR:$n" --slurpfile p "$TMP/ordering-pr.json" '.[$n] = $p[0]' \
      "$TMP/waited.json" > "$TMP/waited2.json" && mv "$TMP/waited2.json" "$TMP/waited.json" \
      || die "can't record the ordering prerequisites"
  done < "$TMP/ordering-prs.txt"
  jq --slurpfile w "$TMP/waited.json" '.waited = $w[0]' "$TMP/world.json" > "$TMP/w2.json" \
    && mv "$TMP/w2.json" "$TMP/world.json" || die "can't record the waits"
}

# The branches of each started builder that is not checked yet, and of each
# ticket whose takeover start must be tried again (ClosedWiz#192).
branches() {
  jqw 'candidates | .s as $s | .t
    | select(.state == "OPEN" and is_approved($s) and (looks | length) == 0 and (start.state == "started" or taking_over($s)))
    | .number' > "$TMP/started.txt" || die "can't read the starts"
  printf '{' > "$TMP/branches.json"
  sep=''
  for n in $(sort -n -u "$TMP/started.txt"); do
    rest "repos/$REPO/git/matching-refs/heads/room/$n-" "$TMP/refs-$n.json" || die "can't read the branches of #$n"
    names=$(jq -ce 'if type == "array" then [.[].ref | ltrimstr("refs/heads/")] else error("not a list") end' "$TMP/refs-$n.json") \
      || die "can't read the branches of #$n"
    printf '%s"%s":%s' "$sep" "$n" "$names" >> "$TMP/branches.json" || die "can't write"
    sep=','
  done
  printf '}' >> "$TMP/branches.json"
  jq --slurpfile b "$TMP/branches.json" '.branches = $b[0]' "$TMP/world.json" > "$TMP/w2.json" && mv "$TMP/w2.json" "$TMP/world.json" \
    || die "can't record the branches"
}

# merges [SINCE]: the merges since the oldest approval of a ticket that relies
# on a contract, or since SINCE if that is older (the re-test guard), with the
# files each one changed.
merges() {
  cutoff=$(jqw --arg since "${1:-}" '[(candidates | .s as $s | .t
      | select(.state == "OPEN" and is_planned($s) and (relies | length) > 0) | cutoff($s)), $since]
      | map(select(. != null and . != "")) | min // ""') \
    || die "can't read the contracts"
  [ -n "$cutoff" ] || return 0
  # The guard's second read is needed only for an older window.
  [ "$cutoff" != "${MERGES_SINCE:-}" ] || return 0
  MERGES_SINCE=$cutoff
  : > "$TMP/merged.txt"
  cursor='' pages=0
  while :; do
    pages=$((pages + 1))
    [ $pages -le 20 ] || die "more than 1000 merges since $cutoff: too many to check for contract changes"
    if [ -z "$cursor" ]; then gql Merged "$TMP/page.json"; else gql Merged "$TMP/page.json" -f cursor="$cursor"; fi
    jq -c --arg c "$cutoff" --arg d "$DEFAULT" '.data.repository.pullRequests.nodes[]
      | select(.mergedAt != null and .mergedAt >= $c and .baseRefName == $d)
      | {number, mergedAt, commit: .mergeCommit.oid, closes: [.closingIssuesReferences.nodes[].number]}' "$TMP/page.json" >> "$TMP/merged.txt" \
      || die "can't read the merges"
    more=$(jq -r --arg c "$cutoff" '.data.repository.pullRequests
      | if .pageInfo.hasNextPage and ([.nodes[].updatedAt] | min // "") >= $c then "yes" else "no" end' "$TMP/page.json") \
      || die "can't read the merges"
    [ "$more" = yes ] || break
    cursor=$(jq -er '.data.repository.pullRequests.pageInfo.endCursor' "$TMP/page.json") || die "can't read the merges"
  done
  cache=${CACHE:-$TMP}
  printf '[' > "$TMP/merged.json"
  sep=''
  while read -r line; do
    n=$(printf '%s' "$line" | jq -er .number) || die "can't read the merges"
    f=$cache/pull-$n-files.json
    # A cached list is used only if it passes today'"'"'s FILES rules (K9 R4):
    # one cached under older rules is read again, never trusted.
    if ! jq -se "$FILES | type == \"array\"" "$f" > /dev/null 2>&1; then
      rest_pages "repos/$REPO/pulls/$n/files?per_page=100" "$TMP/files-$n.raw" || die "can't read the files of #$n"
      jq -s "$FILES" "$TMP/files-$n.raw" > "$TMP/files-$n.json" || die "can't read the files of #$n"
      cp "$TMP/files-$n.json" "$f.$$" 2> /dev/null && mv "$f.$$" "$f" 2> /dev/null || f=$TMP/files-$n.json
    fi
    printf '%s' "$sep" >> "$TMP/merged.json" && jq -c --slurpfile files "$f" '. + {files: $files[0]}' << EOF >> "$TMP/merged.json" || die "can't read the files of #$n"
$line
EOF
    sep=','
  done < "$TMP/merged.txt"
  printf ']' >> "$TMP/merged.json"
  jq --slurpfile m "$TMP/merged.json" '.merged = $m[0]' "$TMP/world.json" > "$TMP/w2.json" && mv "$TMP/w2.json" "$TMP/world.json" \
    || die "can't record the merges"
}

# guard: for each "guard #P <time>" line (the re-test guard, K9), the files
# pull request P changes, into the world, and the merges since the oldest
# <time>. An open pull request'"'"'s files can change, so they are never cached.
guard() {
  printf '{' > "$TMP/prfiles.json" || die "can't write"
  sep=''
  while read -r _ n _; do
    n=${n#\#}
    is_number "$n" || die "can't read the re-test guard's line for #$n"
    rest_pages "repos/$REPO/pulls/$n/files?per_page=100" "$TMP/prfiles-$n.raw" || die "can't read the files of #$n"
    files=$(jq -cs "$FILES" "$TMP/prfiles-$n.raw") || die "can't read the files of #$n"
    printf '%s"%s":%s' "$sep" "$n" "$files" >> "$TMP/prfiles.json" || die "can't write"
    sep=','
  done << EOF
$(grep '^guard #' "$TMP/out.txt" | sort -u)
EOF
  printf '}' >> "$TMP/prfiles.json" || die "can't write"
  jq --slurpfile f "$TMP/prfiles.json" '.prfiles = $f[0]' "$TMP/world.json" > "$TMP/w2.json" && mv "$TMP/w2.json" "$TMP/world.json" \
    || die "can't record the files of the pull requests to merge"
  # The oldest run, less one second, so a merge in the same second is read too.
  since=$(grep '^guard #' "$TMP/out.txt" | jq -Rnr '[inputs | split(" ")[2]] | min | fromdateiso8601 - 1 | todate') \
    || die "can't read the times their CI ran"
  merges "$since"
}

# ---- The unchanged probe (GI1, #2543) ----
#
# GraphQL has no conditional reads, so a fleet thread's check (`spec S`) asks
# REST first, with the ETags it saved, whether anything its last full read
# read can have changed; GitHub does not count a 304 against the allowance.
# Its full read keeps every GraphQL answer, by its whole request, in one
# hash-checked entry, unchanged-spec-S.json, beside the REST answers; and with
# it the probe: the REST reads that change whenever one of those answers would
# (the repository, the account, the spec's sub-issues, each ticket's and each
# closed blocker's timeline, each linked pull request and the checks and
# statuses on its head, the waited issues, and the default branch when merges
# were read), each with the ETags it had before that full read's first
# GraphQL read. When every probe page answers 304 with those ETags and that
# full read is under 30 minutes old, a second process replays the check:
# every GraphQL answer from the entry, every REST read revalidated (the
# spec's own issues, comments, blockers and branches, which must all answer
# 304), and the clock and CloudRoom's records as they are now, so lines that
# come due with time still do. Anything else is a full read, as before: a
# changed answer, a probe that fails, a lost, damaged or unreadable entry, an
# entry for another spec, repository, host or script, a probe that was not
# read before that full read's GraphQL, or a full read 30 minutes old. The
# entry holds GitHub's answers and ETags, never a token; nothing in it is
# printed. A full read that follows a replaced probe keeps the new ETags, so
# the next check can replay it.
UNCHANGED_SCHEMA='launch-fleet unchanged v1'
# The probe of who reads (GI7, #2549): the account (`user`), or with an App
# installation token (LAUNCH_FLEET_GITHUB_AUTH=installation, which loop.sh
# sets), what that installation covers, since such a token can't read `user`.
# A switch between them changes the probe, so the saved read is not replayed.
case ${LAUNCH_FLEET_GITHUB_AUTH:-} in
  installation) IDENTITY_PROBE='installation/repositories?per_page=100' ;;
  *) IDENTITY_PROBE=user ;;
esac
unchanged_entry() { printf '%s/unchanged-spec-%s.json\n' "$CACHE" "$SPEC"; }

# probe ENDPOINT ETAGS: one probe's every page, conditionally. It records
# each page's ETag and requires all-304 pages and the saved ETAGS array to match.
probe() (
  endpoint=$1
  key=$(printf '%s' "$endpoint" | hash) && [ ${#key} = 64 ] || exit 0
  out=$TMP/probe/$key
  printf '%s\n' "$endpoint" > "$out.endpoint" && : > "$out.etags" || exit 0
  page=0 same=yes
  while [ -n "$endpoint" ]; do
    page=$((page + 1))
    [ "$page" -le 50 ] || exit 0
    http_get "$endpoint" "$out.http" 2> /dev/null || exit 0
    [ "$(http_status "$out.http")" = 200 ] || exit 0
    [ -f "$out.http.304" ] || same=no
    tag=$(http_etag "$out.http")
    printf '%s\n' "$tag" | LC_ALL=C grep -qE '^(W/)?"[!#-~]{1,250}"$' || exit 0
    printf '%s\n' "$tag" >> "$out.etags" || exit 0
    endpoint=$(next_page "$out.http") || exit 0
  done
  # Retain the current tags even on a mismatch, for the next full read's
  # snapshot. Only a matching array and all-304 pages earn the same marker.
  jq -Rn --argjson expected "$2" '[inputs] | .,
    (if . == $expected then empty else error("changed probe") end)' \
    < "$out.etags" > "$out.read" 2> /dev/null || exit 0
  [ "$same" = no ] || : > "$out.same"
)

# unchanged: before any GraphQL read, the probe of the last full read; then,
# when it shows nothing changed, the replay, which prints the check and ends
# it. Otherwise the full read goes on, keeping its answers ($RECORD).
unchanged() {
  [ -n "$CACHE" ] || return 0
  mkdir "$TMP/record" "$TMP/probe" "$TMP/snap" || return 0
  RECORD=$TMP/record
  entry=$(unchanged_entry)
  [ -f "$entry" ] && [ ! -L "$entry" ] && cp "$entry" "$TMP/snap/entry" 2> /dev/null || return 0
  jq --stream -serj '[.[] | select(length == 2)] as $fields
    | select(([.[] | select(length == 1)] | length) == 1
      and ($fields | length) == 2 and all($fields[]; (.[0] | length) == 1)
      and ([$fields[][0][0]] | sort) == ["body", "sha256"])
    | $fields | map({key: .[0][0], value: .[1]}) | from_entries
    | select((.body | type == "string") and (.sha256 | type == "string" and test("^[0-9a-f]{64}$")))
    | .sha256, "\n", .body' "$TMP/snap/entry" > "$TMP/snap/checked" 2> /dev/null || return 0
  { IFS= read -r digest && cat > "$TMP/snap/body"; } < "$TMP/snap/checked" || return 0
  [ "$(hash < "$TMP/snap/body")" = "$digest" ] || return 0
  jq -e --arg schema "$UNCHANGED_SCHEMA" --arg self "$SELF" --arg host "${GH_HOST:-github.com}" \
    --arg repo "$REPO" --argjson spec "$SPEC" '
    def tag: type == "string" and test("^(W/)?\"[!#-~]{1,250}\"$");
    type == "object" and (keys == ["default", "graphql", "host", "private", "probes", "read_at",
      "replayable", "repo", "repo_id", "schema", "self", "spec"])
    and .schema == $schema and .self == $self and .host == $host and .repo == $repo and .spec == $spec
    and (.read_at | type == "number" and . >= 0 and . == floor) and (.replayable | type == "boolean")
    and (.private | type == "boolean") and (.default | type == "string" and length > 0)
    and (.repo_id | type == "number" and . > 0 and . == floor)
    and (.graphql | type == "object" and all(keys[]; test("^[0-9a-f]{64}$")) and all(.[]; type == "object"))
    and (.probes | type == "array" and length > 0 and all(.[]; type == "object" and keys == ["endpoint", "etags"]
      and (.endpoint | type == "string" and test("^[!-~]+$"))
      and (.etags | type == "array" and length > 0 and all(.[]; tag)))
      and (map(.endpoint) | unique | length) == length)' "$TMP/snap/body" > /dev/null 2>&1 || return 0
  # Read by this identity: its probe is among the saved ones (GI7).
  jq -e --arg i "$IDENTITY_PROBE" 'any(.probes[]; .endpoint == $i)' "$TMP/snap/body" > /dev/null 2>&1 || return 0
  jq -r '.graphql | to_entries[] | "\(.key) \(.value | tojson)"' "$TMP/snap/body" > "$TMP/snap/answers" \
    && while read -r key answer; do printf '%s\n' "$answer" > "$TMP/snap/gql-$key.json" || return 0; done < "$TMP/snap/answers" \
    && jq -r '.private' "$TMP/snap/body" > "$TMP/snap/private" \
    && jq -r '.probes[] | "\(.endpoint) \(.etags | tojson)"' "$TMP/snap/body" > "$TMP/snap/probes" || return 0
  saved_id=$(jq -r '.repo_id' "$TMP/snap/body") && read_at=$(jq -r '.read_at' "$TMP/snap/body") \
    && replayable=$(jq -r '.replayable' "$TMP/snap/body") || return 0
  # Pages past the first are named by the repository's id.
  REPO_ID=$saved_id
  # Prime every saved endpoint even when this snapshot changed or expired:
  # the full read can then retain a snapshot for the next unchanged tick.
  parallel_reads probe "$TMP/snap/probes" || return 0
  [ "$replayable" = true ] && [ "$NOW" -ge "$read_at" ] && [ $((NOW - read_at)) -lt 1800 ] || return 0
  jq -r '.probes[].endpoint' "$TMP/snap/body" > "$TMP/snap/expected" || return 0
  while IFS= read -r endpoint; do
    key=$(printf '%s' "$endpoint" | hash) || return 0
    [ -f "$TMP/probe/$key.same" ] || return 0
  done < "$TMP/snap/expected"
  if LAUNCH_FLEET_REPLAY=$TMP sh "$0" spec "$SPEC" > "$TMP/replay.out" 2> /dev/null; then
    cat "$TMP/replay.out"
    points
    exit 0
  fi
}

# keep_read: after a full `spec S`, its GraphQL answers and the probe that
# would show them changed, as the unchanged entry; replayable only if every
# probe page was read before this read's first GraphQL read. A full read that
# can't be kept is only not reused.
keep_read() {
  keep_out=$TMP/keep-read
  mkdir "$keep_out" || return 0
  set -- "$RECORD"/gql-*
  [ -f "$1" ] || return 0
  jq -n '[inputs | {k: (input_filename | capture("/gql-(?<k>[0-9a-f]{64})[.][^/]*$").k), v: .}]
    | group_by(.k) | map(if (map(.v) | unique | length) == 1 then {key: .[0].k, value: .[0].v}
      else error("two answers to one request") end) | from_entries' "$@" > "$keep_out/graphql.json" 2> /dev/null || return 0
  merged=false
  for f in "$@"; do jq -e '.data.repository.pullRequests' "$f" > /dev/null 2>&1 && merged=true && break; done
  jq -r --arg r "$REPO" --arg d "$DEFAULT" --arg identity "$IDENTITY_PROBE" --argjson merged "$merged" '
    def prs: .closedByPullRequestsReferences.nodes[]?;
    def pr_probes: "repos/\($r)/pulls/\(.number)",
      # CI on a merged PR never selects a due line. Its metadata remains a
      # probe, and every non-merged PR keeps both head-status probes.
      (select(.state != "MERGED") | .headRefOid // empty
        | "repos/\($r)/commits/\(.)/check-runs?per_page=100", "repos/\($r)/commits/\(.)/status");
    def timeline: "repos/\($r)/issues/\(.number)/timeline?per_page=100";
    ["repos/\($r)", $identity,
     (.specs[] | "repos/\($r)/issues/\(.number)/sub_issues?per_page=100",
       (.subIssues.nodes[] | timeline, (prs | pr_probes),
         (.blockedBy.nodes[]? | select(.state == "CLOSED") | timeline,
           "repos/\(.repository.nameWithOwner // $r)/issues/\(.number)",
           (prs | "repos/\($r)/pulls/\(.number)")))),
     (.waited // {} | to_entries[] | if (.key | startswith("PR:")) then "repos/\($r)/pulls/\(.key[3:])"
       else "repos/\($r)/issues/\(.key)", "repos/\($r)/issues/\(.key)/timeline?per_page=100",
         (.value // {} | prs | "repos/\($r)/pulls/\(.number)") end),
     (if $merged then "repos/\($r)/git/ref/heads/\($d | @uri)" else empty end)]
    | unique[]' "$TMP/world.json" > "$keep_out/probes" 2> /dev/null || return 0
  replayable=true
  : > "$keep_out/etags.json" || return 0
  while IFS= read -r endpoint; do
    key=$(printf '%s' "$endpoint" | hash) || return 0
    if [ -f "$TMP/probe/$key.read" ] && [ "$(cat "$TMP/probe/$key.endpoint")" = "$endpoint" ]; then
      cat "$TMP/probe/$key.read" >> "$keep_out/etags.json" || return 0
    else
      # Not read before this read's GraphQL: its first read now gives the
      # next full read its ETags, and this read is not replayed.
      replayable=false
      printf '%s\n' '["\"-\""]' >> "$keep_out/etags.json" || return 0
    fi
  done < "$keep_out/probes"
  # Pack the same endpoint/ETag pairs in one process, preserving list order
  # and refusing a missing or extra JSON value instead of shifting pairs.
  jq -cn --rawfile endpoints "$keep_out/probes" '
    ($endpoints | split("\n") | .[:-1]) as $endpoints | [inputs] as $tags
    | if ($endpoints | length) != ($tags | length) then error("probe count")
      else $endpoints | to_entries[] | {endpoint: .value, etags: $tags[.key]} end
    ' "$keep_out/etags.json" > "$keep_out/probes.json" || return 0
  jq -n --arg schema "$UNCHANGED_SCHEMA" --arg self "$SELF" --arg host "${GH_HOST:-github.com}" --arg repo "$REPO" \
    --argjson spec "$SPEC" --argjson at "$NOW" --argjson replayable "$replayable" --argjson private "$private" \
    --arg default "$DEFAULT" --argjson repo_id "$REPO_ID" --slurpfile graphql "$keep_out/graphql.json" \
    --slurpfile probes "$keep_out/probes.json" \
    '{schema: $schema, self: $self, host: $host, repo: $repo, spec: $spec, read_at: $at, replayable: $replayable,
      private: $private, default: $default, repo_id: $repo_id, graphql: $graphql[0], probes: $probes}
    | tojson' > "$keep_out/body.json" 2> /dev/null || return 0
  jq -j . "$keep_out/body.json" > "$keep_out/body" && digest=$(hash < "$keep_out/body") || return 0
  pending=$(mktemp "$CACHE/.unchanged.XXXXXX" 2> /dev/null) || return 0
  if jq -c --arg h "$digest" '{sha256: $h, body: .}' "$keep_out/body.json" > "$pending"; then
    mv -f "$pending" "$(unchanged_entry)" 2> /dev/null || rm -f "$pending"
  else rm -f "$pending"; fi
}

if [ "$cmd" = wake ] || [ "$cmd" = claim ]; then
  items
  settings
  wake_world
  # A start claim on a ticket reads every fleet'"'"'s open work (F6, #1353).
  if [ "$cmd" = claim ] && jq -se --argjson n "$CLAIM_N" 'any(.[]; .number == $n and .subIssuesSummary != null)' "$TMP/items.txt" > /dev/null; then
    active
  fi
elif [ "$cmd" = spec ]; then
  # A fleet thread's check: the check's reads, of its own spec alone; none
  # at all past the probe when nothing it read has changed (GI1).
  [ -n "$REPLAY" ] || unchanged
  specs_list
  settings
  awk -v s="$SPEC" '$1 == s' "$TMP/spec-list.sorted" > "$TMP/spec-list.one" \
    && mv "$TMP/spec-list.one" "$TMP/spec-list.sorted" || die "can't read the open issues"
  if [ -s "$TMP/spec-list.sorted" ]; then
    specs
  else
    done_spec="fleet done #$SPEC: it is not an open spec; delete this fleet thread's loop and archive the thread"
    printf '[]' > "$TMP/specs.json" || die "can't write"
  fi
  printf '[]' > "$TMP/singles.json" || die "can't write"
else
  specs_list
  settings
  specs
  singles
fi
world "$TMP/checks.json" "$TMP/labels.json" "$TMP/singles.json"
if [ -f "$TMP/active.json" ]; then
  jq --slurpfile a "$TMP/active.json" '.active = $a[0]' "$TMP/world.json" > "$TMP/w2.json" \
    && mv "$TMP/w2.json" "$TMP/world.json" || die "can't read the open work"
fi
# A gh failure means public. No API body is echoed.
if [ -n "$REPLAY" ]; then
  private=$(cat "$REPLAY/snap/private")
else
  private=$(gh repo view --json isPrivate --jq .isPrivate 2>/dev/null) || private=false
fi
[ "$private" = true ] || private=false
python3 "$(dirname "$0")/records.py" "$REPO" "$private" < "$TMP/world.json" > "$TMP/resolved.json" \
  && mv "$TMP/resolved.json" "$TMP/world.json" || die "can't resolve fleet records"
case $cmd in check | wake | spec | every) branches; waits ;; claim) waits ;; esac
merges
[ "$cmd" = holds ] || { fingerprints; writers; }
links_read
selection
jqw "$cmd" > "$TMP/out.txt" || die "can't work out what is due"
case $(head -n 1 "$TMP/out.txt") in error\ *) die "$(head -n 1 "$TMP/out.txt" | cut -c7-)" ;; esac
if grep -q '^guard #' "$TMP/out.txt"; then
  guard
  jqw "$cmd" > "$TMP/out.txt" || die "can't work out what is due"
  ! grep -q '^guard #' "$TMP/out.txt" || die "the re-test guard could not read what it needs"
fi
if [ "$cmd" = check ]; then
  nightly
  quiet
elif [ "$cmd" = spec ]; then
  quiet
  [ -z "$RECORD" ] || keep_read
fi
[ -z "$REPLAY" ] || [ ! -e "$TMP/changed" ] || die "an answer changed since the saved full read"
cat "$TMP/out.txt"
[ -z "${done_spec:-}" ] || printf '%s\n' "$done_spec"
[ "$cmd" != check ] || [ ! -f "$TMP/nightly-out.txt" ] || cat "$TMP/nightly-out.txt"
[ -n "$REPLAY" ] || points
