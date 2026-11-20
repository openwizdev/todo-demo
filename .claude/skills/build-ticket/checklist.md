# Checklist of past findings

Before you hand back, check your work against every item here that applies to your ticket. Each line is a kind of mistake a review found before, written as the rule that avoids it, then the pull request and finding it came from (in the repository this skill was written in).

**How it grows:** each review that finds a new kind of mistake adds one line here, under its heading, citing its pull request and finding id. One line names a kind of mistake, not one bug.

## Reading outside input

- **A reader takes only the exact shape.** Data from outside (a command's JSON, a request body, a stored record) is read as an object, never as a positional array; with exactly its keys, each once (a repeated key is refused, never silently replaced); each of its own type; and an enum only as its plain string, never as a tagged object like `{"queue": null}`. Prove it with a table of good and bad inputs. (#91 S1; #90 round 2; #88 finding 4; #132 R2)
- **The contract and the code refuse the same values.** Run the same good and bad values through the schema and the code, and get the same verdict from both. (#90 finding 2; #88 finding 3)

## Guards

- **A guard fails closed.** A detector, scanner, allowlist or default refuses what it can't positively recognise: an unknown form, a partial value, a non-ASCII string. Prefer a type that can't hold a bad value to a check someone must remember. (#88 finding 2; #135 R1; #91 S2)
- **Prove each guard catches a real break.** Plant the violation the guard exists for and show it is refused; a test of clean input alone passes with a broken guard. (#135 R1; #141 R2)
- **A check reads the rule itself.** Match the operative line or row, never a word anywhere in the section: a citation or a comment can hold the same word. (#141 R2)

## Tests

- **Wait for the exact log, then read all of it.** A process can write its log line after it answers. Wait, with a time limit, until the log holds exactly the lines you expect, then check the whole log; never snapshot it right after the last answer, or while its writer still runs. (#91 S4; #68, fixing #67)
- **Assert exact counts.** "At least one" passes when lines or calls are missing: assert the exact number of each. (#91 S4, round 2)
- **Never race the clock.** Compare only what the test controls, never a measured time or a value at a clock edge. Wait on explicit states (an attribute, a log line, an answered request), never on text or a sleep, and hold every request a clock jump can start. (#63, fixing #62; #92 R3-5; #92 CI round 1, F-2; #92 CI round 2, V7)
- **Tests share nothing.** Tests that can run at the same time use their own temporary paths and state. (#27, fixing m06 and m08)
- **Red is committed before the fix.** Commit the failing proof and its log before the fix, so the history shows red came first. (#92 round 0, chronology)

## Evidence scripts

- **A runner fails on any unexpected result.** Every evidence runner and wrapper asserts each case's expected pass or fail (and, for a negative case, its expected finding id), checks the exit status of everything it calls, and exits non-zero on any mismatch. Try it with a checker that always passes: the runner must fail. (#141 R1; #136 R3; #138 R3)
- **Check each read separately.** One combined read hides another's failure: check each command's exit status and output on its own before using either. (#136 R4)

## State, retries and repeats

- **A read-only path never writes.** A lookup or a check opens nothing for writing and saves nothing. (#80 finding 1)
- **Re-check under the lock.** Read a record again once you hold its lock, and treat one that is gone as gone. (#80 finding 2)
- **One decision, one place.** Paths that decide the same thing (a preview and its send; every button that sends) share one function, so they can't disagree. (#80 finding 3; #92 R2-3)
- **Unknown stays unknown.** An outcome you can't confirm stays uncertain until its own record settles it; a later refusal or failure never lowers it. (#92 round 1, finding 2; #92 R2-2)
- **Save before you send.** Store what makes a retry safe (its id) first, and send only if the save worked. (#92 round 1, finding 3)
- **One action, one effect.** A repeat (a copied tab, a retry, a held key) reuses the same id and makes no second call. (#92 round 1, finding 1; #92 R2-1; #92 H-1)

## Commands and the web page

- **A printed command recreates the exact request.** Run it through a real shell in the test, with awkward input (a leading dash, a `~`, quotes, stdin), and check the bytes that arrive. (#132 R1; #132 R3)
- **Focus and announcements survive every state.** Controls stay mounted (disabled) while a request is out, focus never falls to the page, and every outcome is inside the live region. (#92 R3-3; #92 F-1)

## CI

- **Every CI edge runs everything.** The cheap path is for the one plain case only, read live. A rerun, a retarget, a draft marked ready, a stale head or base, or an odd value (a branch named `main-null`, a draft state of `"false"`) runs the full set. (#89 rounds 1 and 2; #89 round 3)
- **A test needs only what CI keeps.** If CI deletes files before it runs, a test that reads one of them must be on the list CI keeps. Run the full set on a pruned copy. (#89 round 3, the second reader)

## Reading ahead and shared files

- **Read ahead, build only yours.** Read the whole spec and the bodies of its other tickets, first those yours blocks, so your work fits them; never build their work. (#1313, grill UF4 (c); #1316)
- **Build against the contract-first ticket's shape.** Use its contract, types, schemas, fixtures and stubs instead of inventing your own; leave the seams later tickets need (a named function, a fixture slot, a stub), and name each one in the pull request's Facts. (#1313, grill UF4 (c); #1316)
- **In a `(shared)` file, only your own lines.** Change only this ticket's row or section, never another ticket's lines; a conflict with `main` is merged as build-ticket's step 5 says, keeping theirs. (#1313, grill UF2 (c); #1316)

## Claims and scope

- **Claim only what was observed.** A doc or a pull request promises nothing its evidence doesn't show; a branch or a pull request doesn't show an agent is running; anything unchecked says "unverified". (#131 R1; #136 R2; #135 R2; #141 R3)
- **Build the grill exactly.** No condition the user didn't decide (even one an adapted source had), no limit nobody asked for, and every path the decision allows. (#138 R1; #136 R1; #138 R4)
- **Every acceptance criterion, or a question.** Meet each one; if one can't be met, ask on the ticket instead of substituting or deferring it yourself. (#131 R1)

## Contracted grants and finite messages

- **Check sources, not asserted authority.** For an adopted ops-dispatch envelope/grant, independently read the complete approval and lifecycle history, recompute current source material and compare the actual whole diff, both rename sides, resolved files, owners and shared sections. A supporting name, copied digest, label or builder self-grant supplies no authority. Preserve the unchanged plan fingerprint and all protected gates. (#2188, P1/P2/P7)
- **Separate purpose from review.** Material/approval/rule changes invalidate a grant and terminal lifecycle events end it. A head-only change preserves valid purpose permission but requires fresh exact-head implementation review. (#2188, P2)
- **Consume and end.** On a finite authorized wake, check intended role/assignment, current approval/head, operation key and ordering before your own ACK. Transport is not acknowledgement/completion; unknown outcomes remain unresolved. Record bounded work and end without polling or resetting the review-round count (one review plus one re-check, then at most one fresh round). (#2188, P8)
