# WS6 review-ticket proof

## SK-B and SK-C

These counts use the same `review-ticket.exact-head` branch and stop as WS1: a
first review at a verified head, through the public-safe verdict, with no
grant, re-check or live proof. On that branch the static metric covers the
entrypoint and the public-record contract. The helper only runs, so its source
is never loaded. The re-check and grant references load only on those branches.

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines | 476 | 115 |
| Entrypoint words | 7,757 | 1,990 |
| Entrypoint static tokens | 11,519 | 3,098 |
| Static loaded-path tokens, `review-ticket.exact-head` | 22,300 | 13,879 |
| Observed workflow outcome | Pass | Pass |
| Observed workflow token counts and wall time | Unknown | Unknown |

The entrypoint is 115 lines, past the guide's 50 to 100. Matt Pocock's notice
is 20 of those lines, and the checker requires it word for word. The other
lines keep the privacy, approval, role and record guards visible. Theo Browne's
and Lauren Tan's notices moved to [NOTICES.md](../NOTICES.md), which ships in
the same package.

The conditional branches, counted the same way at the implementation commit,
are 15,038 tokens for a re-check (adding `references/re-checks.md`) and 19,042
for the grant branch (adding `references/grants.md` and
`contracts/ops-dispatch.v1.md`). Before, both branches loaded the whole
11,519-token entrypoint.

Before sources are pinned at `89fc285ce551f341b8d308732bcd8d4467ace353`:
the [WS1 baseline row](../../../tools/measure/evidence/baseline.csv),
[static baseline](../../../tools/measure/evidence/static-baseline.json) and
[LV1 receipt](../../../tools/measure/evidence/lv1.json). The
[after path manifest](ws6-after-paths.json) pins the implementation commit.
The [static count](ws6-static-after.json) uses `js-tiktoken@1.0.21` and
`o200k_base`. To regenerate it from the WizSkills root, run
`node tools/measure/static-count.cjs skills/review-ticket/evidence/ws6-after-paths.json <tokenizer>`.
The same tokenizer reproduces the WS1 static baseline exactly.

The [after receipt](ws6-after-receipt.json) is the fleet's one matched
synthetic trial under the LV1 extension, at candidate
`c41ef0fc2184b942b18a478aeaaacab9dcc95ff1` with WS1's baseline profile
(Codex, Sol 6.2, Medium). The candidate's skill, references, helper and
contracts are byte-identical to the implementation commit pinned for the static
count. Source: [receipt](https://github.com/openwizdev/OpenWiz/issues/1179#issuecomment-7001179969)
and [accounting](https://github.com/openwizdev/OpenWiz/issues/1179#issuecomment-7001196636).

| Workflow and attempt | Observed outcome | Workflow time | Spawn-to-receipt upper bound | Cloud Credits |
| --- | --- | ---: | ---: | ---: |
| `review-ticket.exact-head`, before | Pass | Unknown | 235 s | 3 |
| `review-ticket.exact-head`, after | Pass | Unknown | 316 s | 4 |

The after trial had zero retries. Its workflow-only time and every host token
counter are `null`: no complete matched workflow timer or attributed host
counters were available. The spawn-to-receipt bound covers startup, fixture
preparation and publication as well, rounded up to the second, so it is not a
workflow-time comparison. Cloud Credits are thread-level.

In the trial, `pin` selected a full review using base-branch settings, `check`
accepted the report, and `post` wrote one simulated comment and read it back.
The verdict was `CHANGES`, with one blocking finding for the confirmation guard
the synthetic shortcut route had dropped. A scratch run of the base showed the
red, and a rerun at the clean pinned head reproduced the break. The reviewed
checkout stayed unchanged.

The fixture was reconstructed from the sanitized WS1 before receipt at the
action-dispatch layer. The original fixture bytes were unavailable, so they
could not be compared. It used new synthetic IDs, commits, policy and tracker
records, and it kept the original case's controls and every-route confirmation
requirement. Setup and preflight on disposable state ran outside the measured
segment, as did publication. The trial exercised no grant, re-check, merge or
live proof. No further independent trial is authorized.

## SK-D: mechanics in `scripts/review.py`

| Mechanic, formerly prose | Now |
| --- | --- |
| Pin the head, check the draft state and read the required check runs at that commit | `pin`, with required checks read from the base branch's `fleet.md` |
| Decide first review, re-check, final check or stop, from record-author reports only | `pin` prints the mode, last-read commit, open ids and next id |
| Validate the report: verdict line, second line, intent, ids, grades, blocker lines, ruling marks, the four `Next:` lines and the 1 + 1 rules | `check` prints `report ok` or each broken line |
| Post once and read back with `jq` | `post` refuses a failing report, deduplicates and reads back. A lost response is recovered without a second POST |
| Look up the triage label with `awk`, write the heredoc body, create the issue | `follow-up` reads the label from the ticket repository's default branch, files once and reads back |

No prose copy of these procedures remains. SKILL.md keeps the commands, their
short results and the one-line recovery for each.

## SK-E: guards

No WizSkills suite covered review-ticket before this change, so no kept suite
case existed to rerun. OpenWiz's `tools/skills-eval` review-ticket cases are
model evals against the pinned WizSkills, outside WizSkills CI; WS6 left them
unchanged. Each guard stays visible in SKILL.md, and the helper tests enforce
it where it is mechanical:

| Guard | Text | Enforced by |
| --- | --- | --- |
| Privacy | "Guards: Privacy" and the follow-up and report steps | `test_private_material_is_refused` |
| Only an exact-head APPROVE approves | "Guards: Approval" | `test_approval_never_carries_to_a_new_head`, `test_full_review_report_problems` (wrong head) |
| Builder-reviewer separation and the no-helper rule | "Guards: Role" and the opening paragraph | Independent review: no mechanical form |
| Record authors only, trust nobody without a valid row | "Guards: Records" | `test_a_verdict_from_anyone_else_is_ignored`, `test_missing_or_malformed_record_authors_trust_nobody` |
| Settings can't be relaxed by the pull request itself | Helper paragraph | `test_settings_come_from_the_base_branch` |
| Green CI at the exact head before review | Step 1 | `test_required_check_not_green_stops` |
| 1 + 1, fresh round and park | Re-checks reference | `test_recheck_report_problems`, `test_fresh_round_leads_to_a_final_check_and_park_stops` |
| Self-archive on merge or close | "Guards" | `test_draft_closed_and_ticketless_pull_requests_stop` (merged, closed) |

Mutating each of seven guards in the helper turned its test red: settings read
at the head, any comment author trusted, the CI gate skipped, no post
deduplication, no read-back, a `Risk:` blocker loggable, and the privacy check
off. The [failing-first run](ws6-red.txt) is the committed skeleton, before the
implementation.

## Review round: R1 to R6

The measured candidate above, `c41ef0f`, and its scoped receipt are unchanged.
No new independent trial was run or authorized, so the fixes have no observed
workflow measurement. The [re-check failing-first run](ws6-recheck-red.txt)
reproduces each finding on the reviewed helper before the fix.

| Finding | Workflow path it changes | New test |
| --- | --- | --- |
| R1 | Park and decision only. `pin` consumes a record author's decision naming the parked ids and head. Fix once more admits a final check at the new head. Log and merge admits one same-head report grading those ids polish with the decision's issues. | `test_fix_once_more_decision_admits_a_check_of_the_new_head`, `test_log_and_merge_decision_admits_one_same_head_polish_report`, `test_unmatched_or_unauthorized_decisions_keep_the_park` |
| R2 | Re-check and final-check reports. An earlier finding keeps its grade, a blocker takes only a blocker status, a prior `Risk:` line is carried forward, and the v2 ruling-mark refusals apply. | `test_an_earlier_blocker_cannot_be_closed_as_polish`, `test_v2_ruling_mark_refusals` |
| R3 | Every command. The record-author row is read whole and only once, as launch-fleet's `grants.py` reads it. | `test_record_author_row_is_parsed_whole` |
| R4 | Every command. Required checks include a `**Additional ... check: `name`**` declaration in `## CI checks`, OpenWiz's form for `privacy`. | `test_additional_required_check_outside_the_table` |
| R5 | `post`. Success is bound to the write's returned id and its read-back. A lost response counts only a new comment. An identical comment from anyone else is not a post. | `test_identical_text_from_anyone_else_is_not_a_post` |
| R6 | Every command. `--head` is required. Each command reads one pull-request snapshot and admits it before reading or writing, and `post` repeats admission right before the write. | `test_commands_are_bound_to_the_assigned_head`, `test_pin_reads_one_snapshot`, `test_post_repeats_admission_before_writing` |

On the measured `review-ticket.exact-head` path, the only command change is the
added `--head` argument. The admission gates add stops; they add no reads to
the entrypoint. Recounted at the fix commit, the same path is 13,948 static
tokens: 3,167 for the entrypoint, which is 115 lines and 2,041 words, and
10,781 for the contract ([paths](ws6-recheck-paths.json),
[count](ws6-recheck-static.json)). The earlier count was 13,879. The kept 21
tests changed only to pass the assigned head. One new log-and-merge fixture
gives R4 its status, as a re-check must. No test was deleted.
