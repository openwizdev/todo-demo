#!/bin/sh
# The grill index (ClosedWiz#317): prints one Markdown table row for each grill
# file, from the file itself, so no grill's pull request edits a shared file.
#   sh skills/grill/scripts/index.sh [DIR]      # DIR: default docs/grills
# Reads DIR/*.md but README.md, in file-name order. Each file's line 1 is
# `# Grill: <topic> (<YYYY-MM-DD>)`, and its line 3, the status paragraph, has
# one `Status:` (`**open**.`, or `**parked**` or `**confirmed**` by <User>,
# <YYYY-MM-DD>) and a `Feeds` sentence. Fails closed: a file it can't read that
# way is named on stderr, with every other bad file, and nothing is printed.
# The default folder is the consumer project's own and optional: when it is
# absent, nothing is read and it says so on stderr, printing no table. A DIR
# that is named must exist.
# Exit 0: the table (or no default folder); 1: a bad file; 2: a folder or a
# file it can't read.
# Test: sh skills/grill/scripts/test.sh
set -u
LC_ALL=C
export LC_ALL
if [ $# = 0 ] && [ ! -e docs/grills ] && [ ! -L docs/grills ]; then
  echo "index.sh: this project has no docs/grills folder, so there is no grill index" >&2
  exit 0
fi
dir="${1:-docs/grills}"
[ -d "$dir" ] && [ -r "$dir" ] && [ -x "$dir" ] || { echo "index.sh: cannot read the folder $dir" >&2; exit 2; }

rows=''
bad=0
for f in "$dir"/*.md; do
  [ -e "$f" ] || continue # no grill at all
  [ "${f##*/}" != README.md ] || continue
  [ -f "$f" ] && [ -r "$f" ] || { echo "index.sh: cannot read $f" >&2; exit 2; }
  row="$(awk -v file="$f" -v base="${f##*/}" '
    function fail(why) { print "index.sh: " file ": " why > "/dev/stderr"; failed = 1; exit 1 }
    # s with a backslash before each character of chars, such as "|", which
    # would end the cell, or "[" and "]", which would open a link in a link.
    function esc(s, chars,   out, c, i) {
      out = ""
      for (i = 1; i <= length(s); i++) {
        c = substr(s, i, 1)
        out = out (index(chars, c) ? "\\" : "") c
      }
      return out
    }
    # d is a real day, YYYY-MM-DD.
    function real(d,   y, m, n) {
      if (d !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/) return 0
      y = substr(d, 1, 4) + 0; m = substr(d, 6, 2) + 0; n = substr(d, 9, 2) + 0
      if (m < 1 || m > 12 || n < 1) return 0
      if (m == 2) return n <= ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0 ? 29 : 28)
      return n <= ((m == 4 || m == 6 || m == 9 || m == 11) ? 30 : 31)
    }
    BEGIN {
      if (base !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]-[a-z0-9][a-z0-9.-]*\.md$/)
        fail("the file name is not `<YYYY-MM-DD>-<topic>.md` (lowercase letters, digits, dots and hyphens)")
    }
    NR == 1 {
      if ($0 !~ /^# Grill: .+ \([0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]\)$/ || !real(substr($0, length($0) - 10, 10)))
        fail("line 1 is not `# Grill: <topic> (<YYYY-MM-DD>)`")
      if (substr($0, length($0) - 10, 10) != substr(base, 1, 10)) fail("the file name\047s date is not the title\047s")
      topic = substr($0, 10, length($0) - 22)
    }
    NR == 3 {
      date = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]"
      i = index($0, "Status: ")
      rest = substr($0, i + 8)
      if (i > 0 && index(rest, "Status:") > 0) fail("line 3 has more than one `Status:`")
      if (i > 0 && rest ~ /^\*\*open\*\*\.( |$)/) status = "**open**"
      else if (i > 0 && match(rest, "^\\*\\*(parked|confirmed)\\*\\* by [^,]+, " date "([.,]| \\(|$)")) {
        word = substr(rest, 3, index(rest, "** by") - 3)
        # <User> holds no comma, so the date comes right after the first ", ".
        d = substr(rest, index(rest, ", ") + 2, 10)
        status = real(d) ? "**" word "** (" d ")" : ""
      }
      if (status == "") fail("line 3 has no `Status: **open**`, `**parked** by <User>, <YYYY-MM-DD>` or `**confirmed** by <User>, <YYYY-MM-DD>`")
      feeds = ""
      if ((j = index(" " $0, " Feeds")) > 0) {
        feeds = substr($0, j + 5)
        sub(/^:?[ ]+/, "", feeds)
        if ((k = index(feeds, ". ")) > 0) feeds = substr(feeds, 1, k - 1)
        sub(/[.]?[ ]*$/, "", feeds)
      }
      if (feeds == "") fail("line 3 has no `Feeds`")
      print "| [" esc(topic, "|[]") "](" base ") | " status " | " esc(feeds, "|") " |"
      exit 0
    }
    END {
      if (failed) exit 1
      if (NR < 3) fail("line 3 has no `Status: **open**`, `**parked** by <User>, <YYYY-MM-DD>` or `**confirmed** by <User>, <YYYY-MM-DD>`")
    }
  ' "$f")" || { bad=1; continue; }
  rows="$rows$row
"
done
[ "$bad" = 0 ] || exit 1
echo '| Grill | Status | Feeds |'
echo '| --- | --- | --- |'
printf '%s' "$rows"
