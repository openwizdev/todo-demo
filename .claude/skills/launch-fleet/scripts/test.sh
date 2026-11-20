#!/bin/sh
# fleet.sh on synthetic GitHub answers (ClosedWiz#102). Run from anywhere:
#   sh skills/launch-fleet/scripts/test.sh
# Each case builds a synthetic GitHub (a fixture, changed by a jq filter), runs
# one fleet.sh command against the fake `gh` in fixtures/gh.py, and asserts the
# exact output and exit status: for exit 0, the exact stdout, and on stderr
# exactly the check's one points line (ClosedWiz#189), or exactly $ERR when the
# case sets it; for exit 2, an empty stdout and the expected reason on stderr.
# Any mismatch, any setup step that fails and any missing case is counted, and
# the run exits 1. FLEET_SH=<file> runs the same cases against another script;
# TEST_BEFORE_189=1 also takes an empty stderr, as fleet.sh printed before
# #189, for a red run against it; TEST_ONLY=<a case's name> runs just that
# case or shell pattern (for example TEST_ONLY="contexts:*"); TEST_ONLY=loop runs the four loop cases; TEST_ONLY=fleet-loop runs the two spec-loop cases; an `again` case runs only with the case
# before it). A pattern also sets TEST_EXPECTED to its exact case count.
# HOUR_BEFORE=<file> runs the hour's timer (ClosedWiz#259) on
# another fleet.sh, to measure it; one from before #259 needs the fake gh of
# its day, before the search for issues outside specs.
#
# A full run (no TEST_ONLY) runs the cases in TEST_JOBS workers at once (by
# default one per CPU the container allows; ClosedWiz#1254). Each worker runs
# this script again and takes each group of cases (one `expect` with the
# `again`, `log_has` and checks after it, or one block) that no other worker
# took first; it runs the heavy groups first. Every group runs in exactly one
# worker, in its own folders; the output is printed in this file's order once
# all are done. TEST_TIMES=<file> writes each group's milliseconds and first
# line there (`-` prints them, as on GitHub Actions).
# TEST_SHARD=K/N (#743) runs only shard K's groups of N, for CI's parallel
# members: TEST_SHARD_MAP=<file> gives each group its shard ("GROUP SHARD"
# lines, from ci/shard/lanes.py); a group past the map's last goes to shard
# ((GROUP - 1) mod N) + 1. It writes TEST_SHARD_RAN=<file>: its case count,
# the run's total ($CASES) and group count, and each group it ran with its
# milliseconds; the ci job checks the shards' counts add up to the total.
set -u
HERE=$(cd "$(dirname "$0")" && pwd) || exit 1
FLEET=${FLEET_SH:-$HERE/fleet.sh}
FIX=$HERE/fixtures
NOW=1793534400 # 2026-11-01T12:00:00Z, the fixtures' "now"
CASES=882      # includes the two CW-G fresh wake cases; WS8 moved the re-check case to test-brief.py; WS17 added 22
fails=0
cases=0
ERR=''         # the exact stderr the next case expects, when not the points line
RUN_FLEET=''   # another fleet.sh for the next `again` case only
# The one line a check that exits 0 may print on stderr: what it asked GitHub.
POINTS='fleet\.sh: used [0-9]+ GitHub points in [0-9]+ questions, [0-9]+ unchanged; ([0-9]+ of [0-9]+ left|no GraphQL read)'

WORKER=${TEST_WORKER:-} PASS=${TEST_PASS:-all}
grp=0 mine=yes took='' t0=''
SHARD_K='' SHARD_N='' SHARD_MAPPED=0
if [ -n "${TEST_SHARD:-}" ]; then
  SHARD_K=${TEST_SHARD%/*} SHARD_N=${TEST_SHARD#*/}
  case $TEST_SHARD in [1-9]*/[1-9]*) ;; *) SHARD_K=x ;; esac
  case $SHARD_K$SHARD_N in *[!0-9]*) echo "FAIL TEST_SHARD is not K/N: $TEST_SHARD"; exit 1 ;; esac
  [ "$SHARD_K" -le "$SHARD_N" ] || { echo "FAIL TEST_SHARD is not K/N: $TEST_SHARD"; exit 1; }
  [ -z "${TEST_ONLY:-}" ] || { echo "FAIL TEST_SHARD runs a whole run's share, not TEST_ONLY"; exit 1; }
  [ -r "${TEST_SHARD_MAP:-}" ] && [ -n "${TEST_SHARD_RAN:-}" ] \
    || { echo "FAIL TEST_SHARD needs TEST_SHARD_MAP and TEST_SHARD_RAN"; exit 1; }
  # Every line "GROUP SHARD", each group once, each shard 1 to N: the last group mapped.
  SHARD_MAPPED=$(awk -v n="$SHARD_N" 'NF != 2 || $1 !~ /^[1-9][0-9]*$/ || $2 !~ /^[1-9][0-9]*$/ || $2 > n || seen[$1]++ { bad = 1 }
    $1 > max { max = $1 } END { if (bad) exit 1; print max + 0 }' "$TEST_SHARD_MAP") \
    || { echo "FAIL TEST_SHARD_MAP is not one \"GROUP SHARD\" line a group: $TEST_SHARD_MAP"; exit 1; }
fi
if [ -n "$WORKER" ]; then
  # A worker: its own folder in the run's; what it prints outside a group goes
  # to its stray file, which the run prints and counts as a failure.
  SHARED=${TEST_SHARED:?} tmp=$TEST_SHARED/w$WORKER-$PASS mine=no
  mkdir "$tmp" && exec >> "$SHARED/stray-$WORKER-$PASS" || exit 3
else
  tmp=$(mktemp -d) || { echo "FAIL no temporary folder"; exit 1; }
  trap 'rm -rf "$tmp"' EXIT
  SHARED=$tmp
  if [ -n "$SHARD_K" ]; then
    mkdir "$tmp/mine" && awk -v k="$SHARD_K" '$2 == k { print $1 }' "$TEST_SHARD_MAP" | while read -r g; do : > "$tmp/mine/$g"; done \
      || { echo "FAIL setup: the shard's groups"; exit 1; }
  fi
fi
mkdir "$tmp/bin" "$tmp/nojq" || { echo "FAIL setup"; exit 1; }
PYTHON=$(command -v python3) || { echo "FAIL setup: python3 is missing"; exit 1; }
printf '#!/bin/sh\nexec "%s" -I -S "%s" "$@"\n' "$PYTHON" "$FIX/gh.py" > "$tmp/bin/gh" && chmod +x "$tmp/bin/gh" \
  && cp "$tmp/bin/gh" "$tmp/nojq/gh" || { echo "FAIL setup: the fake gh"; exit 1; }
# Discovery in the legacy-only fixture harness is deliberately out of reach.
# Public discovery cases supply their own synthetic endpoint in test-records.py.
printf '#!/bin/sh\nexit 1\n' > "$tmp/bin/room-cli" && chmod +x "$tmp/bin/room-cli" \
  || { echo "FAIL setup: the fake room-cli"; exit 1; }
for tool in sh jq mktemp; do
  command -v "$tool" > /dev/null || { echo "FAIL setup: $tool is missing"; exit 1; }
done

# A 40-character commit made of TEXT repeated, as the jq `sha` below makes it.
sha() { s=''; while [ ${#s} -lt 40 ]; do s=$s$1; done; printf '%.40s' "$s"; }
S31=$(sha 31) S31F=$(sha 31f) S31E=$(sha 31e) S99=$(sha 99)

# Small changes to a fixture, for the cases' filters.
LIB='
def at($h): "2026-11-01T\($h):00Z";
def sha($n): ("\($n)" * 40)[:40];
# #257: API-documented shapes, synthetic values, never observed live.
def nightly:
  .runs = [{id: 801, run_attempt: 1, head_sha: sha(81),
    head_branch: .default, path: ".github/workflows/ci.yml", event: "schedule",
    status: "completed", conclusion: "failure"}];
def nightly_record($id; $body): .commitComments += [{id: $id, commit_id: sha(81), body: $body}];
# Synthetic discussion comments; each case chooses where its records fall.
def discussion($count): [range(0; $count) | {id: (10000 + .), at: at("11:40"), body: "Synthetic discussion"}];
def issue($n; f): (.issues[] | select(.number == $n)) |= f;
# The time the held label went on #$n, as its timeline shows it (the latest counts).
def held_at($n; $h): issue($n; .labelEvents += [{name: "held", at: at($h)}]);
def say($n; $id; $h; $body): issue($n; .comments += [{id: $id, at: at($h), body: $body}]);
def pull($n; f): (.pulls[] | select(.number == $n)) |= f;
# Comment $id edited at $h to $body, as a tick edits its claim (GitHub'"'"'s updatedAt).
def edit($n; $id; $h; $body): issue($n; .comments |= map(if .id == $id then .body = $body | .edited = at($h) else . end));
def pr_edit($n; $id; $h; $body): pull($n; .comments |= map(if .id == $id then .body = $body | .edited = at($h) else . end));
def pr_say($n; $id; $h; $body): pull($n; .comments += [{id: $id, at: at($h), body: $body}]);
# #641: a comment someone other than the factory wrote ($who: a login, or null
# for GitHub'"'"'s missing user). Every other synthetic comment is the factory'"'"'s.
def by($n; $id; $h; $who; $body): issue($n; .comments += [{id: $id, at: at($h), author: $who, body: $body}]);
def pr_by($n; $id; $h; $who; $body): pull($n; .comments += [{id: $id, at: at($h), author: $who, body: $body}]);
def outsider: "synthetic-outsider";
# KN13 (#1448): the ready-for-agent label of #$n put on at $h by $who (a login, or null
# for GitHub'"'"'s deleted user), and its body last edited at $h by $who.
def labelled($n; $h; $who): issue($n; .labelEvents += [{name: "ready-for-agent", at: at($h), by: $who}]);
def body_edited($n; $h; $who): issue($n; .editedAt = at($h) | .editor = $who);
# Each check carries the time its workflow run was created ($run): when GitHub
# fixed the merge commit it tests (K9, #337; a re-run keeps it).
def green: [{name: "build", status: "COMPLETED", conclusion: "SUCCESS", run: at("11:00")},
            {name: "test", status: "COMPLETED", conclusion: "SUCCESS", run: at("11:00")}];
# The hourly workflow-start event, also exercised on an empty list.
def running_ci: .checks = green | .rollup = "PENDING" | .checks[1].status = "IN_PROGRESS" | .checks[1].conclusion = null;
def open_pr($n; $t; $headline): .pulls += [{number: $n, state: "OPEN", draft: false, base: "main",
  head: sha($n), committed: at("10:30"), headline: $headline, closes: [$t], rollup: "SUCCESS", checks: green,
  mergedAt: null, updatedAt: at("11:00"), comments: [], files: []}];
def merged_pr($n; $t; $h; $files): .pulls += [{number: $n, state: "MERGED", draft: false, base: "main",
  head: sha($n), mergeCommit: sha("\($n)ec"), headline: "#\($t): green", closes: [$t], rollup: "SUCCESS", checks: green,
  mergedAt: at($h), updatedAt: at($h), comments: [], files: $files}];
def changed($f; $s): {filename: $f, status: $s};
def ticket($n; $title; $labels; $blockers): .issues += [{number: $n, title: $title, state: "OPEN",
  parent: 10, labels: $labels, blockedBy: $blockers, body: "", comments: []}];
# A to-tickets approval comment on SPEC, as to-tickets writes it: the graph
# read back now, one row per ticket; a row is a number (ready-for-agent) or
# [number, label].
def row_of($n; $lbl): .issues[] | select(.number == $n)
  | "| #\(.number) | \(.title) | \(if (.blockedBy | length) == 0 then "none" else (.blockedBy | map("#\(.)") | join(", ")) end) | \($lbl) |";
def approve($spec; $id; $h; $rev; $rows): . as $w
  | say($spec; $id; $h; "**Plan graph approved by Robin, 2026-11-01, revision \($rev):** \"approve\"\n\nChanged since revision \($rev - 1): synthetic.\n\n| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n"
    + ([$rows[] | if type == "array" then . else [., "ready-for-agent"] end | . as [$n, $l] | $w | row_of($n; $l)] | join("\n"))
    + "\n\nFingerprint: `@@FP@@`");
# #1340: to-tickets'"'"' machine plan approval (decisions.v1), as approve.py prints
# it, in place of SPEC'"'"'s human approval; and to-spec'"'"'s steering video comment.
def machine_record($spec; $id; $h; $rev; $rows): . as $w
  | "**Machine plan approval, 2026-11-01, revision \($rev):** links, relies, sizes, width and owned paths passed.\nGrill confirmed: https://github.com/synthetic-owner/synthetic-private/issues/1#issuecomment-1\n\nChecks: \($rows | length) tickets; links 4; relies 3; sizes S 1, M 2, L 0; width: chain 3, widest 1; owned paths 3.\n\n"
    + (if $rev > 1 then "Changed since revision \($rev - 1): synthetic.\n\n" else "" end)
    + "| Ticket | Title | Blocked by | Label |\n| --- | --- | --- | --- |\n"
    + ([$rows[] | . as $n | $w | .issues[] | select(.number == $n)
        | "| #\(.number) | \(.title) | \(if (.blockedBy | length) == 0 then "none" else (.blockedBy | map("#\(.)") | join(" ")) end) | \(if .state == "OPEN" then "ready-for-agent" else "none" end) |"] | join("\n"))
    + "\n\nFingerprint: `@@FP@@`\n\n<details><summary>Revision text</summary>\n\n```text\n@@REV@@```\n\n</details>\n";
def machine($spec; $id; $h; $rev; $rows): say($spec; $id; $h; machine_record($spec; $id; $h; $rev; $rows));
def machine_only: issue(10; .comments = []) | machine(10; 1001; "08:00"; 1; [11, 12, 13, 14]);
# The owner'"'"'s own comment: not the factory App'"'"'s (#1340 R2).
def owner_says($n; $id; $h; $body): by($n; $id; $h; "Synthetic-Owner"; $body);
def video($spec; $id; $h): say($spec; $id; $h; "[Watch the narrated spec](https://example.com/synthetic/spec.mp4)\n\nComment here to steer: stop, reset, or anything else.");
def own_approval($n; $id; $h): say($n; $id; $h; "> *This was generated by AI during triage.*\n\n**Approved on its own by Robin, 2026-11-01:** \"approve #\($n)\"");
def closed_single($n; $h): .issues += [{number: $n, title: "Closed single \($n)", state: "CLOSED", parent: null,
  labels: ["ready-for-agent"], blockedBy: [], updatedAt: at($h), body: "", comments: []}];
def followup($n; $state; $body): .issues += [{number: $n, title: "A low finding \($n)", state: $state, parent: null,
  labels: ["needs-triage"], blockedBy: [], body: $body, comments: []}];
def merge12: issue(12; .state = "CLOSED") | say(12; 1202; "11:05"; "launch-fleet: archived")
  | merged_pr(22; 12; "11:00"; [changed("src/store/store.rs"; "modified")]);
def all_closed: merge12 | issue(13; .state = "CLOSED") | issue(14; .state = "CLOSED")
  | merged_pr(24; 13; "11:10"; []) | merged_pr(25; 14; "11:20"; []);
def pr31: open_pr(31; 12; "#12: widget store, green");
# #923: three configured required names; all run IDs and times are synthetic.
def ci31: pr31
  | .files["docs/agents/fleet.md"] |= sub("\\| `test` \\| 4 \\| `main` \\|"; "| `test` | 4 | `main` |\n| `package` | 5 | `main` |")
  | pull(31; .checks = [
      {name: "build", databaseId: 100, status: "COMPLETED", conclusion: "SUCCESS"},
      {name: "test", databaseId: 101, status: "COMPLETED", conclusion: "SUCCESS"},
      {name: "package", databaseId: 102, status: "COMPLETED", conclusion: "SUCCESS"}]);
def retry($id; $status; $conclusion): .checks += [
  .checks[1] | .databaseId = $id | .status = $status | .conclusion = $conclusion];
def reviewing31: pr31 | pr_say(31; 3101; "11:10"; "launch-fleet: review started \(sha(31)), thread thr_synrev31");
def m23($files): merged_pr(23; 99; "10:00"; $files);
def contract23: m23([changed("contracts/widget.v1.md"; "modified")]);
# #31 reviewed at sha(31) with CHANGES, a new green head sha("31f"), and its re-check sent at $h.
def rechecking31($h): reviewing31 | pull(31; .comments[0].at = at("10:30")) | pr_say(31; 3102; "11:20"; "VERDICT: CHANGES at \(sha(31))") | pr_say(31; 3103; "11:21"; "launch-fleet: findings sent \(sha(31))")
  | pull(31; .head = sha("31f")) | pr_say(31; 3104; $h; "launch-fleet: re-check sent \(sha("31f")), thread thr_synrev31");
def told31($id; $h; $c; $t): pr_say(31; $id; $h; "launch-fleet: review told again \($c), thread \($t)");
# The first reviewer of #31 went quiet: its claim (3101) edited to review failed, after one told-again record (3102).
# K9 (#337): #31 approved at sha(31), green on a run created at 11:00, and changing src/store/store.rs.
def run_at($n; $h; $c): {name: $n, status: "COMPLETED", conclusion: $c, run: at($h)};
# The same, in workflow run $id (its databaseId), as a re-test record names it.
def run_in($n; $h; $c; $id): run_at($n; $h; $c) + {runId: $id};
def store31: reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))")
  | pull(31; .files = [changed("src/store/store.rs"; "modified")]);
def main24($h; $files): merged_pr(24; 99; $h; $files);
def quiet31: pr31 | pr_say(31; 3101; "10:30"; "launch-fleet: review failed \(sha(31)), thread thr_synrev31: no verdict 30 minutes after it was told again")
  | told31(3102; "11:00"; sha(31); "thr_synrev31");
'

selected() { case $1 in ${TEST_ONLY:-*}) return 0 ;; *) return 1 ;; esac; }

bad() { echo "FAIL $1: $2"; fails=$((fails + 1)); }

# world FIXTURE FILTER DIR: the fixture changed by FILTER, on stdout. FILTER
# is "BEFORE @@then@@ AFTER", or just BEFORE. BEFORE makes the world as the
# user approved it: then each spec's "@@FP@@" becomes its fingerprint, from
# to-tickets’ revision.sh (the copy in fixtures/) run on that world, as
# to-tickets records it. AFTER changes it since. The frontier fixture takes its
# settings files from check.json. DIR holds the steps.
world() {
  before=${2%%@@then@@*}
  case $2 in *@@then@@*) after=${2#*@@then@@} ;; *) after=. ;; esac
  if [ "$1" = frontier.json ]; then
    jq --slurpfile c "$FIX/check.json" "$LIB ($before) | .files = \$c[0].files" "$FIX/$1" > "$3/approved.json" || return 1
  else
    jq "$LIB $before" "$FIX/$1" > "$3/approved.json" || return 1
  fi
  specs=$(jq -r '[.issues[] | select(any(.comments[]?; .body | contains("@@FP@@"))) | .number] | unique | .[]' "$3/approved.json") || return 1
  for spec in $specs; do
    fp=$(fingerprint "$3/approved.json" "$spec" "$3") && [ ${#fp} = 64 ] && [ -s "$SHARED/fp/$fp.rev" ] || return 1
    # #1340: a machine record carries the revision text itself ("@@REV@@").
    jq --argjson n "$spec" --arg fp "$fp" --rawfile rev "$SHARED/fp/$fp.rev" \
      '(.issues[] | select(.number == $n) | .comments[]?.body) |= (gsub("@@FP@@"; $fp) | gsub("@@REV@@"; $rev))' \
      "$3/approved.json" > "$3/approved2.json" && mv "$3/approved2.json" "$3/approved.json" || return 1
  done
  jq "$LIB $after" "$3/approved.json"
}

# fingerprint WORLD SPEC DIR: SPEC's fingerprint in WORLD: the SHA-256 of
# what revision.sh prints for it. Cached by everything revision.sh reads (the
# spec's body and tickets, and each ticket's title, body and blockers), so a
# case that changes none of them reuses the answer.
fingerprint() {
  key=$(jq -c --argjson n "$2" '[.issues[] | select(.number == $n or .parent == $n)
    | {number, title, body, blockedBy, parent}] | sort_by(.number)' "$1" | sha256sum | cut -c1-64) || return 1
  [ ${#key} = 64 ] || return 1
  # Shared by the workers: each answer is written whole, then renamed.
  if [ ! -s "$SHARED/fp/$key" ]; then
    mkdir -p "$SHARED/fp" \
      && PATH="$tmp/bin:$PATH" FAKE_GH_WORLD="$1" FAKE_GH_LOG="$3/setup.log" sh "$FIX/revision.sh" "$2" > "$3/revision-$2.txt" \
      && fp_new=$(sha256sum < "$3/revision-$2.txt" | cut -c1-64) && [ ${#fp_new} = 64 ] \
      && cp "$3/revision-$2.txt" "$SHARED/fp/$fp_new.rev.$$" && mv "$SHARED/fp/$fp_new.rev.$$" "$SHARED/fp/$fp_new.rev" \
      && printf '%s\n' "$fp_new" > "$SHARED/fp/$key.$$" && mv "$SHARED/fp/$key.$$" "$SHARED/fp/$key" || return 1
  fi
  cat "$SHARED/fp/$key"
}

# fp12 FIXTURE FILTER SPEC: the first 12 characters of SPEC's fingerprint in
# the world FILTER makes, as it is after AFTER: what a re-approve line names.
fp12() {
  # A worker's heavy pass runs only heavy groups, which make their own.
  if [ "$PASS" = heavy ] && [ "$mine" != yes ]; then echo 'not-this-pass'; return; fi
  d=$(mktemp -d "$tmp/fp.XXXXXX") || return 1
  world "$1" "$2" "$d" > "$d/world.json" || return 1
  fingerprint "$d/world.json" "$3" "$d" | cut -c1-12
}

# base_world FIXTURE: the fixture unchanged, sorted, made once.
base_world() {
  if [ ! -s "$tmp/base-$1" ]; then
    mkdir -p "$tmp/base-$1.d" && world "$1" . "$tmp/base-$1.d" | jq -S . > "$tmp/base-$1" || return 1
  fi
  cat "$tmp/base-$1"
}

# points_only FILE: FILE is exactly the points line (or, with
# TEST_BEFORE_189=1, empty).
points_only() {
  if [ ! -s "$1" ]; then [ "${TEST_BEFORE_189:-}" = 1 ]; return; fi
  [ "$(grep -c '' "$1")" = 1 ] && grep -qxE "$POINTS" "$1"
}
# GI7 (#2549): loop.sh without the App key's secret says so first, then the points line.
loop_points() {
  [ "$(grep -c '' "$1")" = 2 ] \
    && [ "$(head -n 1 "$1")" = "loop.sh: no OPENWIZ_GITHUB_APP_KEY secret; GitHub as today's account" ] \
    && tail -n 1 "$1" > "$1.points" && points_only "$1.points"
}

# expect NAME STATUS FIXTURE FILTER [VAR=VALUE...] -- ARGS...
# Runs `fleet.sh ARGS` on the fixture changed by FILTER. Stdin is the exact
# stdout expected (STATUS 0), or a fragment of the stderr expected (STATUS 2).
# The case's folder stays as $last for checks on its gh log, and for `again`.
expect() {
  name=$1 want_status=$2 fixture=$3 filter=$4
  shift 4
  want_err=$ERR ERR=''
  if ! selected "$name"; then cat > /dev/null; last=''; return; fi
  take || { cat > /dev/null; last=''; return; }
  cases=$((cases + 1))
  last=$tmp/case-$cases run=1
  mkdir "$last" || { bad "$name" "no case folder"; cat > /dev/null; return; }
  cat > "$last/want" || { bad "$name" "can't read the expected output"; return; }
  world "$fixture" "$filter" "$last" > "$last/world.json" || { bad "$name" "the filter failed"; return; }
  if [ "$filter" != . ]; then
    base_world "$fixture" > "$last/base.json" && jq -S . "$last/world.json" > "$last/changed.json" \
      || { bad "$name" "can't compare the fixture"; return; }
    cmp -s "$last/base.json" "$last/changed.json" && { bad "$name" "the filter changed nothing"; return; }
  fi
  run_case "$FLEET" '' "$@"
}

# again NAME FILTER [VAR=VALUE...] -- ARGS...
# The last case's next check (ClosedWiz#189): `fleet.sh ARGS` in the same
# folder, with the same cache, on the world the last check read changed by
# FILTER ("." for none). Stdin is the exact stdout expected; it exits 0.
again() {
  name=$1 filter=$2
  shift 2
  want_err=$ERR ERR='' fleet=${RUN_FLEET:-$FLEET} RUN_FLEET=''
  if ! selected "$name"; then cat > /dev/null; return; fi
  [ "$mine" = yes ] || { cat > /dev/null; return; }
  cases=$((cases + 1))
  if [ "${run:-0}" = 1 ]; then prev=''; else prev=${run:-0}; fi
  if [ -z "$last" ] || [ ! -s "$last/world$prev.json" ]; then bad "$name" "no check before it"; cat > /dev/null; return; fi
  run=$((run + 1)) want_status=0
  cat > "$last/want$run" || { bad "$name" "can't read the expected output"; return; }
  jq "$LIB $filter" "$last/world$prev.json" > "$last/world$run.json" || { bad "$name" "the filter failed"; return; }
  run_case "$fleet" "$run" "$@"
}

# run_case FLEET N [VAR=VALUE...] -- ARGS...: one run of FLEET in $last, on
# world$N.json, with the case's cache; it writes out$N, err$N and gh$N.log, and
# checks them against $want_status, want$N and $want_err.
run_case() {
  fleet=$1 n=$2
  shift 2
  envs=''
  while [ $# -gt 0 ] && [ "$1" != -- ]; do envs="$envs $1"; shift; done
  [ "${1:-}" = -- ] || { bad "$name" "no -- before the arguments"; return; }
  shift
  lastlog=$last/gh$n.log
  # No configured installation (#2317, Assumption A1): every case reads through
  # the fake gh, whatever the machine's own state holds; a case may set its own.
  # shellcheck disable=SC2086 # $envs is a list of VAR=VALUE words
  (cd "$last" && env PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo OPENWIZ_STATE_DIR="$last/no-installation" \
    FAKE_GH_WORLD="$last/world$n.json" FAKE_GH_LOG="$lastlog" LAUNCH_FLEET_NOW=$NOW \
    LAUNCH_FLEET_CACHE="$last/cache" LAUNCH_FLEET_REVISION="$FIX/revision.sh" $envs /bin/sh "$fleet" "$@" > "$last/out$n" 2> "$last/err$n")
  got_status=$?
  if [ "$got_status" != "$want_status" ]; then
    bad "$name" "exit $got_status, not $want_status; stdout: $(head -c 400 "$last/out$n"); stderr: $(head -c 400 "$last/err$n")"
    return
  fi
  if [ "$want_status" = 0 ]; then
    if [ -n "$want_err" ]; then
      printf '%s\n' "$want_err" > "$last/want-err$n"
      if ! cmp -s "$last/want-err$n" "$last/err$n"; then
        bad "$name" "unexpected stderr:"
        diff -u "$last/want-err$n" "$last/err$n" | sed 's/^/    /'
        return
      fi
    elif ! points_only "$last/err$n"; then
      bad "$name" "stderr is not the points line: $(head -c 400 "$last/err$n")"; return
    fi
    if [ -s "$last/want$n" ]; then printf '%s\n' "$(cat "$last/want$n")" > "$last/want$n.txt"; else : > "$last/want$n.txt"; fi
    if ! cmp -s "$last/want$n.txt" "$last/out$n"; then
      bad "$name" "unexpected output:"
      diff -u "$last/want$n.txt" "$last/out$n" | sed 's/^/    /'
      return
    fi
  else
    [ -s "$last/out$n" ] && { bad "$name" "stdout is not empty: $(head -c 400 "$last/out$n")"; return; }
    grep -qF -- "$(cat "$last/want$n")" "$last/err$n" || { bad "$name" "stderr lacks the reason: $(head -c 400 "$last/err$n")"; return; }
  fi
  echo "ok   $name"
}

# log_has NAME COUNT PATTERN: the last run's gh log has exactly COUNT lines matching PATTERN.
log_has() {
  selected "$1" || return
  [ "$mine" = yes ] || return 0
  count=$(grep -c -- "$3" "$lastlog" 2> /dev/null)
  [ "$count" = "$2" ] || bad "$1" "the gh log has $count lines matching '$3', not $2"
}

# ms: the time now, in milliseconds (in seconds where date has no %N).
ms() { n=$(date +%s%N); case $n in *[!0-9]*) n=$(date +%s)000000000 ;; esac; echo $((n / 1000000)); }
# done_group: a worker records the group it ran, and prints to its stray file again.

done_group() {
  [ "$mine" = yes ] && [ -n "$WORKER" ] || return 0
  printf '%s %s\n' "$took" "$(($(ms) - t0))" >> "$SHARED/times"
  exec >> "$SHARED/stray-$WORKER-$PASS"
  mine=no
}
# ours GROUP: this run's shard runs GROUP (every group, outside TEST_SHARD).
ours() {
  [ -n "$SHARD_K" ] || return 0
  if [ "$1" -le "$SHARD_MAPPED" ]; then [ -e "$SHARED/mine/$1" ]; else [ $((($1 - 1) % SHARD_N + 1)) = "$SHARD_K" ]; fi
}
# take [heavy]: the next group of cases begins; succeeds if this process runs
# it. Outside a worker it always does. A worker runs it only if no worker has
# taken it (an atomic mkdir), and in its heavy pass only a heavy group; it
# prints to the group's own file.
take() {
  grp=$((grp + 1))
  [ -n "$WORKER" ] || return 0
  done_group
  if [ "$PASS" = heavy ] && [ "${1:-}" != heavy ]; then return 1; fi
  ours "$grp" || return 1
  mkdir "$SHARED/claim/$grp" 2> /dev/null || return 1
  mine=yes took=$grp t0=$(ms)
  exec > "$SHARED/out/$grp"
}

# only_reads LOG...: every gh call in these logs was one of fleet.sh's reads.
only_reads() {
  grep -h -v -E '^(repo view|nightly runs branch=[^ ]+|commit comments [0-9a-f]{40}|contents docs/agents/(fleet|triage-labels)\.md|graphql (Specs|Merged) cursor=[0-9a-z]+|graphql Spec number=[0-9]+( size=[0-9]+)?|graphql Singles cursor=[0-9a-z]+|files [0-9]+|refs heads/room/[0-9]+-|graphql (Nodes|Blockers) count=[0-9]+|graphql Writer login=[a-z0-9-]+|graphql Checks oid=[0-9a-f]{40} cursor=[0-9]+|graphql Item number=[0-9]+ size=(2|5)( cursor=[0-9]+)?|issue view [0-9]+ (subIssues|body|number,title,blockedBy)|issues page=[0-9]+|search issues page=[0-9]+|issue comments [0-9]+ page=[0-9]+|detail [0-9]+|dependencies [0-9]+ page=[0-9]+|repo clone|repository|user|installation repositories|sub issues [0-9]+ page=[0-9]+|timeline [0-9]+ page=[0-9]+|(check runs|status) [0-9a-f]{40}|ref heads/[A-Za-z0-9._/-]+)$' "$@" 2> /dev/null \
    | sed 's/^/    /' > "$tmp/odd-calls"
  if [ -s "$tmp/odd-calls" ]; then bad 'only reads' "unexpected gh calls:"; cat "$tmp/odd-calls"; else echo "ok   every gh call was one of fleet.sh's reads"; fi
}

# cpus: nproc, but no more than the container's cgroup v2 cpu.max allows, at
# its own level or any above it (nproc can report more CPUs than the
# container's CPU limit).
cpus() {
  n=$(nproc 2> /dev/null || getconf _NPROCESSORS_ONLN 2> /dev/null) || n=1
  dir=/sys/fs/cgroup$(sed -n 's/^0:://p' /proc/self/cgroup 2> /dev/null)
  while :; do
    if read -r quota period < "${dir%/}/cpu.max" 2> /dev/null; then
      case $quota$period in *[!0-9]*) ;; *) [ "$period" -gt 0 ] && [ $((quota / period)) -lt "$n" ] && n=$((quota / period)) ;; esac
    fi
    case $dir in /sys/fs/cgroup | /sys/fs/cgroup/ | */..* | '') break ;; esac
    dir=${dir%/*}
  done
  case $n in '' | *[!0-9]* | 0) n=1 ;; esac
  echo "$n"
}

# A full run: the workers, then their groups' output in this file's order.
if [ -z "$WORKER" ] && [ -z "${TEST_ONLY:-}" ]; then
  jobs=${TEST_JOBS:-$(cpus)}
  case $jobs in '' | *[!0-9]* | 0) echo "FAIL TEST_JOBS is not a number of workers: $jobs"; exit 1 ;; esac
  mkdir "$tmp/claim" "$tmp/out" || { echo "FAIL setup: the workers' folders"; exit 1; }
  k=0 pids=''
  while [ "$k" -lt "$jobs" ]; do
    k=$((k + 1))
    (export TEST_SHARED="$tmp" TEST_WORKER=$k
      TEST_PASS=heavy /bin/sh "$HERE/${0##*/}" && TEST_PASS=all /bin/sh "$HERE/${0##*/}") &
    pids="$pids $!"
  done
  for pid in $pids; do wait "$pid" || bad 'every worker finished' "a worker exited $?"; done
  groups='' results=0
  for r in "$tmp"/result-*; do
    [ -s "$r" ] || continue
    read -r c f g < "$r" || { bad 'every worker finished' "can't read $r"; continue; }
    results=$((results + 1)) cases=$((cases + c)) fails=$((fails + f))
    [ -z "$groups" ] || [ "$g" = "$groups" ] || bad 'every worker saw every group' "$g groups, not $groups"
    groups=$g
  done
  [ "$results" = $((jobs * 2)) ] || bad 'every worker finished' "$results of $((jobs * 2)) passes"
  i=0
  while [ "$i" -lt "${groups:-0}" ]; do
    i=$((i + 1))
    ours "$i" || continue
    if [ -d "$tmp/claim/$i" ] && [ -f "$tmp/out/$i" ]; then cat "$tmp/out/$i"; else bad "group $i" "no worker ran it"; fi
  done
  for f in "$tmp"/stray-*; do [ ! -s "$f" ] || cat "$f"; done
  # Each group's time, in file order: into TEST_TIMES, or here on GitHub Actions.
  times=${TEST_TIMES:-}
  [ -n "$times" ] || [ "${GITHUB_ACTIONS:-}" != true ] || times=-
  if [ -n "$times" ]; then
    sort -n "$tmp/times" | while read -r g t; do printf 'time %s ms\t%s\n' "$t" "$(head -n 1 "$tmp/out/$g" | cut -c6-)"; done > "$tmp/times.txt"
    if [ "$times" = - ]; then cat "$tmp/times.txt"; else cp "$tmp/times.txt" "$times"; fi
  fi
  only_reads "$tmp"/w*/case-*/gh*.log "$tmp"/w*/cache-*/gh.log "$tmp"/w*/loop/log[0-9]
  if [ -n "$SHARD_K" ]; then
    # The ci job adds up the shards' counts; each shard records its own.
    { printf 'cases %s\ntotal %s\ngroups %s\n' "$cases" "$CASES" "${groups:-0}"
      sort -n "$tmp/times" 2> /dev/null | sed 's/^/group /'; } > "$TEST_SHARD_RAN" \
      || bad 'the shard record' "can't write $TEST_SHARD_RAN"
    echo "shard $SHARD_K of $SHARD_N: $cases of $CASES cases, $(grep -c '^group ' "$TEST_SHARD_RAN") of ${groups:-0} groups"
  else
    [ "$cases" = "$CASES" ] || bad 'every case ran' "$cases cases ran, not $CASES"
  fi
  echo "$jobs workers"
  echo "$cases cases, $fails failed"
  [ "$fails" = 0 ]
  exit
fi

case ${TEST_ONLY:-} in
  "REST cache:"* | "REST parallel:"*) ;;
  *)
### Nightly CI (#257): the script seam, synthetic runs and commit comments

expect 'nightly: a completed failure needs the user' 0 check.json 'nightly' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
log_has 'nightly: a completed failure needs the user' 1 '^nightly runs branch=main$'
log_has 'nightly: a completed failure needs the user' 1 '^commit comments '
expect 'nightly: no run is quiet' 0 check.json . -- check < /dev/null
expect 'nightly: success is quiet' 0 check.json 'nightly | .runs[0].conclusion = "success"' -- check < /dev/null
log_has 'nightly: success is quiet' 0 '^commit comments '
expect 'nightly: a running run is not a completed success' 0 check.json 'nightly | .runs = [(.runs[0] | .id = 802 | .status = "in_progress" | .conclusion = null)] + .runs' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: unrelated runs cannot hide failure' 0 check.json 'nightly | .runs = [(.runs[0] | .id = 805 | .event = "push" | .conclusion = "success"), (.runs[0] | .id = 804 | .head_branch = "other" | .conclusion = "success"), (.runs[0] | .id = 803 | .path = ".github/workflows/other.yml" | .conclusion = "success")] + .runs' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: latest completed success clears an older failure' 0 check.json 'nightly | .runs = [(.runs[0] | .id = 802 | .conclusion = "success")] + .runs' -- check < /dev/null
expect 'nightly: cancelled is quiet' 0 check.json 'nightly | .runs[0].conclusion = "cancelled"' -- check < /dev/null
log_has 'nightly: cancelled is quiet' 0 '^commit comments '
expect 'nightly: skipped is quiet' 0 check.json 'nightly | .runs[0].conclusion = "skipped"' -- check < /dev/null
expect 'nightly: neutral is quiet' 0 check.json 'nightly | .runs[0].conclusion = "neutral"' -- check < /dev/null
expect 'nightly: stale is quiet' 0 check.json 'nightly | .runs[0].conclusion = "stale"' -- check < /dev/null
expect 'nightly: timed out is red' 0 check.json 'nightly | .runs[0].conclusion = "timed_out"' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (timed_out)
EOF
expect 'nightly: startup failure is red' 0 check.json 'nightly | .runs[0].conclusion = "startup_failure"' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (startup_failure)
EOF
expect 'nightly: action required is red' 0 check.json 'nightly | .runs[0].conclusion = "action_required"' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (action_required)
EOF
expect 'nightly: absent workflow preserves other due work' 0 check.json 'merge12' FAKE_GH_NIGHTLY_HTTP=404 -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'nightly: absent workflow preserves other due work' 0 '^commit comments '
expect 'nightly: forbidden fails even when JSON says not found' 2 check.json 'merge12' FAKE_GH_NIGHTLY_HTTP=403 -- check <<EOF
can't read nightly CI runs
EOF
expect 'nightly: server error fails even when JSON says not found' 2 check.json 'merge12' FAKE_GH_NIGHTLY_HTTP=500 -- check <<EOF
can't read nightly CI runs
EOF
expect 'nightly: another default branch is encoded' 0 check.json 'nightly | .default = "stable/next" | .runs[0].head_branch = .default | say(10; 1001; "09:00"; "launch-fleet: look: planned #11 is closed without a verified merge")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
log_has 'nightly: another default branch is encoded' 1 '^nightly runs branch=stable%2Fnext$'
expect 'nightly: delivery recorded on GitHub is quiet without a warm cache' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly told 801 attempt 1")' -- check < /dev/null
expect 'nightly: the record beyond the first page still suppresses delivery' 0 check.json 'nightly | nightly_record(9000; "unrelated") | nightly_record(9001; "launch-fleet: nightly told 801 attempt 1")' FAKE_GH_PAGE=1 -- check < /dev/null
expect 'nightly: another attempt may alert' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly told 801 attempt 1") | .runs[0].run_attempt = 2' -- check <<EOF
nightly red 801 attempt 2 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: another run on the same commit may alert' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly told 800 attempt 1")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: a quotation is not a delivery record' 0 check.json 'nightly | nightly_record(9001; "quoted: launch-fleet: nightly told 801 attempt 1")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: a claim requires reconciliation rather than another send' 0 check.json 'nightly | nightly_record(9002; "launch-fleet: nightly telling 801 attempt 1, thread thr_synsecond") | nightly_record(9001; "launch-fleet: nightly telling 801 attempt 1, thread thr_synfirst")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure); reconcile comment 9001, thread thr_synfirst
EOF
expect 'nightly: delivery wins over an old claim' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly telling 801 attempt 1, thread thr_synfirst") | nightly_record(9002; "launch-fleet: nightly told 801 attempt 1")' -- check < /dev/null
# #484: uncertainty is a settled notification outcome, never proof of delivery.
expect 'nightly: uncertainty recorded on GitHub is quiet without a warm cache' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly uncertain 801 attempt 1")' -- check < /dev/null
expect 'nightly: paginated uncertainty settles even leftover claims' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly telling 801 attempt 1, thread thr_synlater") | nightly_record(9002; "launch-fleet: nightly uncertain 801 attempt 1")' FAKE_GH_PAGE=1 -- check < /dev/null
expect 'nightly: uncertainty for another attempt does not settle this attempt' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly uncertain 801 attempt 1") | .runs[0].run_attempt = 2' -- check <<EOF
nightly red 801 attempt 2 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: uncertainty for another run on the same commit does not settle this run' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly uncertain 800 attempt 1")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: quoted uncertainty does not settle a claim' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly telling 801 attempt 1, thread thr_synfirst") | nightly_record(9002; "quoted: launch-fleet: nightly uncertain 801 attempt 1")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure); reconcile comment 9001, thread thr_synfirst
EOF
expect 'nightly: suffixed uncertainty does not settle a claim' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly telling 801 attempt 1, thread thr_synfirst") | nightly_record(9002; "launch-fleet: nightly uncertain 801 attempt 1 extra")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure); reconcile comment 9001, thread thr_synfirst
EOF
expect 'nightly: uncertainty for attempt ten does not settle attempt one' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly uncertain 801 attempt 10")' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'nightly: frontier does not read runs' 0 check.json 'nightly' FAKE_GH_FAIL=nightly -- frontier < /dev/null
log_has 'nightly: frontier does not read runs' 0 '^nightly runs '
expect 'nightly: holds does not read runs' 0 check.json 'nightly' FAKE_GH_FAIL=nightly -- holds < /dev/null
log_has 'nightly: holds does not read runs' 0 '^nightly runs '
expect 'nightly: claim does not read runs' 0 check.json 'merge12 | nightly | say(13; 1301; "11:55"; "launch-fleet: starting")' FAKE_GH_FAIL=nightly -- claim 13 1301 <<EOF
go #13
EOF
log_has 'nightly: claim does not read runs' 0 '^nightly runs '
expect 'nightly: a failed run read leaves even ticket output empty' 2 check.json 'merge12' FAKE_GH_FAIL=nightly -- check <<EOF
can't read nightly CI runs
EOF
expect 'nightly: a failed record read leaves even ticket output empty' 2 check.json 'merge12 | nightly' FAKE_GH_FAIL=commit_comments -- check <<EOF
can't read nightly CI notification records
EOF
expect 'nightly: malformed run envelope fails closed' 2 check.json '.nightlyResponse = []' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: missing run list fails closed' 2 check.json '.nightlyResponse = {total_count: 0}' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: a positive count with no run fails closed' 2 check.json '.nightlyResponse = {total_count: 1, workflow_runs: []}' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: an unknown conclusion fails closed' 2 check.json 'nightly | .runs[0].conclusion = "new-state"' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: missing attempt fails closed' 2 check.json 'nightly | del(.runs[0].run_attempt)' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: malformed head fails closed' 2 check.json 'nightly | .runs[0].head_sha = "--bad"' -- check <<EOF
invalid nightly CI runs
EOF
expect 'nightly: malformed comment page fails closed' 2 check.json 'nightly | .commitCommentsResponse = {}' -- check <<EOF
invalid nightly CI notification records
EOF
expect 'nightly: malformed comment body fails closed' 2 check.json 'nightly | .commitCommentsResponse = [{id: 9001, commit_id: sha(81), body: null}]' -- check <<EOF
invalid nightly CI notification records
EOF
expect 'nightly: record appears on the next check without changing the cache' 0 check.json 'nightly' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
again 'nightly: the next check reads the new delivery record' 'nightly_record(9001; "launch-fleet: nightly told 801 attempt 1")' -- check < /dev/null

### The check: nothing due, and starts

expect 'quiet: nothing due prints nothing' 0 check.json . -- check < /dev/null
expect 'no command means check' 0 check.json . -- < /dev/null
expect 'GH_REPO unset: the repository comes from the clone' 0 check.json . GH_REPO= -- check < /dev/null
log_has 'GH_REPO unset: the repository comes from the clone' 1 '^repo view$'
expect 'a merge unlocks the ticket waiting on it' 0 check.json 'merge12' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
### KN13 (#1448): a start needs ready-for-agent from a maintainer and no edit since

expect 'KN13: labelled by a record author, unedited: starts as before' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'KN13: labelled by a record author, unedited: starts as before' 0 '^graphql Writer'
expect 'KN13: labelled by the App, which GraphQL names without [bot]: starts' 0 check.json 'merge12 | labelled(13; "09:00"; "synthetic-factory[bot]")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'KN13: edited before a maintainer labelled it: starts' 0 check.json 'merge12 | body_edited(13; "08:30"; outsider) | labelled(13; "09:00"; "Synthetic-Owner")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'KN13: labelled by a non-maintainer: refused, once, naming who must re-approve' 0 check.json 'merge12 | labelled(13; "09:00"; outsider)' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
again 'KN13: the refusal recorded, nothing more' 'say(13; 1301; "11:58"; "launch-fleet: look: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again")' -- check < /dev/null
again 'KN13: a maintainer adds it again: starts' 'labelled(13; "11:59"; "Synthetic-Owner")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'KN13: labelled by a deleted user: refused' 0 check.json 'merge12 | labelled(13; "09:00"; null)' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: labelled by an App that is not a record author: refused' 0 check.json 'merge12 | labelled(13; "09:00"; "other-app[bot]")' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
log_has 'KN13: labelled by an App that is not a record author: refused' 0 '^graphql Writer'
expect 'KN13: the newest labelling counts: a maintainer, then a non-maintainer' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | labelled(13; "10:00"; outsider)' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T10:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: labelled by a collaborator with write access: starts' 0 check.json 'merge12 | labelled(13; "09:00"; "synthetic-writer") | .collaborators = {"synthetic-writer": "WRITE"}' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'KN13: labelled by a collaborator with write access: starts' 1 '^graphql Writer login=synthetic-writer$'
expect 'KN13: labelled by a collaborator with triage access only: refused' 0 check.json 'merge12 | labelled(13; "09:00"; "synthetic-writer") | .collaborators = {"synthetic-writer": "TRIAGE"}' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: write access only for a longer login it matches: refused' 0 check.json 'merge12 | labelled(13; "09:00"; "synthetic-writer") | .collaborators = {"synthetic-writer-2": "ADMIN"}' -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: an unreadable collaborator answer fails closed' 0 check.json 'merge12 | labelled(13; "09:00"; "synthetic-writer") | .collaborators = {"synthetic-writer": "WRITE"}' FAKE_GH_ERRORS=Writer -- check <<EOF
look #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: a blocked ticket labelled by an outsider asks nothing' 0 check.json 'labelled(13; "09:00"; "synthetic-writer")' -- check < /dev/null
log_has 'KN13: a blocked ticket labelled by an outsider asks nothing' 0 '^graphql Writer'
expect 'KN13: edited by someone else after labelling: refused' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | body_edited(13; "10:00"; outsider)' -- check <<EOF
look #13: start refused: the ticket was edited at 2026-11-01T10:00:00Z, after ready-for-agent was added at 2026-11-01T09:00:00Z; a maintainer must add it again
EOF
again 'KN13: a maintainer adds it again after the edit: starts' 'labelled(13; "11:00"; "Synthetic-Owner")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'KN13: any edit after labelling refuses, a maintainer'"'"'s too' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | body_edited(13; "10:00"; "Synthetic-Owner")' -- check <<EOF
look #13: start refused: the ticket was edited at 2026-11-01T10:00:00Z, after ready-for-agent was added at 2026-11-01T09:00:00Z; a maintainer must add it again
EOF
expect 'KN13: the ready label pushed out of the last 20 label events: refused' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | issue(13; .labelEvents += [range(10; 30) | {name: "bug", at: "2026-11-01T10:\(.):00Z"}])' -- check <<EOF
look #13: start refused: who added ready-for-agent can't be read; a maintainer must add it again
EOF
expect 'KN13: the frontier leaves a refused ticket out' 0 check.json 'merge12 | labelled(13; "09:00"; outsider)' -- frontier < /dev/null
expect 'KN13: a wake on a refused ticket refuses it too' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | body_edited(13; "10:00"; outsider)' -- wake 13 <<EOF
look #13: start refused: the ticket was edited at 2026-11-01T10:00:00Z, after ready-for-agent was added at 2026-11-01T09:00:00Z; a maintainer must add it again
EOF
expect 'KN13: a claim on a ticket edited since labelling withdraws' 0 check.json 'merge12 | labelled(13; "09:00"; "Synthetic-Owner") | body_edited(13; "10:00"; outsider) | say(13; 1301; "11:55"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: start refused: the ticket was edited at 2026-11-01T10:00:00Z, after ready-for-agent was added at 2026-11-01T09:00:00Z; a maintainer must add it again
EOF
expect 'KN13: a claim on a ticket labelled by a non-maintainer withdraws' 0 check.json 'merge12 | labelled(13; "09:00"; outsider) | say(13; 1301; "11:55"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF
expect 'KN13: an issue approved on its own needs a maintainer'"'"'s label too' 0 check.json 'own_approval(70; 7001; "10:00") | labelled(70; "09:00"; outsider)' -- check <<EOF
look #70: start refused: ready-for-agent was last added at 2026-11-01T09:00:00Z by someone who is not a maintainer; a maintainer must add it again
EOF

expect 'KN13 R1: edited the same second as the label on an issue approved on its own: refused' 0 check.json 'own_approval(70; 7001; "10:00") | labelled(70; "09:00"; "Synthetic-Owner") | body_edited(70; "09:00"; outsider)' -- check <<EOF
look #70: start refused: the ticket was edited at 2026-11-01T09:00:00Z, the same second ready-for-agent was added, so which came first can't be read; a maintainer must add it again
EOF
expect 'KN13 R1: a claim on an issue edited the same second as its label withdraws' 0 check.json 'own_approval(70; 7001; "10:00") | labelled(70; "09:00"; "Synthetic-Owner") | body_edited(70; "09:00"; outsider) | say(70; 7002; "11:55"; "launch-fleet: starting")' -- claim 70 7002 <<EOF
withdraw #70: start refused: the ticket was edited at 2026-11-01T09:00:00Z, the same second ready-for-agent was added, so which came first can't be read; a maintainer must add it again
EOF

expect 'a claimed start is left alone for 10 minutes' 0 check.json 'merge12 | say(13; 1301; "11:55"; "launch-fleet: starting")' -- check < /dev/null
expect 'a claim with no outcome after 10 minutes is reconciled' 0 check.json 'merge12 | say(13; 1301; "11:45"; "launch-fleet: starting")' -- check <<EOF
reconcile start #13: claimed at 2026-11-01T11:45:00Z, no outcome after 10 minutes
EOF
expect 'a refused start stays queued and is tried again' 0 check.json 'merge12 | say(13; 1301; "11:30"; "launch-fleet: start refused: plan limit reached")' -- check <<EOF
start #13: W3: widget page (spec #10; retry after "start refused: plan limit reached")
EOF
expect 'a reconciled failed start is tried again' 0 check.json 'merge12 | say(13; 1301; "11:30"; "launch-fleet: start failed: no thread found")' -- check <<EOF
start #13: W3: widget page (spec #10; retry after "start failed: no thread found")
EOF
expect 'a start whose branch is up gets checked' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_syn13") | .refs += ["room/13-w3-widget-page-cccc"]' -- check <<EOF
check start #13: thread thr_syn13, branch room/13-w3-widget-page-cccc
EOF
expect 'no branch yet within 30 minutes: wait' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_syn13")' -- check < /dev/null
expect 'a branch for ticket #130 is not #13s' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_syn13") | .refs += ["room/130-other-dddd"]' -- check < /dev/null
expect 'no branch 30 minutes after the start' 0 check.json 'merge12 | say(13; 1301; "11:20"; "launch-fleet: started, thread thr_syn13")' -- check <<EOF
check start #13: thread thr_syn13, no branch 30 minutes after the start
EOF
expect 'two builders recorded: look, and nothing else for it' 0 check.json 'say(12; 1202; "10:00"; "launch-fleet: started, thread thr_syn12b") | pr31' -- check <<EOF
look #12: more than one builder is recorded as started
EOF

### The check: pull requests

expect 'a green head with green CI gets its first review' 0 check.json 'pr31' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
# #2725: GitHub returned truncated display headlines on all three reported
# PRs, while the full subject ended in green. Existing fixtures used the same
# short string for both fields, so they never exercised that distinction.
# Claims: check/spec/wake and claim agree on first review and re-check;
# stale heads, older claims, missing ci and body-only green still refuse.
LONG31='pr31
  | .files["docs/agents/fleet.md"] = "## CI checks\n| `ci` | selected suites | `main` |\n\n## GitHub identity\n\n| Record authors | `synthetic-factory[bot]` |\n"
  | pull(31; .headline = "#12: synthetic widget implementation with checks and a long commit…"
      | .message = "#12: synthetic widget implementation with checks and a long commit subject, green"
      | .checks = [{name: "ci", status: "COMPLETED", conclusion: "SUCCESS"}])'
RECHECK_LONG31="$LONG31
  | pr_say(31; 3101; \"10:30\"; \"launch-fleet: review started \(sha(99)), thread thr_synrev31\")
  | pr_say(31; 3102; \"11:20\"; \"VERDICT: CHANGES at \(sha(99))\")
  | pr_say(31; 3103; \"11:21\"; \"launch-fleet: findings sent \(sha(99))\")"
LONG_CLAIM='pr_say(31; 3105; "11:59"; "launch-fleet: review starting \(sha(31))")'
expect 'review subject: first review without a re-test, spec' 0 check.json "$LONG31" -- spec 10 <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'review subject: first review without a re-test, claim' 0 check.json "$LONG31 | $LONG_CLAIM" -- claim 31 3105 <<EOF
go #31
EOF
expect 'review subject: re-check without a re-test, spec' 0 check.json "$RECHECK_LONG31" -- spec 10 <<EOF
re-check #31 for #12 at $S31: tell its reviewer, thread thr_synrev31
EOF
expect 'review subject: re-check without a re-test, claim' 0 check.json "$RECHECK_LONG31 | $LONG_CLAIM" -- claim 31 3105 <<EOF
go #31
EOF
RETEST_LONG31="$RECHECK_LONG31 | pr_say(31; 3104; \"11:36\"; \"launch-fleet: re-test sent \(sha(31)): synthetic unrelated failure; re-run by reopen\")"
expect 'review subject: re-test without base or run does not hide re-check, check' 0 check.json "$RETEST_LONG31" -- check <<EOF
re-check #31 for #12 at $S31: tell its reviewer, thread thr_synrev31
EOF
expect 'review subject: re-test without base or run does not hide re-check, claim' 0 check.json "$RETEST_LONG31 | $LONG_CLAIM" -- claim 31 3105 <<EOF
go #31
EOF
expect 'review subject: first review without a re-test, wake' 0 check.json "$LONG31" -- wake 31 <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'review subject: moved head still withdraws' 0 check.json "$LONG31 | $LONG_CLAIM | pull(31; .head = sha(99))" -- claim 31 3105 <<EOF
withdraw #31: the head is now $S99
EOF
expect 'review subject: older open claim still withdraws' 0 check.json "$LONG31 | pr_say(31; 3104; \"11:58\"; \"launch-fleet: review starting \(sha(31))\") | $LONG_CLAIM" -- claim 31 3105 <<EOF
withdraw #31: an older review claim: "review starting $S31"
EOF
expect 'review subject: missing ci still withdraws' 0 check.json "$LONG31 | pull(31; .checks = [{name: \"optional\", status: \"COMPLETED\", conclusion: \"SUCCESS\"}]) | $LONG_CLAIM" -- claim 31 3105 <<EOF
withdraw #31: it is not due a review at $S31
EOF
expect 'review subject: green only in the body is still being built' 0 check.json "$LONG31 | pull(31; .message = \"#12: synthetic work in progress\n\nPrevious proof was green\")" -- spec 10 < /dev/null
expect 'review subject: missing full message cannot authorize claim' 0 check.json "$LONG31 | pull(31; .message = null | .headline = \"#12: green\") | $LONG_CLAIM" -- claim 31 3105 <<EOF
withdraw #31: it is not due a review at $S31
EOF
expect 'a head not marked green is still being built' 0 check.json 'open_pr(31; 12; "#12: work in progress")' -- check < /dev/null
expect '"green" must be a word' 0 check.json 'open_pr(31; 12; "#12: evergreen widgets")' -- check < /dev/null
expect 'CI still running: wait' 0 check.json 'pr31 | pull(31; .rollup = "PENDING" | .checks[1].status = "IN_PROGRESS" | .checks[1].conclusion = null)' -- check < /dev/null
expect 'no CI at all: wait' 0 check.json 'pr31 | pull(31; .rollup = null)' -- check < /dev/null
expect 'a required check missing is not green CI' 0 check.json 'pr31 | pull(31; .checks = [.checks[0]])' -- check < /dev/null
expect 'CI failed: tell the builder' 0 check.json 'pr31 | pull(31; .rollup = "FAILURE" | .checks[1].conclusion = "FAILURE")' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'a CI failure already sent is not sent again' 0 check.json 'pr31 | pull(31; .rollup = "FAILURE" | .checks[1].conclusion = "FAILURE") | pr_say(31; 3101; "11:10"; "launch-fleet: CI failure sent \(sha(31))")' -- check < /dev/null
# #2119: synthetic API windows; required names occur only after 40 contexts.
expect 'contexts: overflow reads required checks on the third page' 0 check.json 'pr31 | pull(31; .checks = ([range(40) | {name: "optional-\(.)", status: "COMPLETED", conclusion: "SUCCESS"}] + .checks))' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
# Complete-page and duplicate-attempt regressions use the existing command seam.
# Every optional name, ID, timestamp, page cursor and fault is synthetic.
MANY31='pr31 | pull(31; .checks = ([range(40) | {name: "optional-\(.)", status: "COMPLETED", conclusion: "SUCCESS"}] + .checks))'
PAD31='pr31 | pull(31; .checks += [range(19) | {name: "optional-\(.)", status: "COMPLETED", conclusion: "SUCCESS"}])'
expect 'contexts: wake also completes all check pages' 0 check.json "$MANY31" -- wake 31 <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'contexts: spec check also completes all check pages' 0 check.json "$MANY31" -- spec 10 <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'contexts: latest failure on a later page blocks review' 0 check.json "$PAD31 | pull(31; retry(900; \"COMPLETED\"; \"FAILURE\"))" -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'contexts: queued later attempt cannot borrow earlier success' 0 check.json "$PAD31 | pull(31; retry(900; \"QUEUED\"; null))" -- check < /dev/null
expect 'contexts: newer success supersedes a first-page failure' 0 check.json "$PAD31 | pull(31; .checks[1].conclusion = \"FAILURE\" | retry(900; \"COMPLETED\"; \"SUCCESS\"))" -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'contexts: reversed pages still select the newest failure' 0 check.json "$PAD31 | pull(31; retry(900; \"COMPLETED\"; \"FAILURE\") | .checks |= reverse)" -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'contexts: later legacy failure supersedes success by timestamp' 0 check.json "$PAD31 | pull(31; .checks[1] = {type: \"StatusContext\", context: \"test\", state: \"SUCCESS\", createdAt: at(\"10:00\")} | .checks += [{type: \"StatusContext\", context: \"test\", state: \"ERROR\", createdAt: at(\"11:00\")}])" -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'contexts: missing required name stays pending after pagination' 0 check.json "$MANY31 | pull(31; .checks |= map(select(.name != \"test\")))" -- check < /dev/null
expect 'contexts: complete pages preserve exact-head approval merge' 0 check.json "$MANY31 | pr_say(31; 3102; \"11:30\"; \"VERDICT: APPROVE at \(sha(31))\")" -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'contexts: stale-head approval still requires first review' 0 check.json "$MANY31 | pr_say(31; 3102; \"11:30\"; \"VERDICT: APPROVE at \(sha(99))\")" -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'contexts: later read failure prints no action' 2 check.json "$MANY31" FAKE_GH_FAIL=graphql_Checks -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: later GraphQL error prints no action' 2 check.json "$MANY31" FAKE_GH_ERRORS=Checks -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: missing initial pagination metadata fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"0\": {pageInfo: null}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: missing continuation cursor fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"0\": {pageInfo: {hasNextPage: true, endCursor: null}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: nonboolean continuation flag fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {pageInfo: {hasNextPage: \"false\", endCursor: \"40\"}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: repeated cursor fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {pageInfo: {hasNextPage: true, endCursor: \"20\"}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: count drift fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {totalCount: 43}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: premature final page fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {pageInfo: {hasNextPage: false, endCursor: \"40\"}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: empty intermediate page fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {nodes: []}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: null context fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {nodes: [null]}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: duplicate identity across pages fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"20\": {nodes: [{__typename: \"CheckRun\", id: \"CR_0\", name: \"test\", databaseId: 900, status: \"COMPLETED\", conclusion: \"SUCCESS\"}]}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: missing final page nodes fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"40\": {nodes: null}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: short final page fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"40\": {nodes: []}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: noninteger count fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"0\": {totalCount: 42.5}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: changed commit identity fails closed' 2 check.json "$MANY31 | pull(31; .contextOids = {\"20\": sha(99)})" -- check <<EOF
can't read the issues outside specs
EOF
# Equal timestamps cannot order conflicting legacy attempts; duplicate run IDs
# and an absent cursor on a nonempty final page are inconsistent observations.
expect 'contexts: tied legacy timestamps cannot authorize review' 0 check.json "$PAD31 | pull(31; .checks[1] = {type: \"StatusContext\", context: \"test\", state: \"ERROR\", createdAt: at(\"11:00\")} | .checks += [{type: \"StatusContext\", context: \"test\", state: \"SUCCESS\", createdAt: at(\"11:00\")}])" -- check < /dev/null
expect 'contexts: duplicate attempt identity fails closed' 2 check.json "$PAD31 | pull(31; retry(101; \"COMPLETED\"; \"SUCCESS\"))" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: absent final cursor fails closed' 2 check.json "$MANY31 | pull(31; .contextPages = {\"40\": {pageInfo: {hasNextPage: false, endCursor: null}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts: conflicting snapshots of one PR fail closed' 2 check.json "$MANY31 | .pulls += [(.pulls[] | select(.number == 31) | .head = sha(99))]" -- check <<EOF
can't read the issues outside specs
EOF
# #2119 CI: the hour begins with no contexts before its workflow starts.
expect 'contexts: hourly workflow start supplies valid pending checks' 0 check.json 'pr31 | pull(31; .checks = [] | running_ci)' -- check < /dev/null
# R1: the same PR is observed separately under two approved specs.
TWO_SPECS31='pr31
  | .issues += [{number: 40, title: "Synthetic second spec", state: "OPEN", parent: null,
      labels: [], body: "Synthetic spec", comments: [], blockedBy: []}]
  | ticket(41; "Synthetic second ticket"; ["ready-for-agent"]; []) | issue(41; .parent = 40)
  | approve(40; 4001; "08:00"; 1; [41]) | pull(31; .closes += [41])'
expect 'contexts R1: same-head newer failed attempt is not discarded' 2 check.json "$TWO_SPECS31 | pull(31; .specSnapshots = {\"40\": {checks: (.checks + [{name: \"test\", databaseId: 901, status: \"COMPLETED\", conclusion: \"FAILURE\"}])}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts R1: same-head newer queued attempt is not discarded' 2 check.json "$TWO_SPECS31 | pull(31; .specSnapshots = {\"40\": {checks: (.checks + [{name: \"test\", databaseId: 901, status: \"QUEUED\", conclusion: null}])}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts R1: same-head malformed pagination is not discarded' 2 check.json "$TWO_SPECS31 | pull(31; .specSnapshots = {\"40\": {contextPages: {\"0\": {pageInfo: null}}}})" -- check <<EOF
can't read the issues outside specs
EOF
expect 'contexts R1: identical duplicate snapshots still page successfully' 0 check.json "$TWO_SPECS31 | pull(31; .checks = ([range(40) | {name: \"optional-\(.)\", status: \"COMPLETED\", conclusion: \"SUCCESS\"}] + .checks))" -- check <<EOF
review #31 for #12 at $S31: first review
review #31 for #41 at $S31: first review
EOF
# #923: aggregate rollup state and non-required contexts do not decide CI.
expect 'CI: cancelled non-required check cannot block three required successes' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | .checks += [{name: "changelog", databaseId: 200, status: "COMPLETED", conclusion: "CANCELLED"}])' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: failed non-required check cannot block review' 0 check.json 'ci31 | pull(31; .rollup = "ERROR" | .checks += [{name: "lint", databaseId: 200, status: "COMPLETED", conclusion: "FAILURE"}])' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: superseded required cancellation is green' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | retry(50; "COMPLETED"; "CANCELLED"))' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: superseded required failure is green in reverse context order' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | retry(50; "COMPLETED"; "FAILURE") | .checks |= reverse)' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: recovered head still gets review after builder was notified' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | retry(50; "COMPLETED"; "CANCELLED")) | pr_say(31; 3101; "11:10"; "launch-fleet: CI failure sent \(sha(31))")' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: latest required failure overrides earlier success and green rollup' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "FAILURE") | .checks |= reverse)' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: latest required error fails' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "ERROR"))' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: latest required timeout fails' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "TIMED_OUT"))' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: latest required cancellation fails' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "CANCELLED"))' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: latest required action-needed result fails' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "ACTION_REQUIRED"))' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: latest required run in progress overrides earlier success' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | retry(200; "IN_PROGRESS"; null))' -- check < /dev/null
expect 'CI: latest required queued run overrides earlier success without a start time' 0 check.json 'ci31 | pull(31; retry(200; "QUEUED"; null) | .checks[-1].startedAt = null)' -- check < /dev/null
expect 'CI: latest required unknown result stays pending' 0 check.json 'ci31 | pull(31; retry(200; "COMPLETED"; "UNKNOWN"))' -- check < /dev/null
expect 'CI: missing required check stays pending despite unrelated failure' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | .checks = [.checks[0], {name: "changelog", databaseId: 200, status: "COMPLETED", conclusion: "CANCELLED"}])' -- check < /dev/null
expect 'CI: required failure is reported while another required check runs' 0 check.json 'ci31 | pull(31; .rollup = "PENDING" | .checks[0].conclusion = "FAILURE" | .checks[1].status = "IN_PROGRESS" | .checks[1].conclusion = null)' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CI: pending non-required check cannot block review' 0 check.json 'ci31 | pull(31; .rollup = "PENDING" | .checks += [{name: "lint", databaseId: 200, status: "IN_PROGRESS", conclusion: null}])' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: latest successful legacy status supersedes failure' 0 check.json 'ci31 | pull(31; .rollup = "FAILURE" | .checks |= map(select(.name != "test")) | .checks += [{type: "StatusContext", context: "test", createdAt: at("11:00"), state: "SUCCESS"}, {type: "StatusContext", context: "test", createdAt: at("10:00"), state: "FAILURE"}])' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'CI: latest failed legacy status overrides success' 0 check.json 'ci31 | pull(31; .checks |= map(select(.name != "test")) | .checks += [{type: "StatusContext", context: "test", createdAt: at("10:00"), state: "SUCCESS"}, {type: "StatusContext", context: "test", createdAt: at("11:00"), state: "ERROR"}])' -- check <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'a review started 29 minutes ago: wait' 0 check.json 'pr31 | pr_say(31; 3101; "11:31"; "launch-fleet: review started \(sha(31)), thread thr_synrev31")' -- check < /dev/null
expect 'no verdict 30 minutes after the review started: tell its reviewer again' 0 check.json 'pr31 | pr_say(31; 3101; "11:30"; "launch-fleet: review started \(sha(31)), thread thr_synrev31")' -- check <<EOF
check review #31 for #12 at $S31: no verdict 30 minutes after "review started $S31, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3101)
EOF
expect 'a review started 50 minutes ago with no verdict: tell its reviewer again' 0 check.json 'reviewing31' -- check <<EOF
check review #31 for #12 at $S31: no verdict 30 minutes after "review started $S31, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3101)
EOF
expect 'a re-check sent 29 minutes ago: wait' 0 check.json 'rechecking31("11:31")' -- check < /dev/null
expect 'no verdict 30 minutes after a re-check was sent: tell its reviewer again' 0 check.json 'rechecking31("11:30")' -- check <<EOF
check review #31 for #12 at $S31F: no verdict 30 minutes after "re-check sent $S31F, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3104)
EOF
expect 'told again 29 minutes ago: wait' 0 check.json 'reviewing31 | told31(3102; "11:31"; sha(31); "thr_synrev31")' -- check < /dev/null
expect 'still no verdict 30 minutes after it was told again: archive it and record review failed' 0 check.json 'reviewing31 | told31(3102; "11:30"; sha(31); "thr_synrev31")' -- check <<EOF
check review #31 for #12 at $S31: still no verdict 30 minutes after it was told again; archive thread thr_synrev31 and record review given up (its record: comment 3101)
EOF
expect 'a verdict after it was told again ends the check' 0 check.json 'reviewing31 | pull(31; .comments[0].at = at("10:30")) | told31(3102; "11:00"; sha(31); "thr_synrev31") | pr_say(31; 3103; "11:40"; "VERDICT: CHANGES at \(sha(31))")' -- check <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'told again on an older head does not count for the new head' 0 check.json 'rechecking31("11:20") | told31(3105; "11:15"; sha(31); "thr_synrev31")' -- check <<EOF
check review #31 for #12 at $S31F: no verdict 30 minutes after "re-check sent $S31F, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3104)
EOF
expect 'a quiet reviewer recorded as failed: a fresh reviewer, the one fleet.md names' 0 check.json 'quiet31' -- check <<EOF
review #31 for #12 at $S31: a fresh reviewer (retry after "review failed $S31, thread thr_synrev31: no verdict 30 minutes after it was told again")
EOF
expect 'a quiet re-check recorded as failed: a fresh reviewer, never a re-check to that thread' 0 check.json 'rechecking31("11:00") | pull(31; .comments |= map(if .id == 3104 then .body = "launch-fleet: review failed \(sha("31f")), thread thr_synrev31: thread gone" else . end))' -- check <<EOF
review #31 for #12 at $S31F: a fresh reviewer (retry after "review failed $S31F, thread thr_synrev31: thread gone")
EOF
expect 'the fresh reviewer re-checks the next head, not the failed one' 0 check.json 'quiet31 | pr_say(31; 3103; "11:05"; "launch-fleet: review started \(sha(31)), thread thr_synrev31b") | pr_say(31; 3104; "11:20"; "VERDICT: CHANGES at \(sha(31))") | pr_say(31; 3105; "11:21"; "launch-fleet: findings sent \(sha(31))") | pull(31; .head = sha("31e"))' -- check <<EOF
re-check #31 for #12 at $S31E: tell its reviewer, thread thr_synrev31b
EOF
expect 'the failed reviewer told again does not count for the fresh one' 0 check.json 'quiet31 | pr_say(31; 3103; "11:25"; "launch-fleet: review started \(sha(31)), thread thr_synrev31b")' -- check <<EOF
check review #31 for #12 at $S31: no verdict 30 minutes after "review started $S31, thread thr_synrev31b"; read thread thr_synrev31b and tell it again (its record: comment 3103)
EOF
expect 'a failed claim whose reason names a thread does not retire that reviewer' 0 check.json 'rechecking31("11:00") | pull(31; .comments |= map(if .id == 3104 then .body = "launch-fleet: review failed \(sha("31f")): thread thr_synrev31 never got the message" else . end))' -- check <<EOF
re-check #31 for #12 at $S31F: tell its reviewer, thread thr_synrev31 (retry after "review failed $S31F: thread thr_synrev31 never got the message")
EOF
expect 'a review record that names no thread: look, since its reviewer cannot be checked' 0 check.json 'pr31 | pr_say(31; 3101; "11:00"; "launch-fleet: review started \(sha(31))")' -- check <<EOF
look #31: thread discovery is out of reach
EOF
expect 'a review claim with no outcome after 10 minutes is reconciled' 0 check.json 'pr31 | pr_say(31; 3101; "11:40"; "launch-fleet: review starting \(sha(31))")' -- check <<EOF
reconcile review #31 for #12 at $S31: claimed at 2026-11-01T11:40:00Z, no outcome after 10 minutes
EOF
expect 'a refused review is tried again, never with another model' 0 check.json 'pr31 | pr_say(31; 3101; "11:10"; "launch-fleet: review refused \(sha(31)): model at capacity")' -- check <<EOF
review #31 for #12 at $S31: first review (retry after "review refused $S31: model at capacity")
EOF
expect 'CHANGES on this head: findings to the builder' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: CHANGES at \(sha(31))\n\nFull review by a synthetic reviewer.\n\n- **R1 [medium]** a finding")' -- check <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'findings already sent: wait for a new head' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: CHANGES at \(sha(31))") | pr_say(31; 3103; "11:35"; "launch-fleet: findings sent \(sha(31))")' -- check < /dev/null
expect 'a new green head after a review: re-check by the same reviewer' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: CHANGES at \(sha(31))") | pr_say(31; 3103; "11:35"; "launch-fleet: findings sent \(sha(31))") | pull(31; .head = ("31f" * 40)[:40])' -- check <<EOF
re-check #31 for #12 at $S31F: tell its reviewer, thread thr_synrev31
EOF
expect 'APPROVE on this head with green CI: merge' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))\n\nRe-check 1 of R1, by a synthetic reviewer.")' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'an APPROVE for an older head does not merge the new one' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))") | pull(31; .head = ("31f" * 40)[:40])' -- check <<EOF
re-check #31 for #12 at $S31F: tell its reviewer, thread thr_synrev31
EOF
expect 'only the latest VERDICT counts: a later one on an older commit is no verdict on the head' 0 check.json 'reviewing31 | pull(31; .head = ("31f" * 40)[:40]) | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(("31f" * 40)[:40])") | pr_say(31; 3103; "11:40"; "VERDICT: CHANGES at \(sha(31))")' -- check <<EOF
re-check #31 for #12 at $S31F: tell its reviewer, thread thr_synrev31
EOF
expect 'APPROVE, then a later CHANGES on the same head: the latest counts' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:40"; "VERDICT: CHANGES at \(sha(31))")' -- check <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'a VERDICT with a short commit is no verdict: look' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at 3131313")' -- check <<EOF
look #31: its latest VERDICT line is not "VERDICT: APPROVE|CHANGES at <the full commit>"
EOF
expect 'a VERDICT that names no commit is no verdict: look' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE")' -- check <<EOF
look #31: its latest VERDICT line is not "VERDICT: APPROVE|CHANGES at <the full commit>"
EOF
expect 'a verdict not at the very start of its comment is not a report' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "Looks good.\nVERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:31"; "**APPROVE** at \(sha(31))")' -- check <<EOF
check review #31 for #12 at $S31: no verdict 30 minutes after "review started $S31, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3101)
EOF
expect 'a merge recorded as blocked: wait' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:40"; "launch-fleet: merge blocked \(sha(31)): main moved")' -- check < /dev/null
### The re-test guard (K9, #337): under M1, CI runs again when main changed,
### since the main its CI provably tested, a file the pull request changed, or a
### test on one side and code on the other; any other move merges.

expect 'K9: two pull requests change the same file: the second is re-tested before it merges' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
log_has 'K9: two pull requests change the same file: the second is re-tested before it merges' 1 '^files 31$'
again 'K9: the re-test claimed, its new run not there yet: wait' 'pr_say(31; 3103; "11:50"; "launch-fleet: re-test starting \(sha(31))")' -- check < /dev/null
again 'K9: the re-test running, the base it tests recorded: wait' 'pr_edit(31; 3103; "11:52"; "launch-fleet: re-test sent \(sha(31)) on \(sha("24ec")) in run 901: src/store/store.rs in #24") | pull(31; .rollup = "PENDING" | .checks += [{name: "build", status: "IN_PROGRESS", conclusion: null, run: at("11:51"), runId: 901}, {name: "test", status: "QUEUED", conclusion: null, run: at("11:51"), runId: 901}])' -- check < /dev/null
again 'K9: the re-test green, on a main with the clash in it: merge' 'pull(31; .rollup = "SUCCESS" | .checks = green + [run_in("build"; "11:51"; "SUCCESS"; 901), run_in("test"; "11:51"; "SUCCESS"; 901)])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: reopened by hand, with no record of the base it tested: no credit, re-test (#258: a reopen can reuse an old merge commit)' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pull(31; .checks += [run_at("build"; "11:20"; "SUCCESS"), run_at("test"; "11:20"; "SUCCESS")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: the re-test tested a main from before the clash: tell its builder to merge main in' 0 check.json 'store31 | merged_pr(23; 99; "11:10"; [changed("README.md"; "modified")]) | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("23ec")) in run 901: src/store/store.rs in #24") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)])' -- check <<EOF
merge main in #31 for #12 at $S31: its re-test ran on main at $(sha 23ec), without src/store/store.rs in #24; tell its builder to merge main in
EOF
expect 'K9: the builder already asked to merge main in: wait' 0 check.json 'store31 | merged_pr(23; 99; "11:10"; [changed("README.md"; "modified")]) | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("23ec")) in run 901: src/store/store.rs in #24") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)]) | pr_say(31; 3104; "11:40"; "launch-fleet: merge main asked \(sha(31))")' -- check < /dev/null
expect 'K9: a clash merged after the re-test'"'"'s reopen: re-test again' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("24ec")) in run 901: src/store/store.rs in #24") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)]) | merged_pr(25; 99; "11:30"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #25 after 2026-11-01T11:15:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: a re-test record naming a base main never merged: no credit' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha(77)) in run 901: synthetic") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: a re-test that ran but never recorded its base: re-test again, never silence' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:10"; "launch-fleet: re-test starting \(sha(31))") | pull(31; .checks += [run_at("build"; "11:11"; "SUCCESS"), run_at("test"; "11:11"; "SUCCESS")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: a re-test record with a short base: no credit, re-test again' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on 24ec24e in run 901: src/store/store.rs in #24") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: checks from two runs after the claim: the recorded base is credited to neither' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("24ec")) in run 901: synthetic") | pull(31; .checks = [run_in("build"; "11:22"; "SUCCESS"; 902), run_in("test"; "11:21"; "SUCCESS"; 901)])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: a re-test record that names no run: no credit' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("24ec")): synthetic") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: closed by its re-test and never reopened: reopen it' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test starting \(sha(31))") | pull(31; .state = "CLOSED" | .closedAt = at("11:20"))' -- check <<EOF
reopen #31 for #12 at $S31: closed by its re-test (comment 3103) and not reopened; reopen it
EOF
expect 'K9: a completed re-test, then closed on purpose: left alone' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test sent \(sha(31)) on \(sha("24ec")) in run 901: synthetic") | pull(31; .checks += [run_in("build"; "11:21"; "SUCCESS"; 901), run_in("test"; "11:21"; "SUCCESS"; 901)] | .state = "CLOSED" | .closedAt = at("11:50"))' -- check < /dev/null
expect 'K9: closed long after an unfinished re-test claim: left alone' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test starting \(sha(31))") | pull(31; .state = "CLOSED" | .closedAt = at("11:40"))' -- check < /dev/null
expect 'K9: closed before its re-test claim: left alone' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test starting \(sha(31))") | pull(31; .state = "CLOSED" | .closedAt = at("11:10"))' -- check < /dev/null
expect 'K9: closed after a re-test claim for another head: left alone' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:20"; "launch-fleet: re-test starting \(sha(32))") | pull(31; .state = "CLOSED" | .closedAt = at("11:21"))' -- check < /dev/null
expect 'K9: a re-test claimed over 30 minutes ago, and still no new run: re-test again' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:16"; "launch-fleet: re-test starting \(sha(31))")' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main (again: no new run 30 minutes after it was claimed)
EOF
expect 'K9: a re-test claim for another head does not count' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pr_say(31; 3103; "11:50"; "launch-fleet: re-test starting \(sha(32))")' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: main moved only in files the pull request did not change: merge without a re-test' 0 check.json 'store31 | main24("11:15"; [changed("README.md"; "modified"), changed("src/page/page.rs"; "added")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: the same file, merged before the head was committed: merge' 0 check.json 'store31 | main24("10:29"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: the same file, merged in the minute the head was committed: re-test, as in doubt' 0 check.json 'store31 | main24("10:30"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: the same file, merged into another branch: merge' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | pull(24; .base = "release-1")' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: main renamed a file the pull request changed: re-test' 0 check.json 'store31 | main24("11:15"; [{filename: "src/store/kept.rs", status: "renamed", previous_filename: "src/store/store.rs"}])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: the pull request renamed a file main changed: re-test' 0 check.json 'store31 | pull(31; .files = [{filename: "src/store/widgets.rs", status: "renamed", previous_filename: "src/model/widget.rs"}]) | main24("11:15"; [changed("src/model/widget.rs"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/model/widget.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: two merges since, each named' 0 check.json 'store31 | pull(31; .files += [changed("src/store/index.rs"; "added")]) | main24("11:15"; [changed("src/store/store.rs"; "modified")]) | merged_pr(25; 99; "11:20"; [changed("src/store/index.rs"; "added"), changed("README.md"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24; src/store/index.rs in #25 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: the pull request changes a test, main changed code it may read (the #326 shape): re-test' 0 check.json 'store31 | pull(31; .files = [changed("tests/fleet/a4_allowlist.rs"; "modified")]) | main24("11:15"; [changed("crates/adapters/github/src/tickets.rs"; "modified"), changed("docs/notes.md"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed crates/adapters/github/src/tickets.rs in #24 (its tests may read them) after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: main changed a test, the pull request changes code it may read: re-test' 0 check.json 'store31 | main24("11:15"; [changed("tests/store.rs"; "modified"), changed("src/model/widget.rs"; "modified")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed tests/store.rs in #24 (tests that may read its files) after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: every shape of test file counts' 0 check.json 'store31 | main24("11:15"; [changed("apps/web/test/a.mjs"; "added"), changed("skills/x/scripts/test.sh"; "modified"), changed("src/a_test.go"; "added"), changed("web/a.test.ts"; "added"), changed("web/a.spec.ts"; "added"), changed("src/attest.rs"; "added")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed apps/web/test/a.mjs, skills/x/scripts/test.sh, src/a_test.go, web/a.spec.ts, web/a.test.ts in #24 (tests that may read its files) after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: test fixtures and other test layouts count as tests' 0 check.json 'store31 | main24("11:15"; [changed("skills/x/scripts/fixtures/gh.sh"; "modified"), changed("src/test_store.py"; "added"), changed("web/__tests__/a.js"; "added"), changed("spec/store_spec.rb"; "added"), changed("lib/store_spec.rb"; "added")])' -- check <<EOF
re-test #31 for #12 at $S31: main changed lib/store_spec.rb, skills/x/scripts/fixtures/gh.sh, spec/store_spec.rb, src/test_store.py, web/__tests__/a.js in #24 (tests that may read its files) after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: names like a test that are not one: merge' 0 check.json 'store31 | main24("11:15"; [changed("src/attest.rs"; "added"), changed("src/contest/a.rs"; "added"), changed("src/latest_test_data.rs"; "added"), changed("testing.md"; "added")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: the pull request changes tests, main changed only docs: merge' 0 check.json 'store31 | pull(31; .files = [changed("tests/store.rs"; "modified")]) | main24("11:15"; [changed("docs/guide.md"; "modified"), changed("README.md"; "modified")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: main changed tests, the pull request changes only docs: merge' 0 check.json 'store31 | pull(31; .files = [changed("docs/store.md"; "modified")]) | main24("11:15"; [changed("tests/store.rs"; "modified")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'K9: a required check with no run time: look, never a merge' 0 check.json 'store31 | pull(31; .checks |= map(del(.run)))' -- check <<EOF
look #31: a required check on its head names no workflow run, so main's moves since its CI can't be checked
EOF
expect 'K9: a head with no commit time: look, never a merge' 0 check.json 'store31 | pull(31; del(.committed))' -- check <<EOF
look #31: its head has no commit time, so main's moves since its CI can't be checked
EOF
expect 'K9: the pull request'"'"'s files can'"'"'t be read: stop' 2 check.json 'store31' FAKE_GH_FAIL=files_31 -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a file without a string name in the pull request'"'"'s files: stop' 2 check.json 'store31 | pull(31; .files += [{filename: 5, status: "added"}])' -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a renamed file whose old name is not a string: stop' 2 check.json 'store31 | pull(31; .files += [{filename: "src/a.rs", status: "renamed", previous_filename: ["src/b.rs"]}])' -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a file without a string name in a merge'"'"'s files: stop' 2 check.json 'store31 | main24("11:15"; [{filename: null, status: "modified"}])' -- check <<EOF
can't read the files of #24
EOF
expect 'K9: a file entry that is not an object: stop' 2 check.json 'store31 | pull(31; .files += ["src/a.rs"])' -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a rename without its old name: stop' 2 check.json 'store31 | pull(31; .files = [{filename: "src/store/new.rs", status: "renamed"}]) | main24("11:15"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a file with an unknown status: stop' 2 check.json 'store31 | pull(31; .files += [{filename: "src/a.rs", status: "moved"}])' -- check <<EOF
can't read the files of #31
EOF
expect 'K9: a merge'"'"'s rename without its old name: stop' 2 check.json 'store31 | main24("11:15"; [{filename: "src/store/kept.rs", status: "renamed", previous_filename: ""}])' -- check <<EOF
can't read the files of #24
EOF
expect 'K9: a merge'"'"'s files, read fresh and cached' 0 check.json 'store31 | main24("11:15"; [{filename: "src/store/kept.rs", status: "renamed", previous_filename: "src/store/store.rs"}])' -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
# An entry cached before the rename rule, without its old name: never trusted.
[ -z "$last" ] || printf '%s\n' '[{"filename":"src/store/kept.rs","status":"renamed","previous_filename":null}]' \
  > "$last/cache/synthetic-owner/synthetic-repo/pull-24-files.json"
again 'K9: an obsolete cached file list is read again, never trusted' . -- check <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
log_has 'K9: an obsolete cached file list is read again, never trusted' 1 '^files 24$'
expect 'K9: a pull request not yet approved reads no files' 0 check.json 'pr31 | pull(31; .files = [changed("src/store/store.rs"; "modified")]) | main24("11:15"; [changed("src/store/store.rs"; "modified")])' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
log_has 'K9: a pull request not yet approved reads no files' 0 '^files 31$'
expect 'K9: a wake re-tests too' 0 check.json 'store31 | main24("11:15"; [changed("src/store/store.rs"; "modified")])' -- wake 31 <<EOF
re-test #31 for #12 at $S31: main changed src/store/store.rs in #24 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: two approved pull requests change the same file at once: only the first merges' 0 check.json 'store31 | open_pr(32; 13; "#13: widget page, green") | pr_say(32; 3201; "11:10"; "launch-fleet: review started \(sha(32)), thread thr_synrev32") | pr_say(32; 3202; "11:30"; "VERDICT: APPROVE at \(sha(32))") | pull(32; .files = [changed("src/store/store.rs"; "modified"), changed("src/page/page.rs"; "added")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
again 'K9: the first merged: the second is re-tested before it merges' 'pull(31; .state = "MERGED" | .mergedAt = at("11:55") | .updatedAt = at("11:55") | .mergeCommit = sha("31ec")) | issue(12; .state = "CLOSED")' -- check <<EOF
archive #12: closed; archive thr_syn12, thr_synrev31
re-test #32 for #13 at $(sha 32): main changed src/store/store.rs in #31 after 2026-11-01T10:30:00Z, which its CI may not have tested; run its CI again on the latest main
EOF
expect 'K9: two approved at once, one with tests and one with code: only the first merges' 0 check.json 'store31 | open_pr(32; 13; "#13: widget page, green") | pr_say(32; 3201; "11:10"; "launch-fleet: review started \(sha(32)), thread thr_synrev32") | pr_say(32; 3202; "11:30"; "VERDICT: APPROVE at \(sha(32))") | pull(32; .files = [changed("tests/page.rs"; "added")])' -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'a draft is left alone' 0 check.json 'pr31 | pull(31; .draft = true)' -- check < /dev/null
expect 'a pull request to another base: look' 0 check.json 'pr31 | pull(31; .base = "release-1")' -- check <<EOF
look #31: its base is release-1, not main
EOF
expect 'two open pull requests for one ticket: look' 0 check.json 'pr31 | open_pr(32; 12; "#12: green")' -- check <<EOF
look #12: more than one open pull request: #31, #32
EOF

### Waiting builders (#467)

WAIT12='say(12; 1202; "11:00"; "Orchestrator (PC, ops): **wait for #71.** Once it merges, merge main and rerun the full set.")'
MERGE71='closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])'
expect 'stall: a legacy wait gets its builder resumed after a verified merge' 0 check.json "$WAIT12 | $MERGE71" -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF

expect 'R1: yes wait without a period resumes' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator (PC, ops): **yes, wait for #71** (PR #72). Once it merges, merge main and rerun the full set.") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
expect 'R1: confirmed wait with a period resumes on a targeted wake' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator (PC, ops): **confirmed: wait for #71.** Once it merges, continue.") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- wake 12 <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
expect 'R1: a plain bold wait without a period resumes' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator: **wait for #71** Once it merges, continue.") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
expect 'R1: an unknown lead-in is not a wait instruction' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator (PC, ops): **do not wait for #71.**") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- check < /dev/null
expect 'R1: free-form prose alone is not a wait instruction' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator (PC, ops): **yes (Q6).** Once #71 has a verified merge, continue.") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- check < /dev/null
expect 'R1: a structured record covers a free-form orchestrator answer' 0 check.json 'say(12; 1202; "11:00"; "Orchestrator (PC, ops): **yes (Q6).** Once #71 has a verified merge, continue.") | say(12; 1203; "11:00"; "launch-fleet: waiting for #71") | closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])' -- wake 12 <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1203)
EOF

expect 'stall: targeted wake resumes the same legacy waiter' 0 check.json "$WAIT12 | $MERGE71" -- wake 12 <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
expect 'stall: a structured wait resumes a standalone builder' 0 check.json 'own_approval(70; 7002; "10:00") | say(70; 7003; "10:01"; "launch-fleet: start checked, thread thr_syn70, branch room/70-link") | say(70; 7004; "11:00"; "launch-fleet: waiting for #11")' -- wake 70 <<EOF
resume #70: #11 merged; tell its builder, thread thr_syn70 (wait comment 7004)
EOF
expect 'stall: an open blocker keeps its builder waiting' 0 check.json "$WAIT12 | $MERGE71 | issue(71; .state = \"OPEN\")" -- check < /dev/null
expect 'stall: a closed blocker without a merge keeps its builder waiting' 0 check.json "$WAIT12 | closed_single(71; \"11:30\")" -- check < /dev/null
expect 'stall: a blocker merged to another base keeps its builder waiting' 0 check.json "$WAIT12 | $MERGE71 | pull(72; .base = \"release-1\")" -- check < /dev/null
expect 'stall: missing blocker data cannot resume a builder' 0 check.json "$WAIT12" -- wake 12 < /dev/null
expect 'stall: delivery suppresses a repeated resume' 0 check.json "$WAIT12 | $MERGE71 | say(12; 1203; \"11:45\"; \"launch-fleet: resume sent 1202 for #71\")" -- check < /dev/null
expect 'stall: a later wait replaces the previous blocker' 0 check.json "$WAIT12 | $MERGE71 | say(12; 1203; \"11:45\"; \"launch-fleet: waiting for #13\")" -- check < /dev/null
expect 'stall: waiting again after delivery gets a new notification' 0 check.json "$WAIT12 | $MERGE71 | say(12; 1203; \"11:45\"; \"launch-fleet: resume sent 1202 for #71\") | say(12; 1204; \"11:46\"; \"launch-fleet: waiting for #71\")" -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1204)
EOF
expect 'stall: a wait never starts a second builder' 0 check.json "$WAIT12 | $MERGE71" -- frontier < /dev/null
expect 'stall: a wait without an existing builder starts nothing early' 0 check.json 'say(13; 1301; "11:00"; "launch-fleet: waiting for #11")' -- wake 13 < /dev/null
expect 'stall: arbitrary prose quoting a wait is not a wait instruction' 0 check.json 'say(12; 1202; "11:00"; "A report said wait for #11; this is not an instruction.")' -- check < /dev/null
expect 'stall: unreadable waiter comments produce a look rather than resume' 0 check.json "$WAIT12 | $MERGE71" FAKE_GH_FAIL=issue_comments_12_page=1 -- wake 12 <<EOF
look #12: comment history could not be read in full
EOF
expect 'stall: an unrelated targeted wake leaves the waiter for the safety net' 0 check.json "$WAIT12 | $MERGE71" -- wake 71 < /dev/null
expect 'stall: every existing builder waiting on a merge gets a line' 0 check.json "$WAIT12 | $MERGE71 | say(13; 1301; \"11:01\"; \"launch-fleet: start checked, thread thr_syn13, branch room/13-page\") | say(13; 1302; \"11:02\"; \"launch-fleet: waiting for #71\")" -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
resume #13: #71 merged; tell its builder, thread thr_syn13 (wait comment 1302)
EOF
expect 'stall: blocker read failure fails closed' 2 check.json "$WAIT12 | $MERGE71" FAKE_GH_FAIL=graphql_Item_number=71 -- wake 12 <<EOF
the GitHub query Item failed
EOF

expect 'stall: a claimed resume cannot be delivered by a second tick' 0 check.json "$WAIT12 | $MERGE71 | say(12; 1203; \"11:59\"; \"launch-fleet: resume starting 1202 for #71, thread thr_syntick1\")" -- wake 12 < /dev/null
expect 'stall: a truncated blocker read leaves unrelated work due' 0 check.json "$WAIT12 | $MERGE71 | issue(71; .linkedPrsTruncated = true) | own_approval(70; 7002; \"10:00\")" -- check <<EOF
look #12: waited-on #71 has more than 5 linked pull requests
start #70: Fix the broken link in the widget docs (approved on its own)
EOF

CLAIM12="$WAIT12 | $MERGE71 | say(12; 1203; \"11:59\"; \"launch-fleet: resume starting 1202 for #71, thread thr_syntick1\")"
expect 'stall: oldest resume claim may deliver' 0 check.json "$CLAIM12" -- claim 12 1203 <<EOF
go #12
EOF
expect 'stall: incomplete spec facts withdraw a resume claim' 0 check.json "$CLAIM12 | reduce range(100; 201) as \$n (.; ticket(\$n; \"Synthetic ticket\"; [\"ready-for-agent\"]; []))" -- claim 12 1203 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: unreadable spec approvals withdraw a resume claim' 0 check.json "$CLAIM12 | issue(10; .commentsTruncated = true)" FAKE_GH_FAIL=issue_comments_10_page=1 -- claim 12 1203 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: recovered spec history permits a resume claim' 0 check.json "$CLAIM12 | issue(10; .commentsTruncated = true)" -- claim 12 1203 <<EOF
go #12
EOF
expect 'stall: a truncated blocker withdraws a resume claim' 0 check.json "$CLAIM12 | issue(71; .linkedPrsTruncated = true)" -- claim 12 1203 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: second resume claim withdraws' 0 check.json "$CLAIM12 | say(12; 1204; \"11:59\"; \"launch-fleet: resume starting 1202 for #71, thread thr_syntick2\")" -- claim 12 1204 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: a stale resume claim is reconciled instead of blindly delivered' 0 check.json "$WAIT12 | $MERGE71 | say(12; 1203; \"11:49\"; \"launch-fleet: resume starting 1202 for #71, thread thr_syntick1\")" -- wake 12 <<EOF
reconcile resume #12: wait comment 1202 for #71; reconcile comment 1203, thread thr_syntick1
EOF
expect 'stall: completed claim suppresses its resume' 0 check.json "$CLAIM12 | edit(12; 1203; \"11:59\"; \"launch-fleet: resume sent 1202 for #71\")" -- wake 12 < /dev/null
expect 'stall: failed delivery releases its claim for retry' 0 check.json "$CLAIM12 | edit(12; 1203; \"11:59\"; \"launch-fleet: resume failed 1202 for #71: no delivery\")" -- wake 12 <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
expect 'stall: superseded wait withdraws the old resume claim' 0 check.json "$CLAIM12 | say(12; 1204; \"11:59\"; \"launch-fleet: waiting for #13\")" -- claim 12 1203 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: unmerged blocker withdraws a resume claim' 0 check.json "$CLAIM12 | issue(71; .state = \"OPEN\")" -- claim 12 1203 <<EOF
withdraw #12: that resume is not due or an older claim holds it
EOF
expect 'stall: a PR number cannot be treated as a waited-on ticket' 0 check.json 'say(12; 1202; "11:00"; "launch-fleet: waiting for #21")' -- wake 12 < /dev/null
expect 'stall: a noted truncated blocker stays quiet without hiding unrelated work' 0 check.json "$WAIT12 | $MERGE71 | issue(71; .linkedPrsTruncated = true) | say(12; 1203; \"11:45\"; \"launch-fleet: look: waited-on #71 has more than 5 linked pull requests\") | own_approval(70; 7002; \"10:00\")" -- check <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'stall: semicolon detail in a reopen record also retries' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:40"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:41"; "launch-fleet: merge blocked \(sha(31)): base moved, reopened for fresh CI; verify the approval again before merging.")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF

### The check: archive, needs-info

expect 'a closed ticket gets its builder and reviewer archived' 0 check.json 'issue(12; .state = "CLOSED") | merged_pr(22; 12; "11:00"; []) | pr_say(22; 2201; "10:30"; "launch-fleet: review started \(sha(22)), thread thr_synrev22")' -- check <<EOF
archive #12: closed; archive thr_syn12, thr_synrev22
start #13: W3: widget page (spec #10)
EOF
expect 'a failed reviewer'"'"'s thread is still archived when its ticket closes' 0 check.json 'issue(12; .state = "CLOSED") | merged_pr(22; 12; "11:00"; []) | pr_say(22; 2201; "10:00"; "launch-fleet: review failed \(sha(22)), thread thr_synrev22a: no verdict 30 minutes after it was told again") | pr_say(22; 2202; "10:30"; "launch-fleet: review started \(sha(22)), thread thr_synrev22b")' -- check <<EOF
archive #12: closed; archive thr_syn12, thr_synrev22a, thr_synrev22b
start #13: W3: widget page (spec #10)
EOF
expect 'needs-info: the question goes to the orchestrator' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "Which store should W2 use?")' -- check <<EOF
needs-info #12: a question for the orchestrator
EOF
expect 'needs-info already asked: quiet' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "Which store?") | say(12; 1203; "11:05"; "launch-fleet: asked the orchestrator")' -- check < /dev/null
expect 'F4: a self-grant record answers the question' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "May I read the issue timeline?") | say(12; 1203; "11:05"; "launch-fleet: granted read route: the issue timeline, under the API rules")' -- check < /dev/null
# R2 (review of #1353): the claim, the gate every builder start passes, reads
# every open ready ticket in the repository and refuses a start whose owned
# paths collide with one running, or claimed by an older claim.
OWN13='def own($n; $p): issue($n; .body = "## Owned paths\n\n- `\($p)`\n\n**Relies on:** nothing\n");
  def claim13: merge12 | own(13; "src/page/") | say(13; 1301; "11:55"; "launch-fleet: starting");
  def other_spec: .issues += [{number: 80, title: "Synthetic spec: other", state: "OPEN", parent: null, labels: [], blockedBy: [], body: "The spec.", comments: []},
    {number: 81, title: "X1: other page work", state: "OPEN", parent: 80, labels: ["ready-for-agent"], blockedBy: [],
     body: "## Owned paths\n\n- `src/page/index.md`\n", comments: [{id: 8101, at: at("11:00"), body: "launch-fleet: started"}]}];'
expect 'F6 claim: no collider, go' 0 check.json "$OWN13"' claim13' -- claim 13 1301 <<EOF
go #13
EOF
expect 'F6 claim: a running ticket outside the spec on the same paths withdraws' 0 check.json "$OWN13"' claim13 | own(70; "src/") | say(70; 7005; "11:00"; "launch-fleet: started")' -- claim 13 1301 <<EOF
withdraw #13: its owned paths collide with #70, which is running or claimed first
EOF
expect 'F6 claim: a running ticket of another spec on the same paths withdraws' 0 check.json "$OWN13"' claim13 | other_spec' -- claim 13 1301 <<EOF
withdraw #13: its owned paths collide with #81, which is running or claimed first
EOF
expect 'F6 claim: an older colliding claim wins' 0 check.json "$OWN13"' claim13 | own(70; "src/page/a.md") | say(70; 1300; "11:50"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: its owned paths collide with #70, which is running or claimed first
EOF
expect 'F6 claim: a newer colliding claim loses' 0 check.json "$OWN13"' claim13 | own(70; "src/page/a.md") | say(70; 1302; "11:56"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
go #13
EOF
expect 'needs-info: a new question after the last one was asked' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "Which store?") | say(12; 1203; "11:05"; "launch-fleet: asked the orchestrator") | say(12; 1204; "11:30"; "And one more thing?")' -- check <<EOF
needs-info #12: a question for the orchestrator
EOF

### Contract changes and existing holds

# #565: historical plan-graph headings, on synthetic ticket bodies only.
expect 'legacy Relies on: notes builders without holding unstarted tickets' 0 check.json 'issue(12; .body = "## Relies on\n\n`contracts/widget.v1.md`\n\n## Proof\nSynthetic proof.") | issue(13; .body = "## Relies on\n\n`contracts/widget.v1.md`\n\n## Acceptance criteria\nSynthetic criterion.") | contract23' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'legacy Relies on: check starts the ready ticket after a contract change' 0 check.json 'merge12 | issue(13; .body = "## Relies on\n\n`contracts/widget.v1.md`\n") | contract23' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'legacy Relies on: a targeted wake starts the ready ticket' 0 check.json 'merge12 | issue(13; .body = "## Relies on\n\n`contracts/widget.v1.md`\n") | contract23' -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'legacy Relies on: every file across lines and CRLF is read' 0 check.json 'issue(13; .body = "## Relies on\r\n\r\n- `contracts/widget.v1.md`\r\n- `contracts/other.v1.md`, `contracts/widget.v1.md`\r\n\r\n## Proof\r\n`contracts/unrelated.v1.md`") | m23([changed("contracts/widget.v1.md"; "modified"), changed("contracts/other.v1.md"; "modified"), changed("contracts/unrelated.v1.md"; "modified")]) | say(13; 1301; "10:50"; "launch-fleet: start checked, thread thr_syn13, branch room/13-widget-cccc")' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
note #13: contracts/other.v1.md, contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn13
EOF
expect 'legacy Relies on: unrelated sections and similar headings add no contracts' 0 check.json 'issue(12; .body = "## Owned paths\n`contracts/widget.v1.md`\n\n## Relies on elsewhere\n`contracts/widget.v1.md`\n\n## Relies on\n\nnothing\n\n## Proof\n`contracts/widget.v1.md`") | issue(13; .body = "## Relies on\n\nnothing\n\n### Proof\n`contracts/widget.v1.md`") | contract23' -- holds < /dev/null
expect 'legacy Relies on: inline and heading declarations both inform builders' 0 check.json 'issue(13; .body = "**Relies on:** `contracts/other.v1.md`\n\n## Relies on\n\n`contracts/widget.v1.md`\n") | m23([changed("contracts/widget.v1.md"; "modified"), changed("contracts/other.v1.md"; "modified")]) | say(13; 1301; "10:50"; "launch-fleet: start checked, thread thr_syn13, branch room/13-widget-cccc")' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
note #13: contracts/other.v1.md, contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn13
EOF

expect 'a changed contract only notes the building ticket' 0 check.json 'contract23' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'the check prints the same note without a hold' 0 check.json 'contract23' -- check <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'creating a contract is not changing it' 0 check.json 'm23([changed("contracts/widget.v1.md"; "added")])' -- holds < /dev/null
expect 'a merge before the approval does not count' 0 check.json 'merged_pr(23; 99; "07:00"; [changed("contracts/widget.v1.md"; "modified")])' -- holds < /dev/null
expect 'a merge before a ticket'"'"'s own approval does not count, though it is after another'"'"'s' 0 check.json 'issue(70; .body = "**Relies on:** `contracts/widget.v1.md`") | own_approval(70; 7002; "11:00") | say(70; 7003; "11:15"; "launch-fleet: start checked, thread thr_syn70, branch room/70-fix-eeee") | contract23' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'a merge into another branch does not count' 0 check.json 'contract23 | pull(23; .base = "release-1")' -- holds < /dev/null
expect 'a merge before the latest approval does not count' 0 check.json 'contract23 | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14])' -- holds < /dev/null
expect 'a past hold or note prevents a duplicate builder note' 0 check.json 'contract23 | say(13; 1302; "10:30"; "launch-fleet: held for #23") | say(12; 1202; "10:30"; "launch-fleet: noted #23") | say(13; 1301; "10:00"; "launch-fleet: start checked, thread thr_syn13, branch room/13-widget-cccc")' -- holds < /dev/null
expect 'a folder and a pattern under Relies on' 0 check.json 'm23([changed("docs/widgets/guide.md"; "modified"), changed("skills/grill/SKILL.md"; "modified"), changed("skills/grill/agents/openai.yaml"; "modified"), changed("docs/other.md"; "modified")]) | say(13; 1301; "10:50"; "launch-fleet: start checked, thread thr_syn13, branch room/13-widget-cccc")' -- holds <<EOF
note #13: docs/widgets/guide.md, skills/grill/SKILL.md changed in #23; tell its builder, thread thr_syn13
EOF
expect 'a contract renamed away is a change' 0 check.json 'm23([{filename: "contracts/widget.v2.md", status: "renamed", previous_filename: "contracts/widget.v1.md"}])' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'a contract removed is a change' 0 check.json 'm23([changed("contracts/widget.v1.md"; "removed")])' -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
EOF
expect 'a ready ticket starts after a relied-on contract change' 0 check.json 'merge12 | contract23' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'a held ticket does not start, even with its label still on' 0 check.json 'merge12 | contract23 | say(13; 1301; "11:10"; "launch-fleet: held for #23")' -- check < /dev/null
expect 'a held label stops a start; with no hold of launch-fleet'"'"'s behind it, it is left on' 0 check.json 'merge12 | issue(13; .labels += ["held"])' -- check < /dev/null
expect 'held, labelled, and no new approval yet: quiet' 0 check.json 'merge12 | contract23 | say(13; 1301; "11:10"; "launch-fleet: held for #23: contract changed, re-approve.") | issue(13; .labels = ["held"])' -- check < /dev/null
expect 'a new approval after the hold: the held label comes off first' 0 check.json 'merge12 | contract23 | held_at(13; "11:09") | say(13; 1301; "11:10"; "launch-fleet: held for #23: contract changed, re-approve.") | issue(13; .labels = ["held", "ready-for-agent"]) | approve(10; 1002; "11:20"; 2; [11, 12, 13, 14])' -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'a held label put on after launch-fleet'"'"'s hold ended is not launch-fleet'"'"'s to release (Sol R4)' 0 check.json 'merge12 | contract23 | held_at(13; "10:59") | say(13; 1301; "11:00"; "launch-fleet: held for #23: contract changed, re-approve.") | approve(10; 1002; "11:30"; 2; [11, 12, 13, 14]) | issue(13; .labels = ["held"]) | held_at(13; "11:45")' -- check < /dev/null
expect 'launch-fleet'"'"'s hold of a ticket already labelled held is launch-fleet'"'"'s to release' 0 check.json 'merge12 | contract23 | issue(13; .labels = ["held"]) | held_at(13; "10:00") | say(13; 1301; "10:30"; "launch-fleet: held for #23: contract changed, re-approve.") | approve(10; 1002; "11:20"; 2; [11, 12, 13, 14])' -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'launch-fleet holds again after a release: an older approval does not release it' 0 check.json 'merge12 | contract23 | held_at(13; "10:59") | say(13; 1301; "11:00"; "launch-fleet: held for #23: contract changed, re-approve.") | approve(10; 1002; "11:30"; 2; [11, 12, 13, 14]) | merged_pr(24; 98; "11:40"; [changed("contracts/widget.v1.md"; "modified")]) | issue(13; .labels = ["held"]) | held_at(13; "11:49") | say(13; 1302; "11:50"; "launch-fleet: held for #24: contract changed, re-approve.")' -- check < /dev/null
expect 'launch-fleet holds again after a release: a newer approval releases it' 0 check.json 'merge12 | contract23 | held_at(13; "10:59") | say(13; 1301; "11:00"; "launch-fleet: held for #23: contract changed, re-approve.") | approve(10; 1002; "11:30"; 2; [11, 12, 13, 14]) | merged_pr(24; 98; "11:40"; [changed("contracts/widget.v1.md"; "modified")]) | issue(13; .labels = ["held"]) | held_at(13; "11:49") | say(13; 1302; "11:50"; "launch-fleet: held for #24: contract changed, re-approve.") | approve(10; 1003; "11:55"; 3; [11, 12, 13, 14])' -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'a held ticket starts once a new revision approves it' 0 check.json 'merge12 | contract23 | say(13; 1301; "11:10"; "launch-fleet: held for #23") | approve(10; 1002; "11:20"; 2; [11, 12, 13, 14])' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'merged pull requests read across pages, files cached' 0 check.json 'contract23 | merged_pr(24; 98; "10:30"; [changed("README.md"; "modified")]) | merged_pr(25; 97; "10:40"; [changed("docs/widgets/a.md"; "modified"), changed("docs/widgets/b.md"; "modified"), changed("docs/widgets/c.md"; "added")]) | say(13; 1301; "10:50"; "launch-fleet: start checked, thread thr_syn13, branch room/13-widget-cccc")' FAKE_GH_PAGE=1 -- holds <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
note #13: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn13
note #13: docs/widgets/a.md, docs/widgets/b.md changed in #25; tell its builder, thread thr_syn13
EOF
log_has 'merged pull requests read across pages' 4 '^graphql Merged'
log_has 'merged pull requests read across pages' 3 '^files 25$'
if [ -z "${TEST_ONLY:-}" ] && [ "$mine" = yes ]; then
  cases=$((cases + 1))
  if (cd "$last" && env PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FAKE_GH_WORLD="$last/world.json" \
    FAKE_GH_LOG="$last/gh2.log" LAUNCH_FLEET_NOW=$NOW LAUNCH_FLEET_CACHE="$last/cache" /bin/sh "$FLEET" holds > "$last/out2" 2> "$last/err2") \
    && cmp -s "$last/out" "$last/out2" && points_only "$last/err2" && ! grep -q '^files' "$last/gh2.log"; then
    echo "ok   a second run reads the merged files from the cache"
  else
    bad 'a second run reads the merged files from the cache' "it failed, changed its answer or read the files again"
  fi
fi

### The loop's script: a clone of the project in the loop's sandbox

# A synthetic project on disk, as `gh repo clone` and `git fetch` find it: this
# fleet.sh, and to-tickets’ revision.sh where the to-tickets skill keeps it.
loop_case() { # NAME, then the checks; $1 is the case's name
  cases=$((cases + 1))
  echo "ok   $1"
}
L=$tmp/loop
if { [ -n "${TEST_ONLY:-}" ] && [ "$TEST_ONLY" != loop ]; } || ! take; then
  : # the loop's script runs only in a full run, in one worker
elif mkdir -p "$L/remote/skills/launch-fleet/scripts" "$L/remote/skills/to-tickets" "$L/home" \
  && cp "$FLEET" "$L/remote/skills/launch-fleet/scripts/fleet.sh" \
    && cp "$HERE/records.py" "$L/remote/skills/launch-fleet/scripts/records.py" && cp "$FIX/revision.sh" "$L/remote/skills/to-tickets/revision.sh" \
  && git -C "$L/remote" init -q && git -C "$L/remote" add -A \
  && git -C "$L/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -q -m one \
  && mkdir "$L/w" && world check.json 'merge12' "$L/w" > "$L/world.json"; then
  # CS5 uses existing normalized input and one private durable state.
  jq --argjson now "$NOW" '.observed_at = $now |
    .budgets[] |= (.reset_at = ($now + 3600))' \
    "$HERE/carried/healthy.json" > "$L/observation.json"
  loop_run() { # LOG OUT: run loop.sh once
    (cd "$L" && env -u OPENWIZ_GITHUB_APP_KEY PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FAKE_GH_WORLD="$L/world.json" FAKE_GH_LOG="$L/$1" \
      LAUNCH_FLEET_OVERLOAD_INPUT="$L/observation.json" LAUNCH_FLEET_OVERLOAD_STATE="$L/pause.json" \
      FAKE_GH_REMOTE="$L/remote" LAUNCH_FLEET_HOME="$L/home" LAUNCH_FLEET_NOW=$NOW LAUNCH_FLEET_CACHE="$L/cache" \
      /bin/sh "$HERE/loop.sh" > "$L/$2" 2> "$L/$2.err")
  }
  printf 'start #13: W3: widget page (spec #10)\n' > "$L/want"
  if loop_run log1 out1 && cmp -s "$L/want" "$L/out1" && loop_points "$L/out1.err" && grep -qx 'repo clone' "$L/log1" \
    && grep -q '^issue view 10 subIssues$' "$L/log1"; then
    loop_case "the loop's script clones the project and runs its check, with to-tickets’ revision.sh beside it"
  else
    bad "the loop's script clones the project and runs its check" "$(cat "$L/out1" "$L/out1.err" | head -c 400)"; cases=$((cases + 1))
  fi
  # E6: the clone refreshes, but its skills/ is never run: the check stays the installed one.
  printf 'echo "the default branch moved"\n' >> "$L/remote/skills/launch-fleet/scripts/fleet.sh"
  if git -C "$L/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -q -am two \
    && loop_run log2 out2 && cmp -s "$L/want" "$L/out2" && loop_points "$L/out2.err" && ! grep -q 'repo clone' "$L/log2" \
    && grep -q 'the default branch moved' "$L/home/synthetic-owner/synthetic-repo/skills/launch-fleet/scripts/fleet.sh"; then
    loop_case "the next run updates its clone to the default branch, without cloning again or running its skills"
  else
    bad "the next run updates its clone" "$(cat "$L/out2" "$L/out2.err" | head -c 400)"; cases=$((cases + 1))
  fi
  if (cd "$L" && env PATH="$tmp/bin:$PATH" GH_REPO= FAKE_GH_WORLD="$L/world.json" FAKE_GH_LOG="$L/log3" /bin/sh "$HERE/loop.sh" > "$L/out3" 2>&1); then
    bad "the loop's script without GH_REPO fails" "it exited 0"; cases=$((cases + 1))
  elif [ $? = 2 ] && grep -q 'GH_REPO must be owner/name' "$L/out3"; then
    loop_case "the loop's script without GH_REPO exits 2"
  else
    bad "the loop's script without GH_REPO exits 2" "$(head -c 300 "$L/out3")"; cases=$((cases + 1))
  fi
else
  bad "the loop's script" "can't set up its synthetic project"; cases=$((cases + 3))
fi

### Claims: two ticks never start two agents for one ticket or one head

if { [ -z "${TEST_ONLY:-}" ] || [ "$TEST_ONLY" = loop ]; } && take; then
  cases=$((cases + 1))
  if sh "$HERE/test-loop.sh" > "$tmp/bundled-loop.log" 2>&1; then
    echo 'ok   the bundled loop works without a consumer skills/ or plugin cache'
  else
    bad 'the bundled loop works without a consumer skills/ or plugin cache' "$(cat "$tmp/bundled-loop.log")"
  fi
fi

expect 'claim: the only claim goes' 0 check.json 'merge12 | say(13; 1301; "11:58"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
go #13
EOF
expect 'claim: of two claims still starting, the older goes' 0 check.json 'merge12 | say(13; 1301; "11:58"; "launch-fleet: starting") | say(13; 1302; "11:59"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
go #13
EOF
expect 'claim: of two claims still starting, the later withdraws' 0 check.json 'merge12 | say(13; 1301; "11:58"; "launch-fleet: starting") | say(13; 1302; "11:59"; "launch-fleet: starting")' -- claim 13 1302 <<EOF
withdraw #13: an older claim or builder: "starting"
EOF
expect 'claim: a later claim withdraws when the older one has already started its builder (Sol R1)' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_synA") | say(13; 1302; "11:51"; "launch-fleet: starting")' -- claim 13 1302 <<EOF
withdraw #13: an older claim or builder: "started, thread thr_synA"
EOF
expect 'claim: an older claim keeps its ticket through start checked' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: start checked, thread thr_synA, branch room/13-w3-widget-page-cccc") | say(13; 1302; "11:51"; "launch-fleet: starting")' -- claim 13 1302 <<EOF
withdraw #13: an older claim or builder: "start checked, thread thr_synA, branch room/13-w3-widget-page-cccc"
EOF
expect 'claim: an older refused start does not stop a retry' 0 check.json 'merge12 | say(13; 1301; "11:30"; "launch-fleet: start refused: plan limit reached") | say(13; 1302; "11:58"; "launch-fleet: starting")' -- claim 13 1302 <<EOF
go #13
EOF
expect 'claim: an open pull request stops a start' 0 check.json 'merge12 | open_pr(33; 13; "#13: work in progress") | say(13; 1301; "11:58"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: pull request #33 is open
EOF
expect 'claim: a ticket held since the check stops a start' 0 check.json 'merge12 | issue(13; .labels += ["held"]) | say(13; 1301; "11:58"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: it is not on the frontier now
EOF
expect 'claim: a comment that is not a starting claim fails' 2 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_synA")' -- claim 13 1301 <<EOF
comment 1301 on #13 is not a "launch-fleet: starting" claim
EOF
expect 'claim: a comment that is not there fails' 2 check.json 'merge12 | say(13; 1301; "11:58"; "launch-fleet: starting")' -- claim 13 9999 <<EOF
can't find comment 9999 on #13
EOF
expect 'review claim: the only claim goes' 0 check.json 'pr31 | pr_say(31; 3101; "11:58"; "launch-fleet: review starting \(sha(31))")' -- claim 31 3101 <<EOF
go #31
EOF
expect 'review claim: a later claim withdraws when an older one has started the reviewer' 0 check.json 'pr31 | pr_say(31; 3101; "11:50"; "launch-fleet: review started \(sha(31)), thread thr_synR") | pr_say(31; 3102; "11:51"; "launch-fleet: review starting \(sha(31))")' -- claim 31 3102 <<EOF
withdraw #31: an older review claim: "review started $S31, thread thr_synR"
EOF
expect 'review claim: a re-check of a new head goes, whatever the older head had' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: CHANGES at \(sha(31))") | pull(31; .head = ("31f" * 40)[:40]) | pr_say(31; 3103; "11:58"; "launch-fleet: review starting \(("31f" * 40)[:40])")' -- claim 31 3103 <<EOF
go #31
EOF
expect 'review claim: a claim for a head that moved withdraws' 0 check.json 'pr31 | pr_say(31; 3101; "11:58"; "launch-fleet: review starting \(sha(31))") | pull(31; .head = ("31f" * 40)[:40])' -- claim 31 3101 <<EOF
withdraw #31: the head is now $S31F
EOF
expect 'review claim: a fresh reviewer after a failed one goes' 0 check.json 'quiet31 | pr_say(31; 3103; "11:58"; "launch-fleet: review starting \(sha(31))")' -- claim 31 3103 <<EOF
go #31
EOF

### Archives are never lost

expect 'an open issue approved on its own, past the first page of the search, starts (#259)' 0 check.json 'own_approval(70; 7002; "09:00") | reduce range(71; 91) as $n (.; closed_single($n; "11:00"))' FAKE_GH_PAGE=5 -- check <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
log_has 'an open issue approved on its own, past the first page of the search, starts (#259)' 6 '^search issues page='

expect 'a closed issue approved on its own is archived, even past the first page of closed issues (Sol R2)' 0 check.json 'own_approval(70; 7002; "09:00") | say(70; 7003; "09:10"; "launch-fleet: start checked, thread thr_syn70, branch room/70-fix-eeee") | issue(70; .state = "CLOSED" | .updatedAt = at("09:30")) | reduce range(71; 91) as $n (.; closed_single($n; "11:00"))' FAKE_GH_PAGE=5 -- check <<EOF
archive #70: closed; archive thr_syn70
EOF
log_has 'a closed issue approved on its own is archived, even past the first page of closed issues (Sol R2)' 6 '^search issues page='
expect 'a search that lists fewer issues outside specs than it counts fails loudly' 2 check.json 'own_approval(70; 7002; "09:00") | issue(70; .state = "CLOSED" | .updatedAt = at("09:30")) | reduce range(71; 91) as $n (.; closed_single($n; "11:00"))' FAKE_GH_SEARCH_CAP=10 -- check <<EOF
the search listed 10 of 21 issues outside specs
EOF
expect 'a closed issue whose last comment is its archive record is not read again' 0 check.json 'own_approval(70; 7002; "09:00") | say(70; 7003; "09:10"; "launch-fleet: start checked, thread thr_syn70, branch room/70-fix-eeee") | say(70; 7004; "10:00"; "launch-fleet: archived") | issue(70; .state = "CLOSED")' -- check < /dev/null
log_has 'a closed issue whose last comment is its archive record is not read again' 0 '^graphql Nodes'
expect 'a spec closes only once its tickets'"'"' agents are archived' 0 check.json 'all_closed | issue(12; .comments |= map(select(.id != 1202))) | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
archive #12: closed; archive thr_syn12
EOF

### A person's ticket under a changed contract

expect 'a person'"'"'s ticket is announced after a contract change' 0 check.json 'merge12 | issue(13; .labels = ["ready-for-human"]) | approve(10; 1002; "09:50"; 2; [11, 12, [13, "ready-for-human"], 14]) | contract23' -- check <<EOF
person #13: W3: widget page (spec #10) is ready, and only the user can do it
EOF
expect 'a held person'"'"'s ticket stays quiet until approved again' 0 check.json 'merge12 | issue(13; .labels = ["held"]) | approve(10; 1002; "09:50"; 2; [11, 12, [13, "ready-for-human"], 14]) | contract23 | say(13; 1301; "10:30"; "launch-fleet: held for #23: contract changed, re-approve.")' -- check < /dev/null
expect 'a person'"'"'s ticket approved again since its hold is released before it is announced' 0 check.json 'merge12 | issue(13; .labels = ["held", "ready-for-human"]) | approve(10; 1002; "09:50"; 2; [11, 12, [13, "ready-for-human"], 14]) | contract23 | held_at(13; "10:29") | say(13; 1301; "10:30"; "launch-fleet: held for #23: contract changed, re-approve.") | approve(10; 1003; "11:20"; 3; [11, 12, [13, "ready-for-human"], 14])' -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF

### The check: approvals and the spec

FP=$(fp12 check.json 'merge12 @@then@@ issue(14; .blockedBy = [12])' 10)
expect 'a plan changed since its approval starts nothing, and asks once' 0 check.json 'merge12 @@then@@ issue(14; .blockedBy = [12])' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $FP)
EOF
expect 'a change already raised is not raised again' 0 check.json "merge12 @@then@@ issue(14; .blockedBy = [12]) | say(10; 1002; \"11:00\"; \"launch-fleet: needs approval: changed since revision 1 (fingerprint now $FP)\")" -- check < /dev/null
expect 'a new revision approves the changed plan' 0 check.json 'merge12 | issue(14; .blockedBy = [12]) | approve(10; 1002; "11:30"; 2; [11, 12, 13, 14])' -- check <<EOF
start #13: W3: widget page (spec #10)
start #14: W4: widget docs (spec #10)
EOF
expect 'a title changed after the approval' 0 check.json 'merge12 @@then@@ issue(13; .title = "W3: widget page, renamed")' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ issue(13; .title = "W3: widget page, renamed")' 10))
EOF
expect 'a ticket body edited after the approval' 0 check.json 'merge12 @@then@@ issue(13; .body += "One more line.")' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ issue(13; .body += "One more line.")' 10))
EOF
expect 'the spec body edited after the approval' 0 check.json 'merge12 @@then@@ issue(10; .body = "The spec, edited.")' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ issue(10; .body = "The spec, edited.")' 10))
EOF
expect 'a ticket dropped from the spec after the approval' 0 check.json 'merge12 @@then@@ issue(14; .parent = null)' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ issue(14; .parent = null)' 10))
look #10: planned #14 is not a sub-issue of the spec
EOF
expect 'a low finding filed under the spec after the approval stops new starts' 0 check.json 'merge12 @@then@@ ticket(15; "W5: a low finding"; ["needs-triage"]; [])' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ ticket(15; "W5: a low finding"; ["needs-triage"]; [])' 10))
look #10: open sub-issue #15 is not in the approved plan
EOF
expect 'labels, comments, closed tickets and merges leave an approval current' 0 check.json '. @@then@@ merge12 | say(13; 1301; "11:00"; "A progress note.") | issue(13; .labels += ["bug"])' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'labels, comments, closed tickets and merges leave an approval current' 1 '^issue view 10 subIssues$'
expect 'a ticked task box leaves an approval current (revision v2)' 0 check.json 'merge12 | issue(13; .body += "\n- [ ] the page lists every widget") @@then@@ issue(13; .body |= sub("- \\[ \\]"; "- [x]"))' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'a ticket being built keeps going when the plan changes' 0 check.json 'pr31 @@then@@ issue(12; .title = "W2: widget store, renamed")' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'nothing could start: no revision is read' 0 check.json . -- check < /dev/null
log_has 'nothing could start: no revision is read' 0 '^issue view'
expect 'nothing could start: no revision.sh is needed' 0 check.json . LAUNCH_FLEET_REVISION=/nonexistent/revision.sh -- check < /dev/null
expect 'an approval with no fingerprint starts nothing' 0 check.json 'merge12 | issue(10; .comments[0].body |= sub("\n\nFingerprint: `@@FP@@`"; ""))' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12' 10))
EOF
expect 'a quoted approval is no approval' 0 check.json 'merge12 | issue(10; .comments[0].body |= "Quoting it: " + .)' -- check < /dev/null
expect 'a ticket approved only in an older revision does not start' 0 check.json 'ticket(15; "W5: widget extras"; ["ready-for-agent"]; []) | approve(10; 1002; "09:00"; 2; [11, 12, 13, 14, 15]) | approve(10; 1003; "11:00"; 3; [11, 12, 13, 14])' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF
expect 'a person'"'"'s ticket is never started: the user is told once it is ready' 0 check.json 'merge12 | ticket(15; "W5: the live check"; ["ready-for-human"]; [12]) | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]])' -- check <<EOF
start #13: W3: widget page (spec #10)
person #15: W5: the live check (spec #10) is ready, and only the user can do it
EOF
expect 'a person'"'"'s ticket still blocked: nothing yet' 0 check.json 'ticket(15; "W5: the live check"; ["ready-for-human"]; [12]) | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]])' -- check < /dev/null
expect 'a person'"'"'s ticket already told: quiet' 0 check.json 'merge12 | ticket(15; "W5: the live check"; ["ready-for-human"]; [12]) | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]]) | say(15; 1501; "11:30"; "launch-fleet: told the user")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'a ready-for-human row never starts, whatever the issue'"'"'s label' 0 check.json 'ticket(15; "W5: the live check"; ["ready-for-agent"]; []) | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]])' -- frontier < /dev/null
expect 'an approval that lists no tickets: look' 0 check.json 'issue(10; .comments[0].body |= gsub("\n\\| #[^\n]*"; ""))' -- check <<EOF
look #10: its latest plan graph approval lists no tickets
EOF
expect 'a low finding filed after the approval does not start, even labelled ready-for-agent' 0 check.json 'ticket(15; "W5: a low finding"; ["ready-for-agent"]; [])' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF
expect 'a low finding approved on its own still waits for its spec'"'"'s approval' 0 check.json 'ticket(15; "W5: a low finding"; ["ready-for-agent"]; []) | say(15; 1501; "11:00"; "**Approved on its own by Robin, 2026-11-01:** \"approve #15\"")' -- frontier < /dev/null

### #1340: a machine plan approval starts the fleet; the video's comments steer it

expect 'machine: a valid machine plan approval starts its fleet' 0 check.json 'merge12 | machine_only' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'machine: a spec with no approval starts nothing' 0 check.json 'merge12 | issue(10; .comments = [])' -- check < /dev/null
expect 'machine: a header that is not the exact machine record approves nothing' 0 check.json 'merge12 | issue(10; .comments = []) | say(10; 1001; "08:00"; machine_record(10; 1001; "08:00"; 1; [11, 12, 13, 14]) | sub("links, relies, sizes, width and owned paths passed"; "links passed"))' -- check < /dev/null
expect 'machine: a record without its grill confirmation approves nothing' 0 check.json 'merge12 | issue(10; .comments = []) | say(10; 1001; "08:00"; machine_record(10; 1001; "08:00"; 1; [11, 12, 13, 14]) | sub("Grill confirmed: [^\n]*\n"; ""))' -- check < /dev/null
expect 'machine: an outsider'"'"'s machine record approves nothing' 0 check.json 'merge12 | issue(10; .comments = []) | by(10; 1001; "08:00"; outsider; machine_record(10; 1001; "08:00"; 1; [11, 12, 13, 14]))' -- check < /dev/null
expect 'machine: a record without its checks summary or revision text approves nothing (R4)' 0 check.json 'merge12 | issue(10; .comments = []) | say(10; 1001; "08:00"; machine_record(10; 1001; "08:00"; 1; [11, 12, 13, 14]) | sub("Checks: [^\n]*\n\n"; "") | sub("\n<details>(.|\n)*$"; "\n"))' -- check < /dev/null
expect 'machine: a table that differs from its revision text approves nothing (R4)' 0 check.json 'merge12 | issue(10; .comments = []) | say(10; 1001; "08:00"; machine_record(10; 1001; "08:00"; 1; [11, 12, 13, 14]) | sub("\\| #13 \\| W3: widget page \\|"; "| #13 | W3: widget pages |"))' -- check < /dev/null
expect 'machine: revision text that is not the plan its fingerprint names approves nothing (R4)' 0 check.json 'merge12 | machine_only @@then@@ issue(10; .comments[0].body |= gsub("W3: widget page"; "W3: widget pages"))' -- check <<EOF
look #10: its latest machine plan approval's revision text is not the plan its fingerprint names
EOF
expect 'machine: a revision after a contract hold leaves the hold to the owner (R1)' 0 check.json 'merge12 | contract23 | held_at(13; "11:09") | say(13; 1301; "11:10"; "launch-fleet: held for #23: contract changed, re-approve.") | issue(13; .labels = ["held", "ready-for-agent"]) | machine(10; 1002; "11:20"; 2; [11, 12, 13, 14])' -- check < /dev/null
expect 'machine: the owner'"'"'s re-approval releases a contract hold under a machine-current plan (R1)' 0 check.json 'merge12 | contract23 | held_at(13; "11:09") | say(13; 1301; "11:10"; "launch-fleet: held for #23: contract changed, re-approve.") | issue(13; .labels = ["held", "ready-for-agent"]) | approve(10; 1002; "11:20"; 2; [11, 12, 13, 14]) | machine(10; 1003; "11:30"; 3; [11, 12, 13, 14])' -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
FP=$(fp12 check.json 'merge12 | machine_only @@then@@ issue(14; .blockedBy = [12])' 10)
expect 'machine: a plan changed since its machine approval starts nothing' 0 check.json 'merge12 | machine_only @@then@@ issue(14; .blockedBy = [12])' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $FP)
EOF
# R2 (decision 7030919773): video comment steering is off in every mode until
# #1402's identity separation is verified, whoever posted the video. The hold,
# re-cut and steer cases WS17 had are gone with that behaviour; the cases below
# keep the one-time notice and prove no comment steers.
OFF_ALL='comments on the video steer nothing until the identity separation of OpenWiz #1402 is verified; the owner steers through the orchestrator'
expect 'steer: an App-posted video and a later shared-login agent note steer nothing (R2 decision)' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | owner_says(10; 1003; "10:00"; "Reset the cache before the next run.")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: the owner'"'"'s stop on an App-posted video steers nothing either (R2 decision)' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | owner_says(10; 1003; "10:00"; "Stop.")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: under the shared login an agent'"'"'s note steers nothing, and steering off is noted (R2)' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | issue(10; .comments[-1].author = "Synthetic-Owner") | owner_says(10; 1003; "10:00"; "Reset the cache before the next run.")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: under the shared login the owner'"'"'s stop steers nothing either (R2)' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | issue(10; .comments[-1].author = "synthetic-owner") | owner_says(10; 1003; "10:00"; "Stop.")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: steering off is noted only once (R2)' 0 check.json "merge12 | machine_only | video(10; 1002; \"09:00\") | owner_says(10; 1003; \"10:00\"; \"Keep the page plain.\") | say(10; 1004; \"10:05\"; \"launch-fleet: look: $OFF_ALL\") | owner_says(10; 1005; \"10:10\"; \"reset\")" -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'steer: a stop before the video steers nothing' 0 check.json 'merge12 | machine_only | owner_says(10; 1002; "08:30"; "stop") | video(10; 1003; "09:00")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: an outsider'"'"'s stop holds nothing' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | by(10; 1003; "10:00"; outsider; "stop")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: the factory App'"'"'s note is no owner steer (R2)' 0 check.json 'merge12 | machine_only | video(10; 1002; "09:00") | say(10; 1003; "10:00"; "Reset the cache before the next run.")' -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
# WS33 (#1736): to-spec's video now invites steering through the orchestrator;
# that exact record is a video too, so its spec still gets the notice.
NEW_CUE='Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).'
expect 'steer: a video with WS33'"'"'s new wording gets the notice (WS33)' 0 check.json "merge12 | machine_only | say(10; 1002; \"09:00\"; \"[Watch the narrated spec](https://example.com/synthetic/spec.mp4)\\n\\n$NEW_CUE\") | owner_says(10; 1003; \"10:00\"; \"Stop.\")" -- check <<EOF
look #10: $OFF_ALL
start #13: W3: widget page (spec #10)
EOF
expect 'steer: a help comment repeating WS33'"'"'s new cue is no video, so no notice (WS33)' 0 check.json "merge12 | machine_only | say(10; 1005; \"10:10\"; \"To steer, ask the orchestrator.\\n\\n$NEW_CUE\")" -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'steer: a help comment repeating the cue is no video, so no notice (R3)' 0 check.json 'merge12 | machine_only | say(10; 1005; "10:10"; "To steer, reply on the video.\n\nComment here to steer: stop, reset, or anything else.")' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF

### Issues outside any spec

expect 'a ready-for-agent issue with no approval does not start' 0 check.json . -- frontier < /dev/null
expect 'an issue approved on its own starts' 0 check.json 'say(70; 7002; "11:00"; "> *This was generated by AI during triage.*\n\n**Approved on its own by Robin, 2026-11-01:** \"approve #70\", with the brief above.")' -- check <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'an issue approved on its own is in the frontier' 0 check.json 'say(70; 7002; "11:00"; "**Approved on its own by Robin, 2026-11-01:** \"approve #70\"")' -- frontier <<EOF
#70 Fix the broken link in the widget docs
EOF
expect 'an approval only quoted mid-line is no approval' 0 check.json 'say(70; 7002; "11:00"; "Not yet: **Approved on its own by** is what we would write.")' -- frontier < /dev/null
expect 'an issue approved on its own waits for its blockers' 0 check.json 'say(70; 7002; "11:00"; "**Approved on its own by Robin, 2026-11-01:** \"approve #70\"") | issue(70; .blockedBy = [13])' -- frontier < /dev/null
expect 'an issue approved on its own goes through review like a ticket' 0 check.json 'say(70; 7002; "09:00"; "**Approved on its own by Robin, 2026-11-01:** \"approve #70\"") | say(70; 7003; "09:10"; "launch-fleet: start checked, thread thr_syn70, branch room/70-fix-eeee") | open_pr(32; 70; "#70: green")' -- check <<EOF
review #32 for #70 at $(sha 32): first review
EOF
expect 'a held issue approved on its own starts once approved again' 0 check.json 'issue(70; .body = "**Relies on:** `contracts/widget.v1.md`") | own_approval(70; 7002; "09:00") | contract23 | say(70; 7003; "10:30"; "launch-fleet: held for #23") | own_approval(70; 7004; "11:00")' -- check <<EOF
note #12: contracts/widget.v1.md changed in #23; tell its builder, thread thr_syn12
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'a closed issue approved on its own gets its builder archived' 0 check.json 'say(70; 7002; "09:00"; "**Approved on its own by Robin, 2026-11-01:** \"approve #70\"") | say(70; 7003; "09:10"; "launch-fleet: start checked, thread thr_syn70, branch room/70-fix-eeee") | issue(70; .state = "CLOSED")' -- check <<EOF
archive #70: closed; archive thr_syn70
EOF
expect 'a spec with no approval is not a fleet' 0 check.json 'merge12 | issue(10; .comments = [])' -- check < /dev/null
expect 'every approved ticket closed: one closing summary' 0 check.json 'all_closed | ticket(15; "W5: low finding"; ["needs-triage"]; []) | issue(15; .body = "Follow-up of #12 (spec #10): a synthetic wording nit.")' -- check <<EOF
spec done #10: every planned ticket is done; open polish follow-ups: #15
EOF
expect 'summary posted, an open sub-issue follow-up does not block closure' 0 check.json 'all_closed | ticket(15; "W5: low finding"; ["needs-triage"]; []) | issue(15; .body = "Follow-up of #12 (spec #10): a synthetic wording nit.") | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF
expect 'every ticket closed after the summary: close the spec' 0 check.json 'all_closed | ticket(15; "W5: low finding"; ["needs-triage"]; []) | issue(15; .body = "Follow-up of #12 (spec #10): a synthetic wording nit.") | issue(15; .state = "CLOSED") | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF

### Batch approval (#1463): render the record from triage's actual instructions

BATCH='all_closed | issue(10; .state = "CLOSED")
  | followup(16; "OPEN"; "Follow-up of #12 (spec #10): first approved nit.")
  | followup(17; "OPEN"; "Follow-up of #12 (spec #10): second approved nit.")
  | followup(18; "CLOSED"; "Follow-up of #12 (spec #10): dropped nit.")
  | followup(19; "OPEN"; "Follow-up of #12 (spec #10): unmentioned nit.")
  | issue(16; .labels = ["ready-for-agent", "polish"])
  | issue(17; .labels = ["ready-for-agent", "polish"])
  | issue(18; .labels = ["wontfix", "polish"])
  | issue(19; .labels = ["ready-for-agent", "polish"])
  | say(10; 1003; "11:00"; "Batch decision by Robin: approve #16 and #17; drop #18.")'
expect 'batch approval: the spec decision alone admits no follow-ups' 0 check.json "$BATCH" -- frontier < /dev/null

# No handwritten copy of the approval marker: removing the documented record
# must reproduce the empty frontier. Only the explicitly approved pair gets it.
BATCH_RECORD=$(awk '
  /^### Record a batch decision$/ { section = 1; next }
  section && /^```markdown$/ { record = 1; next }
  record && /^```$/ { exit }
  record { print }
' "$HERE/../../triage/SKILL.md")
BATCH_JSON=$(printf '%s' "$BATCH_RECORD" | jq -Rs .)
expect 'batch approval: the documented records admit only the approved subset' 0 check.json "$BATCH
  | reduce [16, 17][] as \$n (.; say(\$n; (\$n * 100 + 1); \"11:01\";
      ($BATCH_JSON
        | gsub(\"<user>\"; \"Robin\") | gsub(\"<YYYY-MM-DD>\"; \"2026-11-01\")
        | gsub(\"<their exact words>\"; \"approve #16 and #17; drop #18\")
        | gsub(\"<decision>\"; \"approved #16 and #17; #18 remains dropped\")
        | gsub(\"<pointer>\"; \"https://github.com/jparker2006/ClosedWiz/issues/9001#issuecomment-9000000001\")
        | gsub(\"<batch decision URL>\"; \"https://github.com/synthetic-owner/synthetic-repo/issues/10#issuecomment-1003\")
        | gsub(\"<brief URL>\"; \"https://github.com/synthetic-owner/synthetic-repo/issues/\\(\$n)#issuecomment-1\")
        | gsub(\"<owned paths>\"; \"docs/synthetic-\\(\$n).md\")
        | gsub(\"<what it relies on>\"; \"nothing\")
        | if test(\"<[^>]+>\") then error(\"unfilled triage approval placeholder\")
          else . end)))" -- frontier <<EOF
#16 A low finding 16
#17 A low finding 17
EOF

### Follow-ups filed outside the spec (#155): "Follow-up of #<ticket> (spec #<spec>)"

expect 'the closing summary lists follow-ups filed outside the spec, and only its own' 0 check.json 'all_closed | followup(16; "OPEN"; "Follow-up of #12 (spec #10): R3 [low] a wording nit.") | followup(17; "OPEN"; "Follow-up of #31 (spec #20): another spec'"'"'s.")' -- check <<EOF
spec done #10: every planned ticket is done; open polish follow-ups: #16
EOF
expect 'a "Follow-up of" line that is not the body'"'"'s first line does not count' 0 check.json 'all_closed | followup(16; "OPEN"; "Notes first.\nFollow-up of #12 (spec #10): R3 [low] a wording nit.")' -- check <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
expect 'summary posted, an open external follow-up does not block closure' 0 check.json 'all_closed | followup(16; "OPEN"; "Follow-up of #12 (spec #10): R3 [low] a wording nit.") | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF
expect 'a spec closes once the follow-ups filed outside it are closed' 0 check.json 'all_closed | followup(16; "CLOSED"; "Follow-up of #12 (spec #10): R3 [low] a wording nit.") | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF

### Spec closure guards (#1021): every planned ticket, never polish

expect 'an open planned ticket prevents spec completion with open polish' 0 check.json 'all_closed | issue(14; .state = "OPEN") | ticket(15; "Low finding"; ["polish"]; [])' -- check <<EOF
start #14: W4: widget docs (spec #10)
EOF
expect 'a summary cannot close a spec with an open planned ticket' 0 check.json 'all_closed | issue(14; .state = "OPEN") | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
start #14: W4: widget docs (spec #10)
EOF
# R3 (#1044): a stall that persists (a closed row that never merged) waits for
# a newer verification, like any look.
expect 'closed without a merged planned ticket is not spec completion' 0 check.json 'all_closed | .pulls |= map(select(.number != 25)) | say(10; 1002; "11:30"; "launch-fleet: look: planned #14 is closed without a verified merge")' -- check < /dev/null
expect 'a missing planned ticket is not spec completion' 0 check.json 'all_closed | .issues |= map(select(.number != 14))' -- check <<EOF
look #10: planned #14 is not a sub-issue of the spec
EOF
# R3 (#1044): a stalled row that leaves the plan is reported once, and a spec
# that stalls is never cached quiet, so each check reads it in full.
expect 'R3: a row that left the plan after the approval is reported' 0 check.json 'all_closed | .issues |= map(select(.number != 14)) | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'R3: a row that left the plan after the approval is reported' 1 '^graphql Spec number='
expect 'R3: a planned row closed on a release branch is not a verified merge' 0 check.json 'all_closed | pull(25; .base = "release-1")' -- check <<EOF
look #10: planned #14 is closed without a verified merge
EOF
expect 'R3: the pending ticket is reported before a stall keeps the spec open' 0 check.json 'all_closed | .pulls |= map(select(.number != 25)) | ticket(15; "New planned work"; []; [])' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
look #10: planned #14 is closed without a verified merge
EOF
# R1 (#1044 review): an unrelated historical "open sub-issue" look never
# suppresses a planned-row stall on another ticket.
expect 'R1: an unrelated unplanned-issue record does not hide a closed-unmerged stall' 0 check.json 'all_closed | .pulls |= map(select(.number != 25)) | say(10; 1002; "09:00"; "launch-fleet: look: open sub-issue #99 is not in the approved plan")' -- check <<EOF
look #10: planned #14 is closed without a verified merge
EOF
expect 'R1: an unrelated unplanned-issue record does not hide a missing-sub-issue stall' 0 check.json 'all_closed | .issues |= map(select(.number != 14)) | say(10; 1002; "09:00"; "launch-fleet: look: open sub-issue #99 is not in the approved plan")' -- check <<EOF
look #10: planned #14 is not a sub-issue of the spec
EOF
expect 'R1: a same-reason historical record still settles its own stall' 0 check.json 'all_closed | .pulls |= map(select(.number != 25)) | say(10; 1002; "09:00"; "launch-fleet: look: planned #14 is closed without a verified merge")' -- check < /dev/null
expect 'an open planned live check prevents spec completion' 0 check.json 'all_closed | ticket(15; "Live check"; ["ready-for-human"]; []) | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]])' -- check <<EOF
person #15: Live check (spec #10) is ready, and only the user can do it
EOF
expect 'a completed planned live check needs no pull request' 0 check.json 'all_closed | ticket(15; "Live check"; ["ready-for-human"]; []) | issue(15; .state = "CLOSED") | approve(10; 1002; "11:00"; 2; [11, 12, 13, 14, [15, "ready-for-human"]])' -- check <<EOF
look #15: closed person ticket needs launch-fleet: complete: <evidence>
spec done #10: every planned ticket is done; no follow-ups
EOF

### Review R1: pending planned work is never silently turned into polish

expect 'R1: an unclassified new sub-issue blocks the summary' 0 check.json 'all_closed | ticket(15; "New planned work"; []; [])' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF
expect 'R1: an unclassified new sub-issue blocks closure' 0 check.json 'all_closed | ticket(15; "New planned work"; []; []) | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF
again 'R1: a reported pending sub-issue does not repeat the alert' 'say(10; 1003; "11:35"; "launch-fleet: look: open sub-issue #15 is not in the approved plan")' -- check < /dev/null
expect 'R1: a polish label identifies a follow-up without a body marker' 0 check.json 'all_closed | ticket(15; "A low finding"; ["polish"]; []) | say(10; 1002; "11:30"; "launch-fleet: spec summary")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF
expect 'R1: a follow-up marker for another spec is pending work here' 0 check.json 'all_closed | ticket(15; "New work"; ["needs-triage"]; []) | issue(15; .body = "Follow-up of #31 (spec #20): another spec.")' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF
expect 'R1: a marker after other prose does not identify a follow-up' 0 check.json 'all_closed | ticket(15; "New work"; []; []) | issue(15; .body = "Notes first.\nFollow-up of #12 (spec #10): a wording nit.")' -- check <<EOF
look #10: open sub-issue #15 is not in the approved plan
EOF

### Review R2: report missing evidence once and resume after verification

expect 'R2: recorded missing live evidence blocks the summary' 0 check.json 'all_closed | say(10; 1002; "11:30"; "launch-fleet: look: live check not recorded as passed")' -- check < /dev/null
again 'R2: a wake repeats no missing-evidence alert' . -- wake 10 < /dev/null
again 'R2: verified live evidence releases the summary' 'say(10; 1003; "11:40"; "launch-fleet: live check passed\nVerified the synthetic pass evidence on the planned human ticket.")' -- check <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
expect 'R2: recorded missing live evidence blocks closure after a summary' 0 check.json 'all_closed | say(10; 1002; "11:20"; "launch-fleet: spec summary") | say(10; 1003; "11:30"; "launch-fleet: look: live check not recorded as passed")' -- check < /dev/null
again 'R2: a check repeats no missing-evidence alert after a summary' . -- check < /dev/null
log_has 'R2: a check repeats no missing-evidence alert after a summary' 0 '^graphql Spec number='
again 'R2: a newer verification releases closure and invalidates the cache' 'say(10; 1004; "11:40"; "launch-fleet: live check passed")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF
log_has 'R2: a newer verification releases closure and invalidates the cache' 1 '^graphql Spec number=10'
again 'R2: a later missing-evidence report requires verification again' 'say(10; 1005; "11:45"; "launch-fleet: look: live check not recorded as passed")' -- wake 10 < /dev/null

### Review R6: new evidence wakes verification without a manual pass record

expect 'R6: a new evidence comment asks the tick to verify it' 0 check.json 'all_closed | say(10; 1002; "11:20"; "launch-fleet: look: live check not recorded as passed") | say(10; 1003; "11:30"; "Recorded PASS: synthetic evidence on the planned live-check ticket.")' -- check <<EOF
look #10: live check evidence to verify in comment 1003
EOF
again 'R6: a spec wake also asks for unverified new evidence' . -- wake 10 <<EOF
look #10: live check evidence to verify in comment 1003
EOF
again 'R6: an inspected comment without a verified pass is not reported again' 'say(10; 1004; "11:35"; "launch-fleet: look: live check evidence to verify in comment 1003")' -- check < /dev/null
again 'R6: another evidence comment wakes verification again' 'say(10; 1005; "11:40"; "PASS with the new synthetic proof link.")' -- wake 10 <<EOF
look #10: live check evidence to verify in comment 1005
EOF
again 'R6: the tick verifies the evidence and records a suffixed pass' 'say(10; 1006; "11:45"; "launch-fleet: live check passed: the linked acceptance record, PASS")' -- check <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
expect 'R6: new evidence after a summary also wakes verification' 0 check.json 'all_closed | say(10; 1002; "11:10"; "launch-fleet: spec summary") | say(10; 1003; "11:20"; "launch-fleet: look: live check not recorded as passed") | say(10; 1004; "11:30"; "The synthetic acceptance record now says PASS.")' -- check <<EOF
look #10: live check evidence to verify in comment 1004
EOF
expect 'R6: a suffixed pass record releases a missing-evidence wait' 0 check.json 'all_closed | say(10; 1002; "11:20"; "launch-fleet: look: live check not recorded as passed") | say(10; 1003; "11:30"; "launch-fleet: live check passed: recorded acceptance result, PASS")' -- check <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
expect 'R6: a similar word is not a pass record' 0 check.json 'all_closed | say(10; 1002; "11:20"; "launch-fleet: look: live check not recorded as passed") | say(10; 1003; "11:30"; "launch-fleet: live check passedness: not the pass record")' -- check < /dev/null
expect 'R6: each unhandled evidence comment gets its own verification action' 0 check.json 'all_closed | say(10; 1002; "11:20"; "launch-fleet: look: live check not recorded as passed") | say(10; 1003; "11:30"; "Synthetic evidence one.") | say(10; 1004; "11:35"; "Synthetic evidence two.")' -- check <<EOF
look #10: live check evidence to verify in comment 1003
look #10: live check evidence to verify in comment 1004
EOF

### Complete comment histories (#1002), through check and wake

expect 'history: a 51-comment ticket retains its builder' 0 check.json 'issue(12; .comments += discussion(50))' -- check < /dev/null
log_has 'history: a 51-comment ticket retains its builder' 1 '^issue comments 12 page=1$'
expect 'history: a 120-comment ticket retains its wait on check' 0 check.json "$WAIT12 | $MERGE71 | issue(12; .comments += discussion(118))" -- check <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
log_has 'history: a 120-comment ticket retains its wait on check' 1 '^issue comments 12 page=1$'
log_has 'history: a 120-comment ticket retains its wait on check' 1 '^issue comments 12 page=2$'
expect 'history: a 120-comment ticket retains its wait on wake' 0 check.json "$WAIT12 | $MERGE71 | issue(12; .comments += discussion(118))" -- wake 12 <<EOF
resume #12: #71 merged; tell its builder, thread thr_syn12 (wait comment 1202)
EOF
log_has 'history: a 120-comment ticket retains its wait on wake' 1 '^issue comments 12 page=1$'
log_has 'history: a 120-comment ticket retains its wait on wake' 1 '^issue comments 12 page=2$'
expect 'history: a 51-comment PR retains its reviewer' 0 check.json 'reviewing31 | pull(31; .comments += discussion(50))' -- check <<EOF
check review #31 for #12 at $S31: no verdict 30 minutes after "review started $S31, thread thr_synrev31"; read thread thr_synrev31 and tell it again (its record: comment 3101)
EOF
expect 'history: a 120-comment PR retains its verdict on wake' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "VERDICT: APPROVE at \(sha(31))") | pull(31; .comments += discussion(118))' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
log_has 'history: a 120-comment PR retains its verdict on wake' 1 '^issue comments 31 page=1$'
log_has 'history: a 120-comment PR retains its verdict on wake' 1 '^issue comments 31 page=2$'
# #1057: the verdict itself must be read from page 2, not merely paginated past.
expect 'history: a verdict on page 2 permits a merge on wake' 0 check.json 'reviewing31 | pull(31; .comments += discussion(118)) | pr_say(31; 3102; "11:50"; "VERDICT: APPROVE at \(sha(31))")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
log_has 'history: a verdict on page 2 permits a merge on wake' 1 '^issue comments 31 page=1$'
log_has 'history: a verdict on page 2 permits a merge on wake' 1 '^issue comments 31 page=2$'
expect 'history: a 120-comment spec retains its approval' 0 check.json 'merge12 | issue(10; .comments += discussion(119))' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'history: a 120-comment standalone issue retains its approval' 0 check.json 'own_approval(70; 7002; "10:00") | issue(70; .comments += discussion(118))' -- wake 70 <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'history: an unreadable standalone history cannot start' 0 check.json 'own_approval(70; 7002; "10:00") | issue(70; .comments += discussion(118))' FAKE_GH_FAIL=issue_comments_70_page=2 -- wake 70 <<EOF
look #70: comment history could not be read in full
EOF
expect 'history: an unreadable spec history cannot start its tickets' 0 check.json 'merge12 | issue(10; .comments += discussion(119))' FAKE_GH_FAIL=issue_comments_10_page=2 -- check <<EOF
look #10: comment history could not be read in full
EOF
expect 'history: an unreadable third page cannot archive a closed ticket' 0 check.json 'merge12 | issue(12; .comments += discussion(118))' FAKE_GH_PAGE=50 FAKE_GH_FAIL=issue_comments_12_page=3 -- wake 12 <<EOF
look #12: comment history could not be read in full
EOF
log_has 'history: an unreadable third page cannot archive a closed ticket' 1 '^issue comments 12 page=1$'
log_has 'history: an unreadable third page cannot archive a closed ticket' 1 '^issue comments 12 page=2$'
log_has 'history: an unreadable third page cannot archive a closed ticket' 1 '^issue comments 12 page=3$'

expect 'history: a closed ticket cannot hide an unreadable PR history' 0 check.json 'merge12 | pr_say(22; 2201; "10:00"; "launch-fleet: review started \(sha(22)), thread thr_synrev22") | pull(22; .comments += discussion(119))' FAKE_GH_FAIL=issue_comments_22_page=2 -- wake 12 <<EOF
look #22: comment history could not be read in full
EOF

# R1: a transient read failure must not close the spec while its agents
# may still need archiving. Closing the spec would stop their future checks.
CLOSING_HISTORY='all_closed | issue(12; .comments |= map(select(.id != 1202)))
  | say(10; 1002; "11:30"; "launch-fleet: spec summary")'
expect 'history: an unreadable ticket cannot close its spec' 0 check.json "$CLOSING_HISTORY" FAKE_GH_FAIL=issue_comments_12_page=1 -- check <<EOF
look #12: comment history could not be read in full
EOF
expect 'history: an unreadable linked PR cannot close its spec' 0 check.json "$CLOSING_HISTORY" FAKE_GH_FAIL=issue_comments_22_page=1 -- check <<EOF
look #22: comment history could not be read in full
EOF

### The check: what it can't read in full

expect 'an unreadable second ticket comment page: look' 0 check.json 'issue(12; .comments += discussion(119))' FAKE_GH_FAIL=issue_comments_12_page=2 -- check <<EOF
look #12: comment history could not be read in full
EOF
expect 'a spec with more than 100 tickets: look' 0 check.json 'issue(10; .subIssuesTruncated = true)' -- check <<EOF
look #10: more than 100 tickets, so its graph can't all be read
EOF
expect 'an unreadable second PR comment page: look' 0 check.json 'reviewing31 | pull(31; .comments += discussion(119))' FAKE_GH_FAIL=issue_comments_31_page=2 -- check <<EOF
look #31: comment history could not be read in full
EOF
expect 'a ticket look already raised is not raised again' 0 check.json 'issue(12; .labels += [range(1; 22) | "synthetic-label-\(.)"]) | say(12; 1202; "11:00"; "launch-fleet: look: more than 20 labels")' -- check < /dev/null
expect 'a pull request look already raised is not raised again' 0 check.json 'pr31 | pull(31; .base = "release-1") | pr_say(31; 3101; "11:00"; "launch-fleet: look: its base is release-1, not main")' -- check < /dev/null
expect 'a spec look already raised is not raised again' 0 check.json 'issue(10; .subIssuesTruncated = true) | say(10; 1002; "11:00"; "launch-fleet: look: more than 100 tickets, so its graph can'"'"'t all be read")' -- check < /dev/null

### Errors: exit 2, the reason on stderr, nothing on stdout

expect 'a failed GitHub read' 2 check.json . FAKE_GH_FAIL=graphql_Spec_ -- check <<EOF
the GitHub query Spec failed
EOF
expect 'a failed first read fails loudly: an empty answer is not a spent allowance' 2 check.json . FAKE_GH_FAIL=graphql_Specs -- check <<EOF
the GitHub query Specs failed
EOF
expect 'a wake'"'"'s failed first read fails loudly' 2 check.json 'pr31' FAKE_GH_FAIL=graphql_Item -- wake 31 <<EOF
the GitHub query Item failed
EOF
expect 'GraphQL errors' 2 check.json . FAKE_GH_ERRORS=Specs -- check <<EOF
the GitHub query Specs answered with errors
EOF
expect 'no fleet settings' 2 check.json 'del(.files["docs/agents/fleet.md"])' -- check <<EOF
can't read docs/agents/fleet.md
EOF
expect 'fleet settings with no CI checks' 2 check.json '.files["docs/agents/fleet.md"] |= sub("\\| `build`[^\n]*\n\\| `test`[^\n]*\n"; "")' -- check <<EOF
docs/agents/fleet.md lists no CI checks
EOF
expect 'triage labels missing a role' 2 check.json '.files["docs/agents/triage-labels.md"] |= sub("\\| `wontfix`[^\n]*\n"; "")' -- frontier <<EOF
docs/agents/triage-labels.md does not map all five roles
EOF
expect 'a failed read of a merge'"'"'s files' 2 check.json 'contract23' FAKE_GH_FAIL=files_23 -- holds <<EOF
can't read the files of #23
EOF
expect 'a failed read of the branches' 2 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: started, thread thr_syn13")' FAKE_GH_FAIL=refs -- check <<EOF
can't read the branches of #13
EOF
expect 'revision.sh fails: nothing starts, and the check fails' 2 check.json 'merge12' FAKE_GH_FAIL=issue_view_13_body -- check <<EOF
to-tickets’ revision.sh failed on #10
EOF
expect 'revision.sh missing when a ticket could start: the check fails' 2 check.json 'merge12' LAUNCH_FLEET_REVISION=/nonexistent/revision.sh -- frontier <<EOF
can't find to-tickets’ revision.sh
EOF
expect 'no jq' 2 check.json . PATH="$tmp/nojq" -- check <<EOF
jq is not installed
EOF
expect 'GH_REPO not owner/name' 2 check.json . GH_REPO=nonsense -- check <<EOF
GH_REPO must be owner/name
EOF
expect 'an unknown command' 2 check.json . -- launch <<EOF
usage: fleet.sh
EOF
expect 'LAUNCH_FLEET_NOW not a number' 2 check.json . LAUNCH_FLEET_NOW=soon -- check <<EOF
LAUNCH_FLEET_NOW must be a number of seconds
EOF

### The frontier

FRONTIER='#41 G1: gadget reader
#45 G5: gadget import
#55 G11: gadget filter'
expect 'the frontier: verified merges in any version, the ready label, approved, not started' 0 frontier.json . -- frontier <<EOF
$FRONTIER
EOF
expect 'the frontier read in pages of one' 0 frontier.json . FAKE_GH_PAGE=1 -- frontier <<EOF
$FRONTIER
EOF
log_has 'the frontier read in pages of one' 1 '^graphql Specs'
log_has 'the frontier read in pages of one' 20 '^issues page='
# F6 (#1353): only a hard blocker holds a start. A `file` link (the two only
# share files) is context; owned paths that collide with a running ticket, or
# with a lower-numbered ticket starting in the same read, hold it instead.
OWNS='def owns($n; $line; $links): issue($n; .body = "## Owned paths\n\n- \($line)\n\n**Relies on:** `docs/gadget.md`\n\n## Links\n\n\($links)\n");'
expect 'F6: a ticket whose only open link is context starts' 0 frontier.json "$OWNS"' owns(43; "`gadget/spike.md`"; "none") | owns(42; "`gadget/writer.md`"; "- #43 file: `gadget/notes.md`")' -- frontier <<EOF
#41 G1: gadget reader
#42 G2: gadget writer
#45 G5: gadget import
#55 G11: gadget filter
EOF
expect 'F6: an open hard blocker still holds a start' 0 frontier.json "$OWNS"' owns(42; "`gadget/writer.md`"; "- #43 real: the spike findings, which the writer follows")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a blocker with no link line is hard' 0 frontier.json "$OWNS"' owns(42; "`gadget/writer.md`"; "- #44 file: `gadget/notes.md`")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a path colliding with a running ticket holds a start' 0 frontier.json "$OWNS"' owns(48; "`gadget/`"; "none") | owns(41; "`gadget/reader.md`"; "none")' -- frontier <<EOF
#45 G5: gadget import
#55 G11: gadget filter
EOF
expect 'F6: shared or other-repository paths do not collide' 0 frontier.json "$OWNS"' owns(48; "`gadget/*.md` (shared: the colours line)"; "none") | owns(41; "`gadget/reader.md` (shared: the reader line)"; "none") | owns(49; "`gadget/` in `synthetic-owner/other-repo`"; "none")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: of two colliding ready tickets the lower starts first' 0 frontier.json "$OWNS"' owns(45; "`gadget/io/`"; "none") | owns(55; "`gadget/io/filter.md`"; "none")' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
EOF
# R1 (review of #1353): a file link is context only when check-links.sh
# reads it as a file link naming a file, its blocker's owned paths are read,
# and none of the ticket's relied-on inputs is the blocker's or the link's.
SPIKE=' owns(43; "`gadget/spike.md`"; "none") |'
expect 'F6: an empty file reason is unlabelled, so hard' 0 frontier.json "$OWNS$SPIKE"' owns(42; "`gadget/writer.md`"; "- #43 file:")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a malformed Links section labels nothing' 0 frontier.json "$OWNS$SPIKE"' owns(42; "`gadget/writer.md`"; "- #43 file: `gadget/notes.md`\nnone")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a file link whose blocker owns a relied-on input is hard' 0 frontier.json "$OWNS"' owns(43; "`docs/`"; "none") | owns(42; "`gadget/writer.md`"; "- #43 file: `gadget/notes.md`")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a file link naming a relied-on input is hard' 0 frontier.json "$OWNS$SPIKE"' owns(42; "`gadget/writer.md`"; "- #43 file: `docs/gadget.md`")' -- frontier <<EOF
$FRONTIER
EOF
expect 'F6: a file link whose blocker owns no path it can read is hard' 0 frontier.json "$OWNS"' owns(42; "`gadget/writer.md`"; "- #43 file: `gadget/notes.md`")' -- frontier <<EOF
$FRONTIER
EOF
# R3: approval's fnmatch patterns, brackets and question marks too.
expect 'F6: a bracket or question-mark pattern collides as approval reads it' 0 frontier.json "$OWNS"' owns(48; "`gadget/[rw]eader.md`"; "none") | owns(41; "`gadget/reader.md`"; "none") | owns(49; "`gadget/fil?er.md`"; "none") | owns(55; "`gadget/filter.md`"; "none")' -- frontier <<EOF
#45 G5: gadget import
EOF
# R4: admitted in number order, each against running work and those admitted.
expect 'F6: a ticket held only by an unadmitted collider still starts' 0 frontier.json "$OWNS"' owns(41; "`gadget/reader.md`"; "none") | owns(45; "`gadget/`"; "none") | owns(55; "`gadget/writer.md`"; "none")' -- frontier <<EOF
#41 G1: gadget reader
#55 G11: gadget filter
EOF
expect 'a closed blocker is not enough: with a verified merge it is' 0 frontier.json 'merged_pr(74; 43; "09:00"; [])' -- frontier <<EOF
#41 G1: gadget reader
#42 G2: gadget writer
#45 G5: gadget import
#55 G11: gadget filter
EOF
# #2888: synthetic person completion evidence, through the public commands.
# A closed human blocker with a completion record frees its dependent; the
# existing merge-only cases never exercised a human blocker without a PR.
HUMAN43='issue(43; .labels = ["ready-for-human"])
  | say(43; 4301; "10:00"; "launch-fleet: complete: synthetic repository read-back in evidence/repository.txt")'
PERSON_FRONTIER='#41 G1: gadget reader
#42 G2: gadget writer
#45 G5: gadget import
#55 G11: gadget filter'
expect 'person blocker: closed human with evidence frees the frontier' 0 frontier.json "$HUMAN43" -- frontier <<EOF
$PERSON_FRONTIER
EOF
expect 'person blocker: person label with evidence also frees the frontier' 0 frontier.json "$HUMAN43 | issue(43; .labels = [\"person\"])" -- frontier <<EOF
$PERSON_FRONTIER
EOF
expect 'person blocker: configured human label frees the frontier' 0 frontier.json "$HUMAN43 | issue(43; .labels = [\"human-step\"]) @@then@@ .files[\"docs/agents/triage-labels.md\"] |= sub(\"[|] \`ready-for-human\` [|] \`ready-for-human\`\"; \"| \`ready-for-human\` | \`human-step\`\")" -- frontier <<EOF
$PERSON_FRONTIER
EOF
expect 'person blocker: closed human without a record stays blocked' 0 frontier.json "$HUMAN43 | issue(43; .comments = [])" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: empty completion has no evidence' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].body = \"launch-fleet: complete:   \")" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: prose mentioning completion is not a record' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].body = \"Discussion: launch-fleet: complete: synthetic evidence\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: completion without the colon is not the record form' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].body = \"launch-fleet: completed synthetic evidence\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: reopened human with evidence stays blocked' 0 frontier.json "$HUMAN43 | issue(43; .state = \"OPEN\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: agent with completion still needs a merged PR' 0 frontier.json "$HUMAN43 | issue(43; .labels = [\"ready-for-agent\"])" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: unknown label with completion stays blocked' 0 frontier.json "$HUMAN43 | issue(43; .labels = [\"personality\"])" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: evidence on the dependent cannot complete the blocker' 0 frontier.json 'issue(43; .labels = ["ready-for-human"]) | say(42; 4201; "10:00"; "launch-fleet: complete: synthetic evidence")' -- frontier <<EOF
$FRONTIER
EOF
HUMAN12='issue(12; .state = "CLOSED" | .labels = ["ready-for-human"])
  | say(12; 1202; "11:05"; "launch-fleet: archived")
  | say(12; 1203; "11:06"; "launch-fleet: complete: synthetic read-back in evidence/repository.txt")
  | approve(10; 1002; "11:10"; 2; [11, [12, "ready-for-human"], 13, 14])'
expect 'person blocker: spec check starts the dependent' 0 check.json "$HUMAN12" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'person blocker: claim goes after human completion without a PR' 0 check.json "$HUMAN12 | say(13; 1301; \"11:58\"; \"launch-fleet: starting\")" -- claim 13 1301 <<EOF
go #13
EOF
expect 'person blocker: completion on an older comment page is read' 0 frontier.json "$HUMAN43 | issue(43; .comments += discussion(119))" -- frontier <<EOF
$PERSON_FRONTIER
EOF
expect 'person blocker: dual agent and human labels still require a merge' 0 frontier.json "$HUMAN43 | issue(43; .labels += [\"ready-for-agent\"])" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: quoted completion is not a record' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].body = \" > launch-fleet: complete: synthetic evidence\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: unreadable evidence stays blocked' 0 frontier.json "$HUMAN43" FAKE_GH_FAIL=issue_comments_43_page=1 -- frontier <<EOF
$FRONTIER
EOF
expect 'person blocker: spec cache begins without completion' 0 check.json "$HUMAN12 | issue(12; .comments |= map(select(.id != 1203)))" -- spec 10 <<EOF
look #12: closed person ticket needs launch-fleet: complete: <evidence>
EOF
again 'person blocker: spec cache warms without completion' '.' -- spec 10 <<EOF
look #12: closed person ticket needs launch-fleet: complete: <evidence>
EOF
again 'person blocker: added completion frees the cached dependent' 'say(12; 1203; "11:06"; "launch-fleet: complete: synthetic read-back in evidence/repository.txt")' -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
again 'person blocker: deleted completion blocks the cached dependent' 'issue(12; .comments |= map(select(.id != 1203)))' -- spec 10 <<EOF
look #12: closed person ticket needs launch-fleet: complete: <evidence>
EOF

# R1: closed person work must ask for the evidence record instead of silently
# holding its dependent. Existing frontier cases prove refusal, not this prompt.
MISSING_COMPLETION='closed person ticket needs launch-fleet: complete: <evidence>'
MISSING12="$HUMAN12 | issue(12; .comments |= map(select(.id != 1203)))"
expect 'R1 completion: spec asks for the missing evidence record' 0 check.json "$MISSING12" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
again 'R1 completion: recorded request is quiet' 'say(12; 1204; "11:20"; "launch-fleet: look: closed person ticket needs launch-fleet: complete: <evidence>")' -- spec 10 < /dev/null
again 'R1 completion: adding evidence after the request frees the dependent' 'say(12; 1205; "11:30"; "launch-fleet: complete: synthetic read-back in evidence/repository.txt")' -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'R1 completion: project check asks for the record' 0 check.json "$MISSING12" -- check <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'R1 completion: targeted wake asks for the record' 0 check.json "$MISSING12" -- wake 12 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'R1 completion: person label asks for the record' 0 check.json "$MISSING12 | issue(12; .labels = [\"person\"])" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'R1 completion: empty evidence still asks for the record' 0 check.json "$HUMAN12 | edit(12; 1203; \"11:06\"; \"launch-fleet: complete:   \")" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'R1 completion: an agent ticket gets no person-completion request' 0 check.json "$MISSING12 | issue(12; .labels = [\"ready-for-agent\"])" -- spec 10 < /dev/null
expect 'R1 completion: unrelated look does not suppress the request' 0 check.json "$MISSING12 | say(12; 1204; \"11:20\"; \"launch-fleet: look: synthetic old concern\")" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'R1 completion: request coexists with archiving its builder' 0 check.json "$MISSING12 | issue(12; .comments |= map(select(.id != 1202)))" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
archive #12: closed; archive thr_syn12
EOF
# A closed human blocker may live outside the spec being checked.
EXTERNAL_PERSON='merge12 | closed_single(71; "11:00") | issue(71; .labels = ["ready-for-human"])
  | issue(13; .blockedBy = [71]) | approve(10; 1002; "11:10"; 2; [11, 12, 13, 14])'
expect 'R1 external: spec asks for a person blocker outside its graph' 0 check.json "$EXTERNAL_PERSON" -- spec 10 <<EOF
look #71: $MISSING_COMPLETION
EOF
expect 'R1 external: dependent wake asks for its person blocker record' 0 check.json "$EXTERNAL_PERSON" -- wake 13 <<EOF
look #71: $MISSING_COMPLETION
EOF
again 'R1 external: completion lets the dependent wake proceed' 'say(71; 7101; "11:30"; "launch-fleet: complete: synthetic read-back in evidence/repository.txt")' -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF
# #641: every record the fleet acts on must come from the factory's own
# identity, the record authors docs/agents/fleet.md names. An outsider's record
# of each kind is ignored; the factory's own records still work. A person
# blocker counts as done only when it was closed as completed.
expect 'record authors: an outsider completion keeps the dependent blocked' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].author = outsider)" -- frontier <<EOF
$FRONTIER
EOF
expect 'record authors: a completion with no author keeps the dependent blocked' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].author = null)" -- frontier <<EOF
$FRONTIER
EOF
expect 'record authors: the owner account completion frees the dependent, in any case' 0 frontier.json "$HUMAN43 | issue(43; .comments[0].author = \"synthetic-owner\")" -- frontier <<EOF
$PERSON_FRONTIER
EOF
expect 'record authors: a not-planned close does not complete a person blocker' 0 frontier.json "$HUMAN43 | issue(43; .stateReason = \"NOT_PLANNED\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'record authors: a duplicate close does not complete a person blocker' 0 frontier.json "$HUMAN43 | issue(43; .stateReason = \"DUPLICATE\")" -- frontier <<EOF
$FRONTIER
EOF
expect 'record authors: spec asks for the record despite an outsider completion' 0 check.json "$HUMAN12 | issue(12; .comments |= map(if .id == 1203 then .author = outsider else . end))" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'record authors: a not-planned person ticket blocks its dependent and says why' 0 check.json "$HUMAN12 | issue(12; .stateReason = \"NOT_PLANNED\")" -- spec 10 <<EOF
look #12: closed person ticket was closed as not planned, so it completes nothing
EOF
expect 'record authors: an outsider look does not settle the request' 0 check.json "$MISSING12 | by(12; 1204; \"11:20\"; outsider; \"launch-fleet: look: $MISSING_COMPLETION\")" -- spec 10 <<EOF
look #12: $MISSING_COMPLETION
EOF
expect 'record authors: an outsider starting record is not a claim' 0 check.json "$HUMAN12 | by(13; 1301; \"11:30\"; outsider; \"launch-fleet: starting\")" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'record authors: an outsider started record is not a start' 0 check.json "$HUMAN12 | by(13; 1301; \"11:30\"; outsider; \"launch-fleet: started\")" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'record authors: the owner account starting record is a claim' 0 check.json "$HUMAN12 | by(13; 1301; \"11:58\"; \"Synthetic-Owner\"; \"launch-fleet: starting\")" -- claim 13 1301 <<EOF
go #13
EOF
expect 'record authors: claim refuses an outsider claim' 2 check.json "$HUMAN12 | by(13; 1301; \"11:58\"; outsider; \"launch-fleet: starting\")" -- claim 13 1301 <<EOF
fleet.sh: can't find comment 1301 on #13
EOF
NO_VERDICT31="check review #31 for #12 at $S31: no verdict 30 minutes after \"review started $S31, thread thr_synrev31\"; read thread thr_synrev31 and tell it again (its record: comment 3101)"
expect 'record authors: an outsider APPROVE does not merge' 0 check.json 'reviewing31 | pr_by(31; 3102; "11:30"; outsider; "VERDICT: APPROVE at \(sha(31))")' -- check <<EOF
$NO_VERDICT31
EOF
expect 'record authors: a CHANGES with no author sends no findings' 0 check.json 'reviewing31 | pr_by(31; 3102; "11:30"; null; "VERDICT: CHANGES at \(sha(31))")' -- check <<EOF
$NO_VERDICT31
EOF
expect 'record authors: an outsider review started record starts no review span' 0 check.json 'pr31 | pr_by(31; 3101; "11:10"; outsider; "launch-fleet: review started \(sha(31)), thread thr_synrev31")' -- check <<EOF
review #31 for #12 at $S31: first review
EOF
expect 'record authors: an outsider plan approval approves nothing' 0 check.json "$HUMAN12 | issue(10; .comments |= map(.author = outsider))" -- spec 10 < /dev/null
expect 'record authors: an outsider approval on its own starts nothing' 0 check.json 'own_approval(70; 7002; "09:00") | issue(70; .comments[-1].author = outsider)' -- check < /dev/null
expect 'record authors: the factory approval on its own still starts' 0 check.json 'own_approval(70; 7002; "09:00")' -- check <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'record authors: an outsider asked-the-orchestrator record settles no question' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "Which store?") | by(12; 1203; "11:05"; outsider; "launch-fleet: asked the orchestrator")' -- check <<EOF
needs-info #12: a question for the orchestrator
EOF
expect 'record authors: an outsider reply is no new question' 0 check.json 'issue(12; .labels += ["needs-answer"]) | say(12; 1202; "11:00"; "Which store?") | say(12; 1203; "11:05"; "launch-fleet: asked the orchestrator") | by(12; 1204; "11:30"; outsider; "And one more thing?")' -- check < /dev/null
expect 'record authors: an outsider nightly record does not suppress the alert' 0 check.json 'nightly | nightly_record(9001; "launch-fleet: nightly told 801 attempt 1") | .commitComments[-1].author = outsider' -- check <<EOF
nightly red 801 attempt 1 at $(sha 81): https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)
EOF
expect 'record authors: no record authors setting stops the check' 2 check.json '.files["docs/agents/fleet.md"] |= sub("[|] Record authors [|][^\n]*\n"; "")' -- check <<EOF
fleet.sh: docs/agents/fleet.md names no record authors (its "## GitHub identity" table's "Record authors" row)
EOF
# R3: the row is exactly "| Record authors | <cell> |": anything after the value cell refuses it too.
for row in '| Record authors | `synthetic-factory[bot]`, Synthetic-Owner |' '| Record authors | `synthetic-factory[bot]` `Synthetic-Owner` |' '| Record authors | `synthetic-factory[bot]`, `Synthetic-Owner`; extra |' '| Record authors | `synthetic-factory[bot]` | `Synthetic-Owner`'; do
  expect "record authors: a partly malformed row stops the check: $row" 2 check.json "$HUMAN12 | say(13; 1301; \"11:30\"; \"launch-fleet: starting\") | .files[\"docs/agents/fleet.md\"] |= sub(\"[|] Record authors [|][^\\n]*\"; \"$row\")" -- spec 10 <<EOF
fleet.sh: docs/agents/fleet.md names no record authors (its "## GitHub identity" table's "Record authors" row)
EOF
done
expect 'record authors: a malformed record author stops the check' 2 check.json '.files["docs/agents/fleet.md"] |= sub("`Synthetic-Owner`"; "`synthetic owner`")' -- check <<EOF
fleet.sh: docs/agents/fleet.md names no record authors (its "## GitHub identity" table's "Record authors" row)
EOF
expect 'a merge into a release branch is not a verified merge: into main it is' 0 frontier.json 'pull(72; .base = "main")' -- frontier <<EOF
#41 G1: gadget reader
#44 G4: gadget export
#45 G5: gadget import
#55 G11: gadget filter
EOF
expect 'a reopened blocker holds its ticket: closed again, it does not' 0 frontier.json 'issue(63; .state = "CLOSED")' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#55 G11: gadget filter
#56 G12: gadget share
EOF
expect 'cross-version: an unmerged blocker in the older version holds its ticket' 0 frontier.json 'pull(71; .state = "OPEN" | .mergedAt = null)' -- frontier <<EOF
#45 G5: gadget import
#55 G11: gadget filter
EOF
expect 'missing labels: no ready label, no start; with it, a start' 0 frontier.json 'issue(41; .labels = []) | issue(46; .labels = ["ready-for-agent"])' -- frontier <<EOF
#45 G5: gadget import
#46 G6: gadget icons
#55 G11: gadget filter
EOF
expect 'a ticket waiting on an answer starts once the label is gone' 0 frontier.json 'issue(47; .labels = ["ready-for-agent"])' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#47 G7: gadget sizes
#55 G11: gadget filter
EOF
expect 'an approval for an older revision starts nothing: a new revision does' 0 frontier.json 'approve(50; 5002; "11:00"; 2; [51, 52])' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#51 E1: first
#52 E2: second, renamed after the approval
#55 G11: gadget filter
EOF
expect 'duplicate starts: a started, claimed or pull-requested ticket is not started again; without those, it is' 0 frontier.json 'issue(48; .comments = []) | issue(54; .comments = []) | .pulls |= map(select(.number != 99))' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#48 G8: gadget colours
#49 G9: gadget search
#54 G10: gadget sort
#55 G11: gadget filter
EOF
expect 'a low finding added after the approval starts once a new revision covers it' 0 frontier.json 'approve(40; 4002; "11:00"; 2; [41, 42, 43, 44, 45, 46, 47, 48, 49, 54, 55, 56, 57])' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#55 G11: gadget filter
#57 G13: a low finding, filed after the approval
EOF
expect 'a relied-on contract change leaves a ticket on the frontier' 0 frontier.json 'issue(41; .body = "**Relies on:** `contracts/gadget.v1.md`") | merged_pr(75; 98; "10:00"; [changed("contracts/gadget.v1.md"; "modified")])' -- frontier <<EOF
#41 G1: gadget reader
#45 G5: gadget import
#55 G11: gadget filter
EOF
expect 'the check over several fleets at once' 0 frontier.json . -- check <<EOF
start #41: G1: gadget reader (spec #40)
start #45: G5: gadget import (spec #40)
needs-info #47: a question for the orchestrator
check start #48: thread thr_syn48, no branch 30 minutes after the start
start #55: G11: gadget filter (spec #40; retry after "start refused: plan limit reached")
look #40: open sub-issue #57 is not in the approved plan
look #40: planned #43 is closed without a verified merge
re-approve #50: changed since revision 1 (fingerprint now $(fp12 frontier.json . 50))
look #50: open sub-issue #53 is not in the approved plan
look #60: planned #62 is closed without a verified merge
EOF

### Budget: GitHub's allowance (ClosedWiz#189)

# The literal costs below were measured through the fake transport. The
# small fixture asks five GraphQL reads (metadata, spec, blocker closures,
# single, merges), plus 26 REST GETs and the repository privacy read: 32 questions. A repeat revalidates REST
# responses; 304s cost no primary allowance. Revision reads still cost one
# GraphQL point each. The old bundled query cost six points in nine calls.
ERR='fleet.sh: used 5 GitHub points in 32 questions, 0 unchanged; 5000 of 5000 left'
expect 'budget: the check reports the points and questions it used, on stderr' 0 check.json . -- check < /dev/null
log_has 'budget: the check reports the points and questions it used, on stderr' 0 '^graphql Singles cursor=none$'
log_has 'budget: the check reports the points and questions it used, on stderr' 2 '^search issues page=1$'
log_has 'budget: the check reports the points and questions it used, on stderr' 1 '^graphql Nodes count=1$'
ERR='fleet.sh: used 15 GitHub points in 44 questions, 0 unchanged; 5000 of 5000 left'
expect 'budget: revision.sh'"'"'s questions are counted, a point each' 0 check.json 'merge12' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF

# A quiet back-off: when less than a quarter of the hour's points is left, or
# none, the check prints one line, asks nothing more and exits 0.
ERR='fleet.sh: backing off: 1249 of 5000 GitHub points left, under the 1250 kept for builders and reviewers, until 2026-11-01T13:00:00Z'
expect 'budget: a low allowance backs off: one line, exit 0, nothing more asked' 0 check.json 'merge12' FAKE_GH_REMAINING=1249 -- check < /dev/null
log_has 'budget: a low allowance backs off: one line, exit 0, nothing more asked' 1 '.'
ERR='fleet.sh: used 15 GitHub points in 44 questions, 0 unchanged; 1250 of 5000 left'
expect 'budget: a quarter of the allowance left still checks' 0 check.json 'merge12' FAKE_GH_REMAINING=1250 -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
ERR="fleet.sh: backing off: GitHub's allowance has run out, until it resets"
expect 'budget: an allowance that has run out backs off: one line, exit 0' 0 check.json 'merge12' FAKE_GH_RATE_LIMITED=Specs -- check < /dev/null
log_has 'budget: an allowance that has run out backs off: one line, exit 0' 1 '.'
ERR="fleet.sh: backing off: GitHub's allowance has run out, until it resets"
expect 'budget: a spent allowance spelled RATE_LIMITED backs off too' 0 check.json 'merge12' FAKE_GH_RATE_LIMITED=Specs FAKE_GH_RATE_TYPE=RATE_LIMITED -- check < /dev/null
log_has 'budget: a spent allowance spelled RATE_LIMITED backs off too' 1 '.'
expect 'budget: an allowance that runs out part-way still fails loudly' 2 check.json 'merge12' FAKE_GH_RATE_LIMITED=Spec -- check <<EOF
the GitHub query Spec failed
EOF
expect 'budget: an allowance GitHub does not give as a number fails loudly' 2 check.json . FAKE_GH_REMAINING=lots -- check <<EOF
the GitHub query Specs did not say what it cost and what is left
EOF

# Several fleets: current measured costs are 43 points / 127 questions
# cold and 6 / 83 warm (including the repository privacy read). Conditional REST increases raw calls but makes
# unchanged REST answers free; fingerprint reuse still avoids revision reads.
ERR='fleet.sh: used 43 GitHub points in 127 questions, 0 unchanged; 5000 of 5000 left'
expect 'budget: several fleets, the first check' 0 frontier.json . -- check <<EOF
start #41: G1: gadget reader (spec #40)
start #45: G5: gadget import (spec #40)
needs-info #47: a question for the orchestrator
check start #48: thread thr_syn48, no branch 30 minutes after the start
start #55: G11: gadget filter (spec #40; retry after "start refused: plan limit reached")
look #40: open sub-issue #57 is not in the approved plan
look #40: planned #43 is closed without a verified merge
re-approve #50: changed since revision 1 (fingerprint now $(fp12 frontier.json . 50))
look #50: open sub-issue #53 is not in the approved plan
look #60: planned #62 is closed without a verified merge
EOF
ERR='fleet.sh: used 6 GitHub points in 83 questions, 77 unchanged; 5000 of 5000 left'
again 'budget: several fleets, the next check: the same lines, about a quarter of the points' . -- check <<EOF
start #41: G1: gadget reader (spec #40)
start #45: G5: gadget import (spec #40)
needs-info #47: a question for the orchestrator
check start #48: thread thr_syn48, no branch 30 minutes after the start
start #55: G11: gadget filter (spec #40; retry after "start refused: plan limit reached")
look #40: open sub-issue #57 is not in the approved plan
look #40: planned #43 is closed without a verified merge
re-approve #50: changed since revision 1 (fingerprint now $(fp12 frontier.json . 50))
look #50: open sub-issue #53 is not in the approved plan
look #60: planned #62 is closed without a verified merge
EOF
log_has 'budget: several fleets, the next check: the same lines, about a quarter of the points' 82 '.'
log_has 'budget: several fleets, the next check: the same lines, about a quarter of the points' 0 '^issue view'
log_has 'budget: several fleets, the next check: the same lines, about a quarter of the points' 0 '^graphql Spec number=80'

# A spec's fingerprint is reused until the spec (its updatedAt) or anything
# revision.sh reads changes: each change below, one after another, is read again.
C1='issue(13; .body += "One more line.")'
C2="$C1 | issue(13; .title = \"W3: widget page, renamed\")"
C3="$C2 | issue(14; .blockedBy = [12])"
C4="$C3 | issue(10; .body = \"The spec, edited.\")"
C5="$C4 | issue(14; .parent = null)"
C6="$C5 | ticket(15; \"W5: a low finding\"; [\"needs-triage\"]; [])"
expect 'budget: the first check reads the plan once' 0 check.json 'merge12' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'budget: the first check reads the plan once' 1 '^issue view 10 subIssues$'
again 'budget: the plan unchanged: its fingerprint is reused, no revision read' . -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'budget: the plan unchanged: its fingerprint is reused, no revision read' 0 '^issue view'
again 'budget: a ticket body edited since the last check is read again' "$C1" -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C1" 10))
EOF
log_has 'budget: a ticket body edited since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: a stale plan unchanged since: the reused fingerprint still stops starts' . -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C1" 10))
EOF
log_has 'budget: a stale plan unchanged since: the reused fingerprint still stops starts' 0 '^issue view'
again 'budget: a title changed since the last check is read again' 'issue(13; .title = "W3: widget page, renamed")' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C2" 10))
EOF
log_has 'budget: a title changed since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: a blocker changed since the last check is read again' 'issue(14; .blockedBy = [12])' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C3" 10))
EOF
log_has 'budget: a blocker changed since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: the spec body changed since the last check is read again' 'issue(10; .body = "The spec, edited.")' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C4" 10))
EOF
log_has 'budget: the spec body changed since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: a ticket dropped since the last check is read again' 'issue(14; .parent = null)' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C5" 10))
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'budget: a ticket dropped since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: a ticket added since the last check is read again' 'ticket(15; "W5: a low finding"; ["needs-triage"]; [])' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C6" 10))
look #10: open sub-issue #15 is not in the approved plan
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'budget: a ticket added since the last check is read again' 1 '^issue view 10 subIssues$'
again 'budget: the spec updated since the last check is read again' 'issue(10; .updatedAt = at("11:50"))' -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C6" 10))
look #10: open sub-issue #15 is not in the approved plan
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'budget: the spec updated since the last check is read again' 1 '^issue view 10 subIssues$'
if [ -n "$last" ]; then
  find "$last/cache" -type f -exec sh -c 'printf "damaged\n" > "$1"' _ {} \; || bad 'budget: a damaged cache' "can't damage it"
fi
again 'budget: a damaged cache is not trusted: read again' . -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C6" 10))
look #10: open sub-issue #15 is not in the approved plan
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'budget: a damaged cache is not trusted: read again' 1 '^issue view 10 subIssues$'
{ cat "$FIX/revision.sh" && echo '# changed'; } > "$tmp/revision-changed.sh" || bad 'budget: another revision.sh' "can't copy it"
again 'budget: a fingerprint from another revision.sh is not reused' . LAUNCH_FLEET_REVISION="$tmp/revision-changed.sh" -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "merge12 @@then@@ $C6" 10))
look #10: open sub-issue #15 is not in the approved plan
look #10: planned #14 is not a sub-issue of the spec
EOF
log_has 'budget: a fingerprint from another revision.sh is not reused' 1 '^issue view 10 subIssues$'

# A plan edited between the check's read and revision.sh's: a fingerprint is
# kept only when revision.sh printed the plan the check read (its key), so a
# plan that flaps never leaves the approved fingerprint under a changed plan's
# key. The first check still answers from revision.sh, as before #189 (Sol R2).
expect 'budget: revision.sh read another plan than the check: nothing is kept (Sol R2)' 0 check.json 'merge12 @@then@@ issue(13; .body += "The plan changed.")' FAKE_GH_REVISION_WORLD=approved.json -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
again 'budget: the next check reads the plan again and starts nothing (Sol R2)' . -- check <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json 'merge12 @@then@@ issue(13; .body += "The plan changed.")' 10))
EOF
log_has 'budget: the next check reads the plan again and starts nothing (Sol R2)' 1 '^issue view 10 subIssues$'

# The revision text the check makes from its own read is revision.sh's to the
# byte, ticked task boxes and all: a plan with one is cached like any other.
TICKED='merge12 | issue(13; .body += "\n- [ ] the page lists every widget\n\t* [X]\tand sorts them") @@then@@ issue(13; .body |= sub("- \\[ \\]"; "- [x]"))'
expect 'budget: a plan with ticked task boxes: the first check (Sol R2)' 0 check.json "$TICKED" -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
again 'budget: a plan with ticked task boxes is cached like any other (Sol R2)' . -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'budget: a plan with ticked task boxes is cached like any other (Sol R2)' 0 '^issue view'

# A spec with no open ticket is skipped once a check found nothing due on it,
# until its spec or ticket counts/state change; polish follow-ups do not matter.
# Keep the unapproved graph's pinned fingerprint so its later approval is
# current; again() changes an existing world and never expands @@FP@@.
QUIET='all_closed | issue(10; .comments[0].body |= sub("Plan graph approved by"; "Plan graph pending by")) | followup(16; "OPEN"; "Follow-up of #12 (spec #10): R3 [low] a wording nit.")'
expect 'budget: a spec with no open ticket and nothing due' 0 check.json "$QUIET" -- check < /dev/null
log_has 'budget: a spec with no open ticket and nothing due' 1 '^graphql Spec number=10'
again 'budget: a quiet spec with no open ticket is not read again' . -- check < /dev/null
log_has 'budget: a quiet spec with no open ticket is not read again' 0 '^graphql Spec number='
again 'budget: a quiet spec is read again once a comment lands on it' 'say(10; 1003; "11:40"; "A note from the user.")' -- check < /dev/null
log_has 'budget: a quiet spec is read again once a comment lands on it' 1 '^graphql Spec number=10'
again 'budget: and is quiet again' . -- check < /dev/null
log_has 'budget: and is quiet again' 0 '^graphql Spec number='
again 'budget: polish follow-ups do not invalidate a quiet spec' 'issue(16; .state = "CLOSED")' -- check < /dev/null
log_has 'budget: polish follow-ups do not invalidate a quiet spec' 0 '^graphql Spec number='
# A claim's own record on a closed ticket unsettles it (Sol R1), so the claim
# is a pair of its own: the quiet spec it lands in is skipped by a check, but
# a claim reads its own ticket whatever the cache says (#259).
expect 'budget: a quiet spec, before a claim' 0 check.json "$QUIET" -- check < /dev/null
again 'budget: a claim reads its own ticket, whatever the quiet cache says' 'say(13; 1301; "11:58"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
withdraw #13: it is closed
EOF
log_has 'budget: a claim reads its own ticket, whatever the quiet cache says' 1 '^graphql Item number=13 size=2$'
expect 'budget: a quiet spec, before a ticket reopens' 0 check.json "$QUIET" -- check < /dev/null
again 'budget: a quiet spec is read again once a ticket reopens' 'issue(13; .state = "OPEN") | issue(10; .comments[0].body |= sub("Plan graph pending by"; "Plan graph approved by"))' -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'budget: a quiet spec, before fleet.sh changes' 0 check.json "$QUIET" -- check < /dev/null
{ cat "$FLEET" && echo '# changed'; } > "$tmp/fleet-changed.sh" && cp "$HERE/records.py" "$tmp/records.py" || bad 'budget: another fleet.sh' "can't copy it"
RUN_FLEET=$tmp/fleet-changed.sh
again 'budget: a quiet spec is read again by a changed fleet.sh' . -- check < /dev/null
log_has 'budget: a quiet spec is read again by a changed fleet.sh' 1 '^graphql Spec number=10'
# A closed ticket with a launch-fleet record but no "archived" one can still
# owe an archive: its start claim edited to started, a review claim on its pull
# request edited to started. Neither edit moves its spec, so such a spec is
# never cached as quiet; only archived tickets and tickets with no records are
# settled (Sol R1).
LATE="$QUIET | say(13; 1301; \"11:20\"; \"launch-fleet: starting\")"
expect 'budget: a closed ticket whose start is still claimed: its spec is not cached as quiet (Sol R1)' 0 check.json "$LATE" -- check < /dev/null
again 'budget: its claim edited to started: the archive is due on the next check (Sol R1)' 'issue(13; (.comments[] | select(.id == 1301) | .body) = "launch-fleet: started, thread thr_synlate")' -- check <<EOF
archive #13: closed; archive thr_synlate
EOF
log_has 'budget: its claim edited to started: the archive is due on the next check (Sol R1)' 1 '^graphql Spec number=10'
PRLATE="$QUIET | merged_pr(33; 13; \"11:00\"; []) | pr_say(33; 3301; \"11:10\"; \"launch-fleet: review starting \\(sha(33))\")"
expect 'budget: a closed ticket whose pull request has a review claimed: its spec is not cached as quiet (Sol R1)' 0 check.json "$PRLATE" -- check < /dev/null
again 'budget: the review claim edited to started: the archive is due on the next check (Sol R1)' 'pull(33; (.comments[] | select(.id == 3301) | .body) = "launch-fleet: review started \(sha(33)), thread thr_synrevlate")' -- check <<EOF
archive #13: closed; archive thr_synrevlate
EOF
log_has 'budget: the review claim edited to started: the archive is due on the next check (Sol R1)' 1 '^graphql Spec number=10'
OWED='all_closed | issue(12; .comments |= map(select(.id != 1202))) | say(10; 1002; "11:30"; "launch-fleet: spec summary")'
expect 'budget: a spec with no open ticket that owes an archive' 0 check.json "$OWED" -- check <<EOF
archive #12: closed; archive thr_syn12
EOF
again 'budget: it is read on every check until it is archived' . -- check <<EOF
archive #12: closed; archive thr_syn12
EOF
log_has 'budget: it is read on every check until it is archived' 1 '^graphql Spec number=10'
again 'budget: archived, it closes' 'say(12; 1202; "11:45"; "launch-fleet: archived")' -- check <<EOF
close spec #10: every planned ticket is done; follow-ups go to polish
EOF

# A spec's read asks for its tickets, as many as the open issues list; one
# added since is still read, with no false "more than 100 tickets".
expect 'budget: a ticket added after the list is still read' 0 check.json 'merge12' FAKE_GH_SUMMARY_LAG=1 -- check <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'budget: a ticket added after the list is still read' 2 '^graphql Spec number=10'

### Wakes: GitHub's messages name what to read (ClosedWiz#259)

# A wake reads only the issues and pull requests GitHub's messages named, one
# read each, and prints the check's lines about them. Each case's next check
# (`again`) shows the check's own lines on the same world.
S34=$(sha 34) S22=$(sha 22)
PR34='open_pr(34; 14; "#14: widget docs, green")'
expect 'wake: a pull request reads only itself and its ticket, in one read' 0 check.json "$PR34" -- wake 34 <<EOF
review #34 for #14 at $S34: first review
EOF
log_has 'wake: a pull request reads only itself and its ticket, in one read' 1 '^graphql Item number=34 size=2$'
log_has 'wake: a pull request reads only itself and its ticket, in one read' 2 '^contents docs/agents/'
log_has 'wake: a pull request reads only itself and its ticket, in one read' 10 '.'
again 'wake: the check prints the same line for it' . -- check <<EOF
review #34 for #14 at $S34: first review
EOF
ERR='fleet.sh: used 1 GitHub points in 11 questions, 0 unchanged; 5000 of 5000 left'
expect 'wake: it reports its points: one read of 1 point, and the two settings files' 0 check.json "$PR34" -- wake 34 <<EOF
review #34 for #14 at $S34: first review
EOF
# The ticket of #31 relies on a contract: the merges since its approval are
# read too, as the check reads them, for a hold or a note.
expect 'wake: a pull request whose ticket relies on a contract also reads the merges since its approval' 0 check.json 'pr31' -- wake 31 <<EOF
review #31 for #12 at $S31: first review
EOF
log_has 'wake: a pull request whose ticket relies on a contract also reads the merges since its approval' 1 '^graphql Item number=31 size=2$'
log_has 'wake: a pull request whose ticket relies on a contract also reads the merges since its approval' 1 '^graphql Merged '
log_has 'wake: a pull request whose ticket relies on a contract also reads the merges since its approval' 0 '^graphql \(Specs\|Spec\|Singles\|Nodes\) '
log_has 'wake: a pull request whose ticket relies on a contract also reads the merges since its approval' 0 '^issue view'
expect 'wake: a line on an item it does not name is left to the check' 0 check.json "merge12 | $PR34" -- wake 34 <<EOF
review #34 for #14 at $S34: first review
EOF
again 'wake: the safety-net check prints it' . -- check <<EOF
start #13: W3: widget page (spec #10)
review #34 for #14 at $S34: first review
EOF
# A ticket that could start: its approval is checked against the plan, which
# revision.sh reads in full, so its spec is read in full too; only the ticket
# named has lines, and the tick's claim reuses the approval checked.
expect 'wake: a ticket that could start: its spec is read in full for the approval, and only it has lines' 0 check.json 'merge12 | issue(14; .blockedBy = [])' -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'wake: a ticket that could start: its spec is read in full for the approval, and only it has lines' 1 '^graphql Item number=13 size=2$'
log_has 'wake: a ticket that could start: its spec is read in full for the approval, and only it has lines' 1 '^graphql Spec number=10'
log_has 'wake: a ticket that could start: its spec is read in full for the approval, and only it has lines' 1 '^issue view 10 subIssues$'
log_has 'wake: a ticket that could start: its spec is read in full for the approval, and only it has lines' 0 '^graphql \(Specs\|Singles\|Nodes\) '
again 'wake: the tick'"'"'s claim reuses the approval its wake checked' 'say(13; 1301; "11:59"; "launch-fleet: starting")' -- claim 13 1301 <<EOF
go #13
EOF
log_has 'wake: the tick'"'"'s claim reuses the approval its wake checked' 0 '^issue view'
log_has 'wake: the tick'"'"'s claim reuses the approval its wake checked' 0 '^graphql Specs '
# The approval a wake checked is read again once the plan changes, here the
# spec's body, even when it was empty and every ticket was named.
EMPTY='merge12 | issue(10; .body = "")'
expect 'wake: every ticket of a spec named, its body empty' 0 check.json "$EMPTY" -- wake 11 12 13 14 <<EOF
start #13: W3: widget page (spec #10)
EOF
again 'wake: the spec'"'"'s body written since: its approval is checked again' 'issue(10; .body = "Written since.")' -- wake 11 12 13 14 <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "$EMPTY @@then@@ issue(10; .body = \"Written since.\")" 10))
EOF
log_has 'wake: the spec'"'"'s body written since: its approval is checked again' 1 '^issue view 10 subIssues$'
expect 'wake: a spec it names is read in full, as the check reads it' 0 check.json 'merge12' -- wake 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
log_has 'wake: a spec it names is read in full, as the check reads it' 1 '^graphql Spec number=10'
log_has 'wake: a spec it names is read in full, as the check reads it' 0 '^graphql \(Singles\|Nodes\) '
expect 'wake: a spec it names gets its spec lines' 0 check.json 'all_closed' -- wake 10 <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
again 'wake: the check prints the same spec lines' . -- check <<EOF
spec done #10: every planned ticket is done; no follow-ups
EOF
expect 'wake: an issue approved on its own' 0 check.json 'own_approval(70; 7002; "11:00")' -- wake 70 <<EOF
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
log_has 'wake: an issue approved on its own' 0 '^graphql \(Specs\|Spec\|Singles\|Nodes\) '
expect 'wake: an issue outside the fleets is nothing' 0 check.json 'followup(16; "OPEN"; "Follow-up of #12 (spec #10): R3 [low] a wording nit.")' -- wake 16 < /dev/null
expect 'wake: a number that is no issue or pull request is nothing' 0 check.json . -- wake 999 < /dev/null
log_has 'wake: a number that is no issue or pull request is nothing' 1 '^graphql Item number=999 size=2$'
expect 'wake: several numbers, each read once' 0 check.json "merge12 | $PR34" -- wake 34 13 999 34 <<EOF
start #13: W3: widget page (spec #10)
review #34 for #14 at $S34: first review
EOF
log_has 'wake: several numbers, each read once' 3 '^graphql Item number='
log_has 'wake: several numbers, each read once' 1 '^graphql Item number=34 size=2$'
# A pull request closing more issues than one read holds: every one is read,
# page after page, so its ticket is never lost to a wake or a claim (Sol R2
# on #357: the approved ticket sixth, after five issues outside the fleets).
SIX='.issues += [range(1; 6) | {number: ., title: "Unplanned \(.)", state: "OPEN", parent: null, labels: [], blockedBy: [], body: "", comments: []}] | .pulls += [{number: 34, state: "OPEN", draft: false, base: "main", head: sha(34), headline: "#14: widget docs, green", closes: [1, 2, 3, 4, 5, 14], rollup: "SUCCESS", checks: green, mergedAt: null, updatedAt: at("11:00"), comments: [], files: []}]'
expect 'a pull request closing six issues, its ticket sixth: the check (Sol R2)' 0 check.json "$SIX" -- check <<EOF
review #34 for #14 at $S34: first review
EOF
again 'a pull request closing six issues, its ticket sixth: the wake prints the same (Sol R2)' . -- wake 34 <<EOF
review #34 for #14 at $S34: first review
EOF
log_has 'a pull request closing six issues, its ticket sixth: the wake prints the same (Sol R2)' 2 '^graphql Item number=34 '
again 'a pull request closing six issues, its ticket sixth: its claim goes (Sol R2)' 'pr_say(34; 3401; "11:59"; "launch-fleet: review starting \(sha(34))")' -- claim 34 3401 <<EOF
go #34
EOF
expect 'wake: a pull request merged: its ticket'"'"'s agents are archived' 0 check.json 'issue(12; .state = "CLOSED") | merged_pr(22; 12; "11:00"; [])' -- wake 22 <<EOF
archive #12: closed; archive thr_syn12
EOF
expect 'stall: reopened for fresh CI becomes merge-due at the approved green head' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:40"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:41"; "launch-fleet: merge blocked \(sha(31)): base moved, reopened for fresh CI")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'stall: reopened record with explanatory detail becomes merge-due' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:40"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:41"; "launch-fleet: merge blocked \(sha(31)): base moved, reopened for fresh CI. Head unchanged; a later tick merges after its admission checks.")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
# Only the latest matching block controls the reopen retry; all the existing
# CI and exact-head review gates still run first.
REOPEN31='reviewing31 | pr_say(31; 3102; "11:40"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3103; "11:41"; "launch-fleet: merge blocked \(sha(31)): base moved, reopened for fresh CI")'
expect 'stall: safety-net check retries the reopened approved head' 0 check.json "$REOPEN31" -- check <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'stall: reopened head with pending CI stays quiet' 0 check.json "$REOPEN31 | pull(31; .rollup = \"PENDING\" | .checks[1].status = \"IN_PROGRESS\" | .checks[1].conclusion = null)" -- wake 31 < /dev/null
expect 'stall: reopened head with failed CI goes to its builder' 0 check.json "$REOPEN31 | pull(31; .rollup = \"FAILURE\" | .checks[1].conclusion = \"FAILURE\")" -- wake 31 <<EOF
CI failed #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'stall: reopened head missing a required green check stays quiet' 0 check.json "$REOPEN31 | pull(31; .checks |= map(select(.name != \"test\")))" -- wake 31 < /dev/null
expect 'stall: a stale approval cannot merge the reopened head' 0 check.json "$REOPEN31 | pull(31; .head = sha(99))" -- wake 31 <<EOF
re-check #31 for #12 at $S99: tell its reviewer, thread thr_synrev31
EOF
expect 'stall: a later unrelated block still requires intervention' 0 check.json "$REOPEN31 | pr_say(31; 3104; \"11:45\"; \"launch-fleet: merge blocked \(sha(31)): permission denied\")" -- wake 31 < /dev/null
expect 'stall: an older unrelated block does not hide a later reopen' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:30"; "launch-fleet: merge blocked \(sha(31)): permission denied") | pr_say(31; 3103; "11:40"; "VERDICT: APPROVE at \(sha(31))") | pr_say(31; 3104; "11:41"; "launch-fleet: merge blocked \(sha(31)): base moved, reopened for fresh CI")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'stall: an unknown reopen reason is not an automatic retry' 0 check.json "$REOPEN31 | pr_say(31; 3104; \"11:45\"; \"launch-fleet: merge blocked \(sha(31)): reopened for unknown reasons\")" -- wake 31 < /dev/null
expect 'wake: an approved head merges' 0 check.json 'reviewing31 | pr_say(31; 3102; "11:40"; "VERDICT: APPROVE at \(sha(31))")' -- wake 31 <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect 'wake: a relied-on contract change leaves the ticket ready to start' 0 check.json 'merge12 | contract23' -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF

# A refusal's record is itself a message: a refused start or review is tried
# again 10 minutes after the refusal, not sooner, by a wake or the check, so a
# wake never retries it at once, again and again. A failed one is tried at once.
REFUSED13='merge12 | say(13; 1301; "11:51"; "launch-fleet: start refused: plan limit reached")'
expect 'a start refused 9 minutes ago waits: a wake' 0 check.json "$REFUSED13" -- wake 13 < /dev/null
again 'a start refused 9 minutes ago waits: the check' . -- check < /dev/null
expect 'a start refused 9 minutes ago waits: the frontier' 0 check.json "$REFUSED13" -- frontier < /dev/null
expect 'a start refused 9 minutes ago waits: a claim withdraws' 0 check.json "$REFUSED13 | say(13; 1302; \"11:58\"; \"launch-fleet: starting\")" -- claim 13 1302 <<EOF
withdraw #13: its start was refused less than 10 minutes ago
EOF
expect 'a start refused 9 minutes ago waits: a claim on an issue approved on its own withdraws (helper finding)' 0 check.json 'own_approval(70; 7002; "11:00") | say(70; 7003; "11:55"; "launch-fleet: start refused: plan limit reached") | say(70; 7004; "11:58"; "launch-fleet: starting")' -- claim 70 7004 <<EOF
withdraw #70: its start was refused less than 10 minutes ago
EOF
expect 'a start refused 10 minutes ago is tried again' 0 check.json 'merge12 | say(13; 1301; "11:50"; "launch-fleet: start refused: plan limit reached")' -- wake 13 <<EOF
start #13: W3: widget page (spec #10; retry after "start refused: plan limit reached")
EOF
expect 'a failed start is tried again at once' 0 check.json 'merge12 | say(13; 1301; "11:59"; "launch-fleet: start failed: no thread found")' -- wake 13 <<EOF
start #13: W3: widget page (spec #10; retry after "start failed: no thread found")
EOF
REFUSED31='pr31 | pr_say(31; 3101; "11:51"; "launch-fleet: review refused \(sha(31)): no reviewer free")'
expect 'a review refused 9 minutes ago waits: a wake' 0 check.json "$REFUSED31" -- wake 31 < /dev/null
again 'a review refused 9 minutes ago waits: the check' . -- check < /dev/null
expect 'a review refused 10 minutes ago is tried again' 0 check.json 'pr31 | pr_say(31; 3101; "11:50"; "launch-fleet: review refused \(sha(31)): no reviewer free")' -- wake 31 <<EOF
review #31 for #12 at $S31: first review (retry after "review refused $S31: no reviewer free")
EOF
# The wait runs from the refusal, the edit that made a claim one, not from the
# claim (Sol R1 on #357).
EDITED13='merge12 | say(13; 1301; "11:40"; "launch-fleet: starting") | edit(13; 1301; "11:59"; "launch-fleet: start refused: plan limit reached")'
expect 'a start claimed 20 minutes ago and refused 1 minute ago waits: a wake (Sol R1)' 0 check.json "$EDITED13" -- wake 13 < /dev/null
again 'a start claimed 20 minutes ago and refused 1 minute ago waits: the check (Sol R1)' . -- check < /dev/null
expect 'a start claimed 20 minutes ago and refused 10 minutes ago is tried again (Sol R1)' 0 check.json 'merge12 | say(13; 1301; "11:40"; "launch-fleet: starting") | edit(13; 1301; "11:50"; "launch-fleet: start refused: plan limit reached")' -- wake 13 <<EOF
start #13: W3: widget page (spec #10; retry after "start refused: plan limit reached")
EOF
EDITED31='pr31 | pr_say(31; 3101; "11:40"; "launch-fleet: review starting \(sha(31))") | pr_edit(31; 3101; "11:59"; "launch-fleet: review refused \(sha(31)): no reviewer free")'
expect 'a review claimed 20 minutes ago and refused 1 minute ago waits: a wake (Sol R1)' 0 check.json "$EDITED31" -- wake 31 < /dev/null
again 'a review claimed 20 minutes ago and refused 1 minute ago waits: the check (Sol R1)' . -- check < /dev/null
expect 'wake: a reviewer given up on gets a fresh one at once' 0 check.json 'quiet31' -- wake 31 <<EOF
review #31 for #12 at $S31: a fresh reviewer (retry after "review failed $S31, thread thr_synrev31: no verdict 30 minutes after it was told again")
EOF

ERR='fleet.sh: backing off: 1249 of 5000 GitHub points left, under the 1250 kept for builders and reviewers, until 2026-11-01T13:00:00Z'
expect 'wake: a low allowance backs off: one line, nothing more asked' 0 check.json 'pr31' FAKE_GH_REMAINING=1249 -- wake 31 < /dev/null
log_has 'wake: a low allowance backs off: one line, nothing more asked' 1 '.'
ERR="fleet.sh: backing off: GitHub's allowance has run out, until it resets"
expect 'wake: a spent allowance backs off' 0 check.json 'pr31' FAKE_GH_RATE_LIMITED=Item -- wake 31 < /dev/null
expect 'wake: a read that fails fails loudly' 2 check.json 'pr31' FAKE_GH_ERRORS=Item -- wake 31 <<EOF
the GitHub query Item answered with errors
EOF
expect 'wake: needs a number' 2 check.json . -- wake <<EOF
usage: fleet.sh
EOF
expect 'wake: only numbers' 2 check.json . -- wake 31 '#13' <<EOF
usage: fleet.sh
EOF

### An hour of a fake fleet: the 10-minute timer, then GitHub's messages (ClosedWiz#259)

# One hour of typical activity on the fake fleet of four specs, run twice from
# the same start, counting every question the fleet asks GitHub.
# - The timer (before #259): a check every 10 minutes in the loop's sandbox,
#   whose cache lasts; each check that prints a line wakes a tick, which runs
#   the check again in its own fresh sandbox, then answers a minute later.
# - The wakes (after): each minute GitHub sends messages in wakes a tick, which
#   runs `wake` on the numbers they name, in its fresh sandbox; the safety net
#   checks every 30 minutes, and a tick it wakes runs `wake` on the numbers
#   its lines name. A tick answers a minute later.
# In both, a tick claims each start and review in its own sandbox, and checks
# again after a merge. The builders, reviewers, CI and people act at the same
# minutes in both. One message never arrives (12:25): the safety net finds
# what it was for.
H=$tmp/hour
# Each event: its minute after 12:00 with the wakes, and with the timer ("--"
# for after the hour); the numbers GitHub's message names ("-" for none, or
# one that never arrives); what the tick runs in its sandbox once it is made,
# if anything; and its change to the world, where @@AT@@ is its time ("12:MM").
cat > "$tmp/hour-events" <<'EVENTS'
01|01|41|claim 41 4101|say(41; 4101; @@AT@@; "launch-fleet: starting")
01|01|41||issue(41; .comments[0].body = "launch-fleet: started, thread thr_syng1")
01|01|45|claim 45 4501|say(45; 4501; @@AT@@; "launch-fleet: starting")
01|01|45||issue(45; .comments[0].body = "launch-fleet: started, thread thr_syng5")
01|01|55|claim 55 5502|say(55; 5502; @@AT@@; "launch-fleet: starting")
01|01|55||issue(55; .comments[1].body = "launch-fleet: start refused: plan limit reached")
01|01|47 48 50||say(47; 4701; @@AT@@; "launch-fleet: asked the orchestrator") | issue(48; .comments[0].body = "launch-fleet: start failed: no branch 30 minutes after the start") | say(50; 5002; @@AT@@; "launch-fleet: needs approval: changed since revision 1 (fingerprint now @@FP50@@)")
02|11|48|claim 48 4802|say(48; 4802; @@AT@@; "launch-fleet: starting")
02|11|48||issue(48; .comments[1].body = "launch-fleet: started, thread thr_syng8")
03|03|54||issue(54; .comments[0].body = "launch-fleet: started, thread thr_syng10")
08|08|99||pull(99; .headline = "#49: gadget search, green" | running_ci | .updatedAt = at(@@AT@@))
12|12|-||.refs += ["room/41-g1-gadget-reader-aaaa", "room/45-g5-gadget-import-bbbb", "room/48-g8-gadget-colours-cccc", "room/54-g10-gadget-sort-dddd"]
14|14|99||pull(99; .rollup = "SUCCESS" | .checks = green)
15|21|99|claim 99 9901|pr_say(99; 9901; @@AT@@; "launch-fleet: review starting \(sha(99))")
15|21|99||pull(99; .comments[0].body = "launch-fleet: review started \(sha(99)), thread thr_synr99")
31|21|41 45 48 54||issue(41; .comments[0].body = "launch-fleet: start checked, thread thr_syng1, branch room/41-g1-gadget-reader-aaaa") | issue(45; .comments[0].body = "launch-fleet: start checked, thread thr_syng5, branch room/45-g5-gadget-import-bbbb") | issue(48; .comments[1].body = "launch-fleet: start checked, thread thr_syng8, branch room/48-g8-gadget-colours-cccc") | issue(54; .comments[0].body = "launch-fleet: start checked, thread thr_syng10, branch room/54-g10-gadget-sort-dddd")
31|21|55|claim 55 5503|say(55; 5503; @@AT@@; "launch-fleet: starting")
31|21|55||issue(55; .comments[2].body = "launch-fleet: started, thread thr_syng11")
23|23|141||.pulls += [{number: 141, state: "OPEN", draft: true, base: "main", head: sha(141), headline: "#41: work in progress", closes: [41], rollup: null, checks: [], mergedAt: null, updatedAt: at(@@AT@@), comments: [], files: []}]
25|25|-||issue(47; .labels = ["ready-for-agent"])
31|31|47|claim 47 4702|say(47; 4702; @@AT@@; "launch-fleet: starting")
31|31|47||issue(47; .comments[1].body = "launch-fleet: started, thread thr_syng7")
33|33|99||pr_say(99; 9902; @@AT@@; "VERDICT: CHANGES at \(sha(99))")
34|41|99||pr_say(99; 9903; @@AT@@; "launch-fleet: findings sent \(sha(99))")
42|42|99||pull(99; .head = sha(991) | .rollup = "PENDING" | .checks = [] | .updatedAt = at(@@AT@@))
44|44|141||pull(141; .draft = false | .updatedAt = at(@@AT@@))
48|48|99||pull(99; .rollup = "SUCCESS" | .checks = green)
49|51|99|claim 99 9904|pr_say(99; 9904; @@AT@@; "launch-fleet: review starting \(sha(991))")
49|51|99||pull(99; .comments[3].body = "launch-fleet: re-check sent \(sha(991)), thread thr_synr99")
55|55|99||pr_say(99; 9905; @@AT@@; "VERDICT: APPROVE at \(sha(991))")
56|--|49 99|check|pull(99; .state = "MERGED" | .mergedAt = at(@@AT@@) | .updatedAt = at(@@AT@@)) | issue(49; .state = "CLOSED")
58|--|49||say(49; 4901; @@AT@@; "launch-fleet: archived")
EVENTS
# The events in REGIME's order (wakes or timer): "MINUTE|LINE" for each one
# within the hour, by minute, then as listed.
hour_order() {
  col=1
  [ "$1" = timer ] && col=2
  awk -F'|' -v c=$col '$c != "--" { print $c "|" NR }' "$tmp/hour-events" | sort -t'|' -k1,1n -k2,2n
}
# hour_world REGIME K: the world after REGIME's first K events, into $H/REGIME-K.json.
hour_world() {
  [ -s "$H/$1-$2.json" ] && return 0
  f=.
  hour_order "$1" | head -n "$2" > "$H/order-$1" || return 1
  while IFS='|' read -r ev_m ev_n; do
    ev_change=$(sed -n "${ev_n}p" "$tmp/hour-events" | cut -d'|' -f5-)
    f="$f | $(printf '%s' "$ev_change" | sed "s/@@AT@@/\"12:$ev_m\"/g; s/@@FP50@@/$FP50/")"
  done < "$H/order-$1"
  jq "$LIB $f" "$H/base.json" > "$H/$1-$2.json"
}
# hour_run REGIME K MINUTE CACHE ARGS...: fleet.sh ARGS at 12:MINUTE on the
# world after REGIME's first K events; its lines on stdout and in
# $H/lines-REGIME, its points and questions in $H/points-REGIME.
hour_run() {
  regime=$1 k=$2 m=$3 c=$4
  shift 4
  hour_world "$regime" "$k" || return 1
  fleet=$FLEET
  [ "$regime" = timer ] && fleet=${HOUR_BEFORE:-$FLEET}
  (cd "$H" && env PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FAKE_GH_WORLD="$H/$regime-$k.json" \
    FAKE_GH_LOG="$H/gh-$regime.log" LAUNCH_FLEET_NOW=$((NOW + 60 * ${m#0})) LAUNCH_FLEET_CACHE="$c" \
    LAUNCH_FLEET_REVISION="$FIX/revision.sh" /bin/sh "$fleet" "$@" > "$H/out-$regime" 2> "$H/err-$regime") || return 1
  points_only "$H/err-$regime" || return 1
  sed -E "s/^fleet\.sh: used ([0-9]+) GitHub points in ([0-9]+) questions.*/\1 \2 12:$m $*/" "$H/err-$regime" >> "$H/points-$regime" || return 1
  sed "s/^/12:$m /" "$H/out-$regime" >> "$H/lines-$regime"
  cat "$H/out-$regime"
}
# named: the number each line on stdin is about, its first.
named() { sed -n 's/^[^#]*#\([0-9]*\).*/\1/p' | sort -n -u | tr '\n' ' '; }
# hour_regime REGIME: the hour for REGIME. Each minute: what the loop wakes a
# tick for (a check, or GitHub's messages), the tick's read in its fresh
# sandbox, then each event of that minute, with what the tick runs for it.
hour_regime() {
  r=$1
  : > "$H/points-$r" && : > "$H/lines-$r" && : > "$H/ticks-$r" || return 1
  hour_order "$r" > "$H/all-$r" || return 1
  k=0 m=00
  while [ "${m#0}" -lt 60 ]; do
    nums='' check=no
    case $r in
      timer) case $m in ?0) check=yes ;; esac ;;
      wakes) case $m in 00 | 30) check=yes ;; esac
        nums=$(awk -F'|' -v m="$m" '$1 == m { print $2 }' "$H/all-$r" | while read -r n; do sed -n "${n}p" "$tmp/hour-events" | cut -d'|' -f3; done | grep -v '^-$' | tr '\n' ' ') ;;
    esac
    # The messages of minute M are sent by its events: they wake a tick after them.
    while IFS='|' read -r ev_m ev_n; do
      [ "$ev_m" = "$m" ] || continue
      k=$((k + 1))
      cmd=$(sed -n "${ev_n}p" "$tmp/hour-events" | cut -d'|' -f4)
      [ -z "$cmd" ] || hour_run "$r" "$k" "$m" "$H/tick-cache-$r" $cmd > /dev/null || return 1
    done < "$H/all-$r"
    if [ $check = yes ]; then
      hour_run "$r" "$k" "$m" "$H/loop-$r" check > "$H/due-$r" || return 1
      if [ -s "$H/due-$r" ]; then
        echo "12:$m" >> "$H/ticks-$r"
        rm -rf "$H/tick-cache-$r"
        if [ "$r" = timer ]; then hour_run "$r" "$k" "$m" "$H/tick-cache-$r" check > /dev/null || return 1
        else nums="$nums $(named < "$H/due-$r")"; fi
      fi
    fi
    if [ -n "$(printf '%s' "$nums" | tr -d ' ')" ]; then
      echo "12:$m" >> "$H/ticks-$r"
      rm -rf "$H/tick-cache-$r" && hour_run "$r" "$k" "$m" "$H/tick-cache-$r" wake $(printf '%s\n' $nums | sort -n -u) > /dev/null || return 1
    fi
    m=$(printf '%02d' $((${m#0} + 1)))
  done
  sort -u "$H/ticks-$r" > "$H/ticks-$r.u" && mv "$H/ticks-$r.u" "$H/ticks-$r" \
    && awk '{ p += $1; q += $2 } END { print p + 0, q + 0 }' "$H/points-$r" > "$H/sum-$r"
}
hour() {
  mkdir -p "$H" && world frontier.json . "$H" > "$H/base.json" || return 1
  FP50=$(fp12 frontier.json . 50) && [ ${#FP50} = 12 ] || return 1
  # Each loop's sandbox has checked before the hour: its cache is warm.
  hour_run timer 0 00 "$H/loop-timer" check > /dev/null && hour_run wakes 0 00 "$H/loop-wakes" check > /dev/null || return 1
  # The two regimes share nothing but the base world: they run at once.
  hour_regime timer & timer_pid=$!
  hour_regime wakes; wakes_status=$?
  wait "$timer_pid" && [ "$wakes_status" = 0 ]
}
if [ -n "${TEST_ONLY:-}" ] || ! take heavy; then
  : # the hour runs only in a full run, in one worker
elif hour; then
  read -r tp tq < "$H/sum-timer"
  read -r wp wq < "$H/sum-wakes"
  summary="the timer $tp points in $tq questions, $(grep -c '' "$H/ticks-timer") ticks; the wakes and the safety net $wp in $wq, $(grep -c '' "$H/ticks-wakes") ticks"
  printf '%s\n' "$summary" > "$tmp/hour-summary"
  # The timer as it was before #259 (fleet.sh at efa2490, with the fake gh of
  # its day), on this same hour: measured with HOUR_BEFORE at the commit
  # before the search for issues outside specs (private/evidence/infra-fleets/fa7/).
  today=762
  cases=$((cases + 1))
  if [ $((wp * 10)) -le $((today * 4)) ]; then
    echo "ok   an hour of the fake fleet: the wakes ask at most 40% of the points the timer asked before #259 ($today): $summary"
  else
    bad "an hour of the fake fleet: the wakes ask at most 40% of the points the timer asked before #259 ($today)" "$summary"
  fi
  cases=$((cases + 1))
  if [ "$wp" -lt "$tp" ]; then
    echo "ok   an hour of the fake fleet: with the same fleet.sh, the wakes ask fewer points than the timer"
  else
    bad 'an hour of the fake fleet: with the same fleet.sh, the wakes ask fewer points than the timer' "$summary"
  fi
  # Nothing lost: each kind of line the timer printed about each item, the
  # wakes printed too, at 12:56 at the latest.
  kinds() { sed -E 's/^12:[0-9]+ ([a-zA-Z -]+) #([0-9]+).*/\1 #\2/' "$1" | sort -u; }
  kinds "$H/lines-timer" > "$H/kinds-timer" && kinds "$H/lines-wakes" > "$H/kinds-wakes" \
    && comm -23 "$H/kinds-timer" "$H/kinds-wakes" > "$H/lost" || : > "$H/lost.failed"
  cases=$((cases + 1))
  if [ -s "$H/kinds-timer" ] && [ ! -s "$H/lost" ] && [ ! -e "$H/lost.failed" ]; then
    echo "ok   an hour of the fake fleet: every line the timer printed, the wakes printed too ($(grep -c '' "$H/kinds-timer") kinds of line)"
  else
    bad 'an hour of the fake fleet: every line the timer printed, the wakes printed too' "missing: $(tr '\n' ';' < "$H/lost" 2> /dev/null)"
  fi
  cases=$((cases + 1))
  if grep -qx '12:30 start #47: G7: gadget sizes (spec #40)' "$H/lines-wakes"; then
    echo "ok   an hour of the fake fleet: a message that never arrives is found by the safety net"
  else
    bad 'a message that never arrives is found by the safety net' "the 12:30 check did not start #47: $(grep '^12:30' "$H/lines-wakes" | head -c 300)"
  fi
else
  bad 'an hour of the fake fleet' "a run failed: $(cat "$H"/err-* 2> /dev/null | head -c 300)"; cases=$((cases + 4))
fi

;;
esac

### Conditional REST cache (#405), through the public check seam

cache_case() {
  name=$1 mode=$2
  if ! selected "$name"; then return; fi
  take || return 0
  cases=$((cases + 1))
  d=$tmp/cache-$cases
  mkdir "$d" || { bad "$name" "setup"; return; }
  cp "$FIX/check.json" "$d/world.json" || { bad "$name" "fixture"; return; }
  cache_page=100 cache_head='' cache_reader=$FLEET
  if [ "$mode" = mixed ]; then
    cache_head=$S99
    jq "$LIB pr31" "$d/world.json" > "$d/new.json" && mv "$d/new.json" "$d/world.json" \
      || { bad "$name" "make open PR"; return; }
  fi
  [ "$mode" != pages ] || cache_page=1
  cache_check() {
    env FAKE_GH_PAGE="$cache_page" FAKE_GH_PULL_HEAD="$cache_head" PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo \
      FAKE_GH_WORLD="$d/world.json" FAKE_GH_LOG="$d/gh.log" FAKE_GH_HTTP_LOG="$d/http.log" \
      LAUNCH_FLEET_NOW=$NOW LAUNCH_FLEET_CACHE="$d/cache" LAUNCH_FLEET_REVISION="$FIX/revision.sh" \
      sh "$cache_reader" check > "$d/out$1" 2> "$d/err$1"
  }
  if [ "$mode" = mixed ]; then
    cache_check 1
    status=$?
    printf 'review #31 for #12 at %s: first review\n' "$S31" > "$d/want"
    if [ "$status" != 0 ] || ! cmp -s "$d/want" "$d/out1"; then
      bad "$name" "the verdict must name the head whose checks were read: exit $status; $(cat "$d/out1")"; return
    fi
    echo "ok   $name"; return
  fi
  if ! cache_check 1; then bad "$name" "first read: $(cat "$d/err1")"; return; fi
  if [ "$mode" = transport ]; then
    # Hand-counted from check.json: six issues, one linked PR, two label searches.
    if grep -q '^graphql Singles' "$d/gh.log" || [ "$(wc -l < "$d/http.log")" -ne 26 ] \
      || [ "$(grep -c '^search/issues?.* 200$' "$d/http.log")" -ne 2 ] \
      || [ "$(grep -c '/issues?state=open.* 200$' "$d/http.log")" -ne 1 ] \
      || [ "$(grep -c '/issues/[0-9]*/comments?.* 200$' "$d/http.log")" -ne 7 ] \
      || [ "$(grep -c '/dependencies/blocked_by?.* 200$' "$d/http.log")" -ne 6 ]; then
      bad "$name" "issue listing, search and comments must use REST"; return
    fi
    echo "ok   $name"; return
  fi
  case $mode in
    unchanged | pages) ;;
    upgrade)
      cp "$FLEET" "$d/updated-reader.sh" && cp "$HERE/records.py" "$d/records.py" && printf '\n# Synthetic reader update.\n' >> "$d/updated-reader.sh" \
        || { bad "$name" "copy reader"; return; }
      cache_reader=$d/updated-reader.sh ;;
    changed)
      jq "$LIB nightly" "$d/world.json" > "$d/new.json" && mv "$d/new.json" "$d/world.json" \
        || { bad "$name" "change fixture"; return; } ;;
    corrupt)
      find "$d/cache" -name 'rest-*.json' > "$d/entries" || { bad "$name" "list entries"; return; }
      while IFS= read -r entry; do
        jq --arg tag '"corrupt"' 'if (.response | contains("workflow_runs")) then .etag = $tag
          else .response += "corrupt" end' "$entry" > "$entry.bad" && mv "$entry.bad" "$entry" \
          || { bad "$name" "damage entries"; return; }
      done < "$d/entries" ;;
    duplicate)
      find "$d/cache" -name 'rest-*.json' > "$d/entries" || { bad "$name" "list entries"; return; }
      while IFS= read -r entry; do
        tag=$(jq -c .etag "$entry") || { bad "$name" "read tag"; return; }
        # Add the same top-level field twice, preserving the original value.
        # A parser that silently takes the last value would trust this entry.
        sed '$s/} *$//' "$entry" > "$entry.bad" \
          && printf ',"etag":%s}\n' "$tag" >> "$entry.bad" && mv "$entry.bad" "$entry" \
          || { bad "$name" "duplicate fields"; return; }
      done < "$d/entries" ;;
    split)
      find "$d/cache" -name 'rest-*.json' > "$d/entries" || { bad "$name" "list entries"; return; }
      while IFS= read -r entry; do
        # Keep every field valid, but distribute them across two top-level
        # objects. A stream parser must not combine them into one envelope.
        jq -c '{etag, request}, {response, sha256}' "$entry" > "$entry.bad" \
          && mv "$entry.bad" "$entry" || { bad "$name" "split envelope"; return; }
      done < "$d/entries" ;;
    unreadable)
      find "$d/cache" -name 'rest-*.json' -exec sh -c 'rm "$1" && mkdir "$1"' sh {} \; ;;
  esac
  : > "$d/http.log"
  if ! cache_check 2; then bad "$name" "repeat read: $(cat "$d/err2")"; return; fi
  case $mode in
    pages)
      cmp -s "$d/out1" "$d/out2" && [ "$(grep -c '/issues?state=open.* 304$' "$d/http.log")" = 5 ] \
        || { bad "$name" "all five cached issue pages must be revalidated"; return; }
      jq '.issues += [{number: 71, title: "Synthetic extra issue", state: "OPEN", parent: null,
        body: "", labels: [], blockedBy: [], comments: []}]' "$d/world.json" > "$d/new.json" \
        && mv "$d/new.json" "$d/world.json" || { bad "$name" "append page"; return; }
      : > "$d/http.log"
      cache_check 3 && cmp -s "$d/out2" "$d/out3" && grep -q '/issues?state=open.*page=6 unconditional 200$' "$d/http.log" \
        || { bad "$name" "a 304 with a new next-page Link must expose page six"; return; } ;;
    unchanged | upgrade)
      cmp -s "$d/out1" "$d/out2" && [ "$(grep -c ' 304$' "$d/http.log")" = 25 ] \
        || { bad "$name" "same output and exactly twenty-five REST 304s required"; return; } ;;
    changed)
      printf 'nightly red 801 attempt 1 at %s: https://github.com/synthetic-owner/synthetic-repo/actions/runs/801 (failure)\n' "$(sha 81)" > "$d/want"
      cmp -s "$d/want" "$d/out2" && grep -q 'runs?.* 200$' "$d/http.log" \
        || { bad "$name" "changed 200 did not replace the alert"; return; }
      : > "$d/http.log"
      cache_check 3 && cmp -s "$d/out2" "$d/out3" && grep -q 'runs?.* 304$' "$d/http.log" \
        || { bad "$name" "replacement was not reused on 304"; return; } ;;
    corrupt | duplicate | split | unreadable)
      cmp -s "$d/out1" "$d/out2" && [ "$(grep -c ' unconditional 200$' "$d/http.log")" = 25 ] \
        || { bad "$name" "invalid cache must make twenty-five unconditional REST reads"; return; } ;;
  esac
  echo "ok   $name"
}
cache_case 'REST cache: reader updates retain conditional GETs' upgrade
cache_case 'REST cache: changed PR heads cannot borrow previous checks' mixed
cache_case 'REST cache: paginated 304s retain and refresh next-page links' pages
cache_case 'REST cache: issue listing search and comments use REST' transport
cache_case 'REST cache: 304 keeps the same check output' unchanged
cache_case 'REST cache: a changed response replaces the cached answer' changed
cache_case 'REST cache: split envelope objects are ignored' split
cache_case 'REST cache: duplicate envelope fields are ignored' duplicate
cache_case 'REST cache: corrupt answers are ignored' corrupt
cache_case 'REST cache: unreadable answers are ignored' unreadable

### Bounded parallel REST reads (#1011), through the public check seam

parallel_case() {
  name=$1 mode=$2
  if ! selected "$name"; then return; fi
  take heavy || return 0
  cases=$((cases + 1))
  d=$tmp/parallel-$cases
  mkdir -p "$d/bin" "$d/timing" || { bad "$name" "setup"; return; }
  # One hundred twenty-eight closed singles. Every one still needs a fresh comment read
  # before its archived record can exclude it. All values are synthetic.
  jq '.issues += [range(800; 928) | {number: ., title: "Synthetic archived issue",
    state: "CLOSED", parent: null, labels: ["ready-for-agent"], blockedBy: [], body: "",
    comments: [{id: (. * 10), at: "2026-11-01T09:00:00Z", body: "launch-fleet: archived"}]}]' \
    "$FIX/check.json" > "$d/world.json" || { bad "$name" "fixture"; return; }
  if [ "$mode" = specs ] || [ "$mode" = graphs ]; then
    # Eight small independent specs. A reader pool local to each spec can
    # overlap only two issues, so it cannot fill the sixteen-reader barrier.
    jq '.issues += [range(900; 916) | {number: ., title: "Synthetic spec or ticket",
      state: (if . % 2 == 0 then "OPEN" else "CLOSED" end),
      parent: (if . % 2 == 0 then null else . - 1 end),
      labels: [], blockedBy: [], body: "", comments: []}]' \
      "$FIX/check.json" > "$d/world.json" || { bad "$name" "spec fixture"; return; }
  fi
  if [ "$mode" = failure ]; then
    # Keep the fatal-worker proof on a non-comment resource. This issue is
    # read after the closed-single comment pool has reached its barrier.
    jq '.issues += [{number: 9999, title: "Synthetic unreadable issue", state: "OPEN",
      parent: null, labels: ["ready-for-agent"], blockedBy: [], body: "", comments: []}]' \
      "$d/world.json" > "$d/new.json" && mv "$d/new.json" "$d/world.json" \
      || { bad "$name" "failure fixture"; return; }
  fi
  printf '#!/bin/sh\nexec "%s" -I -S "%s" "$@"\n' "$PYTHON" "$FIX/timing-gh.py" > "$d/bin/gh" \
    && chmod +x "$d/bin/gh" || { bad "$name" "wrapper"; return; }
  parallel_page=100
  [ "$mode" != pages ] || parallel_page=32
  parallel_check() {
    failed_reader=$1
    set -- check
    [ "$mode" != one ] || set -- wake 70
    env FAKE_GH_PAGE="$parallel_page" PATH="$d/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FAKE_GH_SCRIPT="$FIX/gh.py" \
      FAKE_GH_TIMING="$d/timing" FAKE_GH_TIMING_GROUP="$mode" FAKE_GH_TIMING_FAIL="$failed_reader" FAKE_GH_HTTP_LOG="$d/http.log" \
      FAKE_GH_WORLD="$d/world.json" FAKE_GH_LOG="$d/gh.log" LAUNCH_FLEET_NOW=$NOW \
      LAUNCH_FLEET_CACHE="$d/cache" LAUNCH_FLEET_REVISION="$FIX/revision.sh" \
      sh "$FLEET" "$@" > "$d/out" 2> "$d/err"
  }
  if [ "$mode" = failure ]; then
    parallel_check yes
    status=$?
    if [ "$status" != 2 ] || [ -s "$d/out" ] || ! grep -q "can't read REST issue facts for the GitHub query Nodes" "$d/err"; then
      bad "$name" "worker failure must stop the check with empty stdout (exit $status)"; return
    fi
  elif [ "$mode" = comment_failure ]; then
    parallel_check comments && points_only "$d/err" \
      || { bad "$name" "comment failure must return an alert: $(cat "$d/err")"; return; }
    printf '%s\n' 'look #800: comment history could not be read in full' > "$d/want" \
      && cmp -s "$d/want" "$d/out" || { bad "$name" "expected only the comment-history alert"; return; }
  else
    if ! parallel_check ''; then bad "$name" "$(cat "$d/err")"; return; fi
    [ ! -s "$d/out" ] && points_only "$d/err" || { bad "$name" "changed fleet output"; return; }
    if [ "$mode" = warm ]; then
      rm "$d/timing/state" "$d/timing/trace" && : > "$d/http.log" \
        || { bad "$name" "reset trace"; return; }
      parallel_check '' && [ ! -s "$d/out" ] && points_only "$d/err" \
        || { bad "$name" "repeat failed"; return; }
      [ "$(grep -c ' conditional 304$' "$d/http.log")" = 154 ] \
        || { bad "$name" "exactly 154 revalidations required"; return; }
    fi
  fi
  # Read the trace only after fleet.sh and all of its workers have returned.
  python3 - "$d/timing" "$mode" <<'PYTRACE'
import json
from pathlib import Path
import re
import sys
root, mode = Path(sys.argv[1]), sys.argv[2]
state = json.loads((root / 'state').read_text())
trace = [json.loads(line) for line in (root / 'trace').read_text().splitlines()]
starts = [e['endpoint'] for e in trace if e['event'] == 'start']
finishes = [e['endpoint'] for e in trace if e['event'] == 'finish']
assert state['active'] == 0 and sorted(starts) == sorted(finishes), state
assert (state['peak'] == 3 if mode == 'one' else
        1 < state['peak'] <= 64 if mode == 'all' else
        8 <= state['peak'] <= 64 if mode == 'graphs' else
        16 <= state['peak'] <= 64 if mode == 'specs' else state['peak'] == 64), state
if mode != 'failure':
    expected = {'one': 5, 'pages': 158, 'specs': 74, 'graphs': 83, 'warm': 154,
                # The unreadable closed single also needs its detail/blockers.
                'comment_failure': 157}.get(mode, 155)
    assert len(starts) == expected and len(set(starts)) == expected, len(starts)
    assert all(starts.count('repos/synthetic-owner/synthetic-repo/issues/%s/comments?per_page=100' % n) == 1
               for n in (range(70, 71) if mode == 'one' else range(900, 916) if mode in ('specs', 'graphs') else range(800, 928))), starts
    # Ordinary issue hydration must overlap as well as the archive scan.
    active = peak = 0
    for e in trace:
        issue = re.search(r'/issues/([0-9]+)(/|$)', e['endpoint'])
        if issue and int(issue[1]) < 800:
            active += 1 if e['event'] == 'start' else -1
            peak = max(peak, active)
    assert 1 < peak <= 64, peak
print('timing harness: traced reads=%s, peak=%s, drained=0' % (len(starts), state['peak']))
PYTRACE
  [ "$?" = 0 ] || { bad "$name" "read count, bound or worker drain failed"; return; }
  echo "ok   $name"
}
parallel_case 'REST parallel: specs and archive reads share one bounded pool' all
parallel_case 'REST parallel: independent spec queries overlap after the allowance gate' graphs
parallel_case 'REST parallel: one issue reads independent facts together' one
parallel_case 'REST parallel: archive pages share the bounded reader pool' pages
parallel_case 'REST parallel: a slow reader leaves other readers working' pipeline
parallel_case 'REST parallel: small specs share the bounded reader pool' specs
parallel_case 'REST parallel: bounded readers preserve every read and decision' cold
parallel_case 'REST parallel: repeat checks revalidate the shared ETag cache' warm
parallel_case 'REST parallel: a failed reader drains workers and prints no actions' failure
parallel_case 'REST parallel: a failed comment reader drains workers and prints only a look' comment_failure

### Blocker node identity (#405 R1), through frontier and claim

# API-documented dependency/node shapes; all values are synthetic. The slash
# and padding exercise opaque IDs that must never become filename components.
COLLIDING_BLOCKERS='own_approval(70; 7002; "09:00") | issue(70; .blockedBy = [99, 99])
  | .dependencyResponses = {"70": [
      {number: 99, node_id: "I_syn/a99==", state: "closed"},
      {number: 99, node_id: "I_syn/b99==", state: "closed"}]}
  | .blockerNodes = [
      {id: "I_syn/a99==", number: 99, closedByPullRequestsReferences:
        {nodes: [{number: 199, merged: true, baseRefName: "main"}]}},
      {id: "I_syn/b99==", number: 99, closedByPullRequestsReferences: {nodes: []}}]'
expect 'blocker identity: one merged same-number issue cannot free another in the frontier' 0 check.json "$COLLIDING_BLOCKERS" -- frontier < /dev/null
log_has 'blocker identity: one merged same-number issue cannot free another in the frontier' 1 '^graphql Blockers count=2$'
expect 'blocker identity: a claim refuses an unmerged same-number blocker' 0 check.json "$COLLIDING_BLOCKERS | say(70; 7003; \"11:58\"; \"launch-fleet: starting\")" -- claim 70 7003 <<EOF
withdraw #70: it is not on the frontier now
EOF
expect 'blocker identity: both verified same-number issues free the frontier' 0 check.json "$COLLIDING_BLOCKERS | .blockerNodes[1].closedByPullRequestsReferences.nodes = [{number: 299, merged: true, baseRefName: \"main\"}]" -- frontier <<EOF
#70 Fix the broken link in the widget docs
EOF
expect 'blocker identity: a claim goes after both same-number blockers merge' 0 check.json "$COLLIDING_BLOCKERS | .blockerNodes[1].closedByPullRequestsReferences.nodes = [{number: 299, merged: true, baseRefName: \"main\"}] | say(70; 7003; \"11:58\"; \"launch-fleet: starting\")" -- claim 70 7003 <<EOF
go #70
EOF

### One fleet thread per spec (#192): its own check, and takeover from records

# Synthetic records only. Spec #10's fleet thread records itself at 10:00,
# after #12's builder (09:40): that builder is from before it. Spec #40 is a
# second spec, with one ticket ready, and #70 is approved on its own, so a
# spec's check can be seen to leave both out.
FLEET10='say(10; 1090; "10:00"; "launch-fleet: fleet thread thr_synfleet10, loop loop_syn10")'
SPEC40='.issues += [{number: 40, title: "Synthetic spec: gadgets", state: "OPEN", parent: null, labels: [], blockedBy: null, body: "", comments: []}]
  | ticket(41; "G1: gadget model"; ["ready-for-agent"]; []) | issue(41; .parent = 40) | approve(40; 4001; "09:00"; 1; [41])
  | own_approval(70; 7002; "09:00")'
expect 'fleet: the check reads every spec and the issues approved on their own' 0 check.json "merge12 | $SPEC40" -- check <<EOF
start #13: W3: widget page (spec #10)
start #41: G1: gadget model (spec #40)
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect "fleet: a spec's check prints that spec's lines alone" 0 check.json "merge12 | $SPEC40" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect "fleet: another spec's check prints its own lines alone" 0 check.json "merge12 | $SPEC40" -- spec 40 <<EOF
start #41: G1: gadget model (spec #40)
EOF
expect 'fleet: the check leaves a spec with a fleet thread to that thread' 0 check.json "merge12 | $SPEC40 | $FLEET10" -- check <<EOF
start #41: G1: gadget model (spec #40)
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect "fleet: the fleet thread's own check still prints its spec's lines" 0 check.json "merge12 | $SPEC40 | $FLEET10" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect "fleet: a spec's check on a ticket is fleet done" 0 check.json . -- spec 12 <<EOF
fleet done #12: it is not an open spec; delete this fleet thread's loop and archive the thread
EOF
expect "fleet: a spec's check on a closed spec is fleet done" 0 check.json 'issue(10; .state = "CLOSED")' -- spec 10 <<EOF
fleet done #10: it is not an open spec; delete this fleet thread's loop and archive the thread
EOF
expect "fleet: a spec's check needs one number" 2 check.json . -- spec <<EOF
usage: fleet.sh
EOF

# A builder's own fleet thread reaches it; one from before the fleet thread is taken over.
FINDINGS31='pr31 | pr_say(31; 3101; "11:10"; "launch-fleet: review started \(sha(31)), thread thr_synrev31") | pr_say(31; 3102; "11:20"; "VERDICT: CHANGES at \(sha(31))")'
# CW-G: independent processes with cold caches share only the durable routing
# and GitHub fixtures. The first wake must keep the recorded builder, then the
# next must honour the delivery record without taking over or sending again.
if selected 'CW-G: route findings to the existing builder' || selected 'CW-G: resume from the recorded delivery'; then
  printf '%s\n' '{"repo":"synthetic-owner/synthetic-repo","threads":{"builder:12":"thr_syn12","review:31:claim:3101":"thr_synrev31"}}' > "$tmp/fresh-routes.json" || exit 1
fi
FRESH_FINDINGS="pr31 | .private = false
  | edit(12; 1201; \"09:40\"; \"launch-fleet: start checked, branch room/12-w2-widget-store-bbbb\")
  | pr_say(31; 3101; \"09:41\"; \"launch-fleet: review started \(sha(31))\")
  | say(10; 1090; \"10:00\"; \"launch-fleet: fleet active, loop fleet-10\\n\\nWake mode: fresh\")
  | pr_say(31; 3102; \"11:20\"; \"VERDICT: CHANGES at \(sha(31))\")"
expect 'CW-G: route findings to the existing builder' 0 check.json "$FRESH_FINDINGS" \
  LAUNCH_FLEET_STATE="$tmp/fresh-routes.json" -- spec 10 <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'CW-G: resume from the recorded delivery' 0 check.json \
  "$FRESH_FINDINGS | pr_say(31; 3103; \"11:21\"; \"launch-fleet: findings sent \(sha(31))\")" \
  LAUNCH_FLEET_STATE="$tmp/fresh-routes.json" -- spec 10 < /dev/null

expect 'fleet: without a fleet thread, findings go to the recorded builder' 0 check.json "$FINDINGS31" -- spec 10 <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect "fleet: a builder recorded after the fleet thread is its own" 0 check.json "$FINDINGS31 | say(10; 1090; \"09:30\"; \"launch-fleet: fleet thread thr_synfleet10, loop loop_syn10\")" -- spec 10 <<EOF
findings #31 for #12 at $S31: tell its builder, thread thr_syn12
EOF
expect 'takeover: a builder from before the fleet thread goes to the orchestrator to archive, and gets no findings' 0 check.json "$FINDINGS31 | $FLEET10" -- spec 10 <<EOF
look #12: archive thread [private thread]: its builder, started before fleet thread [private thread]
EOF
expect 'takeover: the latest fleet thread record is the fleet' 0 check.json "$FINDINGS31 | say(10; 1080; \"09:00\"; \"launch-fleet: fleet thread thr_synfleet09, loop loop_syn09\") | $FLEET10" -- spec 10 <<EOF
look #12: archive thread [private thread]: its builder, started before fleet thread [private thread]
EOF
TOOK12="$FINDINGS31 | $FLEET10 | say(12; 1290; \"10:05\"; \"launch-fleet: look: archive thread thr_syn12: its builder, started before fleet thread thr_synfleet10\")"
expect 'takeover: once asked, the fleet waits for the archive' 0 check.json "$TOOK12" -- spec 10 < /dev/null
expect 'takeover: once archived, the fleet starts its own builder on the same branch' 0 check.json "$TOOK12 | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201)
EOF
expect "takeover: its new builder is the fleet's own, and gets the findings" 0 check.json "$TOOK12 | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\") | edit(12; 1201; \"10:30\"; \"launch-fleet: started, thread thr_synnew12\")" -- spec 10 <<EOF
check start #12: thread thr_synnew12, branch room/12-w2-widget-store-bbbb
findings #31 for #12 at $S31: tell its builder, thread thr_synnew12
EOF
expect "takeover: the orchestrator's archive record never ends the closed ticket's archive line" 0 check.json "$TOOK12 | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\") | edit(12; 1201; \"10:30\"; \"launch-fleet: start checked, thread thr_synnew12, branch room/12-w2-widget-store-bbbb\") | issue(12; .state = \"CLOSED\")" -- spec 10 <<EOF
archive #12: closed; archive thr_synnew12, thr_synrev31
look #10: planned #12 is closed without a verified merge
EOF
expect 'takeover: a builder from before with no branch yet is started afresh, and its review goes on' 0 check.json "pr31 | edit(12; 1201; \"09:40\"; \"launch-fleet: started, thread thr_syn12\") | .refs |= map(select(startswith(\"room/12-\") | not)) | $FLEET10 | say(12; 1290; \"10:05\"; \"launch-fleet: look: archive thread thr_syn12: its builder, started before fleet thread thr_synfleet10\") | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to build it, as it has no branch yet (its record: comment 1201)
review #31 for #12 at $S31: first review
EOF
expect 'takeover: the project check leaves the takeover to the fleet thread' 0 check.json "$FINDINGS31 | $FLEET10" -- check < /dev/null
expect 'takeover: a wake leaves the takeover to the fleet thread' 0 check.json "$FINDINGS31 | $FLEET10" -- wake 31 <<EOF
wake fleet #10: room-cli loop run loop_syn10
EOF

# A reviewer from before the fleet thread is given up at once, and a fresh one starts.
OWN12='edit(12; 1201; "11:56"; "launch-fleet: start checked, thread thr_syn12, branch room/12-w2-widget-store-bbbb")'
FLEET1155='say(10; 1090; "11:55"; "launch-fleet: fleet thread thr_synfleet10, loop loop_syn10")'
expect 'takeover: a reviewer from before the fleet thread is out of reach at once' 0 check.json "pr31 | pr_say(31; 3101; \"11:50\"; \"launch-fleet: review started \(sha(31)), thread thr_synrev31\") | $FLEET1155 | $OWN12" -- spec 10 <<EOF
check review #31 for #12 at $S31: its reviewer, thread thr_synrev31, was started before fleet thread thr_synfleet10, so it is out of reach; record review given up (its record: comment 3101)
EOF
expect 'takeover: a reviewer the fleet thread started waits its 30 minutes' 0 check.json "pr31 | $FLEET1155 | pr_say(31; 3101; \"11:57\"; \"launch-fleet: review started \(sha(31)), thread thr_synrev31\") | $OWN12" -- spec 10 < /dev/null
expect 'takeover: once given up, a fresh reviewer starts' 0 check.json "pr31 | pr_say(31; 3101; \"11:50\"; \"launch-fleet: review started \(sha(31)), thread thr_synrev31\") | $FLEET1155 | $OWN12 | pr_edit(31; 3101; \"11:58\"; \"launch-fleet: review failed \(sha(31)), thread thr_synrev31: out of reach of fleet thread thr_synfleet10\")" -- spec 10 <<EOF
review #31 for #12 at $S31: a fresh reviewer (retry after "review failed $S31, thread thr_synrev31: out of reach of fleet thread thr_synfleet10")
EOF
expect 'takeover: a re-check never goes to a reviewer from before the fleet thread' 0 check.json "reviewing31 | pr_say(31; 3102; \"11:20\"; \"VERDICT: CHANGES at \(sha(31))\") | pr_say(31; 3103; \"11:21\"; \"launch-fleet: findings sent \(sha(31))\") | pull(31; .head = sha(\"31f\")) | say(10; 1090; \"11:30\"; \"launch-fleet: fleet thread thr_synfleet10, loop loop_syn10\") | edit(12; 1201; \"11:31\"; \"launch-fleet: start checked, thread thr_syn12, branch room/12-w2-widget-store-bbbb\")" -- spec 10 <<EOF
check review #31 for #12 at $S31F: its reviewer, thread thr_synrev31, was started before fleet thread thr_synfleet10, so it is out of reach; record review given up (its record: comment 3101)
EOF

# Sol self-review (#192): a takeover's tie, and the merge read across specs.
expect 'takeover: a builder recorded in the same second as the fleet thread is taken over' 0 check.json "$FINDINGS31 | say(10; 1090; \"09:40\"; \"launch-fleet: fleet thread thr_synfleet10, loop loop_syn10\")" -- spec 10 <<EOF
look #12: archive thread [private thread]: its builder, started before fleet thread [private thread]
EOF
# Two approved heads in two fleet threads' specs change the same file: each
# spec's own check gives its head a merge line, and the read before a merge
# (`every`, every spec's lines) keeps only the lower number's, as the check does.
CLASH='store31 | .issues += [{number: 40, title: "Synthetic spec: gadgets", state: "OPEN", parent: null, labels: [], blockedBy: null, body: "", comments: []}]
  | ticket(41; "G1: gadget model"; ["ready-for-agent"]; []) | issue(41; .parent = 40) | approve(40; 4001; "09:00"; 1; [41])
  | say(41; 4100; "09:40"; "launch-fleet: start checked, thread thr_syn41, branch room/41-g1-gadget-model-cccc")
  | open_pr(51; 41; "#41: gadget model, green") | pull(51; .files = [changed("src/store/store.rs"; "modified")])
  | pr_say(51; 5101; "11:10"; "launch-fleet: review started \(sha(51)), thread thr_synrev51") | pr_say(51; 5102; "11:30"; "VERDICT: APPROVE at \(sha(51))")
  | say(10; 1090; "09:00"; "launch-fleet: fleet thread thr_synfleet10, loop loop_syn10") | say(40; 4090; "09:00"; "launch-fleet: fleet thread thr_synfleet40, loop loop_syn40")'
expect "fleet: each spec's own check gives its approved head a merge line" 0 check.json "$CLASH" -- spec 40 <<EOF
merge #51 for #41 at $(sha 51): APPROVE and CI green
EOF
expect 'fleet: the read before a merge reads every spec, and only the lower of two clashing heads merges' 0 check.json "$CLASH" -- every <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF
expect "fleet: a spec's check refuses a number with a leading zero" 2 check.json . -- spec 010 <<EOF
usage: fleet.sh
EOF
# Sol self-review 2 (#192): a takeover start that CloudRoom refused, or that
# failed, is tried again, and never strands the pull request.
ARCH12="$TOOK12 | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\")"
expect 'takeover: a refused takeover start waits 10 minutes, and nothing goes to a builder' 0 check.json "$ARCH12 | edit(12; 1201; \"11:55\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 < /dev/null
expect 'takeover: a refused takeover start is tried again 10 minutes on' 0 check.json "$ARCH12 | edit(12; 1201; \"11:45\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201; retry after "start refused: synthetic reason")
EOF
expect 'takeover: a failed takeover start is tried again at once' 0 check.json "$ARCH12 | edit(12; 1201; \"11:59\"; \"launch-fleet: start failed: synthetic reason\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201; retry after "start failed: synthetic reason")
EOF
expect "fleet: a tick's read before a merge reads the fleet threads' specs too" 0 check.json "$CLASH | issue(40; .comments |= map(select(.id != 4090)))" -- every <<EOF
merge #31 for #12 at $S31: APPROVE and CI green
EOF

# Sol's review of #1517 at b9628208: a takeover start keeps every gate of an
# ordinary start (R1), a takeover retry needs no pull request (R2), and a
# takeover claim waits 10 minutes from the edit that made it (R3).
expect 'takeover R1: a held ticket gets no replacement builder' 0 check.json "$ARCH12 | issue(12; .labels += [\"held\"])" -- spec 10 < /dev/null
expect "takeover R1: a held ticket's takeover retry starts nothing" 0 check.json "$ARCH12 | issue(12; .labels += [\"held\"]) | edit(12; 1201; \"11:45\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 < /dev/null
expect 'takeover R1: a ticket waiting on its question gets no replacement builder' 0 check.json "$ARCH12 | issue(12; .labels += [\"needs-answer\"])" -- spec 10 <<EOF
needs-info #12: a question for the orchestrator
EOF
expect 'takeover R1: a plan changed since its approval starts no replacement builder, and asks again' 0 check.json "$ARCH12 @@then@@ issue(14; .title = \"W4: widget docs, renamed\")" -- spec 10 <<EOF
re-approve #10: changed since revision 1 (fingerprint now $(fp12 check.json "$ARCH12 @@then@@ issue(14; .title = \"W4: widget docs, renamed\")" 10))
EOF
NOPR12="$FLEET10 | say(12; 1290; \"10:05\"; \"launch-fleet: look: archive thread thr_syn12: its builder, started before fleet thread thr_synfleet10\") | say(12; 1291; \"10:20\"; \"launch-fleet: old builder archived, thread thr_syn12\")"
expect 'takeover R2: a refused takeover start with no pull request yet is tried again on its branch' 0 check.json "$NOPR12 | edit(12; 1201; \"11:45\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201; retry after "start refused: synthetic reason")
EOF
expect 'takeover R2: a failed takeover start with no pull request yet is tried again at once, on its branch' 0 check.json "$NOPR12 | edit(12; 1201; \"11:59\"; \"launch-fleet: start failed: synthetic reason\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201; retry after "start failed: synthetic reason")
EOF
expect 'takeover R2: a refused takeover start with no pull request waits 10 minutes, and is never an ordinary start' 0 check.json "$NOPR12 | edit(12; 1201; \"11:55\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 < /dev/null
expect 'takeover R3: a takeover claim waits 10 minutes from the edit that made it' 0 check.json "$NOPR12 | edit(12; 1201; \"11:55\"; \"launch-fleet: starting\")" -- spec 10 < /dev/null
expect 'takeover R3: a takeover claim with no outcome 10 minutes after its edit is reconciled' 0 check.json "$NOPR12 | edit(12; 1201; \"11:45\"; \"launch-fleet: starting\")" -- spec 10 <<EOF
reconcile start #12: claimed at 2026-11-01T11:45:00Z, no outcome after 10 minutes
EOF

expect "takeover: a contract change before archive leaves the archive request due" 0 check.json "$FINDINGS31 | $FLEET10 | issue(13; .body = \"\") | contract23" -- spec 10 <<EOF
look #12: archive thread [private thread]: its builder, started before fleet thread [private thread]
EOF
expect "takeover: a contract change after archive allows a replacement builder" 0 check.json "$ARCH12 | issue(13; .body = \"\") | contract23" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201)
EOF
expect 'takeover: a contract change does not block a retry with the pull request open' 0 check.json "$ARCH12 | issue(13; .body = \"\") | contract23 | edit(12; 1201; \"11:45\"; \"launch-fleet: start refused: synthetic reason\")" -- spec 10 <<EOF
take over #12: builder thread thr_syn12 is archived; start a builder to continue branch room/12-w2-widget-store-bbbb (its record: comment 1201; retry after "start refused: synthetic reason")
EOF
expect 'takeover R4: once held, a takeover waits for the new approval' 0 check.json "$ARCH12 | issue(13; .body = \"\") | contract23 | issue(12; .labels = [\"held\"]) | say(12; 1295; \"11:50\"; \"launch-fleet: held for #23: contract changed, re-approve. contracts/widget.v1.md changed in #23.\")" -- spec 10 < /dev/null

### A fleet thread's loop (#192): loop.sh with FLEET_SPEC runs that spec's check

if { [ -n "${TEST_ONLY:-}" ] && [ "$TEST_ONLY" != fleet-loop ]; } || ! take; then
  : # the fleet thread's loop runs only in a full run, in one worker
else
  FL=$tmp/case-fleetloop
  if mkdir -p "$FL/remote/skills/launch-fleet/scripts" "$FL/remote/skills/to-tickets" "$FL/home" "$FL/w" \
    && cp "$FLEET" "$FL/remote/skills/launch-fleet/scripts/fleet.sh" \
    && cp "$HERE/records.py" "$FL/remote/skills/launch-fleet/scripts/records.py" && cp "$FIX/revision.sh" "$FL/remote/skills/to-tickets/revision.sh" \
    && git -C "$FL/remote" init -q && git -C "$FL/remote" add -A \
    && git -C "$FL/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -q -m one \
    && world check.json "merge12 | $SPEC40" "$FL/w" > "$FL/world.json"; then
    cases=$((cases + 1))
    # The scheduled spec check uses the same CS5 admission inputs as the
    # project loop. Keep its healthy snapshot/state private to this case.
    jq --argjson now "$NOW" '.observed_at = $now |
      .budgets[] |= (.reset_at = ($now + 3600))' \
      "$HERE/carried/healthy.json" > "$FL/observation.json"
    printf 'start #41: G1: gadget model (spec #40)\n' > "$FL/want"
    if (cd "$FL" && env -u OPENWIZ_GITHUB_APP_KEY PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FLEET_SPEC=40 FAKE_GH_WORLD="$FL/world.json" \
        LAUNCH_FLEET_OVERLOAD_INPUT="$FL/observation.json" LAUNCH_FLEET_OVERLOAD_STATE="$FL/pause.json" \
        FAKE_GH_LOG="$FL/gh1.log" FAKE_GH_REMOTE="$FL/remote" LAUNCH_FLEET_HOME="$FL/home" LAUNCH_FLEET_NOW=$NOW \
        LAUNCH_FLEET_CACHE="$FL/cache" /bin/sh "${LOOP_SH:-$HERE/loop.sh}" > "$FL/out1" 2> "$FL/err1") \
      && cmp -s "$FL/want" "$FL/out1" && loop_points "$FL/err1"; then
      echo "ok   loop: with FLEET_SPEC, the loop's script runs that spec's check alone"
    else
      bad "loop: with FLEET_SPEC, the loop's script runs that spec's check alone" "$(cat "$FL/out1" "$FL/err1" | head -c 400)"
    fi
    cases=$((cases + 1))
    if (cd "$FL" && env PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo FLEET_SPEC=4x /bin/sh "${LOOP_SH:-$HERE/loop.sh}" > "$FL/out2" 2>&1); then
      bad "loop: a FLEET_SPEC that is no number exits 2" "it exited 0"
    elif grep -q "FLEET_SPEC must be a spec's number" "$FL/out2"; then
      echo "ok   loop: a FLEET_SPEC that is no number exits 2"
    else
      bad "loop: a FLEET_SPEC that is no number exits 2" "$(head -c 300 "$FL/out2")"
    fi
  else
    bad "loop: with FLEET_SPEC" "can't set up its synthetic project"; cases=$((cases + 2))
  fi
fi

### Token cuts (#694): one wake per unchanged blocker, one probe per batch

# #13's builder started 40 minutes ago, asked a scope question (needs-info),
# and the question went to the orchestrator: it has no branch to show.
BLOCK13='merge12 | issue(13; .labels += ["needs-answer"]) | say(13; 1301; "11:20"; "launch-fleet: started, thread thr_syn13") | say(13; 1302; "11:25"; "Needs-info: synthetic scope question.") | say(13; 1303; "11:26"; "launch-fleet: asked the orchestrator")'
LOOK13='say(13; 1304; "11:40"; "launch-fleet: look: blocked on scope 1301/1302@2026-11-01T11:25:00Z: thread thr_syn13 has no branch")'
expect 'scope blocker: a builder waiting on its question raises one look, keyed' 0 check.json "$BLOCK13" -- check <<EOF
look #13: blocked on scope 1301/1302@2026-11-01T11:25:00Z: thread [private thread] has no branch
EOF
again 'scope blocker: once recorded, the next tick is quiet' "$LOOK13" -- check < /dev/null
again 'scope blocker: still unchanged, a third tick is quiet too' '.' -- check < /dev/null
again 'scope blocker: an answer changes its key and raises it again' 'say(13; 1305; "11:45"; "Orchestrator: synthetic answer.")' -- check <<EOF
needs-info #13: a question for the orchestrator
look #13: blocked on scope 1301/1305@2026-11-01T11:45:00Z: thread [private thread] has no branch
EOF
expect 'scope blocker: once recorded, the check is quiet' 0 check.json "$BLOCK13 | $LOOK13" -- check < /dev/null
expect 'scope blocker: a wake on its own record prints nothing' 0 check.json "$BLOCK13 | $LOOK13" -- wake 13 < /dev/null
expect 'scope blocker: within the 30-minute timeout, nothing yet' 0 check.json 'merge12 | issue(13; .labels += ["needs-answer"]) | say(13; 1301; "11:40"; "launch-fleet: started, thread thr_syn13") | say(13; 1302; "11:45"; "Needs-info: synthetic scope question.")' -- check <<EOF
needs-info #13: a question for the orchestrator
EOF
expect 'scope blocker: a new builder is a changed input' 0 check.json "$BLOCK13 | $LOOK13"' | edit(13; 1301; "11:27"; "launch-fleet: start failed: synthetic") | say(13; 1306; "11:28"; "launch-fleet: started, thread thr_syn13b")' -- check <<EOF
look #13: blocked on scope 1306/1302@2026-11-01T11:25:00Z: thread [private thread] has no branch
EOF
# R1 on #1442: an edit is a changed input too, a question's or an answer's;
# an edit to launch-fleet's own records is not.
expect 'scope blocker: an edited question raises it again' 0 check.json "$BLOCK13 | $LOOK13"' | edit(13; 1302; "11:45"; "Needs-info: synthetic scope question with changed inputs.")' -- check <<EOF
needs-info #13: a question for the orchestrator
look #13: blocked on scope 1301/1302@2026-11-01T11:45:00Z: thread [private thread] has no branch
EOF
expect 'scope blocker: an edited question raises it again through a wake' 0 check.json "$BLOCK13 | $LOOK13"' | edit(13; 1302; "11:45"; "Needs-info: synthetic scope question with changed inputs.")' -- wake 13 <<EOF
needs-info #13: a question for the orchestrator
look #13: blocked on scope 1301/1302@2026-11-01T11:45:00Z: thread [private thread] has no branch
EOF
expect 'scope blocker: an edited answer raises it again' 0 check.json "$BLOCK13"' | say(13; 1305; "11:30"; "Orchestrator: synthetic answer.") | say(13; 1306; "11:31"; "launch-fleet: asked the orchestrator") | say(13; 1307; "11:32"; "launch-fleet: look: blocked on scope 1301/1305@2026-11-01T11:30:00Z: thread thr_syn13 has no branch") | edit(13; 1305; "11:50"; "Orchestrator: synthetic answer, corrected.")' -- check <<EOF
needs-info #13: a question for the orchestrator
look #13: blocked on scope 1301/1305@2026-11-01T11:50:00Z: thread [private thread] has no branch
EOF
expect 'scope blocker: an edit to its own records stays quiet' 0 check.json "$BLOCK13 | $LOOK13"' | edit(13; 1303; "11:50"; "launch-fleet: asked the orchestrator\nSynthetic detail.") | edit(13; 1304; "11:51"; "launch-fleet: look: blocked on scope 1301/1302@2026-11-01T11:25:00Z: thread thr_syn13 has no branch\nSynthetic detail.")' -- check < /dev/null
expect 'scope blocker: the needs-info label off, the start is checked again' 0 check.json "$BLOCK13 | $LOOK13"' | issue(13; .labels -= ["needs-answer"])' -- check <<EOF
check start #13: thread thr_syn13, no branch 30 minutes after the start
EOF

# Two starts due in one batch: #13 (spec #10) and #70 (approved on its own).
BATCH='merge12 | own_approval(70; 7002; "10:00")'
expect 'one probe per batch: both starts are due' 0 check.json "$BATCH" -- check <<EOF
start #13: W3: widget page (spec #10)
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'one probe per batch: the start not tried waits with the refused probe' 0 check.json "$BATCH"' | say(13; 1301; "11:55"; "launch-fleet: start refused: model catalog unavailable") | say(70; 7003; "11:55"; "launch-fleet: start not tried: #13 was refused: model catalog unavailable")' -- check < /dev/null
expect 'one probe per batch: 10 minutes on, the batch retries together' 0 check.json "$BATCH"' | say(13; 1301; "11:45"; "launch-fleet: start refused: model catalog unavailable") | say(70; 7003; "11:45"; "launch-fleet: start not tried: #13 was refused: model catalog unavailable")' -- check <<EOF
start #13: W3: widget page (spec #10; retry after "start refused: model catalog unavailable")
start #70: Fix the broken link in the widget docs (approved on its own; retry after "start not tried: #13 was refused: model catalog unavailable")
EOF
expect 'one probe per batch: a claim on a start not tried withdraws within 10 minutes' 0 check.json "$BATCH"' | say(70; 7003; "11:55"; "launch-fleet: start not tried: #13 was refused: model catalog unavailable") | say(70; 7004; "11:58"; "launch-fleet: starting")' -- claim 70 7004 <<EOF
withdraw #70: its start was refused less than 10 minutes ago
EOF
expect 'one probe per batch: the frontier leaves out a start not tried' 0 check.json "$BATCH"' | say(70; 7003; "11:55"; "launch-fleet: start not tried: #13 was refused: model catalog unavailable")' -- frontier <<EOF
#13 W3: widget page
EOF

### Token cuts (#694) in the skill: no superseded base-moved text, ticks end,
### re-checks carry their delta, one probe per batch, keyed scope blockers

# skill_has NAME TEXT / skill_lacks NAME REGEX: one case on the skill's text beside this folder,
# SKILL.md and its references (WS8 moved branch detail there, #1181).
SKILL="$HERE/../SKILL.md $HERE/../references/*.md"
skill_has() {
  [ -z "${TEST_ONLY:-}" ] || [ "$1" = "$TEST_ONLY" ] || return 0
  cases=$((cases + 1))
  # shellcheck disable=SC2086 # the list is the skill's own files
  if cat $SKILL | grep -qF -- "$2"; then echo "ok   $1"; else bad "$1" "SKILL.md lacks: $2"; fi
}
skill_lacks() {
  [ -z "${TEST_ONLY:-}" ] || [ "$1" = "$TEST_ONLY" ] || return 0
  cases=$((cases + 1))
  # shellcheck disable=SC2086
  if cat $SKILL | grep -qiE -- "$2"; then bad "$1" "SKILL.md still has: $(cat $SKILL | grep -iE -- "$2" | head -n 1)"; else echo "ok   $1"; fi
}
if take; then
  skill_lacks 'skill: no superseded base-moved merge text' 'base moved'
  skill_has 'skill: M1 alone decides a move of main' 'A move of `main` alone is never a reason to close and reopen a pull request'
  skill_has 'skill: the brief carries no merge rule' 'The brief is only the prompt above'
  skill_has 'skill: a tick archives itself once its records are written' 'once every record and message is written, archive your own thread'
  skill_lacks 'skill: a tick never stays open for the user' 'leave it open with a one-line verdict'
  # The re-check message's ids, both heads and delta: test-brief.py's re-check case (WS8).
  skill_has 'skill: one probe per batch, by assignment' 'start that group'"'"'s first claim alone, the probe'
  skill_has 'skill: the start not tried record' '`start not tried: <why>`'
  skill_has 'skill: a scope blocker is raised once per key' '`look #N: blocked on scope <key>: ...`'
fi

### Conditional ordering holds (#1482): synthetic records and API shapes.
# Labels, comments, merge states and fingerprints are controlled independently.
ORDER13='merge12 | issue(13; .labels = ["held"]) | held_at(13; "11:09")
  | say(13; 1301; "11:10"; "launch-fleet: held for ordering: issue #71 merges to main")'
ORDER71='closed_single(71; "11:30") | merged_pr(72; 71; "11:30"; [])'
ORDERCLAIM='say(13; 1302; "11:59"; "launch-fleet: release starting 1301, thread thr_syntick1")'
ORDERLEGACY='merge12 | issue(13; .labels = ["held"]) | held_at(13; "11:09")
  | say(13; 1301; "11:10"; "Orchestrator: **held for ordering only; the plan and its approval are unchanged.** #71 (approved on its own tonight) edits `fleet.sh`, which this ticket owns too, so the two never run at once. Released (`ready-for-agent` back, `held` off) as soon as #71 merges.")'
expect 'ordering: verified main merge offers only the owned release' 0 check.json "$ORDER13 | $ORDER71" -- check <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering: targeted wake verifies the held tickets full plan' 0 check.json "$ORDER13 | $ORDER71" -- wake 13 <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
log_has 'ordering: targeted wake verifies the held tickets full plan' 1 '^issue view 10 subIssues$'
expect 'ordering: a PR prerequisite requires its own main merge' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: PR #72 merges to main\")" -- check <<EOF_ORDER
release #13: ordering hold 1301; PR #72 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering: a merged PR into another base stays held' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: PR #72 merges to main\") | pull(72; .base = \"release-1\")" -- check < /dev/null
expect 'ordering: a closed unmerged PR stays held' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: PR #72 merges to main\") | pull(72; .state = \"CLOSED\" | .mergedAt = null)" -- check < /dev/null
expect 'ordering: closed unmerged issue stays held' 0 check.json "$ORDER13 | closed_single(71; \"11:30\")" -- check < /dev/null
expect 'ordering: open prerequisite stays held' 0 check.json "$ORDER13 | $ORDER71 | issue(71; .state = \"OPEN\")" -- check < /dev/null
expect 'ordering: wrong base issue merge stays held' 0 check.json "$ORDER13 | $ORDER71 | pull(72; .base = \"release-1\")" -- check < /dev/null
expect 'ordering: incomplete prerequisite relationships stay held' 0 check.json "$ORDER13 | $ORDER71 | issue(71; .linkedPrsTruncated = true)" -- check < /dev/null
expect 'ordering: missing prerequisite stays held' 0 check.json "$ORDER13" -- check < /dev/null
expect 'ordering: PR number cannot impersonate an issue' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: issue #72 merges to main\")" -- check < /dev/null
expect 'ordering: issue number cannot impersonate a PR' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: PR #71 merges to main\")" -- check < /dev/null
expect 'ordering: another unmet native blocker stays held' 0 check.json "$ORDER13 | $ORDER71 | issue(12; .state = \"OPEN\")" -- check < /dev/null
ORDER_STALE="$ORDER13 | $ORDER71 @@then@@ issue(13; .body += \"Changed plan.\")"
ORDER_STALE_FP=$(fp12 check.json "$ORDER_STALE" 10)
expect 'ordering: stale fingerprint never releases' 0 check.json "$ORDER_STALE" -- wake 13 <<EOF_ORDER
re-approve #10: changed since revision 1 (fingerprint now $ORDER_STALE_FP)
EOF_ORDER
expect 'ordering: manual hold cannot be inferred from a closed blocker' 0 check.json 'merge12 | issue(13; .labels = ["held"]) | held_at(13; "11:09") | say(13; 1301; "11:10"; "Orchestrator: manual hold until I approve.")' -- check < /dev/null
expect 'ordering: contract hold still needs reapproval' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"launch-fleet: held for #72: contract changed, re-approve.\")" -- check < /dev/null
expect 'ordering: a contract change does not prevent an ordering release' 0 check.json "$ORDER13 | $ORDER71 | contract23" -- check <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering: production live hold is not an ordering record' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for production/live: wait for #71\")" -- check < /dev/null
expect 'ordering: new manual label ownership defeats older ordering evidence' 0 check.json "$ORDER13 | $ORDER71 | held_at(13; \"11:40\")" -- check < /dev/null
expect 'ordering: missing label timeline cannot prove ownership' 0 check.json "$ORDER13 | $ORDER71 | issue(13; .labelEvents = [])" -- check < /dev/null
expect 'ordering: needs info prevents release' 0 check.json "$ORDER13 | $ORDER71 | issue(13; .labels += [\"needs-answer\"]) | say(13; 1302; \"11:20\"; \"launch-fleet: asked the orchestrator\")" -- check < /dev/null
expect 'ordering: malformed extra release condition stays held' 0 check.json "$ORDER13 | $ORDER71 | edit(13; 1301; \"11:10\"; \"launch-fleet: held for ordering: issue #71 merges to main and live passes\")" -- check < /dev/null
expect 'ordering: legacy explicit ordering-only record is reconciled' 0 check.json "$ORDERLEGACY | $ORDER71" -- check <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering: legacy mismatched release issue stays held' 0 check.json "$ORDERLEGACY | $ORDER71 | issue(13; .comments[-1].body |= sub(\"as soon as #71\"; \"as soon as #11\"))" -- check < /dev/null
expect 'ordering: already manually released legacy hold is not released again' 0 check.json "$ORDERLEGACY | $ORDER71 | issue(13; .labels = [\"ready-for-agent\"])" -- wake 13 <<EOF_ORDER
start #13: W3: widget page (spec #10)
EOF_ORDER
expect 'ordering: release is not a frontier builder start' 0 check.json "$ORDER13 | $ORDER71" -- frontier < /dev/null
expect 'ordering: oldest release claim may act' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM" -- claim 13 1302 <<EOF_ORDER
go #13
EOF_ORDER
expect 'ordering: duplicate release claim withdraws' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | say(13; 1303; \"11:59\"; \"launch-fleet: release starting 1301, thread thr_syntick2\")" -- claim 13 1303 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: claim rechecks manual label ownership' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | held_at(13; \"11:59\")" -- claim 13 1302 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: claim rechecks prerequisite merge' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | pull(72; .base = \"release-1\")" -- claim 13 1302 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: duplicate wake leaves fresh release claim alone' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM" -- wake 13 < /dev/null
expect 'ordering: lost release reply reconciles instead of resending' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:49\"; \"launch-fleet: release starting 1301, thread thr_syntick1\")" -- wake 13 <<EOF_ORDER
reconcile release #13: ordering hold 1301; reconcile comment 1302, thread thr_syntick1
EOF_ORDER
expect 'ordering: removed held label with lost reply cannot start' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:49\"; \"launch-fleet: release starting 1301, thread thr_syntick1\") | issue(13; .labels = [\"ready-for-agent\"])" -- wake 13 <<EOF_ORDER
reconcile release #13: ordering hold 1301; reconcile comment 1302, thread thr_syntick1
EOF_ORDER
expect 'ordering: lost reply is not on the frontier' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | issue(13; .labels = [\"ready-for-agent\"])" -- frontier < /dev/null
expect 'ordering: partial labels still reconcile the same release' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:49\"; \"launch-fleet: release starting 1301, thread thr_syntick1\") | issue(13; .labels = [])" -- wake 13 <<EOF_ORDER
reconcile release #13: ordering hold 1301; reconcile comment 1302, thread thr_syntick1
EOF_ORDER
expect 'ordering: verified release completion permits ordinary start' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | edit(13; 1302; \"11:59\"; \"launch-fleet: released ordering 1301\") | issue(13; .labels = [\"ready-for-agent\"])" -- wake 13 <<EOF_ORDER
start #13: W3: widget page (spec #10)
EOF_ORDER
expect 'ordering: ordinary start still elects the oldest builder claim' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | edit(13; 1302; \"11:59\"; \"launch-fleet: released ordering 1301\") | issue(13; .labels = [\"ready-for-agent\"]) | say(13; 1303; \"11:59\"; \"launch-fleet: starting\") | say(13; 1304; \"11:59\"; \"launch-fleet: starting\")" -- claim 13 1304 <<EOF_ORDER
withdraw #13: an older claim or builder: "starting"
EOF_ORDER
expect 'ordering: builder claim cannot bypass lost release reply' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | issue(13; .labels = [\"ready-for-agent\"]) | say(13; 1303; \"11:59\"; \"launch-fleet: starting\")" -- claim 13 1303 <<EOF_ORDER
withdraw #13: it is not on the frontier now
EOF_ORDER
expect 'ordering: first builder claim after verified release goes' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | edit(13; 1302; \"11:59\"; \"launch-fleet: released ordering 1301\") | issue(13; .labels = [\"ready-for-agent\"]) | say(13; 1303; \"11:59\"; \"launch-fleet: starting\")" -- claim 13 1303 <<EOF_ORDER
go #13
EOF_ORDER
expect 'ordering: standalone held issue is discovered and released' 0 check.json 'own_approval(70; 7002; "10:00") | issue(70; .labels = ["held"]) | held_at(70; "11:09") | say(70; 7003; "11:10"; "launch-fleet: held for ordering: issue #11 merges to main")' -- check <<EOF_ORDER
release #70: ordering hold 7003; issue #11 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering: standalone held wake keeps its own approval requirement' 0 check.json 'own_approval(70; 7002; "10:00") | issue(70; .labels = ["held"]) | held_at(70; "11:09") | say(70; 7003; "11:10"; "launch-fleet: held for ordering: issue #11 merges to main")' -- wake 70 <<EOF_ORDER
release #70: ordering hold 7003; issue #11 merged to main; restore ready-for-agent and remove held
EOF_ORDER

expect 'ordering: superseded release stays uncertain' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:49\"; \"launch-fleet: release starting 1301, thread thr_syntick1\") | say(13; 1303; \"11:50\"; \"launch-fleet: held manual: owner decision required\") | held_at(13; \"11:50\")" -- wake 13 <<EOF_ORDER
reconcile release #13: ordering hold 1301; reconcile comment 1302, thread thr_syntick1
EOF_ORDER
expect 'ordering: a new conditional hold cannot bypass an old uncertain release' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:49\"; \"launch-fleet: release starting 1301, thread thr_syntick1\") | held_at(13; \"11:50\") | say(13; 1303; \"11:51\"; \"launch-fleet: held for ordering: issue #11 merges to main\") | say(13; 1304; \"11:59\"; \"launch-fleet: release starting 1303, thread thr_syntick2\")" -- claim 13 1304 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: snapshot disagreement never releases an approved fingerprint' 0 check.json "$ORDER_STALE" FAKE_GH_REVISION_WORLD=approved.json -- check < /dev/null
expect 'ordering: release claim rechecks stale fingerprint' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM @@then@@ issue(13; .body += \"Changed plan.\")" -- claim 13 1302 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: a later hold record withdraws the earlier release claim' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | say(13; 1303; \"11:59\"; \"launch-fleet: held manual: owner decision required\")" -- claim 13 1302 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering: a production live role remains held even with an ordering record' 0 check.json "$ORDER13 | $ORDER71 | issue(13; .labels += [\"ready-for-human\"])" -- check < /dev/null
expect 'ordering: unreadable held comments cannot authorize release' 0 check.json "$ORDER13 | $ORDER71" FAKE_GH_FAIL=issue_comments_13_page=1 -- wake 13 <<EOF_ORDER
look #13: comment history could not be read in full
EOF_ORDER
expect 'ordering: proven failure without label changes permits release retry' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | edit(13; 1302; \"11:59\"; \"launch-fleet: release failed 1301: confirmed no labels changed\")" -- wake 13 <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER

### R1: later manual/live instructions revoke ordering-only ownership.
expect 'ordering R1: qualified bold live hold supersedes ordering' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"Orchestrator (ops): **held for production/live: wait for the live check too.**\")" -- check < /dev/null
expect 'ordering R1: qualified free-form live hold supersedes ordering' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"Orchestrator (ops): also held until the live run passes; do not release on #71 alone.\")" -- check < /dev/null
expect 'ordering R1: non-record uppercase manual hold defeats ownership' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"Manual HOLD: wait for owner approval too.\")" -- check < /dev/null
expect 'ordering R1: later plain hold withdraws an existing release claim' 0 check.json "$ORDER13 | $ORDER71 | $ORDERCLAIM | say(13; 1303; \"11:59\"; \"Orchestrator (ops): also held until the live run passes.\")" -- claim 13 1302 <<EOF_ORDER
withdraw #13: that ordering release is not due or an older claim holds it
EOF_ORDER
expect 'ordering R1: unrelated plain comment preserves authorized release' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"Orchestrator (ops): prerequisite merge verified.\")" -- check <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering R1: household is not a hold instruction' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"Synthetic household example is documented.\")" -- check <<EOF_ORDER
release #13: ordering hold 1301; issue #71 merged to main; restore ready-for-agent and remove held
EOF_ORDER
expect 'ordering R1: qualified legacy prose grants no release authority' 0 check.json "$ORDERLEGACY | $ORDER71 | issue(13; .comments[-1].body |= sub(\"Orchestrator:\"; \"Orchestrator (ops):\"))" -- check < /dev/null
expect 'ordering R1: documented live hold record defeats ordering ownership' 0 check.json "$ORDER13 | $ORDER71 | say(13; 1302; \"11:20\"; \"launch-fleet: held live: verified live check still required\")" -- check < /dev/null

### #2218 (OB7a): a newer unresolved hold of any kind blocks a contract release.
OB7A=$(cat "$FIX/ops-on1/newer-manual-hold/world.jq")
expect 'OB7a: a newer manual hold keeps an approved contract hold held' 0 check.json "$OB7A" -- check < /dev/null
expect 'OB7a: a wake offers no release under a newer manual hold' 0 check.json "$OB7A" -- wake 13 < /dev/null
expect 'OB7a: a person'"'"'s ticket keeps a newer manual hold' 0 check.json "$OB7A | approve(10; 1003; \"11:35\"; 3; [11, 12, [13, \"ready-for-human\"], 14])" -- check < /dev/null
expect 'OB7a: a newer live hold keeps an approved contract hold held' 0 check.json "$OB7A | edit(13; 1302; \"11:40\"; \"launch-fleet: held live: verified live check still required\")" -- check < /dev/null
expect 'OB7a: a newer plain hold instruction keeps an approved contract hold held' 0 check.json "$OB7A | edit(13; 1302; \"11:40\"; \"Orchestrator (ops): **held for production/live: wait for the live check too.**\")" -- check < /dev/null
expect 'OB7a: a manual hold older than the approval stays unresolved' 0 check.json "$OB7A | issue(13; .comments |= map(if .id == 1302 then .at = at(\"11:10\") else . end))" -- check < /dev/null
expect 'OB7a: a manual hold ended before the held label went on does not block' 0 check.json "$OB7A | issue(13; .comments |= map(if .id == 1302 then .id = 1300 | .at = at(\"10:30\") else . end) | .comments |= sort_by(.id))" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF

### #2112 (OB7): a contract release passes only a complete, unchanged cutoff.
OB7=$(cat "$FIX/ops-on1/release-races/world.jq")
OB7LATE='merged_pr(26; 99; "11:45"; [changed("contracts/widget.v1.md"; "modified")])'
OB7CLAIM='say(13; 1303; "11:55"; "launch-fleet: release starting 1301")'
expect 'OB7: an answered contract hold with nothing newer is released' 0 check.json "$OB7" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a later contract merge does not block release' 0 check.json "$OB7 | $OB7LATE" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a wake releases the existing hold after a later merge' 0 check.json "$OB7 | $OB7LATE" -- wake 13 <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a renamed contract does not block release' 0 check.json "$OB7 | merged_pr(26; 99; \"11:45\"; [{filename: \"contracts/widget.v2.md\", status: \"renamed\", previous_filename: \"contracts/widget.v1.md\"}])" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a deleted contract does not block release' 0 check.json "$OB7 | merged_pr(26; 99; \"11:45\"; [changed(\"contracts/widget.v1.md\"; \"removed\")])" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a person'"'"'s ticket releases after a later contract merge' 0 check.json "$OB7 | approve(10; 1003; \"11:35\"; 3; [11, 12, [13, \"ready-for-human\"], 14]) | $OB7LATE" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a plan changed since its approval releases nothing' 0 check.json "$OB7 @@then@@ issue(14; .blockedBy = [12])" -- check <<EOF
re-approve #10: changed since revision 2 (fingerprint now e9f6f2a713ac)
EOF
expect 'OB7: an unresolved release claim blocks a second release' 0 check.json "$OB7 | $OB7CLAIM" -- check < /dev/null
expect 'OB7: a contract release claim is refused, the release effect stays off' 0 check.json "$OB7 | $OB7CLAIM" -- claim 13 1303 <<EOF
withdraw #13: that ordering release is not due or an older claim holds it
EOF
expect 'OB7: a partial relabel under an unresolved claim starts nothing' 0 check.json "$OB7 | issue(13; .labels = [\"ready-for-agent\"]) | $OB7CLAIM" -- check < /dev/null
expect 'OB7: a newer manual hold keeps the contract hold held' 0 check.json "$OB7 | say(13; 1302; \"11:40\"; \"launch-fleet: held manual: owner decision required\")" -- check < /dev/null
expect 'OB7: a noted contract merge after approval does not block release' 0 check.json "$OB7 | $OB7LATE | say(13; 1304; \"11:46\"; \"launch-fleet: noted #26\")" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF
expect 'OB7: a contract merge at the approval time does not block release' 0 check.json "$OB7 | merged_pr(26; 99; \"11:30\"; [changed(\"contracts/widget.v1.md\"; \"modified\")])" -- check <<EOF
release #13: approved again since its hold; take the held label off
EOF

# #2112 (OB7): ON1 evidence checks; the release effect stays disabled.
if [ -z "${TEST_ONLY:-}" ] || [ "$TEST_ONLY" = on1 ]; then
  if take; then
    cases=$((cases + 1))
    if python3 -I "$HERE/test-on1.py" > "$tmp/on1.log" 2>&1; then
      echo 'ok   on1'
    else
      bad on1 'ON1 evidence checks failed'
      cat "$tmp/on1.log"
    fi
  fi
fi

# #1273: public templates, title/branch recovery and review-span retirement.
if [ -z "${TEST_ONLY:-}" ] || [ "$TEST_ONLY" = public-records ]; then
  if take; then
    cases=$((cases + 1))
    if python3 "$HERE/test-records.py" > "$tmp/public-records.log" 2>&1; then
      echo 'ok   public-records'
    else
      bad public-records 'thread-free records or routing failed'
      cat "$tmp/public-records.log"
    fi
  fi
fi

# E5 (#721 R1): the private map in the shape SKILL.md documents stays readable
# by records.py: thread entries get synthetic thread ids, any other documented
# entry a synthetic loop-shaped id, so a non-thread value there is caught.
if [ -z "${TEST_ONLY:-}" ] || [ "$TEST_ONLY" = private-map ]; then
  if take; then
    cases=$((cases + 1))
    if python3 -I - "$HERE/../references/records.md" "$tmp/private-map.json" > "$tmp/private-map.log" 2>&1 <<'PY' \
      && printf '{"specs":[],"singles":[]}' | LAUNCH_FLEET_STATE="$tmp/private-map.json" \
        python3 -I "$HERE/records.py" synthetic-owner/synthetic-repo false >> "$tmp/private-map.log" 2>&1; then
import json, re, sys
text = open(sys.argv[1]).read()
shape = re.search(r'Its shape is `(\{.*?\}\})`', text).group(1)
state = json.loads(shape)
state['repo'] = 'synthetic-owner/synthetic-repo'
state['threads'] = {k: 'thr_synthetic' if v in ('<thread>', '<sender>', '<fleet>')
                    else '00000000-0000-4000-8000-000000000010' for k, v in state['threads'].items()}
json.dump(state, open(sys.argv[2], 'w'))
PY
      echo 'ok   private-map'
    else
      bad private-map "records.py can't read the private map references/records.md documents"
      cat "$tmp/private-map.log"
    fi
  fi
fi

# E8: the carried O10/triage fixture runs in a release-shaped tree, a copy of
# the carried skills with no Git history, on those carried sources.
if [ -z "${TEST_ONLY:-}" ] || [ "$TEST_ONLY" = o10-release ]; then
  if take; then
    cases=$((cases + 1))
    rel=$tmp/o10-release
    if mkdir -p "$rel/skills" && cp -R "$HERE/../../launch-fleet" "$HERE/../../triage" "$HERE/../../to-tickets" "$rel/skills/" \
      && (cd "$rel" && GIT_CEILING_DIRECTORIES=$tmp python3 -I skills/launch-fleet/scripts/fixtures/test-o10-triage.py) > "$tmp/o10-release.log" 2>&1; then
      echo 'ok   o10-release'
    else
      bad o10-release 'the carried O10/triage fixture needs source Git history'
      cat "$tmp/o10-release.log"
    fi
  fi
fi

### The pinned revision.sh is to-tickets’

if [ -z "${TEST_ONLY:-}" ] && take; then
  cases=$((cases + 1))
  if cmp -s "$FIX/revision.sh" "$HERE/../../to-tickets/revision.sh"; then
    echo "ok   the pinned revision.sh is to-tickets’, byte for byte"
  else
    bad "the pinned revision.sh is to-tickets’, byte for byte" "fixtures/revision.sh differs from skills/to-tickets/revision.sh: copy it again"
  fi
fi

### GI1 (#2543): a fleet thread's check skips unchanged reads

# A spec of a real spec's size (fixtures/unchanged/spec.jq: twelve tickets,
# two open pull requests, a merged one, blockers, a contract it relies on, and
# a start claim that comes due with time). Every run of `spec 10` shares one
# cache, a minute or more apart; each is compared with a full read of the same
# world at the same time from an empty cache (ref N), which is what the check
# must print. The fake GitHub's log counts the GraphQL reads; its HTTP log
# counts the 304s. GH_TOKEN is a synthetic secret no output may contain.
GI1=$(cat "$FIX/unchanged/spec.jq") || { echo "FAIL setup: the GI1 fixture"; exit 1; }
GI1_SECRET=synthetic-token-gi1-0000
gi1_run() { # N DIR CACHE SECONDS: run N of spec 10 on DIR/world.json, SECONDS after NOW
  (cd "$2" && env PATH="$tmp/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo GH_TOKEN=$GI1_SECRET \
    FAKE_GH_WORLD="$2/world.json" FAKE_GH_LOG="$2/gh-$1.log" FAKE_GH_HTTP_LOG="$2/http-$1.log" \
    LAUNCH_FLEET_NOW=$((NOW + $4)) LAUNCH_FLEET_CACHE="$3" LAUNCH_FLEET_REVISION="$FIX/revision.sh" \
    /bin/sh "$FLEET" spec 10 > "$2/out-$1" 2> "$2/err-$1")
}
# gi1_pair N SECONDS: run N on the shared cache and its full-read reference;
# the same exit 0 and the same lines.
gi1_pair() {
  : > "$d/gh-$1.log" && : > "$d/http-$1.log" || return 1
  gi1_run "$1" "$d" "$d/cache" "$2" || { gi1_why="run $1 failed: $(head -c 300 "$d/err-$1")"; return 1; }
  rm -rf "$d/ref" && mkdir "$d/ref" && cp "$d/world.json" "$d/ref/world.json" || return 1
  gi1_run "$1" "$d/ref" "$d/ref/cache" "$2" || { gi1_why="reference $1 failed"; return 1; }
  cmp -s "$d/out-$1" "$d/ref/out-$1" || { gi1_why="run $1 printed $(diff "$d/ref/out-$1" "$d/out-$1" | head -c 400)"; return 1; }
}
gi1_graphql() { grep -c '^graphql ' "$d/gh-$1.log"; }
# gi1_full N: run N was a full read; gi1_unchanged N: it read no GraphQL and
# says how many of its reads were unchanged, every one of them a 304.
gi1_read() { [ "$(gi1_graphql "$1")" -gt 0 ] || { gi1_why="run $1 read no GraphQL"; return 1; }; }
gi1_full() {
  gi1_read "$1" || return 1
  grep -qxE "$POINTS" "$d/err-$1" || { gi1_why="run $1's stderr: $(head -c 300 "$d/err-$1")"; return 1; }
}
gi1_unchanged() {
  [ "$(gi1_graphql "$1")" = 0 ] || { gi1_why="run $1 read GraphQL $(gi1_graphql "$1") times"; return 1; }
  u=$(grep -c ' 304$' "$d/http-$1.log") && [ "$u" -gt 0 ] && [ "$u" = "$(grep -c '' "$d/http-$1.log")" ] \
    || { gi1_why="run $1 made reads that were not 304s"; return 1; }
  grep -qx "fleet\.sh: used 0 GitHub points in [0-9]* questions, $u unchanged; no GraphQL read" "$d/err-$1" \
    || { gi1_why="run $1's points line: $(cat "$d/err-$1")"; return 1; }
}
gi1_change() { jq "$LIB $1" "$d/world.json" > "$d/next.json" && mv "$d/next.json" "$d/world.json"; }
gi1_snapshot() { find "$d/cache" -name 'unchanged-spec-10.json' | head -n 1; }
gi1_case() {
  name=$1 mode=$2
  selected "$name" || return 0
  take heavy || return 0
  cases=$((cases + 1))
  d=$tmp/gi1-$cases gi1_why=''
  mkdir "$d" && world check.json "$GI1" "$d" > "$d/world.json" || { bad "$name" "setup"; return; }
  # Runs 1 and 2 are full reads; run 2 also learns what the probe asks.
  gi1_pair 1 0 && gi1_read 1 && gi1_pair 2 60 && gi1_read 2 || { bad "$name" "$gi1_why"; return; }
  case $mode in
    unchanged)
      gi1_pair 3 120 && gi1_unchanged 3 && gi1_pair 4 180 && gi1_unchanged 4 || { bad "$name" "$gi1_why"; return; }
      # Before and after, on this real-sized spec: the full read's points and the unchanged check's.
      # Before: run 2, a full read of the same unchanged spec on a warm cache.
      before=$(sed -n 's/^fleet\.sh: used \([0-9]*\) GitHub points.*/\1/p' "$d/err-2")
      printf 'GI1 points per unchanged check on a 12-ticket spec: before %s (a warm full read), after 0 (%s)\n' \
        "$before" "$(cat "$d/err-4")" > "$tmp/gi1-points.txt"
      for f in "$d"/out-* "$d"/err-*; do
        if grep -qF "$GI1_SECRET" "$f" || jq -r '.etag // empty' "$d"/cache/*/*/rest-*.json 2> /dev/null | grep -qF -f - "$f"; then
          bad "$name" "a token or ETag in $(basename "$f")"; return
        fi
      done ;;
    changed-probes | expired-probes)
      gi1_pair 3 120 && gi1_unchanged 3 || { bad "$name" "$gi1_why"; return; }
      if [ "$mode" = changed-probes ]; then
        gi1_change 'say(13; 1301; "11:59"; "Synthetic question")' || { bad "$name" "change failed"; return; }
        at=180
      else at=1860; fi
      gi1_pair 4 "$at" && gi1_full 4 || { bad "$name" "$gi1_why"; return; }
      # R1: prime before the full read so the very next unchanged tick
      # reuses its GraphQL snapshot. Every tick retains full due-line parity.
      next_at=$((at + 60))
      gi1_pair 5 "$next_at" && gi1_unchanged 5 || { bad "$name" "$gi1_why"; return; }
      if [ "$mode" = changed-probes ]; then
        gi1_change 'say(13; 1302; "12:01"; "Synthetic second question")' || { bad "$name" "second change failed"; return; }
        gi1_pair 6 300 && gi1_full 6 && gi1_pair 7 360 && gi1_unchanged 7 \
          || { bad "$name" "$gi1_why"; return; }
      fi
      printf 'R1 %s GraphQL reads by tick:' "$mode"
      for tick in 1 2 3 4 5; do printf ' %s' "$(gi1_graphql "$tick")"; done
      if [ "$mode" = changed-probes ]; then
        for tick in 6 7; do printf ' %s' "$(gi1_graphql "$tick")"; done
      fi
      printf '\n' ;;
    merged-checks)
      gi1_pair 3 120 && gi1_unchanged 3 || { bad "$name" "$gi1_why"; return; }
      # Closed tickets archive from their merge and records, not later CI
      # results. Keep probing PR metadata (including a changed state/head).
      gi1_change 'pull(27; .rollup = "FAILURE" | .checks[0].conclusion = "FAILURE")' \
        || { bad "$name" "merged check change failed"; return; }
      gi1_pair 4 180 && gi1_unchanged 4 || { bad "$name" "$gi1_why"; return; }
      gi1_change 'pull(36; .checks[1].status = "COMPLETED" | .checks[1].conclusion = "FAILURE" | .rollup = "FAILURE")' \
        || { bad "$name" "open check change failed"; return; }
      gi1_pair 5 240 && gi1_full 5 || { bad "$name" "$gi1_why"; return; } ;;
    time)
      grep -q '^reconcile start #61' "$d/out-2" && { bad "$name" "the claim was due too soon"; return; }
      gi1_pair 3 480 && gi1_unchanged 3 || { bad "$name" "$gi1_why"; return; }
      grep -q '^reconcile start #61: claimed at 2026-11-01T11:55:00Z, no outcome after 10 minutes$' "$d/out-3" \
        || { bad "$name" "the claim did not come due from saved facts: $(cat "$d/out-3")"; return; } ;;
    age)
      # Run 2 at minute 1 was the last full read: 29 minutes 59 seconds on it
      # is unchanged; 30 minutes on it is a full read.
      gi1_pair 3 120 && gi1_unchanged 3 || { bad "$name" "$gi1_why"; return; }
      gi1_pair 4 1859 && gi1_unchanged 4 || { bad "$name" "29:59 on: $gi1_why"; return; }
      gi1_pair 5 1860 && gi1_full 5 || { bad "$name" "30:00 on: $gi1_why"; return; } ;;
    *)
      gi1_pair 3 120 && gi1_unchanged 3 || { bad "$name" "$gi1_why"; return; }
      snap=$(gi1_snapshot)
      case $mode in
        issue) gi1_change 'say(13; 1301; "11:59"; "Synthetic question")' ;;
        label) gi1_change 'issue(19; .labelEvents += [{name: "ready-for-agent", at: at("11:59")}])' ;;
        pr) gi1_change 'pull(35; .head = sha("35f"))' ;;
        check) gi1_change 'pull(36; .checks[1].status = "COMPLETED" | .checks[1].conclusion = "FAILURE" | .rollup = "FAILURE")' ;;
        review) gi1_change 'pr_say(35; 3502; "11:59"; "VERDICT: APPROVE at \(sha(35))")' ;;
        link) gi1_change 'open_pr(37; 62; "#62: widget cleanup")' ;;
        merge) gi1_change 'm23([changed("contracts/widget.v1.md"; "modified")]) | .pulls[-1].mergedAt = at("11:59")' ;;
        auth) gi1_change '.login = "synthetic-other-user"' ;;
        installation) gi1_change '.installation = "synthetic-other-installation"' ;;
        switch) LAUNCH_FLEET_GITHUB_AUTH=installation FAKE_GH_FAIL=user && export LAUNCH_FLEET_GITHUB_AUTH FAKE_GH_FAIL ;;
        lost) [ -n "$snap" ] && rm "$snap" ;;
        damaged) [ -n "$snap" ] && printf 'x' >> "$snap" ;;
        unreadable) [ -n "$snap" ] && rm "$snap" && mkdir "$snap" ;;
        request) # A whole, well-formed snapshot of another spec's check.
          [ -n "$snap" ] && jq -c '.body |= (fromjson | .spec = 40 | tojson)' "$snap" > "$d/snap" \
            && jq -c --arg h "$(jq -j .body "$d/snap" | sha256sum | cut -c1-64)" '.sha256 = $h' "$d/snap" > "$snap" ;;
        rest) find "$d/cache" -name 'rest-*.json' -exec sh -c 'printf x >> "$1"' sh {} \; ;;
      esac || { bad "$name" "can't make the change"; return; }
      gi1_pair 4 180 && gi1_full 4 || { bad "$name" "$gi1_why"; return; } ;;
  esac
  echo "ok   $name"
}
gi1_case 'WZ-PROBE: merged PR checks cannot invalidate identical due lines' merged-checks
gi1_case 'WZ-PROBE: changed ticks retain immediate snapshot reuse with identical due lines' changed-probes
gi1_case 'WZ-PROBE: expired ticks retain immediate snapshot reuse with identical due lines' expired-probes
gi1_case 'GI1: an unchanged spec reads no GraphQL and prints what a full read prints' unchanged
gi1_case 'GI1: a line due with time comes due from saved facts' time
gi1_case 'GI1: a full read 30 minutes old is read again' age
gi1_case 'GI1: a changed ticket gets a full read' issue
gi1_case 'GI1: a changed label event gets a full read' label
gi1_case "GI1: a pull request's new head gets a full read" pr
gi1_case 'GI1: a changed check gets a full read' check
gi1_case 'GI1: a new review verdict gets a full read' review
gi1_case 'GI1: a newly linked pull request gets a full read' link
gi1_case 'GI1: a merge to main gets a full read' merge
gi1_case 'GI1: another account gets a full read' auth
gi1_case 'GI1: a lost cache gets a full read' lost
gi1_case 'GI1: a damaged cache gets a full read' damaged
gi1_case 'GI1: an unreadable cache gets a full read' unreadable
gi1_case "GI1: another request's cache gets a full read" request
gi1_case 'GI1: damaged probe answers get a full read' rest
# GI7 (#2549): an App installation token can't read `user` (modelled as its
# failure); the check probes what the installation covers instead.
export LAUNCH_FLEET_GITHUB_AUTH=installation FAKE_GH_FAIL=user
gi1_case 'GI7: an unchanged spec read with an App token reads no GraphQL' unchanged
gi1_case 'GI7: another installation gets a full read' installation
unset LAUNCH_FLEET_GITHUB_AUTH FAKE_GH_FAIL
gi1_case "GI7: a switch from the account to the App gets a full read" switch
unset LAUNCH_FLEET_GITHUB_AUTH FAKE_GH_FAIL
if [ -s "$tmp/gi1-points.txt" ]; then cat "$tmp/gi1-points.txt"; fi

### GI2 (#2544): GitHub's messages wake a spec's fleet thread through its loop

# Synthetic records and loop ids only. A wake that names numbers in a spec
# with a fleet thread prints one line to run that thread's own loop, and none
# of the spec's tick lines; a spec with no fleet thread, or a record that
# names no loop, or a loop two specs claim, behaves as before GI2.
GI2_LOOP10=fleet-10 # E5: the public per-spec handle; the real loop id stays private
GI2_LOOP40=fleet-40
GI2_FLEET10="say(10; 1090; \"10:00\"; \"launch-fleet: fleet active, loop $GI2_LOOP10\")"
GI2_FLEET40="say(40; 4090; \"10:00\"; \"launch-fleet: fleet active, loop $GI2_LOOP40\")"
expect 'GI2: a wake on a spec with a fleet thread runs its loop, and prints none of its lines' 0 check.json "merge12 | $SPEC40 | $GI2_FLEET10" -- wake 13 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
EOF
expect 'GI2: a burst naming a spec, its tickets and its pull request runs its loop once' 0 check.json "pr31 | $GI2_FLEET10" -- wake 31 12 13 10 13 31 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
EOF
expect 'GI2: in a public repository too' 0 check.json "merge12 | $GI2_FLEET10 | .private = false" -- wake 13 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
EOF
expect 'GI2: numbers in other specs in the same batch behave as today' 0 check.json "merge12 | $SPEC40 | $GI2_FLEET10" -- wake 13 41 70 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
start #41: G1: gadget model (spec #40)
start #70: Fix the broken link in the widget docs (approved on its own)
EOF
expect 'GI2: two specs with fleet threads each run their own loop' 0 check.json "merge12 | $SPEC40 | $GI2_FLEET10 | $GI2_FLEET40" -- wake 41 13 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
wake fleet #40: room-cli loop run $GI2_LOOP40
EOF
expect 'GI2: the latest fleet record names the loop' 0 check.json "merge12 | say(10; 1080; \"09:00\"; \"launch-fleet: fleet active, loop $GI2_LOOP40\") | $GI2_FLEET10" -- wake 13 <<EOF
wake fleet #10: room-cli loop run $GI2_LOOP10
EOF
expect 'GI2: a spec with no fleet record gets its tick lines, as today' 0 check.json "merge12 | $SPEC40 | $GI2_FLEET40" -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect 'GI2: a fleet record that names no loop is left to the fleet thread, as today' 0 check.json 'merge12 | say(10; 1090; "10:00"; "launch-fleet: fleet thread thr_synfleet10")' -- wake 13 < /dev/null
expect 'GI2: an unreadable fleet record is no fleet record, as today' 0 check.json 'merge12 | say(10; 1090; "10:00"; "launch-fleet: fleet active, loop <the loop id>")' -- wake 13 <<EOF
start #13: W3: widget page (spec #10)
EOF
expect "GI2: a loop id room-cli would read as a flag runs nothing, as today" 0 check.json 'merge12 | say(10; 1090; "10:00"; "launch-fleet: fleet active, loop --all")' -- wake 13 < /dev/null
expect 'GI2: a loop two specs claim runs for neither, and each is left as today' 0 check.json "merge12 | $SPEC40 | $GI2_FLEET10 | say(40; 4090; \"10:00\"; \"launch-fleet: fleet active, loop $GI2_LOOP10\")" -- wake 13 41 < /dev/null
expect 'GI2: an unreadable comment history runs no loop and is looked at, as today' 0 check.json "merge12 | $GI2_FLEET10 | issue(10; .comments += discussion(118))" FAKE_GH_FAIL=issue_comments_10_page=1 -- wake 13 <<EOF
look #10: comment history could not be read in full
EOF
expect "GI2: the project check and the fleet thread's own check are unchanged" 0 check.json "merge12 | $GI2_FLEET10" -- spec 10 <<EOF
start #13: W3: widget page (spec #10)
EOF

### Every case ran, and every call was a read

if [ -n "$WORKER" ]; then
  done_group
  printf '%s %s %s\n' "$cases" "$fails" "$grp" > "$SHARED/result-$WORKER-$PASS"
  exit 0
fi
only_reads "$tmp"/case-*/gh*.log "$tmp"/cache-*/gh.log "$tmp"/loop/log[0-9] "$tmp"/gi1-*/gh-*.log
expected=${TEST_EXPECTED:-1}
case ${TEST_ONLY:-} in
  loop) expected=4 ;;
  fleet-loop) expected=2 ;;
  'contexts:*') expected=31 ;;
  'contexts R1:*') expected=4 ;;
  'CI:*') expected=18 ;;
  'OB7a:*') expected=7 ;;
  'OB7:*') expected=13 ;;
  'GI1:*') expected=16 ;;
  'WZ-PROBE:*') expected=3 ;;
  'GI2:*') expected=13 ;;
  'CW-G:*') expected=2 ;;
esac
[ "$cases" = "$expected" ] || bad 'the selected cases ran' "$cases cases ran, not $expected: is \"$TEST_ONLY\" a case's name?"

echo "$cases cases, $fails failed"
[ "$fails" = 0 ]
