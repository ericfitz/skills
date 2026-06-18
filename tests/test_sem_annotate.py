import sys
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


if __name__ == "__main__":
    unittest.main()
