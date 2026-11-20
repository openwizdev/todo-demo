# WS9 hill-climb and image proof

## SK-B and SK-C

The counts use WS1's `hill-climb.select` and `image.capture` cases, with the same
branch and stop. `hill-climb.select` covers numeric ranking through one evaluation,
with no UI round. `image.capture` covers a screenshot only. On both branches the
static metric counts only the entrypoint. The scripts only run, so their source is
never loaded.

| Evidence | hill-climb before | hill-climb after | image before | image after |
| --- | ---: | ---: | ---: | ---: |
| Entrypoint lines | 468 | 106 | 213 | 76 |
| Entrypoint words | 4,188 | 1,832 | 1,780 | 1,174 |
| Static loaded-path tokens | 6,432 | 2,900 (−54.9%) | 2,684 | 1,770 (−34.1%) |
| Observed workflow outcome | Unknown | Unknown | Unknown | Unknown |
| Observed workflow tokens and wall time | Unknown | Unknown | Unknown | Unknown |

hill-climb is 106 lines, six past the guide's 100. It keeps the isolation guard's
exact sentences, which its kept tests pin, and the council's seating and stop
rules, which the council tests pin. Paragraphs are one line each, as in the pilots.

The design branch is not a WS1 case. Counted the same way, it reads hill-climb,
image, `ui-brief.md` and `ui-craft.md`, and drops from 13,100 to 8,932 tokens. An
image target reads image, `ui-brief.md` and `ui-craft.md`, and drops from 6,668 to
6,032. `ui-craft.md` grows from 1,927 to 2,205 tokens because the screenshot
critique moved into it from hill-climb.

Before sources are pinned at `89fc285ce551f341b8d308732bcd8d4467ace353`:
[baseline row](../../../tools/measure/evidence/baseline.csv) and
[static baseline](../../../tools/measure/evidence/static-baseline.json). After
manifests pin implementation commit `d8616bdadc223367dc2a8f2d6860347c3f381930`:
[hill-climb paths](ws9-after-paths.json), [hill-climb count](ws9-static-after.json),
[image paths](../../image/evidence/ws9-after-paths.json) and
[image count](../../image/evidence/ws9-static-after.json). Each count uses
`js-tiktoken@1.0.21` and `o200k_base`. To reproduce, run
`node tools/measure/static-count.cjs <paths.json> <tokenizer>`. The same tokenizer
reproduces WS1's static baseline exactly.

WS1 ran no before trial for either case, and this ticket ran no after trial. Pass
or fail, host token counters and wall time therefore stay unknown on both sides.
The static count is not an observed load.

## SK-D: mechanics in scripts

| Mechanic, formerly prose | Now |
| --- | --- |
| Bradley-Terry prior, Newton solver, convergence, tie tolerance, refusals and position splits | `climb.py` docstring (`--help`). The behaviour is unchanged, and the prose copy is gone. |
| Chart win probability from the log-strength gap, with the stable logistic | `climb.py odds results.json --baseline <id>` (new, red first) |
| Council output field list | Shortened to what an agent acts on; the fields come from `council`'s output |
| Screenshot tab, scale, motion, waits and closing | `screenshot.py` docstring (`--help`). The behaviour is unchanged. |
| Reading `contentWidth` for horizontal overflow | `screenshot.py` prints `overflow: none` or each overflowing width (new, red first) |
| WCAG luminance and ratio formula | `contrast.py FG BG [--min N]` (new, red first) |

The agreement count at checkpoints, agreed pairs over comparable pairs with ties,
stays one line of prose. It is a definition, not a procedure.

## SK-E: guards

The privacy, approval and builder/judge (or builder/reviewer) guards open each
skill under `## Guards`. These kept text cases pass unchanged:

- `test_isolation.py`, all 5: credential audit, disqualification, unreadable logs,
  no `room-cli` in briefs, and the denied read/write probe.
- `test_council.py` `CouncilInstructions`, all 6.
- `test_ui_guidance.py` tests 01–04, 06 and 07.

`test_ui_guidance.py` test 05 now reads the critique where it moved,
`image/references/ui-craft.md` `## Screenshot critique`. Its requirements are
unchanged.

All 9 earlier screenshot proofs are unchanged. The fixture server gained one
`/wide` route for the overflow proof.

## Review round (R1–R3)

These findings come from the review at `e3076f7`, and each was proved red first.

- **R1:** with `--fixed-at-bottom`, the overflow summary ignored the first-screen measurement. A height-sensitive phone fixture (`/short-wide`) is 600 px wide on the 844 px first screen and 390 px at page height. It printed `overflow: none` ([red](../../image/evidence/ws9-r1-red.txt), commit `cd94432`). The summary now prints `overflow: phone first screen 600 > 390`.
- **R2:** the council chart once again plots each category's mean per round for the best candidate and for each reference, with the per-judge `table` behind it.
- **R3:** the judge brief again lists what judges receive and withholds the stop condition. The controller keeps the stop.
- R2 and R3 failed as text cases before the fix ([red](ws9-r2-r3-red.txt), commit `aa4556a`).

Static recount at fix commit `4d11f0aeac7dd2f05dc175982d5c404064297eee`
([paths](ws9-recheck-paths.json), [count](ws9-recheck-static.json)): hill-climb is
106 lines, 1,880 words and 2,970 tokens (before: 6,432; −53.8%). image's
entrypoint is unchanged at 1,770 tokens. No observed trial ran.
