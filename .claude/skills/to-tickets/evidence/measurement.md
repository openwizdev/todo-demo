# WS4 workflow measurements

Use the [WS1 counter](../../../tools/measure/README.md) with the pinned
[before](static-before-paths.json) and [after](static-after-paths.json)
manifests. The spec case stops at confirmation and excludes the link
contract. The graph case uses the original WS1 approval branch. Both
after cases include the record guidance and its required reads. Owning
project settings, rendered media and script output are outside this
static measure.

| Workflow | Before packaged-path tokens | After packaged-path tokens |
| --- | ---: | ---: |
| Confirmed grill to spec confirmation | 33,948 | 22,871 |
| Confirmed spec to graph approval | 38,193 | 27,549 |

[Before report](static-before.json) · [After report](static-after.json) ·
[WS1 observed results](../../../tools/measure/evidence/README.md)

## Standalone to-spec

Unmeasured at `d99e76a4a48940bf6bf4b01f75e899b47a861e32`. WS1 started with
the spec already confirmed. Both after attempts stopped in fixture setup,
first at slide generation, then at the synthetic playback wrapper after the
test MP4 rendered. Before and after outcomes and all workflow counters are
null. The packaged-path sizes above support no claim of observed savings.
[Original receipt](https://github.com/openwizdev/OpenWiz/issues/1177#issuecomment-7001282240) ·
[Replacement receipt](https://github.com/openwizdev/OpenWiz/issues/1177#issuecomment-7001786230)

The replacement used 5 thread-level Cloud Credits and had a 330 s
spawn-to-receipt upper bound. Both standalone attempts used 10 credits total.
[Standalone accounting](https://github.com/openwizdev/OpenWiz/issues/1177#issuecomment-7001798831)

## Matched to-tickets

The WS1 repeat passed in 8,849 ms. The single matched after trial passed at
`d99e76a4a48940bf6bf4b01f75e899b47a861e32` in 21,892 ms of observed workflow
time. Workflow-only token counters are unknown. The fixture was reconstructed
from the sanitized before receipt. The chat and tracker pictures differed in
one unused legend color. Their cards, edge and fingerprint matched. The
reconstruction and different response intervals limit timing comparison.
[Before receipt](https://github.com/openwizdev/OpenWiz/issues/1174#issuecomment-6999562018) ·
[After receipt](https://github.com/openwizdev/OpenWiz/issues/1177#issuecomment-7000935945)

The after trial used 3 thread-level Cloud Credits and had a 316 s
spawn-to-receipt upper bound.
[Matched accounting](https://github.com/openwizdev/OpenWiz/issues/1177#issuecomment-7000947310)
