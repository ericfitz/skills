# tests/test_schema_check_refs.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import resolve_refs, validate

CORE = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "details": {"type": "object"},
    },
}


def write_schemas(tmp, extra=None):
    base = Path(tmp)
    (base / "core.schema.json").write_text(json.dumps(CORE), encoding="utf-8")
    for name, body in (extra or {}).items():
        (base / name).write_text(json.dumps(body), encoding="utf-8")
    return base


class TestResolveRefs(unittest.TestCase):
    def test_resolves_a_same_directory_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({"$ref": "core.schema.json"}, base)
            self.assertEqual(resolved, CORE)

    def test_sibling_properties_merge_and_keep_the_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({
                "$ref": "core.schema.json",
                "properties": {"details": {"type": "object",
                                           "required": ["kind"]}},
            }, base)
            self.assertIn("id", resolved["properties"])
            self.assertIn("name", resolved["properties"])
            self.assertEqual(resolved["properties"]["details"]["required"], ["kind"])

    def test_sibling_required_unions_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({
                "$ref": "core.schema.json",
                "required": ["name", "details"],
            }, base)
            self.assertEqual(resolved["required"], ["id", "name", "details"])

    def test_resolves_refs_nested_under_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs(
                {"type": "array", "items": {"$ref": "core.schema.json"}}, base)
            self.assertEqual(resolved["items"]["properties"]["id"],
                             {"type": "string"})

    def test_resolves_a_ref_inside_a_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp, {"outer.schema.json": {
                "type": "object",
                "properties": {"dep": {"$ref": "core.schema.json"}},
            }})
            resolved = resolve_refs({"$ref": "outer.schema.json"}, base)
            self.assertEqual(resolved["properties"]["dep"]["required"],
                             ["id", "name"])

    def test_remote_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "https://example.com/a.json"}, base)

    def test_json_pointer_fragment_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "#/$defs/thing"}, base)

    def test_circular_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.schema.json").write_text(
                json.dumps({"$ref": "b.schema.json"}), encoding="utf-8")
            (base / "b.schema.json").write_text(
                json.dumps({"$ref": "a.schema.json"}), encoding="utf-8")
            with self.assertRaises(ValueError):
                resolve_refs({"$ref": "a.schema.json"}, base)

    def test_circular_ref_is_keyed_on_the_resolved_path_not_the_string(self):
        """Two files both named shared.schema.json in different directories
        are not a cycle."""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "sub").mkdir()
            (base / "shared.schema.json").write_text(
                json.dumps({"$ref": "sub/shared.schema.json"}), encoding="utf-8")
            (base / "sub" / "shared.schema.json").write_text(
                json.dumps({"type": "string"}), encoding="utf-8")
            resolved = resolve_refs({"$ref": "shared.schema.json"}, base)
            self.assertEqual(resolved, {"type": "string"})

    def test_self_ref_is_still_circular(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "a.schema.json").write_text(
                json.dumps({"$ref": "a.schema.json"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "circular"):
                resolve_refs({"$ref": "a.schema.json"}, base)

    def test_fragment_after_a_filename_is_rejected_as_unsupported(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            with self.assertRaisesRegex(ValueError, "unsupported"):
                resolve_refs({"$ref": "core.schema.json#/properties/id"}, base)

    def test_non_string_ref_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            for bad in (5, None, ["core.schema.json"], {"a": 1}):
                with self.subTest(ref=bad), self.assertRaisesRegex(ValueError, "must be a string"):
                    resolve_refs({"$ref": bad}, base)

    def test_absolute_path_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, \
                tempfile.TemporaryDirectory() as other:
            base = write_schemas(tmp)
            outside = Path(other) / "x.schema.json"
            outside.write_text(json.dumps({"type": "string"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_refs({"$ref": str(outside)}, base)

    def test_parent_escape_ref_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "contracts").mkdir()
            (root / "secret.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_refs({"$ref": "../secret.json"}, root / "contracts")

    def test_nested_target_may_reference_a_sibling_under_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            (base / "sub").mkdir()
            (base / "sub" / "inner.schema.json").write_text(
                json.dumps({"$ref": "../core.schema.json"}), encoding="utf-8")
            resolved = resolve_refs({"$ref": "sub/inner.schema.json"}, base)
            self.assertEqual(resolved, CORE)

    def test_nested_target_cannot_escape_the_top_level_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "contracts" / "sub").mkdir(parents=True)
            (root / "secret.json").write_text("{}", encoding="utf-8")
            (root / "contracts" / "sub" / "inner.schema.json").write_text(
                json.dumps({"$ref": "../../secret.json"}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "outside"):
                resolve_refs({"$ref": "sub/inner.schema.json"},
                             root / "contracts")

    def test_other_sibling_keys_override_the_target_outright(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            resolved = resolve_refs({
                "$ref": "core.schema.json",
                "type": "array",
                "description": "added",
            }, base)
            self.assertEqual(resolved["type"], "array")
            self.assertEqual(resolved["description"], "added")
            self.assertEqual(resolved["required"], ["id", "name"])


class TestValidateWithBaseDir(unittest.TestCase):
    def test_base_dir_resolves_before_validating(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            schema = {"type": "array", "items": {"$ref": "core.schema.json"}}
            self.assertEqual(
                validate([{"id": "a", "name": "b"}], schema, base_dir=base), [])

    def test_base_dir_reports_violations_inside_the_referenced_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = write_schemas(tmp)
            schema = {"type": "array", "items": {"$ref": "core.schema.json"}}
            errors = validate([{"id": "a"}], schema, base_dir=base)
            self.assertEqual(len(errors), 1)
            self.assertIn("name", errors[0])

    def test_without_base_dir_behaviour_is_unchanged(self):
        schema = {"type": "object", "required": ["a"],
                  "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({"a": "x"}, schema), [])
        self.assertEqual(len(validate({}, schema)), 1)


if __name__ == "__main__":
    unittest.main()
