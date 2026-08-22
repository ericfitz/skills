# tests/test_depscan_source.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.source import SOURCE_LANGUAGES, scan_source
from depscanlib.walk import walk_repo
from repobuilder import build_repo


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_source(root, paths)


def names(findings, key):
    return sorted(item["name"] for item in findings[key])


def kinds(findings):
    return sorted({item["kind"] for item in findings["resilience_calls"]})


class TestEnvRefs(unittest.TestCase):
    def test_go_getenv_and_lookupenv(self):
        findings, _ = scan({"main.go":
            'package main\n\nfunc a() {\n\tx := os.Getenv("DATABASE_URL")\n'
            '\ty, ok := os.LookupEnv("REDIS_ADDR")\n}\n'})
        self.assertEqual(names(findings, "env_refs"), ["DATABASE_URL", "REDIS_ADDR"])

    def test_python_environ_forms(self):
        findings, _ = scan({"app.py":
            'import os\nA = os.environ["DATABASE_URL"]\n'
            'B = os.environ.get("REDIS_ADDR")\nC = os.getenv("QUEUE_URL")\n'})
        self.assertEqual(names(findings, "env_refs"),
                         ["DATABASE_URL", "QUEUE_URL", "REDIS_ADDR"])

    def test_javascript_process_env_forms(self):
        findings, _ = scan({"server.js":
            'const a = process.env.DATABASE_URL;\n'
            'const b = process.env["REDIS_ADDR"];\n'})
        self.assertEqual(names(findings, "env_refs"), ["DATABASE_URL", "REDIS_ADDR"])

    def test_typescript_is_scanned_like_javascript(self):
        findings, _ = scan({"src/config.ts": 'export const u = process.env.API_URL;\n'})
        self.assertEqual(names(findings, "env_refs"), ["API_URL"])

    def test_records_file_and_one_indexed_line(self):
        findings, _ = scan({"app.py": 'import os\n\nX = os.getenv("A_KEY")\n'})
        self.assertEqual(findings["env_refs"],
                         [{"name": "A_KEY", "file": "app.py", "line": 3}])

    def test_same_name_twice_is_two_records(self):
        findings, _ = scan({"app.py": 'os.getenv("A")\nos.getenv("A")\n'})
        self.assertEqual(len(findings["env_refs"]), 2)

    def test_out_of_scope_language_yields_no_env_refs(self):
        findings, _ = scan({"main.rs": 'let x = std::env::var("DATABASE_URL");\n'})
        self.assertEqual(findings["env_refs"], [])

    def test_javascript_destructured_process_env(self):
        findings, _ = scan({"server.js": 'const { DATABASE_URL, PORT } = process.env;\n'})
        self.assertEqual(names(findings, "env_refs"), ["DATABASE_URL", "PORT"])

    def test_javascript_optional_chaining_process_env(self):
        findings, _ = scan({"config.js": 'const u = process.env?.FOO;\n'})
        self.assertEqual(names(findings, "env_refs"), ["FOO"])

    def test_python_bare_environ_imported_from_os(self):
        findings, _ = scan({"app.py":
            'from os import environ\nX = environ.get("DB_URL")\n'})
        self.assertEqual(names(findings, "env_refs"), ["DB_URL"])


class TestResilienceCalls(unittest.TestCase):
    def test_go_context_with_timeout_and_deadline(self):
        findings, _ = scan({"db.go":
            'ctx, cancel := context.WithTimeout(parent, 5*time.Second)\n'
            'ctx2, c2 := context.WithDeadline(parent, t)\n'})
        self.assertEqual(kinds(findings), ["deadline", "timeout"])

    def test_go_struct_timeout_field(self):
        findings, _ = scan({"client.go": 'c := &http.Client{Timeout: 3 * time.Second}\n'})
        self.assertIn("timeout", kinds(findings))

    def test_python_timeout_kwarg_and_retry_decorator(self):
        findings, _ = scan({"client.py":
            'import requests\nfrom tenacity import retry\n\n'
            '@retry\ndef get():\n    return requests.get(url, timeout=5)\n'})
        self.assertEqual(kinds(findings), ["retry", "timeout"])

    def test_javascript_abort_signal_and_axios_timeout(self):
        findings, _ = scan({"api.ts":
            'const s = AbortSignal.timeout(2000);\n'
            'const c = axios.create({ timeout: 3000 });\n'})
        self.assertEqual(kinds(findings), ["timeout"])

    def test_circuit_breaker_libraries_are_recognised(self):
        findings, _ = scan({
            "b.go": 'import "github.com/sony/gobreaker"\n',
            "b.py": 'import pybreaker\n',
            "b.js": 'const CircuitBreaker = require("opossum");\n',
        })
        by_file = {r["file"]: r["kind"] for r in findings["resilience_calls"]}
        self.assertEqual(by_file, {"b.go": "circuit-breaker", "b.py": "circuit-breaker",
                                   "b.js": "circuit-breaker"})

    def test_records_the_matched_text_verbatim_as_raw(self):
        findings, _ = scan({"db.go": 'context.WithTimeout(parent, 5*time.Second)\n'})
        record = findings["resilience_calls"][0]
        self.assertIn("WithTimeout", record["raw"])
        self.assertEqual(record["file"], "db.go")
        self.assertEqual(record["line"], 1)
        self.assertEqual(record["language"], "go")

    def test_findings_are_sorted_by_file_then_line(self):
        """Feed an unsorted paths list directly: walk_repo already returns
        sorted paths, so routing through it would pass even if scan_source
        never sorted anything itself."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"b.py": 'requests.get(u, timeout=1)\n',
                                    "a.py": 'requests.get(u, timeout=2)\n'})
            findings, _ = scan_source(root, ["b.py", "a.py"])
        files = [r["file"] for r in findings["resilience_calls"]]
        self.assertEqual(files, ["a.py", "b.py"])

    def test_raw_is_capped_at_200_characters(self):
        """A minified bundle line can run tens of KB; raw must not carry
        that into the findings payload."""
        huge_line = 'const CircuitBreaker=require("opossum");' + ("x" * 40000)
        findings, _ = scan({"vendor.min.js": huge_line + "\n"})
        record = findings["resilience_calls"][0]
        self.assertEqual(len(record["raw"]), 200)

    def test_timeout_kwarg_not_confused_with_equality_check(self):
        findings, _ = scan({"app.py": 'if timeout == 30:\n    pass\n'})
        self.assertEqual(kinds(findings), [])


class TestSkippedLanguages(unittest.TestCase):
    def test_out_of_scope_source_is_reported_not_silently_dropped(self):
        """D9: the gap must be visible in the contract."""
        _, skipped = scan({"main.rs": "fn main() {}\n", "lib.rs": "pub fn a() {}\n",
                           "app.py": "x = 1\n"})
        self.assertEqual(skipped, [{
            "reason": "source-literal scanning covers go, js, python, and ts only",
            "language": "rust", "count": 2}])

    def test_in_scope_only_repo_reports_nothing_skipped(self):
        _, skipped = scan({"app.py": "x = 1\n", "main.go": "package main\n"})
        self.assertEqual(skipped, [])

    def test_non_source_files_are_not_reported_as_skipped(self):
        _, skipped = scan({"README.md": "# hi\n", "data.json": "{}\n"})
        self.assertEqual(skipped, [])

    def test_the_three_in_scope_ecosystems_are_the_documented_ones(self):
        self.assertEqual(sorted(set(SOURCE_LANGUAGES.values())),
                         ["go", "js", "python", "ts"])


if __name__ == "__main__":
    unittest.main()
