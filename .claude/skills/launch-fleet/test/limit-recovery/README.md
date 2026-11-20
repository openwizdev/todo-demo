# TL3 limit recovery (#2338)

```sh
python3 -I skills/launch-fleet/scripts/test-limit-recovery.py
python3 -I skills/launch-fleet/scripts/limit-recovery.py pass < input.json   # {"view": ..., "cases": [...]}
```

`misses.json` holds synthetic open misses in TL2's stage-bench row shape
(`tools/collector/journey-contract.md`, section 10) and the derived pull
request facts the ops agent supplies after complete GitHub reads. Every
snapshot, owner, approval and outcome in the tests is a **synthetic
assumption**; no GitHub, CloudRoom or merge endpoint is called.

## Selection

Only an open (`end: null`), measured (`result: missed`), gap-free miss read
completely can select a helper, and only when the ticket is `ready-for-agent`
with no holding label, the pull request is open, the retained builder is
`idle` since the miss (complete history; `unknown` refuses) and its family is
known (the helper keeps it).

| Missed stage | Facts | Helper |
| --- | --- | --- |
| `fix_after_changes` | Head still the CHANGES verdict's head | `findings-fix` (prior verdict: the key's origin comment) |
| `fix_after_changes` | Newer head, `ci` red | `ci-fix` |
| `fix_after_changes` | Newer head, conflicts with `main` | `conflict-fix` |
| `fix_after_changes` | Newer head, not red, no conflict | none: `no_cause` (no CI or conflict timer) |
| `merge` | Approved head current, conflicts with `main` | `conflict-fix` |
| `merge` | No conflict | none: the merge owner (#2189) |
| `builder_start`, `reviewer_start` | any | none: #1480 |
| `builder_question_answer` | any | none: #1481 |

Unknown CI or conflict state is `unknown_history`, never a guess.

## Recording and the finite pass

1. An eligible miss with no recorded intent returns `record_intent` and the
   proposed ops-dispatch v1 intent: `builder_start` to destination `builder`
   (the helper does builder-role work on the existing branch; v1 has no
   dedicated helper action), assignment `<role>-<16 hex of the miss key>`,
   the exact PR head, and the next sequence. The caller records it on GitHub
   and reads it back. Nothing is dispatched.
2. The same miss read again matches the recorded intent by subject, action,
   destination, assignment, head and prior verdict, whatever the sequence
   counter says, so a later wake reuses it. Two proposals of one miss in one
   pass: the second is `duplicate`.
3. A recorded intent with no admitted operation claim returns `admit_claim`
   (OB3's `admit_claim`, by the caller).
4. A claimed intent goes through #1456's `records.ops_pass` and so OB3's
   `resume`. The effect boundary is never called: complete current evidence
   ends `disabled/unfenced_effect`; a moved head, stale owner, hold or pause is
   refused; any accepted/uncertain transport, completed-but-unverified
   completion or unresolved key on the ticket is `reconcile/uncertain_outcome`
   and nothing is retried.
5. One helper per pull request head across the pass: another helper intent,
   recorded or only proposed earlier in the pass, at the same head refuses a
   second one (`another_helper`).
6. The snapshot's ticket must be the facts' ticket, which must be one of the
   miss's tickets; a recorded intent is reused only under the current dispatch
   rule (`stale_binding` otherwise).
7. Before asking for `admit_claim`, the history is read in OB3's order: a
   duplicate or reused record identity is `incomplete_read`; then an
   unresolved key or an unsettled transport/admission/completion on the ticket
   is `reconcile`; then a same-key record bound to another plan, subject or
   intent is `stale_binding`; and an admitted claim not read back is
   `incomplete_read`. Each refusal is that case's alone.

`counted` is true only for a `complete` result, which needs a verified
endpoint completion; under OB-A1 none exists, so no TL3 recovery is counted.
P5 and any live recovery stay **Unverified**.
