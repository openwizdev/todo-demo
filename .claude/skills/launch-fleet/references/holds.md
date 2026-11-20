# Contracts and ordering holds

Read this for a `note`, `release`, `reconcile release` line, or to add a hold.

## 5. Contracts

A ticket's **Relies on** line names contract files for its builder. Review handles changes to those contracts. An edit, rename or deletion on the default branch can produce an informational `note #N` for a running builder. Tell that builder which files changed in which pull request and record `launch-fleet: noted #<P>`. A newly created file produces no note. A relied-on file change never puts a ticket on hold.

Existing contract holds keep their recorded release conditions. See [the legacy contract hold procedure](../../to-tickets/changes.md).

### Conditional ordering holds

An unstarted builder ticket may be held **only for ordering**, under its existing
approval. Put `held` on and remove its ready label first, then append exactly
`launch-fleet: held for ordering: issue #B merges to main` or
`launch-fleet: held for ordering: PR #P merges to main`. Record this only when
that merge is the entire release condition. Manual, contract-reapproval,
production/live and mixed conditions keep their own release evidence; never
convert one merely because a dependency closed. A later hold record or a newer
`held` label event defeats the older ordering record's ownership. Missing
ownership evidence leaves the ticket held.

To add a manual or live gate, append `launch-fleet: held manual: <why>` or
`launch-fleet: held live: <why>`, including when `held` is already on and no new
label event occurs. Keep `held` on and remove its ready label. These records
supersede ordering-only ownership; a prerequisite merge does not release them.
Their owner must supply and verify their own release evidence before relabelling.
A later plain comment whose first line mentions a hold or being held also defeats
ordering ownership, including qualified `Orchestrator (ops):` instructions and
case variants. Treat that ambiguity as another gate to resolve, not permission to
release. Plain prose never grants ordering release authority: the legacy release
parser remains the exact unqualified form below.

For old ordering holds only, the check also recognizes the narrow first-line form

```text
Orchestrator: **held for ordering only; the plan and its approval are unchanged.** #B ... Released (`ready-for-agent` back, `held` off) as soon as #B merges.
```

The same issue must occur at both ends. This is a legacy reader, not a number-specific
exception. An already manually released ticket gets no second release action.
Use the structured record for new holds.

The full check after a merge, the safety net, or a wake naming the held ticket
reassesses it. A dependency-only wake does not discover reverse relationships.
An Issue must be closed by a verified default-branch merge; a PR must itself be
merged into that branch. The check also requires the current plan fingerprint
(and agreement with the plan snapshot it read), every remaining native blocker,
no manual/live gate, no existing builder/open PR and
ordinary role/claim safeguards. Standalone tickets still need their own approval.
The release action names the ordering hold comment id C; release never spawns.

1. **Claim the release.** Append `launch-fleet: release starting C`
   to #N. Run `sh "<this skill's folder>/scripts/fleet.sh" claim N <your comment id>`.
   Only `go #N` may act: this rereads ownership, current approval, merges and all
   other guards and elects the oldest claim. On `withdraw`, edit your claim to
   `launch-fleet: release withdrawn C`; change no labels.
2. **Verify, relabel, read back.** Run that claim check again immediately before
   changing labels; require `go #N` again. Restore the configured ready-for-agent
   label and remove `held` with `gh issue edit`. Read the ticket, comments and
   label timeline back: the exact hold must still be the authorized owner, with
   the ready label present and `held` absent. Then edit your claim to
   `launch-fleet: released ordering C`. A separate later `start` line still uses
   the ordinary builder claim protocol. Do not start from a release line.
3. **Lost reply or partial labels.** Leave the claim as `release starting` while
   any outcome is unknown. An unresolved release blocks starts even if `held`
   disappeared. After 10 minutes the check prints `reconcile release`: read the
   claiming thread, the labels, timeline and current hold/approval evidence.
   A completed authorized relabel edits that same claim to `released ordering C`;
   prove that before recording completion. Only a proven failure with no label
   changes and no live sender may edit it to `release failed C: <why>` for retry.
   Partial changes, a newer/different hold, an active sender or unreadable evidence
   stay claimed and go to the orchestrator. Never blindly repeat the relabel.

## The due lines in full

| Line | Do |
| --- | --- |
| `release #N` | The user approved it again since launch-fleet's old contract hold (their approval or a C2 record in its form; a machine revision never releases a contract hold): take its `held` label off (`gh issue edit <N> --remove-label held`). It starts on a later line. Only launch-fleet's holds are released here, each once: a `held` label put on after launch-fleet's hold (by `to-tickets`, which takes its own off) is never launch-fleet's |
