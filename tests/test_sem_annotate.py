import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_annotate as sa


class TestCommentPrefix(unittest.TestCase):
    def test_go_ts_js_use_slashes(self):
        for p in ("a/b/x.go", "x.ts", "x.tsx", "x.js", "x.jsx"):
            self.assertEqual(sa.comment_prefix(p), "//", p)

    def test_python_uses_hash(self):
        self.assertEqual(sa.comment_prefix("pkg/mod/x.py"), "#")

    def test_unsupported_returns_none(self):
        self.assertIsNone(sa.comment_prefix("README.md"))
        self.assertIsNone(sa.comment_prefix("x.rs"))


class TestParseMarkers(unittest.TestCase):
    SRC = (
        "package auth\n"                                  # 0
        "\n"                                              # 1
        "// SEM@b14a829: validate an oauth token (pure)\n"  # 2
        "func Validate() {}\n"                            # 3
        "    # SEM@deadbee: parse a config file\n"        # 4 (indented, hash)
        "x = 1\n"                                         # 5
    )

    def test_parse_returns_indexed_markers(self):
        got = sa.parse_markers(self.SRC)
        self.assertEqual(set(got), {2, 4})
        self.assertEqual(got[2]["sha"], "b14a829")
        self.assertEqual(got[2]["desc"], "validate an oauth token (pure)")
        self.assertEqual(got[4]["sha"], "deadbee")

    def test_find_marker_above_entity(self):
        lines = self.SRC.splitlines()
        m = sa.find_marker_above(lines, 4)   # entity 'func Validate' is on 1-based line 4
        self.assertIsNotNone(m)
        self.assertEqual(m["sha"], "b14a829")

    def test_find_marker_above_none_when_not_a_marker(self):
        lines = self.SRC.splitlines()
        # entity on 1-based line 2 ('// SEM...') -> line above is blank line 1 -> no marker
        self.assertIsNone(sa.find_marker_above(lines, 2))


class TestApplyMarker(unittest.TestCase):
    def test_build_marker_format(self):
        self.assertEqual(
            sa.build_marker("//", "  ", "abc1234", "validate a token"),
            "  // SEM@abc1234: validate a token",
        )

    def test_insert_when_absent(self):
        lines = ["package p", "", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "abc1234", "compute a checksum")
        self.assertEqual(out[2], "// SEM@abc1234: compute a checksum")
        self.assertEqual(out[3], "func F() {}")
        self.assertEqual(len(out), 4)

    def test_replace_when_present(self):
        lines = ["package p", "// SEM@abc0000: stale desc", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "def2222", "fresh desc")
        self.assertEqual(out, ["package p", "// SEM@def2222: fresh desc", "func F() {}"])

    def test_indentation_matches_entity(self):
        lines = ["class C:", "    def m(self): pass"]
        out = sa.apply_marker(lines, 2, "#", "abc1234", "handle a request")
        self.assertEqual(out[1], "    # SEM@abc1234: handle a request")
        self.assertEqual(out[2], "    def m(self): pass")


class TestClassify(unittest.TestCase):
    FULL = "b14a829fd98bc22eaf2939ee51854649b9620cb0"

    def test_missing_when_no_marker(self):
        self.assertEqual(sa.classify(None, self.FULL, False), "missing")

    def test_fresh_when_sha_prefix_matches_blame(self):
        self.assertEqual(sa.classify("b14a829", self.FULL, True), "fresh")

    def test_stale_when_blame_moved_and_logic_changed(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, True), "stale")

    def test_fresh_when_blame_moved_but_cosmetic_only(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, False), "fresh")


class TestClassifyRobust(unittest.TestCase):
    def test_uncommitted_none(self):
        self.assertEqual(sa.classify("b14a829", None, False), "uncommitted")

    def test_uncommitted_empty(self):
        self.assertEqual(sa.classify("b14a829", "", False), "uncommitted")

    def test_uncommitted_all_zeros(self):
        self.assertEqual(sa.classify("b14a829", "0000000000000000000000000000000000000000", False), "uncommitted")

    def test_missing_takes_precedence_over_uncommitted(self):
        self.assertEqual(sa.classify(None, None, False), "missing")

    def test_is_uncommitted_helper(self):
        self.assertTrue(sa._is_uncommitted(None))
        self.assertTrue(sa._is_uncommitted(""))
        self.assertTrue(sa._is_uncommitted("0000000"))
        self.assertFalse(sa._is_uncommitted("b14a829"))


class TestInvalidRevError(unittest.TestCase):
    def _patch(self, stderr):
        import subprocess as sp
        def fake_run(cmd, cwd=None, capture_output=True, text=True, check=True):
            raise sp.CalledProcessError(1, cmd, stderr=stderr)
        self._orig = sa.subprocess.run
        sa.subprocess.run = fake_run

    def tearDown(self):
        if hasattr(self, "_orig"):
            sa.subprocess.run = self._orig

    def test_revspec_not_found_raises_invalidrev(self):
        self._patch("Error: git error: revspec 'abc123' not found; class=Reference (4); code=NotFound (-3)")
        with self.assertRaises(sa.InvalidRevError):
            sa.run_sem(["diff", "abc123..HEAD", "--no-cosmetics", "--", "x.ts"])

    def test_invalidrev_is_semerror(self):
        self.assertTrue(issubclass(sa.InvalidRevError, sa.SemError))

    def test_other_failure_is_plain_semerror(self):
        self._patch("some unrelated failure")
        with self.assertRaises(sa.SemError):
            sa.run_sem(["entities", "."])
        # and NOT InvalidRevError
        with self.assertRaises(sa.SemError):
            try:
                sa.run_sem(["entities", "."])
            except sa.InvalidRevError:
                self.fail("should be plain SemError, not InvalidRevError")


class TestEntityLogicSha(unittest.TestCase):
    def setUp(self):
        self._orig_log = sa.sem_log_entity

    def tearDown(self):
        sa.sem_log_entity = self._orig_log

    def test_picks_newest_logic_ignoring_later_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}},
            {"change_type": "modified (logic)", "commit": {"sha": "bbb222"}},
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}},
        ]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "bbb222")

    def test_added_only(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "aaa111")

    def test_fallback_when_only_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")

    def test_fallback_when_empty(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": []}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "")

    def test_sem_log_entity_returns_empty_on_semerror(self):
        def boom(args, cwd=None):
            raise sa.SemError("nope")
        orig = sa.run_sem
        sa.run_sem = boom
        try:
            self.assertEqual(sa.sem_log_entity("E", "f.py"), {"changes": []})
        finally:
            sa.run_sem = orig


class TestScan(unittest.TestCase):
    def setUp(self):
        self.files = {}  # path -> source text

        def fake_read(path):
            return self.files[path]

        self._orig_read = sa._read_text
        self._orig_entities = sa.sem_entities
        self._orig_blame = sa.sem_blame
        self._orig_logic = sa.logic_changed_entities
        sa._read_text = fake_read

    def tearDown(self):
        sa._read_text = self._orig_read
        sa.sem_entities = self._orig_entities
        sa.sem_blame = self._orig_blame
        sa.logic_changed_entities = self._orig_logic

    def test_scan_flags_missing_and_stale_only(self):
        path = "auth/x.go"
        self.files[path] = (
            "package auth\n"
            "// SEM@aaaaaaa: validate a token\n"   # fresh: sha matches blame below
            "func Fresh() {}\n"
            "func Missing() {}\n"                   # no marker -> missing
        )
        entities = [
            {"name": "Fresh", "type": "function", "start_line": 3, "end_line": 3},
            {"name": "Missing", "type": "function", "start_line": 4, "end_line": 4},
        ]
        blame = [
            {"name": "Fresh", "lines": [3, 3], "commit": "aaaaaaa000111222333"},
            {"name": "Missing", "lines": [4, 4], "commit": "bbbbbbb000111222333"},
        ]
        sa.sem_entities = lambda paths, cwd=None: entities
        sa.sem_blame = lambda f, cwd=None: blame
        sa.logic_changed_entities = lambda base, f, cwd=None: set()

        work = sa.scan([path])
        names = {w["name"]: w["status"] for w in work}
        self.assertEqual(names, {"Missing": "missing"})
        self.assertEqual(work[0]["blame_sha"], "bbbbbbb000111222333")


class TestWrite(unittest.TestCase):
    def test_write_applies_bottom_up(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\nfunc B() {}\n")
            n = sa.write([
                {"file": p, "start_line": 2, "sha": "aaa1111", "desc": "build A"},
                {"file": p, "start_line": 3, "sha": "bbb2222", "desc": "build B"},
            ])
            self.assertEqual(n, 1)  # one file written
            with open(p) as fh:
                out = fh.read().splitlines()
            self.assertEqual(out[1], "// SEM@aaa1111: build A")
            self.assertEqual(out[2], "func A() {}")
            self.assertEqual(out[3], "// SEM@bbb2222: build B")
            self.assertEqual(out[4], "func B() {}")


REAL_DIFF_PAYLOAD = {
    "summary": {"added": 0, "deleted": 0, "modified": 1},
    "changes": [
        {
            "entityName": "classify",
            "changeType": "modified",
            "entityType": "function",
            "startLine": 10,
            "endLine": 20,
            "filePath": "dev/scripts/sem_annotate.py",
        },
        {
            "entityName": "some_added",
            "changeType": "added",
            "entityType": "function",
            "startLine": 30,
            "endLine": 40,
            "filePath": "dev/scripts/sem_annotate.py",
        },
    ],
    "binaryChanges": [],
}


class TestParseChangedEntities(unittest.TestCase):
    def test_returns_only_modified_entities(self):
        result = sa._parse_changed_entities(REAL_DIFF_PAYLOAD)
        self.assertEqual(result, {"classify"})

    def test_added_entities_are_excluded(self):
        result = sa._parse_changed_entities(
            {"changes": [{"changeType": "added", "entityName": "foo"}]}
        )
        self.assertEqual(result, set())

    def test_empty_payload_returns_empty_set(self):
        self.assertEqual(sa._parse_changed_entities({}), set())


class TestArgs(unittest.TestCase):
    def test_scan_subcommand(self):
        ns = sa.parse_args(["scan", "auth/", "-C", "/repo"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["auth/"])
        self.assertEqual(ns.cwd, "/repo")
        self.assertFalse(ns.rebuild)

    def test_update_is_scan_over_files(self):
        ns = sa.parse_args(["--update", "a.go", "b.go"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go", "b.go"])

    def test_update_with_cwd(self):
        ns = sa.parse_args(["--update", "a.go", "-C", "/repo"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go"])
        self.assertEqual(ns.cwd, "/repo")

    def test_update_with_rebuild(self):
        ns = sa.parse_args(["--update", "a.go", "--rebuild"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go"])
        self.assertTrue(ns.rebuild)

    def test_write_subcommand_with_cwd(self):
        ns = sa.parse_args(["write", "-C", "/repo"])
        self.assertEqual(ns.cmd, "write")
        self.assertEqual(ns.cwd, "/repo")


class TestScanScope(unittest.TestCase):
    def setUp(self):
        # No markers => both entities classify as "missing" (surfaced by scan).
        self.files = {"src/a.ts": "function A() {}\n",
                      "scripts/b.ts": "function B() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.logic_changed_entities, sa.sem_scope.load_scope)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 1, "end_line": 1},
            {"name": "B", "type": "function", "file": "scripts/b.ts", "start_line": 1, "end_line": 1},
        ]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ccc"}, {"name": "B", "commit": "ddd"}]
        sa.logic_changed_entities = lambda base, f, cwd=None: set()

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.logic_changed_entities, sa.sem_scope.load_scope) = self._orig

    def test_scope_exclude_drops_entities(self):
        sa.sem_scope.load_scope = lambda cwd=None: {"include": ["src/", "scripts/"],
                                                    "exclude": ["scripts/"]}
        work = sa.scan(None)
        names = {w["name"] for w in work}
        self.assertIn("A", names)            # src/ kept (missing marker -> surfaced)
        self.assertNotIn("B", names)         # scripts/ excluded by scope

    def test_explicit_paths_ignore_scope(self):
        called = {"n": 0}
        def boom(cwd=None):
            called["n"] += 1
            return {"exclude": ["**/*"]}
        sa.sem_scope.load_scope = boom
        sa.scan(["src/a.ts"])
        self.assertEqual(called["n"], 0)     # explicit args => scope file never consulted


class TestDbSubcommand(unittest.TestCase):
    def test_db_status_dispatches(self):
        import sem_db
        orig = sem_db.status
        sem_db.status = lambda cwd=None: {"verdict": "up-to-date", "stored_sha": "x",
                                          "stored_count": "1", "current_sha": "x",
                                          "current_count": "1"}
        out = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = out
        try:
            rc = sa.main(["db", "status", "-C", "/tmp"])
        finally:
            sys.stdout = _stdout
            sem_db.status = orig
        self.assertEqual(rc, 0)
        self.assertIn("up-to-date", out.getvalue())

    def test_db_update_no_files_is_auto(self):
        import sem_db
        called = {"auto": 0}
        orig = sem_db.auto_update
        sem_db.auto_update = lambda cwd=None: called.__setitem__("auto", 1) or {"mode": "auto", "files": 0, "entities": 0}
        try:
            rc = sa.main(["db", "update", "-C", "/tmp"])
        finally:
            sem_db.auto_update = orig
        self.assertEqual(rc, 0)
        self.assertEqual(called["auto"], 1)


if __name__ == "__main__":
    unittest.main()
