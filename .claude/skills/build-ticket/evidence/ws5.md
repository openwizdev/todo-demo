# WS5 build-ticket proof

## SK-B and SK-C

Same `build-ticket.regression` case and stop as WS1: an ordinary approved
ticket through scoped hand-back, with simulated effects and no grant or
review response. The skill runs `ticket.py` without reading its source. The
review loop and the ops-dispatch rules load only on their own branches. The
App identity section of launch-fleet loads only when an App token mints, so
both branches are counted.

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines (WS1 pin / pre-rewrite `main`) | 377 / 354 | 91 |
| Entrypoint words (WS1 pin / pre-rewrite `main`) | 6,777 / 5,848 | 1,590 |
| Entrypoint static tokens (WS1 pin) | 9,389 | 2,358 |
| Static loaded-path tokens, no App token | 53,161 | 15,061 |
| Static loaded-path tokens, App token mints | 53,161 | 43,800 |
| Observed workflow outcome | Pass | Unmeasured |
| Observed workflow token counts and wall time | Unknown | Unknown |

Conditional references carry static token counts of 804 for
`references/review.md` and 644 for `references/ops.md`. These references are
outside the regression branch. The entrypoint includes the full license notice
that the WizSkills checker requires.

The before values come from the
[WS1 static baseline](../../../tools/measure/evidence/static-baseline.json)
and [LV1 receipts](../../../tools/measure/evidence/lv1.json) at
`89fc285ce551f341b8d308732bcd8d4467ace353`. The
[after path manifest](ws5-after-paths.json) pins the repaired text after
the first review. The App branch also counts the GitHub identity contract,
matching WS1's path scope (the first count omitted it). The [static count](ws5-static-after.json) uses the same tokenizer and
encoding. The unmeasured trial below ran at the earlier candidate `b38d2e6`;
the static count is a separate size estimate of the repaired text.
To regenerate it, run
`node tools/measure/static-count.cjs skills/build-ticket/evidence/ws5-after-paths.json <tokenizer>`
from the WizSkills root, using `js-tiktoken@1.0.21`.

### Observed after trial: unmeasured

The [after record](ws5-after-receipt.json) preserves both receipts for the
candidate `b38d2e6ff78e177725555df3f4217cb2c7506b8c`, which used WS1's case
and baseline profile. Both attempts stopped in setup, before synthetic
assignment, so neither reached the workflow. Under the standing rule, the one
allowed replacement is spent and the case is handed back **unmeasured**.

| Attempt | Where it stopped | Outcome and workflow counters | Spawn-to-receipt upper bound | Cloud Credits |
| --- | --- | --- | ---: | ---: |
| [Original](https://github.com/openwizdev/OpenWiz/issues/1178#issuecomment-7001331616) | Git seed setup | All `null` | 176 s | 4 |
| [Replacement](https://github.com/openwizdev/OpenWiz/issues/1178#issuecomment-7001776864) | Isolated preflight | All `null` | 297 s | 3 |

The two attempts used 7 Cloud Credits in total
([accounting](https://github.com/openwizdev/OpenWiz/issues/1178#issuecomment-7001788768)).
Credits and spawn intervals cover whole threads, including setup and
publication, and are not workflow time. The `build-ticket.near-miss` and
`build-ticket.unowned-path` cases were not observed. No observed outcome or
token saving is claimed. The static counts above are a separate reproducible
size estimate of the required paths, not an observation.

## SK-D: mechanics in tested scripts

`scripts/ticket.py` now does the mechanics that the text used to spell out:

- reading the ticket's repository-bound owned paths, complete blocker data, blockers closed as completed and the record-author fleet start
- checking every changed path, including both sides of a rename and untracked files, against the paths owned in this checkout's repository
- reading record authors only from the GitHub identity table, the newest exact verdict header against the current head, a complete decision line bound only when it follows the newest verdict, whose last line parks exactly its findings at the current head, the newest `launch-fleet:` record on a ticket or pull request, and one named comment checked for a record author
- setting the noreply author
- keeping the first-successful-push receipt, leaving it unknown after an unrecorded earlier push, and posting it once as a record author with read-back after a lost or timed-out response

Run `python3 -I skills/build-ticket/scripts/test_ticket.py -v`, which
`check/run.py` also runs. All 17 tests first failed against a stub that
exits 2 for every command. Each failure reached its own assertion, as shown in
[ws5-red.txt](ws5-red.txt). After the first review (R1 to R5), the 16 new
or changed cases failed at their own assertions against `e88fcf3`, while
the 13 kept cases passed. That run is
[ws5-review-red.txt](ws5-review-red.txt). All 29 cases pass after the fix.
R6 restores ops-wake text, which has no script.

In the fresh round for the re-check's R1, the new cases failed at their own
assertions against `fd3bd0f`, as shown in [ws5-r1-red.txt](ws5-r1-red.txt).
Eleven subtests failed and no setup errors occurred. Each failing subtest
represents a decision that is bound or a comment that is read when it should
not be. They cover a partial parked set, a decision before the park report, a
park line that is quoted rather than terminal, an incomplete decision line,
`log and merge` without its polish issues, the ticket read offering the
newest trusted comment as the answer, the missing named-comment check and
the pull request read omitting its `launch-fleet:` record. The
superseded-park case was already refused, but it failed on its reason.
Afterwards, a park report at an older head was added. `fd3bd0f` refused that
case for a different reason. All 30 tests pass after the fix. The fix adds
39 words to the entrypoint's Records guard and 33 to `references/review.md`.
The static counts above remain pinned at `ca6cefd` and were not rerun.

Each guard below was broken in a temporary copy of the implementation. The
named test then failed, and restoring the copy made it pass.

| Planted break | Caught by |
| --- | --- |
| Folder prefix matched without its `/` boundary | `test_scope_flags_every_unowned_side` |
| Only the new side of a rename checked | `test_scope_flags_every_unowned_side` |
| Untracked files skipped | `test_scope_flags_every_unowned_side` |
| Any commenter's `VERDICT:` trusted | `test_records_trusts_only_record_authors` |
| An empty authors row trusts everyone | `test_records_without_a_valid_authors_row_trusts_nobody` |
| Verdict head not compared with the current head | `test_records_marks_a_verdict_on_an_older_head` |
| Open blocker ignored | `test_read_refuses_an_open_blocker` |
| `needs-info` ignored | `test_read_refuses_a_ticket_not_released_to_agents` |
| Repository qualifier read as an owned path | `test_read_lists_owned_paths_and_readiness` |
| Receipt replaced on a later push | `test_push_receipt_records_only_the_first_success` |
| Receipt saved after a failed push | `test_push_receipt_records_only_the_first_success` |
| Receipt allowed inside the checkout | `test_push_refuses_a_receipt_inside_the_checkout` |
| Post without reading back first | `test_post_receipt_survives_a_lost_response_and_never_posts_twice` |
| Lost POST response treated as not posted | `test_post_receipt_survives_a_lost_response_and_never_posts_twice` |
| Author email not the noreply form | `test_author_sets_the_users_noreply_identity` |
| R1: verdict SHA read anywhere in the body | `test_records_reads_only_a_full_verdict_header` |
| R1: decision head not checked | `test_records_binds_a_decision_to_its_parked_finding_and_head` |
| R1: decision's parked finding not checked | `test_records_binds_a_decision_to_its_parked_finding_and_head` |
| R1: authors row read outside the identity table | `test_records_reads_authors_only_from_the_identity_table` |
| Fresh R1: decision before the park report accepted | `test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park` |
| Fresh R1: park line read anywhere in the report | `test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park` |
| Fresh R1: partial parked set accepted | `test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park` |
| Fresh R1: park report's head not checked | `test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park` |
| Fresh R1: `log and merge` accepted without its polish issues | `test_records_binds_only_a_later_decision_naming_exactly_the_terminal_park` |
| Fresh R1: named comment trusted from any author | `test_records_reads_one_named_trusted_comment_on_a_ticket_or_pull_request` |
| Fresh R1: ticket read offers the newest trusted comment as the answer | `test_records_reads_one_named_trusted_comment_on_a_ticket_or_pull_request` |
| R2: repository qualifier ignored | `test_scope_applies_owned_paths_only_in_their_repository` |
| R2: `--owned` accepted without an annotated bullet | `test_scope_accepts_annotated_and_hand_resolved_paths` |
| R3: blocker closed as not completed accepted | `test_read_requires_completed_blockers_and_the_fleet_start` |
| R3: fleet start record not required | `test_read_requires_completed_blockers_and_the_fleet_start` |
| R3: incomplete blocker data accepted | `test_read_refuses_incomplete_blocker_data` |
| R4: earlier unrecorded push ignored | `test_push_after_an_unrecorded_earlier_push_stays_unknown` |
| R5: a copy by any author accepted | `test_post_receipt_ignores_a_copy_by_anyone_else` |
| R5: read-back failure not reported as unknown | `test_post_receipt_without_a_read_back_is_unknown` |

## SK-E: guards

- **Privacy.** The skill still names the open-development contract and keeps
  its no-private-details rule visible. The receipt is refused inside the
  checkout.
- **Approval.** The skill states the rules for owned paths, supporting
  edits, standing rules, shared files, ticket bodies and asking first. The
  `scope` command enforces them before each commit and at hand-back. Paths
  are bound to their repositories. `read` requires blockers closed as completed
  and the fleet's start record. Ops-dispatch envelopes, grants and the
  authorized-wake, OB-A1 and OB8 limits are in `references/ops.md`.
- **Records.** The skill states the record-author rule, the current-head
  binding of verdicts and decisions, and the parked-finding binding inline.
  The `records` command enforces them on pull requests and tickets. Without a
  valid authors row in the identity table, it trusts nobody. A first-push
  receipt is reused or confirmed only from a record author.
- **Builder and reviewer.** The builder never reviews, merges or delegates,
  uses no helper agents, never waits awake, follows the 1 + 1 loop with its
  `Next:` states and archives itself after a merge or close (CW16).

No build-ticket suite existed before this change. The review repair changed
expected output lines only in this change's own new tests, and no test was
deleted.
The skill rules, the standalone check and every other suite run unchanged.
