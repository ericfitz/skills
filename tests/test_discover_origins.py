import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover_origins import (
    DEPENDENCY_SCHEMAS,
    DEPENDENCY_SKILLS,
    PROFILE_SCHEMAS,
    PROFILE_SKILLS,
    SHORTCUT_SKILLS,
    dependency_skill_refs,
    schema_drift,
    skill_drift,
)

REPO = Path(__file__).resolve().parents[1]


def _dir_with(*names):
    tmp = tempfile.TemporaryDirectory()
    for name in names:
        (Path(tmp.name) / f"{name}.schema.json").write_text("{}", encoding="utf-8")
    return tmp


class TestDiscoverOrigins(unittest.TestCase):
    def test_unlisted_schema_is_reported(self):
        with _dir_with("a", "rogue") as tmp:
            self.assertEqual(schema_drift(Path(tmp), ["a"]), (["rogue"], []))

    def test_missing_schema_is_reported(self):
        with _dir_with("a") as tmp:
            self.assertEqual(schema_drift(Path(tmp), ["a", "b"]), ([], ["b"]))

    def test_real_contract_dirs_match_the_origin_lists(self):
        self.assertTrue(set(PROFILE_SCHEMAS).isdisjoint(DEPENDENCY_SCHEMAS))
        self.assertEqual(
            schema_drift(REPO / "discover" / "references" / "contracts", PROFILE_SCHEMAS + DEPENDENCY_SCHEMAS),
            ([], []),
        )


def _skills_with(*names):
    tmp = tempfile.TemporaryDirectory()
    for name in names:
        (Path(tmp.name) / name).mkdir()
    return tmp


class TestSkillOrigins(unittest.TestCase):
    def test_unlisted_skill_is_reported(self):
        with _skills_with("a", "rogue") as tmp:
            self.assertEqual(skill_drift(Path(tmp), ["a"]), (["rogue"], []))

    def test_missing_skill_is_reported(self):
        with _skills_with("a") as tmp:
            self.assertEqual(skill_drift(Path(tmp), ["a", "b"]), ([], ["b"]))

    def test_real_skill_dir_matches_the_origin_lists(self):
        lists = (PROFILE_SKILLS, DEPENDENCY_SKILLS, SHORTCUT_SKILLS)
        names = [n for lst in lists for n in lst]
        self.assertEqual(len(names), len(set(names)), "a skill is listed under two origins")
        self.assertEqual(skill_drift(REPO / "discover" / "skills", names), ([], []))

    def test_every_dependency_skill_token_is_detected(self):
        for name in DEPENDENCY_SKILLS:
            with self.subTest(skill=name):
                text = f"Then invoke `discover:{name}` with the path."
                self.assertEqual(dependency_skill_refs(text), [f"discover:{name}"])

    def test_profile_skill_names_and_prose_are_not_detected(self):
        text = "Invoke discover:stack and discover:topology; read the config and service sections."
        self.assertEqual(dependency_skill_refs(text), [])

    def test_longer_names_sharing_a_prefix_are_not_detected(self):
        self.assertEqual(dependency_skill_refs("discover:configuration discover:services"), [])


if __name__ == "__main__":
    unittest.main()
