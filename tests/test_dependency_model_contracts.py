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
                "credential", "content", "material", "key")

# Enum membership pinned so a later rename (e.g. "object-store" ->
# "objectstore") fails a test instead of silently passing every example,
# since each example exercises only one enum member.
CATEGORY_DETAIL_ENUMS = {
    "service": {"kind": ["database", "cache", "queue", "object-store", "search", "api"]},
    "package": {"resolution": ["declared", "locked", "installed"]},
    "config": {"mechanism": ["env", "file", "flag", "remote", "constant", "unknown"]},
    "security": {"kind": ["secret", "credential-ref", "permission", "role", "policy",
                          "certificate-ref"]},
    "platform": {
        "kind": ["cpu", "memory", "disk", "gpu", "arch", "os", "runtime-version",
                 "cloud-service"],
        "source": ["dockerfile", "compose", "kubernetes", "iac", "ci", "manifest", "docs"],
    },
    "network": {
        "kind": ["hostname", "ip", "port", "dns", "egress", "proxy", "ingress"],
        "direction": ["inbound", "outbound", "internal", "unknown"],
    },
}

RESILIENCE_OBJECT_FACTS = ("timeout", "retry", "fallback", "health_check")


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def is_value_shaped(name):
    """Substring match, not exact: a field named 'secret_value' or 'api_key'
    is just as much of a leak vector as one named 'value' outright."""
    lowered = name.lower()
    return any(banned in lowered for banned in VALUE_SHAPED)


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

    def test_each_example_carries_at_least_one_null_resilience_fact(self):
        """The brief requires this; nothing pinned it before now."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                instance = load(EXAMPLES / f"{category}.example.json")
                deps = instance["categories"][category]["dependencies"]
                facts = [dep["resilience"][fact]
                         for dep in deps for fact in RESILIENCE_OBJECT_FACTS]
                self.assertIn(None, facts,
                              "example declares no 'no declaration found' fact")


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

    def test_every_category_details_rejects_unknown_properties(self):
        """A typo'd field name in a category's details object should fail a
        real validator, not silently pass through as an unknown key."""
        for category in CATEGORIES:
            with self.subTest(category=category):
                schema = load(CONTRACTS / f"{category}.schema.json")
                details = schema["properties"]["dependencies"]["items"]["properties"]["details"]
                self.assertEqual(details.get("additionalProperties"), False)

    def test_envelope_categories_rejects_unknown_properties(self):
        """A typo'd category key (e.g. "servcie") must fail a real validator,
        not merge silently into layer 2's key-union graph."""
        schema = load(CONTRACTS / "discovery.schema.json")
        categories = schema["properties"]["categories"]
        self.assertEqual(categories.get("additionalProperties"), False)

    def test_every_resilience_object_fact_rejects_unknown_properties(self):
        """Same guarantee as details objects: a typo'd resilience field
        should fail validation, not pass through silently."""
        core = load(CONTRACTS / "dependency-core.schema.json")
        props = core["properties"]["resilience"]["properties"]
        for fact in RESILIENCE_OBJECT_FACTS:
            with self.subTest(fact=fact):
                self.assertEqual(props[fact].get("additionalProperties"), False)


class TestEnumMembership(unittest.TestCase):
    """Each enum has exactly one member exercised by its example, so a
    silent rename would pass every other test in this suite. Pin the full
    membership here instead."""

    def test_category_details_enums_are_pinned(self):
        for category, fields in CATEGORY_DETAIL_ENUMS.items():
            schema = load(CONTRACTS / f"{category}.schema.json")
            details_props = (schema["properties"]["dependencies"]["items"]
                              ["properties"]["details"]["properties"])
            for field, expected in fields.items():
                with self.subTest(category=category, field=field):
                    self.assertEqual(details_props[field]["enum"], expected)

    def test_core_on_path_enum_is_pinned(self):
        core = load(CONTRACTS / "dependency-core.schema.json")
        on_path = core["properties"]["resilience"]["properties"]["on_path"]
        self.assertEqual(on_path["items"]["enum"],
                         ["startup", "request", "background", "build"])


class TestSecurityNeverCarriesValues(unittest.TestCase):
    """A discovery skill that writes credentials into a contract is a leak.
    The schema must give it nowhere to put one."""

    def test_security_details_declares_no_value_shaped_property(self):
        schema = load(CONTRACTS / "security.schema.json")
        details = schema["properties"]["dependencies"]["items"]["properties"]["details"]
        for name in details["properties"]:
            with self.subTest(field=name):
                self.assertFalse(is_value_shaped(name))

    def test_security_example_carries_no_value_shaped_key_anywhere(self):
        text = (EXAMPLES / "security.example.json").read_text(encoding="utf-8")
        for dep in json.loads(text)["categories"]["security"]["dependencies"]:
            for field in dep["details"]:
                with self.subTest(field=field):
                    self.assertFalse(is_value_shaped(field))

    def test_widened_value_shaped_list_does_not_false_positive_on_real_fields(self):
        """Guards the widening itself: security's own legitimate field names
        must survive the substring check that api_key-style names must not."""
        for name in ("kind", "provider", "scope", "granted_to", "rotation_declared"):
            with self.subTest(field=name):
                self.assertFalse(is_value_shaped(name))
        for name in ("api_key", "key_material", "secret_value", "value"):
            with self.subTest(field=name):
                self.assertTrue(is_value_shaped(name))

    def test_security_details_rejects_unknown_properties(self):
        """additionalProperties: false is inert to this repo's validator but
        enforced by real downstream validators — the guarantee in the
        description is only real once nothing unlisted can be written."""
        schema = load(CONTRACTS / "security.schema.json")
        details = schema["properties"]["dependencies"]["items"]["properties"]["details"]
        self.assertEqual(details.get("additionalProperties"), False)


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


class TestLifecycle(unittest.TestCase):
    """Two values only. The build environment is a strict superset of the
    runtime environment, so a runtime dependency is present at build BECAUSE
    it is a runtime dependency -- `both` would record the containment twice."""

    def test_core_requires_lifecycle_with_exactly_two_values(self):
        core = load(CONTRACTS / "dependency-core.schema.json")
        self.assertIn("lifecycle", core["required"])
        self.assertEqual(core["properties"]["lifecycle"]["enum"], ["build", "run"])

    def test_no_schema_admits_a_both_value(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            with self.subTest(schema=path.name):
                self.assertNotIn('"both"', path.read_text(encoding="utf-8"))

    def test_every_example_dependency_declares_lifecycle(self):
        for category in CATEGORIES:
            instance = load(EXAMPLES / f"{category}.example.json")
            for dep in instance["categories"][category]["dependencies"]:
                with self.subTest(category=category, dep=dep["id"]):
                    self.assertIn(dep["lifecycle"], ("build", "run"))

    def test_package_example_is_build_and_service_example_is_run(self):
        pkg = load(EXAMPLES / "package.example.json")
        self.assertEqual(
            pkg["categories"]["package"]["dependencies"][0]["lifecycle"], "build")
        svc = load(EXAMPLES / "service.example.json")
        self.assertEqual(
            svc["categories"]["service"]["dependencies"][0]["lifecycle"], "run")


if __name__ == "__main__":
    unittest.main()
