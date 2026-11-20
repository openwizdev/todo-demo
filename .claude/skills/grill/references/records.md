# Save and verify a grill

Create `docs/grills/<start-date>-<lowercase-topic>.md` using the
[template](../assets/grill.md). Keep one `Status:` and the `Feeds:` sentence in
the third physical line. Omit the Already settled line when empty. Use
`## Round N` in increasing order and IDs with one or two uppercase letters
and a counter that increases across rounds. A repeated question uses the
same ID with `, re-asked` appended before the separator. Use
`## Summary, corrected (shown to <User> for confirmation)` for a correction.

The template's risk lines are examples. Classify each round and summary
independently as ordinary, live, release or publish on the first physical line
after its heading. If risk is unknown, omit the locator and keep cockpit
answering disabled. Live, release and publish require the cockpit's second
confirmation under [decisions.v1](../../../contracts/decisions.v1.md#response-risk-and-answers)
and their existing authority gates. A grill record grants no additional authority.

Quote every reply line in order with `> `, using `>` for a blank line. Save
typos, whitespace and skipped or ambiguous replies. Record `Settled:` and
`Open:` after each round reply, with every question in one list and `none`
for an empty list. Put clarifications and cross-record pointers in separate
notes below the reply. Set the final status to
`Status: **confirmed** by <User>, <YYYY-MM-DD>.` only after explicit confirmation.

## Decision requests

Run `python3 -I <skill-directory>/scripts/records.py <private-owner/repo> <PR> <grill-file> <operation>`
from the verified private checkout. Use the relative grill file path. The
helper uses the explicitly named private PR and its saved head. Keep all
inputs, outputs and local scratch files private.

| Operation | When to use it |
| --- | --- |
| `publish <request-id>` | After the round or summary is pushed. Use a repository-unique ID and retain it in private state before the first attempt. Proceed on `verified request`, using the read-back status and the saved file to resume. |
| `match <message-file> <new-answer-file>` | For a cockpit-framed answer, before interpretation. Save the entire message byte for byte into the input. A match writes the exact payload and prints its single question or summary locator. Keep the output private and apply the ordinary answer rules only to that locator. A refused match settles nothing. |
| `advance <comment-id> [<answered-id> ...]` | Only the orchestrator, after the exact reply, settled IDs and private reply comment are saved and verified. Supply all saved answered IDs in question order. For a confirmed summary use `advance <comment-id> confirmed` after pushing the confirmed status. |
| `supersede <comment-id>` | Only the orchestrator, after the replacement source is pushed or the request is withdrawn. Use the old PR and exact pending comment. Verify supersession before publishing the replacement with a fresh request ID. |

On a refusal or uncertain write, reread the private PR and exact saved request
before proceeding. Reuse the original ID and checkout for reconciliation.
An absent result after an uncertain POST remains unresolved. Never switch
IDs or checkouts to retry it. A transport receipt, vague reply or closed PR
alone settles nothing. For cockpit replies, include payload lines even if
they look like a second header or name another grill. Those lines remain
part of the one matched answer. Ordinary replies still use their normal routing.

## Terms and decisions

Save and read back a comment on the private grill PR with the user's exact
reply and the question or summary it answers. After an uncertain comment
write, reconcile on that PR before retrying. Use the verified comment as the
source for public decisions under the
[open-development contract](../../../contracts/open-development.v1.md).

In a separate development PR, add each settled project-specific term to the
configured glossary using its format. Write one ADR per hard-to-reverse
decision in the configured ADR folder, numbered after the highest existing
record. Give it a short decision title and one paragraph of context, decision
and reason. Cite the decider, date and verified private-comment pointer.
