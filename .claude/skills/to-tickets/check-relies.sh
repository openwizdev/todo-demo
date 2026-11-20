#!/bin/sh
# Read-only ticket-body check on stdin. Uses the fleet's existing sh/jq tools.
# Exit 0: valid; 1: refused body/path; 2: bad arguments. No writes or API calls.
set -f
LC_ALL=C
export LC_ALL
fail() { printf 'Relies on: %s\n' "$*" >&2; exit 1; }
usage() { printf 'usage: sh check-relies.sh [--root DIR] [--planned PATH]... < ticket.md\n' >&2; exit 2; }
lexical_path() {
  case "$1" in
    '' | /* | */ | *//* | *[!A-Za-z0-9_./-]*) fail 'use full repository-relative file paths, without patterns' ;;
  esac
  case "/$1/" in */./* | */../*) fail 'paths must not contain . or .. components' ;; esac
}
root=.
planned=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --root) [ "$#" -ge 2 ] || usage; root=$2; shift 2 ;;
    --planned)
      [ "$#" -ge 2 ] || usage
      lexical_path "$2"
      planned="$planned
$2"
      shift 2 ;;
    -h | --help) printf 'Check one inline Relies on declaration; sh and jq only.\n'; exit 0 ;;
    *) usage ;;
  esac
done
case "$root" in /*) ;; *) root="$(pwd -P)/$root" ;; esac
root=$(CDPATH='' cd -P -- "$root" 2>/dev/null && pwd -P) || fail 'repository root must be a directory'

# Output is an internal, whitespace-delimited protocol: ok plus ASCII paths,
# or error plus a reason. No arbitrary input is emitted before validation.
parsed=$(jq -rRs '
  def refuse($why): error($why);
  try (
    gsub("\r\n"; "\n") as $body
    | if ($body | contains("\r")) then refuse("use LF or CRLF lines, never a bare CR") else . end
    | ($body | split("\n")) as $lines
    | reduce range(0; $lines | length) as $i (
        {fence: null, comment: false, declarations: []};
        $lines[$i] as $line | ($line | sub("^\\s+"; "")) as $trim
        | if ($line | test("^\\s*(?:#{1,6}\\s+|\\**)Relies on\\b")) then
            if (.comment or .fence != null or ($line | contains("<!--"))) then
              refuse("the declaration must be visible, outside code and comments")
            else .declarations += [$i] end
          else . end
        | if .fence != null then
            .fence as $open
            | if ($trim | test("^" + $open[0:1] + "{" + ($open | length | tostring) + ",}\\s*$")) then
                .fence = null
              else . end
          else .fence = ([$trim | match("^(`{3,}|~{3,})") | .string][0] // null) end
        | if ($line | contains("<!--")) then .comment = true else . end
        | if ($line | contains("-->")) then .comment = false else . end
      )
    | if (.declarations | length) != 1 then refuse("use exactly one **Relies on:** line") else . end
    | .declarations[0] as $i
    | if ($lines[$i] | test("^\\*\\*Relies on:\\*\\* .+$")) then .
      else refuse("put the complete declaration on one **Relies on:** line") end
    | ($lines[$i] | capture("^\\*\\*Relies on:\\*\\* (?<value>.+)$") | .value) as $value
    | reduce $lines[$i + 1:][] as $line (
        {ended: false};
        if .ended then .
        elif ($line | test("^(#{1,6} |\\*\\*[A-Za-z][^*]*:\\*\\*)")) then .ended = true
        elif ($line | test("\\S")) then refuse("the declaration must occupy one line, with no continuation")
        else . end
      )
    | if $value == "nothing" then ["ok"]
      elif ($value | test("^`[^`]+`(, `[^`]+`)*$")) then
        [$value | scan("`([^`]+)`") | .[0]] as $paths
        | if all($paths[]; test("^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")) then ["ok"] + $paths
          else refuse("use full repository-relative file paths, without patterns") end
      else refuse("use comma-separated backticked paths or exactly nothing; no prose") end
    | .[]
  ) catch ("error\n" + .)
' 2>/dev/null) || fail 'cannot parse the declaration (jq is required)'

check_file() {
  lexical_path "$1"
  rest=$1
  path=$root
  while :; do
    case "$rest" in
      */*) part=${rest%%/*}; rest=${rest#*/}; last=false ;;
      *) part=$rest; last=true ;;
    esac
    path=$path/$part
    [ ! -L "$path" ] || fail 'name the contract file itself, not a symlink'
    if [ "$last" = false ] && [ -e "$path" ] && [ ! -d "$path" ]; then
      fail 'a file cannot be a parent directory of a planned contract'
    fi
    [ "$last" = false ] || break
  done
  if [ -e "$path" ]; then
    [ -f "$path" ] || fail 'name individual contract files, not folders'
  elif [ "$2" != planned ]; then
    case "
$planned
" in
      *"
$1
"*) ;;
      *) fail 'file does not exist at its full path; use --planned only for a blocked contract' ;;
    esac
  fi
}
# Planned values were lexically checked before storing them; paths contain no
# whitespace. Check metadata after consuming stdin so early refusal cannot race
# the callers writing their ticket body into the pipe.
for file in $planned; do check_file "$file" planned; done
set -- $parsed
[ "$#" -gt 0 ] || fail 'the parser returned no verdict'
case "$1" in
  error) shift; fail "$*" ;;
  ok) shift ;;
  *) fail 'the parser returned an unknown verdict' ;;
esac
for file do check_file "$file" declared; done
exit 0
