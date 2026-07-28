# tests/test_logseq_cli.py
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "logseq_cli", ROOT / "logseq" / "scripts" / "logseq-cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


def setup_env(td: str):
    root = Path(td)
    g = root / "graph"
    for d in ("pages", "journals", "logseq"):
        (g / d).mkdir(parents=True)
    (g / "pages" / "Foo.md").write_text("- see [[Bar]]\n")
    (g / "pages" / "Bar.md").write_text("- hi\n")
    cfgp = root / "config.json"
    cfgp.write_text(json.dumps({
        "graphs": {"main": {"path": str(g)}},
        "default_graph": "main",
        "api": {"url": "http://127.0.0.1:1", "token_env": "NO_SUCH_TOKEN"},
    }))
    return g, cfgp


class TestCli(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.g, self.cfgp = setup_env(self.td.name)
        # no token in env -> every API attempt raises ApiUnavailable
        patcher = mock.patch.dict("os.environ", {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.td.cleanup)

    def _run(self, *args):
        return run([*args, "--config", str(self.cfgp)])

    def test_resolve(self):
        code, out = self._run("resolve")
        self.assertEqual(code, 0)
        self.assertEqual(out["name"], "main")
        self.assertEqual(out["path"], str(self.g))
        self.assertFalse(out["api_up"])

    def test_append_journal_files_fallback(self):
        code, out = self._run("append", "--journal", "--text", "note",
                              "--date", "2026-07-17")
        self.assertEqual(code, 0)
        self.assertEqual(out["via"], "files")
        f = self.g / "journals" / "2026_07_17.md"
        self.assertEqual(f.read_text(), "- note\n")

    def test_append_journal_invalid_date_is_json_error_and_no_escape(self):
        code, out = self._run("append", "--journal", "--text", "note",
                              "--date", "../../x")
        self.assertEqual(code, 1)
        self.assertIn("error", out)
        escaped = Path(self.td.name) / "x.md"
        self.assertFalse(escaped.exists())

    def test_lint_and_scan(self):
        code, out = self._run("lint", "--types", "orphan")
        self.assertEqual(code, 0)
        self.assertTrue(all(f["type"] == "orphan" for f in out["findings"]))
        code, out = self._run("scan")
        self.assertIn("foo", out["pages"])
        self.assertEqual(out["pages"]["foo"]["links"], ["Bar"])

    def test_rename_refs_dry_then_apply(self):
        code, out = self._run("rename-refs", "--old", "Bar", "--new", "Baz",
                              "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(out["dry_run"])
        self.assertEqual((self.g / "pages" / "Foo.md").read_text(),
                         "- see [[Bar]]\n")
        code, out = self._run("rename-refs", "--old", "Bar", "--new", "Baz")
        self.assertEqual(code, 0)
        self.assertEqual((self.g / "pages" / "Foo.md").read_text(),
                         "- see [[Baz]]\n")

    def test_error_is_json_exit_1(self):
        code, out = self._run("merge", "--source", "Nope", "--target", "Bar",
                              "--content-file", "/dev/null")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "unknown page: Nope")

    def test_convert_plan_and_import(self):
        vault = Path(self.td.name) / "vault"
        vault.mkdir()
        (vault / "Note.md").write_text("Hello\n")
        code, out = self._run("convert-plan", "--vault", str(vault))
        self.assertEqual(code, 0)
        self.assertEqual(out["plans"][0]["status"], "new")
        code, out = self._run("convert-import", "--vault", str(vault))
        self.assertEqual(code, 0)
        target = self.g / "pages" / "Note.md"
        self.assertIn("- Hello", target.read_text())
        code, out = self._run("convert-import", "--vault", str(vault))
        self.assertEqual(out["skipped"]["unchanged"], 1)

    def test_convert_plan_scope_outside_vault_is_json_error(self):
        vault = Path(self.td.name) / "vault2"
        vault.mkdir()
        (vault / "Note.md").write_text("Hello\n")
        outside = Path(self.td.name) / "outside"
        outside.mkdir()
        (outside / "Stray.md").write_text("Stray\n")
        code, out = self._run("convert-plan", "--vault", str(vault),
                              "--scope", str(outside))
        self.assertEqual(code, 1)
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
