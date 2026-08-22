# tests/test_dependency_model_coupling.py
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "dependency-model"
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]
PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)")


def body(skill):
    return skill.read_text(encoding="utf-8")


class TestSkillSet(unittest.TestCase):
    def test_all_six_category_skills_exist(self):
        self.assertEqual([p.parent.name for p in SKILLS], CATEGORIES)


class TestNoCrossPluginPathCoupling(unittest.TestCase):
    def test_no_skill_reaches_into_profile_by_path(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill)
                self.assertNotIn("profile/scripts", text)
                self.assertNotIn("profile_inventory.py", text)

    def test_every_skill_names_profile_topology_as_a_skill(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("profile:topology", body(skill))

    def test_plugin_root_refs_stay_inside_this_plugin(self):
        for skill in SKILLS:
            for ref in PLUGIN_ROOT_REF.findall(body(skill)):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    # Without this, ../profile/... resolves and passes exists().
                    self.assertNotIn("..", ref)
                    self.assertTrue((PLUGIN / ref.lstrip("/")).exists())

    def test_profile_skills_are_not_modified_to_know_about_this_plugin(self):
        """#48 AC 4: the dependency direction is one-way."""
        for skill in sorted((REPO / "profile" / "skills").glob("*/SKILL.md")):
            with self.subTest(skill=skill.parent.name):
                self.assertNotIn("dependency-model", body(skill))


class TestEachSkillOwnsItsCategory(unittest.TestCase):
    def test_each_skill_names_its_own_contract_and_example(self):
        for skill in SKILLS:
            category = skill.parent.name
            with self.subTest(skill=category):
                text = body(skill)
                self.assertIn(f"contracts/{category}.schema.json", text)
                self.assertIn(f"examples/{category}.example.json", text)

    def test_each_skill_names_the_shared_envelope(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("discovery.schema.json", body(skill))


class TestDisciplineIsStatedInEverySkill(unittest.TestCase):
    def test_every_skill_states_it_is_read_only(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertIn("read-only", body(skill).lower())

    def test_every_skill_states_null_is_not_confirmed_absent(self):
        """D1: layer 3 reads a null as a candidate gap. Layer 1 must not have
        decided it is a real one."""
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                self.assertIn("no declaration was found", text)
                self.assertIn("confirmed absent", text)

    def test_every_skill_distinguishes_an_empty_list_from_a_failed_scan(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                self.assertIn("failed", text)
                self.assertIn("legitimate finding", text)

    def test_no_skill_promises_criticality_or_remediation(self):
        banned = ("criticality", "blast radius", "remediation",
                  "monitoring gap", "chaos test")
        # Word-boundary patterns: a bare substring match ("not " inside
        # "cannot ", "never" inside "whenever") would count prose as a
        # disclaimer that never disclaimed anything.
        disclaim_markers = (r"\bno\b", r"\bnot\b", r"\bnever\b", r"\bdo not\b")
        for skill in SKILLS:
            text = body(skill).lower()
            for word in banned:
                with self.subTest(skill=skill.parent.name, word=word):
                    # Allowed only where every occurrence sits in a line that
                    # disclaims it — a single disclaiming line must not give
                    # cover to a later line that promises the word outright.
                    for line in text.splitlines():
                        if word not in line:
                            continue
                        self.assertTrue(
                            any(re.search(pat, line) for pat in disclaim_markers),
                            f"{skill.parent.name} promises {word!r}: {line}")


class TestSecuritySkillCarriesTheCredentialRule(unittest.TestCase):
    def test_security_skill_forbids_reading_values_and_keys_dir(self):
        text = body(PLUGIN / "skills" / "security" / "SKILL.md")
        self.assertIn("~/.keys/", text)
        lower = text.lower()
        self.assertIn("never read a secret", lower)
        self.assertIn("stringdata", lower)


class TestPackageSkillHonoursSyftsLimits(unittest.TestCase):
    def test_package_skill_requires_the_exclusions(self):
        text = body(PLUGIN / "skills" / "package" / "SKILL.md")
        self.assertIn("--exclude", text)
        self.assertIn("270", text)

    def test_package_skill_documents_file_level_evidence(self):
        text = body(PLUGIN / "skills" / "package" / "SKILL.md").lower()
        self.assertIn("no line number", text)


class TestRegistration(unittest.TestCase):
    def test_plugin_manifest_is_semver_and_named_for_its_directory(self):
        data = json.loads(
            (PLUGIN / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "dependency-model")
        self.assertRegex(data["version"], r"^\d+\.\d+\.\d+$")

    def test_marketplace_entry_exists_in_the_development_category(self):
        data = json.loads(
            (REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        entry = next(p for p in data["plugins"] if p["name"] == "dependency-model")
        self.assertEqual(entry["source"], "./dependency-model")
        self.assertEqual(entry["category"], "development")

    def test_verify_script_declares_the_plugin_with_all_six_skills(self):
        text = (REPO / "scripts" / "verify-marketplace.sh").read_text(encoding="utf-8")
        self.assertIn(
            '"dependency-model:development:config,network,package,platform,security,service"',
            text)
        self.assertIn("dependency-model/scripts/depscan.py", text)

    def test_requirements_declare_syft_as_required(self):
        data = json.loads((PLUGIN / "requirements.json").read_text(encoding="utf-8"))
        self.assertEqual(data["plugin"], "dependency-model")
        syft = next(t for t in data["tools"] if t["name"] == "syft")
        self.assertTrue(syft["required"])
        self.assertIsInstance(syft["probe"], list)

    def test_readme_documents_the_plugin(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("### dependency-model", text)
        self.assertIn("Fifteen plugins", text)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(f"**{category}**", text)


if __name__ == "__main__":
    unittest.main()
