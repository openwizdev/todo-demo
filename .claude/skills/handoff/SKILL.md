---
name: handoff
description: Keep the orchestrator's one-page handoff file in the private repository current, so a new orchestrator can take over without the old chat. Use after the user approves a plan graph, before an orchestrator retires, and first thing when taking over as orchestrator. Orchestrator only.
version: 0.2.0
---

# Handoff

The orchestrator's knowledge survives in one short **handoff page** in the project's configured private repository, where every authorized new orchestrator can read it, unlike a sandbox's temporary folder.

## Guards

- **Orchestrator only.** A builder's state is its branch, pull request and ticket; a reviewer's is its report on the pull request; the fleet loop reads GitHub fresh on every wake. Their replacements resume from those records. Anyone else asked to hand off declines and says why.
- **Private only.** The page lives only in the configured private repository. Missing settings, unknown visibility or a public target stops the write; never fall back to a public `docs/agents/handoff.md`. Public files, PRs and comments carry no handoff content, state, exact replies or thread ids: a decision there is its summary, date and private-comment pointer.
- **Nothing secret.** No keys, tokens, passwords, email addresses, thread ids or personal details. Exact user words appear only as the user's decisions, on this private page.
- **No guesses.** A line you could not check says **unverified**. A branch or PR shows the work, not that its agent runs: unless CloudRoom shows the thread, its state is unverified.

## When

| When | Do |
| --- | --- |
| You take over as orchestrator | **Take over**, before anything else |
| The user has just approved a plan graph | **Update** |
| You are about to retire: your chat is too long, or another orchestrator takes over | **Update** as your last act, then tell the user the page is ready |

## Find the page

Read `docs/agents/issue-tracker.md` for the private repository, `docs/agents/domain.md` for its checkout and state paths, and the handoff path the project's instructions name. Before any write, check the target:

```sh
python3 <skill-directory>/scripts/handoff.py private <owner/repo>
```

`private ok` lets you go on. `refused` or `unknown` stops every write: report the missing setting or read. If no page exists yet, create it at that private path from [the template](page.md).

## Take over

1. Read the page, then the issues and files it points to.
2. Check every line against now: each fleet against its spec issue, each agent and loop against CloudRoom, each decision where it was asked. The page is a snapshot; act on what is true now.

Done when you know, for every line, whether it still holds.

## Update

1. **Read the facts fresh** from GitHub and CloudRoom: each open spec with an approved plan graph and its tickets, the open pull requests, every agent and loop running for the project, and the standing approvals on record.
2. **Rewrite the page whole** from [the template](page.md), replacing the old page; git keeps the history. Keep it one short page: one row per fleet, each full list one link away.
3. **Source every line:** the issue, pull request, commit or file it comes from, or a decision with its date and private-comment pointer. Link to specs, plans and reports instead of copying them. Name agents by their work (role, ticket, branch, pull request).
4. **Check it:** `python3 <skill-directory>/scripts/handoff.py check <page-file>` prints `page ok`, or each problem by line: the wrong sections, an empty one (write "None."), a token, key, email address or thread id. Fix and rerun until `page ok`. It can't judge everything, so the guards above still hold.
5. **Land it** on the private repository's default branch, from its verified private checkout and targeting that repository explicitly, by the project's merge rules (`docs/agents/fleet.md`). Then read it back:

   ```sh
   python3 <skill-directory>/scripts/handoff.py landed <owner/repo> <page-path> <page-file>
   ```

   `landed` names the branch and blob. `not landed` means the default branch lacks this page: finish landing it, since a page left on a branch hands nothing off. `unknown` means the read failed: read again before any new write.

Done when `landed` prints for the page that passed the check.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
