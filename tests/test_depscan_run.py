# tests/test_depscan_run.py
"""Git-ignored excludes, --ref snapshots, and per-run output directories."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import depscan
from depscanlib.report import build_scan
from depscanlib.run import RefError, prepare
from repobuilder import build_repo, git_commit_all, git_init

SCRIPT = Path(__file__).resolve().parents[1] / "dependency-model" / "scripts" / "depscan.py"


def committed_repo(tmp):
    """A git repo with one committed manifest, an ignored build dir holding a
    manifest of its own, and one untracked file."""
    root = git_init(build_repo(Path(tmp) / "repo", {
        ".gitignore": "junk/\nbin/app\n",
        "requirements.txt": "flask==3.0\n",
    }))
    git_commit_all(root)
    build_repo(root, {
        "junk/requirements.txt": "stale==1.0\n",
        "bin/app": "binary\n",
        "untracked.py": "import os\n",
    })
    return root


class TestIgnored(unittest.TestCase):
    def test_git_ignored_paths_are_listed_without_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = build_scan(committed_repo(tmp))
            self.assertEqual(scan["ignored"], ["bin", "junk"])

    def test_syft_excludes_combine_glob_names_and_root_anchored_ignores(self):
        """syft only matches globs: bare names become **/<name>, repo-relative
        ignored paths become ./<path>. Computed here so no skill re-derives it."""
        with tempfile.TemporaryDirectory() as tmp:
            excludes = build_scan(committed_repo(tmp))["syft_excludes"]
            self.assertIn("**/node_modules", excludes)
            self.assertIn("./junk", excludes)
            self.assertIn("./bin", excludes)

    def test_non_git_target_has_no_ignored_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = build_scan(build_repo(tmp, {"app.py": "x = 1\n"}))
            self.assertEqual(scan["ignored"], [])
            self.assertIsNone(scan["ref"])


def linked_repo(tmp):
    """A committed repo holding one safe link and three unsafe ones."""
    outside = build_repo(Path(tmp) / "outside", {"secret.txt": "API_KEY=x\n"})
    root = git_init(build_repo(Path(tmp) / "repo", {"app.py": "x = 1\n"}))
    (root / "inside.py").symlink_to("app.py")
    (root / "escape.txt").symlink_to("../outside/secret.txt")
    (root / "absolute.txt").symlink_to(outside / "secret.txt")
    (root / "absolute-inside.py").symlink_to(root / "app.py")
    git_commit_all(root)
    return root


class TestSymlinks(unittest.TestCase):
    """Only relative links that stay inside the repo are followed; anything
    else is treated as hostile and never read."""

    def test_unsafe_links_are_listed_and_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            scan = build_scan(linked_repo(tmp))
            self.assertEqual(scan["unsafe_links"],
                             ["absolute-inside.py", "absolute.txt", "escape.txt"])
            self.assertEqual(scan["coverage"]["files_scanned"], 2)
            self.assertNotIn("API_KEY", json.dumps(scan["findings"]))

    def test_snapshot_reports_the_links_it_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = linked_repo(tmp)
            run = prepare(root, "HEAD", tmp_base=tmp)
            self.assertTrue((run.scan_root / "inside.py").is_symlink())
            self.assertEqual(run.refused,
                             ["absolute-inside.py", "absolute.txt", "escape.txt"])
            scan = build_scan(run.scan_root, target=root, ref=run.ref,
                              refused=run.refused)
            self.assertEqual(scan["unsafe_links"], run.refused)


class TestPrepare(unittest.TestCase):
    def test_working_tree_run_scans_the_repo_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            run = prepare(root, None, tmp_base=tmp)
            self.assertEqual(run.scan_root, root.resolve())
            self.assertIsNone(run.ref)

    def test_ref_run_scans_a_snapshot_of_committed_files_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            run = prepare(root, "HEAD", tmp_base=tmp)
            self.assertTrue((run.scan_root / "requirements.txt").is_file())
            self.assertFalse((run.scan_root / "untracked.py").exists())
            self.assertFalse((run.scan_root / "junk").exists())
            self.assertEqual(run.ref["name"], "HEAD")
            self.assertEqual(len(run.ref["commit"]), 40)

    def test_a_committed_absolute_symlink_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            (root / "escape.json").symlink_to("/etc/hosts")
            git_commit_all(root, "link")
            run = prepare(root, "HEAD", tmp_base=tmp)
            self.assertTrue((run.scan_root / "requirements.txt").is_file())
            self.assertFalse((run.scan_root / "escape.json").exists())

    def test_run_dirs_differ_by_ref_and_are_stable_per_ref(self):
        """Two branches of one repo must never share a run dir; the same
        commit always maps to the same one."""
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            tree = prepare(root, None, tmp_base=tmp).run_dir
            head = prepare(root, "HEAD", tmp_base=tmp).run_dir
            self.assertNotEqual(tree, head)
            self.assertEqual(head, prepare(root, "HEAD", tmp_base=tmp).run_dir)

    def test_unknown_ref_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RefError):
            prepare(committed_repo(tmp), "no-such-branch", tmp_base=tmp)

    def test_ref_on_a_non_git_target_raises(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(RefError):
            prepare(build_repo(tmp, {"a.py": "x\n"}), "main", tmp_base=tmp)


class TestScanOfSnapshot(unittest.TestCase):
    def test_target_stays_the_repo_and_ref_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            run = prepare(root, "HEAD", tmp_base=tmp)
            scan = build_scan(run.scan_root, target=root, ref=run.ref)
            self.assertEqual(scan["target"], str(root.resolve()))
            self.assertEqual(scan["scan_root"], str(run.scan_root))
            self.assertEqual(scan["ref"], run.ref)
            self.assertNotIn("untracked.py", json.dumps(scan["files"]))


class TestWriteCli(unittest.TestCase):
    def test_write_saves_the_scan_in_the_run_dir_and_prints_the_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = committed_repo(tmp)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), str(root), "--ref", "HEAD", "--write"],
                capture_output=True, text=True, timeout=60, check=False,
                env={"TMPDIR": tmp, "PATH": "/usr/bin:/bin:/opt/homebrew/bin"})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            run_dir = Path(proc.stdout.strip())
            scan = json.loads((run_dir / "depscan.json").read_text())
            self.assertEqual(scan["run_dir"], str(run_dir))
            self.assertEqual(scan["ref"]["name"], "HEAD")

    def test_unknown_ref_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(depscan.main([str(committed_repo(tmp)), "--ref", "nope"]), 2)


if __name__ == "__main__":
    unittest.main()
