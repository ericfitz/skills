import io
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

    def _record(self, args, env=None):
        self.calls.append(list(args))
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_outdated_targets_project_venv(self):
        """Regression: without --python this reads the ephemeral env and always sees []."""
        exe = _make_venv(self.root)
        py.handle("outdated", [])
        self.assertEqual(self.calls[0][:5], ["uv", "pip", "list", "--outdated", "--format"])
        self.assertIn("--python", self.calls[0])
        self.assertEqual(self.calls[0][self.calls[0].index("--python") + 1], str(exe))

    def test_no_venv_with_lockfile_auto_syncs_then_targets_venv(self):
        """#28: a fresh clone has uv.lock but no .venv; querying the ambient env returns
        [] for every project. outdated must create the env, then ask it."""
        (self.root / "uv.lock").write_text("")
        exe_holder = {}

        def record(args, env=None):
            args = list(args)
            self.calls.append(args)
            if args[:2] == ["uv", "sync"]:
                exe_holder["exe"] = _make_venv(self.root)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record):
            py.handle("outdated", [])
        self.assertEqual(self.calls[0][:2], ["uv", "sync"])
        listing = self.calls[1]
        self.assertIn("--python", listing)
        self.assertEqual(listing[listing.index("--python") + 1], str(exe_holder["exe"]))

    def test_no_venv_no_lockfile_skips_sync_and_strips_virtual_env(self):
        """Lockless project: don't create an env, but never let the ephemeral
        VIRTUAL_ENV answer 'what is installed?'."""
        captured = {}

        def record(args, env=None):
            self.calls.append(list(args))
            captured["env"] = env
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record), \
                mock.patch.dict(os.environ, {"VIRTUAL_ENV": "/ephemeral"}):
            py.handle("outdated", [])
        self.assertFalse(any(c[:2] == ["uv", "sync"] for c in self.calls))
        self.assertNotIn("--python", self.calls[0])
        self.assertIsNotNone(captured["env"])
        self.assertNotIn("VIRTUAL_ENV", captured["env"])

    def test_sync_failure_still_queries_without_virtual_env(self):
        (self.root / "uv.lock").write_text("")

        def record(args, env=None):
            args = list(args)
            self.calls.append(args)
            rc = 1 if args[:2] == ["uv", "sync"] else 0
            return mock.Mock(returncode=rc, stdout="", stderr="boom")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record):
            py.handle("outdated", [])
        self.assertNotIn("--python", self.calls[1])

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


class TestOutdatedReconcilesVenvWithLock(unittest.TestCase):
    """#37: `uv pip list --outdated` answers for the venv, but uv.lock is what the project
    declares. A venv behind the lock (any `git pull` that touched uv.lock) reports the
    drift as phantom updates; a venv ahead of it hides real ones. So whenever a lockfile
    exists, reconcile the environment to it first -- `--frozen`, so a read verb never
    rewrites the lockfile -- and only then ask the environment."""

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
        self.sync_rc = 0

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args, env=None):
        args = list(args)
        self.calls.append(args)
        rc = self.sync_rc if args[:2] == ["uv", "sync"] else 0
        return mock.Mock(returncode=rc, stdout="", stderr="boom" if rc else "")

    def test_existing_venv_with_lockfile_syncs_before_listing(self):
        """The stale-venv case: venv present, lock present -> sync first, then list."""
        exe = _make_venv(self.root)
        (self.root / "uv.lock").write_text("")
        py.handle("outdated", [])
        self.assertEqual(self.calls[0][:2], ["uv", "sync"])
        listing = self.calls[1]
        self.assertEqual(listing[:5], ["uv", "pip", "list", "--outdated", "--format"])
        self.assertEqual(listing[listing.index("--python") + 1], str(exe))

    def test_sync_is_frozen(self):
        """A read verb must not rewrite uv.lock: plain `uv sync` re-resolves when
        pyproject drifted from the lock, which would then show up in apply's
        git-verified filesModified."""
        _make_venv(self.root)
        (self.root / "uv.lock").write_text("")
        py.handle("outdated", [])
        self.assertIn("--frozen", self.calls[0])

    def test_no_lockfile_does_not_sync(self):
        _make_venv(self.root)
        py.handle("outdated", [])
        self.assertFalse(any(c[:2] == ["uv", "sync"] for c in self.calls))
        self.assertEqual(self.calls[0][:2], ["uv", "pip"])

    def test_sync_failure_with_existing_venv_still_queries_it_and_warns(self):
        exe = _make_venv(self.root)
        (self.root / "uv.lock").write_text("")
        self.sync_rc = 1
        with mock.patch("bumplib.ecosystems.python.sys.stderr", new_callable=io.StringIO) as err:
            py.handle("outdated", [])
        listing = self.calls[1]
        self.assertEqual(listing[listing.index("--python") + 1], str(exe))
        self.assertIn("uv sync", err.getvalue())

    def test_pip_manager_never_syncs(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}):
            py.handle("outdated", [])
        self.assertEqual(self.calls, [["pip", "list", "--outdated", "--format", "json"]])


class TestApplyReportsOnlyRealChanges(unittest.TestCase):
    """#37: `uv lock --upgrade-package X` is a no-op when the lock already holds the
    target, yet apply echoed every spec back in `applied`. A commit message built from
    `applied` then claims a bump that did not happen. For uv the lockfile IS the evidence,
    so an empty git-verified `filesModified` means nothing was applied."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.enterContext(mock.patch("bumplib.ecosystems.python.Path",
                                     side_effect=lambda p: self.root if str(p) == "." else Path(p)))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run",
                                     return_value=mock.Mock(returncode=0, stdout="", stderr="")))

    def test_uv_noop_apply_reports_nothing_applied(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "uv", "present": True}), \
                mock.patch("bumplib.ecosystems.python.changed_files", return_value=[]):
            result = py.handle("apply", ["charset-normalizer==3.5.1"])
        self.assertEqual(result, {"applied": [], "filesModified": []})

    def test_uv_apply_with_lock_change_reports_specs(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "uv", "present": True}), \
                mock.patch("bumplib.ecosystems.python.changed_files", return_value=["uv.lock"]):
            result = py.handle("apply", ["requests==2.32.4"])
        self.assertEqual(result, {"applied": ["requests==2.32.4"], "filesModified": ["uv.lock"]})

    def test_pip_apply_unchanged(self):
        """pip install never edits requirements.txt, so an empty filesModified carries
        no signal there; keep echoing the specs."""
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}), \
                mock.patch("bumplib.ecosystems.python.changed_files", return_value=[]):
            result = py.handle("apply", ["requests==2.32.4"])
        self.assertEqual(result["applied"], ["requests==2.32.4"])


class TestAuditAgainstLockfile(unittest.TestCase):
    """audit must read the LOCKFILE, never the installed environment.

    pip-audit's environment mode asks pip to enumerate installed distributions. In a
    uv-created venv pip enumerates nothing -- measured here: 0 from `pip list` against 33
    dist-info directories on disk and 33 from importlib.metadata -- so pip-audit scanned
    an empty set and reported "No known vulnerabilities found". A security check that
    silently passes because it saw nothing is the failure mode worth engineering against.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        (self.root / "uv.lock").write_text("")
        self.calls = []
        self.responses = {}
        self.enterContext(mock.patch("bumplib.ecosystems.python.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.python.shutil.which", return_value="/bin/uv"))
        self.enterContext(mock.patch("bumplib.ecosystems.python.detect",
                                     return_value={"packageManager": "uv", "present": True}))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run", side_effect=self._record))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args):
        args = list(args)
        self.calls.append(args)
        for marker, (rc, out) in self.responses.items():
            if marker in args:
                return mock.Mock(returncode=rc, stdout=out, stderr="")
        return mock.Mock(returncode=0, stdout="{}", stderr="")

    def _export_call(self):
        return next(c for c in self.calls if "export" in c)

    def _audit_call(self):
        return next(c for c in self.calls if "pip-audit" in c)

    def test_exports_lockfile_to_pylock(self):
        py.handle("audit", [])
        exp = self._export_call()
        self.assertEqual(exp[:2], ["uv", "export"])
        self.assertIn("--frozen", exp)                       # never re-resolve to audit
        self.assertEqual(exp[exp.index("--format") + 1], "pylock.toml")
        self.assertEqual(exp[exp.index("--project") + 1], str(self.root))

    def test_audits_the_exported_file_not_the_environment(self):
        py.handle("audit", [])
        exp, aud = self._export_call(), self._audit_call()
        written = Path(exp[exp.index("-o") + 1])
        self.assertEqual(written.name, "pylock.toml")
        self.assertIn("--locked", aud)
        self.assertEqual(aud[aud.index("--locked") + 1], str(written.parent))

    def test_export_is_temporary_not_written_into_the_project(self):
        """uv ignores a pylock.toml and silently re-resolves, so it must never land
        beside uv.lock where it could be mistaken for the source of truth."""
        py.handle("audit", [])
        exp = self._export_call()
        written = Path(exp[exp.index("-o") + 1])
        self.assertNotIn(str(self.root), str(written))
        self.assertFalse((self.root / "pylock.toml").exists())

    def test_advisories_parsed_from_audit_output(self):
        self.responses["pip-audit"] = (1, (FIX / "pip_audit.json").read_text())
        advs = py.handle("audit", [])
        self.assertTrue(advs)
        self.assertTrue(any("PYSEC" in (a.ids[0] if a.ids else "") for a in advs))

    def test_export_failure_degrades_to_empty(self):
        """No lockfile, or a stale one under --frozen: report nothing rather than
        falling back to the environment mode that silently passes."""
        self.responses["export"] = (2, "")
        self.assertEqual(py.handle("audit", []), [])
        self.assertFalse(any("pip-audit" in c for c in self.calls))

    def test_non_json_output_degrades_to_empty(self):
        """Offline, or pip-audit unavailable: a usage banner must not crash the run."""
        self.responses["pip-audit"] = (1, "error: failed to fetch pip-audit\n")
        self.assertEqual(py.handle("audit", []), [])

    def test_pip_manager_path_unchanged(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}):
            py.handle("audit", [])
        self.assertEqual(self.calls, [["pip-audit", "--format", "json"]])


class TestApplyReportsFailure(unittest.TestCase):
    """apply must surface a failed package-manager command, never report success (#32)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        self.calls = []
        self.fail_on = None          # substring of argv marking the command that fails
        self.enterContext(mock.patch("bumplib.ecosystems.python.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.python.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))
        self.enterContext(mock.patch("bumplib.ecosystems.python.detect",
                                     return_value={"packageManager": "uv", "present": True}))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args, env=None):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return mock.Mock(returncode=1, stdout="", stderr="resolution is unsatisfiable")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_uv_lock_failure_surfaces_error(self):
        self.fail_on = "lock"
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("unsatisfiable", res["error"])
        self.assertFalse(any("sync" in c for c in self.calls))   # stops at first failure

    def test_uv_sync_failure_surfaces_error(self):
        self.fail_on = "sync"
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)

    def test_success_reports_git_verified_files(self):
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], ["tqdm==4.70.0"])
        self.assertEqual(res["filesModified"], ["pyproject.toml", "uv.lock"])
        self.assertNotIn("error", res)

    def test_pip_install_failure_surfaces_error(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}):
            self.fail_on = "install"
            res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
