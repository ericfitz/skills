import contextlib
import io
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from bumplib.ecosystems import python as py

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"
UV = {"packageManager": "uv", "present": True, "projects": [{"dir": ".", "members": ["."]}]}
NESTED = "writing/skills/boring"
TWO = {
    "packageManager": "uv",
    "present": True,
    "projects": [{"dir": ".", "members": ["."]}, {"dir": NESTED, "members": [NESTED]}],
}


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
        with (
            mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None),
            mock.patch("bumplib.ecosystems.python.detect", return_value=UV),
        ):
            self.assertEqual(py.handle("audit", []), [])

    def test_audit_missing_binary_pip(self):
        """Regression test: audit verb should return [] when pip-audit binary is missing (pip manager)."""
        with (
            mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None),
            mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip"}),
        ):
            self.assertEqual(py.handle("audit", []), [])


class TestParseTreeOutdated(unittest.TestCase):
    """`uv tree --outdated --frozen --all-groups` text, recorded from this repo's two
    projects (root, and writing/skills/boring) on 2026-10-18; the synthetic file is
    hand-built for shapes the real trees do not currently contain."""

    def _recs(self, name, location="uv.lock"):
        return {r.name: r for r in py.parse_tree_outdated((FIX / f"uv_tree_outdated_{name}.txt").read_text(), location)}

    def test_depth_one_is_direct_deeper_is_transitive(self):
        recs = self._recs("boring")
        self.assertEqual((recs["spacy"].current, recs["spacy"].latest), ("3.8.14", "3.8.16"))
        self.assertEqual(recs["spacy"].kind, "direct")
        self.assertEqual(recs["lxml"].kind, "transitive")  # depth 2
        self.assertEqual(recs["markupsafe"].kind, "transitive")  # depth 3

    def test_project_itself_and_legend_are_not_records(self):
        recs = self._recs("boring")
        self.assertNotIn("boring-analyzer", recs)
        self.assertEqual(len(recs), 26)
        for r in recs.values():
            self.assertEqual((r.location, r.ecosystem, r.wanted), ("uv.lock", "python", r.latest))

    def test_only_latest_annotated_lines_make_records(self):
        """pytest/ruff carry `(group: dev)` but no `(latest: ...)`: up to date."""
        recs = self._recs("root")
        self.assertNotIn("pytest", recs)
        self.assertNotIn("ruff", recs)
        self.assertEqual(len(recs), 19)

    def test_versions_differ_per_project(self):
        self.assertEqual(self._recs("root")["srsly"].current, "2.5.3")
        self.assertEqual(self._recs("boring")["typing-extensions"].current, "4.15.0")
        self.assertNotIn("typing-extensions", self._recs("root"))

    def test_nested_location_is_passed_through(self):
        recs = self._recs("boring", f"{NESTED}/uv.lock")
        self.assertEqual({r.location for r in recs.values()}, {f"{NESTED}/uv.lock"})

    def test_shallowest_appearance_wins_even_when_it_has_no_latest(self):
        """uv prints `(latest: ...)` on the first appearance only; `shared` first shows
        at depth 2 (annotated), then at depth 1 (not annotated): it is direct."""
        self.assertEqual(self._recs("synthetic")["shared"].kind, "direct")

    def test_combined_annotations(self):
        recs = self._recs("synthetic")
        self.assertEqual((recs["c"].latest, recs["c"].bump, recs["c"].kind), ("2.0.0", "major", "direct"))
        self.assertEqual((recs["d"].latest, recs["d"].bump), ("3.2.0", "minor"))
        self.assertEqual(recs["e"].kind, "transitive")

    def test_extras_suffix_is_stripped_and_repeats_are_ignored(self):
        recs = self._recs("synthetic")
        self.assertIn("httpx", recs)
        self.assertEqual(len(recs), 5)  # `a ... (*)` adds nothing

    def test_empty_and_garbage_output(self):
        self.assertEqual(py.parse_tree_outdated(""), [])
        self.assertEqual(py.parse_tree_outdated("error: no lockfile\n"), [])


class _Repo(unittest.TestCase):
    """A real temp directory as cwd, with the subprocess boundary faked."""

    manager = UV

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        old = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)
        self.calls = []
        self.responses = {}  # marker in argv -> (returncode, stdout)
        self.cwds = []
        self.enterContext(mock.patch("bumplib.ecosystems.python._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run_shell", side_effect=self._shell))
        self.enterContext(mock.patch("bumplib.ecosystems.python.shutil.which", return_value="/bin/uv"))
        self.enterContext(mock.patch("bumplib.ecosystems.python.detect", return_value=self.manager))

    def _record(self, args, env=None, cwd=None):
        args = list(args)
        self.calls.append(args)
        for marker, (rc, out) in self.responses.items():
            if marker in args:
                return mock.Mock(returncode=rc, stdout=out, stderr="boom" if rc else "")
        return mock.Mock(returncode=0, stdout="{}", stderr="")

    def _shell(self, cmd, cwd=None):
        self.calls.append(cmd)
        self.cwds.append(cwd)
        return mock.Mock(returncode=0, stdout="", stderr="")


class TestOutdatedFromLockfile(_Repo):
    """outdated reads each project's uv.lock through `uv tree`; no venv, no sync."""

    manager = TWO

    def setUp(self):
        super().setUp()
        self.responses["tree"] = (0, (FIX / "uv_tree_outdated_boring.txt").read_text())

    def test_one_frozen_tree_call_per_project(self):
        py.handle("outdated", [])
        trees = [c for c in self.calls if c[:2] == ["uv", "tree"]]
        self.assertEqual([t[t.index("--project") + 1] for t in trees], [".", NESTED])
        for t in trees:
            self.assertEqual(t[:5], ["uv", "tree", "--outdated", "--frozen", "--all-groups"])

    def test_never_syncs_or_lists_the_environment(self):
        """#28/#37: no venv is created, read or reconciled."""
        py.handle("outdated", [])
        self.assertFalse(any(c[:2] in (["uv", "sync"], ["uv", "pip"]) for c in self.calls))

    def test_locations_are_each_projects_lockfile(self):
        recs = py.handle("outdated", [])
        self.assertEqual({r.location for r in recs}, {"uv.lock", f"{NESTED}/uv.lock"})
        self.assertEqual(sum(r.location == f"{NESTED}/uv.lock" for r in recs), 26)

    def test_failed_tree_warns_and_only_drops_that_project(self):
        calls = iter([(1, ""), (0, (FIX / "uv_tree_outdated_boring.txt").read_text())])

        def record(args, env=None, cwd=None):
            rc, out = next(calls)
            return mock.Mock(returncode=rc, stdout=out, stderr="no lock")

        with (
            mock.patch("bumplib.ecosystems.python._run", side_effect=record),
            contextlib.redirect_stderr(io.StringIO()) as err,
        ):
            recs = py.handle("outdated", [])
        self.assertEqual({r.location for r in recs}, {f"{NESTED}/uv.lock"})
        self.assertIn("uv tree --outdated", err.getvalue())

    def test_pip_manager_path_unchanged(self):
        with mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}):
            py.handle("outdated", [])
        self.assertEqual(self.calls, [["pip", "list", "--outdated", "--format", "json"]])


class TestDetectProjects(unittest.TestCase):
    """detect lists one project per tracked uv.lock."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def _touch(self, *rels):
        for rel in rels:
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text("")

    def _detect(self, git_files):
        with (
            mock.patch("bumplib.ecosystems.python.shutil.which", return_value="/bin/uv"),
            mock.patch(
                "bumplib.ecosystems.python._run", return_value=mock.Mock(returncode=0, stdout=git_files, stderr="")
            ),
        ):
            return py.detect(self.root)

    def test_one_project_per_tracked_lockfile_root_first(self):
        self._touch("pyproject.toml", "uv.lock", f"{NESTED}/uv.lock")
        got = self._detect(f"{NESTED}/uv.lock\nuv.lock\n")
        self.assertEqual(got["projects"], [{"dir": ".", "members": ["."]}, {"dir": NESTED, "members": [NESTED]}])

    def test_untracked_or_deleted_lockfiles_are_not_projects(self):
        self._touch("pyproject.toml", "uv.lock")
        got = self._detect("uv.lock\ngone/uv.lock\nxuv.lock\n")  # gone/ absent, xuv.lock a name clash
        self.assertEqual(got["projects"], [{"dir": ".", "members": ["."]}])

    def test_git_unavailable_falls_back_to_root_lock(self):
        self._touch("pyproject.toml", "uv.lock", f"{NESTED}/uv.lock")
        with (
            mock.patch("bumplib.ecosystems.python.shutil.which", return_value="/bin/uv"),
            mock.patch("bumplib.ecosystems.python._run", side_effect=OSError("no git")),
        ):
            got = py.detect(self.root)
        self.assertEqual(got["projects"], [{"dir": ".", "members": ["."]}])

    def test_pyproject_without_lock_is_a_root_project(self):
        self._touch("pyproject.toml")
        self.assertEqual(self._detect("")["projects"], [{"dir": ".", "members": ["."]}])

    def test_pip_mode_has_the_root_project(self):
        self._touch("requirements.txt")
        with mock.patch("bumplib.ecosystems.python.shutil.which", return_value=None):
            got = py.detect(self.root)
        self.assertEqual((got["packageManager"], got["projects"]), ("pip", [{"dir": ".", "members": ["."]}]))


class TestApplyReportsOnlyRealChanges(_Repo):
    """#37: `uv lock --upgrade-package X` is a no-op when the lock already holds the
    target, yet apply echoed every spec back in `applied`. For uv the lockfile IS the
    evidence, so an empty git-verified `filesModified` means nothing was applied."""

    def test_uv_noop_apply_reports_nothing_applied(self):
        with mock.patch("bumplib.ecosystems.python.changed_files", return_value=[]):
            result = py.handle("apply", ["charset-normalizer==3.5.1"])
        self.assertEqual(result, {"applied": [], "filesModified": []})

    def test_uv_apply_with_lock_change_reports_specs(self):
        with mock.patch("bumplib.ecosystems.python.changed_files", return_value=["uv.lock"]):
            result = py.handle("apply", ["requests==2.32.4"])
        self.assertEqual(result, {"applied": ["requests==2.32.4"], "filesModified": ["uv.lock"]})

    def test_pip_apply_unchanged(self):
        """pip install never edits requirements.txt, so an empty filesModified carries
        no signal there; keep echoing the specs."""
        with (
            mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}),
            mock.patch("bumplib.ecosystems.python.changed_files", return_value=[]),
        ):
            result = py.handle("apply", ["requests==2.32.4"])
        self.assertEqual(result["applied"], ["requests==2.32.4"])


class TestApplyPerProject(_Repo):
    manager = TWO

    def test_default_project_is_the_root(self):
        with mock.patch("bumplib.ecosystems.python.changed_files", return_value=["uv.lock"]) as cf:
            py.handle("apply", ["requests==2.32.4"])
        self.assertEqual(self.calls[0], ["uv", "lock", "--project", ".", "--upgrade-package", "requests"])
        self.assertEqual(self.calls[1], ["uv", "sync", "--project", "."])
        self.assertEqual(cf.call_args.args[0], ["pyproject.toml", "uv.lock"])

    def test_nested_project_locks_there_and_reports_repo_relative_files(self):
        locked = [f"{NESTED}/uv.lock"]
        with mock.patch("bumplib.ecosystems.python.changed_files", return_value=locked) as cf:
            res = py.handle("apply", ["--project", NESTED, "spacy==3.8.16"])
        where = NESTED
        self.assertEqual(self.calls[0], ["uv", "lock", "--project", where, "--upgrade-package", "spacy"])
        self.assertEqual(self.calls[1], ["uv", "sync", "--project", where])
        self.assertEqual(cf.call_args.args[0], [f"{NESTED}/pyproject.toml", f"{NESTED}/uv.lock"])
        self.assertEqual(res, {"applied": ["spacy==3.8.16"], "filesModified": locked})

    def test_flag_may_follow_the_specs_and_is_not_passed_on_as_a_spec(self):
        with mock.patch("bumplib.ecosystems.python.changed_files", return_value=["x"]):
            res = py.handle("apply", ["spacy==3.8.16", "--project", f"{NESTED}/"])
        self.assertEqual(res["applied"], ["spacy==3.8.16"])
        self.assertIn(NESTED, self.calls[0])

    def test_unknown_project_is_rejected_before_anything_runs(self):
        for bad in ("elsewhere", "../x", "/etc", NESTED + "/sub"):
            with self.subTest(bad), self.assertRaises(ValueError):
                py.handle("apply", ["--project", bad, "x==1"])
        with self.assertRaises(ValueError):
            py.handle("validate", ["--project", "elsewhere"])
        self.assertEqual(self.calls, [])

    def test_malformed_project_flag_is_rejected(self):
        with self.assertRaises(ValueError):
            py.handle("apply", ["x==1", "--project"])
        with self.assertRaises(ValueError):
            py.handle("apply", ["--project", ".", "--project", NESTED])

    def test_pip_accepts_only_the_root(self):
        with (
            mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}),
            mock.patch("bumplib.ecosystems.python.changed_files", return_value=[]),
        ):
            self.assertEqual(py.handle("apply", ["--project", ".", "x==1"])["applied"], ["x==1"])
            with self.assertRaises(ValueError):
                py.handle("apply", ["--project", NESTED, "x==1"])


class TestValidateRunsWhatIsDeclared(_Repo):
    manager = TWO

    def _pyproject(self, rel, text):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)

    def test_declared_tools_run_in_the_projects_directory(self):
        self._pyproject(
            f"{NESTED}/pyproject.toml", "[project]\nname='b'\n[dependency-groups]\ndev=['pytest>=8','ruff']\n"
        )
        res = py.handle("validate", ["--project", NESTED])
        self.assertEqual((res["test"], res["lint"]), ("pass", "pass"))
        self.assertEqual(self.calls, ["uv run pytest", "uv run ruff check ."])
        self.assertEqual(self.cwds, [Path(NESTED)] * 2)

    def test_undeclared_pytest_is_skipped_not_failed(self):
        """boring declares ruff (a [tool.ruff] table) but no pytest."""
        self._pyproject(f"{NESTED}/pyproject.toml", "[project]\nname='b'\n[tool.ruff]\nline-length=99\n")
        res = py.handle("validate", ["--project", NESTED])
        self.assertEqual((res["test"], res["lint"]), ("skipped", "pass"))
        self.assertIn("no pytest declared", res["test_output"])
        self.assertIn(f"{NESTED}/pyproject.toml", res["test_output"])
        self.assertEqual(self.calls, ["uv run ruff check ."])

    def test_missing_pyproject_skips_everything(self):
        res = py.handle("validate", [])
        self.assertEqual((res["test"], res["lint"]), ("skipped", "skipped"))
        self.assertEqual(self.calls, [])

    def test_failure_is_still_fail(self):
        self._pyproject("pyproject.toml", "[tool.pytest.ini_options]\n[tool.ruff]\n")
        with mock.patch(
            "bumplib.ecosystems.python._run_shell", return_value=mock.Mock(returncode=1, stdout="x", stderr="")
        ):
            res = py.handle("validate", [])
        self.assertEqual((res["test"], res["lint"]), ("fail", "fail"))

    def test_pip_validate_keeps_running_both(self):
        with mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}):
            res = py.handle("validate", [])
        self.assertEqual((res["test"], res["lint"]), ("pass", "pass"))
        self.assertEqual(self.calls, ["pytest", "ruff check ."])


class TestDeclared(unittest.TestCase):
    def _declared(self, text, tool):
        with TemporaryDirectory() as td:
            p = Path(td) / "pyproject.toml"
            p.write_text(text)
            return py.declared(p, tool)

    def test_every_place_a_requirement_can_live(self):
        for text in (
            "[project]\ndependencies=['pytest>=8']\n",
            "[project.optional-dependencies]\ntest=['PyTest']\n",
            "[dependency-groups]\ndev=['pytest']\n",
            "[tool.uv]\ndev-dependencies=['pytest[x]>=8; python_version>\"3\"']\n",
            "[tool.pytest.ini_options]\naddopts='-q'\n",
        ):
            with self.subTest(text):
                self.assertTrue(self._declared(text, "pytest"))

    def test_lookalikes_and_absence(self):
        for text in (
            "[project]\ndependencies=['pytest-cov','mypytest']\n",
            "[dependency-groups]\ndev=[{include-group='lint'}]\n",
            "# pytest\n[project]\nname='pytest-fan'\n",
            "not toml [",
        ):
            with self.subTest(text):
                self.assertFalse(self._declared(text, "pytest"))
        self.assertFalse(py.declared(Path("/nonexistent/pyproject.toml"), "ruff"))

    def test_text_fallback_without_tomllib(self):
        with mock.patch("bumplib.ecosystems.python.tomllib", None):
            self.assertTrue(self._declared("[tool.ruff.lint]\nx=1\n", "ruff"))
            self.assertTrue(self._declared("[dependency-groups]\ndev=['pytest>=8']\n", "pytest"))
            self.assertFalse(self._declared("[project]\ndependencies=['pytest-cov']\n", "pytest"))


class TestAuditAgainstLockfile(_Repo):
    """audit must read the LOCKFILE, never the installed environment.

    pip-audit's environment mode asks pip to enumerate installed distributions. In a
    uv-created venv pip enumerates nothing -- measured here: 0 from `pip list` against 33
    dist-info directories on disk and 33 from importlib.metadata -- so pip-audit scanned
    an empty set and reported "No known vulnerabilities found". A security check that
    silently passes because it saw nothing is the failure mode worth engineering against.
    """

    def _export_call(self, n=0):
        return [c for c in self.calls if "export" in c][n]

    def _audit_call(self, n=0):
        return [c for c in self.calls if "pip-audit" in c][n]

    def test_exports_lockfile_to_pylock(self):
        py.handle("audit", [])
        exp = self._export_call()
        self.assertEqual(exp[:2], ["uv", "export"])
        self.assertIn("--frozen", exp)  # never re-resolve to audit
        self.assertEqual(exp[exp.index("--format") + 1], "pylock.toml")
        self.assertEqual(exp[exp.index("--project") + 1], ".")

    def test_export_includes_every_extra_and_group(self):
        """A package reached only through an optional extra (nltk via `boring`) is
        still in uv.lock and still ships to whoever installs the extra; the default
        export leaves it out, so its advisories were never seen."""
        py.handle("audit", [])
        exp = self._export_call()
        self.assertIn("--all-extras", exp)
        self.assertIn("--all-groups", exp)

    def test_lockfile_advisories_are_located_at_uv_lock(self):
        self.responses["pip-audit"] = (1, (FIX / "pip_audit.json").read_text())
        advs = py.handle("audit", [])
        self.assertTrue(advs)
        self.assertEqual({a.location for a in advs}, {"uv.lock"})

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
        written = Path(self._export_call()[self._export_call().index("-o") + 1])
        self.assertNotIn(str(self.root), str(written.resolve()))
        self.assertFalse((self.root / "pylock.toml").exists())

    def test_advisories_parsed_from_audit_output(self):
        self.responses["pip-audit"] = (1, (FIX / "pip_audit.json").read_text())
        advs = py.handle("audit", [])
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
        with mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}):
            py.handle("audit", [])
        self.assertEqual(self.calls, [["pip-audit", "--format", "json"]])


class TestAuditEveryProject(_Repo):
    manager = TWO

    def test_each_project_is_exported_and_located_at_its_own_lockfile(self):
        self.responses["pip-audit"] = (1, (FIX / "pip_audit.json").read_text())
        advs = py.handle("audit", [])
        exports = [c for c in self.calls if "export" in c]
        self.assertEqual([e[e.index("--project") + 1] for e in exports], [".", NESTED])
        per = len(advs) // 2
        self.assertTrue(per)
        self.assertEqual([a.location for a in advs], ["uv.lock"] * per + [f"{NESTED}/uv.lock"] * per)

    def test_one_projects_failed_export_does_not_hide_the_other(self):
        results = iter([(2, ""), (0, ""), (1, (FIX / "pip_audit.json").read_text())])

        def record(args, env=None, cwd=None):
            rc, out = next(results)
            return mock.Mock(returncode=rc, stdout=out, stderr="")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record):
            advs = py.handle("audit", [])
        self.assertTrue(advs)
        self.assertEqual({a.location for a in advs}, {f"{NESTED}/uv.lock"})


class TestApplyReportsFailure(_Repo):
    """apply must surface a failed package-manager command, never report success (#32)."""

    def setUp(self):
        super().setUp()
        self.enterContext(
            mock.patch("bumplib.ecosystems.python.changed_files", side_effect=lambda cands, cwd=None: list(cands))
        )

    def test_uv_lock_failure_surfaces_error(self):
        self.responses["lock"] = (1, "")
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("error", res)
        self.assertFalse(any("sync" in c for c in self.calls))  # stops at first failure

    def test_uv_sync_failure_surfaces_error(self):
        self.responses["sync"] = (1, "")
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)

    def test_success_reports_git_verified_files(self):
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], ["tqdm==4.70.0"])
        self.assertEqual(res["filesModified"], ["pyproject.toml", "uv.lock"])
        self.assertNotIn("error", res)

    def test_pip_install_failure_surfaces_error(self):
        with mock.patch("bumplib.ecosystems.python.detect", return_value={"packageManager": "pip", "present": True}):
            self.responses["install"] = (1, "")
            res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)


if __name__ == "__main__":
    unittest.main()
