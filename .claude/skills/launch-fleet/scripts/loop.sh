#!/bin/sh
# The script of a project's launch-fleet loop (ClosedWiz#102). A loop's script
# runs in the loop's own sandbox, which lasts between runs. --bundle OWNER/REPO
# prints an uploadable script containing this runner and the installed fleet
# and revision helpers. It refreshes the consumer clone but runs those pinned
# helpers, so the consumer needs no skills/ and no plugin cache at runtime.
# Without --bundle, it runs the helpers installed beside it, never the clone's.
# A spec's fleet thread's loop (ClosedWiz#192) also sets FLEET_SPEC (or passes
# the spec's number after --bundle OWNER/REPO): then it runs that spec's check
# alone (`fleet.sh spec <FLEET_SPEC>`).
# Exit as the check exits; 2 when the clone can't be made or updated.
die() { printf 'loop.sh: %s\n' "$*" >&2; exit 2; }
repository() {
  case $1 in
    */*/* | /* | */ | *[!A-Za-z0-9._/-]* | ./* | ../* | */. | */..) return 1 ;;
    ?*/?*) return 0 ;;
    *) return 1 ;;
  esac
}

spec_number() { case $1 in '' | 0* | *[!0-9]* | ??????????*) return 1 ;; esac; }

if [ "${1:-}" = --bundle ]; then
  [ $# = 2 ] || [ $# = 3 ] || die 'usage: loop.sh --bundle owner/name [spec]'
  repository "$2" || die 'GH_REPO must be owner/name'
  [ $# = 2 ] || spec_number "$3" || die "FLEET_SPEC must be a spec's number"
  source=$(cd -P "$(dirname "$0")/../.." && pwd) || die "can't find the installed skills"
  files='launch-fleet/scripts/loop.sh launch-fleet/scripts/fleet.sh launch-fleet/scripts/records.py to-tickets/revision.sh to-tickets/check-links.sh launch-fleet/scripts/carried/alarm.py'
  for file in $files; do
    [ -r "$source/$file" ] || die "can't read installed $file"
    # The quoted heredoc must preserve every byte, without interpreting shell
    # substitutions in a helper. Refuse a delimiter collision before emitting.
    if grep -qx 'OPENWIZ_BUNDLED_HELPER_EOF' "$source/$file"; then die "heredoc delimiter in $file"; fi
  done
  bundle=$(mktemp) || die "can't stage the bundled loop"
  trap 'rm -f "$bundle"' EXIT
  trap 'exit 2' HUP INT TERM
  {
    printf '#!/bin/sh\nGH_REPO=%s\nexport GH_REPO\n' "$2"
    [ $# = 2 ] || printf 'FLEET_SPEC=%s\nexport FLEET_SPEC\n' "$3"
    cat <<'OPENWIZ_BUNDLE_BOOTSTRAP'
runtime=$(mktemp -d) || { echo "loop.sh: can't unpack the bundled loop" >&2; exit 2; }
trap 'rm -rf "$runtime"' EXIT
trap 'exit 2' HUP INT TERM
mkdir -p "$runtime/skills/launch-fleet/scripts/carried" "$runtime/skills/to-tickets" || exit 2
OPENWIZ_BUNDLE_BOOTSTRAP
    for file in $files; do
      printf 'cat > "$runtime/skills/%s" <<%s || exit 2\n' "$file" "'OPENWIZ_BUNDLED_HELPER_EOF'"
      cat "$source/$file" || exit 2
      printf '\nOPENWIZ_BUNDLED_HELPER_EOF\n'
    done
    printf 'LAUNCH_FLEET_RUNTIME="$runtime/skills" sh "$runtime/skills/launch-fleet/scripts/loop.sh"\n'
  } > "$bundle" || die "can't bundle the installed helpers"
  cat "$bundle" || die "can't print the bundled loop"
  exit 0
fi
[ $# = 0 ] || die 'usage: loop.sh [--bundle owner/name [spec]]'
GH_REPO=${GH_REPO:-}
repository "$GH_REPO" || die "GH_REPO must be owner/name"
FLEET_SPEC=${FLEET_SPEC:-}
[ -z "$FLEET_SPEC" ] || spec_number "$FLEET_SPEC" || die "FLEET_SPEC must be a spec's number"
export GH_REPO
# The check reads GitHub as the OpenWiz App (GI7, #2549; the identity contract
# `openwiz.github-identity.v1`): with the loop's OPENWIZ_GITHUB_APP_KEY secret,
# `openwiz github token --read` mints a read-only installation token for gh
# (GH_TOKEN) and git (its credential helper reads GH_TOKEN from the
# environment). No token is stored, printed or passed as an argument. Without
# the secret, or when the mint fails, the check runs on today's account and
# says so on stderr, so it never stops for it.
# The check is told which identity reads (LAUNCH_FLEET_GITHUB_AUTH), so its
# unchanged probe asks what that identity can read; never an inherited value.
app=
unset LAUNCH_FLEET_GITHUB_AUTH
if [ -z "${OPENWIZ_GITHUB_APP_KEY:-}" ]; then
  echo "loop.sh: no OPENWIZ_GITHUB_APP_KEY secret; GitHub as today's account" >&2
elif ! command -v openwiz > /dev/null; then
  echo "loop.sh: no openwiz to mint the App token; GitHub as today's account" >&2
elif app=$(openwiz github token --repository "$GH_REPO" --read 2> /dev/null < /dev/null) && [ -n "$app" ]; then
  GH_TOKEN=$app LAUNCH_FLEET_GITHUB_AUTH=installation
  export GH_TOKEN LAUNCH_FLEET_GITHUB_AUTH
  app=1
else
  app=
  echo "loop.sh: the App token mint failed; GitHub as today's account" >&2
fi
# Read GH_TOKEN from the environment only when the App token is in use.
git_() {
  if [ -n "$app" ]; then
    # shellcheck disable=SC2016 # the helper expands GH_TOKEN when git runs it
    git -c credential.helper= -c 'credential.helper=!f() { [ "$1" = get ] && printf "username=x-access-token\npassword=%s\n" "$GH_TOKEN"; }; f' "$@"
  else
    git "$@"
  fi
}
# Guard with the invoking installation (or pinned runtime), before touching
# the consumer checkout. Missing observations/state refuse; no ungated fallback.
# Both actions use the same repository-scoped durable state as merge admission.
guard_scripts=${LAUNCH_FLEET_RUNTIME:-$(cd -P "$(dirname "$0")/../.." && pwd)}
overload() {
  sh "$guard_scripts/launch-fleet/scripts/fleet.sh" overload "$1" > /dev/null \
    || die "overload refuses $1"
}
overload automatic-refresh
dir=${LAUNCH_FLEET_HOME:-$HOME/launch-fleet}/$GH_REPO
if [ -d "$dir/.git" ]; then
  git_ -C "$dir" fetch -q --depth 1 origin HEAD || die "can't fetch $GH_REPO"
  git -C "$dir" checkout -q --detach FETCH_HEAD || die "can't update the clone in $dir"
else
  mkdir -p "$(dirname "$dir")" || die "can't make $(dirname "$dir")"
  gh repo clone "$GH_REPO" "$dir" -- -q --depth 1 || die "can't clone $GH_REPO"
fi
# Always the invoking installation's (or the bundle's pinned) helpers: the
# consumer clone's skills/ is data to read, never code to run.
scripts=$guard_scripts
LAUNCH_FLEET_REVISION=$scripts/to-tickets/revision.sh
LAUNCH_FLEET_LINKS=$scripts/to-tickets/check-links.sh
export LAUNCH_FLEET_REVISION LAUNCH_FLEET_LINKS
# Refresh may have overlapped another observation. Recheck before the poll.
overload nonessential-poll
if [ -n "$FLEET_SPEC" ]; then exec sh "$scripts/launch-fleet/scripts/fleet.sh" spec "$FLEET_SPEC"; fi
exec sh "$scripts/launch-fleet/scripts/fleet.sh"
