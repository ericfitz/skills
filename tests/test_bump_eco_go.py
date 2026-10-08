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
        gomod = ("module x\nrequire (\n\tgithub.com/foo/bar v1.2.3 // pinned: compat\n)\n"
                 "replace github.com/foo/bar => ./local\n")
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
        gomod = (
            "module x\n"
            "require (\n"
            "\tgithub.com/foo/bar v1.2.3 // pinned: compat\n"
            "\tgithub.com/other/pkg v2.0.0\n"
            ")\n"
        )
        names = go.pinned_names(gomod)
        self.assertIn("github.com/foo/bar", names)
        self.assertNotIn("github.com/other/pkg", names)
        self.assertNotIn("require", names)


    def test_required_filters_graph_only_modules_and_labels_kind(self):
        gomod = (
            "module x\n"
            "require github.com/gin-gonic/gin v1.10.0\n"
            "require (\n"
            "\tgolang.org/x/sys v0.21.0 // indirect\n"
            ")\n"
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
        self.enterContext(mock.patch("bumplib.ecosystems.go.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))

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


if __name__ == "__main__":
    unittest.main()
