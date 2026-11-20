# OpenWiz decisions contract, version 1 (`openwiz.decisions.v1`)

Structured decision requests posted by the orchestrator, plus the read-only
decisions response (0.0.11, #648, U1 #651). The schema is
[decisions.v1.schema.json](decisions.v1.schema.json). **Contract only:** U4 builds
posting, U5 reading and U6 cards/sends. Inline synthetic tests in
`tests/checks/plan_decisions_schema_conformance.rs` prove parsed shapes only.

Authority: E1–E3 and the later ruling approving all three contract choices
([private record](https://github.com/jparker2006/ClosedWiz/issues/651#issuecomment-6575677837)).
It covers grill summary confirmation as well as rounds, spec confirmation and
plan approval. The scope-only reply did not settle the contract; this later
ruling does. The source skills' human-readable records and approval rules stay.

## Record and wire rules

One GitHub comment contains one request in a fenced block whose opening line is
exactly three backticks followed by `json`, and whose closing line is exactly
three backticks, each at column zero. Its JSON object has `schema` equal to
`openwiz.decisions.v1`. Ordinary prose outside the block is not executable input.
A marked request comment with multiple JSON blocks, invalid JSON, duplicate keys,
unknown/malformed fields or a response envelope instead of a request is reported
as malformed; never guess which record was meant.

**Candidate discovery:** inspect raw text and decoded JSON string tokens before classifying a comment as ordinary.
`openwiz.decisions.` at the start of a decoded string marks a candidate, including
an unsupported version or a schema key/value written with Unicode escapes. The
literal prefix anywhere in the raw comment also marks a candidate. Decode strings
for identification even if strict parsing later refuses duplicate keys or other
structure; detection never supplies trusted record values. Inspect every JSON
fence before ignoring a comment. If malformed fencing/escapes prevent establishing
whether it holds a record, report a malformed gap rather than confidently ignore
it. Only positively unrelated comments are ordinary comments. This is identification
for reporting, not authority to send or execute anything.

With no configured pair, discovery covers cwd's repository's issue-comment feed, including PR conversation
comments on open and closed subjects; inline code-review comments are not posting
locations. Readers paginate this feed and check totals before claiming complete
coverage. Read the container from GitHub metadata, not JSON-supplied subject ids.

All objects have exactly the schema's keys, each once, including nested objects.
No missing/extra/duplicate keys or positional arrays; enums are exact strings,
never tagged objects. Integers are JSON integers (no strings, booleans, fractional
numbers or wire spelling `1.0`); issue/comment/round numbers are positive, times
nonnegative millisecond integers. Nonempty strings preserve their exact Unicode,
spaces and punctuation. Duplicate wire keys and integer spelling need a strict
reader in addition to schema validation. No normalization of the user's words.

Each request has these common fields:

```text
schema, kind, id, status: open | resolved | superseded,
fingerprint: 64 lowercase hexadecimal characters,
risk: ordinary | live | release | publish | unknown
```

`id` is a repository-unique opaque ASCII letter/digit/underscore/hyphen identifier,
starting with a letter or digit. The orchestrator allocates it when posting, reads
it back and never reuses it for a different request. Request identity is scoped to
this repository and the GitHub subject/comment, not a card's display position.
No target thread is supplied by a request comment.

## Four request variants

| Kind | Additional required fields | Source / meaning |
| --- | --- | --- |
| `grill_round` | `grill_file`, `round`, `questions`, `answered` | One saved round, 1–3 question objects, and the ids whose replies the orchestrator has saved |
| `grill_confirmation` | `grill_file`, `summary` | The latest saved grill summary; no fabricated spec number or headline |
| `spec_confirmation` | `spec`, `summary`, `headline`, `tickets: []`, `graph: []` | Confirmation precedes ticket creation; the empty table/graph honestly says not planned yet |
| `plan_approval` | `spec`, `summary`, `headline`, `tickets`, `graph` | The actual proposed plan graph and its existing revision-v2 fingerprint |

`grill_file` is a relative `docs/grills/<basename>.md` path, not an absolute path
or traversal. It names the current grill's file, including when it is on an open
PR branch. Read that PR's current head, not an older default-branch copy. A round
record is posted on that grill's PR; summary confirmation goes there too. Spec
and plan requests are comments on their spec issue. They add records alongside
the skills' existing saved wording/replies; no spec/ticket-body edit is implied.

A question is `{id, decides, context, recommendation}`, all nonempty exact strings
from the saved round. `decides` is the question's wording/what it decides. Its id
is the skill's one/two topic letters plus positive counter (for example G1), unique
in the record and consistent with open/parked grills. Simplification preserves
that id and context; it rephrases the question rather than settling it. Summary
is an array of 1–10 nonempty lines, none containing CR or LF; display them as
numbered lines. This represents the existing ten-line summary, not truncation.

`headline` is the spec's exact changelog headline (`none` for infra as the skill
already allows). A plan ticket is `{number, title, blockers}`. Ticket rows sort by
number; blockers are positive, unique, ascending and never self. The table is
exactly the current spec's sub-issues. `graph` is the unique sorted list of
`{blocker, ticket}` edges from that table, including external prerequisites;
never a separate graph that can disagree with the table. Titles/blockers and the
fingerprint bind the revision proposed, rather than the latest title guessed by
the page. These cross-record/order rules require U4/U5 checks beyond the schema.

## Fingerprints and current wording

For `plan_approval`, fingerprint is exactly the existing SHA-256 of
`skills/plan-graph/revision.sh <spec>`'s revision-v2 text, including its
newlines and existing task-box normalization. Do not invent a new plan approval
hash, use v1, or hash just the ticket table. It covers spec body, ticket numbers,
bodies, titles and blocking links; labels/comments/state do not change that hash.

For the other three variants, fingerprint is SHA-256 of the UTF-8 canonical JSON
of that request after removing only `fingerprint`, `status` and `answered`.
Canonical JSON recursively sorts object keys by their ASCII names, keeps array
order, uses no whitespace or trailing newline, decimal integers, raw Unicode
without normalization, escapes quote/backslash and C0 controls (short escapes for
backspace/formfeed/newline/carriage-return/tab, otherwise lowercase `\u00xx`),
and does not escape `/`. This binds the exact saved proposal and risk/id, not
answer progress. Every eligible request must still match the saved file/spec
wording; hashing a modified comment cannot make it current.

**Independent grill risk locator.** The grill skill saves exactly one of
`Risk: ordinary`, `Risk: live`, `Risk: release` or `Risk: publish` as the first
physical line immediately below each `## Round N` heading and each summary
or corrected-summary heading, before any blank line. Read that line from the
request's saved round or latest saved summary in `grill_file` at its PR's current
immutable head, alongside the exact wording. The request's `risk` must match
that independently saved classification. An absent, misplaced, malformed or
unknown locator means currentness is unknown plus a gap, and answering stays
disabled; never trim it, infer ordinary or borrow risk from another section.

The response's `current` is known true only after reading and checking those
current source inputs: saved grill round/summary at its head, spec body/headline,
or current plan revision and exact displayed proposal. Known false means the
check positively found a change; a failed/missing check is unknown plus a gap.
Neither an open status nor a recent comment is proof of current wording. A
changed summary/headline/risk also invalidates the displayed binding even when
the plan revision hash happens to be unchanged. Schema fixtures' repeated hex
strings are format examples, not calculated or verified revision fingerprints.

## Machine plan approval

Jake, 2026-11-19 (J202, J203; [private record](https://github.com/jparker2006/ClosedWiz/issues/3065#issuecomment-7005344027)):
a confirmed grill is the owner's one active step. Its plan is approved by the
agents' own checks, with no `plan_approval` request and no human reply. The
record is one spec comment, posted by a record author, that to-tickets'
`scripts/approve.py` prints only when every check passes:

````md
**Machine plan approval, <YYYY-MM-DD>, revision <N>:** links, relies, sizes, width and owned paths passed.
Grill confirmed: <the grill confirmation's private-comment URL>

Checks: <T> tickets; links <L>; relies <R>; sizes S <s>, M <m>, L <l>; width: chain <C>, widest <W>; owned paths <O>.

Changed since revision <N-1>: <what changed>.

| Ticket | Title | Blocked by | Label |
| --- | --- | --- | --- |
| #<n> | <title> | <#blockers, or none> | <ready-for-agent, ready-for-human, or none when closed> |

Fingerprint: `<SHA-256 of the revision text>`

<details><summary>Revision text</summary>

```text
<revision.sh's revision-v2 text, exactly>
```

</details>
````

The `Changed since` line and its blank line appear exactly when `N` is above 1.
The fingerprint is the plan revision-v2 SHA-256 above, of the same graph read
the checks ran on: the script refuses revision text that names other tickets,
titles, blockers or bodies. The checks are links (`check-links.sh`), relies
(`check-relies.sh`, a path a direct blocker owns counting as planned), sizes
(exactly one `Size: S`, `M` or `L` per open ticket), width (no cycle, and no
arrow another chain implies) and owned paths (exact repository paths, and no
two tickets that can run at once owning the same path unless both bullets say
`(shared`). A plan that fails any check gets no record. The header differs from
`**Plan graph approved by`, so a reader of human approvals never takes a
machine record for one; a reader of machine records re-runs the checks on the
current revision and compares the fingerprint. The record grants what a plan
approval grants and nothing more: every action gate (publish, spend, secrets,
deleting user data, cut-overs) keeps its own approval.

## Lifecycle

Only the orchestrator updates the added JSON block, preserving the surrounding
human-readable comment. It does so **after** saving the exact reply through the
existing skill. A page sends a message and performs no GitHub update.

- `open`: pending. A round's `answered` contains exactly the saved answered ids,
  unique and in question order; the other questions remain pending. A sent,
  dispatching, uncertain or merely accepted send is not a saved answer.
- `resolved`: the existing skill saved the reply/confirmation/approval. A resolved
  round has every question answered; partial answers keep it open. Confirmation
  variants resolve only after their existing confirmation rules accept the reply.
- `superseded`: withdrawn or replaced wording. Rephrasing/simplifying or otherwise
  changing a proposal uses a new request id/fingerprint and supersedes the old
  request; re-asked questions keep their question ids. Saving answers changes only
  status/answered; it never changes the original question text or fingerprint.

The record's `id`, kind and proposal fields are immutable over its lifecycle.
Ambiguous duplicate ids, conflicting records, a stale or unread replacement, or an
unconfirmed close produce gaps/unavailable actions, never last-write-wins approval.
If a request loses all remaining questions, it is resolved and omitted from the
open read. Closing a PR/issue alone is not proof that a request was answered.

## Response, risk and answers

```text
response { schema, kind: response, snapshot_at, coverage, freshness,
           orchestrator: { coverage, freshness, target: Fact<thread id | null> },
           items: [{ comment_id, subject: { repository, kind: issue | pull_request, number },
                     created_at, updated_at, current: Fact<boolean>, request }] }
Fact<T>  { known: T } | { unknown: nonempty reason }
```

Return every valid open record once by repository/subject/comment id, sorted by creation
time, then repository, subject kind/number and comment id. Partially answered rounds remain
one record; show only unanswered question cards. Omit resolved/superseded records,
including a positively superseded older request. Malformed marked records are
omitted with a sanitized `malformed` gap; unsupported versions, incomplete reads
and ambiguous identities are gaps too. Never mistake them for no pending work.
A stale but valid open record may remain visible with `current` false/unknown and
honest freshness; it cannot authorize an answer. The schema accepts standalone
request records in any lifecycle status, but response items only with `open`.

`risk` is an explicit orchestrator classification, never inferred from a title,
label, missing flag or question wording. `ordinary` is an affirmative classification;
`unknown` disables answering. `live`, `release` and `publish` always require a
second explicit confirmation; they remain messages asking the orchestrator, not
a new live/release/publish capability in OpenWiz.

`orchestrator.target` uses #129's configured and bounded verified target, with its
own coverage and freshness, as in `cockpit.v1`: known string only after confirming
that exact configured thread exists; known null only when a successful source
read establishes no target; otherwise unknown and a gap. The thread id is 1–128
ASCII letters/digits/underscore/hyphen, not starting with `-`. Never select a
comment author's thread, a request-supplied target or another project's target.
GitHub plan/record reads may use the read-only App token; the existing target
verification is a separate read, not new GitHub write authority.

Each card's answer is one existing send with its op id and honest outcome.
The **answer segment** is `G1 yes`, `simplify G1`, or the exact own-words
answer; `confirm` for the grill summary, `confirm spec #N`, or `approve #N`.
“Yes” takes the exact recommendation shown. These meanings and approval
requirements are unchanged; generated context is never itself an answer or approval.

**Contextual answer message.** The entire UTF-8 message has exactly this framing:

```text
openwiz decision answer v1
<one compact JSON context object>

<verbatim answer segment, through the end of the message>
```

The first line ends with LF. The second is compact JSON (no whitespace outside
strings), with keys in the following fixed order; it ends with two LF bytes.
The answer starts immediately after those two bytes and ends at message EOF:
there is no closing marker or appended newline. Never search within the answer
for another header, delimiter or command. An answer may itself contain blank
lines, JSON or header-like text without altering its boundaries.

- All contexts: `subject` (keys `repository`, `kind`, `number`, in that order),
  `comment_id`, `request_id`, `request_kind`, `fingerprint`.
- Then for `grill_round`: `grill_file`, `round`, `question_id`.
- Then for `grill_confirmation`: `grill_file`.
- Then for `spec_confirmation` or `plan_approval`: `spec`.

Values come directly from the existing response item/request and selected
question, with the same types and constraints; `subject.repository` is the
verified repository. JSON uses decimal integers, ordinary JSON string escaping
and no escaped `/`. No other keys, duplicate keys or alternative framing are
accepted. This adds message text only: no request-schema field, new identity,
fingerprint algorithm or answer HTTP route/field. For example (synthetic):

```text
openwiz decision answer v1
{"subject":{"repository":"synthetic-owner/synthetic-repo","kind":"pull_request","number":2731},"comment_id":9100001,"request_id":"dr_loops_r2","request_kind":"grill_round","fingerprint":"1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f1f","grill_file":"docs/grills/2030-01-15-loops.md","round":2,"question_id":"L4"}

L4 yes
```

The card supplies its existing binding to the request/comment, fingerprint,
exact displayed content, question id, risk and verified configured target. The
full contextual message is displayed exactly before the final send, including
at the risky second confirmation, and is the exact text retained in the receipt
and carried by the existing send. Concise action labels describe the answer;
the preview shows its context too. Own words preserve every byte typed, including
leading/trailing whitespace, Unicode and newlines, with no trimming, escaping,
normalization or synthetic prefix **inside the answer segment**. The owner does
not type the context. No automatic round batching or automatic send on
load/refresh/reload. Existing send limits apply to the **whole contextual message**;
never truncate or split an oversized message or claim an unlimited transport.

**Receiving interpretation.** Read the framing only at message start and verify
all context against the exact saved request on that repository/subject/comment:
its id, kind, existing revision fingerprint and applicable grill file/round/
question or spec identity. Independently verify that exact saved source/revision
is still current and open, the question unanswered (or the summary/proposal the
latest), and every existing risk/approval gate. Unread, ambiguous, malformed,
mismatching, stale or superseded context settles nothing; never fall back to
ordinary reply interpretation for a message claiming this framing. Do not choose
a grill or revision from a question label or the latest comment alone.

Only after that match, interpret and save **only the verbatim answer segment**
through the existing private-record, saved-first lifecycle and approval workflow;
context is attribution, not the owner's words. A transport receipt is not a saved
answer. An ordinary reply without this framing keeps its existing interpretation,
including ambiguity handling and latest-summary confirmation.

Answering requires an open unanswered item, known current wording and risk,
fresh source data, and a fresh verified target. Bind the exact visible request,
question, risk and target before preview/send; a changed/removed request or target
invalidates it. Risky records confirm twice. Repeats, held keys, reload and retry
reuse the existing operation id and one-send guarantees. These are U6's runtime
proofs. A sent/uncertain answer remains unresolved until the orchestrator saves it.

## Coverage, freshness and proof limits

Coverage/gap/freshness forms and the 70,000 ms oldest-required-source threshold
are as in [plan.v1](plan.v1.md#coverage-and-freshness) and `cockpit.v1`. Source
snapshot time is the comment/source read snapshot, never the comment's creation
or update time. Assembly never refreshes retained data. Record discovery,
pagination, malformed records and current-wording checks all contribute to
coverage/freshness; target availability has its separate part. Only complete fresh
empty record coverage permits “no decisions waiting”; no target does not hide the
records or itself turn their discovery into a confident empty list.

Reading decisions never sends, saves an answer, edits a comment or starts work.

Schema conformance does not prove fencing, authorization/provenance, canonical
hashing, question-id grammar/uniqueness, lifecycle consistency, table/graph equality,
source time math, currentness, target verification or a send. U4/U5/U6 must prove
their rules at the spec's fixture/source/page seams. All inline fixture values,
URLs, fingerprints, wording and times are synthetic (`synthetic_assumptions`);
none is a live observation or acceptance of a day's real decisions.

## Field sources

One row per declared property; inline fact fields retain the enclosing field’s source.

| Property | Source |
| --- | --- |
| `approval_ticket.blockers` | Native blocked-by numbers covered by the proposed revision |
| `approval_ticket.number` | Current spec sub-issue number in revision-v2 text |
| `approval_ticket.title` | Exact ticket title covered by the proposed revision |
| `coverage.gaps` | All incomplete required reads/derivations; empty exactly for complete coverage |
| `coverage.state` | Completeness of every required read and derived fact for this part |
| `edge.blocker` | A blocker number from the ticket table, including external prerequisites |
| `edge.ticket` | The table row blocked by this prerequisite |
| `freshness.snapshot_at` | Oldest required source snapshot, or explicit unknown when unavailable |
| `freshness.snapshot_at.known` | Nonnegative oldest required source time, never rewritten as assembly time |
| `freshness.state` | Oldest required source snapshot and assembly clock, using the existing 70,000 ms threshold |
| `gap.detail` | Sanitized explanation of the required failed/incomplete read or derivation |
| `gap.kind` | Existing inventory/fleet/cockpit failure classification |
| `grill_confirmation.fingerprint` | Existing plan revision-v2 SHA-256 for plan_approval; specified canonical exact-proposal SHA-256 for other variants |
| `grill_confirmation.grill_file` | The current saved grill file on its PR head |
| `grill_confirmation.id` | Orchestrator-allocated repository-unique request identifier, read back from the posted block |
| `grill_confirmation.kind` | Explicit request variant posted by the source skill |
| `grill_confirmation.risk` | Explicit orchestrator classification, independently saved as the first-line risk locator under the latest summary heading at the grill PR head |
| `grill_confirmation.schema` | Contract constant openwiz.decisions.v1 |
| `grill_confirmation.status` | Orchestrator-maintained open/resolved/superseded state after saving the reply through the existing skill |
| `grill_confirmation.summary` | Latest saved summary, 1–10 lines, without truncation |
| `grill_round.answered` | Unique question ids whose exact replies the orchestrator has saved, in source question order |
| `grill_round.fingerprint` | Existing plan revision-v2 SHA-256 for plan_approval; specified canonical exact-proposal SHA-256 for other variants |
| `grill_round.grill_file` | The current saved grill file on its PR head |
| `grill_round.id` | Orchestrator-allocated repository-unique request identifier, read back from the posted block |
| `grill_round.kind` | Explicit request variant posted by the source skill |
| `grill_round.questions` | The exact saved round’s 1–3 questions in source order |
| `grill_round.risk` | Explicit orchestrator classification, independently saved as the first-line risk locator under this round heading at the grill PR head |
| `grill_round.round` | Positive saved grill round number |
| `grill_round.schema` | Contract constant openwiz.decisions.v1 |
| `grill_round.status` | Orchestrator-maintained open/resolved/superseded state after saving the reply through the existing skill |
| `item.comment_id` | GitHub comment id from the comment read, not JSON-supplied identity |
| `item.created_at` | GitHub comment createdAt, converted to nonnegative milliseconds |
| `item.current` | Positive source comparison of exact saved wording/revision; false when changed, unknown when unread |
| `item.current.known` | Positive known result of: Positive source comparison of exact saved wording/revision; false when changed, unknown when unread |
| `item.request` | Validated fenced request record with status open |
| `item.request.status` | Open-read filter; only status open is returned |
| `item.subject` | GitHub issue/PR containing the comment |
| `item.updated_at` | GitHub comment updatedAt, converted to nonnegative milliseconds |
| `orchestrator.coverage` | Completeness of this configuration/target verification read |
| `orchestrator.freshness` | Oldest required configuration/target verification snapshot |
| `orchestrator.target` | Existing #129 configured target verified to exist; null only after successful absence |
| `orchestrator.target.known` | Positive known result of: Existing #129 configured target verified to exist; null only after successful absence |
| `plan_approval.fingerprint` | Existing plan revision-v2 SHA-256 for plan_approval; specified canonical exact-proposal SHA-256 for other variants |
| `plan_approval.graph` | Exact blocker-to-ticket edges of that table; empty before planning |
| `plan_approval.headline` | Exact spec changelog headline, including none for infra when applicable |
| `plan_approval.id` | Orchestrator-allocated repository-unique request identifier, read back from the posted block |
| `plan_approval.kind` | Explicit request variant posted by the source skill |
| `plan_approval.risk` | Explicit orchestrator classification; never inferred or defaulted ordinary |
| `plan_approval.schema` | Contract constant openwiz.decisions.v1 |
| `plan_approval.spec` | The spec issue on which this request is posted |
| `plan_approval.status` | Orchestrator-maintained open/resolved/superseded state after saving the reply through the existing skill |
| `plan_approval.summary` | Latest saved summary, 1–10 lines, without truncation |
| `plan_approval.tickets` | Current revision’s actual sub-issue table; empty before spec confirmation permits planning |
| `question.context` | Exact saved context, preserved on simplification |
| `question.decides` | Exact saved question wording / what it decides |
| `question.id` | Exact saved skill question id, stable on simplification |
| `question.recommendation` | Exact saved recommendation which yes accepts |
| `response.coverage` | All request discovery/validation/current-wording reads, including pagination |
| `response.freshness` | Oldest required request/source snapshot, not comment update time |
| `response.items` | All valid open requests; partial rounds retained, resolved/superseded omitted |
| `response.kind` | Contract response discriminator, never a request kind |
| `response.orchestrator` | Existing configured target and bounded verification read, with separate coverage/freshness |
| `response.schema` | Contract constant openwiz.decisions.v1 |
| `response.snapshot_at` | Clock at assembly after reads |
| `spec_confirmation.fingerprint` | Existing plan revision-v2 SHA-256 for plan_approval; specified canonical exact-proposal SHA-256 for other variants |
| `spec_confirmation.graph` | Exact blocker-to-ticket edges of that table; empty before planning |
| `spec_confirmation.headline` | Exact spec changelog headline, including none for infra when applicable |
| `spec_confirmation.id` | Orchestrator-allocated repository-unique request identifier, read back from the posted block |
| `spec_confirmation.kind` | Explicit request variant posted by the source skill |
| `spec_confirmation.risk` | Explicit orchestrator classification; never inferred or defaulted ordinary |
| `spec_confirmation.schema` | Contract constant openwiz.decisions.v1 |
| `spec_confirmation.spec` | The spec issue on which this request is posted |
| `spec_confirmation.status` | Orchestrator-maintained open/resolved/superseded state after saving the reply through the existing skill |
| `spec_confirmation.summary` | Latest saved summary, 1–10 lines, without truncation |
| `spec_confirmation.tickets` | Current revision’s actual sub-issue table; empty before spec confirmation permits planning |
| `subject.repository` | Canonical GitHub owner/repository from verified source metadata; included in subject/request/comment identity and every answer binding |
| `subject.kind` | GitHub comment container: issue or pull_request |
| `subject.number` | GitHub issue or PR number containing that comment |
| `unknown.unknown` | Sanitized explanation of an unavailable fact; never raw tool output |


## Repository roles

The optional `decision_repositories` setting in private service settings names
`public` and `private`, each an exact `{owner, name}` object. The roles must be
valid and distinct under case folding. The reader reads `service/config.json`
in the existing private state directory.
An absent setting/file preserves today's single cwd repository. A malformed or
unreadable setting never falls back. In pair mode, GitHub metadata must confirm
the configured canonical identities and their public/private visibility before
feed reads; a failed role contributes a coverage gap while the other is still
read. Public spec/plan requests and private grill requests stay on their own
role. Each subject, current-source lookup, duplicate check and answer binding
includes its canonical repository; equal local IDs across repositories are
separate identities. Coverage is complete only if every configured feed and its
required source reads are complete. Private request text is never posted on
the public repository.

Repository role names must be ordinary path components; `.` and `..` are refused. Settings are read once, when the reader is set up.

On upgrade, an earlier web answer may be stored under a slot key without a
repository. A matching legacy receipt or composer record blocks answers to
either qualified slot until that earlier record is resolved. Its stored bytes
and operation identity are retained; it is never automatically rebound to a
repository or silently discarded. An unread legacy namespace also blocks the
answer through the existing unavailable presentation. No new send or recovery
route is added.
