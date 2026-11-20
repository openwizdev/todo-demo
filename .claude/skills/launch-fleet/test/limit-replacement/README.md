# TL4 owner replacement after two misses (#2339)

Run the owning synthetic proofs:

```sh
python3 -I skills/launch-fleet/scripts/test-limit-replacement.py
```

`../../scripts/limit-replacement.py` is one finite pass, `check(bench, sources,
snapshot, intent=None, claim=None, history=(), effect_boundary=None,
limits_path=<limits.conf>)`. It returns a report to record, and then the pass
ends. It has no network or process client and no enable switch.
`effect_boundary` is never called. Retirement and start stay **disabled** under
OB-A1 even when every check passes. P5 and live replacement remain **Unverified**.
The fixtures, owners, approvals and outcomes are synthetic assumptions, never
observed endpoint capabilities.

## Inputs

| Input | Source |
| --- | --- |
| `bench` | TL2's `stage_waits` object (`closedwiz.journey.stage-bench.v1`, `authority: none`), checked for internal agreement: each miss is a `missed` wait, every key appears once, and each wait's limit is the bench's setting |
| `limits_path` | TL1's settings, read once through `limits.py`. A bench measured against other limits is refused. An unreadable or invalid file raises, as `limits.read` does |
| `sources` | Private reconciliation reads by the ops agent. Exact keys: `complete`, `ticket`, `overload` (`clear`/`paused`/`unknown`, the CS5 durable pause state), `recorded_misses` (miss keys that earlier passes recorded for this ticket), `incumbent` {`assignment`, `family`, `branch`, `head`, `activity` (`stopped`/`running`/`unknown`), `worktree` (`clean`/`handed_off`/`dirty`/`unknown`)}, `reviewer` {`assignment`, `family_conflicts`, `correction_rounds`} |
| `snapshot`, `intent`, `claim`, `history` | ops-dispatch v1 records, decoded by OB3's strict reader. The intent and claim are given together or not at all |

## Decisions

- **Misses.** A miss counts against the owner only in `OWNER_STAGES`
  (`fix_after_changes`, the builder's own wait). A miss counts only once for
  each bench key, so repeated observations and folded records of one overdue
  interval are one miss. Earlier recorded misses are kept and joined to the
  fresh bench, so a later tick never resets the count. With fewer than two,
  the decision is `none`, and an intent is refused as unevidenced.
- **Order of refusals.** Checks run in this order, and the first failure decides:
  1. **Uncertainty** (`reconcile`): an unresolved key, an unsettled transport,
     completion or admission on this ticket, or an earlier `builder_start`
     intent on this ticket without a `disabled`, `refused` or `superseded`
     completion. A purported completed or non-executed start stays uncertain,
     because no endpoint lookup authenticates it yet.
  2. **Incomplete reads** (`incomplete_read`), including the incumbent's
     activity or uncommitted work being unread.
  3. **Holds, gates, pause, revocation and the CS5 overload pause**
     (`paused_or_revoked`).
  4. **Binding** (`stale_binding`): limits that are no longer current, fewer
     than two misses, a live incumbent, uncommitted work not handed off, or a
     branch head that moved since the incumbent was read.
- **Intent first.** With no intent, a passing pass returns `record_intent` and
  a `proposal`: a `builder_start` to `builder` at the current head. Its
  evidence digest binds the ticket, branch, head and incumbent span. The agent
  records that intent, reads it back and ends. A pass that finds the same
  selection already recorded returns `duplicate`.
- **One writer.** The intent must bind this exact replacement, with a new span
  that is neither the incumbent's nor the selected reviewer's. Among recorded
  claimants for the same selection, the lowest sequence wins, and every other
  claimant is `duplicate`/`record_only`. A changed head is a new selection,
  which waits until the earlier one has settled. OB3's `resume` then decides
  the generation, ordering and effect. The best outcome is
  `disabled`/`unfenced_effect`.
- **Selected.** A `disabled` report carries the `plan` and four `gaps` for
  Jake: retirement, start, lookup and fencing. The `plan` holds the same
  branch and head, the span to retire, the replacement span, the unchanged
  selected reviewer and correction rounds, and the family conflicts. The
  family conflicts include the incumbent's family, because its code stays on
  the branch. An `unknown` family keeps reviewer assignment waiting. No reviewer
  substitution, permission, model change, CI, live or spending authority follows.

## Seams

The report's `misses` and the recorded intent are the durable miss and action
records that later passes feed back as `recorded_misses` and `history`. TL3
(#2338) keeps the single-miss helper recoveries. #2244 discovery and OB8 own
any actual retirement or start boundary, which needs a hold-first amendment
before this module may report anything but disabled.
