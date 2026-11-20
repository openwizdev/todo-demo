# #1095 build checks

## Failing first

- `red.txt`, committed at 6a7f4eff: the affected skill tests failed on the missing skill, registration, phase reference, and the previously forbidden explicit-invocation settings (26 passed, four failed).
- `install-gate-red.txt`, committed at ddeb6cc6: a replacement instruction that installs immediately still satisfied the scattered-word check. The corrected check requires one visible operative installation paragraph; hidden comments, fenced examples and citations cannot satisfy it.

## Validation scope

The affected suite is `cargo test -p openwiz-tests --test checks skills`. Format is `cargo fmt --check`; clippy is `cargo clippy -p openwiz-tests --test checks -- -D warnings`. Only the test crate changed. No full workspace or browser suite runs locally, under the scoped-check policy; CI runs the repository's selected full checks. Exact hand-back head, tree and command results are recorded in the PR.

The generic skill-creator `quick_validate.py` was also tried. It rejects the ticket-required `disable-model-invocation` key because its format allowlist lacks that key. This is a validator incompatibility, not a passing check. The repository's own tests cover that exact required boolean and Codex's matching invocation policy, while preserving the existing ban for other skills.

No Cargo manifest or lockfile changed and no project dependency was added. Nothing was run live. External searches, runtime recommendation quality and installation remain unverified; these are instructions with static/text proof, not runtime observations.

## Helper and builder checklist

One Codex Terra High helper (fast service tier), Checklist and diff auditor, inspected the contract and changed paths at b25faefa56bfb5ba9aad0d23ac59cbb72c47f3d5. That content is now at 467b10ad after synchronizing with main before the first push. It reported one item: the installation gate text proof matched scattered words. The builder independently read the checker and checklist, reproduced the weakness red, and used that item; used 1, ignored 0, wrong 0. The helper was archived before its no-push check:

`clean #1095: nothing changed but the writes you named (branches 0, comments 3)`

Builder checklist: changed paths are owned; the MIT notice matches the existing adapted skills; both repository links and all relative Markdown links resolve through the static checker; no new dependencies, live calls, secrets or session content. ADR 0005's agent-invocation rule has a deliberate, documented ask-wiz-only exception required by the confirmed grill. The reviewer remains independent and is assigned by the fleet, not the builder.
