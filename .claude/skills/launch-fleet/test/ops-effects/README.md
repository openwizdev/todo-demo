# OB3 shared effect boundary

Run the owning synthetic boundary suite:

```sh
python3 -I skills/launch-fleet/scripts/test-effects.py
```

`../../scripts/effects.py` implements the `openwiz.ops-dispatch.v1` callable
seams without importing OB1's test implementation or changing the mechanical
fleet-tick wire format. The tests reuse OB1's synthetic examples and recording
storage. All snapshots, owners, approvals, recipient verification and historical
transport/outcome records are **synthetic assumptions**, not observed endpoint
capabilities. Tests call no GitHub, CloudRoom or merge endpoint.

| Callable | Input and outcome |
| --- | --- |
| `read_record(raw)` | Strict JSON/schema and local record semantics; malformed records raise ValueError. No approval or source authentication. |
| `read_comment(body, container)` | One JSON fence, bound to actual repository/subject kind/number supplied by the collector. |
| `operation_key(intent)` / `claim_ref(claim)` | The exact OB1 canonical identity and disjoint generation/operation reference namespaces. |
| `admit_claim(claim, snapshot, record_commit, create_if_absent)` | One injected record-storage attempt only. Returns admitted, duplicate, stale, refused, reconcile or uncertain. No update/delete or retry. |
| `resume(intent, claim, history, snapshot, effect_boundary)` | Reconstructs one schema-valid result with `next: end` and `effects: []`. The supplied effect callback is **never called**, for any action or snapshot. |

Consumers #1456/#1480/#1481/#2112 call this boundary from their own owned paths.
#2190 consumes its explicit disabled/refused/reconcile results. This module does
not collect GitHub pages, resolve private routes, authenticate reviewer output,
implement a new planner or install a runner. The consumer must obtain complete
authorized source reads, check the complete current approval/table/native
blockers/Relies on and applicable rules, and bind record IDs/timestamps/content
to immutable source metadata. A JSON `complete` or recipient-verification flag
alone proves nothing. Duplicate or conflicting immutable identities refuse.

Before `admit_claim`, the collector must read the whole generation namespace,
validate max+1 and the unique current owner, and verify that `record_commit`
contains the exact reviewed `ops-record.json`. Admission is not a durable lease.
After creating a reference, read its commit/content and current generation
history back; persist the contract admission event before relying on it.
`exists` means duplicate, never a new owner or permission to act. An unknown
reply, or interruption before the admission save, requires ref/content read-back
on a later finite wake, not another create. Until that read is complete, retain
an incomplete snapshot; for an unsettled operation retain its uncertain key.
The pure handler cannot supply durable persistence on a caller's behalf.

Before `resume`, read the verified durable intent, claims, admissions, transport,
ACK and completion history, including older approvals/heads/generations and
unresolved keys for this logical ticket. Record the returned result and end.
Do not retain a callback/token to execute later. Re-enter `resume` with newly
read current sources after takeover: an obsolete generation/owner is refused.
Uncertainty precedes stale-current checks. Accepted/uncertain transport,
unresolved admission and purported completed/non-executed outcomes remain
`reconcile/uncertain_outcome`; no discovered endpoint lookup authenticates them.
Neither ACK, later refusal, lease expiry, missing branch, supersession nor a
replacement operation key proves that an old builder did not start. Preserve
its branch, assignment, pause/revocation and existing correction counts.
Uncertainty from another ticket does not become a repository-wide lock.

All effects remain disabled under OB-A1, including starts, deliveries, releases,
merges, grants and audits passed to `resume`. Record admission cannot enable an
external call. No caller field, configuration switch, same-account APPROVE or
synthetic endpoint can enable one. Exact-head review, actual selected-reviewer
own-output authentication, required CI, approval, M1/re-test and verified merge
read-back remain necessary; a serialized real merge executor cannot be claimed
until its actual door enforces the generation and operation. No new endpoint,
broker, dependency or access is implemented. New enforcement/access needs a
hold-first amendment; #2244 discovery and OB8 live authority remain separate.

P5 and live availability/reconciliation remain **Unverified**. The pause/resume
proof establishes a local refusal with zero calls, not an external stale-request
rejection. Historical interruption cases prove that uncertainty is retained,
not successful endpoint recovery. Every pass records and ends; there is no
watcher, waiting poll loop or sleep.
