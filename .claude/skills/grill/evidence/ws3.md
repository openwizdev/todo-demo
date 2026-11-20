# WS3 grill proof

## SK-B and SK-C

Same `grill.new` branch and stop as WS1, from the first interview through the
read-back of the confirmed private record. The static metric includes the
ordinary-workflow file and record references and the public-record contract.
The helper executes without its source being loaded. Coordination, factory
stock and elevated-risk cockpit guidance are conditional on those branches.

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines | 238 | 107 |
| Entrypoint words | 3,960 | 872 |
| Entrypoint static tokens | 5,842 | 1,220 |
| Static loaded-path tokens | 26,553 | 13,056 |
| Observed workflow outcome | Pass | Pass, zero retries |
| Instrumented workflow time | Unknown | 23,545 ms |
| Bounded spawn-to-receipt time | 329 s | 264 s |
| Observed Cloud Credits | 3 | 3 |
| Observed workflow token counts | Unknown | Unknown |

The after entrypoint includes the full license notice required by the
WizSkills checker and keeps the privacy and approval boundaries visible.
The before source is pinned at `89fc285ce551f341b8d308732bcd8d4467ace353`.
The before observation comes from the
[WS1 receipt](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999424054),
the [WS1 before accounting](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999452169),
and the [WS1 static baseline](../../../tools/measure/evidence/static-baseline.json).
The [after path manifest](ws3-after-paths.json) pins the implementation.
The [static count](ws3-static-after.json) uses the same tokenizer and encoding.
Regenerate it from the WizSkills root with
`node tools/measure/static-count.cjs skills/grill/evidence/ws3-after-paths.json <tokenizer>`
using `js-tiktoken@1.0.21` and `o200k_base`.

The single authorized after-run passed on Codex Sol 6.2 Medium at
`9e7efe35dcc8e6ac1c895ec27aae15877535283a`. The 23,545 ms instrumented
timer covers delivery of the synthetic request through the final local
read-back, including operator time between steps. The 264 s bound covers
spawn through receipt publication, and 3 Cloud Credits cover the thread.
Workflow token counters remain null because the host could not isolate them.
[Saved receipt](ws3-after-receipt.json) ·
[Trial receipt](https://github.com/openwizdev/OpenWiz/issues/1176#issuecomment-7000772836) ·
[Thread accounting](https://github.com/openwizdev/OpenWiz/issues/1176#issuecomment-7000783715)

The before receipt describes the notebook choices and checks without the
original fixture bytes. The after fixture reconstructed that workflow with
fresh synthetic prompts, replies, dates and IDs. It delivered the two
independent replies separately and used a multiline dependent reply with
trailing spaces. The candidate index and record helper read actual local Git
commits. A local adapter supplied the expected origin identity and private
tracker responses. Push, PR, comment, message and merge effects stayed local.

The operator verified that the first two answers were saved before the
dependent header choice was asked, that all four exact replies matched the
Git record and simulated private comments, and that the confirmed summary
and round order survived local Git read-back. Only the representative
`grill.new` workflow ran. The other nine research cases remain unobserved
in an agent workflow. Their scoped proof is listed below.

## SK-D and SK-E

Run `python3 -I skills/grill/scripts/test_records.py -v` and
`sh skills/grill/scripts/test.sh` from WizSkills. The skill-wide checker
runs both suites. The 30 existing index cases are byte-identical.

| WS1 case | Scoped evidence |
| --- | --- |
| New grill | The notebook replay publishes both rounds in their fixture order and reads back the confirmed summary. Premature resolution is refused. |
| Cold restart | Publishing with the saved request ID recovers partial progress and does not add a request. |
| Ambiguous reply | Only the saved, settled IDs advance. The user or interviewer still determines which replies are ambiguous. |
| Simplify | The replacement has a fresh fingerprint and the same ID and context for the question. Its predecessor is superseded. |
| Stale contextual answer | A repointed round or wrong subject refuses before extracting an answer. |
| Shared message | Contextual routing binds one grill even if the payload names another. The ordinary line-splitting instructions are retained in coordination. |
| Park and resume | The saved parked state refuses answers without settling the request. The old request can be superseded after its PR is closed. Branch creation and restoration of the frontier are interview steps. |
| Corrected summary | An old confirmation fingerprint refuses after the corrected summary is saved. |
| Unknown privacy | Unknown or internal visibility refuses with zero private writes. |
| Lost write response | Read-back recovers one committed effect. An unresolved POST does not repeat in the same checkout. |

The tests exercise public CLI results and saved tracker state in disposable
fixture directories. First-red runs are in this folder. The new feature
proofs fail at the earlier helper absence. The recovery and privacy red
runs also show the regressions on the initial helper.
