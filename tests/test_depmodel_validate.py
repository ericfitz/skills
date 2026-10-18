# tests/test_depmodel_validate.py
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dependency-model" / "scripts" / "validate.py"
EXAMPLES = REPO / "dependency-model" / "references" / "contracts" / "examples"


def run(contract, path):
    return subprocess.run([sys.executable, str(SCRIPT), contract, str(path)],
                          capture_output=True, text=True)


class ValidateCliTest(unittest.TestCase):
    def test_valid_examples(self):
        for contract, name in (("discovery", "service"), ("synthesis", "synthesis")):
            with self.subTest(contract):
                self.assertEqual(run(contract, EXAMPLES / f"{name}.example.json").returncode, 0)

    def test_invalid_envelope_resolves_refs(self):
        doc = json.loads((EXAMPLES / "service.example.json").read_text())
        # error must come from inside the $ref'd service schema
        doc["categories"]["service"]["dependencies"][0].pop("name")
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(doc))
            result = run("discovery", bad)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("name", result.stdout)

    def test_stray_key_in_closed_object_fails(self):
        doc = json.loads((EXAMPLES / "synthesis.example.json").read_text())
        doc["graph"]["mermaid"] = "graph TD"
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(doc))
            result = run("synthesis", bad)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unexpected property 'mermaid'", result.stdout)

    def service_doc_with(self, used_by):
        doc = json.loads((EXAMPLES / "service.example.json").read_text())
        doc["categories"]["service"]["dependencies"][0]["details"]["used_by"] = used_by
        return doc

    def run_doc(self, doc):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.json"
            path.write_text(json.dumps(doc))
            return run("discovery", path)

    def test_min_items_rejects_empty_evidence(self):
        result = self.run_doc(self.service_doc_with(
            [{"component_id": "component:api", "evidence": []}]))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("at least 1", result.stdout)

    def test_used_by_extra_property_rejected(self):
        result = self.run_doc(self.service_doc_with(
            [{"component_id": "component:api", "evidence": ["a.go:1"], "role": "x"}]))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("unexpected property 'role'", result.stdout)

    def test_used_by_valid_entry_accepted(self):
        result = self.run_doc(self.service_doc_with(
            [{"component_id": "component:api", "evidence": ["a.go:1"]}]))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_unknown_contract(self):
        self.assertEqual(run("nope", EXAMPLES / "service.example.json").returncode, 2)


if __name__ == "__main__":
    unittest.main()
