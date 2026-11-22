"""User-invoked shortcut skills: each one chains skills of its own plugin, in a pinned order."""

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The single statement of each shortcut's chain.
SHORTCUTS = {
    ("discover", "dependency-model"): ["synthesize", "dependency-report"],
    ("discover", "project-profile"): ["stack", "docs", "journeys", "topology", "project-report"],
    ("test-api-fuzzing", "api-fuzz"): ["init", "run", "report", "analyze"],
    ("test-api-workflows", "api-workflows"): ["init", "arazzo"],
}
# Backticked plugin:skill tokens in the body.
REF = re.compile(r"`/?([a-z0-9-]+):([a-z0-9-]+)`")


def split(plugin, name):
    text = (REPO / plugin / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    _, front, body = text.split("---\n", 2)
    return front, body


class TestShortcutSkills(unittest.TestCase):
    def test_frontmatter_disables_model_invocation(self):
        for (plugin, name), _ in SHORTCUTS.items():
            with self.subTest(shortcut=name):
                front, _ = split(plugin, name)
                self.assertRegex(front, rf"(?m)^name: {re.escape(name)}$")
                self.assertRegex(front, r"(?m)^disable-model-invocation: true$")

    def test_names_only_skills_in_its_own_plugin(self):
        for (plugin, name), _ in SHORTCUTS.items():
            with self.subTest(shortcut=name):
                _, body = split(plugin, name)
                refs = REF.findall(body)
                self.assertTrue(refs, "no skill references found")
                for ref_plugin, ref_skill in refs:
                    self.assertEqual(ref_plugin, plugin)
                    self.assertTrue((REPO / plugin / "skills" / ref_skill / "SKILL.md").is_file())

    def test_chain_order_is_pinned(self):
        for (plugin, name), chain in SHORTCUTS.items():
            with self.subTest(shortcut=name):
                _, body = split(plugin, name)
                seen = list(dict.fromkeys(skill for _, skill in REF.findall(body) if skill != name))
                self.assertEqual(seen, chain)


if __name__ == "__main__":
    unittest.main()
