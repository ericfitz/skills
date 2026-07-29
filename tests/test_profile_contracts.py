import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "profile" / "references" / "contracts"


class TestValidator(unittest.TestCase):
    def test_accepts_valid_object(self):
        schema = {"type": "object", "required": ["a"],
                  "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({"a": "x"}, schema), [])

    def test_reports_missing_required_property(self):
        schema = {"type": "object", "required": ["a"], "properties": {}}
        errors = validate({}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("required", errors[0])

    def test_reports_wrong_type_with_path(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        errors = validate({"a": 1}, schema)
        self.assertIn("$.a", errors[0])

    def test_validates_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual(validate([1, 2], schema), [])
        self.assertEqual(len(validate([1, "x"], schema)), 1)

    def test_enum_enforced(self):
        schema = {"enum": ["a", "b"]}
        self.assertEqual(validate("a", schema), [])
        self.assertEqual(len(validate("c", schema)), 1)

    def test_bool_is_not_an_integer(self):
        self.assertEqual(len(validate(True, {"type": "integer"})), 1)


class TestProfileContracts(unittest.TestCase):
    def test_every_schema_is_valid_json_and_has_required_metadata(self):
        schemas = sorted(CONTRACTS.glob("*.schema.json"))
        self.assertEqual([p.name for p in schemas],
                         ["docs.schema.json", "journeys.schema.json",
                          "stack.schema.json", "topology.schema.json"])
        for path in schemas:
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["type"], "object")
                self.assertIn("contract_version", schema["properties"])
                self.assertIn("contract_version", schema["required"])

    def test_every_schema_has_an_example_that_validates(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            name = path.name.replace(".schema.json", "")
            example_path = CONTRACTS / "examples" / ("%s.example.json" % name)
            with self.subTest(contract=name):
                self.assertTrue(example_path.exists(), "missing example for %s" % name)
                errors = validate(
                    json.loads(example_path.read_text(encoding="utf-8")),
                    json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(errors, [])

    def test_topology_contract_uses_no_testing_vocabulary(self):
        """Extraction discipline: profile phases stay consumer-agnostic."""
        text = (CONTRACTS / "topology.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("boundary", "test", "fixture", "mock"):
            self.assertNotIn(banned, text, "topology contract mentions %r" % banned)

    def test_journeys_contract_uses_no_testing_vocabulary(self):
        text = (CONTRACTS / "journeys.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("test", "coverage_hint", "fixture"):
            self.assertNotIn(banned, text, "journeys contract mentions %r" % banned)

    def test_docs_contract_uses_no_testing_vocabulary(self):
        text = (CONTRACTS / "docs.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("test", "fixture", "mock", "scenario"):
            self.assertNotIn(banned, text, "docs contract mentions %r" % banned)

    def test_docs_contract_emits_evidence_not_journey_candidates(self):
        """Ownership boundary: profile:journeys alone forms and ranks candidates."""
        schema = json.loads((CONTRACTS / "docs.schema.json").read_text(encoding="utf-8"))
        properties = schema["properties"]
        self.assertIn("journey_evidence", properties)
        self.assertNotIn("candidates", properties)

    def test_docs_requirements_do_not_classify_scope(self):
        """Cross-cutting-ness is judged against the journey set, which does not
        exist when docs runs. Deliberately absent; see the spec."""
        schema = json.loads((CONTRACTS / "docs.schema.json").read_text(encoding="utf-8"))
        requirement = schema["properties"]["requirements"]["items"]["properties"]
        self.assertNotIn("scope", requirement)


if __name__ == "__main__":
    unittest.main()
