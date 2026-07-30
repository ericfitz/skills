# tests/test_profile_testfiles.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.testfiles import classify_test_files, test_dirs
from repobuilder import build_repo


def classify(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return classify_test_files(root, sorted(files))


class TestClassifyTestFiles(unittest.TestCase):
    def test_non_test_files_are_excluded(self):
        self.assertEqual(classify({"src/app.py": "x = 1\n"}), [])

    def test_python_name_pattern_is_a_unit_test(self):
        [record] = classify({"tests/test_app.py": "def test_x(): pass\n"})
        self.assertEqual(record["kind"], "unit")
        self.assertEqual(record["language"], "python")
        self.assertIn("name:test_*.py", record["signals"])

    def test_integration_directory_overrides_unit(self):
        [record] = classify({"tests/integration/test_api.py": "def test_x(): pass\n"})
        self.assertEqual(record["kind"], "integration")
        self.assertIn("dir:integration", record["signals"])

    def test_pytest_marker_detected_from_content(self):
        [record] = classify({
            "tests/test_api.py": "import pytest\n\n@pytest.mark.integration\ndef test_x(): pass\n",
        })
        self.assertEqual(record["kind"], "integration")
        self.assertIn("marker:pytest.mark.integration", record["signals"])

    def test_go_build_tag_detected(self):
        [record] = classify({
            "api/client_test.go": "//go:build integration\n\npackage api\n",
        })
        self.assertEqual(record["kind"], "integration")
        self.assertIn("buildtag:integration", record["signals"])
        self.assertEqual(record["language"], "go")

    def test_e2e_beats_integration(self):
        [record] = classify({"tests/e2e/integration/flow.spec.ts": "it('x', () => {})\n"})
        self.assertEqual(record["kind"], "e2e")

    def test_directory_signal_alone_is_unknown(self):
        [record] = classify({"tests/helpers.py": "VALUE = 1\n"})
        self.assertEqual(record["kind"], "unknown")

    def test_markdown_in_a_test_directory_is_not_a_test_file(self):
        """A directory signal alone must not admit a non-source file."""
        self.assertEqual(classify({"docs/contract/terms.md": "# Terms\n"}), [])

    def test_locale_data_in_a_test_named_directory_is_excluded(self):
        """'it' is a Maven test convention and an Italian locale code."""
        self.assertEqual(classify({"src/it/messages.json": "{}\n"}), [])

    def test_signals_are_sorted(self):
        [record] = classify({"tests/integration/test_api.py": "def test_x(): pass\n"})
        self.assertEqual(record["signals"], sorted(record["signals"]))

    def test_unreadable_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"tests/test_a.py": "def test_x(): pass\n"})
            records = classify_test_files(root, ["tests/test_a.py", "tests/test_gone.py"])
            self.assertEqual(len(records), 2)


class TestTestDirs(unittest.TestCase):
    def test_unique_sorted_parent_dirs(self):
        records = [
            {"path": "tests/integration/test_a.py"},
            {"path": "tests/integration/test_b.py"},
            {"path": "tests/test_c.py"},
        ]
        self.assertEqual(test_dirs(records), ["tests", "tests/integration"])


if __name__ == "__main__":
    unittest.main()
