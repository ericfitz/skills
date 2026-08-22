# tests/test_dependency_model_contracts.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import resolve_refs, validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "dependency-model" / "references" / "contracts"
EXAMPLES = CONTRACTS / "examples"
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]

VALUE_SHAPED = ("value", "secret", "token", "password", "passwd",
                "credential", "content", "material")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


class TestContractFilesExist(unittest.TestCase):
    def test_every_expected_schema_is_present(self):
        names = sorted(p.name for p in CONTRACTS.glob("*.schema.json"))
        expected = sorted(
            ["dependency-core.schema.json", "discovery.schema.json"]
            + [f"{c}.schema.json" for c in CATEGORIES])
        self.assertEqual(names, expected)

    def test_every_category_has_an_example(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertTrue((EXAMPLES / f"{category}.example.json").exists())


class TestEnvelope(unittest.TestCase):
    def test_envelope_requires_version_target_and_categories(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        self.assertEqual(schema["type"], "object")
        for field in ("contract_version", "target", "categories"):
            self.assertIn(field, schema["required"])
            self.assertIn(field, schema["properties"])

    def test_envelope_references_all_six_category_schemas(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        refs = schema["properties"]["categories"]["properties"]
        self.assertEqual(sorted(refs), CATEGORIES)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(refs[category]["$ref"],
                                 f"{category}.schema.json")

    def test_envelope_resolves_without_error(self):
        resolved = resolve_refs(load(CONTRACTS / "discovery.schema.json"), CONTRACTS)
        item = resolved["properties"]["categories"]["properties"]["service"]
        self.assertIn("dependencies", item["properties"])


class TestExamplesValidate(unittest.TestCase):
    def test_each_example_validates_against_the_envelope(self):
        schema = load(CONTRACTS / "discovery.schema.json")
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                self.assertEqual(validate(instance, schema, base_dir=CONTRACTS), [])

    def test_each_example_populates_exactly_its_own_category(self):
        """D6: one skill emits a full envelope with one category populated."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                self.assertEqual(list(instance["categories"]), [category])

    def test_each_example_has_at_least_one_dependency_with_evidence(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                deps = instance["categories"][category]["dependencies"]
                self.assertTrue(deps, "example has no dependencies to prove shape")
                for dep in deps:
                    self.assertTrue(dep["evidence"])
                    self.assertTrue(dep["id"].startswith(f"{category}:"))

    def test_every_example_declares_contract_version_1_0_0(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertEqual(
                    load(EXAMPLES / f"{category}.example.json")["contract_version"],
                    "1.0.0")


class TestSharedCore(unittest.TestCase):
    def test_every_category_item_refs_the_shared_core(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                item = schema["properties"]["dependencies"]["items"]
                self.assertEqual(item["$ref"], "dependency-core.schema.json")

    def test_core_requires_all_five_resilience_facts(self):
        """A skill must state 'no declaration found' explicitly, not by omission."""
        core = load(CONTRACTS / "dependency-core.schema.json")
        resilience = core["properties"]["resilience"]
        self.assertEqual(sorted(resilience["required"]),
                         ["fallback", "health_check", "on_path", "retry", "timeout"])

    def test_each_resilience_fact_accepts_null(self):
        core = load(CONTRACTS / "dependency-core.schema.json")
        props = core["properties"]["resilience"]["properties"]
        for fact in ("timeout", "retry", "fallback", "health_check"):
            with self.subTest(fact=fact):
                self.assertIn("null", props[fact]["type"])

    def test_core_documents_that_null_is_not_confirmed_absent(self):
        text = (CONTRACTS / "dependency-core.schema.json").read_text(
            encoding="utf-8").lower()
        self.assertIn("no declaration was found", text)
        self.assertIn("never", text)

    def test_every_category_status_enum_is_the_same_three_values(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                self.assertEqual(schema["properties"]["status"]["enum"],
                                 ["discovered", "not-applicable", "failed"])

    def test_every_category_requires_assumptions(self):
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                self.assertIn("assumptions", schema["required"])


class TestSecurityNeverCarriesValues(unittest.TestCase):
    """A discovery skill that writes credentials into a contract is a leak.
    The schema must give it nowhere to put one."""

    def test_security_details_declares_no_value_shaped_property(self):
        schema = load(CONTRACTS / "security.schema.json")
        details = schema["properties"]["dependencies"]["items"]["properties"]["details"]
        for name in details["properties"]:
            with self.subTest(field=name):
                self.assertNotIn(name.lower(), VALUE_SHAPED)

    def test_security_example_carries_no_value_shaped_key_anywhere(self):
        text = (EXAMPLES / "security.example.json").read_text(encoding="utf-8")
        for key in json.loads(text)["categories"]["security"]["dependencies"]:
            for field in key["details"]:
                with self.subTest(field=field):
                    self.assertNotIn(field.lower(), VALUE_SHAPED)


class TestContractStaysInItsLayer(unittest.TestCase):
    def test_no_criticality_or_remediation_vocabulary(self):
        """Layers 2-4 judge; layer 1 reports. Banned words keep that boundary
        visible in review."""
        banned = ("criticality", "severity", "blast_radius", "remediation",
                  "recommendation", "risk_score", "priority")
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                with self.subTest(schema=path.name, word=word):
                    self.assertNotIn(word, text)

    def test_no_probing_vocabulary(self):
        """D3: nothing is measured, so nothing names a measurement."""
        banned = ("measured", "observed_latency", "reachable", "resolved_ip",
                  "ping", "probe_result")
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8").lower()
            for word in banned:
                with self.subTest(schema=path.name, word=word):
                    self.assertNotIn(word, text)


if __name__ == "__main__":
    unittest.main()
