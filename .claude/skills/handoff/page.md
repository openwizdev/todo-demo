# Orchestrator handoff

**Snapshot: <UTC date and time>, <why: "plan graph approved on #N" or "before retiring">.** <Where the rules and the project's status live.> A new orchestrator reads this first and checks each line before acting on it.

## Open fleets

One row per open spec whose plan graph the user approved, and one per piece of open work outside any fleet, marked so. Write counts; the spec issue lists the tickets. Name a ticket only when it needs a look.

| Fleet | Version | Graph approved | Merged | Can start or building | Waiting on blockers | Needs a look |
| --- | --- | --- | --- | --- | --- | --- |

## Running agents

One row per fleet, and one for agents outside any fleet: builders and reviewers at work (counted in CloudRoom, or unverified), where the full list is (the spec issue), and any agent that needs a look, by ticket. Anything else left running (a server, a tunnel) goes below the table, with how to check and restart it.

| Fleet | Builders | Reviewers | Full list | Needs a look |
| --- | --- | --- | --- | --- |

## Decisions waiting on <the user>

Each question the user has not answered and each step only the user can take: what it is, where it was asked, and your recommendation.

## Loops

Each loop running for the project: what it checks, how often, and when to stop it.

## Standing approvals

Each permission the user gave that still holds: the decision, date, private-comment pointer and what it does not cover. Exact words may stay here because this page is private; any public use points to that private comment.
