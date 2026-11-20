# Fleet settings

Every fleet in this project starts from these settings. The fleet skills read this file instead of naming any project's agents, commands or rules. Each value names its source; when a source changes, run the `setup` skill again (or edit the line by hand) so the two agree.

## Builder

One per ticket. It builds its ticket on its own branch, and never reviews or merges.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

Source: Jake, 2026-11-20: J267, the to-do demo's builders are Claude Code, Opus 5.5, Medium, launched on boat.dev, reviewed by Codex, Sol 6.2, Medium ([private record](https://github.com/jparker2006/ClosedWiz/pull/3154#issuecomment-7036872503)).

## Builder for small tickets

Tickets with an exact `polish`, `huntr` or `proposal` label use this table; every other ticket uses `## Builder`.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

Source: Jake, 2026-11-20: J267, the to-do demo's builders are Claude Code, Opus 5.5, Medium, launched on boat.dev, reviewed by Codex, Sol 6.2, Medium ([private record](https://github.com/jparker2006/ClosedWiz/pull/3154#issuecomment-7036872503)).

## Reviewer for Claude-built

One per pull request, from a different model family than the builder. It reviews the exact head and never edits. If it can't be started, the review waits: it is never swapped for another model.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Codex | `--provider codex` |
| Model | Sol 6.2 | `--model gpt-6.2-sol` |
| Effort | Medium | `--reasoning-level medium` |

Source: Jake, 2026-11-20: J267, the to-do demo's builders are Claude Code, Opus 5.5, Medium, launched on boat.dev, reviewed by Codex, Sol 6.2, Medium ([private record](https://github.com/jparker2006/ClosedWiz/pull/3154#issuecomment-7036872503)).

## Reviewer for GPT-built

Use the verified builder's provider, from its branch-matching `start checked` record and that exact thread's provider read. Unknown or conflicting family waits; existing reviewers retain their thread.

| Setting | Value | `room-cli thread spawn` flag |
| --- | --- | --- |
| Harness | Claude Code | `--provider claude-code` |
| Model | Opus 5.5 | `--model claude-opus-5-5` |
| Effort | Medium | `--reasoning-level medium` |

Source: Jake, 2026-11-20: J267, the to-do demo's builders are Claude Code, Opus 5.5, Medium, launched on boat.dev, reviewed by Codex, Sol 6.2, Medium ([private record](https://github.com/jparker2006/ClosedWiz/pull/3154#issuecomment-7036872503)). No GPT builder is planned; this table keeps the other-family rule if one is used.

## Labels

The triage labels and their names here are in `triage-labels.md`. A fleet adds one label of its own:

| Label | Means | Put on by | Taken off by |
| --- | --- | --- | --- |
| `held` | The ticket is held: it waits for the user's approval of a changed plan or contract, and never starts while it has this label. It has no ready label while held | `to-tickets`, before it changes an approved plan; `launch-fleet`, when a merge changes a contract the ticket relies on | `to-tickets`, as it puts the ready label back once the new approval is recorded; `launch-fleet`'s `release` line, if it is still on after that |

The skill that holds a ticket first creates the label, once, with the description "Held: waits for the user's approval".

Source: the fleet skills, `to-tickets` and `launch-fleet`, which put it on and take it off. It is the same in every project.

## Test commands

The full set, in this order. A builder runs all of it locally, and opens its pull request only when every command passes. Node.js 24; no dependencies.

| # | Folder | Command | CI check |
| --- | --- | --- | --- |
| 1 | root | `npm test` | `Test` |

Source: [AGENTS.md](../../AGENTS.md), and [the CI workflow](../../.github/workflows/ci.yml).

## CI checks

| Check | Runs | Required on |
| --- | --- | --- |
| `Test` | 1 | `main` |

Every pull request runs it, docs-only ones too. The `Pages` workflow deploys `app/` to GitHub Pages after each merge to `main`; it is not a pull request check.

Source: [the CI workflow](../../.github/workflows/ci.yml), and the branch rules (`gh api 'repos/{owner}/{repo}/rulesets'`).

## Standing merge rules

| Pull request | Review | Merged by, and when |
| --- | --- | --- |
| A ticket of an approved plan | Its other-family reviewer, `VERDICT: APPROVE` at the exact head | The orchestrator (launch-fleet), with CI green at that head, the base unchanged and the merge read back |
| Anything else | None set | The user |

Source: Jake, 2026-11-20: J267, the to-do demo's ticket pull requests merge on their reviewer's approval ([private record](https://github.com/jparker2006/ClosedWiz/pull/3154#issuecomment-7036872503)).

## GitHub identity

| Setting | Value |
| --- | --- |
| Record authors | `openwiz[bot]`, `jparker2006` |
| Harness permission mode | `bypassPermissions` |

Source: the OpenWiz App's settings (slug `openwiz`), and `gh api user` on the account the fleet runs as; the harness permission mode as in `jparker2006/openwiz-boat-demo` for boat.dev builders (Jake, 2026-11-20: J261 A).
