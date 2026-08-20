import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
ITEST_SKILLS = sorted((REPO / "itest" / "skills").glob("*/SKILL.md"))
PROFILE_SKILLS = sorted((REPO / "profile" / "skills").glob("*/SKILL.md"))


class TestCrossPluginCoupling(unittest.TestCase):
    def test_itest_skills_exist(self):
        self.assertEqual([p.parent.name for p in ITEST_SKILLS],
                         ["conventions", "critique", "design", "state"])

    def test_itest_never_references_the_inventory_script(self):
        for skill in ITEST_SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = skill.read_text(encoding="utf-8")
                self.assertNotIn("profile_inventory.py", text.replace(
                    "Never invoke `profile`'s inventory script by path.", ""))

    def test_itest_plugin_root_refs_stay_inside_itest(self):
        for skill in ITEST_SKILLS:
            for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)",
                                  skill.read_text(encoding="utf-8")):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    # Without this, ../profile/... resolves and passes exists().
                    self.assertNotIn("..", ref)
                    self.assertTrue((REPO / "itest" / ref.lstrip("/")).exists())

    def test_profile_skills_never_reference_itest(self):
        for skill in PROFILE_SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertNotIn("itest", skill.read_text(encoding="utf-8"))

    def test_design_preflights_all_four_profile_skills(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8")
        for name in ("profile:stack", "profile:docs", "profile:topology",
                     "profile:journeys"):
            with self.subTest(skill=name):
                self.assertIn(name, text)

    def test_design_documents_the_human_gate(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("gate", text)
        self.assertIn("subagents cannot ask", text)

    def test_design_maps_requirements_to_journeys_before_the_gate(self):
        """Cross-cutting requirements only exist relative to the journey set, so the
        mapping has to happen in the main context before the user is asked."""
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("gate prep", text)
        self.assertIn("cross-cutting", text)

    def test_design_writes_confirmed_journeys_doc_after_the_gate(self):
        """Issue #45: the confirmed journeys must be persisted to docs/journeys.md
        after the Phase 5 human gate, not left in chat (profile:journeys stays a
        pure proposer)."""
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8")
        self.assertIn("docs/journeys.md", text)
        lower = text.lower()
        # The write is documented inside/after the human gate, not during discovery.
        self.assertGreater(lower.index("docs/journeys.md"),
                           lower.index("phase 5"))
        # Journeys the user adds at the gate carry the user_supplied marker.
        self.assertIn("user_supplied", text)
        # Existing docs are never silently clobbered.
        self.assertIn("overwrit", lower)

    def test_design_offers_conflict_disposition_without_building_a_mechanism(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("doc_code_conflicts", text)
        self.assertIn("github:create-issue", text)
        self.assertIn("no new issue-creation mechanism", text)


if __name__ == "__main__":
    unittest.main()
