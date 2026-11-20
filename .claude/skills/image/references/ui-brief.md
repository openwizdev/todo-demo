# UI brief and content packet

Complete this before a UI target; save the filled brief, specification and packet
beside its prompt in the ticket's owned evidence path. Load the project's profile
rather than treating the example below as a universal brand. Missing approval or
conflicting source decisions go to the ticket's orchestrator.

## Project taste brief

```text
Project and surface:
Source revision: <approved public taste-summary revision; private-record comment pointer for private sources>
Approval: <decision in your own words, date and verified private-record pointer>
Hard rules: <requirements that every candidate must keep>
Explicit preferences: <paraphrased owner preferences, date and private-record pointer; no exact words>
Observed patterns: <what references show, without promoting them to requirements>
Rubric version: <fixed for this hill-climb stretch>
```

For OpenWiz, an example source revision is the private mood board as saved on
2026-11-02: the public summary records dark-only
as a hard rule; its explicit preferences include Terminal's structure, gold for
attention, room on PC and compactness on phone. Its landing direction is calm
space/wizard imagery with constellation lines, orbits and spell circles, never
cartoonish. Themes such as ASCII/dither are observed reference patterns,
not blanket requirements. Saved video posters do not prove watched motion.
Resolve the current approved revision for a real run; this historical example
must not silently override a newer profile.

Builders and judge receive the same public, synthetic brief. Keep credentials,
private source content and held-out evaluation material out of it. When the owner
changes a preference, retain the old brief and start a new rubric version at the
next stretch; do not change constraints halfway through a comparison pool.

## App brief

```text
Taste brief: <revision and rubric version>
Person: <who uses this screen, with synthetic context>
Task: <the job they came to finish>
Scope: <objects, time range and state this screen covers>
Main question: <the one answer the hierarchy should reveal first>
Important finding: <the fact requiring attention, from the content packet>
Next action: <one concrete action, within the product's authorised scope>
```

**Synthetic example:** a maintainer reviews a three-session sample inventory at
09:00 UTC on 2030-01-15. Scope: this sample project only. Main question: which
session needs attention? Important finding: session Birch is waiting for input.
Next action: open Birch's saved details. Use the pinned profile's dark surfaces,
terminal structure and gold attention role. The task drives the composition;
there is no assumption that a dashboard needs a marketing hero or a KPI row.

## Marketing brief

```text
Taste brief: <same project roles, revision and rubric version>
Audience: <who needs to understand the offer>
Promise: <one specific outcome the product can support>
Proof: <each public claim, its evidence and limits>
One action: <the single intended next step>
```

**Synthetic example:** an agent user wants to understand a session inventory.
Promise: see which sample session needs attention. Proof: the same three-session
packet rendered as an explicitly labelled example; it illustrates the layout,
not live reliability, customer adoption or a benchmark. One action: view the
sample inventory. Retain the app's dark surfaces and gold attention meaning;
use calm constellation linework for the surrounding landing composition if the
profile allows it. Product fragments keep the packet, states and labels used by
the app. Invent no testimonial or unsupported performance promise.

## Design specification

Write and critique these decisions **before generating the target**, then save
this specification beside the prompt. Use existing components and approved fonts
and tokens; named roles do not require a new library or token file.

```text
Type roles and fonts: <heading/body/label/data sizes, weights, line heights;
                      actual font files or installed fallbacks and loading check>
Colour roles: <ground/panel/overlay, primary/subdued text, control edge,
               focus/selection, attention and other semantic roles>
Spacing and radii: <the short set of spacing steps and corner sizes used>
Composition: <main regions, reading order, anchor edges and intentional space>
Density: <row height, padding and information visible for this person's task>
Phone changes: <at 390 CSS px: navigation, order, wrapping, tables and actions;
                compare with the desktop layout at 1440 CSS px>
Product-specific element: <one feature of this product that gives the page identity>
Held fixed: <approved brand roles, content packet, states and constraints>
```

For the synthetic app, the attention session can anchor the reading order; for
marketing, a faithful sample inventory can support the promise. Neither is a
new product requirement. Record actual values for a run, not adjectives such as
“premium”. Check whether the composition still serves the stated job before
requesting the picture. Compare target and render against these same decisions.

## Synthetic content packet

Use one small packet per design, shared by target prompts, app fragments and the
implementation fixture. Keep a source path/version with the brief. Inventory
objects before arranging panels; do not invent independent numbers for each
component. Reconcile displayed totals, changes, timestamps, rounding, repeated
labels and chart annotations from the same records. Correct image transcription
errors or list the exact mismatch alongside the target; do not alter a correct
fixture to match a generated typo. No invented adoption claims or testimonials.

**Objects, fields and units:** a sample project contains sessions with a synthetic
ID, name, status and snapshot time (UTC); counts have unit “sessions”. Statuses
here are illustrative content, not a proposed API enum. The packet is:

| Snapshot (UTC) | Session | Name | Status |
| --- | --- | --- | --- |
| 2030-01-15 08:00 | sample-a | Alder | Running |
| 2030-01-15 08:00 | sample-b | Birch | Running |
| 2030-01-15 08:00 | sample-c | Cedar | Idle |
| 2030-01-15 09:00 | sample-a | Alder | Running |
| 2030-01-15 09:00 | sample-b | Birch | Needs input |
| 2030-01-15 09:00 | sample-c | Cedar | Idle |

Worked display values at 09:00: **3 sessions; 1 running; 1 needs input; 1 idle**.
Since 08:00: running **−1**, needs input **+1**, idle **0**, total **0**. A status
chart, if needed, uses those same counts and period; it never adds a fourth item.
Birch is the attention finding in both brief examples. These literals provide a
reviewer an independent reconciliation, not a claim about live session data.

Name the edge variants and preserve their meaning across target and fixture:

- **Empty:** no session records; show an empty explanation, not a failed load.
- **Zero:** the baseline snapshot has 0 sessions needing input; keep a real 0.
- **Long:** replace Cedar's name with “Cedar — documentation and compatibility verification”; retain its identity and readable action at phone width.
- **Sparse:** only Alder is present; do not stretch it into a seemingly full queue.
- **Missing:** Cedar's snapshot time is unavailable; label it unavailable rather than displaying 00:00 or pretending it is current.

## Sources

Original summaries for [approved research proposals 1–4][research]. The source
ideas are a product-specific plan ([Anthropic][anthropic], Apache-2.0), separate
app/page jobs and coherent data ([TasteSkill][taste], [app screens][app], MIT),
surface modes ([Impeccable][modes], Apache-2.0) and stable project decisions with
page overrides ([Pro Max][promax], MIT). The pinned OpenWiz profile is summarized
above without exposing its private files. No outside prompt, checklist or
code is transplanted; asset rights remain separate. These are briefing methods,
not evidence that any particular style improves owner preference.

Research revision: the private 2026-11-02 design-skills research note, kept in
the private record.
Jake, 2026-11-02: use the six design-research methods, including a pinned taste
brief that separates hard rules, explicit preferences and observed patterns
([private record][research]).

[research]: https://github.com/jparker2006/ClosedWiz/issues/640#issuecomment-6573915029
[anthropic]: https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/frontend-design/SKILL.md
[taste]: https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/SKILL.md
[app]: https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/references/app-screens.md
[modes]: https://github.com/pbakaus/impeccable/blob/e89e3ada3e875a89ac2c5d33d11e65ebef6fe285/.agents/skills/impeccable/SKILL.md
[promax]: https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/3a13158ff1f32156cbe144108de48eda2ecaed9a/.claude/skills/ui-ux-pro-max/SKILL.md
