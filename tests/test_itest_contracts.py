# tests/test_itest_contracts.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "itest" / "references" / "contracts"
DOCTRINE = REPO / "itest" / "references" / "test-design.md"

ISSUE_TYPES = [
    "over-mocking",
    "implementation-detail-assertion",
    "non-determinism",
    "shared-mutable-state",
    "tautological-assertion",
    "assertion-free",
    "framework-not-system",
    "missing-failure-path",
]


class TestItestContracts(unittest.TestCase):
    def test_expected_contracts_exist_with_metadata(self):
        names = sorted(p.name for p in CONTRACTS.glob("*.schema.json"))
        self.assertEqual(names, [
            "conventions.schema.json", "critique.schema.json",
            "scenario.schema.json", "state.schema.json",
        ])
        for path in CONTRACTS.glob("*.schema.json"):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["type"], "object")
                self.assertIn("contract_version", schema["required"])

    def test_every_contract_has_a_validating_example(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            name = path.name.replace(".schema.json", "")
            example = CONTRACTS / "examples" / f"{name}.example.json"
            with self.subTest(contract=name):
                self.assertTrue(example.exists(), f"missing example for {name}")
                errors = validate(json.loads(example.read_text(encoding="utf-8")),
                                  json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(errors, [])

    def test_critique_issue_types_match_the_doctrine(self):
        schema = json.loads((CONTRACTS / "critique.schema.json").read_text(encoding="utf-8"))
        enum = (schema["properties"]["assessed"]["items"]["properties"]["issues"]
                ["items"]["properties"]["type"]["enum"])
        self.assertEqual(sorted(enum), sorted(ISSUE_TYPES))

    def test_doctrine_documents_every_issue_type(self):
        text = DOCTRINE.read_text(encoding="utf-8")
        for issue in ISSUE_TYPES:
            with self.subTest(issue=issue):
                self.assertIn(issue, text)

    def test_doctrine_states_the_tier_rule_and_composition_rules(self):
        text = DOCTRINE.read_text(encoding="utf-8").lower()
        self.assertIn("arises from integration", text)
        self.assertIn("valid by construction", text)
        self.assertIn("could not itself produce", text)
        self.assertIn("must be asserted on", text)

    def test_conventions_contract_requires_integration_separation(self):
        schema = json.loads(
            (CONTRACTS / "conventions.schema.json").read_text(encoding="utf-8"))
        self.assertIn("integration_separation", schema["required"])
        separation = schema["properties"]["integration_separation"]
        self.assertEqual(sorted(separation["required"]), ["how_to_add", "mechanism"])

    def test_state_contract_records_whether_injection_is_possible(self):
        schema = json.loads((CONTRACTS / "state.schema.json").read_text(encoding="utf-8"))
        store = schema["properties"]["writable_stores"]["items"]
        self.assertIn("direct_write_possible", store["required"])


if __name__ == "__main__":
    unittest.main()
