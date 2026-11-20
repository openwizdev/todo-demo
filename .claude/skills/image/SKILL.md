---
name: image
description: Generate or edit pictures, make the target picture a visible UI change needs before it is built, and capture real pages at phone and desktop widths. Use for image generation, UI targets and review, diagrams, charts, and hill-climb's per-round pictures and screenshots; for running the climb itself, use hill-climb.
version: 0.2.0
---

# Pictures and UI

A generated picture is a design target; a screenshot is evidence of what HTML actually renders. Keep that distinction in every claim. Hill-climb calls this skill for every round's picture and screenshot.

## Guards

- **Privacy:** keep private content out of prompts, saved artifacts and evidence; use synthetic UI data. Summarize owner preferences in your own words, with the decision date and verified private-record comment pointer; never copy exact owner words or private file links into a public brief. Commit only reviewed, synthetic evidence: no real page's personal content, account URLs or credentials.
- **Approval:** the user approves the target of a big change (a new screen, a new flow, the landing page's look), recorded on the ticket, before it is built. Never edit the approved ticket body. A screenshot command never authorises live account reads or writes; capture only pages you may view.
- **Builder and reviewer apart:** the reviewer, not the builder, compares the real page with the target.

## Prepare a UI design

For app screens and marketing pages, complete the [UI brief](references/ui-brief.md) before generating a target: the pinned public taste brief (mood-board commit; hard rules, explicit preferences and observed patterns kept apart), the app or marketing template, and the compact design specification kept beside the prompt. Critique the specification against the brief before making the target. Prepare one synthetic content packet per design, with its empty, zero, long, sparse and missing cases, and give the prompt and implementation fixtures the same packet. Invented user counts, adoption claims and testimonials are not filler. Reuse the project's design system; this adds no dependency or approval stage.

Done when the brief, specification and packet are saved beside the prompt.

## Generate or edit a picture

1. Name the deliverable, exact copy, use, composition, dimensions, style and what to preserve. For an edit, inspect the original and say what changes.
2. **Generate through OpenAI's built-in image tool in Codex, with no separate API key**: generally a Codex agent on Sol at medium effort, routed through the project's agent workflow from another harness. Follow the installed imagegen instructions. If that route is unavailable, report the blocker on the ticket; never switch silently to an API-key runner or pass an HTML render off as a generated target.
3. Prompt with purpose, subject or UI state, reference roles, layout, style, exact text and constraints. Describe UI targets at **390 CSS px** and at the desktop width (default **1440 CSS px**); never squeeze a desktop picture into a phone frame.
4. Inspect the result as an image: composition, legibility, exact copy, clipping and transparency, and for UI the brief, packet and [dark craft checks](references/ui-craft.md). Fix the specific defect and inspect again.

Done when the selected picture is saved in an owned path with its prompt, reference roles and generation route, and earlier versions are kept.

## Target before implementation

Every ticket that changes something the user sees gets a target picture at phone and desktop widths before it is built, small changes included.

1. Read the spec, confirmed grill, existing design and owned paths. Save the targets in the ticket's owned evidence path, commit and push them, and post a ticket comment embedding them with URLs pinned to that commit, with viewports, state, prompt and constraints. Check the links render. With no owned artifact path, ask on the ticket.
2. Big change: wait for the user's approval on the ticket (Guards). Small change: proceed; the reviewer judges the picture. Route an unclear case through the ticket's orchestrator.
3. Build real **HTML** in the project's UI patterns.
4. The reviewer screenshots the real page at both widths in the same state and records drift in hierarchy, spacing, type, colour, content, wrapping and clipping, with the [dark craft checks](references/ui-craft.md) and measured colour pairs. Behaviour and accessibility need their own proofs.

## Screenshot a real page

Read the installed browser-harness skill first. The script needs Python 3 and Cloudroom's `browser-harness`, and adds no packages.

```sh
python3 skills/image/scripts/screenshot.py http://127.0.0.1:3000/fixture \
  --ready-selector '[data-ready="true"]' --out /tmp/image-round-1
```

Pick a **visible selector that marks the intended settled state**. For a state that needs interaction, open a fixture URL that starts in it or prepare it with browser-harness; the script performs no interaction. Use a new `--out` folder each time. It saves `phone.png` (390 × 844) and `desktop.png` (1440 × 900) full-page, then `capture.json` last, and prints the manifest path and an `overflow:` line. Nonzero exit means no completed pair, even if files exist; fix the cause and capture into a new folder. `python3 skills/image/scripts/screenshot.py --help` lists the waits and `--fixed-at-bottom`.

Done when you have opened **both** PNGs and checked content, fonts, images, overlays, the intended state and any overflow it named. A pair does not prove visual quality, touch, accessibility, or canvas, video or CSS background assets; never replace it with a mockup or a resized image.

## Diagrams

Explanations and architecture pictures use a **hand-drawn Excalidraw look**: **Virgil font**, **off-white background**, **coloured rounded frames for where things run**, **bold black boxes with one grey line under the name**, **few boxes** and **lots of space**. Keep labels short and check the frames show where things run. No default Mermaid architecture drawings; simple left-to-right ticket graphs are fine.

## Charts

Use **one colour-blind-safe palette checked by a validator** against the actual colours (protanopia, deuteranopia and tritanopia), **labels on the marks**, and **a table behind the chart** with the plotted values and units. Keep the validator's name, inputs and result; with none available, call the palette unchecked, and ask before adding a validator dependency. Render marks from the table with the project's chart or HTML tools and screenshot the real chart; generated images never supply measurements. Use labels or shapes as well as colour. For a text contrast pair, `python3 skills/image/scripts/contrast.py FG BG --min 4.5` prints the WCAG ratio and pass or fail.

## Verify

```sh
python3 -I -m unittest discover -s skills/image/tests -v
python3 -I -m unittest discover -s skills/image/references -v
```

These prove capture, failure handling and the contrast helper on fixtures, not live pages or image generation. Hand back the saved paths, prompt or manifest, what you inspected and any unverified part.

## Source and trace

**Source:** new, original to OpenWiz. Not adapted from Matt Pocock's skills.

Jake, 2026-11-01: built-in OpenAI generation through Codex, target pictures before visible UI changes, owner approval for big changes, phone and desktop screenshots for hill-climb, and the diagram and chart rules ([private record](https://github.com/jparker2006/ClosedWiz/issues/1278#issuecomment-6704791158)). Jake, 2026-11-02: pinned taste briefs, surface templates, design specifications, one synthetic content packet, separate screenshot critiques and dark craft ([private record](https://github.com/jparker2006/ClosedWiz/issues/640#issuecomment-6573915029)); these have not shown an improvement in his taste judgments.

Prior art, with original workflow and code here: OpenAI's [imagegen](https://github.com/openai/skills/tree/main/skills/.system/imagegen), GitHub's [generate-image](https://github.com/github/awesome-copilot/blob/main/skills/generate-image/SKILL.md) and Matt Pocock's [prototype](https://github.com/mattpocock/skills).
