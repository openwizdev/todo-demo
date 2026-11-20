# OB1 synthetic contract seam

Run only this affected proof:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 skills/launch-fleet/test/ops-protocol/test_protocol.py
```

`examples.json` is synthetic throughout: repository, comments, paths, owners,
assignments, commits, digests, currentness, ACK and transport observations are
invented fixtures. In particular, accepted transport/recipient verification
and complete snapshots are **synthetic assumptions**, not discovered endpoint
capabilities. No live endpoint is called. `AtomicRefs` implements only the
recording create-if-absent seam; it is not external-effect fencing.

`protocol.py` implements offline schema/local-record conformance and pure refusal
stubs named in the contract. It supplies no network/process client, durable
dispatcher, new broker or effect implementation. Its injected `resume` effect
boundary is never called. `admit_claim` injects only the record-storage seam;
callers must verify source completeness and exact commit content themselves.
Downstream tickets implement their own approved handlers using the contract;
they need not import a test directory as production code.

The owning table covers strict shapes/number spelling/duplicate keys,
repository-bound comments, duplicate generation/operation refs, stale/incomplete
claims, missing durable intent, unknown create replies, crash/uncertainty and
the pause-after-ref-check trace, purpose-bound grants, inclusive ON1/newer holds,
and incomplete audit cursors. Every effect stays disabled/refused. P5 remains
Unverified; #2244 Local discovery and OB8 live permissions remain separate.
