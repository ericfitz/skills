# tests/test_openapi_findspecs.py
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "openapi" / "scripts"))

import find_specs

MINIMAL_OPENAPI_YAML = """openapi: 3.1.0
info:
  title: t
  version: "1"
paths: {}
"""

MINIMAL_ARAZZO_YAML = """arazzo: 1.0.1
info:
  title: t
  version: "1"
sourceDescriptions:
  - name: api
    url: openapi.yaml
    type: openapi
workflows:
  - workflowId: w1
    steps:
      - stepId: s1
        operationId: op1
"""


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestCandidateSearch(TempTree):
    def test_finds_yaml_openapi3(self):
        self.write("api/openapi.yaml", MINIMAL_OPENAPI_YAML)
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([p.name for p in found], ["openapi.yaml"])

    def test_finds_json_openapi3(self):
        self.write("spec.json", json.dumps(
            {"openapi": "3.0.3", "info": {"title": "t", "version": "1"},
             "paths": {}}))
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([p.name for p in found], ["spec.json"])

    def test_finds_arazzo_yaml(self):
        self.write("arazzo.yaml", MINIMAL_ARAZZO_YAML)
        found = find_specs.find_candidate_files(self.root, "arazzo")
        self.assertEqual([p.name for p in found], ["arazzo.yaml"])

    def test_ignores_non_yaml_json_files(self):
        self.write("README.md", "openapi: 3.1.0\n")
        self.assertEqual(find_specs.find_candidate_files(self.root, "openapi"), [])

    def test_excluded_dirs_are_skipped(self):
        self.write("node_modules/dep/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.assertEqual(find_specs.find_candidate_files(self.root, "openapi"), [])

    @unittest.skipUnless(shutil.which("rg"), "rg not installed")
    def test_gitignored_files_skipped_with_rg(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "generated/\n")
        self.write("generated/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([str(p.relative_to(self.root)) for p in found],
                         ["openapi.yaml"])


class TestVerify(TempTree):
    def _no_validators(self):
        # Hide vacuum/redocly/spectral so the structural branch runs.
        return patch.object(find_specs.shutil, "which", lambda name: None)

    def test_structural_accepts_minimal_openapi(self):
        p = self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertTrue(entry["valid"])
        self.assertEqual(entry["validator"], "structural")
        self.assertEqual(entry["marker"], "openapi-3.1.0")
        self.assertEqual(entry["path"], "openapi.yaml")

    def test_structural_accepts_minimal_arazzo(self):
        p = self.write("arazzo.yaml", MINIMAL_ARAZZO_YAML)
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "arazzo")
        self.assertTrue(entry["valid"])
        self.assertEqual(entry["marker"], "arazzo-1.0.1")

    def test_structural_rejects_marker_without_structure(self):
        # e.g. a dependency pin that matched the grep marker
        p = self.write("deps.json", json.dumps({"openapi": "3.1.0"}))
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertFalse(entry["valid"])
        self.assertEqual(entry["validator"], "structural")

    def test_unparseable_candidate_is_invalid_not_fatal(self):
        p = self.write("bad.yaml", "openapi: 3.1.0\n\t: {broken")
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertFalse(entry["valid"])
        self.assertIn("parse", entry["detail"])

    def test_external_validator_verdict_wins(self):
        p = self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        bindir = self.root / "bin"
        bindir.mkdir()
        stub = bindir / "vacuum"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        with patch.dict(os.environ, {"PATH": str(bindir)}):
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertEqual(entry["validator"], "vacuum")
        self.assertFalse(entry["valid"])


class TestDiscoverAndMain(TempTree):
    def test_ordering_valid_first_then_shallow(self):
        self.write("deep/nested/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.write("openapi.json", json.dumps({"openapi": "3.0.0"}))  # invalid
        self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        with patch.object(find_specs.shutil, "which", lambda name: None):
            result = find_specs.discover(self.root)
        paths = [e["path"] for e in result["openapi"]]
        self.assertEqual(paths, ["openapi.yaml",
                                 str(Path("deep/nested/openapi.yaml")),
                                 "openapi.json"])

    def test_empty_tree_exits_zero_with_empty_lists(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "openapi" / "scripts" / "find_specs.py"),
             str(self.root)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data, {"openapi": [], "arazzo": []})


if __name__ == "__main__":
    unittest.main()
