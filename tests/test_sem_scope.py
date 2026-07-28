import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_scope as ss


class TestGlobMatch(unittest.TestCase):
    def test_dir_prefix_trailing_slash(self):
        self.assertTrue(ss.glob_match("scripts", "scripts/"))
        self.assertTrue(ss.glob_match("scripts/build.ts", "scripts/"))
        self.assertFalse(ss.glob_match("scriptsx/build.ts", "scripts/"))

    def test_doublestar_crosses_slashes(self):
        self.assertTrue(ss.glob_match("src/a/b.spec.ts", "**/*.spec.ts"))
        self.assertTrue(ss.glob_match("b.spec.ts", "**/*.spec.ts"))
        self.assertFalse(ss.glob_match("src/a/b.ts", "**/*.spec.ts"))

    def test_single_star_does_not_cross_slash(self):
        self.assertTrue(ss.glob_match("a.ts", "*.ts"))
        self.assertFalse(ss.glob_match("a/b.ts", "*.ts"))

    def test_question_mark(self):
        self.assertTrue(ss.glob_match("a.ts", "?.ts"))
        self.assertFalse(ss.glob_match("ab.ts", "?.ts"))
        self.assertFalse(ss.glob_match("a/c", "a?c"))   # ? must not cross '/'


class TestIsExcluded(unittest.TestCase):
    def test_any_pattern_matches(self):
        scope = {"exclude": ["scripts/", "**/*.spec.ts"]}
        self.assertTrue(ss.is_excluded("scripts/x.ts", scope))
        self.assertTrue(ss.is_excluded("src/a.spec.ts", scope))
        self.assertFalse(ss.is_excluded("src/a.ts", scope))

    def test_none_scope_or_no_exclude(self):
        self.assertFalse(ss.is_excluded("a.ts", None))
        self.assertFalse(ss.is_excluded("a.ts", {}))

    def test_backslashes_normalized(self):
        self.assertTrue(ss.is_excluded("scripts\\x.ts", {"exclude": ["scripts/"]}))


class TestIncludePaths(unittest.TestCase):
    def test_default_when_empty(self):
        self.assertEqual(ss.include_paths(None), ["."])
        self.assertEqual(ss.include_paths({}), ["."])
        self.assertEqual(ss.include_paths({"include": []}), ["."])

    def test_returns_include(self):
        self.assertEqual(ss.include_paths({"include": ["src/", "e2e/"]}), ["src/", "e2e/"])


class TestLoadScope(unittest.TestCase):
    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ss.load_scope(d))

    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                json.dump({"include": ["src/"], "exclude": ["scripts/"]}, f)
            scope = ss.load_scope(d)
            self.assertEqual(scope["include"], ["src/"])
            self.assertEqual(scope["exclude"], ["scripts/"])

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                f.write("{not json")
            with self.assertRaises(ValueError):
                ss.load_scope(d)

    def test_wrong_type_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                json.dump({"include": "src/"}, f)  # not a list
            with self.assertRaises(ValueError):
                ss.load_scope(d)


if __name__ == "__main__":
    unittest.main()
