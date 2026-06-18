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


if __name__ == "__main__":
    unittest.main()
