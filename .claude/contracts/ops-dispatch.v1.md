# Ops record and claim contract v1 (`openwiz.ops-dispatch.v1`)

OB1 (#2187), spec #2185 revision 3. Jake, 2026-11-10: OB-A1 permits
GitHub-first records and atomic create-if-absent claims, with unsupported
effects disabled ([private record](https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6759599541)).
The [schema](ops-dispatch.v1.schema.json) and
[synthetic reference handlers/examples](../skills/launch-fleet/test/ops-protocol/)
fix the shape for downstream implementations. **Only records, claim admission
and effect refusals may be certified here. P5 remains Unverified.** No new
enforcing endpoint, credential, broker, dependency, loop or live effect follows.

## Boundary and routing

One GitHub issue/PR conversation comment contains one record in exactly one
column-zero `json` fence (three backticks). Extra/malformed fences, duplicate
wire keys, unknown versions/kinds, missing/extra fields, positional objects,
wrong types and ambiguous histories confer no authority. Decode one strict JSON
object; refuse floating-point spellings, NaN/Infinity, booleans as integers,
and integers outside 0..9007199254740991 (positive where the schema requires).
All object keys in the schema are required; explicit null means absent, never
unread. Arrays preserve order. Schema validity is structural, not an approval.
Cross-record and source checks below are mandatory in addition to the schema.

The collector binds `repository` and `subject` to actual GitHub metadata, checks
the current spec revision/fingerprint/complete approval table, native blocker
merges, Relies on and all applicable gates. A self-described `complete`, evidence
class, owner, approval or cursor in JSON cannot replace those reads. Unread or
partial pages produce a gap; never infer absence. Record creation time/identity
must agree with source metadata, not the order comments happened to arrive.

Records on either repository use public forms under
[open development v1](open-development.v1.md): technical summaries and synthetic
fixtures, never thread IDs, session payloads, machine paths, account/host details,
credentials or exact private answers. `owner`/`assignment` are opaque record/span
aliases, not CloudRoom identities. Resolve private routes by repository/ticket
or repository/PR/original review head in private state, preserving selected
reviewer spans. Exact evidence stays private; public evidence names a decision
and its verified private-comment pointer. No route is accepted from a public
record. Unknown repository visibility uses public rules.

An evidence entry is `{evidence_class, source, digest}`. `source` is a synthetic
`fixture:` locator or a verified GitHub issue/PR comment pointer; `digest` binds
the reviewed evidence. `fixture`, `observation` and `review` remain distinct.
A fixture cannot establish an observed capability; a shared-account comment
cannot authenticate the selected reviewer's own output. Evidence location,
current content, authority and completeness need independent source checks.

## Common record fields

All durable variants except `snapshot`/`result` have these fields:

| Fields | Source and meaning |
| --- | --- |
| `schema`, `kind` | Version constant and exact variant tag |
| `id`, `created_at` | Unique immutable repository record identity and source creation time in milliseconds; append events instead of editing history |
| `repository`, `spec`, `ticket`, `subject` | Verified repository, parent spec, work ticket, and `{kind: issue or pull_request, number}` container; audit/spec-generation records may use the spec as their work ticket |
| `operation_key` | Stable operation identity; zero digest sentinel for non-operation records and generation claims |
| `approval` | `{revision, fingerprint, comment}` of the complete current approved plan; existing revision-v2 fingerprint, never a new envelope/grant hash |
| `rule` | `{name, revision, comment}` of the actual governing rule; revision binds its operative wording and identity/source |
| `evidence` | Nonempty ordered evidence list with source checks above; neither a label nor free-form prose is evidence of delegated authority |

Record identity is `(repository, id)`. Conflicting reuse, edited immutable fields,
duplicate source IDs, contradictory decisions or incomplete history refuse the
affected item. Events bind their intent by both `intent_id` and `operation_key`,
and preserve repository/spec/ticket/approval and the appropriate assignment/head.
An event for another identity never settles this operation.

## Intent, delivery and completion

An `intent` is also the pending notification; there is no second pending queue
record to lose. Its additional fields are `action`, `destination`, `assignment`,
`prior_verdict`, `head`, `sequence`. Actions: `builder_start`, `review_start`,
`delivery`, `hold_release`, `merge`, `grant`, `audit`. Destination is a role, not
a route. A review/recheck retains the selected reviewer assignment and prior
verdict; a head change requires fresh exact-head review and a new operation.
`sequence` is positive, allocated once per ticket/approval in source order;
duplicate/conflicting sequence allocation refuses. Do not deliver later items
past an unresolved earlier item. Superseded work is ignored for execution but
keeps any unresolved external outcome visible for reconciliation.

Intent evidence binds the complete existing planner action/arguments and actual
configured provider/model/effort/tier selection. Consumers recheck those sources,
actual builder family and selected-reviewer continuity; this record grants no
model substitution or start. The assignment's fresh exact-head review rule
still applies independently of an intent's structural validity.

The operation key is SHA-256 of UTF-8 `openwiz.ops-operation.v1` plus LF, then
canonical JSON containing **only**, in sorted-key order: `repository`, `spec`,
`ticket`, `subject`, `approval`, `action`, `destination`, `assignment`,
`prior_verdict`, `head`, `sequence`. Canonical JSON recursively sorts keys,
preserves array order, uses no whitespace, raw Unicode, standard JSON escapes
and decimal integers. No owner/generation/time/random salt: retries, duplicate
wakes and project/spec ticks must identify the same work. The worked synthetic
intent's key is `122291124bad25e809fe86f73c91b3293f634593f3ea325c8a69a82942ca64a3`.

| Event | Additional fields and transition |
| --- | --- |
| `transport` | `intent_id`, `generation`, `state`, `attempt: 1`, nullable `receipt_digest`. States: not_attempted, accepted, refused, uncertain. Record intent and claim first; never infer acknowledgement/completion from accepted transport. Receipt payload/routing stays private. |
| `ack` | `intent_id`, `recipient`, `assignment`, `sequence`, nullable `checked_head`, `checks_digest`. The intended recipient independently reads/checks the pending intent and current authority, then records the same key. Verify recipient own-output/assignment evidence; another same-account comment is not acknowledgement. |
| `completion` | `intent_id`, `generation`, `state`, nullable `superseded_by`, nullable `result_digest`. States: completed, superseded, uncertain, reconciled_not_executed, disabled, refused. Exactly superseded requires its successor key. Completed requires verified endpoint result, not an ACK. |

A crash before an effect leaves pending/disabled work; a crash after dispatch,
lost reply or missing outcome after accepted transport leaves **uncertain**
work. Later failure/refusal, generation expiry, ACK, branch absence or a new
tick cannot lower uncertainty. Retry/replacement needs complete operation-bound
endpoint proof of completion or non-execution and still-current authority; no
such lookup is established here. Preserve live builder/branch/reviewer and
intentional pauses/revocations. Current stubs return `reconcile` and end even
for purported historical completed/non-executed records: they cannot authenticate
those endpoint claims. #2244 owns the unstarted Local discovery; it is not
performed or replaced by fixture assumptions.

## Atomic record/claim admission

A `claim` adds `scope`, `generation`, `previous_generation`, `owner`, nullable
`intent_id` and `ref`. Generation is positive and exactly previous+1. The logical
fleet namespace is repository+spec, shared by project/spec tick paths. Read the
complete immutable generation history before proposing max+1; a partial read
does not select an owner. The current record generation is the highest complete
valid admitted generation, with its unique owner; lower generations cannot
become current. Conflicting/missing generation history refuses. A newly created
claim must be read back with its commit content and current history before any
consumer relies on it; admission is not a durable lease or external ownership.

Reference names, scoped by the repository containing them:

```text
refs/heads/openwiz-ops/v1/s-<spec>/generations/g-<generation>
refs/heads/openwiz-ops/v1/s-<spec>/operations/g-<generation>/k-<operation_key>
```

These namespaces avoid Git's reference file/directory collision. Generation
claims use a zero operation key and null intent. Operation claims use the
current generation/owner and one verified read-back durable intent with the
same key/binding. Their previous_generation is generation−1, not a second
takeover attempt. Reject uncertain operations before admitting any replacement
operation claim, even under a new generation. Per-generation uniqueness alone
does not deduplicate cross-generation external effects.

`snapshot.uncertain_keys` covers all unresolved operations for this logical
ticket, including older approvals/heads/generations. Until actual endpoint
evidence resolves them, the stub refuses further operation admission for that
ticket; changing a key cannot create a replacement. Independent tickets may
continue and new intents can still be recorded. Generation-record admission
alone never settles an old operation or transfers a live builder's work.

Use only atomic **create-if-absent**, pointing to a reviewed immutable Git commit
whose `ops-record.json` is the exact claim. Record object SHA and canonical
record digest in private source evidence, verify content/ref/read-back binding,
and reject arbitrary commits. Do not rewrite, force, delete or reuse operational
claim refs; the historical bounded throwaway probe is not an operational API.
`exists` is duplicate/refused admission, never permission for a second claimant;
reconcile its exact content when needed. An unknown create reply is uncertain:
read back on a later finite wake, do not blindly issue another create. A read
failure never proves absence. The generation and operation refs each arbitrate
only that record, not an atomic multi-ref or multi-system transaction.

An `admission` event records the attempt independently: common binding plus
`claim_id`, `generation`, `ref`, `record_commit`, and `state` (admitted, duplicate,
stale, refused, reconcile, uncertain). Bind it to the exact claim/source response;
do not invent admitted from a local intent or treat duplicate as new ownership.
Save uncertain attempts before ending so a later wake does not issue another
create. A missing admission event is unresolved until the ref and content are
completely read back. This event is evidence, not an external-effect token.

The observed probe established sequential duplicate-create refusal and
ancestry-constrained updates. A non-forced update is **not** expected-old-SHA
compare-and-swap; neither update nor ref creation fences a later effect.
All production storage/collection wiring remains with the consuming tickets.

## Unfenced effects and finite handlers

All new ops starts, reviewer starts/rechecks, deliveries, hold-label releases
and merges remain **disabled**. No configuration flag, successful claim,
`fenced: true` field, agent judgment, expiry or same-account approval enables
one. The schema has no enable flag and the reference stub never invokes its
effect callback. A stale owner paused after a successful ref check and resumed
after takeover returns refused/disabled with no effect; this is a refusal
fixture, **not** proof of an external endpoint rejecting a stale request.
Live P3–P5/P7 and actual enablement retain separate gates; P5 stays Unverified.

The offline callable seam is defined in `protocol.py` beside the examples:

| Handler | Input/output; no unlisted effect |
| --- | --- |
| `read_record(raw)` / `read_comment(body, container)` | Strict schema/local semantic validation; actual container is repository, subject kind, number. Invalid input raises ValueError; no I/O other than reading the checked-in schema. |
| `operation_key(intent)` / `claim_ref(claim)` | Pure identity/name functions fixed above |
| `admit_claim(claim, snapshot, record_commit, create_if_absent)` | One injected **record-storage** attempt only; admitted, duplicate, stale, refused, reconcile or uncertain. Caller supplies verified commit content/source snapshot; timeout/unknown response never retries. No update/delete/effect callback. |
| `resume(intent, claim, history, snapshot, effect_boundary)` | Validates complete inputs and returns a `result`; the effect callback is never called, including for grant/audit intents. Denial priority: uncertainty, incomplete/current binding, stale claim, pause/revocation/gates, supersession, ordering, disabled. |
| `grant_current(grant, snapshot)` / `on1_current(record, snapshot)` | Pure equality/completeness checks of record material, not agent scope decisions, source authentication or edit/release authority |
| `audit_cursor(report)` | Proposed end cursor only for a complete monotone report; otherwise exact start. Caller saves only after complete source/report read-back. |

`result` fields are `schema`, `kind`, `operation_key`, `intent_id`, `state`,
`reason`, `next: end`, `effects: []`. States/reasons are exact schema enums;
there is no executable pending callback. Every finite pass records its result
or unresolved operation and ends. Later events/scheduled passes resume it;
no watcher, poll loop or waiting sleep and no reset of review-round counts
(one review plus one re-check, then at most one fresh round).

`snapshot` is **private derived execution data**, never a public attestation or
record to post. Its schema fixes repository/spec/ticket/current approval/head,
generation/owner, complete-read status, unresolved keys, pause/revocation, exact
hold IDs and other gates, inclusive cutoff/change inventory/history digest,
next sequence, independently verified recipient status, material/current rule,
read-back intents, producer and all consumer bindings. Each value must come
from authorized complete source reads; caller-supplied booleans cannot certify
an endpoint. The stubs validate shape and refuse effects even for a purportedly
verified snapshot. Downstream owners implement actual source authentication,
pagination, cursor persistence and handlers; fixtures do not provide them.

## Supporting envelopes and grants

`envelope` adds `paths`, `supporting`, `material`, `protected`. Each exact path
entry is `{path, purpose, criterion, shared_section, owner_ticket}`. Canonical
repository-relative paths only: no empty, dot, parent, absolute, glob or alias
components. Check resolved files, both sides of renames, shared sections, active
owners and complete mixed diffs. Supporting entries must serve the approved
criterion/owned behavior and be explicitly covered by this approval/standing
rule. Never retrofit an old graph. `protected` always includes contracts,
interfaces, dependencies, workflows, live, spending and self_authorization;
a supporting filename supplies none of those permissions. #2243 owns the plain
instruction slice; #2188 owns the contract-shaped integration.

`grant` adds `grant_id`, `envelope_id`, exact `paths`, `material`, `status`,
technical `reason`, nullable `supersedes`. Status: granted, refused, uncertain,
revoked, completed, replaced. A decision is an agent's assessment of the actual
diff, intent, criterion, current rule and ownership, never a filename heuristic
or builder self-approval. A grant authorizes only the listed purposes, never
the resulting implementation, review, merge, policy/parser that authorizes
itself, new contract/interface, workflow, dependency, live action or spending.

`material` fixes digests of `intent_digest`, `evidence_digest`,
`ownership_digest`, `purpose_digest`, `rule_digest` (the operative rule revision).
The grant's current operative rule is `narrow-grant`; an otherwise identical
dispatch/ON1 rule cannot supply grant currentness. ON1 evidence likewise binds
the current `on1` rule, including its revision and source comment.
Source readers recompute these from complete relevant approved intent/evidence,
owners and exact path/purpose/criterion lists; copied asserted digests are not
verification. Changed approval, operative rule, intent, relevant evidence,
ownership or purpose invalidates until reassessed. A head-only change does not
erase purpose authority but always expires prior implementation review.
Completion/revocation/replacement ends the grant; append a new event/identity
and preserve the stable grant_id/history. Grants/envelopes supplement the
**unchanged** revision-v2 plan fingerprint, checked separately. Changed approved
outcome/body/title/native link goes through hold-first reapproval instead.

## ON1 evidence and inclusive cutoff

`on1` is evidence, not a label-release instruction. It fixes:

| Field | Source |
| --- | --- |
| `producer` | Approved ticket/approval, verified merge and actual contract-delta digest |
| `consumers` | Every affected ticket's current approval, unchanged scope/effective-path digests including valid grants, Relies on and link-check digests |
| `cutoff` | Start and inclusive end commits, complete-read flag and every declared-contract change through end; changes include commit, current path, nullable previous path, producer and affected consumer tickets, including renames/deletions |
| `hold` | Exact contract-hold comment, ON1 owner and complete history digest, never only current labels |
| `other_gates`, `competing_claims` | Full remaining gates and unresolved competing release records; any one prevents release |
| `revision_record` | Existing validated complete plan-revision record/table before label changes |
| `verification` | Pre-effect evidence digest, nullable later evidence/label read-back digests and full-history status; null later fields mean pending verification, not success |

Gate affected unstarted consumers before advancing any cutoff; notify running
consumers through recorded work. Assess every outstanding declared change
through the inclusive new cutoff, not only its triggering merge. Preserve all
other gate owners/native blockers. Re-read complete cutoff/history after
recording and immediately before any future effect; newer holds/changes,
missing pages, changed consumer material, invalid grants or partial labels
block readiness. Delayed verification records/ends for another wake.
An optional/additive field alone is not evidence. ON1 delegates only evidenced
unchanged-scope applications; C2 remains orchestrator-only, CT1/factory-skill/
red-main authorities keep their own bounds. This version still disables the
actual release effect even when an ON1 record is current.

## Audit cursor and report

`audit` adds `start`, `end`, `complete`, `entries`. A cursor is
`{created_at, comment}`; compare lexicographically, read **after** start and
**through** end, including all records tied at the cutoff time. No backwards
movement. Each entry fixes operation key, decision (granted/refused/uncertain/
revoked/completed/replaced), nullable grant and final-diff digest, and remediation
(none/revoke_and_hold/escalate). Include invalidations/refusals/uncertainty,
not just successful grants. Missing final diff is explicit null, not omission.
Complete source pages and every operation in that interval must be covered;
an unread page retains the old cursor. Persist the report/read-back before the
cursor. Daily retrospective audit is not synchronous grant approval; invalid
grants are revoked and affected work held through existing authority, never
by inventing an enabled effect in these stubs.

## Consumer ownership and compatibility

| Consumer | Interface; implementation remains in its approved owned paths |
| --- | --- |
| #2188 | envelope/grant/material/audit and inbox rules; grants.py and skill integration |
| #2189 | generation/operation admission, resume/result refusals; effects.py. Client-owned paths cannot claim an external fence. |
| #1456 | snapshot/finite result/private routing contracts; records.py/loop.sh and bounded skill/settings sections |
| #1480 | intent/claim/transport/result; ops-starts.py keeps starts disabled |
| #1481 | pending intent, order, transport/ACK/completion and review span; approved inbox files, not the existing collector implementation |
| #2112 | on1/material/full cutoff/hold evidence and disabled release; approved on1.py and hold predicates; #2218 keeps its regression |
| #2190 | schema evidence/result and honest disabled/Unverified outcomes; kit/result consumers, with #2219 controls and #2244 discovery separate |

Paths were checked against revision 3; these are record/refusal seams only,
not endpoint adapters or unavailable behavior implemented in another owner's
files. Current [mechanical tick v1](fleet-tick.v1.md) remains its existing
private envelope/API. This schema is separate and does not change its wire
fields or implement Rust parity. A mechanical due item is a candidate; an agent
applies authorized judgment and records a refusal when evidence/authority is
missing. Approval currentness, other applicable review selection (including
the assignment's exact-head review), CI, M1/re-test, verified merge, the
review-round limit (one review plus one re-check, then at most one fresh
round), privacy and every live/machine/activation/spending/release/publication gate stay.
