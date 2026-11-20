# Dark-interface craft

Use this on the target and again on the real HTML at matched states and widths.
Mark screenshot regions and record observations; a generated image is not proof
of browser contrast, loaded fonts or working controls. Use the project's profile,
not an imported palette. Mechanical checks and visual judgment answer different
questions; neither replaces functional or accessibility proofs.

## Dark-interface checks

- **Surface roles:** identify ground, panel and overlay in the actual image.
  Give them deliberate tone/elevation differences; inspect overlaps and edges.
  A floating menu needs a readable boundary against everything behind it.
- **Text:** inspect subdued text as carefully as headings. Measure contrast for
  the actual foreground/background pairs, including nested or translucent
  surfaces and selected states. Record resolved colours, metric, ratio and the
  project's required threshold; do not judge from token names. For gradients or
  imagery, inspect the worst region behind the text. A single flat-colour ratio
  does not prove the entire page meets accessibility requirements.
- **Controls:** make control boundaries stronger than decorative separators.
  Check inputs, buttons and menus against adjacent surfaces. Thin constellation
  lines and grouping rules need not carry the burden of identifying a control.
- **Meaning:** keep the accent semantic and restrained under the project brief;
  OpenWiz's example reserves gold for attention. Preserve visible selection,
  keyboard focus and non-colour state cues. Inspect disabled controls without
  making active controls look unavailable.
- **Browser surfaces:** set the intended `colour-scheme` (CSS: `color-scheme`)
  and theme colour. Inspect native controls and scrollbars in the real browser,
  including select menus and focus states; custom panels alone do not prove
  these. Note platform-specific or uninspected states rather than claiming them.

Write each defect with viewport, screenshot region, observation, impact and one
proposed change, as in the screenshot critique below. Keep a pass/defect/gap
record for each applicable check. Do not import style bans, image or motion
quotas, scoring caps, new validators or a new approval stage from the sources.

## Screenshot critique

For each hill-climb round, or a reviewer's real-page pass, inspect both real-page
images, then write these passes separately in the round's critique record. Cite
the screenshot filename and region in each pass, including passes with no defect
found; do not substitute a generic polish score.

| Pass | What to inspect |
| --- | --- |
| First-visible answer | Can the person find the screen's answer and next action, or the page's promise and evidence? |
| Visual masses and hierarchy | Which regions dominate before reading? Does that order serve the brief? |
| Alignment and accidental voids | Shared edges, grouping and deliberate space; locate empty regions that disrupt the work. |
| Type and contrast | Loaded fonts, readable roles and measured colour pairs, with the dark-interface checks above. |
| Content fullness | Reconcile the packet and visible facts; distinguish purposeful space from missing content. |
| Phone composition | Inspect the actual phone image for action order, wrapping, readable fields and overflow. |
| Detailed defects | Locate clipped copy, weak control edges, icons and state cues needing correction. |

Record each issue, most consequential first:

| Viewport | Screenshot region | Observation | Impact | One proposed change |
| --- | --- | --- | --- | --- |
| 390 × 844 | `phone.png`, queue header, x:16–374 y:96–156 | Long label wraps over the count | The count cannot be read | Put the count on a separate aligned row |

That row is a synthetic example. Give a real issue an exact region or annotated
marker. Turn a chosen issue into one concrete change per candidate, keeping the
other brief decisions fixed. Keep this diagnostic record separate from raw
verdicts; it adds no score, scoring formula or stopping rule.

## Worked synthetic inspection

The [HTML fixture](dark-craft.html) illustrates the method, not a proposed product
screen or generated target. It uses the brief's synthetic 09:00 session counts.
These real Chromium captures contain numbered annotations at both required
widths: [desktop](dark-craft-desktop.png) (1440 × 900 viewport) and
[phone](dark-craft-phone.png) (390 × 844 viewport, full-page image).
The [capture record](dark-craft-capture.json) retains the viewports, resolved
browser styles and prepared focus state.

Reproduce with existing tools; choose a new output directory each time:

```sh
python3 -m http.server 8640 --bind 127.0.0.1 --directory skills/image/references
# In another shell:
python3 skills/image/scripts/screenshot.py http://127.0.0.1:8640/dark-craft.html \
  --ready-selector '[data-ready="true"]' --out /tmp/dark-craft-new
```

Inspect the captures, measure computed browser colours and retain the manifest
with the run's evidence. Stop the fixture server when done. The fixture requests
no remote assets or account data and installs nothing.

The saved example uses browser-harness to prepare focus explicitly: after
activating each tab and setting its viewport/reduced motion, call
`cdp('Emulation.setFocusEmulationEnabled', enabled=True)`, load the fixture,
focus `#details` and assert `matches(':focus-visible')` before capturing. This
prevents an unfocused browser window from hiding the ring. The default screenshot
command above does not perform that extra preparation; do not claim it captured
focus without inspecting it. Wait for the ready selector, fonts and two animation
frames; retain both full-page captures and close both tabs.

Recorded pairs below are **WCAG 2 contrast** ratios from
`python3 skills/image/scripts/contrast.py FG BG --min <threshold>`, run on the
browser-verified fixture colours. The example checks 4.5:1 for ordinary text and
3:1 for the necessary control edge/focus indicator against the surrounding
panel. These are example criteria, not a replacement for the project's
accessibility contract.

| Pair / annotation | Foreground | Background | Ratio | Example result |
| --- | --- | --- | --- | --- |
| Primary text / 2 | `#edf2f7` | `#1b222b` | 14.23:1 | Pass, 4.5:1 |
| Subdued text / 2 | `#aab7c4` | `#1b222b` | 7.85:1 | Pass, 4.5:1 |
| Subdued text / 3 | `#aab7c4` | `#283341` | 6.27:1 | Pass, 4.5:1 |
| Attention text / 4 | `#e5bd68` | `#1b222b` | 9.01:1 | Pass, 4.5:1 |
| Control edge / 5, 6 | `#718399` | `#1b222b` | 4.13:1 | Pass, 3:1 |
| Focus outline / 5 | `#9bc7ff` | `#1b222b` | 9.16:1 | Pass, 3:1 |

Inspection record: annotations 1/2/3 locate the ground, panel and overlay tones.
At 4, words and a persistent left edge accompany the attention colour. At 5,
the control edge is stronger than the quiet separator below; a blue outline
marks focus. At 6, the closed native select uses a dark browser scheme. Both
captures show readable content and a phone layout in one column. Gaps: the
“overlay” is an in-flow tone sample, not an exercised popup; the open native
menu, scrollbar behaviour and other operating systems are unverified. Buttons
are inert fixture controls. No product accessibility or taste improvement is
claimed by this example.

## Sources

Original synthesis implementing [research proposals 5–6][research]: separate,
locatable screenshot critiques from [TasteSkill][critique] (MIT) and
[OneRedOak][review] (MIT); deliberate dark surface/text/control roles from
[TasteSkill app screens][app] (MIT), browser details from [Vercel][vercel] (MIT),
and finishing checks from [Impeccable][floor] (Apache-2.0). No source text or code
is transplanted. Contrast calculation and example thresholds follow the
[WCAG contrast definition][contrast] and [non-text contrast criterion][nontext];
these measurements cover the named pairs only.

Research revision: the private 2026-11-02 design-skills research note, kept in
the private record.
Jake, 2026-11-02: use separate screenshot critique passes and dark-interface craft
from the six approved design-research methods ([private record][research]).

[research]: https://github.com/jparker2006/ClosedWiz/issues/640#issuecomment-6573915029
[app]: https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/references/app-screens.md
[critique]: https://github.com/Leonxlnx/taste-skill/blob/12af471f627f866411b4bd785b19646d3672784c/skills/taste-skill/references/critique.md
[review]: https://github.com/OneRedOak/claude-code-workflows/blob/29a34c725313c7621f426f838ed31cf482473fb4/design-review/design-review-agent.md
[vercel]: https://github.com/vercel-labs/web-interface-guidelines/blob/434b7f91364665f2f733b310ec54809bf8f37937/README.md
[floor]: https://github.com/pbakaus/impeccable/blob/e89e3ada3e875a89ac2c5d33d11e65ebef6fe285/.agents/skills/impeccable/reference/craft-floor.md
[contrast]: https://www.w3.org/TR/WCAG22/#dfn-contrast-ratio
[nontext]: https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html
