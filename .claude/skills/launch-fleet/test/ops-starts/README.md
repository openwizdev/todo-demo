# OB5 starts: approved builders and initial green-head reviews

Run the owning synthetic proof:

```sh
python3 -I skills/launch-fleet/scripts/test-ops-starts.py
```

`../../scripts/ops-starts.py` is #1480's finite ops seam. The ops agent reads
GitHub and CloudRoom completely and supplies one fact set per candidate;
`plan()` checks it, then hands each eligible start to `records.py ops_pass`
(#1456), which goes through OB3's `effects.resume`. **Every start stays
disabled under OB-A1.** The effect callback is never called. A pass records
its intents, claims and results, then ends. It has no watcher, poll, sleep
or retry. `world.json`, `bench-miss.json` and `project/docs/agents/fleet.md`
(a consumer project's four start tables) are synthetic. Neither is an
observed endpoint.

| Input | Facts, all from complete reads |
| --- | --- |
| `pass` | Current `generation`, `owner` and `now` (ms) of this finite pass |
| `generations` | Every admitted generation claim for this repository/spec |
| `rule` | The current `dispatch` rule `{name, revision, comment}` |
| `builders[]` | `ticket`, `open`, `labels`, `approval`, `approved_ready` (its row in the current approval), `fingerprint_now`, `table_complete`, `blockers[{number, merged}]` and `blockers_complete`, `holds`, `gates`, `live_builders` (int; `null` is unknown), `start_claims`, `open_prs`, `admission` (`ok`, or the capacity/permission/overload refusal), `complete`, `evidence {evidence_class, source}` |
| `reviews[]` | `pr`, `ticket`, `open`, `draft`, `labels`, `approval`, `fingerprint_now`, `table_complete`, `head` and re-read `head_now`, `branch`, `ci {head, state, required_complete}`, `builder {record_branch, providers}` (the checked start record's branch and the provider read from each builder thread on it), `spans[{head, given_up}]` (every reviewer ever started on the PR), `closes` (tickets the PR closes), `base`, `default_branch`, `subject` (the full first line of the head commit's `message`, as #2736's review gate reads it; never GraphQL `messageHeadline`, which GitHub cuts to 70 characters with an ellipsis and can drop `green`), `verdict` (the latest `VERDICT:` line, or `null`), `holds`, `gates`, `reviewer_available`, `admission`, `complete`, `evidence` |
| `history` | Every durable ops record (intent, admission, transport, ack, completion) for these tickets |

Rules the proof fixes:

- **Builder start:** open, approval current, approved ready, `ready-for-agent` with none of `needs-info`, `needs-triage`, `ready-for-human`, `wontfix`, `held`. No hold or gate. Every blocker a verified merge. No live or unknown builder, no unsettled start claim, no open PR, and admission `ok`. Settings come from `## Builder`, or `## Builder for small tickets` for `polish`/`huntr`/`proposal`.
- **Initial review:** open, not a draft, approval current, not held. The PR closes exactly its ticket, targets the default branch, has `green` as a word in its head subject and has no verdict (fleet-tick's `first_review`/`fresh_review`). The head is unchanged on re-read and required CI is green at exactly that head. Either no reviewer was ever started, or every one was given up (a fresh review, with a new assignment). A retained reviewer re-checks through OB6 (#1481), never a new start here. The start record's branch is the head branch, and the family is exactly one of `claude-code`/`codex`. The selected table is the other family and its reviewer is available. The settings read itself refuses the pass unless the Claude-built table names `codex`, the GPT-built table names `claude-code` and both builder tables name one of the two. Anything else is refused with a reason (`look` material). The reviewer is never swapped. Sonnet small-review selection stays outside (#588).
- **One operation per start:** an intent with the same identity (all key fields but `sequence`) is reused, never re-recorded, while its bound evidence (`binding_digest`: that identity, the selected settings and the rule) and rule are unchanged. A changed binding after a settled outcome is a new operation with the next sequence; with an unsettled earlier intent it is refused. Intent ids derive from the operation key, so they stay unique across re-approvals. A candidate that is not an object, or whose facts fail the record schema, is refused alone. Duplicate project/spec copies get `duplicate`. Transport `accepted`/`uncertain`, an uncertain admission or completion, or an admitted claim with no later outcome is `reconcile/uncertain_outcome`. That applies under older approvals too, and nothing is retried. Refusals and uncertainty affect only their own ticket.
- **Missed goals (TL3 share):** `plan(..., bench=, limits=)` takes TL2's `stage-bench.v1` with `authority: none` and settings equal to `limits.py`'s current read. An open `builder_start`/`reviewer_start` miss is marked on the matching candidate's entry. It reuses that same intent and gives no start authority. A repeated overdue read records nothing more.
- **Report:** `report(bench)` gives each start stage's results (the denominators), its ended measured waits (a non-null end only; p50/p90 by nearest rank), minutes beyond the goal for measured waits only, and the excluded gated/stale/unknown counts. It also carries the original #1480 audit provenance (a ceiling, not recovered time).

CLI: `python3 -I skills/launch-fleet/scripts/ops-starts.py pass WORLD.json [--bench BENCH.json]`
prints one JSON entry per candidate, reading the settings from `docs/agents/fleet.md`
in the working directory, the consumer project's root. `report BENCH.json` prints the report.
Bad input exits 2 with nothing on stdout.

Not here: GitHub/CloudRoom collection, private routing, posting the records,
actual starts (OB8 and OB-A1), recheck/message delivery (#1481), CI/findings/
conflict helpers (#2338) and two-miss replacement (#2339).
