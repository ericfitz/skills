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


import sem_annotate as sa


class TestIndexFiles(unittest.TestCase):
    def setUp(self):
        self.files = {
            "src/a.ts": "// SEM@aaaaaaa: build a thing\nfunction A() {}\n",
        }
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame)
        sa._read_text = lambda p, *a, **k: self.files[p.replace(self.repo + "/", "")] \
            if p.startswith(self.repo) else self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts",
             "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "aaaaaaa999"}]

    def tearDown(self):
        sa._read_text, sa.sem_entities, sa.sem_blame = self._orig

    def test_index_then_reindex_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo = d
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "src", "a.ts"), "w") as f:
                f.write(self.files["src/a.ts"])
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            n = db.index_files(conn, ["src/a.ts"], cwd=d)
            self.assertEqual(n, 1)
            row = conn.execute(
                "SELECT name, sha, desc, blame_sha FROM entities WHERE file='src/a.ts'"
            ).fetchone()
            self.assertEqual(row[0], "A")
            self.assertEqual(row[1], "aaaaaaa")          # marker sha
            self.assertEqual(row[2], "build a thing")
            self.assertEqual(row[3], "aaaaaaa999")       # blame sha
            # re-index is idempotent (delete-then-insert; still one row)
            db.index_files(conn, ["src/a.ts"], cwd=d)
            cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE file='src/a.ts'").fetchone()[0]
            self.assertEqual(cnt, 1)
            conn.close()


if __name__ == "__main__":
    unittest.main()
