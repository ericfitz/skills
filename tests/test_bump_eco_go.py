import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from bumplib.ecosystems import go

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


class TestGoOutdated(unittest.TestCase):
    def test_parses_bracketed_updates_only(self):
        recs = go.parse_outdated((FIX / "go_list.txt").read_text())
        names = {r.name: r for r in recs}
        self.assertIn("github.com/gin-gonic/gin", names)
        self.assertEqual(names["github.com/gin-gonic/gin"].current, "v1.10.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].latest, "v1.11.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].bump, "minor")
        # up-to-date line must be excluded
        self.assertNotIn("golang.org/x/sys", names)

    def test_replace_and_pinned(self):
        gomod = (
            "module x\nrequire (\n\tgithub.com/foo/bar v1.2.3 // pinned: compat\n)\n"
            "replace github.com/foo/bar => ./local\n"
        )
        self.assertIn("github.com/foo/bar", go.replace_targets(gomod))
        self.assertIn("github.com/foo/bar", go.pinned_names(gomod))

    def test_replace_targets_block_form_two_entries(self):
        gomod = (
            "module x\n"
            "replace (\n"
            "\tgithub.com/foo/bar => ./local\n"
            "\tgithub.com/baz/qux v1.0.0 => github.com/baz/qux v1.0.1\n"
            ")\n"
        )
        targets = go.replace_targets(gomod)
        self.assertEqual({"github.com/foo/bar", "github.com/baz/qux"}, targets)
        self.assertNotIn("(", targets)

    def test_replace_targets_single_line(self):
        gomod = "module x\nreplace github.com/foo/bar => ./local\n"
        targets = go.replace_targets(gomod)
        self.assertEqual({"github.com/foo/bar"}, targets)
        self.assertNotIn("(", targets)

    def test_pinned_names_single_line_require(self):
        gomod = "module x\nrequire github.com/foo/bar v1.2.3 // pinned: compat\n"
        names = go.pinned_names(gomod)
        self.assertIn("github.com/foo/bar", names)
        self.assertNotIn("require", names)

    def test_pinned_names_block_form_require(self):
        gomod = "module x\nrequire (\n\tgithub.com/foo/bar v1.2.3 // pinned: compat\n\tgithub.com/other/pkg v2.0.0\n)\n"
        names = go.pinned_names(gomod)
        self.assertIn("github.com/foo/bar", names)
        self.assertNotIn("github.com/other/pkg", names)
        self.assertNotIn("require", names)

    def test_required_filters_graph_only_modules_and_labels_kind(self):
        gomod = (
            "module x\nrequire github.com/gin-gonic/gin v1.10.0\nrequire (\n\tgolang.org/x/sys v0.21.0 // indirect\n)\n"
        )
        required = go.required_modules(gomod)
        self.assertEqual({"github.com/gin-gonic/gin": "direct", "golang.org/x/sys": "indirect"}, required)
        text = (
            "github.com/gin-gonic/gin v1.10.0 [v1.11.0]\n"
            "golang.org/x/sys v0.21.0 [v0.22.0]\n"
            "github.com/graph/only v1.0.0 [v1.1.0]\n"
        )
        recs = {r.name: r for r in go.parse_outdated(text, required)}
        self.assertEqual({"github.com/gin-gonic/gin", "golang.org/x/sys"}, set(recs))
        self.assertEqual(recs["github.com/gin-gonic/gin"].kind, "direct")
        self.assertEqual(recs["golang.org/x/sys"].kind, "indirect")

    def test_workspace_gomods_reads_go_work_use_dirs(self):
        with TemporaryDirectory() as d:
            root = Path(d)
            (root / "go.mod").write_text("module x\n")
            (root / "svc").mkdir()
            (root / "svc" / "go.mod").write_text("module svc\n")
            (root / "go.work").write_text("go 1.22\nuse (\n\t.\n\t./svc\n\t./missing\n)\n")
            mods = go._workspace_gomods(root)
            self.assertEqual([root / "go.mod", root / "go.mod", root / "svc" / "go.mod"], mods)


class TestGoParseVuln(unittest.TestCase):
    def test_parse_vuln(self):
        text = (FIX / "govulncheck.json").read_text()
        advs = go.parse_vuln(text)
        self.assertEqual(len(advs), 1)
        self.assertEqual(advs[0].ids, ["GO-2024-1234"])
        self.assertEqual(advs[0].package, "github.com/foo/bar")

    def test_audit_returns_empty_when_govulncheck_missing(self):
        with mock.patch.object(go.shutil, "which", return_value=None):
            self.assertEqual(go.handle("audit", []), [])


class TestApplyReportsFailure(unittest.TestCase):
    """apply must surface a failed go command, never report success (#32)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "go.mod").write_text("module x\n")
        self.calls = []
        self.fail_on = None
        self.enterContext(mock.patch("bumplib.ecosystems.go.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.go._run", side_effect=self._record))
        self.enterContext(
            mock.patch("bumplib.ecosystems.go.changed_files", side_effect=lambda cands, cwd=None: list(cands))
        )

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return mock.Mock(returncode=1, stdout="", stderr="invalid version: unknown revision")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_go_get_failure_surfaces_error(self):
        self.fail_on = "get"
        res = go.handle("apply", ["github.com/foo/bar@v9.9.9"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("unknown revision", res["error"])
        self.assertFalse(any("tidy" in c for c in self.calls))

    def test_go_mod_tidy_failure_surfaces_error(self):
        self.fail_on = "tidy"
        res = go.handle("apply", ["github.com/foo/bar@v1.2.3"])
        self.assertIn("error", res)
        self.assertEqual(res["applied"], [])

    def test_success_reports_git_verified_files(self):
        res = go.handle("apply", ["github.com/foo/bar@v1.2.3"])
        self.assertEqual(res["applied"], ["github.com/foo/bar@v1.2.3"])
        self.assertEqual(res["filesModified"], ["go.mod", "go.sum"])
        self.assertNotIn("error", res)


class _InTempDir(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        old = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, old)

    def _write(self, rel, text=""):
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.root / rel).write_text(text)


class TestGoProjects(_InTempDir):
    def test_detect_reports_one_root_project(self):
        self._write("go.mod", "module x\n")
        self.assertEqual(go.handle("detect", [])["projects"], [{"dir": ".", "members": ["."]}])

    def test_workspace_use_dirs_are_members(self):
        self._write("go.mod", "module x\n")
        self._write("go.work", "go 1.22\nuse (\n\t./svc\n\t./lib/util\n)\n")
        self._write("svc/go.mod", "module y\n")
        self._write("lib/util/go.mod", "module z\n")
        self.assertEqual(go.handle("detect", [])["projects"], [{"dir": ".", "members": [".", "svc", "lib/util"]}])

    def test_absent_go_has_no_projects(self):
        self.assertNotIn("projects", go.handle("detect", []))

    def test_other_projects_are_rejected_before_anything_runs(self):
        self._write("go.mod", "module x\n")
        with mock.patch("bumplib.ecosystems.go._run") as run, mock.patch("bumplib.ecosystems.go._run_shell") as shell:
            for verb in ("apply", "validate"):
                for bad in ("svc", "..", "/tmp"):
                    with self.subTest(verb=verb, bad=bad), self.assertRaises(ValueError):
                        go.handle(verb, ["--project", bad, "github.com/foo/bar@v1.2.3"])
            run.assert_not_called()
            shell.assert_not_called()

    def test_project_dot_is_accepted_and_is_not_a_spec(self):
        self._write("go.mod", "module x\n")
        with (
            mock.patch("bumplib.ecosystems.go._run", return_value=mock.Mock(returncode=0, stdout="", stderr="")) as run,
            mock.patch("bumplib.ecosystems.go.changed_files", return_value=["go.mod"]),
        ):
            res = go.handle("apply", ["github.com/foo/bar@v1.2.3", "--project", "."])
        self.assertEqual(res["applied"], ["github.com/foo/bar@v1.2.3"])
        self.assertEqual(run.call_args_list[0].args[0], ["go", "get", "github.com/foo/bar@v1.2.3"])


if __name__ == "__main__":
    unittest.main()


class TestGoRenames(unittest.TestCase):
    def test_parse_list_stream_maps_specs_to_gomod_and_drops_errors(self):
        got = go.parse_list_stream((FIX / "go_list_json_stream.txt").read_text())
        self.assertEqual(set(got), {"github.com/google/cel-go@v0.32.0", "github.com/ThalesGroup/crypto11@v1.6.8"})
        self.assertTrue(got["github.com/google/cel-go@v0.32.0"].endswith("v0.32.0.mod"))

    def test_parse_list_stream_tolerates_garbage(self):
        self.assertEqual(go.parse_list_stream(""), {})
        self.assertEqual(go.parse_list_stream("not json"), {})

    def test_module_line(self):
        self.assertEqual(go.module_line((FIX / "go_mod_renamed.mod").read_text()), "cel.dev/cel-go")
        self.assertEqual(go.module_line('// c\nmodule "a/b" // x\n'), "a/b")
        self.assertEqual(go.module_line("go 1.20\n"), "")

    def test_last_version_with_path(self):
        declared = {"v0.30.0": "a/b", "v0.31.0": "a/b", "v0.32.0": "c/d", "v0.31.1-rc1": "a/b"}
        cands = list(declared)
        self.assertEqual(go.last_version_with_path("v0.29.0", "v0.32.0", cands, declared, "a/b"), "v0.31.0")
        self.assertEqual(go.last_version_with_path("v0.31.0", "v0.32.0", cands, declared, "a/b"), "")

    def _rec(self, name, cur, lat):
        return go.parse_outdated(f"{name} {cur} [{lat}]\n")[0]

    def _stub(self, declared_by_spec, versions):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)

        def run(args):
            if "-versions" in args:
                return mock.Mock(returncode=0, stdout=f"{args[-1]} {' '.join(versions)}\n", stderr="")
            out = []
            for spec in args[args.index("-json=Path,Version,GoMod,Error") + 1 :]:
                if spec in declared_by_spec:
                    f = Path(tmp.name) / (spec.replace("/", "_") + ".mod")
                    f.write_text(f"module {declared_by_spec[spec]}\n")
                    path, ver = spec.split("@")
                    out.append(json.dumps({"Path": path, "Version": ver, "GoMod": str(f)}))
            return mock.Mock(returncode=0, stdout="\n".join(out), stderr="")

        return mock.patch("bumplib.ecosystems.go._run", side_effect=run)

    def test_rename_sets_meta_with_last_version_under_old_path(self):
        rec = self._rec("github.com/google/cel-go", "v0.29.2", "v0.32.0")
        declared = {
            "github.com/google/cel-go@v0.32.0": "cel.dev/cel-go",
            "github.com/google/cel-go@v0.30.0": "github.com/google/cel-go",
            "github.com/google/cel-go@v0.31.0": "github.com/google/cel-go",
        }
        with self._stub(declared, ["v0.29.2", "v0.30.0", "v0.31.0", "v0.32.0"]):
            go.detect_renames([rec])
        self.assertEqual(rec.meta, {"renamedTo": "cel.dev/cel-go", "lastVersionWithPath": "v0.31.0"})

    def test_rename_with_no_version_under_old_path(self):
        rec = self._rec("github.com/google/cel-go", "v0.31.0", "v0.32.0")
        with self._stub({"github.com/google/cel-go@v0.32.0": "cel.dev/cel-go"}, ["v0.31.0", "v0.32.0"]):
            go.detect_renames([rec])
        self.assertEqual(rec.meta["lastVersionWithPath"], "")

    def test_same_path_and_lookup_failure_leave_record_unchanged(self):
        same = self._rec("a/b", "v1.0.0", "v1.1.0")
        unknown = self._rec("c/d", "v1.0.0", "v1.1.0")
        with self._stub({"a/b@v1.1.0": "a/b"}, []):
            go.detect_renames([same, unknown])
        self.assertEqual(same.meta, {})
        self.assertEqual(unknown.meta, {})

    def test_go_list_failure_and_up_to_date_records_are_not_marked(self):
        rec = self._rec("a/b", "v1.0.0", "v1.1.0")
        done = self._rec("c/d", "v1.0.0", "v1.0.0")
        with mock.patch(
            "bumplib.ecosystems.go._run", return_value=mock.Mock(returncode=1, stdout="", stderr="boom")
        ) as run:
            go.detect_renames([rec, done])
        self.assertEqual(rec.meta, {})
        self.assertNotIn("c/d@v1.0.0", " ".join(run.call_args.args[0]))

    def test_parse_renamed_from_issue_error(self):
        text = (FIX / "go_get_renamed_error.txt").read_text()
        self.assertEqual(
            go.parse_renamed(text),
            [{"required": "github.com/ThalesGroup/crypto11", "declared": "github.com/eclipse-keypont/crypto11"}],
        )
        self.assertEqual(go.parse_renamed("unknown revision"), [])

    def test_apply_error_carries_renamed(self):
        text = (FIX / "go_get_renamed_error.txt").read_text()
        with (
            mock.patch("bumplib.ecosystems.go._run", return_value=mock.Mock(returncode=1, stdout="", stderr=text)),
        ):
            res = go.handle("apply", ["github.com/ThalesGroup/crypto11@v1.6.8"])
        self.assertEqual(res["renamed"][0]["declared"], "github.com/eclipse-keypont/crypto11")
        self.assertEqual(res["applied"], [])
