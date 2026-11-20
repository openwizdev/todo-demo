---
name: install
description: Install OpenWiz from its one line, "Install OpenWiz from github.com/openwizdev/OpenWiz", then optionally run a resumable first fleet. Checks the machine, installs the verified prebuilt release (no Rust or Node), checks setup's connections, and on the first-fleet branch connects one repository and starts its fleet through launch-fleet. Use to install, repair, update or remove OpenWiz, or to start or resume a first fleet. For a project's docs/agents/ settings alone, use setup.
version: 0.2.0
---

# Install OpenWiz

The user pasted one line into their agent:

> Install OpenWiz from github.com/openwizdev/OpenWiz

Take them from that line to setup, then to their first fleet if they want one. Every step reads before it writes and reuses what an earlier one recorded, so a repeat or a fresh session resumes at the first unfinished step. Tools: OpenWiz's installer (`tools/install/install`, over its `contracts/install.v1.md`) and installed runtime (`contracts/setup.v1.md`), the agent CLI ([cli.v1](../../contracts/cli.v1.md)), and for the first fleet `grill`, `to-spec`, `to-tickets` and `launch-fleet`. This skill adds no installer, engine, approval or planner, and never runs `openwiz engine` or `openwiz fleet tick`.

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

## Guards

- **Install permission is not work approval.** Installing or finishing setup approves no spec, plan or start. The first fleet needs the user's spec confirmation, exact-plan approval and a separate yes to start. Never write, fake or infer an approval, or ask for blanket consent.
- **Show every effect, then wait for a yes to exactly it.** Sign-in, the App or its skip, project settings, the brain, phone access, the demo repository and the launch each preview first; confirm with that preview's own `--yes` or `--yes --operation <id>`.
- **Credentials stay out of the conversation.** Never ask for a key or token in chat or put one in a prompt, argument, URL, log, issue or file. Keys go only through the tools' protected setup, into owner-only state on this computer or CloudRoom's secret store. Save the user's exact words only under [open-development](../../contracts/open-development.v1.md).
- **Uncertain is never retried blindly.** Run the same command again: it reads its record first and never repeats an effect.
- **Read JSON and exit codes, never a screen.** Run installed programs by absolute path. Python 3.9+ only: no Rust, Cargo, Node, npm or source build; if a step seems to need one, stop and say so.
- **Free now; other charges are separate.** OpenWiz is free now. Paid plans come later. CloudRoom and model charges are separate and not included. More Cloud Credits are CloudRoom's own plan, from `https://cloudroom.dev/pricing`. Referral verification is unavailable. No referral is applied. Never add a code or parameter to that link.

Keep `<root>` (default `$HOME/.local/lib/openwiz`), and the `build` and `state_root` paths `install` prints as `<build>` (also `build=<build>` in the shell) and `<state>`, all absolute and owner-only. Run runtime tools with `python3 -I -B` and `OPENWIZ_STATE_DIR=<state>`, and pass `--state-dir <state>`.

## 1. Preflight

```sh
openwiz=<private temporary folder>/openwiz
git clone --depth 1 https://github.com/openwizdev/OpenWiz "$openwiz"
python3 -I "$openwiz"/tools/install/install preflight
```

It reads Python, the target, disk space and whether `room-cli`, `gh` and `git` are on `PATH`; it runs none of them. Exit 5 names each missing item and its `next` step: tell the user plainly (CloudRoom: install the app and sign in; `gh`: install it and `gh auth login`).

Done when preflight passes, or the user has each next step.

## 2. Verified install

```sh
python3 -I "$openwiz"/tools/install/install download --target <target> --dir <private download folder>
python3 -I "$openwiz"/tools/install/install install --assets <private download folder> --target <target> --root <root>
```

A refusal leaves the previous build selected: report it, never work around it. A checksum proves the files are the release's, not who published them.

Done when `install` printed `"activated": true` with the version, target, `build` and `state_root`.

## 3. Setup and connections

```sh
python3 -I "$openwiz"/tools/install/install open --root <root> --browser
python3 -I -B "$build"/runtime/setup/setup.py check --state-dir <state>
```

`open` serves only this build's setup page on `http://127.0.0.1:7370/setup` (add `--state-root <state>` for a custom state). Read each component's state (`verified`, `missing`, `refused`, `unknown`) and `next` step; only the check marks a component ready. Reuse the user's current CloudRoom sign-in and harnesses. GitHub, the App, the project and its brain wait for the repository the user picks under First fleet. Phone access is optional: `python3 -I -B "$build"/runtime/access/access.py`, as its README says. Run `check` after each change.

Done when CloudRoom reads `verified`, or the user chose to stop with the remaining `next` steps.

## 4. Explain

Say this before asking about a project, once:

> You bring an **idea**. I **grill** you with a few quick questions to settle it, then write it up as a **spec** for you to confirm. The spec becomes small **tickets**, a plan you approve as a whole. Each ticket gets its own **builder**, an agent that writes the code on its own branch. A **reviewer** from a different model family reviews each pull request independently, and approved, green work **merges** by the project's rules. Nothing starts until you approve the plan.

Done when the user has seen it.

## 5. First fleet

Continue only if the user wants a first fleet; otherwise finish with the install and any outstanding setup steps. Pass one owner-only `--state <file>` outside the project to every `first_fleet.py` command (`python3 <this skill's folder>/scripts/first_fleet.py`), from the project's clone. To resume, run `first_fleet.py next --state <file> --setup-state <state>`: it reads only that file and the repository setup prepared, and prints the first unfinished step and its command. Exits: 0 done, 1 read failure, 2 usage, 5 refused, 6 uncertain, 7 busy, 10 state unavailable, 12 preview awaiting `--yes`.

### 1. Choose a project

Offer three or four fun, one-line ideas made up for this user, plus "your own idea". Then ask where it goes:

1. **A new private demo repository** (recommended). Sign in first: `python3 -I -B "$build"/runtime/setup/github_login.py sign-in --state-dir <state>` (it reuses a verified login; signed out, preview, then `--yes` for GitHub's browser page). Then `first_fleet.py create-repo --repo <owner>/<name>` previews the repository and its one README commit; on the yes, add `--yes`. Exit 6: run it again. The user makes or picks its CloudRoom project.
2. **An existing repository:** confirm it, and that the fleet opens branches and pull requests there, then run `first_fleet.py select --repo <owner>/<name>`.

Done when the idea and one repository are chosen and read back. There is no second repository.

### 2. Connect

For that repository, each tool previews and applies only on the yes (`--yes`, or `--yes --operation <id>` from its preview):

1. **Sign-in:** `github_login.py sign-in --repository <owner>/<name> --state-dir <state>`. Only the account and push-access read-back count.
2. **Prepare:** `setup.py prepare --state-dir <state> --repository <owner>/<name> ...` with the CloudRoom project and the harness, model and effort the user picks from `openwiz models --json`, one question each, with a recommendation.
3. **The App, or an explicit skip:** recommend the App, set up as `setup`'s "The App" says. Only the user's answer selects `github_login.py skip-app`; an App failure never becomes a skip.
4. **The brain:** `<build>/openwiz init --repository <owner>/<name> --state-dir <state> --json`, then `--yes --operation <id>`. Say in one line where it went; the user merges its pull request. For a public repository's private companion, run `first_fleet.py decisions --setup-state <state>`, then `--yes`, and ask the user to restart the OpenWiz server.
5. **Carry it:** `setup.py check --state-dir <state>`, then `first_fleet.py continue --setup-state <state> --explained`. It refuses, naming each component that is missing, refused, unknown or stale, and withdraws what it carried before; follow that `next` step and run both again.

Done when `continue` prints the carried setup and the acting identity.

### 3. Grill

Run `grill` briefly: one or two rounds of at most three questions, each with a recommendation, steered to 4 to 7 small, mostly independent tickets. Save it as `grill` says.

Done when the user confirms the grill's summary.

### 4. Choose the agents

Harness, model and effort were answered at Connect. Ask only where the agents run: Cloud (recommended; it uses Cloud Credits) or Local. Save `openwiz models --json` privately, then run `first_fleet.py choose --options <saved file> --from-setup --agents cloud|local` (without a carried setup, ask the three and pass `--harness --model --effort`). Then run `setup` so both builder tables name exactly these settings, sourced to the user's decision; setup keeps reviewers in the other family. Then run the same `choose` again: it reads the tables back. Local is not available yet: say so, and offer Cloud or stopping.

Done when the choice is recorded and the builder tables match it.

### 5. Plan

Run `to-spec` and wait for the user's spec confirmation. Run `to-tickets` for 4 to 7 small tickets with disjoint owned paths and few arrows, then wait for the user's exact-plan approval; a change request is not an approval. Then run `first_fleet.py spec --spec <N> --repo <owner>/<name>`.

Done when the approval record on the spec is current and `spec` saved it.

### 6. Launch

Preview with `first_fleet.py launch --spec <N>`. Show its effects (one fleet thread and its loop, the frontier's builders and their other-family reviewer, Cloud Credits unknown until measured) and ask for a yes to exactly those. On the yes, run it with `--yes --confirm <the digest it printed>`. It refuses if anything changed since the preview: run `continue` or preview again and ask again. Exit 6 is uncertain: run it again to read the fleet record, never start by hand.

Done when the start is recorded, or recorded uncertain and reported so.

### 7. Watch

Run `first_fleet.py progress --spec <N> --openwiz <absolute path to openwiz>` when the user asks, and point them to the cockpit's Home and First hour pages. Unknown stays unknown, and a count is never a first merge. Reviews and merges follow on the fleet thread's loop. Then offer their next idea.

Done when the user has seen their agents' progress.

## Doctor

When setup or a fleet seems stuck, or the user asks whether setup is right, run the doctor from the project's clone:

```sh
python3 -I <this skill's folder>/scripts/doctor.py --repo <owner>/<name> --state-dir <state> --build <build> --openwiz "$openwiz" [--driver <the driver this machine runs>]
```

In order, it checks the labels, the App, that the acting login is a record author, the harness, the driver's `version` and the skills, through the checks that already exist. It only reads. Show each problem line as it is; its `Fix:` is the command that fixes it. A sign-in fix is the user's to run: show it, never run it. Exit 0 prints one all-clear line; 5 prints the problems.

Done when it prints all clear, or the user has each fix.

## Recovery and removal

If setup does not open, run `install status --root <root>` and `open` again; a failed bind never proves another page is OpenWiz's. To remove OpenWiz, stop only its own setup server and delete `<root>`; keep `<state>` unless the user asks. Removal revokes nothing: show the user how to uninstall the App or remove repositories from it, delete any phone-access tunnel or rule, and delete the fleet loops in CloudRoom. Never remove or revoke anything without their yes.
