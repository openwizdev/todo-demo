# WS11 wayfind proof

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines | 163 | 91 |
| Entrypoint words | 2,489 | 1,222 |
| Entrypoint static tokens | 3,360 | 1,790 |
| `wayfind.resume` static loaded-path tokens | 29,913 | 14,853 |
| Observed workflow outcome | Unknown | Unknown |
| Observed workflow token counts | Unknown | Unknown |

Before is the WS1 pin `89fc285ce551f341b8d308732bcd8d4467ace353` ([static baseline](../../../../tools/measure/evidence/static-baseline.json)).
After is `cbfe4bcf3d5a1aafecf081f6a192db752d314a71` ([path manifest](after-paths.json), [static count](static-after.json)),
counted with `node tools/measure/static-count.cjs skills/wayfind/evidence/1184/after-paths.json <tokenizer>`
using `js-tiktoken@1.0.21` and `o200k_base`. The after path follows the default
grill route through grill's WS3 entrypoint, asset and records reference, so
part of the path saving is WS3's. No workflow trial ran for this ticket:
the [receipt](after-receipt.json) keeps outcome and every counter unknown.

`frontier.py` owns the frontier and claim-holder reads. Its tests run
through the CLI against a fake `gh`:
`python3 -I skills/wayfind/test/test_frontier.py`. The [red run](frontier-red.txt)
fails on the skeleton. The two kept wayfind claim cases in
`skills/triage/test/test_public_records.py` pass unchanged.
