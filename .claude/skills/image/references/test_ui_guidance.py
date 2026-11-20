"""#640: written UI workflow contracts, not evidence of better designs.

Run: PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
    -s skills/image/references -p 'test_*.py' -v
"""
from pathlib import Path
import re
import unittest


SKILLS = Path(__file__).resolve().parents[2]


class UIGuidance(unittest.TestCase):
    def document(self, path):
        file = SKILLS / path
        self.assertTrue(file.is_file(), f"Missing guidance: {path}")
        return file.read_text(encoding="utf-8")

    def section(self, path, heading, level="##"):
        text = self.document(path)
        marker = f"{level} {heading}\n"
        self.assertEqual(text.count(marker), 1, f"Expected one {heading} section")
        return " ".join(text.split(marker, 1)[1].split(f"\n{level} ", 1)[0].split())

    def contains(self, section, *requirements):
        for requirement in requirements:
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, section)

    def test_01_pinned_public_taste_brief(self):
        brief = self.section("image/references/ui-brief.md", "Project taste brief")
        self.contains(brief, "Source revision:", "Hard rules:",
                      "Explicit preferences:", "Observed patterns:",
                      "private mood board")
        image = self.section("image/SKILL.md", "Prepare a UI design")
        self.contains(image, "references/ui-brief.md", "before generating")
        setup = self.section("hill-climb/SKILL.md", "Set up the run")
        self.contains(setup, "public taste brief", "new rubric version")

    def test_02_surface_specific_templates(self):
        app = self.section("image/references/ui-brief.md", "App brief")
        self.contains(app, "Person:", "Task:", "Scope:", "Main question:",
                      "Important finding:", "Next action:", "Synthetic example:")
        marketing = self.section("image/references/ui-brief.md", "Marketing brief")
        self.contains(marketing, "Audience:", "Promise:", "Proof:",
                      "One action:", "Synthetic example:")

    def test_03_design_specification_precedes_target(self):
        spec = self.section("image/references/ui-brief.md", "Design specification")
        self.contains(spec, "Type roles and fonts:", "Colour roles:",
                      "Spacing and radii:", "Composition:", "Density:",
                      "Phone changes:", "Product-specific element:", "Held fixed:")
        image = self.section("image/SKILL.md", "Prepare a UI design")
        self.contains(image, "design specification", "beside the prompt")

    def test_04_one_synthetic_packet_with_edge_cases(self):
        packet = self.section("image/references/ui-brief.md", "Synthetic content packet")
        self.contains(packet, "Objects, fields and units:", "Empty:", "Zero:",
                      "Long:", "Sparse:", "Missing:", "transcription",
                      "testimonials", "fixture")
        image = self.section("image/SKILL.md", "Prepare a UI design")
        self.contains(image, "one synthetic content packet", "same packet")

    def test_05_critique_passes_and_locatable_defects(self):
        critique = self.section("image/references/ui-craft.md", "Screenshot critique")
        self.contains(critique, "First-visible answer", "Visual masses and hierarchy",
                      "Alignment and accidental voids", "Type and contrast",
                      "Content fullness", "Phone composition", "Detailed defects",
                      "Viewport", "Screenshot region", "Observation", "Impact",
                      "One proposed change", "one concrete change per candidate")

    def test_06_dark_craft_is_used_for_targets_and_real_pages(self):
        craft = self.section("image/references/ui-craft.md", "Dark-interface checks")
        self.contains(craft, "ground", "panel", "overlay", "subdued text",
                      "contrast", "control boundaries", "accent", "selection",
                      "focus", "native controls", "colour-scheme", "scrollbars")
        image = self.document("image/SKILL.md")
        self.assertGreaterEqual(image.count("references/ui-craft.md"), 2,
                                "Use craft checks at target inspection and real-page review")
        example = self.section("image/references/ui-craft.md", "Worked synthetic inspection")
        self.contains(example, "dark-craft-desktop.png", "dark-craft-phone.png",
                      "Foreground", "Background", "Ratio", "WCAG")
        for name in ("dark-craft-desktop.png", "dark-craft-phone.png"):
            with self.subTest(artifact=name):
                self.assertTrue((SKILLS / "image/references" / name).is_file())

    def test_07_each_reference_cites_pinned_research_and_primary_sources(self):
        # O10/P3: a provenance edit must retain the pinned research and primary
        # citations while removing links that publish private source locations.
        # Existing source checks required only revision hashes, so leaked links
        # passed even when a public reader could not use them.
        for name in ("ui-brief.md", "ui-craft.md"):
            with self.subTest(reference=name):
                sources = self.section(f"image/references/{name}", "Sources")
                self.contains(sources, "Research revision: the private 2026-11-02",
                              "12af471f627f866411b4bd785b19646d3672784c")
                self.assertFalse(
                    bool(re.search(r"https://github\.com/[^\s)]+/(?:private|docs/grills)/", sources)),
                    "public reference links directly to a private source file",
                )
                self.assertTrue(
                    re.search(r"https://github\.com/jparker2006/ClosedWiz/(?:issues|pull)/[1-9][0-9]*#issuecomment-[1-9][0-9]*", sources),
                    "public decision source needs a private-record comment pointer",
                )


if __name__ == "__main__":
    unittest.main()
