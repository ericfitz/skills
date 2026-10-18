import unittest

from bumplib import projects as proj


class TestSplitProject(unittest.TestCase):
    def test_default_is_the_root(self):
        self.assertEqual(proj.split_project(["a==1", "b==2"]), (".", ["a==1", "b==2"]))

    def test_flag_anywhere_is_removed_and_normalized(self):
        self.assertEqual(proj.split_project(["--project", "./x/y/", "a==1"]), ("x/y", ["a==1"]))
        self.assertEqual(proj.split_project(["a==1", "--project", "."]), (".", ["a==1"]))

    def test_dangling_or_repeated_flag_is_rejected(self):
        for bad in (["--project"], ["--project", ".", "--project", "x"]):
            with self.subTest(bad), self.assertRaises(ValueError):
                proj.split_project(bad)

    def test_require_root(self):
        proj.require_root(".", "go")
        with self.assertRaises(ValueError):
            proj.require_root("svc", "go")


class TestShapes(unittest.TestCase):
    def test_join_and_parent(self):
        self.assertEqual(proj.join(".", "uv.lock"), "uv.lock")
        self.assertEqual(proj.join("a/b", "uv.lock"), "a/b/uv.lock")
        self.assertEqual(proj.parent_of("uv.lock"), ".")
        self.assertEqual(proj.parent_of(""), ".")
        self.assertEqual(proj.parent_of("a/b/uv.lock"), "a/b")

    def test_merge_unions_members_by_dir_in_first_seen_order(self):
        got = proj.merge(
            [{"dir": ".", "members": ["."]}, {"dir": "s", "members": ["s"]}, {"dir": "./", "members": [".", "w"]}]
        )
        self.assertEqual(got, [{"dir": ".", "members": [".", "w"]}, {"dir": "s", "members": ["s"]}])

    def test_merge_rejects_bad_shapes(self):
        for bad in ({"dir": "."}, [{"members": []}], [None], [{"dir": ".", "members": [1]}]):
            with self.subTest(bad), self.assertRaises(ValueError):
                proj.merge(bad)

    def test_resolve_prefers_a_projects_own_dir_over_a_members_claim(self):
        projects = [{"dir": ".", "members": [".", "sub"]}, {"dir": "sub", "members": ["sub"]}]
        self.assertEqual(proj.resolve("sub/uv.lock", projects), "sub")
        self.assertEqual(proj.resolve("pkg.json", projects), ".")
        self.assertIsNone(proj.resolve("other/uv.lock", projects))


if __name__ == "__main__":
    unittest.main()
