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

    def test_critique_verdicts_match_the_doctrine(self):
        schema = json.loads((CONTRACTS / "critique.schema.json").read_text(encoding="utf-8"))
        enum = schema["properties"]["assessed"]["items"]["properties"]["verdict"]["enum"]
        self.assertEqual(sorted(enum), ["misleading", "sound", "weak"])
        text = DOCTRINE.read_text(encoding="utf-8")
        for verdict in enum:
            with self.subTest(verdict=verdict):
                self.assertIn(f"`{verdict}`", text)

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


class TestScenarioContract(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (CONTRACTS / "scenario.schema.json").read_text(encoding="utf-8"))
        self.scenario = self.schema["properties"]["scenarios"]["items"]

    def test_scenario_carries_placement_and_runner(self):
        required = self.scenario["required"]
        self.assertIn("placement", required)
        self.assertIn("runner_invocation", required)
        placement = self.scenario["properties"]["placement"]["required"]
        self.assertEqual(sorted(placement), ["file_path", "marker_or_tag", "naming"])

    def test_preconditions_record_method_and_assertion(self):
        precondition = self.scenario["properties"]["preconditions"]["items"]
        self.assertEqual(precondition["properties"]["method"]["enum"],
                         ["compose", "inject"])
        self.assertIn("assert_established", precondition["required"])

    def test_open_assumptions_survive_into_every_scenario(self):
        self.assertIn("open_assumptions", self.scenario["required"])

    def test_scenario_records_provenance_and_requirement_traceability(self):
        required = self.scenario["required"]
        self.assertIn("provenance", required)
        self.assertIn("requirement_ids", required)
        self.assertEqual(self.scenario["properties"]["provenance"]["enum"],
                         ["journey", "requirement", "both"])

    def test_cross_cutting_scenarios_may_have_no_journey(self):
        """A requirement no journey owns still produces a scenario."""
        self.assertEqual(self.scenario["properties"]["journey_id"]["type"],
                         ["string", "null"])

    def test_example_has_a_composed_and_an_injected_precondition(self):
        example = json.loads(
            (CONTRACTS / "examples" / "scenario.example.json").read_text(encoding="utf-8"))
        methods = {p["method"]
                   for scenario in example["scenarios"]
                   for p in scenario["preconditions"]}
        self.assertEqual(methods, {"compose", "inject"})

    def test_example_demonstrates_a_cross_cutting_scenario(self):
        example = json.loads(
            (CONTRACTS / "examples" / "scenario.example.json").read_text(encoding="utf-8"))
        by_provenance = {s["provenance"]: s for s in example["scenarios"]}
        self.assertIn("requirement", by_provenance)
        self.assertIsNone(by_provenance["requirement"]["journey_id"])
        self.assertTrue(by_provenance["requirement"]["requirement_ids"])


if __name__ == "__main__":
    unittest.main()
