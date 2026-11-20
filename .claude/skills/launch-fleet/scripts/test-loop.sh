#!/bin/sh
# #384: a generated Loop must outlive its plugin install and work in a
# consumer with no skills/. All GitHub answers and git remotes are synthetic.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
FIX=$HERE/fixtures
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir -p "$work/bin" "$work/plugin cache/skills/launch-fleet/scripts/carried" \
  "$work/plugin cache/skills/to-tickets" "$work/remote" "$work/runtime"
cp "$HERE/loop.sh" "$HERE/fleet.sh" "$HERE/records.py" "$work/plugin cache/skills/launch-fleet/scripts/"
cp "$HERE/../../to-tickets/revision.sh" "$HERE/../../to-tickets/check-links.sh" "$work/plugin cache/skills/to-tickets/"
cp "$HERE/carried/alarm.py" "$work/plugin cache/skills/launch-fleet/scripts/carried/"
mkdir "$work/linked skills"
ln -s "$work/plugin cache/skills/launch-fleet" "$work/linked skills/launch-fleet"
# GI7 (#2549): the fake gh also records the token each call gets (synthetic).
printf '#!/bin/sh\nprintf "%%s %%s\\n" "${GH_TOKEN:-none}" "${LAUNCH_FLEET_GITHUB_AUTH:-account}" >> "%s"\nexec "%s" -I -S "%s" "$@"\n' \
  "$work/gh-token.log" "$(command -v python3)" "$FIX/gh.py" > "$work/bin/gh"
chmod +x "$work/bin/gh"
export PATH="$work/bin:$PATH" GH_REPO=synthetic-owner/synthetic-repo
export FAKE_GH_REMOTE="$work/remote" FAKE_GH_WORLD="$work/world.json" FAKE_GH_LOG="$work/gh.log"
export LAUNCH_FLEET_HOME="$work/home" LAUNCH_FLEET_CACHE="$work/cache"
export LAUNCH_FLEET_NOW=1793534400 TMPDIR="$work/runtime"
unset GH_TOKEN GITHUB_TOKEN OPENWIZ_GITHUB_APP_KEY
# CS5 setup uses caller-normalized synthetic reads and durable repository state.
jq --argjson now "$LAUNCH_FLEET_NOW" '.observed_at = $now |
  .budgets[] |= (.reset_at = ($now + 3600))' \
  "$HERE/carried/healthy.json" > "$work/observation.json"
export LAUNCH_FLEET_OVERLOAD_INPUT="$work/observation.json"
export LAUNCH_FLEET_OVERLOAD_STATE="$work/pause.json"
unset LAUNCH_FLEET_REVISION
git -C "$work/remote" init -q
printf 'one\n' > "$work/remote/version"
git -C "$work/remote" add version
git -C "$work/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -qm one
jq '(.issues[] | select(.number == 12)) |= (.state = "CLOSED" | .comments += [
  {id: 1202, at: "2026-11-01T11:05:00Z", body: "launch-fleet: archived"}])
  | .pulls += [(.pulls[0] | .number = 22 | .closes = [12] | .mergedAt = "2026-11-01T11:00:00Z"
    | .files = [{filename: "src/store/store.rs", status: "modified"}])]' "$FIX/check.json" > "$work/world.json"
sh "$FIX/revision.sh" 10 > "$work/revision"
fingerprint=$(sha256sum < "$work/revision" | cut -d' ' -f1)
jq --arg fp "$fingerprint" '(.issues[].comments[]?.body) |= gsub("@@FP@@"; $fp)' \
  "$work/world.json" > "$work/approved.json"
mv "$work/approved.json" "$work/world.json"

# This is the setup command's public seam. The uploaded file must carry all
# three scripts; neither the install nor the consumer provides them at run time.
python3 - "$HERE/../references/launch.md" "$work/linked skills/launch-fleet" "$work/loop.sh" <<'PY'
import pathlib
import subprocess
import sys
import textwrap

text = pathlib.Path(sys.argv[1]).read_text()
setup = text.split("## Launch", 1)[1].split("```sh\n", 1)[1]
setup = textwrap.dedent(setup.split('   room-cli loop create --name', 1)[0])
setup = setup.replace("<this skill's folder>", sys.argv[2])
setup = setup.replace("<owner>/<repo>", "synthetic-owner/synthetic-repo")
setup = setup.replace("/tmp/launch-fleet-loop.sh", sys.argv[3])
subprocess.run(["sh", "-c", setup], check=True)
PY
sh -n "$work/loop.sh"
rm -rf "$work/plugin cache"
cd "$work"
printf 'start #13: W3: widget page (spec #10)\n' > "$work/want"
fallback="loop.sh: no OPENWIZ_GITHUB_APP_KEY secret; GitHub as today's account"
run() {
  if sh "$work/loop.sh" > "$work/out" 2> "$work/err"; then :
  else cat "$work/err" >&2; return 1; fi
  cmp "$work/want" "$work/out"
  [ "$(grep -c '^fleet.sh: used ' "$work/err")" = 1 ]
  [ "$(head -n 1 "$work/err")" = "$fallback" ]
  [ "$(wc -l < "$work/err" | tr -d ' ')" = 2 ]
  grep -qx 'issue view 10 subIssues' "$work/gh.log"
  [ -z "$(ls -A "$work/runtime")" ]
}
run
[ ! -e "$LAUNCH_FLEET_HOME/$GH_REPO/skills" ]
grep -qx 'repo clone' "$work/gh.log"
echo 'ok   bundled loop runs the packaged fleet and revision in a plain consumer'

# The consumer still refreshes. Its later skills must not replace the bundle.
printf 'two\n' > "$work/remote/version"
mkdir -p "$work/remote/skills/launch-fleet/scripts" "$work/remote/skills/to-tickets"
printf 'exit 99\n' > "$work/remote/skills/launch-fleet/scripts/fleet.sh"
printf 'exit 99\n' > "$work/remote/skills/to-tickets/revision.sh"
git -C "$work/remote" add -A
git -C "$work/remote" -c user.name=synthetic -c user.email=synthetic@example.invalid commit -qm two
rm -rf "$work/cache"
: > "$work/gh.log"
run
[ "$(cat "$LAUNCH_FLEET_HOME/$GH_REPO/version")" = two ]
! grep -q 'repo clone' "$work/gh.log"
echo 'ok   later runs refresh the consumer while keeping the packaged helpers'

# E6: the installed loop.sh run directly (no bundle) uses its own installed
# fleet and revision helpers, never the consumer clone's hostile skills/.
mkdir -p "$work/installed/skills/launch-fleet/scripts/carried" "$work/installed/skills/to-tickets"
cp "$HERE/loop.sh" "$HERE/fleet.sh" "$HERE/records.py" "$work/installed/skills/launch-fleet/scripts/"
cp "$HERE/../../to-tickets/revision.sh" "$HERE/../../to-tickets/check-links.sh" "$work/installed/skills/to-tickets/"
cp "$HERE/carried/alarm.py" "$work/installed/skills/launch-fleet/scripts/carried/"
rm -rf "$work/cache"
status=0
sh "$work/installed/skills/launch-fleet/scripts/loop.sh" > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 0 ] || { cat "$work/err" >&2; exit 1; }
cmp "$work/want" "$work/out"
[ -z "$(ls -A "$work/runtime")" ]
echo 'ok   a direct installed loop runs its installed helpers, not the consumer skills/'

# GI7 (#2549): the check reads GitHub as the App when the loop has the key's
# secret, and as today's account, saying so, when it is missing or the mint
# fails. No token reaches the output or a process argument.
token=synthetic-app-token-2549
{
  printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s"\n' "$work/openwiz.log"
  printf '[ "${FAKE_OPENWIZ_FAIL:-}" = 1 ] && { echo "openwiz: github token: refused" >&2; exit 5; }\n'
  printf 'printf "%%s\\n" %s\necho "expires_at 1793538000" >&2\n' "$token"
} > "$work/bin/openwiz"
chmod +x "$work/bin/openwiz"
identity() { # "token identity" every gh call gets; the stderr line expected, or ''
  rm -rf "$work/cache"
  : > "$work/gh-token.log"
  : > "$work/openwiz.log"
  sh "$work/loop.sh" > "$work/out" 2> "$work/err" || { cat "$work/err" >&2; return 1; }
  cmp "$work/want" "$work/out"
  [ -s "$work/gh-token.log" ]
  [ -z "$(grep -vx "$1" "$work/gh-token.log")" ]
  [ "$(grep -c '^fleet.sh: used ' "$work/err")" = 1 ]
  lines=1
  [ -z "$2" ] || { grep -qx "$2" "$work/err"; lines=2; }
  [ "$(wc -l < "$work/err" | tr -d ' ')" = "$lines" ]
  ! grep -q "$token" "$work/out" "$work/err" "$work/openwiz.log"
}
(OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity "$token installation" '')
[ "$(cat "$work/openwiz.log")" = 'github token --repository synthetic-owner/synthetic-repo --read' ]
echo 'ok   with the key secret the check reads GitHub with a read-only App token and prints none (#2549)'
(LAUNCH_FLEET_GITHUB_AUTH=installation identity 'none account' "$fallback")
[ ! -s "$work/openwiz.log" ]
(OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj FAKE_OPENWIZ_FAIL=1 identity 'none account' \
  "loop.sh: the App token mint failed; GitHub as today's account")
rm "$work/bin/openwiz"
# The fake gh stays first; no installed openwiz is in these system folders.
(PATH="$work/bin:/usr/bin:/bin" OPENWIZ_GITHUB_APP_KEY=c3ludGhldGlj identity 'none account' \
  "loop.sh: no openwiz to mint the App token; GitHub as today's account")
echo "ok   without the secret, openwiz or a token, the check runs as today's account and says so (#2549)"

# Failed refreshes and first clones must not emit work or leave runtime files.
mv "$work/remote" "$work/offline"
status=0
sh "$work/loop.sh" > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q "can't fetch" "$work/err"
[ -z "$(ls -A "$work/runtime")" ]
LAUNCH_FLEET_HOME="$work/new-home" FAKE_GH_FAIL=repo_clone sh "$work/loop.sh" \
  > "$work/out" 2> "$work/err" && exit 1 || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q "can't clone" "$work/err"
[ -z "$(ls -A "$work/runtime")" ]
echo 'ok   clone and refresh failures exit 2 without due lines or temporary files'

# Generation must fail before emitting a partial upload when a helper is absent.
mkdir -p "$work/incomplete/skills/launch-fleet/scripts" "$work/incomplete/skills/to-tickets"
cp "$HERE/loop.sh" "$work/incomplete/skills/launch-fleet/scripts/loop.sh"
status=0
sh "$work/incomplete/skills/launch-fleet/scripts/loop.sh" --bundle synthetic-owner/synthetic-repo \
  > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
echo 'ok   an incomplete install cannot generate a partial loop'

cp "$HERE/fleet.sh" "$work/incomplete/skills/launch-fleet/scripts/fleet.sh"
cp "$FIX/revision.sh" "$work/incomplete/skills/to-tickets/revision.sh"
printf '\nOPENWIZ_BUNDLED_HELPER_EOF\n' >> "$work/incomplete/skills/launch-fleet/scripts/fleet.sh"
status=0
sh "$work/incomplete/skills/launch-fleet/scripts/loop.sh" --bundle synthetic-owner/synthetic-repo \
  > "$work/out" 2> "$work/err" || status=$?
[ "$status" = 2 ] && [ ! -s "$work/out" ]
grep -q 'heredoc delimiter' "$work/err"
echo 'ok   a helper cannot terminate its quoted bundle early'

for repo in '../consumer' 'owner/../consumer' 'owner/consumer;echo'; do
  status=0
  sh "$HERE/loop.sh" --bundle "$repo" > "$work/out" 2> "$work/err" || status=$?
  [ "$status" = 2 ] && [ ! -s "$work/out" ]
  grep -q 'GH_REPO must be owner/name' "$work/err"
done
echo 'ok   unsafe repository names cannot generate a loop'

