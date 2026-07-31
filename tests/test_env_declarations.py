# tests/test_env_declarations.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import validate

REPO = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO / "env" / "references" / "requirements.schema.json"
EXEMPLAR_PLUGINS = ["dev", "env", "github"]

# Known keys per shape, kept in sync with requirements.schema.json by hand.
# schema_check.py ignores unknown keywords and the schema has no
# additionalProperties enforcement, so a typo like "min_verison" would
# otherwise validate silently and just never fire. This closes that gap.
TOP_LEVEL_KEYS = {"requirements_version", "plugin", "tools", "config", "auth"}
TOOL_ENTRY_KEYS = {"name", "required", "why", "probe", "version_pattern",
                    "min_version", "install"}
CONFIG_ENTRY_KEYS = {"path", "scope", "required", "why", "remedy"}
AUTH_ENTRY_KEYS = {"name", "probe", "why", "remedy"}


def declaration_files():
    return sorted(REPO.glob("*/requirements.json"))


class TestExemplarDeclarationsExist(unittest.TestCase):
    """RED until Step 5: the schema and the three exemplar declarations exist."""

    def test_schema_exists(self):
        self.assertTrue(SCHEMA_PATH.exists(), f"missing {SCHEMA_PATH}")

    def test_three_exemplar_declarations_exist(self):
        for plugin in EXEMPLAR_PLUGINS:
            with self.subTest(plugin=plugin):
                path = REPO / plugin / "requirements.json"
                self.assertTrue(path.exists(), f"missing {path}")


class TestDeclarationsValidateAgainstSchema(unittest.TestCase):
    def test_every_committed_declaration_validates(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        declarations = declaration_files()
        self.assertTrue(declarations, "expected at least one requirements.json")
        for path in declarations:
            with self.subTest(declaration=str(path.relative_to(REPO))):
                data = json.loads(path.read_text(encoding="utf-8"))
                errors = validate(data, schema)
                self.assertEqual(errors, [])


class TestDeclarationInvariants(unittest.TestCase):
    def test_plugin_field_matches_directory_name(self):
        for path in declaration_files():
            with self.subTest(declaration=str(path.relative_to(REPO))):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["plugin"], path.parent.name)

    def test_requirements_version_is_pinned_to_1_0_0(self):
        for path in declaration_files():
            with self.subTest(declaration=str(path.relative_to(REPO))):
                data = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(data["requirements_version"], "1.0.0")

    def test_every_probe_is_an_argv_array_never_a_string(self):
        # Safety property from the spec: probes are argv arrays executed with
        # shell=False. A probe stored as a plain string would be a step
        # toward shell interpolation, so this is asserted directly rather
        # than only implied by the schema's `items` check.
        for path in declaration_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            for section in ("tools", "auth"):
                for entry in data.get(section, []):
                    probe = entry.get("probe")
                    with self.subTest(declaration=str(path.relative_to(REPO)),
                                       section=section, name=entry.get("name")):
                        self.assertIsInstance(
                            probe, list,
                            f"probe must be a JSON array, got {type(probe).__name__}")
                        self.assertTrue(probe, "probe must not be empty")
                        for token in probe:
                            self.assertIsInstance(
                                token, str, "every probe token must be a string")

    def test_no_unknown_keys(self):
        # A typo'd optional key (e.g. "min_verison") satisfies the schema
        # (no additionalProperties enforcement) and is silently ignored by
        # schema_check.py, so the field it was meant to set is silently
        # inert. Guard the known key sets directly instead.
        sections = (("tools", TOOL_ENTRY_KEYS),
                    ("config", CONFIG_ENTRY_KEYS),
                    ("auth", AUTH_ENTRY_KEYS))
        for path in declaration_files():
            data = json.loads(path.read_text(encoding="utf-8"))
            rel = str(path.relative_to(REPO))
            with self.subTest(declaration=rel, level="top"):
                unknown = set(data.keys()) - TOP_LEVEL_KEYS
                self.assertEqual(unknown, set(), f"unknown top-level key(s) in {rel}")
            for section, known_keys in sections:
                for entry in data.get(section, []):
                    label = entry.get("name") or entry.get("path")
                    with self.subTest(declaration=rel, section=section, name=label):
                        unknown = set(entry.keys()) - known_keys
                        self.assertEqual(
                            unknown, set(),
                            f"unknown key(s) {unknown} in {rel} {section} entry {label!r}")


if __name__ == "__main__":
    unittest.main()
