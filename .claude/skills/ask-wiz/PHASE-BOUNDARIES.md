# Phase boundaries in CloudRoom

A phase ends when one useful chunk is done: settling a design, writing a plan,
building a ticket, or checking a result. Choose at that boundary. Mid-phase,
keep going or delegate a bounded independent chore; avoid losing the reasoning
that is still in use.

Work down these questions in order:

1. **Keep going?** If the next phase needs this conversation as a primary source,
   or the thread still has enough useful context, stay here. Grilling and
   planning often benefit from the exact reasoning remaining together.
2. **Does the next job need a fresh thread?** If context is exhausted, the work
   is moving to another repository or harness, or another orchestrator is taking
   over, first preserve decisions and pointers in a committed handoff file.
   Read the [handoff skill](../handoff/SKILL.md): only the orchestrator updates
   that project's one-page handoff. Land it by the project's merge rules, then
   have the fresh thread read and check it against current sources.
   A builder instead preserves its branch, ticket, pull request, proof and
   unresolved questions; a reviewer preserves its exact-head report on the
   pull request. Their replacements resume those records, not a new
   orchestrator handoff. If the next task needs none of the old context, start
   its fresh thread from its own brief without copying irrelevant history.
3. **Can a bounded part run in a child thread?** Use a CloudRoom child thread for
   an independent chore with a clear brief, pinned sources and a report back.
   Follow the project's helper settings and permissions; keep the main thread
   for decisions. Starting a child gives it a separate context, not knowledge
   of later edits. Do not turn a builder's helper into a second builder or
   reviewer, and do not create an agent merely to choose a skill.

A handoff is a summary: it loses detail compared with the primary source.
Keep public links to the spec, ticket, exact commits and synthetic evidence,
and verified private-record comment pointers for the grill or private evidence.
Exact user words, thread ids and the handoff state stay in the configured private
repository; never paste them or private file links into a public hand-back.
The next thread checks the original through those pointers. Automatic context compaction is
also a summary, not evidence that every decision survived. Continue from the
saved records and verify anything uncertain.

Adapted from Matt Pocock's `ask-matt/PHASE-BOUNDARIES.md`
(`github.com/mattpocock/skills` @ `4ae2317`). The MIT notice is in
[SKILL.md](SKILL.md#credit).
