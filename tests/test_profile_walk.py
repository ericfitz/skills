import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.walk import SKIP_DIRS, walk_repo
from repobuilder import build_repo, git_init


class TestWalkRepo(unittest.TestCase):
    def test_lists_files_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "b.py": "x = 1\n",
                "a.py": "y = 2\n",
                "pkg/c.py": "z = 3\n",
            })
            files, method = walk_repo(root)
            self.assertEqual(files, ["a.py", "b.py", "pkg/c.py"])
            self.assertEqual(method, "walk")

    def test_skips_noise_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "app.py": "x = 1\n",
                "node_modules/left-pad/index.js": "//\n",
                ".venv/lib/thing.py": "x = 1\n",
                "dist/bundle.js": "//\n",
            })
            files, _ = walk_repo(root)
            self.assertEqual(files, ["app.py"])

    def test_uses_git_listing_and_honors_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                ".gitignore": "secret.txt\n",
                "app.py": "x = 1\n",
                "secret.txt": "shh\n",
            })
            git_init(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertIn("app.py", files)
            self.assertNotIn("secret.txt", files)

    def test_skip_dirs_contains_expected_entries(self):
        self.assertTrue({"node_modules", ".venv", "vendor", "dist"} <= SKIP_DIRS)


if __name__ == "__main__":
    unittest.main()
