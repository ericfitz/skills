import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.report import build_inventory, coverage_confidence
from repobuilder import build_repo

PY_REPO = {
    "pyproject.toml": "[project]\nname = 'demo'\n",
    "uv.lock": "version = 1\n",
    "src/app.py": "def run(): pass\n",
    "tests/integration/test_api.py": "def test_x(): pass\n",
    "docker-compose.yml": "services: {}\n",
    "README.md": "# demo\n",
}


def inventory(files):
    with tempfile.TemporaryDirectory() as tmp:
        return build_inventory(build_repo(tmp, files))


class TestCoverageConfidence(unittest.TestCase):
    def test_no_languages_is_low(self):
        self.assertEqual(coverage_confidence([], [{"path": "go.mod"}], [], 3), "low")

    def test_no_manifests_is_low(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [], [], 3), "low")

    def test_mostly_classified_is_high(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}], [], 100),
            "high")

    def test_many_unclassified_is_partial(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}],
                                ["a.zig"] * 20, 100),
            "partial")


class TestBuildInventory(unittest.TestCase):
    def test_has_all_required_keys(self):
        found = inventory(PY_REPO)
        self.assertEqual(set(found), {
            "root", "listing_method", "languages", "manifests", "test_files",
            "test_dirs", "test_config", "ci", "containers", "iac",
            "entrypoints", "docs", "docs_total", "docs_sites", "unclassified",
            "unclassified_total", "coverage_confidence", "inventory_version",
        })

    def test_root_is_absolute_and_paths_are_relative(self):
        found = inventory(PY_REPO)
        self.assertTrue(Path(found["root"]).is_absolute())
        self.assertEqual(found["manifests"][0]["path"], "pyproject.toml")

    def test_python_repo_is_classified_end_to_end(self):
        found = inventory(PY_REPO)
        self.assertEqual(found["languages"][0]["name"], "python")
        self.assertEqual(found["manifests"][0]["package_manager"], "uv")
        self.assertEqual(found["test_files"][0]["kind"], "integration")
        self.assertEqual(found["test_dirs"], ["tests/integration"])
        self.assertEqual(found["containers"][0]["kind"], "compose")
        self.assertEqual(found["coverage_confidence"], "high")

    def test_documentation_census_is_carried_into_the_inventory(self):
        found = inventory(PY_REPO)
        self.assertEqual([d["path"] for d in found["docs"]], ["README.md"])
        self.assertEqual(found["docs"][0]["doc_type_guess"], "readme")
        self.assertEqual(found["docs_total"], 1)
        self.assertEqual(found["docs_sites"], [])

    def test_docs_are_truncated_with_total_preserved(self):
        files = {"docs/d%03d.md" % i: "# x\n" for i in range(250)}
        found = inventory(files)
        self.assertEqual(len(found["docs"]), 200)
        self.assertEqual(found["docs_total"], 250)

    def test_unrecognized_stack_reports_low_confidence_not_a_wrong_answer(self):
        found = inventory({"main.zig": "pub fn main() void {}\n",
                           "build.zig": "pub fn build() void {}\n"})
        self.assertEqual(found["languages"], [])
        self.assertEqual(found["manifests"], [])
        self.assertEqual(found["coverage_confidence"], "low")
        self.assertEqual(sorted(found["unclassified"]), ["build.zig", "main.zig"])

    def test_unclassified_is_truncated_with_total_preserved(self):
        files = {"f%03d.zig" % i: "x\n" for i in range(250)}
        found = inventory(files)
        self.assertEqual(len(found["unclassified"]), 200)
        self.assertEqual(found["unclassified_total"], 250)


if __name__ == "__main__":
    unittest.main()
