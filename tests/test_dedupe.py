import sqlite3
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import dedupe as dd


def mem_db():
    conn = sqlite3.connect(":memory:")
    dd.init_db(conn)
    return conn


class TestSchema(unittest.TestCase):
    def test_tables_created(self):
        conn = mem_db()
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"entities", "edges", "dead_candidates",
                         "dup_clusters", "cluster_members", "findings"} <= names)

    def test_code_types(self):
        self.assertEqual(dd.CODE_TYPES, {"function", "method", "type", "constant"})


class TestClassifiers(unittest.TestCase):
    def test_is_unexported_go(self):
        self.assertTrue(dd.is_unexported("helper", "api/x.go"))
        self.assertFalse(dd.is_unexported("Helper", "api/x.go"))

    def test_is_unexported_python_ts(self):
        self.assertTrue(dd.is_unexported("_priv", "pkg/x.py"))
        self.assertFalse(dd.is_unexported("pub", "pkg/x.py"))
        self.assertTrue(dd.is_unexported("_priv", "src/x.ts"))

    def test_is_entrypoint(self):
        for n in ("main", "init", "TestFoo", "BenchmarkX", "ExampleY", "FuzzZ"):
            self.assertTrue(dd.is_entrypoint(n), n)
        self.assertFalse(dd.is_entrypoint("doWork"))

    def test_is_test(self):
        for p in ("api/x_test.go", "src/x.test.ts", "src/x.spec.ts",
                  "test/util.go", "pkg/__tests__/a.ts", "tests/test_x.py"):
            self.assertTrue(dd.is_test(p), p)
        self.assertFalse(dd.is_test("api/handler.go"))


if __name__ == "__main__":
    unittest.main()
