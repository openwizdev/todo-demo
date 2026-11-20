## Changing an approved graph

Any change to the plan after an approval needs a new approval, by the checks of [to-tickets step 4](SKILL.md#4-approve-by-the-checks): a ticket added or dropped, an arrow added or removed, or an edit to the spec's body or to a ticket's title or body. **Hold first, then change,** so the five-minute loop never starts a changed ticket under its old approval, even if it checks between two of your steps.

1. **Hold the tickets the change touches.** Put the `held` label on each one that has no builder yet and take its ready label off, in one edit, then read the labels back and check: `held` on, the ready label off. `held` is the fleet's label for a held ticket (`docs/agents/fleet.md`); if the project has none yet, create it once first (use the tracker commands). The tickets it touches:
   - each ticket whose title, body or arrows will change, and each one you will drop;
   - for a change to the spec's body, every ticket of the spec that has no builder yet.

   If you can't tell whether a ticket has a builder, hold it anyway: the labels only decide whether a builder may start, so holding a running ticket stops nothing.
2. **Tell the running builders.** A ticket already being built keeps going: tell its builder what will change, in a comment on its ticket. For a change to the spec's body, tell the builder of every running ticket of the spec.
3. **Then change the plan on GitHub** (use the tracker commands), with a `## Links` line for every arrow the change adds and no line left for an arrow it removes. A new ticket gets no label. A dropped ticket leaves the spec, loses its `held` label if it has one, and is closed, with a comment saying why: only a merge closes a ticket that stays in a spec.
4. **Post what changed** on the spec: that part of the picture, and the changed rows.
5. **Approve it by the checks** as in [to-tickets step 4](SKILL.md#4-approve-by-the-checks), with the next revision number and `--changed`. A refusal releases nothing: fix and check again. Only after the record reads back, release each held ticket in one edit, its ready label back on and `held` off, label the new ones, and read the labels back.

From step 3 until the new approval, the fingerprint no longer matches, so `launch-fleet` starts nothing under the spec. The hold covers the moments before that, and any loop that only looks at labels. Its `held` label also tells the fleet's view that the ticket is held, not unapproved.

**An existing contract hold.** Review handles new changes to relied-on files. For a ticket already held by an older `launch-fleet` ("contract changed: re-approve"), check that it has `held` and no ready label (fix either, and read them back), read what changed, and, unless it is a wording-only change (next), update the ticket if it needs it and ask the user to re-approve just that ticket. Record it as above, then release it as in step 5, its ready label back on and `held` off: the new revision is what releases the hold.

**A wording-only change (C2).** Jake, 2026-11-05: the orchestrator may assess and release wording-only contract holds under a standing approval (read the configured private standing-approval record). A merge that only rewords a contract, changing no route, field, status, header, bound, limit, write rule or approval rule, needs no re-approval from Jake. Only the orchestrator, never a tick, decides this:

1. **Read the exact contract diff** of the merge the hold names, its contract files only (`gh pr diff <P>`).
2. **Classify it:** wording-only, or an interface or behaviour change. Unsure, mixed or any doubt counts as an interface or behaviour change (fail closed): ask Jake to re-approve, as above. A ticket whose body needs any edit always goes to Jake, however small.
3. **Post the assessment** on the ticket and on its spec: the merge, the contract, the changed lines quoted, and why no ticket changes, then the line `**Released under Jake's standing approval for wording-only contract changes (C2, 2026-11-05)**`.
4. **Hold first, then check the whole cutoff.** The new approval can answer existing contract holds across the whole spec, or on the ticket approved on its own. Before recording it, gate every ticket in that scope that has a Relies on line and no builder yet, whatever its labels: `held` on and its ready label off, in one edit if either differs, then append `launch-fleet: held manual: C2 check of spec #<S> before its new approval` (for a ticket approved on its own, `#<S>` is that ticket), and read the labels and comments back. The check starts no held ticket, and this newer hold record takes any older ordering hold's release away from the check, so nothing under this gate can start or get its ready label back until step 7. A ticket with an unresolved `launch-fleet: release starting` claim, or one that doesn't read back gated: record nothing and take it to Jake. Then list every merge since the latest approval (`FROM`, its `createdAt`; `TO=9999-12-31T23:59:59Z`) and read each one's files with the commands below, and assess as in steps 1 to 3, for every ticket that relies on it, each merge that edited, renamed or deleted a file matching any Relies on line of those tickets, by its new name or its old one; a ticket being built gets launch-fleet's `note` first. Any change that is not wording-only, needs a ticket edit, or a list or file read that fails or errors (its files not read in full, or a rename without its old name): record nothing and release nothing, leave the approval and every hold as they are, and take it to Jake.
5. **Record the approval the check reads:** first read back the private comment holding Jake's standing approval for wording-only contract changes (C2, 2026-11-05), identified above, and verify its words and scope. Use that verified comment's full URL for the immediate `Private record:` line in either public form below. Write a paraphrased decision naming the standing approval, never its exact words. Name every merge step 4 assessed.

For a spec's ticket, take the next revision as in [the approval procedure](SKILL.md#4-approve-by-the-checks) (the same plan: the fingerprint must still match the latest approval's). Keep the complete table, matching fingerprint and revision text, and the Changed-since statement:

```md
**Plan graph approved by Jake, <YYYY-MM-DD>, revision <N + 1>:** approved under Jake's standing approval for wording-only contract changes (C2, 2026-11-05).
Private record: <the verified private-comment URL for the C2 standing approval>

Changed since revision <N>: none; released under C2 after the wording-only changes in #<P>, #<P>.

<the complete approval table, matching fingerprint and revision text>
```

For a ticket approved on its own, retain its brief, owned paths and Relies on, and name every merge step 4 assessed:

```md
**Approved on its own by Jake, <YYYY-MM-DD>:** approved under Jake's standing approval for wording-only contract changes (C2, 2026-11-05).
Private record: <the verified private-comment URL for the C2 standing approval>

<every assessed merge; the brief, owned paths and Relies on>
```

6. **Re-check up to the record.** Read the record back; once its read-back has its `createdAt`, and no sooner than a minute after that time (so a merge GitHub is still recording is listed), list the merges again with `TO` set to it (including merges at that second) and read every new one's files: every contract merge up to the cutoff must be one the record names. Any other, or a read that fails or errors: release nothing, keep every step-4 gate in place (put `held` back on any ticket the check has since released, its ready label still off), give running builders the note, and take it to Jake, naming the merges the record covers unassessed: only his re-approval releases those tickets. The cutoff bounds this C2 assessment. The fleet uses current re-approval and recorded hold ownership to release an existing contract hold. Later merges do not veto that release.
7. **End the gate.** Before either release or restoration, reread the complete hold history, labels, ownership and each hold's release evidence. Identify only this operation's C2 gate by the exact comment id read back in step 4, never by its text alone. Every other gate, including another C2 check's, keeps its own owner. If history, ownership or release evidence is incomplete or ambiguous, keep the ticket gated and take it to Jake. A newer unresolved non-C2 hold remains authoritative: append no older hold record over it and restore no ready label; keep `held` on and ready off, read its record and labels back, end only the identified C2 gate as below, and stop for that ticket. Only after these reads establish that no newer unresolved hold remains may either branch run. A ticket that had no `held` label before step 4, or whose every hold record since its `held` label last went on, other than this C2 check's own gate record, is a launch-fleet contract hold that step 4 assessed: release it directly (never re-append that contract hold, which would hold it again) in one edit, its ready label back on and `held` off, and read the labels back. Any other gated ticket (an ordering, manual or live hold, a plain hold comment, a hold of to-tickets', or a hold added since the record) is never released by C2: re-append the exact text of its latest hold record from before the gate (a legacy ordering line in its structured `launch-fleet: held for ordering: issue #B merges to main` form), keep `held` on and its ready label off, and read it back, so only its own release evidence frees it. Release nothing else: never any other held ticket. To end only the identified C2 gate, post and read back a comment with the standalone first line `C2 gate <comment-id>: ended`, citing these read-backs below it as that gate's release evidence. This creates no new hold record and grants no release of any other condition; each keeps its own release evidence. A stop in step 4 or 6 keeps every gate until Jake answers; then end each one as above, with his re-approval in place of step 4's assessment for the holds it covers.

The merges and their files, from REST in full (GraphQL's changed-file list has no old name of a rename, so it can't show a contract renamed away). Each command saves every page before `jq` reads them, so a failed page stops it; `RELIES` is the tickets' Relies on paths as a JSON list:

```sh
gh api --paginate "repos/{owner}/{repo}/pulls?state=closed&base=main&sort=updated&direction=desc&per_page=100" > merges.json \
  && jq -s --arg from "$FROM" --arg to "$TO" '[(add // [])[] | select(.merged_at != null and .merged_at > $from and .merged_at <= $to) | .number] | sort' merges.json
gh api --paginate "repos/{owner}/{repo}/pulls/<P>/files?per_page=100" > files-<P>.json \
  && jq -s --argjson relies "$RELIES" 'add // [] | if length >= 3000 then error("3000 files or more: not read in full")
    elif any(.[]; (.filename | type) != "string" or .filename == "" or (.status | type) != "string"
             or (.status == "renamed" and ((.previous_filename | type) != "string" or .previous_filename == "")))
    then error("a file without a name, status or old name")
    else [.[] | select(.status != "added") | .filename, .previous_filename | select(. != null)
          | select(. as $f | any($relies[]; . as $p | if endswith("/") then $f | startswith($p)
              elif contains("*") then $f | test("^" + ($p | gsub("(?<c>[.+?^${}()|\\[\\]\\\\])"; "\\\(.c)") | gsub("\\*"; "[^/]*")) + "$")
              else $f == $p end))] | unique end' files-<P>.json
```

The second prints the contract files the merge changed by either name (`[]`: none), matched as the check matches them: a path ending `/` is a folder, and `*` any name within one folder.

Done when the latest approval is current and every held ticket has its ready label back and no `held` label.

## Contract-shaped grants and delegated ON1 evidence

When the approval explicitly adopts [ops-dispatch v1](../../contracts/ops-dispatch.v1.md),
record/check its envelope separately from the existing complete approval table,
revision text and revision-v2 fingerprint. The envelope's exact paths, supporting
purposes, criteria, shared sections, owners and source-recomputed material explain
current authority; they are not a new template field or an alternative plan hash.
No graph approval silently retrofits envelopes into another approved graph.
The ops agent may assess other exact same-intent paths under the current
`narrow-grant` rule, reading the actual diff and source/ownership evidence and
recording a bound intent, grant/refusal/uncertainty and invalidations. The helper
checks evidence, never decides scope. Builders cannot grant their own exceptions.
Protected policies, contracts/interfaces, dependencies, workflows, scope, live and
spending retain their existing gates. Changes to approved bodies, titles, links
or outcomes still use **hold first**, the full successor revision and reapproval.
Follow the consumer project's finite daily audit procedure, resolved through
its private-state settings. The procedure stays in the configured private
repository; never copy it into the skills package.

Delegated ON1 is evidence preparation under the contract, not C2 authority or an
enabled release effect. Before any proposed release, record the approved producer
and verified merge/actual delta; every affected consumer's current approval,
unchanged behaviour and effective paths including valid grants; the exact hold
id/owner/full history; standing rule revision/reference; other gates and competing
claims; and the stable claimed operation. Optional/additive wording alone proves
nothing. Preserve the existing complete plan-revision/table, unchanged fingerprint,
Relies on and link checks and record-before-label order. Gate affected unstarted
consumers before moving a cutoff, and notify running consumers through recorded
work. Assess every outstanding declared-contract delta inclusively through the
new cutoff, including renames/deletions. After recording, re-read the complete
cutoff and hold history; do delayed verification on a later finite wake, never
sleep. Immediately before any separately enabled effect recheck current authority,
all consumers/grants, exact hold ownership, blockers and competing claims. A newer
hold, unread page or uncertain/partial relabel leaves work nonstartable. Restore
only the approved ready role for the exact covered hold and read labels/history
back; release never starts a builder. Under current OB-A1 the actual ops release
remains disabled, even with complete evidence. #2112 owns that consumer.

C2 remains the orchestrator-only wording assessment above, with all its full-cutoff
and hold-ownership checks unchanged. ON1 delegates no C2, CT1, factory-skill,
red-main, live, activation, spending or publication authority. Missing evidence,
changed consumer scope or an unavailable effect boundary records a gap and ends;
new decisions go through the existing exception/reapproval path.
