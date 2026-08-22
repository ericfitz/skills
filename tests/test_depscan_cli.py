# tests/test_depscan_cli.py
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import depscan
from depscanlib.report import build_scan
from repobuilder import build_repo

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dependency-model" / "scripts" / "depscan.py"

FINDING_KEYS = ["env_refs", "host_port_literals", "resilience_calls",
                "resource_limits", "secret_shaped_keys", "url_literals"]


class TestBuildScan(unittest.TestCase):
    def test_emits_the_documented_top_level_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            scan = build_scan(root)
            self.assertEqual(sorted(scan),
                             ["coverage", "exclusions", "files", "findings",
                              "listing_method", "scan_version", "target"])
            self.assertEqual(scan["scan_version"], "1.0.0")
            self.assertEqual(scan["target"], str(Path(root).resolve()))

    def test_every_findings_key_is_present_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"README.md": "# hi\n"})
            self.assertEqual(sorted(build_scan(root)["findings"]), FINDING_KEYS)

    def test_exclusions_are_sorted_and_are_the_shared_source_of_truth(self):
        """The package skill passes these to syft --exclude; the file-scanning
        skills inherit the same list. One list, two tools."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            exclusions = build_scan(root)["exclusions"]
            self.assertEqual(exclusions, sorted(exclusions))
            for name in (".venv", "node_modules", "vendor", "site-packages"):
                self.assertIn(name, exclusions)

    def test_coverage_counts_scanned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n", "b.py": "y = 2\n"})
            coverage = build_scan(root)["coverage"]
            self.assertEqual(coverage["files_scanned"], 2)
            self.assertEqual(coverage["confidence"], "high")
            self.assertEqual(coverage["skipped"], [])

    def test_empty_repo_is_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {})
            self.assertEqual(build_scan(root)["coverage"]["confidence"], "low")

    def test_output_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n", "docker-compose.yml":
                                    "services:\n  db:\n    image: postgres:16\n"})
            self.assertEqual(json.dumps(build_scan(root), sort_keys=True),
                             json.dumps(build_scan(root), sort_keys=True))


class TestCli(unittest.TestCase):
    def test_returns_2_for_a_path_that_is_not_a_directory(self):
        self.assertEqual(depscan.main(["/definitely/not/here"]), 2)

    def test_runs_under_bare_python3_with_no_dependencies(self):
        """depscanlib is stdlib-only so the documented python3 fallback works."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(root)],
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["scan_version"], "1.0.0")

    def test_indent_zero_emits_compact_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n"})
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(root), "--indent", "0"],
                capture_output=True, text=True, timeout=60, check=False)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertNotIn("\n  ", proc.stdout)


class TestCoverageReportsUnscannedLanguages(unittest.TestCase):
    def test_partial_confidence_when_a_language_is_out_of_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n", "main.rs": "fn main() {}\n"})
            coverage = build_scan(root)["coverage"]
            self.assertEqual(coverage["confidence"], "partial")
            self.assertEqual(coverage["skipped"][0]["language"], "rust")


if __name__ == "__main__":
    unittest.main()
