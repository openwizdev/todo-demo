# Ops passes, grants and the check's cost

Read this for an ops wake, a builder's narrow path question, or when the check's cache matters.

**What the check costs** (#2543). The spec check uses the scheduler's cached
REST ETags when available. A cache miss triggers a full read. The cache is
an optimization and carries no routing, approval or outcome authority.

## Ops passes (#1456)

An ops wake, a project tick, a spec's fleet thread or an independent standby, is one **finite pass**: it handles due work, records each outcome and ends. Nothing waits awake: no background watcher, waiting poll loop or sleep survives the pass, and delayed work is resumed by a later event or scheduled pass. The former supervised pass runner (`loop.sh --pass` and `--ack`) is removed (#1238): the scheduler's own run limit bounds a pass.

- **One logical owner per spec.** Project and spec paths build the same operation key, and only the current fenced generation's owner may act: `records.py ops-pass` sends every copy through OB3's `resume`, the sole effect boundary, first, so recorded uncertainty stays `reconcile` on the operation's first valid copy whatever its generation; then it refuses a copy whose claim or snapshot is from an older generation, another owner or another fleet (`stale_claim`) and a later copy of an operation already handled (`duplicate`). Stale, mismatched or invalid copies never use up the key of a current copy. Under OB-A1 starts, deliveries, hold releases and merges stay disabled there; a disabled effect is never counted as done.
- **Standby takeover.** A standby outside the PC's failure domain takes over only by admitting the next generation claim through OB3 and reading it back; a timeout or comment is never ownership. It rebuilds work and private routing from durable records, keeps each builder, branch and selected reviewer, reconciles uncertain starts instead of replacing them, and keeps intentional pauses and revocations.
- **Access.** Parent-only reachability (ADR 0011) no longer forces recovery through the orchestrator: record the intent on GitHub; the recipient reads it on its own wake. Never archive or replace a live builder to gain access.
- **Delegated grants.** A builder's narrow same-intent path question is evaluated by the ops agent within the `narrow-grant` rule ([`grants.py`](../scripts/grants.py)), not escalated by default. Contract, interface, dependency, workflow, scope, live, spending, unreadable or ambiguous cases go to the orchestrator, which audits every grant daily.
- **Merges.** A fresh pass verifies the selected reviewer's own output under the existing rule or keeps the merge blocked; under OB-A1 merge stays disabled here.
- **A failed operation** never blocks unrelated due work and never resets a 1 + 1 count.

The project's ops protocol, wake plan and roles stay in its private orchestration state (in ClosedWiz, `private/orchestration/ops-dispatch.md`). Installing or enabling any loop or machine configuration is OB8's separately authorized step.

## The due lines in full

| Line | Do |
| --- | --- |
| `needs-info #N` | Its builder asked a question. A narrow same-intent path request goes first to the ops agent's grant evaluation ("Ops passes", above); otherwise, and for every real exception, tell the orchestrator, with a link to the question, and record `launch-fleet: asked the orchestrator` |
