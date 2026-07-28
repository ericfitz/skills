import os
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


class TestBuildDropsOrphans(unittest.TestCase):
    """FIX 2: full build (paths=None) must wipe orphan rows for removed/renamed files."""

    def setUp(self):
        self._orig_sa = (sa._read_text, sa.sem_entities, sa.sem_blame)
        self._orig_scope_files = db._scope_files
        self._orig_git_head = db.git_head
        # Default entity for src/a.ts
        sa._read_text = lambda p, *a, **k: "// SEM@aaaaaaa: thing\nfunction A() {}\n"
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "aaaaaaa999"}]
        db.git_head = lambda cwd=None: ("deadbeef", "1")

    def tearDown(self):
        sa._read_text, sa.sem_entities, sa.sem_blame = self._orig_sa
        db._scope_files = self._orig_scope_files
        db.git_head = self._orig_git_head

    def test_full_build_drops_rows_for_files_no_longer_in_scope(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "src", "a.ts"), "w") as f:
                f.write("// SEM@aaaaaaa: thing\nfunction A() {}\n")

            # First build: src/a.ts is in scope, entity A is discovered
            sa.sem_entities = lambda paths, cwd=None: [
                {"name": "A", "type": "function", "file": "src/a.ts",
                 "start_line": 2, "end_line": 2}
            ]
            db._scope_files = lambda cwd, paths: ["src/a.ts"]
            db.build(cwd=d)

            # Verify row is present after first build
            conn = db.connect(db.db_path(d))
            cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE file='src/a.ts'").fetchone()[0]
            conn.close()
            self.assertEqual(cnt, 1, "row should exist after first build")

            # Second build: src/a.ts is no longer in scope (e.g., deleted/renamed)
            sa.sem_entities = lambda paths, cwd=None: []
            db._scope_files = lambda cwd, paths: []
            db.build(cwd=d)

            # The orphan row must be gone after a full rebuild
            conn = db.connect(db.db_path(d))
            cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE file='src/a.ts'").fetchone()[0]
            conn.close()
            self.assertEqual(cnt, 0,
                "full build must delete orphan rows for files no longer in scope")


import sem_scope


class TestAutoUpdateIncludeFilter(unittest.TestCase):
    """FIX 3: auto_update must honor include prefixes, not just exclude globs."""

    def setUp(self):
        self._orig_changed_files = db.changed_files
        self._orig_index_files = db.index_files
        self._orig_stamp_head = db.stamp_head
        self._orig_load_scope = sem_scope.load_scope
        self._indexed = []

    def tearDown(self):
        db.changed_files = self._orig_changed_files
        db.index_files = self._orig_index_files
        db.stamp_head = self._orig_stamp_head
        sem_scope.load_scope = self._orig_load_scope

    def test_auto_update_filters_by_include_prefix(self):
        with tempfile.TemporaryDirectory() as d:
            # Seed a stored head so auto_update takes the incremental path
            conn = db.connect(db.db_path(d))
            db.set_meta(conn, "head_sha", "aabbcc")
            conn.close()

            # Scope: only src/ is included
            sem_scope.load_scope = lambda cwd=None: {"include": ["src/"]}

            # changed_files returns one in-scope and one out-of-scope file
            db.changed_files = lambda cwd, head: ["src/a.py", "tools/b.py"]

            # Capture which files are actually indexed
            indexed = self._indexed
            db.index_files = lambda conn, files, cwd=None: indexed.extend(files) or 0
            db.stamp_head = lambda conn, cwd=None: None

            db.auto_update(cwd=d)

            self.assertEqual(indexed, ["src/a.py"],
                "auto_update should only index files matching include prefixes")


class TestAutoAndStatus(unittest.TestCase):
    def test_auto_update_falls_back_to_build_when_no_head(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            conn.close()
            called = {"build": 0}
            orig = db.build
            db.build = lambda cwd=None, paths=None: called.__setitem__("build", 1) or {
                "files": 0, "entities": 0, "mode": "full"}
            try:
                db.auto_update(cwd=d)
                self.assertEqual(called["build"], 1)
            finally:
                db.build = orig

    def test_status_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            db.set_meta(conn, "head_sha", "aaaa")
            db.set_meta(conn, "head_commit_count", "5")
            conn.close()
            db.git_head = lambda cwd=None: ("aaaa", "5")
            self.assertEqual(db.status(cwd=d)["verdict"], "up-to-date")
            db.git_head = lambda cwd=None: ("bbbb", "6")
            self.assertEqual(db.status(cwd=d)["verdict"], "stale")
            db.git_head = lambda cwd=None: ("", "")
            self.assertEqual(db.status(cwd=d)["verdict"], "unknown")


if __name__ == "__main__":
    unittest.main()
