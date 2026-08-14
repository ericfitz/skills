import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bumplib.gitfiles import changed_files

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00",
           "HOME": "/dev/null", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True)


class TestChangedFiles(unittest.TestCase):
    """apply must report the files git actually saw change, not a hardcoded list."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _git(self.root, "init", "-q")
        (self.root / "go.mod").write_text("module x\n")
        (self.root / "go.sum").write_text("")
        _git(self.root, "add", "go.mod", "go.sum")
        _git(self.root, "commit", "-qm", "init")

    def test_reports_only_the_candidates_that_changed(self):
        (self.root / "go.mod").write_text("module x\nrequire y v1.0.0\n")
        self.assertEqual(changed_files(["go.mod", "go.sum"], cwd=self.root), ["go.mod"])

    def test_untracked_candidate_counts_as_changed(self):
        (self.root / "uv.lock").write_text("x")
        self.assertEqual(changed_files(["pyproject.toml", "uv.lock"], cwd=self.root), ["uv.lock"])

    def test_clean_tree_reports_nothing(self):
        self.assertEqual(changed_files(["go.mod", "go.sum"], cwd=self.root), [])

    def test_non_repo_falls_back_to_candidates(self):
        with TemporaryDirectory() as plain:
            self.assertEqual(changed_files(["a", "b"], cwd=plain), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
