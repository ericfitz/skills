# tests/test_dependency_model_coupling.py
import json
import re
import sys
import unittest
from pathlib import Path
from typing import ClassVar

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "dependency-model"
SKILLS = sorted((PLUGIN / "skills").glob("*/SKILL.md"))
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]
LAYER2 = ["report", "synthesize"]
ALL_SKILLS = sorted(CATEGORIES + LAYER2)
PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)")


def skill_path(name):
    return PLUGIN / "skills" / name / "SKILL.md"


def body(skill):
    return skill.read_text(encoding="utf-8")


def collapse_ws(text):
    """Collapse whitespace runs to a single space.

    These tests grep exact phrases out of prose. A mid-sentence line wrap
    breaks a raw substring match even though the wrap position carries no
    meaning — this has broken assertions here four times, and started
    deforming the prose it exists to check (skills carrying lines far past
    house wrap purely to keep a phrase contiguous). Comparing on collapsed
    whitespace fixes wrap sensitivity only; it does not touch case, which
    every call site already handles for itself before matching.
    """
    return re.sub(r"\s+", " ", text)


def assert_phrase_in(test_case, needle, haystack):
    test_case.assertIn(collapse_ws(needle), collapse_ws(haystack))


def assert_phrase_not_in(test_case, needle, haystack):
    test_case.assertNotIn(collapse_ws(needle), collapse_ws(haystack))


class TestSkillSet(unittest.TestCase):
    def test_all_eight_skills_exist(self):
        self.assertEqual([p.parent.name for p in SKILLS], ALL_SKILLS)


class TestNoCrossPluginPathCoupling(unittest.TestCase):
    def test_no_skill_reaches_into_profile_by_path(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill)
                assert_phrase_not_in(self, "profile/scripts", text)
                assert_phrase_not_in(self, "profile_inventory.py", text)

    def test_every_skill_names_profile_topology_as_a_skill(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                assert_phrase_in(self, "profile:topology", body(skill))

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
                assert_phrase_not_in(self, "dependency-model", body(skill))


class TestEachSkillOwnsItsCategory(unittest.TestCase):
    """Category-scoped: only the six discovery skills emit a `discovery`
    envelope with their own per-category contract. The two layer-2 skills
    consume that envelope and emit `synthesis` instead — see
    TestLayer2SkillsNameTheirDependencies."""

    def test_each_skill_names_its_own_contract_and_example(self):
        for category in CATEGORIES:
            with self.subTest(skill=category):
                text = body(skill_path(category))
                assert_phrase_in(self, f"contracts/{category}.schema.json", text)
                assert_phrase_in(
                    self, f"examples/{category}.example.json", text)

    def test_each_skill_names_the_shared_envelope(self):
        for category in CATEGORIES:
            with self.subTest(skill=category):
                assert_phrase_in(
                    self, "discovery.schema.json", body(skill_path(category)))


class TestLayer2SkillsNameTheirDependencies(unittest.TestCase):
    def test_both_layer2_skills_name_the_synthesis_contract(self):
        for skill in LAYER2:
            with self.subTest(skill=skill):
                assert_phrase_in(
                    self, "synthesis.schema.json", body(skill_path(skill)))

    def test_report_names_synthesize(self):
        assert_phrase_in(self, "synthesize", body(skill_path("report")))

    def test_synthesize_names_depgraph(self):
        assert_phrase_in(
            self, "depgraph.py", body(skill_path("synthesize")))


class TestDisciplineIsStatedInEverySkill(unittest.TestCase):
    def test_every_skill_states_it_is_read_only(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                assert_phrase_in(self, "read-only", body(skill).lower())

    def test_every_skill_states_null_is_not_confirmed_absent(self):
        """D1: layer 3 reads a null as a candidate gap. Layer 1 must not have
        decided it is a real one."""
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                assert_phrase_in(self, "no declaration was found", text)
                assert_phrase_in(self, "confirmed absent", text)

    def test_every_skill_distinguishes_an_empty_list_from_a_failed_scan(self):
        for skill in SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = body(skill).lower()
                assert_phrase_in(self, "failed", text)
                assert_phrase_in(self, "legitimate finding", text)

    def test_no_skill_promises_criticality_or_remediation(self):
        # Patterns, not plain substrings: "blast radius" and "blast-radius"
        # are the same promise (C1), and "rank"/"ranking" are the same
        # promise too (C2).
        banned = (r"criticality", r"blast[- ]radius", r"remediation",
                  r"monitoring gap", r"chaos test", r"\brank(?:ing)?\b")
        # Word-boundary patterns: a bare substring match ("not " inside
        # "cannot ", "never" inside "whenever") would count prose as a
        # disclaimer that never disclaimed anything.
        disclaim_markers = (r"\bno\b", r"\bnot\b", r"\bnever\b", r"\bdo not\b")
        for skill in SKILLS:
            text = body(skill).lower()
            for pattern in banned:
                with self.subTest(skill=skill.parent.name, pattern=pattern):
                    # Allowed only where every occurrence sits in a line that
                    # disclaims it — a single disclaiming line must not give
                    # cover to a later line that promises the word outright.
                    # (Scoped per physical line by design, not the phrase
                    # helper above: a disclaimer and the word it disclaims
                    # are expected to sit together, so line boundaries here
                    # are meaningful rather than incidental wrapping, and
                    # collapse_ws must not be used here for the same reason.)
                    for line in text.splitlines():
                        if not re.search(pattern, line):
                            continue
                        self.assertTrue(
                            any(re.search(pat, line) for pat in disclaim_markers),
                            f"{skill.parent.name} promises {pattern!r}: {line}")


class TestSecuritySkillCarriesTheCredentialRule(unittest.TestCase):
    def test_security_skill_forbids_reading_values_and_keys_dir(self):
        text = body(skill_path("security"))
        assert_phrase_in(self, "~/.keys/", text)
        lower = text.lower()
        assert_phrase_in(self, "never read a secret", lower)
        assert_phrase_in(self, "stringdata", lower)


class TestPackageSkillHonoursSyftsLimits(unittest.TestCase):
    def test_package_skill_requires_the_exclusions(self):
        text = body(skill_path("package"))
        assert_phrase_in(self, "--exclude", text)
        assert_phrase_in(self, "270", text)

    def test_package_skill_documents_file_level_evidence(self):
        text = body(skill_path("package")).lower()
        assert_phrase_in(self, "no line number", text)


class TestLifecycleInstructions(unittest.TestCase):
    """Spec pin: an unenforced classification is how two skills come to
    disagree about the same entry."""

    RUN_CONSTANT: ClassVar[list[str]] = [
        "service", "network", "config", "security", "platform"]

    def test_the_constant_categories_say_run(self):
        """D3 (user correction): arch, os, and runtime-version constrain the
        runtime environment, not the build environment, so every
        `details.kind` on a platform entry is `run` too -- platform joins
        the other constant categories rather than splitting by kind."""
        for category in self.RUN_CONSTANT:
            text = body(skill_path(category))
            with self.subTest(skill=category):
                self.assertRegex(text, r"`lifecycle`[^\n]*`run`")

    def test_package_defers_to_pkglifecycle_and_says_syft_cannot(self):
        text = body(skill_path("package"))
        assert_phrase_in(self, "pkglifecycle.py", text)
        assert_phrase_in(self, "syft cannot", text.lower())

    def test_no_skill_mentions_a_third_lifecycle_value(self):
        for skill in ALL_SKILLS:
            text = body(skill_path(skill))
            with self.subTest(skill=skill):
                assert_phrase_not_in(self, "`both`", text)


class TestFailabilityRuleIsStated(unittest.TestCase):
    """Spec pin, both ends: a bundled library must not enter health, a
    dynamically loaded package must. These are the two cases a category
    filter would have got wrong in opposite directions."""

    def test_synthesize_states_the_failability_test_not_a_category_filter(self):
        text = body(skill_path("synthesize")).lower()
        assert_phrase_in(self, "fail independently while the process is up", text)
        assert_phrase_in(self, "not by `lifecycle`", text)

    def test_synthesize_names_both_ends_explicitly(self):
        text = body(skill_path("synthesize")).lower()
        assert_phrase_in(self, "bundled", text)
        assert_phrase_in(self, "dynamically loaded", text)
        assert_phrase_in(self, "loading site", text)


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

    def test_verify_script_declares_the_plugin_with_all_eight_skills(self):
        text = (REPO / "scripts" / "verify-marketplace.sh").read_text(encoding="utf-8")
        self.assertIn(
            '"dependency-model:development:'
            'config,network,package,platform,report,security,service,synthesize"',
            text)
        self.assertIn("dependency-model/scripts/depscan.py", text)
        self.assertIn("dependency-model/scripts/depgraph.py", text)
        self.assertIn("dependency-model/scripts/pkglifecycle.py", text)

    def test_requirements_declare_syft_as_required(self):
        data = json.loads((PLUGIN / "requirements.json").read_text(encoding="utf-8"))
        self.assertEqual(data["plugin"], "dependency-model")
        syft = next(t for t in data["tools"] if t["name"] == "syft")
        self.assertTrue(syft["required"])
        self.assertIsInstance(syft["probe"], list)

    def test_requirements_declare_mmdc_as_optional(self):
        data = json.loads((PLUGIN / "requirements.json").read_text(encoding="utf-8"))
        mmdc = next(t for t in data["tools"] if t["name"] == "mmdc")
        self.assertFalse(mmdc["required"])
        self.assertIsInstance(mmdc["probe"], list)

    def test_readme_documents_the_plugin(self):
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("### dependency-model", text)
        self.assertIn("Fifteen plugins", text)
        for skill in ALL_SKILLS:
            with self.subTest(skill=skill):
                self.assertIn(f"**{skill}**", text)


if __name__ == "__main__":
    unittest.main()
