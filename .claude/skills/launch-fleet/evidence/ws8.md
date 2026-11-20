# WS8 launch-fleet proof

## SK-B and SK-C

The counts use WS1's `launch-fleet.wake` case and stop: an existing fleet
handles one eligible start, with the overload read, the public-record rules and
the identity contract. After the rewrite that branch also reads the builders
reference (the start's probe and outcome) and the identity reference. Scripts
only run on that branch, so their source is never loaded.

| Evidence | WS1 baseline `89fc285` | Main before WS8 `7c72d28` | After |
| --- | ---: | ---: | ---: |
| Entrypoint lines | 720 | 725 | 130 |
| Entrypoint words | 18,244 | 16,546 | 2,787 |
| Entrypoint static tokens | 27,561 | 25,098 | 4,399 |
| Static loaded-path tokens, `launch-fleet.wake` | 43,331 | 40,868 | 23,097 |
| Observed workflow outcome | Unknown | Unknown | Unknown |
| Observed workflow token counts and wall time | Unknown | Unknown | Unknown |

Result: pass for the static size (the WS1 path falls from 43,331 to 23,097
tokens, 47% less); unknown for an observed workflow.

The main column counts the same WS1 path at the main this branch last merged
(after WS13, the notice move, AP2's status lines and WS18's version line), with the same tokenizer.

The entrypoint is 130 lines, past the guide's 50 to 100. The Records section
is 38 lines: every wake writes those records, and the kept public record case
(`test-records.py`) reads the table from SKILL.md and checks it word for word against the open-development contract. The rest keep the
approval, record, privacy, role, no-waiting and action-gate guards visible,
the merge steps whose order is itself a guard, and the sections other skills
cite by name ("Fleet threads", "Starting one", "Each wake", "GitHub identity",
"Record authors").

Before sources are pinned at `89fc285ce551f341b8d308732bcd8d4467ace353`:
the [WS1 baseline row](../../../tools/measure/evidence/baseline.csv) and
[static baseline](../../../tools/measure/evidence/static-baseline.json). WS1
recorded no observed `launch-fleet.wake` trial, so its outcome, host tokens and
time stay unknown before and after. No after trial was run: none is
authorized for this ticket, and fixtures are not a workflow observation. The
[after path manifest](ws8-after-paths.json) pins the implementation commit.
The [static count](ws8-static-after.json) uses `js-tiktoken@1.0.21` and
`o200k_base`; the same tokenizer reproduces the WS1 static baseline exactly.
To regenerate it from the WizSkills root, run
`node tools/measure/static-count.cjs skills/launch-fleet/evidence/ws8-after-paths.json <tokenizer>`.

Each other line now loads the entrypoint plus only its own reference
(for example `references/reviews.md` for a findings line), where before every
line loaded the whole 25,098-token entrypoint.

## SK-D: mechanics in scripts

| Mechanic, formerly prose | Now |
| --- | --- |
| The two GraphQL and jq reads of a pull request's merge state and admission | `merge.py read` and `merge.py admit` |
| Merge at the exact head, read back, record `merge queued` or `merge blocked` | `merge.py merge` |
| FM4's cost line after a verified merge, posted once | `merge.py cost`, also run by `merge` |
| Writing and editing records with `gh api`, checking bodies for thread ids | `post.py comment` and `post.py edit`, with read-back and lost-response recovery |
| Seven copies of the builder, reviewer, re-check, fresh-builder, diagnose and loop briefs, each carrying the full skill-file lookup | `brief.py`, one source; the fleet-thread brief is the one install sends |

The nightly commit-comment claim, the re-test run discovery and the ordering
release remain written procedures, now in conditional references; no script
replaces them yet.

## #1238: the dormant reader and pass runner

The owner's decision of 2026-11-19 (recorded on #1181) let WS8 delete them or
test them. WS8 deletes them, so the behaviour is gone:

- `fleet.sh`'s installation read route (the `installation.json` switch,
  `routed`, `installation_get`, the paged-response shim and the installation
  privacy read). Every read is the `gh` read it was with the route off;
- `loop.sh --pass` and `--ack`, the supervised finite-pass runner;
- C8's carried installation reader, `read.py` beside `alarm.py` in `carried/`.
  Its last caller, where-are-we's dormant installation branch, was removed by
  WS13 (#1186, merged into main at `6a57abd`); WS8 merged main and deleted it,
  as the decision recorded on #1181 asked.

No WizSkills test covered any of these, so no test is deleted. The
installation read route stays disabled: no WizSkills script reads through an
installation any more. `records.py ops-pass` and the GitHub App write
identity are unchanged.
