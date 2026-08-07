import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from bumplib.ecosystems import python as py

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


def _make_venv(root, posix=True):
    """Create the marker files that identify a project virtualenv."""
    d = root / ".venv" / ("bin" if posix else "Scripts")
    d.mkdir(parents=True)
    exe = d / ("python" if posix else "python.exe")
    exe.write_text("")
    return exe


class TestPython(unittest.TestCase):
    def test_parse_outdated(self):
        recs = {r.name: r for r in py.parse_outdated((FIX / "pip_outdated.json").read_text())}
        self.assertEqual(recs["requests"].current, "2.28.0")
        self.assertEqual(recs["requests"].latest, "2.31.0")

    def test_parse_audit(self):
        advs = py.parse_audit((FIX / "pip_audit.json").read_text())
        self.assertTrue(any("PYSEC" in (a.ids[0] if a.ids else "") for a in advs))

    def test_audit_missing_binary_uv(self):
        """Regression test: audit verb should return [] when uv binary is missing (uv manager)."""
        # Mock detect to return uv manager
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None), \
                mock.patch("bumplib.ecosystems.python.detect") as mock_detect:
            mock_detect.return_value = {"packageManager": "uv"}
            result = py.handle("audit", [])
            self.assertEqual(result, [])

    def test_audit_missing_binary_pip(self):
        """Regression test: audit verb should return [] when pip-audit binary is missing (pip manager)."""
        # Mock detect to return pip manager
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None), \
                mock.patch("bumplib.ecosystems.python.detect") as mock_detect:
            mock_detect.return_value = {"packageManager": "pip"}
            result = py.handle("audit", [])
            self.assertEqual(result, [])


class TestProjectEnvironmentTargeting(unittest.TestCase):
    """The verbs must inspect the PROJECT environment, never the ambient one.

    bump.py carries a PEP 723 header, so `uv run bump.py` executes it in an isolated
    ephemeral environment. `uv pip list --outdated` inherits that environment and reports
    on it -- an env with nothing installed -- so `outdated` returned [] for every uv
    project no matter how many packages were actually stale.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        self.calls = []
        self.enterContext(mock.patch("bumplib.ecosystems.python.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.python.detect",
                                     return_value={"packageManager": "uv", "present": True}))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args):
        self.calls.append(list(args))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_outdated_targets_project_venv(self):
        """Regression: without --python this reads the ephemeral env and always sees []."""
        exe = _make_venv(self.root)
        py.handle("outdated", [])
        self.assertEqual(self.calls[0][:5], ["uv", "pip", "list", "--outdated", "--format"])
        self.assertIn("--python", self.calls[0])
        self.assertEqual(self.calls[0][self.calls[0].index("--python") + 1], str(exe))

    def test_outdated_without_venv_omits_flag(self):
        """No project venv -> fall back to ambient discovery rather than passing a bad path."""
        py.handle("outdated", [])
        self.assertNotIn("--python", self.calls[0])

    def test_outdated_honors_uv_project_environment(self):
        """uv's documented override for a non-.venv environment directory."""
        d = self.root / "envs" / "prod" / "bin"
        d.mkdir(parents=True)
        (d / "python").write_text("")
        with mock.patch.dict(os.environ, {"UV_PROJECT_ENVIRONMENT": "envs/prod"}):
            py.handle("outdated", [])
        self.assertEqual(self.calls[0][self.calls[0].index("--python") + 1], str(d / "python"))

    def test_windows_layout_resolved(self):
        exe = _make_venv(self.root, posix=False)
        py.handle("outdated", [])
        self.assertEqual(self.calls[0][self.calls[0].index("--python") + 1], str(exe))

    def test_audit_runs_against_the_project(self):
        """Same isolation defect: `uv run pip-audit` audited the ephemeral env."""
        _make_venv(self.root)
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value="/usr/bin/uv"):
            py.handle("audit", [])
        self.assertIn("--project", self.calls[0])
        self.assertEqual(self.calls[0][self.calls[0].index("--project") + 1], str(self.root))

    def test_pip_manager_path_unchanged(self):
        """Only the uv path was environment-ambiguous; plain pip must not gain flags."""
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}):
            py.handle("outdated", [])
        self.assertEqual(self.calls[0], ["pip", "list", "--outdated", "--format", "json"])


if __name__ == "__main__":
    unittest.main()
