# GitHub identity v1 (`openwiz.github-identity.v1`)

GI3 of spec #2537, the App work's contract-first ticket (#2545). This contract
covers the factory's own GitHub identity: one OpenWiz App and where it is
installed, the Cloudroom secret that holds its key, the `openwiz github token`
command, who authors commits, and what each role does as the App. GI4 (#2546)
builds the setup, GI5 (#2547) the token command, GI6 (#2548) is Jake's install
and GI7 (#2549) the switch. They build to this contract.

**This contract grants nothing.** It authorizes no App registration,
installation, credential, secret, token mint, live read or write, push, merge,
spending or permission change. Each of those stays with its own ticket and its
existing approval. A fixture or test that passes here proves the contract is
consistent, never that any of it is live. `contracts/setup.v1.md`,
`contracts/agent-github-reads.v1.md` (`openwiz.agent-github-reads.v1`) and
`contracts/open-development.v1.md` remain authoritative where they apply.

## The pin

The JSON block below is the machine-readable pin.
`tools/github-app/test_identity_contract.py` checks it against the registered
manifest and the reads contract. The prose explains it. Where they disagree,
the contract is wrong and must be fixed.

```json
{
  "schema": "openwiz.github-identity.v1",
  "authority": {"installation": false, "credential": false, "live": false},
  "app": {
    "count": 1,
    "name": "OpenWiz",
    "visibility": "public",
    "token_minting": "owner key only",
    "permissions": {
      "metadata": "read",
      "contents": "write",
      "issues": "write",
      "pull_requests": "write",
      "checks": "read",
      "actions": "read"
    },
    "events": [],
    "webhook": false
  },
  "read_permissions": {
    "metadata": "read",
    "contents": "read",
    "issues": "read",
    "pull_requests": "read",
    "checks": "read",
    "actions": "read"
  },
  "installations": [
    {"account": "jparker2006", "repository_selection": "selected",
     "repositories": ["jparker2006/ClosedWiz"]},
    {"account": "openwizdev", "repository_selection": "selected",
     "repositories": ["openwizdev/OpenWiz", "openwizdev/WizPlugins", "openwizdev/WizSkills"]}
  ],
  "secret": {
    "name": "OPENWIZ_GITHUB_APP_KEY",
    "holds": ["private_key"],
    "encoding": "base64 of the PEM file, one line"
  },
  "public_ids": {
    "app_id": "OPENWIZ_GITHUB_APP_ID",
    "installation_id": "resolved per repository from GitHub, never stored"
  },
  "token_command": {
    "argv": ["openwiz", "github", "token", "--repository", "<owner/name>", "[--read]"],
    "auth": "installation",
    "stdout": "token",
    "stderr": "expires_at <unix seconds>",
    "read_flag_permissions": "read_permissions",
    "max_lifetime_s": 3900,
    "min_remaining_s": 300,
    "stores": false,
    "exits": {
      "0": "token printed",
      "1": "context or read failure",
      "2": "usage",
      "3": "repository not installed",
      "5": "refused"
    }
  },
  "authorship": {
    "author": "user",
    "committer": "user",
    "email": "<id>+<login>@users.noreply.github.com, id and login read from GitHub"
  },
  "roles": {
    "builder": ["push branch", "open pull request"],
    "reviewer": ["comment"],
    "manager": ["comment", "label", "merge"]
  }
}
```

## The App

One public App for the whole factory, named OpenWiz, with no App per role
or per spec (public: assumption A2, under "The installations"). It keeps the established permission profile, unchanged:
`tools/github-app/manifest.json` and `contracts/setup.v1.md`. That is Metadata
read; Contents, Issues and Pull requests write; Checks and Actions read. It
has no webhook, subscribes to no events and has no other permission. Changing
the profile is out of scope for this spec and needs Jake's approval.

**Read-only uses get the read profile.** Any use that only reads asks for a
token downscoped to the read profile above. That profile is
`openwiz.agent-github-reads.v1`'s, every permission `read` (C9's rule: a read
never carries write permission). A token is never wider than its use.

## The installations

The App is installed on selected repositories only, never on all of an
account's repositories:

| Account | Repositories |
| --- | --- |
| `jparker2006` (Jake's account) | `jparker2006/ClosedWiz` |
| `openwizdev` (organisation) | `openwizdev/OpenWiz`, `openwizdev/WizPlugins`, `openwizdev/WizSkills` |

Each installation has its own request budget. This table is our factory's.
It binds no one else's, and no other repository is in scope.

**The App is public (assumption A2, #2558 R1).** GitHub lets a private App
install only on the account that owns it. One App on two accounts, as above,
must therefore be public. Public changes only who *may* install it, never
what it can do. It keeps the same permissions and installs on selected
repositories only. Only the owner's key, the Cloudroom secret below, mints
its tokens. An installation by any other account gives that account nothing,
and our factory uses only the installations it names here. The registered
manifest still says `"public": false`; reconciling that line is GI4's
(#2546). If Jake decides otherwise, this pin flips back to private, and the
installation design returns to the plan.

A stranger's factory registers its own App from the same definition, with
its own key, through the same setup. It installs that App on the account
and repositories it names, also selected only.

## The secret and the public ids

The App's private key lives once, as the Cloudroom secret named
**`OPENWIZ_GITHUB_APP_KEY`**. It holds the private key only, nothing else.
The value is the PEM file GitHub returns, base64-encoded (standard alphabet,
no line breaks), so it fits one dotenv line. The user gives it once and never
replaces it. Rotating or revoking it follows the existing protected secret
handling.

`openwiz` reads the key only from that secret as Cloudroom delivers it: the
environment variable of that name in the agent's process, from Cloudroom's
owner-only (0600) dotenv file. That file lives outside any Git working tree.
The key never enters chat, an issue, a pull request, a prompt, a process
argument, a URL, a log, an error, a fixture or the repository. Nothing writes
it to disk anywhere else, and no copy remains after setup.

The App id and the installation ids are **public identifiers, not secrets**.
They are still never written into this contract or its fixtures.

- **App id:** the public variable `OPENWIZ_GITHUB_APP_ID`, which setup writes
  beside the secret. On a host with OpenWiz state, it also lives in the
  existing `<state>/service/app/app.json`, and the two must agree.
- **Installation id:** never stored. The token command resolves it each time
  from the named repository. It authenticates as the App, asks GitHub for that
  repository's installation, and checks that the installation's account owns
  the repository and that its selection is `selected`.

## Each user's own App and the factory's (0.0.16)

Spec #625's [setup-onboard.v1](setup-onboard.v1.md) extends this contract
compatibly; the pin above is unchanged and still describes the **factory's**
App. J48 (Jake, 2026-11-14) settles that each user's own OpenWiz App is private
by default and installable only on its owner's account, while the current
factory's multi-account App stays public.
Private record: https://github.com/jparker2006/ClosedWiz/issues/325#issuecomment-6869926983

- **Two modes, never inferred.** A user's own App is `mode: user`,
  `visibility: private` on its default setting. The factory's App is
  `mode: factory`, `visibility: public`, through an explicit separate setting
  that is never a default. A repository outside the user App's owning account
  never causes an automatic switch to a public App, and nothing changes the
  factory's existing App or its installations.
- **The owner boundary is enforced where tokens are minted.** For a user App,
  the token command and the adapter accept an installation only on the App
  owner's account, for a repository that account owns, selected repositories
  only. Another account is refused like any installation outside the rules
  above. The permission profile, read downscoping, lifetime guards, exits and
  user authorship are unchanged.
- **The explicit login path.** When the owner explicitly skips the App, setup
  records that the factory acts through their verified personal login
  (setup.v1). That is a separate, visible choice: this command still never
  falls back to another identity, and an App failure or revocation never
  selects the login path.
- **Key delivery and the one temporary key file.** The preferred route hands
  the converted key straight to the protected secret through the CloudRoom
  agent-side save-secret contribution, once it ships and is observed; it leaves
  no key file. Until then the supported route is one protected paste
  (`docs/agents/github-app.md`, step 4): the converted key is discarded, GitHub
  generates a replacement key that the owner's browser downloads, the owner
  encodes it to one line, pastes it into CloudRoom's own protected prompt and
  deletes the download. That owner download is the one explicit exception to
  "nothing writes it to disk anywhere else": it is outside every OpenWiz
  component and Git tree, temporary, deleted after provisioning and counted
  among the owner's actions. No OpenWiz component writes, reads or keeps it,
  and it is never described as a no-download route.

## The token command

```text
openwiz github token --repository <owner/name> [--read]
```

It mints one installation access token for the installation that covers that
repository, scoped to that one repository.

- **Permissions:** without `--read`, exactly the App's profile; with
  `--read`, exactly the read profile. GitHub's answer must grant exactly what
  was asked, for exactly that one repository, or the command refuses.
- **stdout:** the token alone, on one line, so `GH_TOKEN=$(openwiz github
  token ...)` and git's credential helper can use it as is.
- **stderr:** on success, one line, `expires_at <unix seconds>`. On failure,
  one fixed plain sentence for that exit, with no provider body, URL, id,
  key or token.
- **Guards:** it authenticates as an installation only, never as an App user
  and never with a personal or `gh` login token. The App JWT is used only to
  look up the installation and mint the token, and is never printed. It
  refuses an expired token, and a token whose remaining life is 300 seconds
  or less (the adapter's refresh boundary). It also refuses a token claiming
  more than 3900 seconds (GitHub's hour plus five minutes of clock skew).
  Nothing stores the token: no file, cache or log. Each call mints a fresh one.
- **Secrecy:** the key and the token never reach a process argument, a URL, a
  log, an error or any output except that one stdout line. The existing
  signing and exchange helpers (`/usr/bin/openssl`, `/usr/bin/curl` in
  `crates/adapters/github/src/app.rs`) get the key or the JWT only through a
  pinned descriptor, a pipe or stdin, with a cleared environment, never in
  arguments. The token is passed to no child process.

| Exit | Meaning (`contracts/cli.v1.md`'s fixed values) |
| --- | --- |
| 0 | Token printed on stdout, its expiry on stderr |
| 1 | Context or read failure: secret or App id missing or unreadable, GitHub unreachable, or output failure |
| 2 | Usage: bad or missing `--repository`, unknown option |
| 3 | The repository is not covered by an installation of this App |
| 5 | Refused: GitHub refused the exchange, granted different permissions or repositories, or the token failed the expiry guards |

Nothing is uncertain: no token is kept, so a lost reply is a failure (1),
and the next call mints again. The command never falls back to another
identity. A caller that falls back to today's path when the command fails
(GI7) says so on stderr. Reads migrated under `openwiz.agent-github-reads.v1`
keep that contract's rule of no silent user-quota fallback.

## Authorship

Every commit is authored and committed as the user, so the contribution
credit stays theirs. The name is the user's GitHub login, and the email is
their GitHub noreply address, `<id>+<login>@users.noreply.github.com`. The id
and login are read from GitHub (`GET /users/<login>`), never guessed. The
App's token only carries the push. Nothing is authored by or credited to the
App.

## Roles

Each role uses an App token minted when it needs one, with `--read` for
read-only uses:

- **Builders** push their branch and open its pull request.
- **Reviewers** comment.
- **Managers** comment, label and merge. They merge only under
  `docs/agents/fleet.md`'s standing merge rules. A repository rule that
  refuses the App stops for Jake, and nobody bypasses it.

Jake keeps his own account for his own actions (approvals, settings). The App
profile has no Workflows permission, so a push that changes
`.github/workflows/` stays on today's path. The App never pushes one.

## Fixtures and the test

`contracts/fixtures/github-identity/` holds synthetic fixtures only:
`secret.json` (the secret's name and what it holds, with no value),
`token-exchange.json` (a write and a `--read` token request and answer, for
GI5's fake exchange) and `commit-identity.json` (a GitHub user and the author
line it gives, for GI7). Owners, logins, ids, times and tokens in them are
synthetic placeholders. `red-run.txt` is the test's failing-first run.

Run `python3 -I tools/github-app/test_identity_contract.py`. It is offline,
uses no credentials and checks:

- the pin's App profile, events and webhook against `manifest.json` (not its
  visibility: A2, above);
- that one App installed on more than one account is public;
- the read profile against the `permissions` constant in
  `agent-github-reads.v1.schema.json`;
- the installations, token guards and exits as pinned;
- that the fixtures agree with the pin, including each exchange answer and its
  expected exit, stdout and stderr against the token guards;
- that neither this file nor the fixtures hold a PEM key, a GitHub token or
  JWT, a secret assignment or any number long enough to be a real id.
