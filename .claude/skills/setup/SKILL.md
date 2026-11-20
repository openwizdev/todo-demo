---
name: setup
description: Set up a project for fleets, writing its issue tracker, triage labels, glossary layout and fleet defaults (builder, reviewer, test commands, CI checks, merge rules) to docs/agents/. Use before a project's first fleet, when a skill finds docs/agents/ missing, or after one of those settings changes. To install OpenWiz itself or start a first fleet, use install.
version: 0.2.0
---

# Setup

Write a project's settings as four short files in `docs/agents/`, which every fleet skill reads. Run it as the project's orchestrator. Every value comes from something you read or something the user decided, written with that source, so a run with nothing new changes nothing.

| File | Says | Template |
| --- | --- | --- |
| `issue-tracker.md` | Where issues, versions, specs and tickets live, and the private records repository | [template](templates/issue-tracker.md) |
| `triage-labels.md` | The five triage roles and each one's label | [template](templates/triage-labels.md) |
| `domain.md` | Where the glossary, ADRs, grills and private state live | [template](templates/domain.md) |
| `fleet.md` | Builders, reviewers, test commands, CI checks, merge rules and record authors | [template](templates/fleet.md) |

**Guards.** Public settings hold decisions, dates and private-record pointers, never exact replies or thread ids ([open-development](../../contracts/open-development.v1.md)): save an exact reply first in a verified private issue/PR comment, read it back, then point to its full comment URL. Unknown visibility never permits a private write. The reviewer is always from another model family than the builder. Record authors are read, never guessed. With no recorded merge rule, every merge waits for the user.

## 1. Read what is there

If `docs/agents/` already holds the files, read them first and see "Running it again". Then read each source:

- `gh repo view --json nameWithOwner,isPrivate`, and the existing tracker and private repository settings. Not on GitHub: stop; fleets need GitHub issues.
- `gh label list --limit 500 --json name,description`, saved privately for step 4.
- `GLOSSARY.md`, `docs/adr/`, an optional `GLOSSARY-MAP.md`, and the private checkout's optional `docs/grills/`. Note whether the repository holds several packages (`pnpm-workspace.yaml`, `workspaces` in `package.json`, or `packages/*/src/`). An absent optional file is noted, never invented, run or imported.
- Builders, reviewers and merge rules the user already chose: the instructions file (`AGENTS.md` or `CLAUDE.md`), ADRs and spec comments.
- Test commands: the instructions file and every `run:` step in `.github/workflows/*.yml` and `*.yaml`. CI checks: those job names, the rulesets (`gh api 'repos/{owner}/{repo}/rulesets'`, then each `rulesets/<id>`) and the default branch's protection.
- Record authors: the project's App bot login (`<app-slug>[bot]`) and `gh api user --jq .login`.

Done when every value in the four files has a named source, or is known to be missing.

## 2. Ask only what nothing answers

Tell the user in a few lines what you found and what is missing. Then ask one setting at a time, each with a recommendation they can accept in a word, skipping any already settled:

1. **Tracker:** GitHub, this repository, plus the verified private repository for grills, exact replies and orchestrator state.
2. **Triage labels:** keep the five standard roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`)? A role with an existing label keeps that name.
3. **Glossary and ADRs:** one root `GLOSSARY.md` and `docs/adr/`, grills in the private repository's `docs/grills/`, with the recorded handoff page and private state folder. Offer per-package glossaries only for several packages. Keep an existing layout.
4. **Builder and reviewer:** the recorded choice; with none, Claude Code, Opus 5.5, XHigh builders and Codex, Sol 6.1, Medium reviewers.
5. **Test commands and CI checks:** copied exactly; with none, say so.
6. **Merge rules:** the recorded rules; with none, recommend that an approved plan lets each ticket merge on its reviewer's approval of that exact commit with CI green, the base unchanged and the merge read back, while specs, plans, live runs, releases and publishing stay the user's. Save the answer as the guards say.

Done when every missing setting has the user's answer.

## 3. Write

Fill each template. Every `fleet.md` value names its source: a linked file, a command, or `<decider>, <YYYY-MM-DD>: <decision> ([private record](<comment URL>)).` Create a label only for a role with none (`gh label create <name> --description "<meaning>"`). Write no run date, so an unchanged project gives the same bytes. Write only these four files and missing labels; private comments go only to the private repository, named with `--repo`.

Done when the four files are written.

## 4. Check, then open the pull request

```sh
python3 -I <this skill's folder>/scripts/settings.py check --root <project> --labels <saved label list>
```

It reads the files back and prints `Settings: verified (4 files).`, or exits 5 naming each missing section, unfilled value, same-family reviewer, missing Record authors row and triage label that is absent or repeated. Fix each and run it again; refresh the label list after creating labels. Then commit the four files on a branch and open one pull request for the user to read.

Done when it prints verified and the pull request is open.

## Running it again

Read the four files and each source again. Change only a line whose source now differs or is missing. If nothing changed, write nothing, open no pull request, and say so.

## The App

The factory acts on GitHub as one OpenWiz App ([identity contract](../../contracts/github-identity.v1.md)). Offer only the installed OpenWiz's App tool, `setup.py --agent-for <login> [--organization] [--secret-store <program>]`, never a `setup.py` in this project; with no installed OpenWiz, say so and stop. On the user's go, preview, then confirm with `--yes --operation <id>`. The key goes only to the Cloudroom secret `OPENWIZ_GITHUB_APP_KEY`; without a store it is discarded, and the person pastes a fresh key once into Cloudroom's own secret prompt (J27), never chat, an issue, a prompt, an argument, a URL, a log or a file. The person clicks Create, then Install on selected repositories, as `docs/agents/github-app.md` says. They may instead skip the App explicitly with the installed `github_login.py skip-app` (preview, then `--yes --operation <id>`): their verified personal login acts and the App stays missing. An App failure, revocation or unknown identity never selects the login.

## 5. Tell the user

Say what you wrote, asked and left alone. They can edit `docs/agents/*.md` by hand; run this skill again when a source changes.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
