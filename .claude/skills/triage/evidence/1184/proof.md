# WS11 triage proof

| Evidence | Before | After |
| --- | ---: | ---: |
| Entrypoint lines | 185 | 124 |
| Entrypoint words | 2,812 | 1,534 |
| Entrypoint static tokens | 3,936 | 2,271 |
| `triage.dispatch` static loaded-path tokens | 15,643 | 13,978 |
| Observed workflow outcome | Unknown | Unknown |
| Observed workflow token counts | Unknown | Unknown |

Before is the WS1 pin `89fc285ce551f341b8d308732bcd8d4467ace353`. After is `cbfe4bcf3d5a1aafecf081f6a192db752d314a71`
([path manifest](after-paths.json), [static count](static-after.json)), same
tokenizer and encoding as WS1. The open-development contract dominates the
path and is unchanged. No workflow trial ran for this ticket: the
[receipt](after-receipt.json) keeps outcome and every counter unknown.

The entrypoint is 124 lines: 20 are Matt Pocock's notice (moving to
`NOTICE.md` under WS15) and two record templates are read verbatim by
`test_public_records.py` and launch-fleet's batch cases. A new idea that
needs the user's design decisions names its road from the project's
`docs/agents/roads.md`; triage asks and the user picks. No new script:
`find-work.sh` keeps the mechanics, and its prose description is now
only its call, output and exit codes. Kept suites pass unchanged.
