# Telling the user

Read this for a `nightly red`, `re-approve`, `person`, `spec done`, `close spec` or live-check `look` line.

## 6. Telling the user

The fleet talks to the user only when it needs them: a red nightly CI run, a plan that changed since its approval, a finding parked as a decision for Jake or an overturned ruling whose stated cost is high ([reviews.md](reviews.md)), a security, privacy, live, spending or publishing call an orchestrator decision needs, a live step (a `person` line), and once when a spec closes. Everything else stays quiet; the user can always ask the orchestrator where things stand. Each ticket or spec item goes to two places: a message in the orchestrator's thread (`room-cli thread tell <the orchestrator's thread> "Needs you: ..."`), and a comment on the spec issue starting `**Needs you:**` (on the issue itself, for one approved on its own). A fleet thread posts only the comment: GitHub records are its only channel to the orchestrator (SKILL.md, "Fleet threads"). The user reads and answers it in the orchestrator's thread, on the web page; in 0.0.6 it moves to the web page's "Needs you" list.

**A red nightly run** belongs to the repository, not a ticket. The check reads
the latest **completed**, scheduled `ci.yml` run on the default branch. Only
`failure`, `timed_out`, `startup_failure` and `action_required` are red.
Success, cancelled, skipped, neutral and stale are quiet, as is no completed
run. Projects without that workflow are quiet (HTTP 404); other read failures
still stop the check. A newer queued run does not count as success. These
alerts are only in this loop: they do not change the product fleet view or its contract.

For `nightly red <run> attempt <attempt> at <commit>: <url> (<conclusion>)`:

1. Run the check again. If the alert is gone, do nothing. If it names a
   reconciliation comment, do step 4 before sending anything.
2. Claim the notification by creating a **commit comment** on the named commit:
   `gh api --method POST repos/<owner>/<repo>/commits/<commit>/comments -f body='launch-fleet: nightly telling <run> attempt <attempt>'`.
   Keep its returned comment ID. Run the check again: it must still name the
   same run and attempt, with **your comment ID as the oldest claim**. A later
   claimant leaves the oldest claim to its sender until it is older than one
   tick (step 4). If the alert cleared, leave your claim alone and do nothing.
3. Tell the orchestrator's thread `Needs you: nightly CI <url>, attempt <attempt>, concluded <conclusion>.` Only after that call succeeds, edit
   **your** claim using `gh api --method PATCH repos/<owner>/<repo>/comments/<comment id> -f body='launch-fleet: nightly told <run> attempt <attempt>'`.
   Read it back; its exact body is the delivery record. The commit comment
   replaces the spec comment for this repository alert. Never mark it told
   before delivery. Run the check again to verify the alert is gone.
4. **An existing claim is unfinished delivery, not permission to resend.** A
   fresh tick cannot read an earlier tick's thread output. Read the named
   commit comment with `gh api repos/<owner>/<repo>/comments/<comment id>` and
   compare its `created_at` with now. Until it is older than one safety-net
   tick (the interval in `docs/agents/fleet.md`, including its setting while
   GitHub's messages are off), leave it alone and go on with the tick's other
   lines; do not report `needs-you` for this claim.

   Once it is older, run the check again. If the alert cleared or its oldest
   claim changed, do nothing. Otherwise tell the orchestrator once, in the
   same message form, `Needs you: nightly CI <url>, attempt <attempt>, concluded <conclusion>. Delivery of the earlier notification for this run attempt is uncertain (claim <comment id>).`
   Only after that call succeeds, edit **that oldest claim** using
   `gh api --method PATCH repos/<owner>/<repo>/comments/<comment id> -f body='launch-fleet: nightly uncertain <run> attempt <attempt>'`.
   Read it back and run the check again to verify the alert is gone. If the
   edit or read-back fails, repair the record without sending another notice.
   This settles the uncertainty notice; it never claims the earlier message
   was delivered. Do not keep reporting `needs-you` for a settled attempt.

The complete commit-comment history is read afresh on every failed-nightly
check. An exact `nightly told` or `nightly uncertain` record suppresses only
that run attempt, including across fresh sandboxes; another run or rerun may
alert separately. Overlapping ticks use the oldest claim.

- **`re-approve #S`:** say that the plan changed since which revision (compare `revision.sh`'s output with the approval's revision text to see what), and record `launch-fleet: needs approval: <the line's text after "re-approve #S: ">`. Nothing under the spec starts until a new revision approves it. Tickets already being built keep going.
- **`spec done #S`:** a spec is done when all its planned builder tickets have verified merges and its live check (if it has one) has passed. Planned `ready-for-human` tickets must be complete too; their closed state is not itself proof that a live check passed. For a required live check, the evidence is an explicit recorded **passed** result with its proof on the planned `ready-for-human` live-check ticket, or in the version's acceptance record linked from the spec. A closed issue alone or fixture tests do not prove that result. Read it before posting the summary or closing the spec; a spec with no required live check needs no live-pass evidence.

  **Missing evidence:** leave the spec open. Notify the orchestrator once and post `launch-fleet: look: live check not recorded as passed` on the spec. Ask it to add or link the evidence in a new plain comment on the spec (one whose first line does not start `launch-fleet:`). The missing-evidence record blocks both completion actions without repeating that alert. Do not post the summary while it applies.

  **Evidence arrives:** each newer plain spec comment produces `look #S: live check evidence to verify in comment <id>` on both checks and spec wakes. This is a task for the tick to verify that comment and its linked recorded proof. If it contains the required explicit pass, append a new spec comment whose first line starts `launch-fleet: live check passed`; the line may append `: <evidence source>`. Name the evidence source and result in the comment. That newer record releases the wait and invalidates the quiet cache; run the check again before continuing. If the comment does not establish the pass, record `launch-fleet: look: live check evidence to verify in comment <id>` and leave the spec open. That acknowledges this comment without repeating the alert; later plain comments each get their own verification task. A later missing-evidence report requires another verification. The pass record is the tick's verification of stored evidence, not a claim that the tick ran anything live.

  **Closing summary:** Write a comment on the spec starting `launch-fleet: spec summary`: what merged, the live-check result (or no live check required), and any open follow-ups (low review findings). The line names confirmed follow-ups only: an open sub-issue outside the plan must have `polish` or a first non-empty body line starting `Follow-up of #<ticket> (spec #S)`. External issues use that same first-line marker. An unclassified open sub-issue can be new planned work awaiting re-approval: the check emits a `look` and blocks the summary and closure. Have the orchestrator classify it; new planned work goes through to-tickets. Never label it `polish` just to close the spec. Label each `polish` (`gh issue edit <N> --add-label polish`); if that label is missing, create it once with the description "Small follow-up in the polish backlog; never blocks a spec". Follow-ups never hold a spec open, including after the summary: close it on `close spec #S` once its planned agents are archived and the live-check pass is verified. Jake, 2026-11-04: completion requires planned merges and the live check; low follow-ups remain in polish ([private record](https://github.com/jparker2006/ClosedWiz/issues/1021#issuecomment-6642589413)). If the spec was its version's last, report its readiness for the release branch only when that version's live check has passed; release branches and live checks remain the user's. Tell the orchestrator too.

## The due lines in full

| Line | Do |
| --- | --- |
| `nightly red <run> attempt <attempt> at <commit>: ...` | Tell the orchestrator about the red nightly run, once per run attempt; reconcile any existing delivery claim first ([user.md](user.md)) |
| `person #N` | A person's ticket (a live step) is ready: approved, unblocked and not held. Tell the user ([user.md](user.md)), and record `launch-fleet: told the user`. After the person finishes, the orchestrator or owning fleet thread verifies the result and posts `launch-fleet: complete: <evidence>` as the first nonblank line of a comment on that ticket, before or when it closes. Name the completion proof on that line: a read-back, artifact path or linked result; a live step needs its observed result. If a `look #N` line asks for the record after closure, verify that same evidence and post it then. Without a verified merge, missing or unverified completion evidence keeps its dependents blocked |
| `re-approve #S` | A ticket could start, but the plan changed since the user approved it, so nothing under the spec starts. Tell the user ([user.md](user.md)) |
| `spec done #S` | Every planned builder ticket has a verified merge and every planned human ticket is complete. Check the live-check evidence and write the closing summary ([user.md](user.md)); follow-ups never block it |
| `close spec #S` | Apply the same live-evidence and missing-evidence record procedure as `spec done`, label confirmed follow-ups `polish`, and close the spec issue with a comment saying the planned tickets are done |
| `look #N` | For `live check evidence to verify in comment <id>`, verify the new evidence as in "Telling the user" above. For other reasons, tell the orchestrator what the line says and record `launch-fleet: look: <the reason>` on #N |
