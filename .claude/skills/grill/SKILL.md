---
name: grill
description: Settle a design through a recorded interview. Use when asked to grill, before planning an unsettled design, or to resume an open grill.
version: 0.2.0
---

# Grill

Settle the design with the user and leave a confirmed, resumable private
record. Look up facts yourself. The user makes the decisions. A grill gives
no authority to plan from unsettled answers, start tickets, build, or review.

## Start or resume

1. Read the project's tracker and domain settings, relevant glossary and ADRs.
   Verify the configured private repository's visibility and the private
   checkout's remote before any write. Stop if you cannot verify either.
   Keep the grill, its branch, PR, exact replies and requests there. Before
   the first save, read [recording and recovery](references/records.md).
2. From the private checkout, run `sh <skill-directory>/scripts/index.sh`. Read
   related grills and check open private PRs for unmerged files. Resume the
   matching grill from its last saved round and pending decisions. Otherwise
   use the [file template](assets/grill.md) to create one private file, branch
   and PR. Keep the shared index untouched.
3. For a version grill, create or reuse its named development-tracker milestone
   on the day the grill starts. Use the project's tracker instructions.

Start is complete when the private file, index row, PR and any required
milestone exist.

The orchestrator also brings the next grill the same day the project's board
reports low stock. Use the [ready-stock and fed-ratio rules](../../contracts/plan-links.v1.md)
if counting from the tracker. The orchestrator can bring several grills for a
large gap. Builder limits and approval gates still apply.

## Work the frontier

Keep a design tree: each decision branches into the decisions that hang off
it. The frontier is the open decisions whose prerequisites are settled. Before
each round, read the saved answers, related grills and ADRs. Record anything
you skipped as already settled, with its source.

1. Ask at most three frontier questions per grill. Choose the ones that unblock
   the most. Give each a stable ID, plain context, options and consequences,
   and one recommendation on its own ➡️ line so “yes” accepts it. A question
   that depends on one still open this round waits for a later round. Finding
   facts never blocks a round: only the questions that depend on a pending
   lookup wait.
2. Classify and save the round's risk. Push, publish and verify the request,
   then show the round exactly as saved. Wait for the user's reply.
3. For a cockpit reply, match its context to the current, unanswered private
   request before interpreting the payload. Stale, malformed or uncertain
   context settles nothing. Apply the risk gates even when context matches.
4. Save the exact reply before doing anything else. Record which IDs it
   settles and which stay open, push, and read back the exact private reply
   comment before updating answered IDs or status. A skip or an ambiguous
   “yeah” leaves the question open.
5. Recompute the frontier. For “simplify,” keep the ID and context and ask
   it more plainly next round. Answer a question back before the next round
   and save the explanation. For a conflict or fuzzy term, ask which meaning
   or decision stands.
6. When a reply settles a project term or a hard-to-reverse decision, follow
   the glossary/ADR steps in [recording and recovery](references/records.md).
   Keep public decisions in plain words with decider, date and a verified
   private-comment pointer. Keep exact words and thread IDs private.

A round is complete when the exact reply, settled/open IDs and any required
records are saved and verified. On a cold restart, read those sources and
continue at the first unfinished step.

Before sending several grills in one message, assigning IDs alongside another
open or parked grill, parking, or resuming a parked grill, read
[coordination](references/coordination.md). Each grill keeps its own frontier.

## Confirm

With an empty frontier, save a summary of at most ten numbered decisions.
Classify its risk, push, and publish and verify its confirmation request.
Show the saved summary and ask the user to confirm it. Save the exact reply
first. Corrections need a new saved summary and request. New decisions reopen
the rounds.

Confirm only when the user explicitly accepts the latest saved summary and
nothing is open. Mark the file confirmed and dated, push, and resolve its
request. Merge under the project's rules or ask the user to merge. The job
ends at the merged private record for [to-spec](../to-spec/SKILL.md).
Spec confirmation and plan approval remain separate, and builders and reviewers stay independent.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
