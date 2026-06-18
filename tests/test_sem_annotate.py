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


if __name__ == "__main__":
    unittest.main()
