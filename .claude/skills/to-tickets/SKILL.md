---
name: to-tickets
description: Turn a spec into sized tickets and approve the plan by its own checks (links, relies, sizes, width, owned paths), recording a machine plan approval. Use when to-spec hands over a spec, or to re-cut a changed plan. Send unconfirmed grills to grill.
version: 0.2.0
---

# To tickets

The orchestrator takes a spec from [to-spec](../to-spec/SKILL.md) to a plan
approved by its own checks (J202): no owner question and no human approval in
between. In OpenWiz,
[the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Check the starting point

Read the project's tracker, domain, label and fleet settings in `docs/agents/`.
You need the spec and its grill confirmation's private-comment URL; read that
comment back privately. No confirmed grill: stop and use [grill](../grill/SKILL.md).
If the plan was already approved, [hold before editing](changes.md). Existing
contract holds keep their recorded release conditions.

Keep exact owner replies and private sources private. Verify tracker and private
repository before writing. A failed read or unknown state stops the write or
handoff it would authorize.

## 2. Cut the tickets

Cut end-to-end tickets as large as one builder can finish near-certainly in one
fresh context, sized S, M or L from first-pass review results on comparable
work. Cut for the shortest critical chain, then the widest graph (F6): disjoint
owned paths and only the arrows a ticket truly needs. To choose between two
cuts, write each as picture data and run
`python3 -I "<this skill's folder>/scripts/prefer.py" <cut A> <cut B>`: it keeps
the shorter critical chain, and the wider graph when the chains are equal.
Use a contract-first ticket for a shared interface, or say why none is needed.
Ask yourself the owner's old questions: is each ticket the right size, is each
arrow right, what should merge or split. The checks in
step 4 hold you to them. See [the ticket and graph inputs](tickets.md).

## 3. Write and verify the tickets

Create each issue without a ready label, blockers first, in the spec's
milestone, with its native parent and blockers. Read back every issue: title,
body, parent, milestone, labels and blockers. Draw the read-back graph with
`python3 -I "<this skill's folder>/scripts/picture.py" < graph.json > picture.md`
and post it on the spec: the graph is the agents' document, never the owner's.

## 4. Approve by the checks

```sh
sh "<this skill's folder>/check-links.sh" --read <spec> > graph.json
sh "<this skill's folder>/revision.sh" <spec> > revision.txt
python3 -I "<this skill's folder>/scripts/approve.py" --graph graph.json --revision revision.txt \
  --grill <confirmation URL> --number <N> [--changed "<what changed>"] --root . > record.md
```

Exit 0 prints the record, whose `width: chain` is the critical chain: the
longest run of open work, open blockers outside the spec included
([decisions.v1](../../contracts/decisions.v1.md#machine-plan-approval)).
Exit 1 names each failed check and prints nothing: fix the tickets, then run all
three again. Exit 2 is an unreadable input: read again. `N` is 1, or the latest
approval's revision plus one with `--changed`.

Post `record.md` with `gh issue comment <spec> --body-file record.md` as a
record author, read it back and compare it byte for byte. On an uncertain write,
read the comments before retrying. Only then apply each row's ready label (the
project's label for that role) and read the labels back.

## 5. Hand off

[launch-fleet](../launch-fleet/SKILL.md) starts the fleet from the machine
approval. Hand back to to-spec for the steering video. Builders and
other-family reviewers stay independent, and the fleet owns exact-head checks
and merge. The plan's outcome is the spec's lead time, from the spec's creation
to its last ticket's merge, for the war room:
`python3 -I "<this skill's folder>/scripts/lead_time.py" <collector JSON> --spec <spec>`
reads the collector's `flow` fact and keeps unknown unknown. Every action gate
(publish, spend, secrets, deleting user data, cut-overs) and the owner's
release go stay as they are. Older human-approved plans and approvals on their own follow [records.md](records.md); before
labelling one, `sh "<this skill's folder>/scripts/check-approval.sh" <spec>` must
validate its posted table. End the turn
while waiting.

Credit: adapted from Matt Pocock's skills under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
