import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "discover" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.report import build_inventory
from repowalk import EXCLUDE_DIRS, walk_repo
from repobuilder import build_repo, git_commit_all, git_init


class TestWalkRepo(unittest.TestCase):
    def test_lists_files_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(
                tmp,
                {
                    "b.py": "x = 1\n",
                    "a.py": "y = 2\n",
                    "pkg/c.py": "z = 3\n",
                },
            )
            files, method = walk_repo(root)
            self.assertEqual(files, ["a.py", "b.py", "pkg/c.py"])
            self.assertEqual(method, "walk")

    def test_skips_noise_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(
                tmp,
                {
                    "app.py": "x = 1\n",
                    "node_modules/left-pad/index.js": "//\n",
                    ".venv/lib/thing.py": "x = 1\n",
                    "dist/bundle.js": "//\n",
                },
            )
            files, _ = walk_repo(root)
            self.assertEqual(files, ["app.py"])

    def test_uses_git_listing_and_honors_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(
                tmp,
                {
                    ".gitignore": "secret.txt\n",
                    "app.py": "x = 1\n",
                    "secret.txt": "shh\n",
                },
            )
            git_init(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertIn("app.py", files)
            self.assertNotIn("secret.txt", files)

    def test_git_listing_filters_skip_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(
                tmp,
                {
                    "app.py": "x = 1\n",
                    "vendor/lib/thing.go": "package lib\n",
                    "node_modules/left-pad/index.js": "//\n",
                },
            )
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertEqual(files, ["app.py"])

    def test_skip_dirs_contains_expected_entries(self):
        self.assertTrue({"node_modules", ".venv", "vendor", "dist"} <= EXCLUDE_DIRS)


# inventorylib's own SKIP_DIRS before the walks were merged into repowalk (#115).
PRE_MERGE_INVENTORY_SKIP_DIRS = frozenset(
    {
        ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "vendor", "dist", "build", "target",
        "out", "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next", ".gradle",
        "site-packages", ".idea",
    }
)  # fmt: skip

APP = {
    "pyproject.toml": "[project]\nname = 'app'\nversion = '0.1.0'\n",
    "app.py": "print('hi')\n",
    "infra/main.tf": 'resource "null_resource" "x" {}\n',
    "ios/Podfile": "platform :ios, '15.0'\n",
}
NOISE = {
    ".terraform/providers/registry/null/main.tf": 'resource "null_resource" "y" {}\n',
    "infra/.terraform/modules/vpc/variables.tf": 'variable "x" {}\n',
    "ios/Pods/Alamofire/Source/AF.swift": "import Foundation\n",
    "ios/Pods/Manifest.lock": "PODS:\n",
}


def inventory(files, git):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        if git:
            git_init(root)
            git_commit_all(root)
        inv = build_inventory(root)
    inv.pop("root")
    return inv


class TestInventoryAfterWalkMerge(unittest.TestCase):
    """The merged walk changes inventory output for .terraform/ and Pods/, plus the two named deltas below."""

    def test_exclusion_set_grew_by_exactly_terraform_and_pods(self):
        self.assertEqual(set(EXCLUDE_DIRS) - PRE_MERGE_INVENTORY_SKIP_DIRS, {".terraform", "Pods"})
        self.assertEqual(PRE_MERGE_INVENTORY_SKIP_DIRS - set(EXCLUDE_DIRS), set())

    def test_terraform_and_pods_trees_leave_the_inventory_unchanged(self):
        for git in (False, True):
            with self.subTest(method="git" if git else "walk"):
                self.assertEqual(inventory({**APP, **NOISE}, git), inventory(APP, git))

    def test_the_same_trees_under_other_names_do_change_it(self):
        """Control: the comparison above is sensitive to these files when they are not excluded."""
        renamed = {k.replace(".terraform", "terraform").replace("Pods", "pods"): v for k, v in NOISE.items()}
        for git in (False, True):
            with self.subTest(method="git" if git else "walk"):
                self.assertNotEqual(inventory({**APP, **renamed}, git), inventory(APP, git))

    def test_named_delta_non_ascii_names_are_listed_as_they_are_on_disk(self):
        """Before the merge, git mode returned C-quoted names ("caf\\303\\251.py") that do not exist on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"caf\u00e9.py": "x = 1\n"})
            git_init(root)
            git_commit_all(root)
            files, method = walk_repo(root)
        self.assertEqual(method, "git")
        self.assertEqual(files, ["caf\u00e9.py"])

    def test_named_delta_unsafe_symlinks_are_not_listed(self):
        """Before the merge, inventory listed absolute and out-of-root symlinks; now none is listed."""
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "secret.txt"
            target.write_text("shh\n")
            root = build_repo(tmp, {"app.py": "x = 1\n", "inside.txt": "ok\n"})
            os.symlink(target, Path(root) / "absolute.txt")
            os.symlink(os.path.relpath(target, root), Path(root) / "escapes.txt")
            os.symlink("inside.txt", Path(root) / "relative.txt")
            files, _ = walk_repo(root)
        self.assertEqual(files, ["app.py", "inside.txt", "relative.txt"])


if __name__ == "__main__":
    unittest.main()
