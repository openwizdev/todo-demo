# CLI v1

T1 of 0.0.12 (#1096), spec #1092, confirmed grill C1–C5 of
2026-11-05, kept in the private record. This is the compatibility
boundary for agents. [`cli.v1.schema.json`](cli.v1.schema.json) defines
`catalogue`, `error`, `help` and `loop_switch`.
Existing report schemas remain authoritative and unchanged.

**Implementation boundary:** T1 implements `help --agent` and human `help`.
T2 supplies the additive JSON help/errors and complete stream-selection runtime
proof. T3's `ui` and its capability result were removed in 0.0.16 (#776). A pinned
future result does not make its command or JSON form available today. The
catalogue describes shipped success forms; its `json` boolean and `flags` are
availability, never permission to run a write. No fixture proves live behaviour.

## Discovery

`openwiz help --agent` prints exactly one compact JSON document and a newline,
exits 0, reads neither source, stdin nor state, and creates nothing. It works
without a configured installation, repository, server, credentials or state
store. Human `openwiz help`, `--help` and `-h` print bounded usage without reads
or writes. Existing command-specific help aliases keep their parsing rules;
notably `fleet --help` is not implemented, and exact `loop --help`/`loop -h`
print loop-specific text. `help --agent` accepts no other operand or option.
Main ships the read-only `fleet tick --dry-run` and `fleet due --github-only`;
the catalogue includes these implemented forms. The executing `fleet tick` and
its `--expect-plan` were retired in 0.0.17 (#800, spec #786), and the `engine`
commands with them; neither is in the catalogue or human help.

For `ls` and `show`, any standalone `--help` or `-h` after the command selects
help before parsing other tokens, including after an unknown option, in a
separate value position (`ls --limit --help`), or after `--`. Embedded values
such as `--limit=--help` do not match. `fleets` defers ordinary argument errors
until the end, so later standalone help also wins, but an earlier non-UTF-8
argument refuses before help is reached. Arguments after its help token are
not parsed. Other forms retain their own catalogue help rules. These legacy
help rules are distinct from the syntactic JSON selector below.

The `openwiz.cli.v1` catalogue has `kind: catalogue`, shared `flags`, ordered
`commands` and `notes`. A flag definition has its name/aliases, arity
(`switch`, `value`, `delimiter`), whether `=value` is accepted, whether repeated values accumulate,
default (null means no default), and meaning. `repeatable: false` means no
accumulation; it does not impose a new duplicate-refusal policy. Each form
states its existing duplicate handling in `rules`. Each command form has:

| Field | Meaning |
| --- | --- |
| `name` | Stable form id, e.g. `send.preview`; not an extra subcommand |
| `argv`, `aliases` | Command/selector tokens and alternative entry forms, without program name |
| `flags`, `required_flags` | References to shared flag names; required selectors included |
| `arguments` | Positional names, required/repeatable booleans and value constraints |
| `stdin` | `never`, or `text_if_absent` (piped text only) |
| `effects`, `sources` | All possible effects of the form, including conditional staging/sweeping; external programs used |
| `results` | Success/outcome schema name, exact file/fragment, and when used |
| `exits` | Every documented normal exit and its contextual meaning |
| `examples` | Synthetic argument arrays, without program name; not shell code |
| `rules` | Cross-field requirements, refusals and compatibility details |
| `json` | Whether this shipped form supports the listed machine report |

Form names and flag definitions are unique; every reference resolves; every
required flag is available in its form. Aliases are exact token arrays. Defaults
can depend on the form (e.g. op-id required for lookup, generated for a write).
Positional requirements may be conditional (`project` versus `--project-id`);
`arguments.description` and `rules` carry those conditions without inventing a
default. Examples parse but are not promises that synthetic targets exist.
`--help`'s `-h` alias applies only to forms listing it. Loop-only help entry
forms are aliases of human help.

Effects are `none`, `source_read`, `state_read`, `state_write`, `send`, `create`,
`stage`, `delete`, `loop_switch`. `none` appears alone. `send` and `create` are
the existing guarded CloudRoom writes. The executing tick's `fleet_action`
effect was retired with it (#800). The tick's dry-run form reads and plans
only; due reads GitHub candidates only. Neither is new terminal authority.
Stage/delete/switch are local mutations, not a third CloudRoom write. `new.preview --attach` stages locally;
`attachment ls` sweeps an existing store and can delete expired/unfinished
copies. `send.check` reads only its record; `new.status` may additionally read a
created thread's start stage. Help has no effects even when state exists.

`sources` lists every possible external program, including conditional local
tools: `send`, `new` and `new.preview` use `/bin/df` when staging an `--attach`
path; both loop switches use local allowlisted `git` reads to resolve immutable
definitions. Listing a program does not imply every invocation calls it or
that it contacts a remote service. `df` is a free-space measure; these `git`
reads are local. Existing per-form effects and write authority stay unchanged.

## JSON selection and streams (T2 runtime)

Keep text mode and all existing success reports byte/semantically compatible;
no wrapper, renamed field or changed meaning is added to inventory, messaging,
new-thread, attachment or fleet reports. JSON may remain pretty-printed except
for compact agent help. A report with a nonzero outcome exit is still a report,
not a CLI error. Dispatch remains noninteractive for every explicit command.

Select JSON from actual option tokens, even if another option causes a handled
error. Never search the raw argument list or text for `--json`. Consume known
value options (both `--flag=value` and separate values) as values, even when the
value resembles an option. After the text delimiter `--`, all remaining tokens
are data. A malformed `--json=value` is a usage error, not a valid selection;
a separate syntactic `--json` still selects JSON. Non-UTF-8 input is refused
without lossy target/text conversion; select JSON only from genuine ASCII
option bytes in their syntactic positions. Repeated flags must follow the
existing parser's documented acceptance/refusal, not a new blanket policy.

Examples of selection, not permission to send:

| Arguments after the program name | Selected JSON? |
| --- | --- |
| `send thread-synthetic --json -- hello` | yes |
| `send thread-synthetic -- --json` | no: text |
| `send thread-synthetic --op-id --json` | no: invalid op-id value |
| `new --model=--json ...` | no: model value |
| `ls --unknown --json` | yes: handled usage error document |
| `attachment add -- --json` | no: path |

With selected JSON, every handled result/error writes exactly one document on
stdout followed by a newline. Stderr may carry sanitized diagnostics or the
existing generated-op-id notice; it never replaces or duplicates that document.
No terminal controls, progress text, help prose or banners may mix into JSON
stdout. Source stderr is not blindly copied. A rejected request performs no
send/create, but local attachment preparation and opened stores can remain.
In particular, `send`, `new` and `new.preview` can stage `--attach` paths before
validating uniqueness of the combined ordered attachment-ID list. An ID may
appear only once, including IDs produced by staging paths. Late duplicate-ID
rejection exits 2 without CloudRoom reads or send/create; the ready copies stay
on disk, and send's record store may already be opened. Earlier parse errors
can still leave state untouched. Never infer rollback from exit 2; preserve the
existing partial-preparation behavior and report it honestly.

A handled failure with no existing outcome report uses `openwiz.cli-error.v1`:
`command` (canonical command or `unknown`), numeric `exit_code`, and
`error: {kind, message}`. Kinds: `usage` (2), `read_failed` (1), `not_found` (3),
`store_unavailable` (10), `unavailable` (1, or 5 for an existing pre-write
refusal without a report). Messages are sanitized nonempty explanations, never
raw source output or secret configuration. Existing outcome reports take
precedence, including attachment preparation failures and partial reads.
Human help requested with syntactic JSON uses `openwiz.cli-help.v1` with `text`;
agent discovery remains the catalogue. Error objects do not imply that a
previous uncertain operation failed or can be retried.

**Broken-output limitation:** failure to write/flush stdout cannot reliably
carry a JSON error on that same stream. Do not attempt a second JSON document
on a partly written stream or substitute an error document on stderr. Preserve
the command's existing output-failure exit behaviour (some legacy paths cannot
report a failed write and keep their outcome code); a caller must check stream
integrity as well as exit. This is separate from a handled command error, and
T1 does not claim to repair those existing write/flush limitations.

## Fixed exits and existing results

Per-form meanings in `help --agent` are normative. Preserve the numeric values:
0 result/accepted/created, 1 read/context/output failure, 2 usage, 3 missing
session/target/attachment, 5 refused/failed, 6 uncertain, 7 in progress, 8
conflicting operation-id reuse, 9 possible duplicate, 10 unusable record/store,
11 no operation record, 12 new-thread preview awaiting `--yes`, 13 no offered
Cloud options, 14 attachment removal refused. There is no assigned exit 4.
No outcome code is silently converted to 0 for JSON. Preview/lookup/status use
their own subset in the catalogue; source partial coverage can still exit 0.
Accepted/sent never means work completed; created never means started.

| Forms | Existing schema file/definition |
| --- | --- |
| `ls`, `show` | `inventory.v1.schema.json#/$defs/envelope` |
| `send`, `send.preview`, `send.check` | `messaging.v1.schema.json#/$defs/report`, `preview`, `lookup` |
| `new`, `new.preview`, `new.status`, `models` | `new-thread.v1.schema.json#/$defs/report`, `preview`, `status_read`, `options` |
| Attachment add/list/remove, failed `--attach` preparation | `attachment.v1.schema.json#/$defs/add_report`, `list_report`, `remove_report` |
| `fleets`, `fleet` | `fleet.v1.schema.json#/$defs/envelope` |
| `fleet.tick.preview` | `fleet-tick.v1.schema.json#/$defs/envelope` |
| `fleet.due` | Currently human candidate lines only; no shipped JSON flag |
| `loop off/on` | This schema's `loop_switch`: existing unwrapped event, **no schema field** |
| `loop validate` | [loop-cli.v1](loop-cli.v1.md): `loop-cli.v1.schema.json#/$defs/validate_report` |
| `loop export` | [loop-cli.v1](loop-cli.v1.md): `loop-cli.v1.schema.json#/$defs/export_report` (LC3, #791) |
| `loop plan` | [loop-cli.v1](loop-cli.v1.md): `loop-cli.v1.schema.json#/$defs/plan_report` (LC4, #792) |
| `loop apply` | [loop-cli.v1](loop-cli.v1.md): `loop-cli.v1.schema.json#/$defs/apply_report` (LC5, #793) |

Tick (`--dry-run`) exits 0 after reporting its plan, 1 for a required global
read, setup, planning or output failure, and 2 for invalid options, including
`fleet tick` without `--dry-run` and the retired `--expect-plan` (#800). Due
exits 0 for candidate lines or quiet empty output, 1 on a failed global
read/output, and 2 for invalid options. Neither accepts repeated options,
`=value`, operands or a `--` delimiter.
T2's additive JSON form for due uses `openwiz.fleet-due.v1` (`fleet_due` here):
`candidates` is the same ordered list as the current text, each with positive
`spec` and positive `ticket` or null for a spec-level candidate. Empty is `[]`;
it grants no action authority. This schema does not advertise JSON as shipped.

The local switch event has exactly `loop_id`, `definition_revision`,
`repository`, `project`, `enabled`, `actor`, `at_ms`. IDs, revision, repository,
project, trusted actor and nonnegative millisecond time obey the existing
[loops contract](loops.v1.md) and switch store validation; the schema pins the
unchanged structural shape, not trust or authority. It is neither a
`openwiz.loops.v1` definition/run nor the durable `openwiz.loop-switches.v1`
wrapper. Switch exits are 0 saved, 1 context/target/lock/save/output failure,
2 malformed invocation. A busy 30-second lock wait saves no event; explicit
operator retry after refusal grants no new authority.

Switching local admission does not sample created-run occupancy or clear
persisted retirement. The service samples unsettled created runs once per
pass before dispatch planning and durably retires observed idle/error runs,
as the [loops contract](loops.v1.md#authority-budget-and-switching) specifies.
That accounting changes neither this switch event nor a created receipt,
budget charge or uncertain outcome. An explicit `new --status` is an operation
lookup, separate from the service's occupancy sampling.

## GitHub token (`github token`, GI5 #2547)

`openwiz github token --repository <owner/name> [--read]` is the token
command of [`openwiz.github-identity.v1`](github-identity.v1.md#the-token-command),
which stays authoritative. It reads the App key only from the
`OPENWIZ_GITHUB_APP_KEY` environment variable (the PEM file, standard
base64, one line, at most 4096 bytes decoded) and the App id from
`OPENWIZ_GITHUB_APP_ID` (a positive decimal, no leading zero). It signs one
App JWT, looks up that repository's installation (it must be this App's,
the repository owner's and `selected`), then mints one token for exactly that
repository with exactly the App's profile, or with `--read` exactly the read
profile. It reads no CloudRoom source and no OpenWiz state.

- **stdout:** the token and a newline, nothing else. **stderr:** on success
  `expires_at <unix seconds>`; otherwise one fixed `openwiz: github token: `
  sentence naming no value, provider body, id, key, JWT or token.
- **Exits:** 0 printed; 1 key or App id missing or unusable, no complete
  answer from GitHub, or output failure; 2 usage (`--repository` missing,
  repeated or not `owner/name`, `--read=value`, any other option or operand,
  `--json` included); 3 no installation of this App covers the repository
  (GitHub's 404); 5 refused: any other status, an installation outside the
  rules above, or an answer granting other permissions or repositories, or
  failing the expiry guards (expired, 300 seconds or less left, or more than
  3900 seconds away). `--help` or `-h` prints the command's help and exits 0.
- **Secrecy:** the key reaches the fixed `/usr/bin/openssl` signer only
  through an unnamed pipe's descriptor, the JWT reaches the fixed
  `/usr/bin/curl` only on stdin, both with a cleared environment; the token
  is passed to no child. Nothing stores the token. Linux only: elsewhere the
  key is unusable (exit 1).
- **Catalogue:** `help --agent` lists it as `github.token` (plain text,
  `json: false`; sources `/usr/bin/openssl` and `/usr/bin/curl`).

## Init (0.0.16, T5)

Pinned by [setup-onboard.v1](setup-onboard.v1.md#init) for T5 #635; **not
shipped**. Until T5 merges, `init` is absent from `help --agent`'s catalogue
and from human help, and this section grants no command, effect or authority.

```text
openwiz init [--repository <owner/name>] [--state-dir DIR] [--json]
openwiz init --yes --operation ID [--repository <owner/name>] [--state-dir DIR] [--json]
openwiz init --help [--json]
```

- **Runtime.** A thin wrapper over the matching package's
  `runtime/setup/init.py` through absolute `/usr/bin/python3 -I`, with no
  source checkout, `PATH` fallback, fixture environment or production override.
  `--help` reads neither source nor state. Options occur once with separate
  values; unknown, duplicate or non-UTF-8 arguments are refused. No stdin.
- **Forms.** Without `--yes` it reads and persists one `prepare_project`
  proposal (setup.v1's durable operation id and fingerprint) and prints its
  disclosed effects; it changes nothing on GitHub. `--yes --operation ID`
  applies only that exact current proposal. The repository defaults to the
  saved project's; there is no placement option or question. JSON output is one
  setup-onboard.v1 `init_result` or the existing CLI error document.
- **Effects** (catalogue words once shipped): `source_read` (GitHub's
  repository identity and visibility, existing companions, links and pull
  requests), `state_read`, `state_write`, and only with `--yes`, the disclosed
  GitHub writes of setup-onboard.v1: create the private companion, link it,
  open the brain's pull request, create the factory label.
- **Exits**, with the fixed values above: 0 proposal printed or applied; 1
  read, context or output failure; 2 usage; 5 refused (visibility unknown or
  ambiguous, denied or conflicting companion, unauthorized apply); 6 uncertain,
  held for reconciliation against the exact provider resource before any other
  call; 8 a stale or conflicting operation id; 10 unusable private state.
  Existing CLI error schemas and numeric meanings remain unchanged.

## No terminal app (#776)

The visual terminal app and its `openwiz.terminal-capability.v1` result were
removed in 0.0.16. `ui` is not a command: it is a usage error (exit 2) that
opens and starts nothing. No-argument `openwiz` prints the human help when
stdin and stdout are both terminals, and is a bounded usage error otherwise.
