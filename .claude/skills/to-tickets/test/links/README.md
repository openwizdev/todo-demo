# Plan links fixtures

The fixtures of the [plan links contract](../../../../contracts/plan-links.v1.md) (#1315). Each case folder holds a graph read (`graph.json`) with the link checker's expected JSON report (`report.json`), text report (`report.txt`) and standard error (`stderr.txt`), and the board's expected measures (`board.json`). Every expected value was written by hand from the contract, never computed by the code under test. All values are synthetic, except the `## Links` lines of `this-spec`, which are spec #1313's own, unchanged.

| Case | Shows | Checker |
| --- | --- | --- |
| `clean-wide` | A contract-first ticket and four tickets on it, all real; a fenced example heading that is not a section | pass |
| `real-and-file` | Real and file links; the file links reported, ordered, files joined | pass |
| `refuse-no-reason` | A section missing a line (for an external blocker), a body with no section, `none` with a blocker | `no_reason` |
| `refuse-not-a-blocker` | A line naming a ticket that is not a native blocker | `not_a_blocker` |
| `refuse-duplicate` | Two lines for one blocker | `duplicate` |
| `refuse-real-without-behaviour` | A real line that is only a path, two words, empty, or a bare path | `real_without_behaviour` |
| `refuse-file-without-file` | A file line with no backticks, or a path leaving the repository | `file_without_file` |
| `refuse-malformed` | Each malformed detail, including on a ticket with no blocker | `malformed` |
| `external-blockers` | Blockers outside the read, with their reasons | pass |
| `closed-blocker` | A closed blocker still needs its line and stops nothing; closed tickets are not checked | pass |
| `low-stock` | A board read: building, held, waiting on Jake, blocked and ready tickets; the low-stock flag | pass |
| `this-spec` | Spec #1313's own `## Links` lines | pass |
| `unapproved-proposal` | A proposal before approval: nothing open approved, no share, no ratio | pass |

`history/` holds a history, its baseline row first, and its expected daily rows across the PST day boundary.

The consumer project's own plan-links check, where its settings name one,
validates these fixtures against the carried schema and checks each expectation
against its graph read.
