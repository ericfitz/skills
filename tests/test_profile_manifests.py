# tests/test_profile_manifests.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))

from inventorylib.manifests import detect_manifests


class TestDetectManifests(unittest.TestCase):
    def test_detects_go_module(self):
        found = detect_manifests(["go.mod", "main.go"])
        self.assertEqual(found, [
            {"path": "go.mod", "ecosystem": "go", "package_manager": "go"},
        ])

    def test_lockfile_refines_package_manager(self):
        found = detect_manifests(["pyproject.toml", "uv.lock"])
        self.assertEqual(found[0]["package_manager"], "uv")

    def test_manifest_default_used_when_no_lockfile(self):
        found = detect_manifests(["requirements.txt"])
        self.assertEqual(found[0]["package_manager"], "pip")

    def test_pyproject_without_lockfile_has_no_package_manager(self):
        found = detect_manifests(["pyproject.toml"])
        self.assertIsNone(found[0]["package_manager"])

    def test_lockfile_only_applies_within_same_directory(self):
        found = detect_manifests(["api/package.json", "web/pnpm-lock.yaml"])
        self.assertIsNone(found[0]["package_manager"])

    def test_monorepo_reports_each_manifest_sorted(self):
        found = detect_manifests([
            "web/package.json", "web/yarn.lock", "api/go.mod",
        ])
        self.assertEqual([entry["path"] for entry in found],
                         ["api/go.mod", "web/package.json"])
        self.assertEqual(found[1]["package_manager"], "yarn")

    def test_non_manifest_files_ignored(self):
        self.assertEqual(detect_manifests(["src/app.py", "README.md"]), [])


if __name__ == "__main__":
    unittest.main()
