import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_inventory
from repobuilder import build_repo


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = profile_inventory.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_emits_json_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n", "main.go": "package main\n"})
            code, out, _ = run([str(root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["languages"][0]["name"], "go")

    def test_json_flag_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            code, out, _ = run([str(root), "--json"])
        self.assertEqual(code, 0)
        self.assertIn("coverage_confidence", json.loads(out))

    def test_output_is_deterministic_with_sorted_keys(self):
        """The determinism contract: sorted keys, byte-stable across runs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            _, first, _ = run([str(root)])
            _, second, _ = run([str(root)])
        self.assertEqual(first, second)
        self.assertEqual(
            first, json.dumps(json.loads(first), indent=2, sort_keys=True) + "\n")

    def test_indent_flag_changes_formatting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            _, compact, _ = run([str(root), "--indent", "0"])
            _, pretty, _ = run([str(root), "--indent", "4"])
        self.assertLess(len(compact.splitlines()), len(pretty.splitlines()))

    def test_missing_path_exits_two_with_json_error(self):
        code, out, err = run(["/nonexistent/path/xyz"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error", json.loads(err))

    def test_file_instead_of_directory_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n"})
            code, _, _ = run([str(root / "a.py")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
