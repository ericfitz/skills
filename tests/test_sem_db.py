import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_db as db


class TestSchemaMeta(unittest.TestCase):
    def test_connect_creates_db_and_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".local", "sem.db")
            conn = db.connect(p)
            self.assertTrue(os.path.exists(p))
            tbls = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("meta", tbls)
            self.assertIn("entities", tbls)
            conn.close()

    def test_meta_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, "sem.db"))
            db.set_meta(conn, "head_sha", "abc123")
            db.set_meta(conn, "head_sha", "def456")  # upsert, not duplicate
            self.assertEqual(db.get_meta(conn, "head_sha"), "def456")
            self.assertIsNone(db.get_meta(conn, "missing"))
            conn.close()

    def test_stamp_head_uses_git_head(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, "sem.db"))
            db.git_head = lambda cwd=None: ("deadbeef", "42")
            db.stamp_head(conn, cwd=d)
            self.assertEqual(db.get_meta(conn, "head_sha"), "deadbeef")
            self.assertEqual(db.get_meta(conn, "head_commit_count"), "42")
            self.assertEqual(db.get_meta(conn, "schema_version"), db.SCHEMA_VERSION)
            self.assertIsNotNone(db.get_meta(conn, "updated_at"))
            conn.close()


if __name__ == "__main__":
    unittest.main()
