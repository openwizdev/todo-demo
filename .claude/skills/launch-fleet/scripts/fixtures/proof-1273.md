# #1273 / P4 fixture evidence

What this ticket's fixtures prove, in public form. It proves fixture behaviour only; no live fleet, publication or cut-over was run.

| Claim | Proof |
| --- | --- |
| Public writers carry no thread id | The skill's complete record table, huntr's captured approval bodies, and the load driver's scan on every new or edited fixture comment |
| Public starts, claims, checks, resumes and reviews remain routable | `test-records.py` through fake gh and CloudRoom; helper-check process tests; review-relay process tests |
| Re-checks preserve their original reviewer; give-up closes the span across commits | Public fixture tests with and without the private map; legacy quiet-review and re-check cases |
| Ambiguous, missing and conflicting identities never receive a message | Public title/branch, helper exclusion and private-map disagreement fixtures; relay ambiguity cases |
| The nine replacement forms match the contract exactly | `PublicRecords.test_record_table_uses_the_contract_public_forms_word_for_word` |
| Approvals point to a real private comment without copying its words | huntr gate captures the two-line public body and refuses missing, malformed or unreadable pointers |

## Where the run evidence is

The red-first runs, CI correction, helper reports, no-push checks and policy reads for this ticket are kept in the private record, not here. The red logs and tracebacks once kept beside this file were removed from the public package (WZ17). This file carries no run measurements, timestamps, paths or identifiers, and nothing in it is invented output standing in for a historical run. The `green-*.txt` files beside it are the saved passing outputs; the O10 consumer's saved output was removed too, because it named a private source commit, and `test-o10-triage.py` reproduces it.

## Behaviour the fixtures keep

- **Review spans.** A legacy re-check fixture puts its first review start before its re-check: review spans follow creation time, not edit time or input order.
- **CI reproduction.** `python3 skills/launch-fleet/scripts/fixtures/reproduce-1273-ci.py` selects the fleet cases a past CI failure touched, with their setup cases, straight from `test.sh`, without copying their assertions. The fixes it checked were fixture-only: `records.py` carried beside every executable copy of `fleet.sh`, literal totals that count the repository-privacy question, sorted archive expectations after the synthetic-id rename, and a review start before its told-again notification.
- **O10 template consumer.** `python3 skills/launch-fleet/scripts/fixtures/test-o10-triage.py` runs O10's producer and collector beside this fixture code, on fake gh and synthetic records. The fleet's prefix recognition must not admit a record with unfilled public-template placeholders (`<decision>`, `<pointer>`): the fixture fills a paraphrased synthetic decision and a contract-valid synthetic private-comment pointer. It checks the empty frontier without per-issue approval, exactly the approved subset, the first-line header, the immediately following pointer, the blank line and the AI marker; pasted approvals, absent, malformed, file or leading-zero pointers, missing markers and unrelated later markers stay triage work. It grants no approval, live authority or activation.
- **Fallback records (R1).** The builder-fallback paragraph prescribes only `launch-fleet: builder fallback due, branch <branch>` and `launch-fleet: start checked, branch <branch>`. Old and replacement identities and handover lineage stay private, and immutable start-claim mappings survive a give-up.
- **Closure archival (R2).** An archive failure, then a start claim edited to given-up, still lists that retired reviewer for ticket-closure archival, while re-checks reach only its replacement. A replacement edited to given-up keeps its own archive identity. `test-records.py` covers same-head and later-head replacements, discovery present and absent, two retired reviewers and older commit-only maps, through synthetic gh and CloudRoom.

Actual CloudRoom discovery shapes and live behaviour remain unverified.
