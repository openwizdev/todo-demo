# O10 proof plan

What this ticket's evidence proves, in public form. The run records themselves (commits, counts, pins, helper reports, no-push checks and rulings) are kept in the private record; this file carries no run measurements or identifiers, and nothing in it is invented output standing in for a historical run.

## Claims and proofs

- **P3 / acceptance 1, scoped privacy.** O3's canonical privacy checker, with the required private literals, ran on a staging copy of every O10-owned public file: red at the starting commit, green after the edits. `privacy-red.txt` and `privacy-green.txt` beside this file are its saved safe outputs; the checker prints locations and rules without echoing a literal. This proves the privacy rules only on that owned, staged scope. It does not prove public ancestry, commit-range privacy, tracker execution, text inside binary images, the full future public tree, live behaviour or publication.
- **P4 / acceptance 2, public tracker instructions.** `skills/triage/test/test_public_records.py` guards copied standalone approval templates, decision routing and wayfind claim/release commands, red before the wording changes, then green. The regressions it catches: a copied quote-bearing approval, a builder answer or batch decision publishing exact words, and a thread-bearing wayfind claim or release. Independent full-diff review covers prose tests cannot prove and the privacy of auxiliary files.
- **Acceptance 3.** The affected static skill checks and script tests pass; the full workspace and browser suites ran only in CI.
- **Image provenance.** The UI-guidance checks refuse private links; private-file URLs were replaced by private-comment pointers. This is written-provenance evidence, not the canonical privacy scan.
- **Triage collector.** The fake-GitHub cases recognize an approval-first header and pointer followed by the AI marker, while pasted records, absent or file pointers and unrelated markers still appear as work.
- **O5 consumer seam.** `python3 skills/launch-fleet/scripts/fixtures/test-o10-triage.py` runs the fleet's batch cases against O10's producer on fake gh and synthetic records: the empty frontier without individual approvals, exactly the approved subset, O10's shape table and the rendered-record cases (valid, pasted, absent, malformed, file or leading-zero pointer, absent marker, unrelated later marker). Its saved output was removed from the package because it named a private source commit; running the command reproduces it. This is fixture integration evidence, not live proof.
- **Review R1, claim identity.** The instruction proof runs the skill's exact jq expression on synthetic GitHub-shaped comments with opaque node ids and URLs carrying numeric comment ids. After a release, the earliest remaining claim must hold. The reader keeps each comment's URL beside its body; the claim id is the URL's positive decimal comment suffix, kept privately and reused in the release, never the opaque node id. `r1-red.txt` and `r1-green.txt` are its saved outputs.

The other `*-red.txt` files beside this file are the saved failing-first outputs for the instruction, image-provenance and collector slices.

## Limits

- Tests check the instructions agents copy; they never execute a live tracker flow or replace the privacy checker.
- The spec's named grill was absent and was not recreated or read; the recorded spec confirmation, the approval and the merged O2 contract supplied the decisions.
- A helper-check hit during this work was resolved by an ops ruling that attributed one coordination write to another builder; it is recorded privately and grants no exemption elsewhere.
- No whole-tree, history, binary-image privacy, live, activation or publication pass is claimed. Exact-head CI and independent review gated the merge.
- This is an Infra skill and privacy change, so no product changelog sentence was needed.
