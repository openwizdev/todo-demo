---
name: to-spec
description: Turn a confirmed grill into a spec issue, run to-tickets on it, and make the spec's narrated steering video. Use when a grill is confirmed or the owner steers a spec through the orchestrator. No human step between grill and fleet.
version: 0.2.0
---

# To spec

The owner's one active step is answering and confirming the grill (J202). From
there the orchestrator writes the spec, has [to-tickets](../to-tickets/SKILL.md)
cut and approve the plan by its own checks, and makes one video the owner
watches, then steers through the orchestrator. Nothing is asked between them.
In OpenWiz,
[the roads page](https://github.com/openwizdev/OpenWiz/blob/main/docs/agents/roads.md)
describes when this road applies.

## 1. Read the confirmed grill

Read the consumer project's tracker, domain and fleet settings in `docs/agents/`.
Read the grill privately, with its confirmation comment, the glossary, relevant
ADRs and the code. An unconfirmed grill, or a decision still open, goes back to
[grill](../grill/SKILL.md). Keep the confirmation's private-comment URL: it is
the plan approval's authority.

Keep exact replies, grill sources, thread IDs and private media in private
storage. Verify the private records repository and development tracker before
writing. Save public-safe summaries, issue text and visuals in public. An
unclear read or publication approval stops the related write.

## 2. Write the spec

Use the [spec template](spec.md). Name the outcome, proof and seams. Take the
headline from the grill's words, or `none` for infra. Use the grill's version
milestone, creating it if missing. Give the spec no ticket label. Create it,
read it back, and on a resume confirm any uncertain write before retrying. For
an already approved plan, use [the hold-first procedure](../to-tickets/changes.md)
before changing the spec.

## 3. Cut the plan

Run [to-tickets](../to-tickets/SKILL.md) on the spec now, with the grill
confirmation's URL. It ends with a machine plan approval on the spec, or a
refusal it fixes and re-checks. It never comes back to the owner.

## 4. Make the steering video

One animatic: what changes for a user and in the codebase, in the grill's
words, in build order (step 1 is what starts first in the approved plan). No
bench and no ticket graph: the graph stays on the spec as the agents' document.
Write `storyboard.json` in a work folder outside any repo, as
[video.md](video.md) says, then:

- `node "<this skill's folder>/scripts/animatic.mjs" build storyboard.json -o spec.mp4`
  checks the storyboard first and renders nothing on a refusal: fix the lines
  it names. Read `build/sheet.png`; done when it reads right and the report ends
  `no warnings`.
- Put the MP4 where the owner can play it with the issue's visibility. Public
  sharing needs publication authority. Confirm playback there, then
  `node "<this skill's folder>/scripts/animatic.mjs" link "$url"` gives the line.
- Post it as a spec comment, never in the body (that would change the plan's
  fingerprint): the link, then `Steering by comment is off for now: tell your orchestrator what to change (stop, reset, or anything else).`

## 5. Steer

Steering by comment is off for now (until OpenWiz #1402), so the owner steers
through their orchestrator: stop holds the fleet, reset re-cuts the plan through
[the hold-first procedure](../to-tickets/changes.md) and makes a new video, and
anything else is a steer to act on. A changed spec or plan always gets a new
machine approval and a new video.

Planning grants only what the machine approval records: every action gate
(publish, spend, secrets, deleting user data, cut-overs) still asks the owner.
Builders and other-family reviewers stay independent; starting, reviewing and
merging stay with their roles.

Credit: adapted from Matt Pocock's skills, the video from his `animatic` skill, under the MIT License; the notice and sources are in [NOTICE.md](NOTICE.md).
