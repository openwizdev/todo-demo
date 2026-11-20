#!/bin/sh
# The link checker of the plan links contract (contracts/plan-links.v1.md,
# #1318): every native blocker of an open ticket needs one reason line in
# its ticket's `## Links` section, real (with its behaviour) or file (with
# its files). Refuses a graph with any link that gives no reason, and
# reports its file links. Same style as check-relies.sh: sh and jq, writes
# nothing.
#
#   sh check-links.sh [--json] <spec>      reads spec <spec>'s tickets through gh
#   sh check-links.sh [--json] --graph -   reads one graph read on standard input
#   sh check-links.sh --read <spec>        prints the spec's graph read, unchecked,
#                                          for approve.py (#1339)
#
# Exit 0: pass, the report on stdout. 1: refused, the report on stdout and one
# line per refusal on stderr. 2: bad arguments, or a failed, partial or
# invalid read: nothing on stdout, why in one line on stderr. The spec form
# reads the Record authors setting (docs/agents/fleet.md on the default
# branch, #717), then makes only `gh api graphql` reads (its sub-issues, then
# the open pull requests), each checked and every page counted; --graph makes
# no call.
set -f
LC_ALL=C
export LC_ALL
nl='
'
die() { printf 'check-links: %s\n' "$*" >&2; exit 2; }
usage() { die 'usage: sh check-links.sh [--json | --read] <spec> | sh check-links.sh [--json] --graph -'; }

json=false
graph=false
read_only=false
spec=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --json) [ "$json" = false ] || usage; json=true; shift ;;
    --read) [ "$read_only" = false ] || usage; read_only=true; shift ;;
    --graph)
      [ "$#" -ge 2 ] && [ "$2" = - ] && [ "$graph" = false ] && [ -z "$spec" ] || usage
      graph=true
      shift 2 ;;
    -h | --help)
      printf 'usage: sh check-links.sh [--json] <spec> | sh check-links.sh [--json] --graph -\n'
      printf 'Check that every link of a plan graph gives its reason; sh and jq only.\n'
      exit 0 ;;
    '' | 0* | *[!0-9]*) usage ;;
    *) [ -z "$spec" ] && [ "$graph" = false ] || usage; spec=$1; shift ;;
  esac
done
[ "$graph" = true ] || [ -n "$spec" ] || usage
[ "$read_only" = false ] || { [ "$graph" = false ] && [ "$json" = false ]; } || usage
command -v jq > /dev/null 2>&1 || die 'jq is required'

# The checker: one graph read, as a stream of jq events (so a repeated key,
# which jq's parser would silently drop, is seen), in; the JSON report, or a
# JSON string saying why the read is refused, out. Messages are fixed text:
# no ticket text reaches stderr.
CHECK='
def fail($why): error("read: " + $why);
def need(c; $why): if c then . else fail($why) end;
def number: type == "number" and . == floor and . >= 1;
def keys_are($k): type == "object" and (keys == ($k | sort));
def unique_items: (unique | length) == length;
def strip: sub("^[ \t]+"; "") | sub("[ \t]+$"; "");

def valid_ticket:
  need(keys_are(["number","title","state","labels","milestone","parent","blocked_by","body","start_recorded","pull_requests"]); "a ticket does not have exactly its keys")
  | need(.number | number; "a ticket number is not a positive integer")
  | need(.title | type == "string" and length > 0; "a ticket title is not a non-empty string")
  | need(.state == "OPEN" or .state == "CLOSED"; "a ticket state is not OPEN or CLOSED")
  | need(.labels | type == "array" and all(.[]; type == "string" and length > 0) and unique_items; "a ticket'"'"'s labels are not unique non-empty strings")
  | need(.milestone == null or (.milestone | type == "string" and length > 0); "a milestone is not a non-empty string or null")
  | need(.parent == null or (.parent | number); "a parent is not a positive integer or null")
  | need(.blocked_by | type == "array" and all(.[]; keys_are(["number","state"]) and (.number | number) and (.state == "OPEN" or .state == "CLOSED")); "a blocker is not a number and a state")
  | need(.body | type == "string"; "a body is not a string")
  | need(.start_recorded | type == "boolean"; "start_recorded is not a boolean")
  | need(.pull_requests | type == "array" and all(.[]; number) and unique_items; "pull_requests are not unique positive integers")
  | need([.blocked_by[].number] | unique_items; "a blocker is listed twice for one ticket");

def valid_graph:
  need(keys_are(["schema","kind","repo","read_at","source","tickets"]); "the read is not a graph record with exactly its keys")
  | need(.schema == "openwiz.plan-links.v1" and .kind == "graph"; "the read is not an openwiz.plan-links.v1 graph")
  | need(.repo | type == "string" and test("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"); "the repo is not owner/name")
  | need(.read_at | type == "string" and test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"); "read_at is not a UTC time")
  | need(.source | (keys_are(["kind","spec"]) and .kind == "spec" and (.spec | number)) or (keys_are(["kind"]) and .kind == "board"); "the source is not a spec or the board")
  | need(.tickets | type == "array"; "tickets is not a list")
  | [.tickets[] | valid_ticket] as $ok
  | need([.tickets[].number] | unique_items; "a ticket is listed twice");

# A body'"'"'s `## Links` section: null (none), {malformed: detail},
# or {lines: [...]}, by the contract'"'"'s "Reading a section".
def section:
  (split("\r\n") | join("\n") | split("\n") | map(sub("[ \t]+$"; ""))) as $l
  | (reduce range(0; $l | length) as $i ({fence: null, comment: false, heads: []};
      $l[$i] as $line | ($line | sub("^\\s+"; "")) as $trim
      | (if $line == "## Links" and (.comment | not) and .fence == null then .heads += [$i] else . end)
      | (if .fence != null then
          .fence as $open
          | if ($trim | test("^" + $open[0:1] + "{" + ($open | length | tostring) + ",}\\s*$")) then .fence = null else . end
        else .fence = ([$trim | match("^(`{3,}|~{3,})") | .string][0] // null) end)
      | (if ($line | contains("<!--")) then .comment = true else . end)
      | (if ($line | contains("-->")) then .comment = false else . end)
    ) | .heads) as $heads
  | if ($heads | length) == 0 then null
    elif ($heads | length) > 1 then {malformed: "more than one ## Links section"}
    else
      ($l[$heads[0] + 1:]) as $rest
      | ([range(0; $rest | length) | select($rest[.] | test("^(#{1,6} |#{1,6}$)"))][0] // ($rest | length)) as $stop
      | [$rest[0:$stop][] | select(. != "")] as $lines
      | if ($lines | length) == 0 then {malformed: "no lines"}
        elif any($lines[]; . != "none" and (test("^- #[1-9][0-9]* (real|file):") | not)) then {malformed: "a line is not a link line or none"}
        elif ($lines | length) > 1 and any($lines[]; . == "none") then {malformed: "none must be the only line"}
        elif $lines == ["none"] then {lines: []}
        else {lines: [$lines[] | capture("^- #(?<n>[1-9][0-9]*) (?<kind>real|file):(?<reason>.*)$") | .reason |= strip]}
        end
    end;

def words:
  gsub("`[^`]*`"; " ") | [splits("\\s+")]
  | map(sub("^[\\[\\](){}\"\u0027,.;:!?]+"; "") | sub("[\\[\\](){}\"\u0027,.;:!?]+$"; ""))
  | map(select(test("^[A-Za-z]+([\u0027-][A-Za-z]+)*\u0027?$"))) | length;

def files:
  [scan("`([^`]*)`") | .[0]
   | select(test("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*/?$") and all(split("/")[]; . != "." and . != ".."))]
  | reduce .[] as $f ([]; if any(.[]; . == $f) then . else . + [$f] end);

def refusal($t; $n; $code; $message): {ticket: $t, number: $n, code: $code, message: $message};
def link($t; $b; $kind; $files): {ticket: $t, blocker: $b.number, blocker_state: $b.state, kind: $kind, files: $files};

# One open ticket: {links, refusals}.
def judge:
  .number as $t
  | (.blocked_by | sort_by(.number)) as $b
  | (.body | section) as $s
  | if $s == null or $s.lines == [] then
      {links: [$b[] | link($t; .; "unlabelled"; [])],
       refusals: [$b[] | refusal($t; .number; "no_reason"; "#\(.number) has no reason line")]}
    elif $s.malformed then
      {links: [$b[] | link($t; .; "unlabelled"; [])],
       refusals: [refusal($t; null; "malformed"; "malformed section: \($s.malformed)")]}
    else
      ($b | map(.number | tostring)) as $names
      | ([$s.lines[].n | select(. as $n | $names | index([$n]) | not)] | unique | map(tonumber) | sort) as $strangers
      | [$b[] | . as $one | [$s.lines[] | select(.n == ($one.number | tostring))] as $mine
         | if ($mine | length) == 0 then {link: link($t; $one; "unlabelled"; []), refusal: refusal($t; $one.number; "no_reason"; "#\($one.number) has no reason line")}
           elif ($mine | length) > 1 then {link: link($t; $one; "unlabelled"; []), refusal: refusal($t; $one.number; "duplicate"; "#\($one.number) has more than one line")}
           elif $mine[0].kind == "real" then
             if ($mine[0].reason | words) >= 3 then {link: link($t; $one; "real"; [])}
             else {link: link($t; $one; "unlabelled"; []), refusal: refusal($t; $one.number; "real_without_behaviour"; "the real line for #\($one.number) names no behaviour")} end
           else
             ($mine[0].reason | files) as $f
             | if ($f | length) > 0 then {link: link($t; $one; "file"; $f)}
               else {link: link($t; $one; "unlabelled"; []), refusal: refusal($t; $one.number; "file_without_file"; "the file line for #\($one.number) names no file in backticks")} end
           end] as $judged
      | {links: [$judged[].link],
         refusals: ([$strangers[] | refusal($t; .; "not_a_blocker"; "#\(.) is not a native blocker")] + [$judged[] | .refusal // empty] | sort_by(.number))}
    end;

try (
  [inputs] as $events
  | [fromstream($events[])] as $values
  | need(($values | length) == 1; "the read is not one JSON value")
  | $values[0]
  | need(([tostream] | length) == ($events | length); "a key is repeated")
  | valid_graph
  | ([.tickets[] | select(.state == "OPEN")] | sort_by(.number)) as $open
  | [$open[] | judge] as $judged
  | [$judged[].links[]] as $links
  | [$judged[].refusals[]] as $refusals
  | ([$links[] | select(.kind == "real")] | length) as $real
  | ([$links[] | select(.kind == "file")] | length) as $file
  | ([$links[] | select(.kind == "unlabelled")] | length) as $unlabelled
  | {schema: "openwiz.plan-links.v1", kind: "report", repo, source,
     result: (if ($refusals | length) == 0 then "pass" else "refused" end),
     counts: {tickets: ($open | length), links: ($links | length), real: $real, file: $file,
              unlabelled: $unlabelled, refusals: ($refusals | length)},
     links: $links, refusals: $refusals}
) catch (if type == "string" and startswith("read: ") then .[6:] else "the graph read cannot be checked" end)
'

# Runs the checker on the graph read on stdin and prints the report.
run_check() {
  out=$(jq -cn --stream "$CHECK" 2> /dev/null) || die 'the graph read is not JSON'
  case "$out" in
    '"'*) why=$(printf '%s\n' "$out" | jq -r .) || why='the graph read is not valid'; die "$why" ;;
    '{'*) ;;
    *) die 'the checker gave no verdict' ;;
  esac
  if [ "$json" = true ]; then
    printf '%s\n' "$out" | jq . || die 'cannot print the report'
  else
    printf '%s\n' "$out" | jq -r '
      "\(.result) \(if .source.kind == "spec" then "spec #\(.source.spec)" else "board" end): tickets \(.counts.tickets), links \(.counts.links), real \(.counts.real), file \(.counts.file), unlabelled \(.counts.unlabelled), refusals \(.counts.refusals)",
      (.links[] | select(.kind == "file") | "file link: #\(.ticket) blocked by #\(.blocker): \(.files | join(", "))")
    ' || die 'cannot print the report'
  fi
  printf '%s\n' "$out" | jq -r '.refusals[] | "Links: #\(.ticket): \(.message)"' >&2
  if printf '%s\n' "$out" | jq -e '.result == "pass"' > /dev/null; then exit 0; fi
  exit 1
}

if [ "$graph" = true ]; then
  run_check
fi

# The spec form: the spec's sub-issues, then the open pull requests, through
# `gh api graphql`, page by page. Each page is checked as it arrives and
# reduced to two lines: its next cursor (or -), its record count and the
# count GitHub gives, then its records.
command -v gh > /dev/null 2>&1 || die 'gh is required'
command -v date > /dev/null 2>&1 || die 'date is required'
read_at=$(date -u +%Y-%m-%dT%H:%M:%SZ) || die 'cannot read the time'
# #717: a start record counts only when the factory wrote it. Its identity is
# the one "| Record authors | <cell> |" row of fleet.md's "## GitHub identity"
# table, read as launch-fleet reads it: the whole cell backticked logins
# separated by commas. No row, an empty one, any malformed or extra entry, or
# anything after the value cell refuses the read, never keeping only the
# logins that did parse.
fleet=$(gh api -H 'Accept: application/vnd.github.raw+json' \
  'repos/{owner}/{repo}/contents/docs/agents/fleet.md' 2> /dev/null) ||
  die 'cannot read the record authors from docs/agents/fleet.md'
# The row is picked as launch-fleet's awk picks it, in jq: this checker uses
# sh and jq only.
authors=$(printf '%s\n' "$fleet" \
  | jq -cRse 'split("\n")
    | reduce .[] as $line ({on: false, rows: []};
        if $line | startswith("## ") then .on = ($line == "## GitHub identity")
        elif .on and ($line | test("^[|] *Record authors *[|]")) then .rows += [$line] else . end)
    | .rows | select(length == 1) | .[0]
    | split("|") | select(length == 4 and (.[3] | test("^\\s*$"))) | .[2]
    | "`[A-Za-z0-9](-?[A-Za-z0-9])*(\\[bot\\])?`" as $login
    | select(test("^\\s*" + $login + "(\\s*,\\s*" + $login + ")*\\s*$"))
    | [scan("`([^`]*)`") | .[0] | ascii_downcase]' 2> /dev/null) ||
  die 'docs/agents/fleet.md names no record authors (its "## GitHub identity" table'"'"'s "Record authors" row)'
ISSUES='query($owner:String!,$name:String!,$spec:Int!,$after:String){repository(owner:$owner,name:$name){nameWithOwner issue(number:$spec){subIssues(first:50,after:$after){totalCount pageInfo{hasNextPage endCursor} nodes{number title state body labels(first:100){totalCount nodes{name}} milestone{title} parent{number} blockedBy(first:100){totalCount nodes{number state}} comments(last:15){nodes{body author{__typename login}}}}}}}}'
PULLS='query($owner:String!,$name:String!,$after:String){repository(owner:$owner,name:$name){pullRequests(states:OPEN,first:100,after:$after){totalCount pageInfo{hasNextPage endCursor} nodes{number title}}}}'
PAGE='
def fail($why): error($why);
def need(c; $why): if c then . else fail($why) end;
def count: type == "number" and . == floor and . >= 0;
# GraphQL names an App without the "[bot]" REST and the setting give it. A
# comment with no author (a deleted account) is never a record.
def login: .author | if type == "object" and (.login | type) == "string" then
  (if .__typename == "Bot" and (.login | endswith("[bot]") | not) then .login + "[bot]" else .login end
   | ascii_downcase) else null end;
def authored: login as $l | $l != null and any($authors[]; . == $l);
def complete($what): need(type == "object" and (.totalCount | count) and (.nodes | type == "array") and (.nodes | length) == .totalCount; "a ticket'"'"'s \($what) were not all read");
try (
  need(type == "object" and .errors == null and (.data | type == "object") and (.data.repository | type == "object"); "the read failed")
  | .data.repository as $r
  | (if $kind == "issues" then
       need($r.issue | type == "object"; "it is not an issue") | $r.issue.subIssues
     else $r.pullRequests end) as $c
  | need($c | type == "object" and (.totalCount | count) and (.nodes | type == "array") and (.pageInfo | type == "object") and (.pageInfo.hasNextPage | type == "boolean"); "a page is not a connection")
  | need(($c.pageInfo.hasNextPage | not) or (($c.pageInfo.endCursor | type == "string" and test("^[A-Za-z0-9+/=_-]+$")) and ($c.nodes | length) > 0); "a page has no next cursor")
  | "\(if $c.pageInfo.hasNextPage then $c.pageInfo.endCursor else "-" end) \($c.nodes | length) \($c.totalCount)",
    ({kind: $kind, total: $c.totalCount, repo: $r.nameWithOwner, records:
      [$c.nodes[] | need(type == "object"; "a record is not an object")
       | if $kind == "prs" then {number, title}
         else
           (.labels | complete("labels")) as $ok1 | (.blockedBy | complete("blockers")) as $ok2
           | need(.comments | type == "object" and (.nodes | type == "array"); "a ticket'"'"'s comments were not read")
           | {number, title, state, labels: [.labels.nodes[].name], milestone: (.milestone.title // null),
              parent: (.parent.number // null), blocked_by: [.blockedBy.nodes[] | {number, state}], body,
              start_recorded: any(.comments.nodes[]; authored and (.body | type == "string" and startswith("launch-fleet: start")))}
         end]} | tojson)
) catch error("bad")
'

# read_pages <issues|prs> <query> [gh args...]: appends each page's records
# line to $pages, following cursors until the last page. A page with more to
# come holds at least one record, and the pages may hold no more than the
# first page counts, so a repeated cursor ends the read instead of looping.
pages=''
read_pages() {
  kind=$1 query=$2
  shift 2
  after='' got=0 total=''
  while :; do
    if [ -z "$after" ]; then
      page=$(gh api graphql -f query="$query" -F owner='{owner}' -F name='{repo}' "$@" 2> /dev/null) || return 1
    else
      page=$(gh api graphql -f query="$query" -F owner='{owner}' -F name='{repo}' "$@" -f after="$after" 2> /dev/null) || return 1
    fi
    info=$(printf '%s\n' "$page" | jq -cr --arg kind "$kind" --argjson authors "$authors" "$PAGE" 2> /dev/null) || return 1
    case "$info" in *"$nl"*) ;; *) return 1 ;; esac
    first=${info%%"$nl"*}
    cursor=${first%% *} rest=${first#* }
    n=${rest%% *} count=${rest#* }
    case "$rest" in *' '*) ;; *) return 1 ;; esac
    case "$n" in '' | *[!0-9]*) return 1 ;; esac
    case "$count" in '' | *[!0-9]*) return 1 ;; esac
    [ -n "$total" ] || total=$count
    got=$((got + n))
    [ "$got" -le "$total" ] || return 1
    pages="$pages$nl${info#*"$nl"}"
    [ "$cursor" != - ] || return 0
    after=$cursor
  done
}
read_pages issues "$ISSUES" -F spec="$spec" || die "cannot read spec #$spec's tickets"
read_pages prs "$PULLS" || die 'cannot read the open pull requests'

# The graph read: every page of each kind agrees on its count, and the pages
# hold exactly that many records; each ticket gets its open pull requests.
read=$(printf '%s\n' "$pages" | jq -cs --arg read_at "$read_at" --argjson spec "$spec" '
  def need(c; $why): if c then . else error($why) end;
  def all_of($kind): [.[] | select(.kind == $kind)];
  try (
    all_of("issues") as $i | all_of("prs") as $p
    | need(($i | length) > 0 and ($p | length) > 0; "a read is missing")
    | need(($i | map(.total) | unique | length) == 1 and ($p | map(.total) | unique | length) == 1; "a count changed between pages")
    | [$i[].records[]] as $tickets | [$p[].records[]] as $pulls
    | need(($tickets | length) == $i[0].total and ($pulls | length) == $p[0].total; "the pages do not hold every record counted")
    | need(($i | map(.repo) | unique | length) == 1; "the pages name different repositories")
    | {schema: "openwiz.plan-links.v1", kind: "graph", repo: $i[0].repo, read_at: $read_at,
       source: {kind: "spec", spec: $spec},
       tickets: [$tickets[] | (.number | tostring) as $n
         | . + {pull_requests: [$pulls[] | select(.title | type == "string" and test("^#" + $n + "([^0-9]|$)")) | .number] | unique}]}
  ) catch error("bad")
' 2> /dev/null) || die "spec #$spec's read is partial or invalid"

if [ "$read_only" = true ]; then printf '%s\n' "$read"; exit 0; fi
printf '%s\n' "$read" | run_check
