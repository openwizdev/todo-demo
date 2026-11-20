#!/bin/sh
# huntr hunter provisioning (#1685), run by each hunter in its own sandbox from its brief:
#   sh provision.sh <owner/repo> <pinned-commit> <absolute-dir> <slice>
# It uses this sandbox's own GitHub login (never another's), clones the project into <dir> if no
# checkout is there, fetches the pinned commit itself and checks it out. A copy with any staged,
# unstaged or untracked change is refused, never cleaned: its edits stay. It prints exactly one line:
#   huntr hunter: ready <slice> at <pin>                  (exit 0)
#   huntr hunter: BLOCKED <slice> at <step>: <reason>     (exit 3)
# Bad arguments exit 2 and run nothing. Command output is discarded: no token reaches the line.
set -u
[ $# -eq 4 ] || exit 2
repo=$1 pin=$2 dir=$3 slice=$4
printf '%s\n' "$repo" | grep -Eqx '[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+' || exit 2
printf '%s\n' "$pin" | grep -Eqx '[0-9a-f]{40}' || exit 2
printf '%s\n' "$slice" | grep -Eqx '[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*' || exit 2
case $dir in /*) ;; *) exit 2 ;; esac
blocked() { printf 'huntr hunter: BLOCKED %s at %s: %s\n' "$slice" "$1" "$2"; exit 3; }
gh auth status >/dev/null 2>&1 || blocked auth 'gh is not signed in in this sandbox'
gh auth setup-git >/dev/null 2>&1 || blocked auth 'gh could not set up Git credentials'
if [ ! -d "$dir/.git" ]; then
  if [ -e "$dir" ] && [ -n "$(ls -A "$dir" 2>/dev/null)" ]; then blocked source "$dir is not a Git checkout"; fi
  gh repo clone "$repo" "$dir" -- --quiet --filter=blob:none >/dev/null 2>&1 || blocked clone "could not clone $repo"
fi
# The source must be exactly the pin: no change of anyone's, before or after the checkout.
clean() {
  changes=$(git -C "$dir" status --porcelain --untracked-files=all 2>/dev/null) || blocked source "could not read $dir"
  [ -z "$changes" ] || blocked source "$dir has uncommitted changes"
}
clean
git -C "$dir" fetch --quiet --no-tags origin "$pin" >/dev/null 2>&1 || blocked fetch "could not fetch $pin from origin"
git -C "$dir" checkout --quiet --detach "$pin" >/dev/null 2>&1 || blocked checkout "could not check out $pin"
[ "$(git -C "$dir" rev-parse HEAD 2>/dev/null)" = "$pin" ] || blocked source-pin "HEAD is not $pin"
clean
printf 'huntr hunter: ready %s at %s\n' "$slice" "$pin"
