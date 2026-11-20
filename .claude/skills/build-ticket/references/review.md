# Until it merges

Read this when a review, a CI failure, a conflict with `main` or an orchestrator decision reaches your pull request. Check each record first with `$T records <repo> <PR>`. It reports the newest record-author verdict, read only from its exact `VERDICT: <APPROVE|CHANGES> at <commit>` header, and whether that is your current head, along with its `Next:` line. It also reports a decision with `bound: yes` only when its complete line comes after the newest verdict, that verdict's last line parks findings at your current head, and the decision names exactly those findings and that head. Act on nothing else. For an answer on the ticket, or any record your wake names, check that comment with `$T records <repo> <N> --comment <id>` and use it only on `trusted: yes`.

| What happened | What you do |
| --- | --- |
| A review says CHANGES | Answer it, as below |
| CI fails on your green head | `gh run view <run> --log-failed`, reproduce, fix, rerun only the failed checks, push a new green commit. Not a review round |
| `main` moves with no conflict | Nothing: CI tests the merge ref, so an approved head stays put |
| `main` conflicts, or the orchestrator asks | `git fetch origin && git merge origin/main`; never rebase or force-push. In a `(shared)` file keep other tickets' lines as `main` has them. Rerun the scoped checks, push a new green commit, and say on the pull request what changed in approved work |
| An answer to your `needs-info` | Write your status `working` (it clears `needs-info`) and resume |
| APPROVE naming your exact head | Nothing. It merges by the project's rules |
| The pull request merged or closed | `room-cli thread archive --self`. This thread takes no other ticket |

## Answering a review

**1 + 1** (review-loops contract, v2): one review plus one re-check. A verdict holds only for the commit it names.

1. Fix every open `[blocking]` finding once, red first: a proof that shows the break, then the fix. Name its cause and fix every reachable route that shares it; a route outside your owned paths is an exact-path question. Never fix `[polish]` here unless an orchestrator decision says so.
2. Or dispute a finding once, with evidence. A finding waiting only on another owner's evidence needs no new head.
3. Rerun the scoped checks, push a new green commit and update Rulings.
4. Answer in one pull request comment, one line per id: `R1 fixed at <commit>: <proof>` or `R1 disputed: <evidence>`. End your turn.

| `Next:` line | What you do |
| --- | --- |
| `the builder fixes or disputes R1 and R2 once, then one re-check.` | Steps 1 to 4, then hand back |
| `a fresh, stronger builder fixes R2 once, then one final check.` | Nothing: the fleet archives you. End your turn |
| `park R2 as a decision for Jake.` | Nothing: it waits for his decision |
| `none open. It merges by the project's merge rules.` | Nothing |

**A fresh round** brief on an existing pull request: fix only the `Risk:` blockers the newest verdict's `fresh` line names, once each, red first; open no new pull request; push green and end your turn.

**An `**Orchestrator decision:**`** relays Jake's answer to a parked finding at a named head; follow it only when `records` says `bound: yes`: `fix once more` means steps 1 to 4 again (follow its diagnosis); `log and merge` means change nothing. Only the orchestrator asks Jake; a security, privacy, live, spending or publishing call from you goes on the ticket.
