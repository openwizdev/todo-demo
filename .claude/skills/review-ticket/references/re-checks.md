# Re-checks and the final check

Read this when `review.py pin` prints `review re-check`, `review final` or `review log-and-merge`. Each pull request gets **one review plus one re-check** (1 + 1, the project's review-loops contract, v2), at most one fresh round and its final check. The fresh round never resets the 1 + 1.

A re-check reads only:

- **the open blockers** `pin` names, at the new head;
- **the code changed since `last read`:** `git diff <last read> <head>`. If the builder merged `main` in, judge only what changes this pull request's own work. Code unchanged since your last read is not reviewed again.

A re-check never opens new narrow cases. In the changed code a new real-user path or a new security, privacy or data-loss risk still blocks, as a new finding numbered from `next id`; anything else there is polish.

**The one exception:** a security, privacy or data-loss risk you find in unchanged code is still raised, as a new blocking finding whose `Risk:` line states it. No other new finding goes on a file the change since `last read` leaves alone; `review.py check` refuses it.

1. **Read the builder's answers** since your last report, from record authors only. Each open id was fixed, or disputed once with evidence.
2. **Give every earlier id one status,** in id order, in place of its finding:

   | Status | When |
   | --- | --- |
   | `resolved at <short commit>: <how you checked>` | It is fixed |
   | `withdrawn: <why the builder's evidence holds>` | The dispute convinced you |
   | `still open after the re-check: <why>` (or `after the final check`) | The fix didn't fix it |
   | `disputed, kept: <why the evidence doesn't hold>` | The dispute didn't convince you |
   | `still open after the re-check: <why>. Logged as follow-up #<issue>.` | A `User path:` blocker still open, logged |
   | `Polish issue: #<issue>.` | A polish finding, already filed |

   An open or logged blocker restates its `User path:` or `Risk:` line under it. An open blocker waiting only on another owner's evidence keeps its id, names that owner and the event it needs, and closes like any other.
3. **Run the three checks on the changed code** under the rule above.
4. **Mark every ruling again,** keeping earlier marks; a newly overturned one takes the next id.
5. **Close the loop.** Each blocker still open after the re-check (still open, `disputed, kept`, or new in the changed code):
   - with a `User path:` line is **logged**: file it with `review.py follow-up ... --logged re-check --user-path "<its line>"` (or `--logged "final check"`), and end its status `Logged as follow-up #<issue>.` A logged blocker is not open.
   - with a `Risk:` line stays open, is never logged, and goes to one fresh, stronger builder: `Next: a fresh, stronger builder fixes R2 once, then one final check.` At the final check it parks for Jake: `Next: park R2 as a decision for Jake.`
   - with nothing open: `Next: none open. It merges by the project's merge rules.`
6. **Post** as in step 4 of the skill. The second paragraph starts `Re-check of <the open ids> and the code changed since <short commit>, by <harness, model, effort>. CI green on this commit: <checks>.`, or `Final check of ...` after the fresh round. `review.py check` refuses a builder line at a re-check, an unlogged `User path:` blocker, a logged `Risk:` blocker, a dropped or renumbered id, and a new finding on unchanged code without a `Risk:` line.

**Jake's answer to a parked finding** is a record author's `**Orchestrator decision:**` after the park report, naming exactly the parked ids and the head they parked at. With none, `pin` keeps the park stop.

- `fix once more: R2 at <parked head>. Why: ...`: the builder pushes a new green head, and `pin` prints `review final` there. Check it as a final check: the parked ids and the code changed since.
- `log and merge: R2 at <parked head>. Polish issues: #<n>. Why: ...`: `pin` prints `review log-and-merge` at the parked head itself. Post one report at that head that grades each parked id `[polish]` with the status `Polish issue: #<n>.` from the decision, then `APPROVE` and `Next: none open. It merges by the project's merge rules.`

If `main` is merged in after your `APPROVE` and changes what you approved, `pin` starts a short re-check of that change: your `APPROVE` held only for the commit it named.

Synthetic re-check of the skill's example, after the builder fixed R1 at `9e8d7c6` and changed the export error:

```md
VERDICT: APPROVE at 9e8d7c6b5a4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d

Re-check of R1 and the code changed since 4b1f0c9, by Codex, Sol 6.2, Medium. CI green on this commit: build, test.

Intent: `pantry export` writes the whole cookbook to one zip and refuses to overwrite an existing file.

- **R1 [blocking]** resolved at 9e8d7c6: R1's command now prints `3`, and `cookbook.zip` is unchanged.
- **R2 [polish]** Polish issue: #58.
- **R3 [polish]** `src/export.rs:52` (Sweep) The new error says "file exist". Fix: "file exists". Polish issue: #60.

- **Ruling 1** upheld: the importer reads `photos/` in every export (`src/import.rs:14`).

Checked: R1 and `git diff 4b1f0c9 9e8d7c6` with the three checks. Ran: R1's command (prints `3`); `cargo test` (33 passed).

Next: none open. It merges by the project's merge rules.
```
