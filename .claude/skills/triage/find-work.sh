#!/bin/sh
# Lists a project's triage work, oldest first, one line per issue:
#   #<number> <what>: <title>
# where <what> is "new", "to sort", "reply" or "builder question". Prints
# nothing, and exits 0, when there is no work.
#
# Exits 2, with the reason on stderr and nothing on stdout, when it can't
# read every open issue, the labels file or the record authors. Never read
# that as "nothing to do".
#
# It reads every open issue, 100 at a time, and only each issue's newest
# comment. The state labels come from docs/agents/triage-labels.md (written
# by the setup skill), so a project's own label names work. A marker or an
# approval quiets an issue only when the factory wrote it (#717): its logins
# are the Record authors row of docs/agents/fleet.md on the default branch.
#
# Usage, from the project's root: sh <this folder>/find-work.sh [<triage-labels.md>]
# Needs gh (signed in) and jq.
set -u

labels_file=${1:-docs/agents/triage-labels.md}

die() {
  echo "find-work: $*" >&2
  exit 2
}

command -v gh > /dev/null 2>&1 || die "gh is not installed"
command -v jq > /dev/null 2>&1 || die "jq is not installed"
[ -r "$labels_file" ] || die "cannot read $labels_file (run the setup skill)"

# The label for one role: its row "| `role` | `label` | meaning |" must
# appear exactly once, with the label in backticks.
label() {
  awk -F'|' -v role="$1" '
    { r = $2; l = $3; gsub(/^ +| +$/, "", r); gsub(/^ +| +$/, "", l) }
    r == "`" role "`" && l ~ /^`[^`]+`$/ { n++; v = substr(l, 2, length(l) - 2) }
    END { if (n == 1) print v; else exit 1 }' "$labels_file"
}
needs_triage=$(label needs-triage) || die "$labels_file maps no single label to needs-triage"
needs_info=$(label needs-info) || die "$labels_file maps no single label to needs-info"
ready_for_agent=$(label ready-for-agent) || die "$labels_file maps no single label to ready-for-agent"
ready_for_human=$(label ready-for-human) || die "$labels_file maps no single label to ready-for-human"
wontfix=$(label wontfix) || die "$labels_file maps no single label to wontfix"
jq -en --arg a "$needs_triage" --arg b "$needs_info" --arg c "$ready_for_agent" --arg d "$ready_for_human" \
  --arg e "$wontfix" '[$a, $b, $c, $d, $e] | unique | length == 5' > /dev/null ||
  die "$labels_file gives two roles one label"

# #717: the factory's identity, read as launch-fleet reads it: the one
# "| Record authors | <cell> |" row of fleet.md's "## GitHub identity" table,
# its whole cell backticked logins separated by commas. No row, an empty one,
# any malformed or extra entry, or anything after the value cell stops the
# check, never keeping only the logins that did parse.
fleet=$(gh api -H 'Accept: application/vnd.github.raw+json' 'repos/{owner}/{repo}/contents/docs/agents/fleet.md' 2> /dev/null) ||
  die "cannot read the record authors from docs/agents/fleet.md"
authors=$(printf '%s\n' "$fleet" \
  | awk '/^## /{on = ($0 == "## GitHub identity")} on && /^[|] *Record authors *[|]/' \
  | jq -cRse 'split("\n") | map(select(length > 0)) | select(length == 1) | .[0]
    | split("|") | select(length == 4 and (.[3] | test("^\\s*$"))) | .[2]
    | "`[A-Za-z0-9](-?[A-Za-z0-9])*(\\[bot\\])?`" as $login
    | select(test("^\\s*" + $login + "(\\s*,\\s*" + $login + ")*\\s*$"))
    | [scan("`([^`]*)`") | .[0] | ascii_downcase]' 2> /dev/null) ||
  die 'docs/agents/fleet.md names no record authors (its "## GitHub identity" table'"'"'s "Record authors" row)'

# Every open issue, oldest first. comments(last: 1) is the newest comment.
query='query($owner: String!, $repo: String!, $endCursor: String) {
  repository(owner: $owner, name: $repo) {
    issues(states: OPEN, first: 100, after: $endCursor, orderBy: {field: CREATED_AT, direction: ASC}) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        milestone { number }
        parent { number }
        subIssuesSummary { total }
        labels(first: 100) { totalCount nodes { name } }
        comments(last: 1) { nodes { body author { __typename login } } }
      }
    }
  }
}'
pages=$(gh api graphql --paginate --slurp -F owner='{owner}' -F repo='{repo}' -f query="$query") ||
  die "gh failed, so the open issues were not all read"

# Check the read is whole before listing anything, then sort it.
work=$(printf '%s\n' "$pages" | jq -r \
  --arg nt "$needs_triage" --arg ni "$needs_info" --arg ra "$ready_for_agent" \
  --arg rh "$ready_for_human" --arg wf "$wontfix" --argjson authors "$authors" '
  def fail($why): error("find-work: " + $why);
  [$nt, $ni, $ra, $rh, $wf] as $states
  | if type != "array" or length == 0 then fail("gh returned no pages") else . end
  | if any(.[]; .errors != null) then fail("GitHub returned an error") else . end
  | [.[].data.repository.issues] as $pages
  | [$pages[].nodes[]] as $issues
  | if ([$pages[].totalCount] | unique | length) != 1 then fail("the open issues changed while they were read; run it again") else . end
  | if ($issues | length) != $pages[0].totalCount then fail("read \($issues | length) of \($pages[0].totalCount) open issues") else . end
  | if ([$issues[].number] | unique | length) != ($issues | length) then fail("an issue was read twice; run it again") else . end
  | if any($issues[]; .labels.totalCount > (.labels.nodes | length)) then fail("an issue has more than 100 labels") else . end
  | def labelled($l): any(.labels.nodes[].name; . == $l);
    def stated: any(.labels.nodes[].name; IN($states[]));
    # GraphQL names an App without the "[bot]" REST and the setting give it.
    # A comment with no author (a deleted account) is never a record.
    def login: .author | if type == "object" and (.login | type) == "string" then
      (if .__typename == "Bot" and (.login | endswith("[bot]") | not) then .login + "[bot]" else .login end
       | ascii_downcase) else null end;
    def authored: login as $l | $l != null and any($authors[]; . == $l);
    # Recognition of our response marker, not an approval/authority check.
    # Approval records keep the contract opening and pointer before the marker.
    # Only the newest comment counts, and only when the factory wrote it (#717).
    def quiet: (.comments.nodes | last // {}) | select(authored) // {} | (.body // "")
      | startswith("> *This was generated by AI during triage.*")
        or test("^\\*\\*Approved on its own by [^\\n]+, [0-9]{4}-[0-9]{2}-[0-9]{2}:\\*\\* [^\"“”\\n]+\\nPrivate record: https://github\\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*\\n\\n> \\*This was generated by AI during triage\\.\\*(\\n|$)");
    [$issues | sort_by(.number) | .[]
     | (if stated | not then
          (if .milestone == null and .parent == null and .subIssuesSummary.total == 0 then "new" else empty end)
        elif quiet then empty
        elif labelled($ni) and labelled($ra) then "builder question"
        elif labelled($ni) then "reply"
        elif labelled($nt) then "to sort"
        else empty end) as $what
     | "#\(.number) \($what): \(.title)"]
  | .[]') || die "the open issues could not be checked"

[ -z "$work" ] || printf '%s\n' "$work"
