# tests/test_dependency_model_references.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
REFERENCES = REPO / "dependency-model" / "references"
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]


class TestReferencesExist(unittest.TestCase):
    def test_the_three_references_are_present(self):
        for name in ("categories.md", "resilience-signatures.md",
                     "running-discovery.md"):
            with self.subTest(reference=name):
                self.assertTrue((REFERENCES / name).exists())


class TestCategoriesReference(unittest.TestCase):
    def test_names_every_category(self):
        text = (REFERENCES / "categories.md").read_text(encoding="utf-8").lower()
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(category, text)

    def test_carries_the_service_network_adjudication_rule(self):
        text = (REFERENCES / "categories.md").read_text(encoding="utf-8").lower()
        self.assertIn("related_ids", text)
        self.assertIn("the thing depended on", text)
        self.assertIn("the path used to reach it", text)


class TestResilienceSignatures(unittest.TestCase):
    def test_documents_all_three_in_scope_ecosystems(self):
        text = (REFERENCES / "resilience-signatures.md").read_text(
            encoding="utf-8").lower()
        for language in ("go", "typescript", "python"):
            with self.subTest(language=language):
                self.assertIn(language, text)

    def test_states_that_null_is_not_confirmed_absent(self):
        text = (REFERENCES / "resilience-signatures.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("no declaration was found", text)


class TestRunningDiscovery(unittest.TestCase):
    def test_documents_the_sequence_and_the_deferred_orchestrator(self):
        text = (REFERENCES / "running-discovery.md").read_text(encoding="utf-8")
        self.assertIn("profile:topology", text)
        self.assertIn("depscan.py", text)
        for category in CATEGORIES:
            with self.subTest(category=category):
                self.assertIn(f"/dependency-model:{category}", text)
        self.assertIn("no orchestrator", text.lower())

    def test_documents_the_python3_fallback(self):
        text = (REFERENCES / "running-discovery.md").read_text(encoding="utf-8")
        self.assertIn("python3", text)


if __name__ == "__main__":
    unittest.main()
