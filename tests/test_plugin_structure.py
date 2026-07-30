# tests/test_plugin_structure.py
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)")


def plugin_dirs():
    # parents[1], not parent: the match is <plugin>/.claude-plugin/plugin.json,
    # so one level up is .claude-plugin and two levels up is the plugin dir.
    return sorted(p.parents[1] for p in REPO.glob("*/.claude-plugin/plugin.json"))


def skill_files():
    return sorted(REPO.glob("*/skills/*/SKILL.md"))


class TestPluginStructure(unittest.TestCase):
    def test_every_plugin_is_registered_in_the_marketplace(self):
        registered = {
            entry["source"].lstrip("./")
            for entry in json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"]
        }
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                self.assertIn(plugin.name, registered)

    def test_every_plugin_manifest_has_name_and_description(self):
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                data = json.loads(
                    (plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(data["name"], plugin.name)
                self.assertTrue(data["description"].strip())

    def test_every_skill_has_name_and_description_frontmatter(self):
        for skill in skill_files():
            with self.subTest(skill=str(skill.relative_to(REPO))):
                text = skill.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), "missing frontmatter")
                front = text.split("---", 2)[1]
                self.assertRegex(front, r"(?m)^name:\s*\S+")
                self.assertRegex(front, r"(?m)^description:\s*\S+")

    def test_skill_frontmatter_name_matches_directory(self):
        for skill in skill_files():
            with self.subTest(skill=str(skill.relative_to(REPO))):
                front = skill.read_text(encoding="utf-8").split("---", 2)[1]
                name = re.search(r"(?m)^name:\s*(\S+)", front).group(1)
                self.assertEqual(name, skill.parent.name)

    def test_skill_frontmatter_has_no_version_field(self):
        # Skill-level versions have no consumer (harnesses and install caching
        # key on plugin.json's version) and drift silently; the plugin version
        # is the only one.
        for skill in skill_files():
            front = skill.read_text(encoding="utf-8").split("---", 2)[1]
            with self.subTest(skill=str(skill.relative_to(REPO))):
                self.assertNotRegex(front, r"(?m)^version:")

    def test_plugin_root_references_resolve(self):
        for skill in skill_files():
            plugin = skill.parents[2]
            for ref in PLUGIN_ROOT_REF.findall(skill.read_text(encoding="utf-8")):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    self.assertTrue((plugin / ref.lstrip("/")).exists(),
                                    f"{skill} references missing {ref}")


MD_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)#]+?)(?:#[^)]*)?\)")
SUBAGENT_REF = re.compile(r"\bsub-?agents?\b", re.IGNORECASE)
FALLBACK_MARKER = "**No-subagent fallback:**"


class TestCodexParity(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        for skill in skill_files():
            text = skill.read_text(encoding="utf-8")
            for target in MD_LINK.findall(text):
                if "${" in target:
                    continue  # env-var paths are covered by test_plugin_root_references_resolve
                with self.subTest(skill=str(skill.relative_to(REPO)), link=target):
                    self.assertTrue((skill.parent / target).exists(),
                                    f"dangling relative link: {target}")

    def test_dispatching_skills_declare_no_subagent_fallback(self):
        for skill in skill_files():
            text = skill.read_text(encoding="utf-8")
            if not SUBAGENT_REF.search(text):
                continue
            with self.subTest(skill=str(skill.relative_to(REPO))):
                self.assertIn(FALLBACK_MARKER, text,
                              "skill dispatches subagents but has no fallback note")


if __name__ == "__main__":
    unittest.main()
