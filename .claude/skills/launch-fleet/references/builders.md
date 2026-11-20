# Builders

Read this for a `start`, `reconcile start`, `check start`, `resume` or `reconcile resume` line, a refused probe, or a Claude plan-limit restart. The builder brief is `python3 -I scripts/brief.py builder <N>`.

## 3. Builders

**Starting one** (a `start` line):

1. **Claim it.** Post `launch-fleet: starting` on the ticket with `post.py comment`, which prints its id. Then ask the check whether your claim stands: `sh "<this skill's folder>/scripts/fleet.sh" claim <N> <your comment's id>`. It reads the ticket afresh and prints `go #<N>` only when no older claim is still live (`starting`, `started` or `start checked`), no builder is recorded, no pull request is open, the ticket is still on the frontier, and its ready label was last put on by a maintainer with no edit since (#1448). Anything else (`withdraw #<N>: <why>`, or an error): edit your claim to `launch-fleet: start withdrawn`, and stop. Two ticks that overlap can't both start a builder: the older claim wins, and it keeps the ticket as you edit it to `started` and `start checked`.
2. **Start it,** with `fleet.md`'s `## Builder for small tickets` table for an exact `polish`, `huntr` or `proposal` label, otherwise `## Builder`, the ticket in its title, and the one-line brief `brief.py builder` prints, the same for every builder:

   ```sh
   room-cli thread spawn --top-level --provider <harness> --model <model> --reasoning-level <effort> \
     --title "#<N>: <ticket title>" \
     --prompt "$(python3 -I "<this skill's folder>/scripts/brief.py" builder <N>)"
   ```

   Everything about the work is in the ticket and its spec, so the brief never drifts from them. A top-level thread starts from the default branch on GitHub, and outlives this tick. A fleet thread starts it as its own child instead (`--parent-self --project "$ROOM_PROJECT_ID"` in place of `--top-level`), so it can reach it (SKILL.md, "Fleet threads").

   With a host chosen (`host.py which` prints `host: <name>`), start it through that host's driver instead ("Hosts", below); `host: none` keeps the `room-cli` start above.

3. **Record the outcome** by editing your claim (`post.py edit`): `launch-fleet: started` when CloudRoom started it, or `launch-fleet: start refused: <its reason>` when it said no. A refused start stays on the frontier, and is tried again 10 minutes after the refusal (the edit that made your claim one), not sooner: the refusal's record is itself one of GitHub's messages, which would otherwise wake a retry at once, again and again. If the start timed out or you can't tell, leave the claim as it is: the check asks for a reconcile after 10 minutes.

**Hosts** (#1371). A project chooses where its builders run in `docs/agents/host.md` on its default branch: one `Host: <name>` line naming a driver in OpenWiz's `adapters/` (records v1, section 6). `host.py` reads it at the default branch's current tip on origin, never the checkout's copy, which can be older. Onboarding writes it, and the user changes it by asking their agent to edit that line; nothing else changes. `scripts/host.py`, run from the project checkout with `LAUNCH_FLEET_HARNESS`, `LAUNCH_FLEET_MODEL` and `LAUNCH_FLEET_SKILLS` set to your own `--harness`, `--model` and `--skills` for `status.py` (set them if you can; with any unset, a start or wake still runs and still comments, and only the fleet status note is skipped, with a warning naming them), calls the driver (`$OPENWIZ_ADAPTERS/<name>/driver`, driver v1) and keeps each run privately in `LAUNCH_FLEET_RUNS`, an absolute JSON file beside `LAUNCH_FLEET_STATE`, never in the checkout or a public record:

- **Start:** `python3 -I "<this skill's folder>/scripts/host.py" start <owner>/<repo> <N> <harness> <model>`, the harness `claude` for Claude Code or `codex` for Codex and the model the table's `--model` value. `started #<N> on <host>` means the run is saved locally: commit that run map to the private repository's latest map and read it back, as with the thread map, before you edit the claim to `launch-fleet: started`; a later wake restores it (SKILL.md, "Each wake" step 1). `unknown: #<N> started on <host> but its run was not saved; save run ...` names the run: save exactly that into the private map before anything else. `stopped (driver start failed): ...` means the driver refused three tries, 1 and 2 seconds apart (#1446): `host.py` has already written your fleet status note on the ticket as `stopped (driver start failed)` (unless the three variables were unset) and posted one `launch-fleet: driver start failed` comment, each only once. The comment never quotes the driver: it gives a fixed reason, `exit 1: refused` and the entry of the owner-only log `driver-failures.log` beside `LAUNCH_FLEET_RUNS`, which holds the driver's own `error` and `next`; read that entry to see what to do, and never copy it to GitHub. Post nothing more about it; edit the claim to `launch-fleet: start refused: driver start failed`. A line ending `; unknown: the ticket's report is incomplete (...)` is the same refusal: the note and the comment are each tried, and the parentheses name what failed; the next refused try writes what is missing. The next start or wake that succeeds marks that comment cleared and posts a `done` fleet note; a second line `unknown: the failure report on #<N> was not cleared ...` after a success leaves that to the next success. The `next:` on host.py's own line is the driver's text only when it holds no credential, private id, machine path or URL with user info (`user@` or `user:password@` before the host, with or without a scheme); otherwise it is withheld whole. `unknown: ...` leaves the claim as it is: the reconcile looks for the builder's status note and branch on GitHub before any retry, as a run may exist. A ticket never gets a second live run.
- **Wake:** every message to a builder with a run (a CI failure, findings, a resume) is `host.py wake <owner>/<repo> <N>`, after its record or reason is on GitHub: the builder reads its ticket and pull request again. Due lines name such a builder `thread run:<N>`. `woke` is the delivery's confirmation. A wake is retried and reported as a start is: `stopped (driver start failed): ...` means the delivery failed and the ticket says so; leave the message undelivered. `no run: ...` means the builder was started with `room-cli`: tell it as before.
- **Stop:** `host.py stop <owner>/<repo> <N>` when its ticket closes, in place of archiving its thread, then save the run map privately again.
- **No run map:** a due line `look #<N>: the private run map LAUNCH_FLEET_RUNS was not restored ...` or `... no private run map LAUNCH_FLEET_RUNS was restored` means this wake skipped the restore: restore it and read again; never guess the builder.

Wake and stop reach the host that started the run, even after the setting changes; the next start uses the new host. A driver gets the caller's environment unchanged, and no login ever passes through `host.py` or a driver. For a builder with a run, `reconcile start` and `check start` look for its live builder status note and its branch on GitHub instead of a thread. Reviewers still start with `room-cli`.

**Never wait awake.** No brief or message from a tick asks an agent to stay awake while it waits: a builder or reviewer never keeps a background watcher, a poll loop or a `sleep` waiting for CI, a review or another thread, and ends its turn instead, as `build-ticket` and `review-ticket` say. The tick's next message (CI failed, findings, a re-check, a resume) is what wakes it. A message that tells one to wait for something (#B to merge, say) says to end its turn until the resume (Jake, the cheaper-factory grill, CF1).

**One probe per batch.** Before claiming, read each `start` ticket's labels and pick its builder table, as step 2 above says: that is its assignment, and the starts with one assignment are one group. Claim them all as in step 1; then start that group's first claim alone, the probe. If CloudRoom starts it, start the rest of the group in parallel. If it refuses the probe for a reason that is not that ticket's own (the model catalog, the account or plan, the provider), edit the probe's claim to `launch-fleet: start refused: <reason>`, and every other claim of the group to `launch-fleet: start not tried: #<probe> was refused: <reason>`, without starting them. Each waits the same 10 minutes as a refusal, so the group retries together, with one probe again. A refusal for the ticket's own reason ends only that start: the next claim becomes the probe. Never swap in another provider or model.

**Claude plan-limit restart (#1196):** if `## Builder for small tickets` still selects `claude-code`, the tick prints `look: fallback builder is the limited family` and saves no fallback record; wait for an approved setting from another family before restarting. Otherwise, a Rust tick `restart` due item records `launch-fleet: builder fallback due, branch <branch>` on the ticket and names the small-ticket builder settings. Reconcile that recorded item before acting: never start twice. Stop/archive the limited builder, preserve its branch, then start the replacement from that branch using `## Builder for small tickets`, with the ticket brief and an explicit instruction to continue its existing work. Keep the old and replacement identities, the fallback claim, the branch and their handover lineage exclusively in private state; update the private builder mapping to the replacement after its start is confirmed. Update the original public checked-start record to `launch-fleet: start checked, branch <branch>`, keeping the same branch. The fallback comment keeps its branch-only first line, with no replacement identity appended. The private handover retires the old stored builder when the tick next reads it. It retains the original code on the branch, so the tick leaves the builder family conflicting for new reviewer assignments. First and fresh reviews print `look` and start no reviewer; the orchestrator or Jake chooses the reviewer explicitly. Never apply this fallback to a reviewer; its review waits for its family. A consumed fallback is never tried again automatically; an uncertain restart goes to the orchestrator.

**Reconciling** (a `reconcile start` line): before any retry, find out whether a builder started. Look for a thread titled `#<N>:` in `room-cli thread list`, and for its branch (`git ls-remote origin 'refs/heads/room/<N>-*'`). If one is there, edit the claim to `launch-fleet: started`. If not, edit it to `launch-fleet: start failed: <why>`, and the next tick starts it again. A ticket never gets two builders.

**Checking** (a `check start` line): its thread exists and is working, its title names the ticket, and its branch shows up. Then edit the claim to `launch-fleet: start checked, branch <branch>`. If the thread is gone or never started work, edit it to `launch-fleet: start failed: <why>`.

A builder stays with its ticket through every review round, and is archived when its ticket closes. It is never given another ticket.

**Waiting on another ticket (#467):** whoever tells an existing builder to
wait for #B, including the orchestrator answering a builder's question, must
also add a new `launch-fleet: waiting for #B` comment on its ticket. Post it
even when the answer uses free-form prose such as "Once #B has a verified
merge, continue." The latest wait replaces the previous one. The check also
reads the legacy first line `Orchestrator (PC, ops): **wait for #B.** ...`,
with or without the parenthesized context, an optional `yes, ` or `confirmed: `
lead-in (comma or colon accepted), and an optional period inside the bold.
Those known forms cover existing waits; new instructions always get the
structured record. It prints
`resume` only after #B is closed by a pull request merged into the default
branch. A closed issue alone is insufficient. The safety net and the full
check after a merge find waiting builders; a targeted wake finds only the
waiting tickets it names. Delivery is recorded against that wait comment's
id, so the same wait is not sent twice and a new wait can be sent again.

**Delivering a resume:** comment `launch-fleet: resume starting C for #B` on #N, then run `sh "<this skill's folder>/scripts/fleet.sh" claim N <your comment id>`. Only
`go #N` may tell its recorded builder that #B merged and to continue the
instructions in wait comment C. An older claim wins, so overlapping ticks
cannot both deliver. On success, edit your claim to `launch-fleet: resume sent
C for #B`; on a definite failure, edit it to `launch-fleet: resume failed C for
#B: <why>`. On `withdraw`, edit your claim to `launch-fleet: resume withdrawn C
for #B` and send nothing.

A claim with no outcome after 10 minutes prints `reconcile resume`. Read the
claiming thread and the builder's delivery history before any retry. Proven
delivery edits that claim to `resume sent`; a definite non-delivery edits it
to `resume failed`. A still-running or unreadable sender, or an uncertain
delivery, stays claimed and goes to the orchestrator. Never resend on a
reconcile without proving the earlier delivery did not happen.

## The due lines in full

| Line | Do |
| --- | --- |
| `look #N: blocked on scope <key>: ...` | Its builder waits on its own scope question (`needs-info`), with no branch, past the 30-minute start check. Read the builder's thread once: if it is gone, edit its start record to `launch-fleet: start failed: <why>` and tell the orchestrator. Either way, record `launch-fleet: look: <the reason>`. The check raises it once per key (the start record and the latest plain comment, written or edited; never launch-fleet's own records), so it comes back only when the question is answered or edited, a new builder starts or the `needs-info` label comes off |
