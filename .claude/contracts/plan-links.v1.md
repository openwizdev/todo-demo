# OpenWiz plan links contract, version 1 (`openwiz.plan-links.v1`)

Every link in a plan graph says why it exists. This contract fixes the words and shapes the rest of spec #1313 (Unchain the factory graph) builds against: the link reason in a ticket body, the link checker's interface, the graph read, the board's measures and its history row. Its schema is [plan-links.v1.schema.json](plan-links.v1.schema.json); its fixtures, each with its expected checker report and board numbers, are in [`skills/plan-graph/test/links/`](../skills/plan-graph/test/links/README.md).

**Contract only** (#1315, U1). U4 (#1318) builds the checker, U5 (#1321) the board, U2 (#1317) the plan-graph rules and U6 (#1319) the fed-factory rule. The fixtures prove shapes and expected answers, never live behaviour.

Authority: spec #1313 and its confirmed grill, `docs/grills/2026-11-05-unchain-the-factory.md` (UF1 (a), UF2 (c), UF4 (c), UF7 (a)).

## Words

| Word | Meaning here |
| --- | --- |
| **Link** | One native "blocked by" relation on GitHub: an open ticket and one of its native blockers, open or closed. GitHub's native links still decide when a ticket can start; a reason only explains one. |
| **Native blocker** | A ticket's blocker as GitHub's own "blocked by" list gives it, whatever spec or milestone it belongs to. |
| **Reason line** | One line of a ticket's `## Links` section, naming one native blocker and why the ticket waits for it. |
| **Real link** | A link whose reason line names the behaviour the later ticket needs from the earlier one. Real links stay, as long as they need to be. |
| **File link** | A link whose reason line says the two tickets only share files, and names them. The goal is zero. |
| **Unlabelled link** | A link with no valid reason line: its ticket has no `## Links` section (a body written before this rule), or its section has no line for it, or its line is refused. |
| **Open approved ticket** | An open issue with at least one of the labels `ready-for-agent`, `ready-for-human`, `held` or `needs-info`: the tickets the plan board draws today. |
| **Can start** | An open approved ticket with no open native blocker. |
| **Startable share** | The tickets that can start, of the open approved tickets. |
| **Builders running** | The open approved tickets with a recorded start or an open pull request, as `render.py` counts "building". |
| **Ready stock** | The open approved tickets that can start, have no builder running, aren't held (`held`) and aren't waiting on Jake (`needs-info` or `ready-for-human`): `render.py`'s "ready". |
| **Fed ratio** | The ready stock against the builders running. The factory is fed while the ready stock is at least twice the builders running. |

## The link reason

A ticket body gives each native blocker its reason in a `## Links` section, after Owned paths (and its **Relies on** line). One line per native blocker:

```md
## Links

- #<n> real: <the behaviour needed, in words>
- #<n> file: <the shared files, in backticks>
```

or, when the ticket has no blocker, exactly:

```md
## Links

none
```

This spec's own tickets use the form, and it accepts their lines unchanged:

```md
## Links

- #1315 real: the link-reason line, the checker's command and exit codes, and the measures' words, as the plan links contract fixes them
```

```md
## Links

- #1315 real: the checker's interface and the fixtures with their expected reports, which its tests run on
```

```md
## Links

- #1315 real: the definitions of the ready stock and the builders running that the rule counts by
```

```md
## Links

- #1318 real: the checker's JSON report on a graph read, which gives the board its file-link and unlabelled counts
```

```md
## Links

- #1318 real: the checker's pass and report on the re-cut graph, which is this ticket's proof and gates the request to Jake
```

and the spec's own example of a file line:

```md
## Links

- #1270 real: the open development contract's form for a public approval
- #1262 file: `.github/workflows/ci.yml`
```

### Reading a section

1. **Lines.** CRLF reads as LF. Trailing spaces and tabs are dropped from each line.
2. **The heading** is a line that is exactly `## Links`. A heading inside a fenced code block, or inside or on the line of an HTML comment, is not one, as `check-relies.sh` reads its declaration: a fence opens on a line whose start, after leading whitespace, is three or more backticks or tildes, and closes on a line of only that character, at least as many, and trailing whitespace; a comment runs from a line containing `<!--` to a line containing `-->`, both lines included. Another heading level, or other words on the line, is not one either.
3. **The section** is the lines after its heading, up to the next ATX heading (a line starting with one to six `#` and then a space, or only `#`s) or the end of the body. Fences and comments play no part inside the section: every line counts, so a fence or comment line there is malformed (rule 5). Blank lines in it are skipped.
4. **Each other line** must be either `none` or a link line, matched whole: `- #<n> real:<reason>` or `- #<n> file:<reason>`, where `<n>` is a positive issue number without a leading zero, `- ` starts the line (a line with leading whitespace is not a link line), the kind is lowercase, and `<reason>` is the rest of the line with surrounding spaces and tabs dropped (it may be empty).
5. **Malformed,** in this order, first match only: more than one `## Links` section; a section with no lines; a line that is neither a link line nor `none`; `none` beside any other line (another `none` included). A malformed section labels nothing: every native blocker of its ticket is unlabelled, and the ticket gets one malformed refusal, never a refusal per blocker.
6. **A real line names behaviour:** at least three words outside backticks. Replace every backticked span (a pair of backticks and what's between them, paired from the left) with a space; split the rest on whitespace; strip each piece of leading and trailing `()[]{}"',.;:!?`; a word is a piece matching `^[A-Za-z]+(['-][A-Za-z]+)*'?$` (so `checker's`, `measures'` and `file-link` are words, and a path such as `contracts/plan-links.v1.md` is not).
7. **A file line names a file:** at least one backticked span holding a repository-relative path: segments of `A-Z a-z 0-9 _ . -`, joined by single `/`, with an optional trailing `/` for a folder, no leading `/`, and no `.` or `..` segment. Its files are the contents of those path spans, exactly as written, in order, each once. Other spans and words may sit beside them and are not files. A path is checked by form only, never on disk: a link may name a planned file.

### Which links each line labels

For each open ticket in the graph read, with native blockers `B`:

| Case | Refusal | The links |
| --- | --- | --- |
| No section | `no_reason` for each blocker in `B` | Every one unlabelled. A ticket with no blocker and no section has no link and no refusal |
| Malformed section | One `malformed` | Every one unlabelled |
| `none` | `no_reason` for each blocker in `B` | Every one unlabelled |
| A line names a number not in `B` | `not_a_blocker`, once per number | Not a link |
| No line names a blocker | `no_reason` | Unlabelled |
| Two or more lines name one blocker | `duplicate` | Unlabelled |
| Its one line is real, with fewer than three words | `real_without_behaviour` | Unlabelled |
| Its one line is file, with no file | `file_without_file` | Unlabelled |
| Its one line is real, with behaviour | none | Real |
| Its one line is file, with a file | none | File |

Closed tickets are never checked or counted: they wait for nothing. Every native blocker of an open ticket needs a line, open or closed, inside the spec or outside it: external blockers need reasons too.

## The link checker

`sh skills/plan-graph/check-links.sh`, beside `check-relies.sh`, in its style: `sh` and `jq`, writes nothing.

```text
sh skills/plan-graph/check-links.sh [--json] <spec>       # reads spec <spec>'s tickets through gh
sh skills/plan-graph/check-links.sh [--json] --graph -    # reads one graph read on standard input; no network call
```

- **`<spec>`:** the spec's sub-issues, open and closed, each with its native blockers and their states, read through `gh`, every read checked and every page counted. It first reads the `Record authors` row of `docs/agents/fleet.md`'s `## GitHub identity` table from the default branch, through `gh`; a failed read, or no row, an empty row or a malformed login, exits 2. It builds the same graph read as below (source `{ "kind": "spec", "spec": <spec> }`) and makes no other call.
- **`--graph -`:** one graph read, as below, on standard input.
- **`--json`:** the JSON report on standard output instead of the text report.

| Exit | Means | Standard output | Standard error |
| --- | --- | --- | --- |
| 0 | Pass: no refusal | The report | Nothing |
| 1 | Refused | The report | One line per refusal |
| 2 | Bad arguments, or a failed, partial or invalid read (not JSON; not valid against the schema as a `graph` record; a ticket listed twice; a blocker listed twice for one ticket) | Nothing | Why, in one line |

A read that fails passes nothing.

### The text report

```text
<pass|refused> <spec #N|board>: tickets <t>, links <l>, real <r>, file <f>, unlabelled <u>, refusals <x>
file link: #<ticket> blocked by #<blocker>: <file>, <file>
```

One summary line, then one `file link:` line for each file link, ordered by ticket then blocker (ascending numbers, as every order here), its files joined by `, `. The counts are over open tickets: `tickets` is how many were checked.

### Refusals

Standard error, one line each, in the JSON report's order: `Links: #<ticket>: <message>`.

| Code | Message |
| --- | --- |
| `no_reason` | `#<blocker> has no reason line` |
| `not_a_blocker` | `#<n> is not a native blocker` |
| `duplicate` | `#<blocker> has more than one line` |
| `real_without_behaviour` | `the real line for #<blocker> names no behaviour` |
| `file_without_file` | `the file line for #<blocker> names no file in backticks` |
| `malformed` | `malformed section: <detail>`, the detail one of `more than one ## Links section`, `no lines`, `a line is not a link line or none`, `none must be the only line` |

A message never quotes the body, so no ticket text reaches standard error.

### The JSON report

```text
report  { schema, kind: "report", repo, source, result: pass | refused, counts, links, refusals }
source  { kind: "spec", spec } | { kind: "board" }
counts  { tickets, links, real, file, unlabelled, refusals }
link    { ticket, blocker, blocker_state: OPEN | CLOSED, kind: real | file | unlabelled, files }
refusal { ticket, number, code, message }
```

- `repo` and `source` are the graph read's.
- `links`: one per link of an open ticket, ordered by ticket then blocker. `files` is the file line's files for a file link, and `[]` otherwise.
- `refusals`: ordered by ticket, then `number`. `number` is the blocker or the named number, and `null` for `malformed`. `message` is the text after `Links: #<ticket>: ` on standard error.
- `result` is `refused` exactly when `refusals` is not empty. `counts.links` is `real + file + unlabelled`.

The board reads the report, not the bodies, so there is one parser.

## The graph read

The JSON the checker reads on standard input and the board fetches once an hour.

```text
graph   { schema, kind: "graph", repo, read_at, source, tickets }
ticket  { number, title, state: OPEN | CLOSED, labels, milestone, parent,
          blocked_by: [{ number, state: OPEN | CLOSED }], body,
          start_recorded, pull_requests }
```

- `repo` is `owner/name`, the one repository setting; `read_at` is the read's UTC time, `YYYY-MM-DDTHH:MM:SSZ`.
- `source` is `{ "kind": "spec", "spec": <n> }`, for spec `<n>`'s sub-issues, open and closed; or `{ "kind": "board" }`, for the open approved tickets, as `render.py` reads them.
- `labels` are label names; `milestone` is the milestone's title or `null`; `parent` is the parent issue's number or `null`.
- `blocked_by` is every native blocker with its state, in any order.
- `body` is the issue body, unchanged.
- `start_recorded` is the start record the board already reads: true when one of the ticket's last 15 comments starts with `launch-fleet: start` and was written by a record author (a login in that `Record authors` row, compared case-insensitively); a comment with no author never counts.
- `pull_requests` are the open pull requests whose titles start with `#<number>` (the ticket's number, then a non-digit or the end), as `render.py` matches them.

Each ticket appears once, each blocker once per ticket. Every object has exactly its listed keys.

## The board's measures

Over one graph read and the checker's report on it:

| Measure | Counts |
| --- | --- |
| `open_approved` | Open approved tickets |
| `can_start` | Open approved tickets that can start |
| `startable_percent` | `can_start` of `open_approved`, as a whole percent rounded half up; `null` when `open_approved` is 0 |
| `file_links` | The report's file links whose ticket is open approved |
| `unlabelled_links` | The report's unlabelled links whose ticket is open approved |
| `ready_stock` | The ready stock |
| `builders_running` | The builders running |
| `fed_ratio` | `ready_stock / builders_running`, rounded half up to one decimal, a JSON number (written with its decimal, as `3.0`; a reader compares numbers, so `3` reads the same); `null` when `builders_running` is 0 |
| `low_stock` | The flag: `ready_stock < 2 × builders_running` |

```text
measures { schema, kind: "measures", open_approved, can_start, startable_percent,
           file_links, unlabelled_links, ready_stock, builders_running, fed_ratio, low_stock }
```

A building ticket counts as a builder running even when an open blocker would stop it starting.

## The history row

The board appends one row per run to its history, one JSON object per line.

```text
history { schema, kind: "history", sample: "baseline" | "run", at, day, repo,
          open_approved, can_start, startable_percent,
          file_links, unlabelled_links, ready_stock, builders_running, fed_ratio, low_stock }
```

- A `run` row is that run's measures, with `at` the graph read's `read_at` and `repo` its `repo`. All its numbers are measured: only `startable_percent` and `fed_ratio` may be `null`, as in the measures.
- `day` is `at`'s date in PST, a fixed UTC−8 all year, so every day is 24 hours: 2026-11-06T07:59:00Z is day 2026-11-05, and 2026-11-06T08:00:00Z day 2026-11-06.
- **The daily row** is a day's last sample: the row with that `day` and the latest `at` (on a tie, the later line). A day with no sample has no row.
- **The baseline row** is the first line: an explicitly synthetic example,
  not a factory measurement. In this invented cohort, 20 of 80 can start
  (25%); the other measures are unknown (`null`).

```json
{"schema":"openwiz.plan-links.v1","kind":"history","sample":"baseline","at":"2026-11-05T23:50:00Z","day":"2026-11-05","repo":"synthetic-owner/synthetic-repo","open_approved":80,"can_start":20,"startable_percent":25,"file_links":null,"unlabelled_links":null,"ready_stock":null,"builders_running":null,"fed_ratio":null,"low_stock":null}
```

## Fixtures

[`skills/plan-graph/test/links/`](../skills/plan-graph/test/links/README.md), all synthetic but this spec's own lines. Each case folder holds:

| File | What |
| --- | --- |
| `graph.json` | The graph read |
| `report.json` | The checker's expected JSON report |
| `report.txt` | The checker's expected text report (standard output) |
| `stderr.txt` | The checker's expected standard error: empty on a pass |
| `board.json` | The expected board measures |

`history/` holds a history (`history.jsonl`) and its expected daily rows (`daily.jsonl`). `tests/checks/plan_links.rs` validates every fixture against the schema, checks that each report agrees with its graph read, and recomputes the board numbers by the definitions above.
