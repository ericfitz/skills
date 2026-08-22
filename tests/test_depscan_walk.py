# tests/test_depscan_walk.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.files import classify_files
from depscanlib.walk import EXCLUDE_DIRS, read_text, walk_repo
from repobuilder import build_repo, git_commit_all, git_init


class TestWalkRepo(unittest.TestCase):
    def test_lists_files_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"b.py": "x = 1\n", "a.py": "y = 2\n",
                                    "pkg/c.py": "z = 3\n"})
            files, method = walk_repo(root)
            self.assertEqual(files, ["a.py", "b.py", "pkg/c.py"])
            self.assertEqual(method, "walk")

    def test_excludes_vendored_and_installed_trees(self):
        """D7: an unscoped scan of this repo reported 270 packages against 2
        declared deps, 188 of them from a nested virtualenv."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "app.py": "x = 1\n",
                "node_modules/left-pad/index.js": "//\n",
                ".venv/lib/python3.11/site-packages/thing.py": "x = 1\n",
                "sub/.venv/lib/other.py": "x = 1\n",
                "vendor/lib/thing.go": "package lib\n",
                "dist/bundle.js": "//\n",
            })
            files, _ = walk_repo(root)
            self.assertEqual(files, ["app.py"])

    def test_uses_git_listing_and_honors_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {".gitignore": "ignored.txt\n",
                                    "app.py": "x = 1\n", "ignored.txt": "x\n"})
            git_init(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertIn("app.py", files)
            self.assertNotIn("ignored.txt", files)

    def test_git_listing_still_filters_excluded_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"app.py": "x = 1\n",
                                    "vendor/lib/thing.go": "package lib\n"})
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertEqual(files, ["app.py"])

    def test_exclude_dirs_covers_the_trees_syft_would_otherwise_catalogue(self):
        for name in (".venv", "venv", "node_modules", "vendor",
                     "site-packages", "dist", ".git"):
            with self.subTest(directory=name):
                self.assertIn(name, EXCLUDE_DIRS)

    def test_git_listing_preserves_non_ascii_filenames(self):
        """core.quotepath defaults to true, which C-quotes non-ASCII names in
        plain `git ls-files` output ("caf\\303\\251.yaml" as literal text) --
        a path that does not exist on disk. -z must be used to avoid that."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"café.yaml": "a: 1\n", "app.py": "x = 1\n"})
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertEqual(files, ["app.py", "café.yaml"])
            self.assertEqual(read_text(root, "café.yaml"), "a: 1\n")

    def test_non_ascii_filename_is_still_classifiable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"café.env": "A=1\n"})
            git_init(root)
            git_commit_all(root)
            files, _ = walk_repo(root)
            self.assertEqual(classify_files(root, files)["env"], ["café.env"])

    def test_git_listing_preserves_filenames_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"my file.py": "x = 1\n"})
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertEqual(files, ["my file.py"])


if __name__ == "__main__":
    unittest.main()
