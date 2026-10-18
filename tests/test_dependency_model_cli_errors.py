# tests/test_dependency_model_cli_errors.py
import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"

# Every dependency-model CLI that reports failures as {"error": ...} on stderr.
JSON_ERROR_CLIS = ("idmap.py", "depgraph.py", "health.py", "depscan.py", "pkglifecycle.py")

# Arguments that satisfy each CLI's required ones, so an unknown flag is the
# only usage error left to report.
VALID_ARGS = {"pkglifecycle.py": (".", "--syft-json", "syft.json")}


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          capture_output=True, text=True)


class UsageErrorsAreJsonTest(unittest.TestCase):
    """A usage error is a failure like any other: the caller parses stderr as
    JSON, so argparse's plain-text usage message must not leak through."""

    def test_unknown_flag_is_a_json_error(self):
        for script in JSON_ERROR_CLIS:
            with self.subTest(script=script):
                result = run(script, *VALID_ARGS.get(script, ("input.json",)), "--no-such-flag")
                self.assertEqual(result.returncode, 2)
                self.assertIn("--no-such-flag", json.loads(result.stderr)["error"])

    def test_missing_argument_is_a_json_error(self):
        for script in ("idmap.py", "depgraph.py", "health.py"):
            with self.subTest(script=script):
                result = run(script)
                self.assertEqual(result.returncode, 2)
                self.assertIn("required", json.loads(result.stderr)["error"])

    def test_help_stays_plain_text(self):
        for script in JSON_ERROR_CLIS:
            with self.subTest(script=script):
                result = run(script, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("usage:"))


if __name__ == "__main__":
    unittest.main()
