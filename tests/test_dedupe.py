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


if __name__ == "__main__":
    unittest.main()
