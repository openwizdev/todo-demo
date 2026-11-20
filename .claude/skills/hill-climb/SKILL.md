---
name: hill-climb
description: Improve one outcome in autonomous rounds. Fresh CloudRoom branches each try one change, an isolated judge council (or pairwise Bradley-Terry) keeps or undoes it, and Jake picks at checkpoints. Use for a hill-climb run or iterative design exploration; for one picture or screenshot, use image instead.
version: 0.2.0
---

# Hill-climb one thing

Change, score, keep or undo, round after round; keep the best so far, even from an earlier round. The judge helps search; Jake's checkpoint picks are the ground truth for his taste. A fixture run is not a live climb, a generated target is not a working page, and the last candidate is not the best.

## Guards

- **Privacy:** saved artifacts use synthetic content. Exact checkpoint answers, thread ids and evaluation state stay in the configured private repository or private state. Public ledgers record a choice in your own words, its date and the verified private-record comment pointer, never exact user words or links to private files.
- **Approval:** this skill gives no new permission to read live accounts, publish, deploy, merge or spend through a new service, and a checkpoint grants none. Unresolved scope or approval questions go to the ticket's orchestrator.
- **Builders and judges apart:** no family judges its own work alone, and the judge sits outside the climbers' reach (below).

## Set up the run

1. Read the ticket, spec, confirmed grill, project instructions and owned paths. Record one outcome, the starting commit and baseline, the allowed changes, the required functional checks and the evidence of improvement.
2. For design runs, complete the image skill's [UI brief](../image/references/ui-brief.md) first. Pin the project profile and mood-board commit in a public taste brief, with hard rules, explicit preferences and observed patterns kept apart. Builders and judges get the same public taste brief, surface brief, design specification and synthetic content packet, frozen for the stretch. A changed preference starts a new rubric version at the next stretch; keep earlier briefs and comparisons and never pool them.
3. Record a **fixed schedule**: round cadence, the few branches per round, checkpoint cadence and a positive stall window in completed unchanged rounds. These are run parameters, not a round, time, token or dollar cap; add no cap. Schedule with CloudRoom Loops (see the installed `room-cli` help), never a shell sleep loop. One round owns the run's state; a repeated wake resumes it.
4. Pin builder and judge routes (harness, model, effort) and the rubric for the stretch. Cheap builders (Codex Terra, Claude Haiku) iterate freely; big builders (Codex Sol, Claude Opus) make the checkpoint candidates. Verify model IDs in the harness: a model's name in a JSON file is not proof of which ran.

Done when the run record holds all of the above.

## Put the judge outside the climbers' reach

The controller's evaluation workspace holds the judge, frozen judge brief, scoring scripts, candidate-to-artifact map, raw verdicts and a **held-out check that climbers never see**. Candidate sandboxes get only their scoped source, baseline artifacts, public goal and one concrete change. Use separate filesystem and credential boundaries: judge files chmod'd read-only under the same user are not isolation. A CloudRoom child copies its parent's workspace, uncommitted files included, so keep evaluation material outside the copied project and verify the child's accessible files and tools before it works. If the filesystem boundary cannot be enforced, stop setup and report it.

When the runtime cannot enforce a credential boundary between climbers and the judge, the controller must audit each climber's complete command log and tool calls after every round, before judging any candidate. Allow only `room-cli files wait`, CloudRoom's startup step; any other `room-cli` command, or any use of the bridge to the user's machines, including indirect calls through commands, scripts or tools, disqualifies the climber. Drop that climber's candidate from judging and selection, and record the finding in the controller ledger. If any climber's command log or tool-call record cannot be read completely, stop the run and report the blocker; never treat an unreadable log as clean. Climbers' briefs must never mention `room-cli`.

Verify isolation with a harmless denied read/write probe. Plant one known-bad candidate and prove the held-out check rejects it; climbers see only its pass or fail. Save these observations: the fixture tests prove neither.

## Run a round

1. Round 0 evaluates the unchanged baseline. The controller ledger holds immutable candidates: blind label, parent, commit, builder family and model, one change, round, picture, screenshots, checks, verdicts and keep/undo/crash.
2. Start a **few fresh CloudRoom threads** with `room-cli thread spawn`, each on its own branch from the committed best so far, never hidden agents or a shared sandbox. Each brief stands alone: outcome, owned paths, parent commit, public constraints, evidence to return and **one distinct concrete change**. No inherited chat or judge reasoning.
3. Read each candidate's actual diff and results. A failed check, missing screenshot or absent judge reply is not a win and is never sent to taste judging. Keep failed and discarded tries as evidence.
4. Judge eligible candidates beside the incumbent, by council (below) or pairwise. Keep a new best only after the functional and held-out checks pass. On a tie keep the incumbent if it is tied; otherwise record an unresolved tie. Undo leaves the incumbent and keeps the losing branch; never force-push or reset a shared branch.
5. Save the round's pictures, screenshots, scores and decision, even when every try crashed; update the chart. Check for Jake's stop and a stall, archive finished candidate threads, and continue at the next scheduled round.

Only the controller moves the best-so-far pointer; resume from its ledger. Never repeat a verdict for a nicer result or change the rubric mid-stretch.

## Council judging

The council is the default for design work. Pairwise judging with Bradley-Terry ranking stays available as an option when the ticket asks, there is no category rubric, or a council tie needs settling. Seat three judges from at least two model families, each a pinned route in a fresh context every round. Judges score every artifact from 1 to 10 in each category of the frozen rubric, with a reason each. A ticket may name its own categories; otherwise:

- **Design:** hierarchy, typography, color and contrast, consistency, clarity.
- **Copy:** clarity, accuracy, tone, brevity.

Named reference products are scored in the same round, with the same rubric and viewports, under blind labels. The aim is a candidate that beats every reference in every category, consistently. Judges never see the score being aimed for. A judge's brief holds the frozen rubric, the 1–10 scale, the categories and the blind artifacts; never the stop condition, an earlier score, another judge's score or which artifacts are references. The controller keeps the stop and varies the order between judges. Run the cheapest judge alone until it is satisfied, then seat the whole council for every later round. Record each judge's scores for every round, discarded candidates included. The run stops on the references when the same single candidate leads, and is also the round's `best`, for `--window` consecutive full-council rounds.

```sh
python3 skills/hill-climb/scripts/climb.py council council.json --window 2 > council-result.json
python3 skills/hill-climb/scripts/climb.py table council.json > scores.md
```

`council` checks seating, complete scores and references, and prints each round's leaders and `best`, then `next_judges`, `stop` and `reason`; `table` prints the Markdown score table. Exit 2 is a refusal. Input shape:

```json
{"categories":["hierarchy","clarity"],"artifacts":[{"id":"A","family":"openai"},{"id":"R","reference":"Synthetic Reference One"}],"judges":[{"id":"J1","family":"anthropic","cost":1},{"id":"J2","family":"openai","cost":2},{"id":"J3","family":"anthropic","cost":3}],"rounds":[{"round":0,"judges":["J1"],"scores":[{"judge":"J1","artifact":"A","category":"hierarchy","score":7,"reason":"The next action reads first"}]}]}
```

## Pairwise judging

The judge comes from a different family from both authors of every pair. With only OpenAI and Anthropic, use one builder family per pool; a mixed pool needs an independent third family, or report the blocker.

```sh
python3 skills/hill-climb/scripts/climb.py pairs pool.json > tasks.json
python3 skills/hill-climb/scripts/climb.py rank results.json > ranking.json
```

`pool.json` is `{"candidates":[{"id":"A","family":"openai"},...],"judge_family":"anthropic"}`. Show each task in a fresh judge context with the frozen brief and two blind artifacts only. The judge returns `{"winner":"left|right|tie","reason":"..."}` (one enum value). A missing or malformed reply leaves the pair incomplete, never a tie. `results.json` adds `comparisons` (each task with its `winner` and `reason`) for every call in the stretch, discarded candidates included; never rank only the latest round. `rank` prints relative strengths, the `top` set and a `winner` only when unique; the fit's rules are in `climb.py --help`.

## Checkpoints: Jake chooses

On the checkpoint schedule, big models build from the strongest cheap directions; judge them against the incumbent and show Jake the **best three**, with stable letters, changes, ranking and reasons. Fewer than three valid ones is a gap to fill, never padding. Show before and after images with arrows and short notes on what changed, plus the per-round score table, drawn over real screenshots with the image skill.

Jake may pick one or mix parts. Save his exact answer privately and record the chosen parts publicly with the pointer; a mix becomes a new tested candidate with its parents, and the next stretch's parent. Report agreement as agreed over comparable pairs of his explicit picks against the judge's pre-pick order, with ties; a mix alone leaves it unmeasured. A pending checkpoint is a wait, not a finished climb; keep exploring without overriding it.

## Stall and stop

```sh
python3 skills/hill-climb/scripts/climb.py stall history.json --window 2
```

`history.json` is `{"rounds":[{"round":0,"winner":"A"},...],"stopped_by_jake":false}`, contiguous from round 0, with `winner:null` for an unresolved round; a checkpoint pick or new rubric starts a fresh history at round 0. Set `stopped_by_jake` only for his explicit stop. It prints `continue`, `stall` or `jake`. On a stop, end the run's loop, collect artifacts, archive workers and report the best candidate, lineage, rounds, measurements and gaps. Broken infrastructure, an account limit or a timeout pauses with a blocker; it is neither a stall nor a win.

## Design rounds

Follow the image skill: generated targets set the look, the real HTML is judged. Every round folder, discarded candidates too, keeps the target and prompt, code commit, both real-page screenshots from its [screenshot script](../image/scripts/screenshot.py) at 390 × 844 and 1440 × 900, the capture manifest, comparisons, ranking and a written critique from the [screenshot critique](../image/references/ui-craft.md#screenshot-critique). Open both PNGs; test interactions and accessibility separately. Record missing artifacts for a crashed round; never invent them.

Chart the climb from recorded numbers, never generated images, with the image skill's chart rules. Plot each round's selected candidate's chance of beating the fixed baseline from `climb.py odds results.json --baseline <id>`. For a council run, plot each category's council mean per round for the round's best candidate and for each reference, from `council`'s output, and keep the per-judge `table` output behind it. Mark ties, crashes, cheap-only rounds and picks, and never join different rubrics.

## Verify

```sh
python3 -I -m unittest discover -s skills/hill-climb/tests -v
```

Fixtures prove planning, fitting, odds, council scoring and stopping, not live judging, isolation, model quality, human agreement or a real design climb.

## Sources and decisions

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

Jake, 2026-11-01: autonomous rounds, fresh branches, frozen independent judging, checkpoint picks and mixes, complete evidence, and a stall or explicit stop ([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704791158)). Jake, 2026-11-06: council by default, pairwise Bradley-Terry as an option ([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704794292)). Concepts, in original prose and code: [Karpathy's autoresearch](https://github.com/karpathy/autoresearch), [Anthropic's generator/evaluator](https://www.anthropic.com/engineering/harness-design-long-running-apps), [Theo Browne's council](https://github.com/t3dotgg/tstack/tree/1085050/skills/council) and his video "Agents Sucked At UI (Until Today)", [Simon Willison's pairwise image Elo](https://simonwillison.net/2025/Jun/6/six-months-in-llms/) and [LMSYS's Bradley-Terry](https://lmsys.org/blog/2023-12-07-leaderboard/). None adds a round or spend cap.
