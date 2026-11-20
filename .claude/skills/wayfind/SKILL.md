---
name: wayfind
description: Chart an effort too big for one grill (many specs, even many versions, far out) as a map of the decisions it needs, and settle them one at a time until its designs are ready for to-spec and to-tickets. Use when a grill shows the effort is bigger than one grill, when asked to wayfind, or to work through an open map. Not for an effort one grill can settle.
version: 0.2.0
---

# Wayfind

Chart the way to a far **destination** as a **map** issue on GitHub, then settle its **questions** one session at a time until nothing is left to decide and `to-spec` can take over. Wayfind plans; it never builds. Work starts only from a plan graph the user approves, never from the map.

- **Every decision is the user's, in a grill.** Research and prototypes only feed the grills; never answer the user's side yourself. Save exact answers in the configured private repository (the open-development contract); public answers give the decision in your own words, its date and a private-record comment pointer. Publish no exact user words, thread ids or private links. If the private record cannot be saved or verified, ask the orchestrator before recording the decision.
- **Refer by name:** call each map and question by its title, linked (`[<title>](<url>)`), never a bare `#42`.

## The map and its questions

The map is one issue labelled `wayfind:map`: an index read once per session, holding `## Destination` (one or two lines), `## Notes` (the domain, the skills every session reads, the user's standing preferences), `## Decisions so far` (one linked line per settled question), `## Not yet specified` (the fog) and `## Out of scope`. Each question is a sub-issue whose body is only `## Question` and the decision, fact or work it settles; open questions are never listed in the map.

- **Its kind is its one label;** the body never says it. `wayfind:` labels are the only labels a map and its questions carry, never a ready or triage label, so no fleet builds them.
- **Blocking is GitHub's "blocked by" link.** A question is unblocked when every blocker is closed.
- **A claim is a comment,** `wayfind: claimed`, posted before any work by a record author (the Record authors row of `docs/agents/fleet.md`); anyone else's claim or release is ignored. Keep its numeric comment id (the `#issuecomment-` suffix of its URL, not the GraphQL `id`) in private resumable state, never a thread id. The earliest unreleased claim holds the question; `wayfind: released <claim comment id>` releases only that claim; release yours if you stop before settling. If you lose your id, ask the orchestrator rather than release another holder's claim.
- **The frontier** is the open, unblocked, unclaimed questions. `frontier.py` (below) prints it.

| Label | Settled by |
| --- | --- |
| `wayfind:grill` (default) | A small grill with the user, with the `grill` skill. Its confirmed summary gives the public decision, date and pointer |
| `wayfind:research` | A fresh Cloud child thread briefed "Read `skills/research/SKILL.md` and follow it" with the question. It decides nothing; record its report as the answer |
| `wayfind:prototype` | A rough throwaway (outline, mock, stub), linked from the question and shown to the user in a grill |
| `wayfind:task` | Work a decision waits on (access, a sign-up). Do it where you can, else give the user a checklist. Record what was done |

**Fog and scope.** Don't chart what you can't see: a question you can state precisely now is a question, even while blocked; anything vaguer stays fog under Not yet specified, uncut. Not yet specified holds only fog. Work beyond the destination goes under Out of scope and never comes back: close such a question with a comment saying why, and add one line there.

## Chart the map

1. **Name the destination** in a grill: it fixes the scope.
2. **Map the frontier** in a breadth-first grill. If there is no fog and one grill fits, stop and ask the user how to go on.
3. **Create the map,** then each question you can state now as a sub-issue with its label; add "blocked by" links and real cross-references in a second pass.
4. **Add one Later line** to the project's roadmap linking the map.
5. **Claim each research question,** then run `frontier.py holder <question> --mine <claim comment id>`. Start its agent only on `yours`; on anything else (`held by`, `blocked by`, `no kind label` or `closed`), release yours and leave that question. Start the agents in parallel. Then stop.

Done when the map, its labelled and linked questions, the roadmap line and every research agent exist.

## Work through the map

1. **Load the map's body** and run `frontier.py map <map>`. Take the question you were named, else the first `frontier` line.
2. **Claim it,** then run `frontier.py holder <question> --mine <claim comment id>`. Work only on `yours`. On anything else (`held by` another id, `blocked by`, `no kind label` or `closed`), release yours and stop work on that question; then run `frontier.py map <map>` again and take the next `frontier` line. Run the holder check again before you record an answer; if it no longer says `yours`, release and stop.
3. **Settle it** as its label says, reading related questions and the skills in Notes as needed.
4. **Record it:** the public-safe answer as a comment, linking (never pasting) anything made to settle it; close the question, add its linked line to Decisions so far.
5. **Redraw the map:** create and link new questions, graduate fog the answer made specific, rule out what lies beyond the destination, and change or close questions the decision makes wrong. Read the map's body again right before each edit.

One question per session, except research, which runs in parallel. Done when the answer is on the closed question and the map shows its line and the redrawn fog.

## When the way is clear

When `frontier.py map` prints `no open question` and Not yet specified is empty, hand the map to `to-spec`, never straight to building.

## Commands

```sh
python3 -I <wayfind-skill-folder>/scripts/frontier.py map <map>      # exit 2: read incomplete, never "clear"; run again
python3 -I <wayfind-skill-folder>/scripts/frontier.py holder <question> --mine <claim comment id>
gh issue create --title "<the question>" --label wayfind:grill --parent <map> --body-file question.md
gh issue edit <question> --add-blocked-by <blocker>
gh issue comment <question> --body "wayfind: claimed"
gh issue comment <question> --body "wayfind: released <claim comment id>"
gh issue view <question> --json labels,blockedBy,comments --jq '{labels: [.labels[].name], open_blockers: [.blockedBy.nodes[] | select(.state == "OPEN") | .number], claims: [.comments[] | select(.body | startswith("wayfind: ")) | {url, body}]}'
```

Create the five labels (`wayfind:map` and the four kinds) once per repository with `gh label create`. Write multi-line bodies to a file first.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
