# OpenWiz agent status contract, version 1 (`openwiz:status v1`)

Agents say what they are doing on their tickets, in one public format that any agent host writes and the OpenWiz app reads. The truth about a ticket's work is one **status note** per agent, edited in place. People set labels; agents don't set state labels. Building, in review and merged are read from GitHub. Its schema is [agent-status.v1.schema.json](agent-status.v1.schema.json). Its writer and checker is [`skills/launch-fleet/scripts/status.py`](../skills/launch-fleet/scripts/status.py).

Authority: spec openwizdev/OpenWiz#1223 (the app, v1), revision 4, and ticket AP1 #1254; the records spec's design B. Writers: build-ticket, review-ticket and launch-fleet (AP2 #1255). Readers: the app's pages (AP6 #1259, AP7 #1260). The app reads this contract, never an agent host.

## Labels

People set only five labels. They are gates, never an agent's progress:

| Label | Means |
| --- | --- |
| `spec` | The issue is a spec |
| `ready-for-agent` | Approved: an agent can take it once its blockers have merged |
| `ready-for-human` | A person has to act |
| `needs-info` | Waiting on the user (shown as "needs you"). The writer adds it while any live note on the ticket is `asking`, and clears it only when no live note is `asking` and the writer's own login added it last. A `needs-info` added last by anyone else is theirs, and stays |
| `held` | Held |

There are no `building`, `in-review` or `needs-you` labels; a writer never sets one.

## Read from GitHub

| What | Read from |
| --- | --- |
| Building | A live `working` note from a builder on the ticket |
| In review | An open pull request that closes the ticket, with its reviews and checks |
| Merged | The ticket's closing pull request has merged |
| Waiting on the user | `needs-info`, or a live `asking` note |

## The status note

One comment per agent on the ticket it works on. Its first line is exactly the **marker**:

```text
<!-- openwiz:status v1 -->
```

Then one `key: value` line per field, in this order, each key once; optional fields are left out when empty:

| Key | Required | Value |
| --- | --- | --- |
| `agent` | yes | The agent's kind: `builder`, `reviewer` or `fleet` |
| `state` | yes | `working`, `asking`, `done` or `stopped`; `stopped` may carry its reason, `stopped (<why>)` |
| `harness` | yes | The agent's harness, as its fleet settings name it, for example `Claude Code` or `Codex` |
| `model` | yes | The agent's model and effort, for example `Opus 5.5 Medium` |
| `skills` | yes | Every skill the agent ran for this note, each `<skill>@<version>`, joined by `, `: the skill's folder name and the version of the skills package it ran from (its `.claude-plugin/plugin.json` `version`), for example `build-ticket@0.1.2, launch-fleet@0.1.2`. A writer reports the skills its agent actually ran; there is no default. Each one must be a skill listed in the installed package's manifest, at that manifest's version: the package that supplies the writer. Which skills an agent ran is its caller's record (AP2) |
| `step` | yes | One short public sentence: the agent's last step |
| `time` | yes | When that step happened, UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `pr` | no | The ticket's pull request: `https://github.com/<owner>/<repo>/pull/<n>` |
| `preview` | no | A public `https://` preview page of that pull request, which the app shows as-is. Its host is a public domain name: never `localhost`, an IP address, or a `.local`, `.internal`, `.lan` or `.localhost` name. It carries no user, password, token, query (`?`) or fragment (`#`). An optional port is allowed |

Every value is one line of 1 to 300 characters with no control character; `harness` and `model` hold at most 60, and a `stopped` reason at most 100 with no parentheses. In `skills`, a skill's name is lowercase letters, digits and single hyphens, and its version is `<major>.<minor>.<patch>` in digits; nothing else (no path, no URL, no other word) is a skill.

Example (synthetic):

```text
<!-- openwiz:status v1 -->
agent: builder
state: working
harness: Claude Code
model: Opus 5.5 Medium
skills: build-ticket@0.1.2
step: opened the pull request; CI is running
time: 2030-01-02T03:04:05Z
pr: https://github.com/example/site/pull/42
preview: https://42.example-site.pages.dev
```

A note counts only when its author is one of the project's record authors: the `Record authors` row of `docs/agents/fleet.md`'s `## GitHub identity` table, compared case-insensitively. A comment with the marker from anyone else is ordinary discussion. A marker of another version, `<!-- openwiz:status v<N> -->` with N other than 1, or a note that doesn't read as above, is shown as **unknown**: a reader never guesses at its fields.

## Claims

- **Live:** a note is live while its state is `working` or `asking` and GitHub's `updated_at` for it is less than 30 minutes old.
- **Lapsed:** a `working` or `asking` note not edited for 30 minutes has lapsed. Its claim is gone. Its agent may edit it back to live only while no other live note of its kind holds the claim; otherwise the fence stops that agent. The note stays until the fleet stops it.
- **The oldest live note wins:** among the live notes of one kind (`agent`) on one ticket, the one with the lowest comment id holds the claim. Notes of other kinds don't compete: a fleet note never blocks a builder.
- **Re-read before each write:** a writer reads the ticket's comments again just before it writes. It stops (the fence) when its own note is gone, is no longer its kind, or is `stopped`, or when another live note of its kind holds the claim. That covers an older live note, and a newer one that replaced a lapsed note. An agent that stops posts a new note if it starts again.

## What it never holds

The status note is public. It never holds:

- **thread ids:** any `thr_` token, synthetic or not;
- **machine details:** any machine path. That means any absolute path of two or more parts (`/etc/openwiz/config.toml`, `/home/…`), and a home folder by any name (`~/…`, `$HOME`, `${HOME}`, `%USERPROFILE%`). It also means a Windows drive or share path (`C:\…`, `\\server\…`), a `file:` link, or a CloudRoom id (`proj_`, `prj_`, `mch_`, `usr_`, `acct_`, `auto_`, `cr_`). A repository path such as `skills/launch-fleet/scripts/status.py` is not absolute, and a URL's own path is not a machine path;
- **credentials:** a `token=`, `key=`, `secret=`, `password=`, `sig=` or similar assignment, a `password:` or `Bearer` value, or a known key shape (`gh?_…`, `github_pat_…`, `AKIA…`, `xox?-…`, `sk-…`);
- **private words:** anyone's exact words. A writer refuses any double quote mark (`"`, `“`, `”`) and any value that starts with `>`.

The writer refuses such text before any call to GitHub.

## The writer and the check

```sh
status.py write --repo <owner>/<name> --ticket <n> --agent builder|reviewer|fleet \
  --state working|asking|done|stopped [--why <text>] --harness <text> --model <text> \
  --skills '<skill>@<version>[, <skill>@<version>…]' --step <text> \
  [--pr <pull request url>] [--preview <https url>] [--time <YYYY-MM-DDTHH:MM:SSZ>] [--note <comment id>]
status.py check --repo <owner>/<name>
```

- **`write`** refuses a bad or private value, or a skill the installed package lacks, before any call (exit 2). It reads the record authors from the repository's `docs/agents/fleet.md`. It refuses (exit 2, nothing written) when its acting login, as GitHub's `viewer` names it, is not a record author. A token that can't name itself (a GitHub App's) is judged by the author GitHub gives the posted note. If that author isn't a record author, the writer deletes the note and exits 2. Then it re-reads the ticket and its comments, and:
  - with `--note`, edits that note, unless the fence stops it (exit 3, nothing written);
  - without `--note`, posts the agent's note, unless the new note would be `working` or `asking` while an older live note of its kind holds the claim (exit 3, nothing written). After posting it reads the comments back; if an older live note of its kind appeared meanwhile, it edits its own to `stopped (lost claim)` and exits 3;
  - reads the comments back and requires its note there, from a record author, with the text it wrote. Otherwise it exits 2 (`note <id> was posted but not read back`) before any label change;
  - re-reads the issue's labels, then adds `needs-info` while any live note is `asking`. It removes `needs-info` only when no live note is `asking` and the issue's events show the writer's own login added it last. It touches no other label. Each run settles the label from what GitHub shows now, so a retry after a failed label write repairs it.

  It prints `#<n>: <agent> <state>, status note <id> posted` or `… edited`. The agent keeps the id and passes it as `--note` on every later write. `--time` defaults to now.
- **`check`** reads every open issue, its labels, its comments and the pull requests that close it, and prints one line per mismatch, `#<n> note <id> <agent> <state>: <what GitHub shows>`. It writes nothing. Exit 0: no mismatch; 1: mismatches printed; 2: it could not read. A mismatch is:
  - a `working` or `asking` note on a ticket whose closing pull request has merged;
  - a lapsed claim: a `working` or `asking` note not edited for 30 minutes;
  - a live `asking` note on a ticket without `needs-info`;
  - a live note of a kind whose claim an older live note holds.
