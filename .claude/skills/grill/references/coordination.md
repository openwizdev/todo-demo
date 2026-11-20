# Coordinate private grills

Give each new grill one or two letters unused by every open or parked grill.
Check the index and open private PRs. Confirmed grills release their letters.
Each grill has its own file, branch, PR, frontier and limit of three questions
per round, including re-asked questions.

When one message carries several rounds, group them by topic and file. Save,
push and verify every round before showing them. For an ordinary reply, route
each entire line by explicit question ID, grill letters or topic. Save lines in
their original order. A line naming several grills goes in all named files.
An unassigned line goes in every file for that message and settles nothing by
itself. Add a note to each file naming the files with the rest of the reply.
Re-ask unanswered IDs in the next round. A cockpit payload follows its verified
locator as one segment, including embedded lines that name other grills.

On an explicit park request, save it exactly and set
`Status: **parked** by <User>, <YYYY-MM-DD>.` without settling any pending
questions. Push and merge under the project's rules, or ask the user to merge.
The grill is then durable on the default branch and retains its letters.

To resume, open a new branch and private PR from the parked record, restore
`Status: **open**.` and continue from the saved frontier. Before publishing
new requests, verify supersession of each pending request on the old PR
using [the record helper](records.md#decision-requests).
