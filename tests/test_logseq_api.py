# tests/test_logseq_api.py
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from logseqlib import api
from logseqlib import config as cfg


def resolved(graph: Path) -> cfg.Resolved:
    return cfg.Resolved(name="t", path=graph, source="config",
                        api_url="http://127.0.0.1:12315", api_token="tok",
                        obsidian_vault=None)


def make_graph(td: str) -> Path:
    g = Path(td)
    (g / "journals").mkdir()
    (g / "pages").mkdir()
    (g / "logseq").mkdir()
    return g


class TestApiPath(unittest.TestCase):
    def test_append_to_page_via_api(self):
        calls = []

        def fake_post(url, token, method, args, timeout=3.0):
            calls.append((method, args))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td, mock.patch.object(api, "_post", fake_post):
            out = api.append_to_page(resolved(make_graph(td)), "Inbox", "hi")
        self.assertEqual(out["via"], "api")
        self.assertIn(("logseq.Editor.appendBlockInPage", ["Inbox", "hi"]),
                      calls)

    def test_append_to_journal_via_api_uses_query(self):
        def fake_post(url, token, method, args, timeout=3.0):
            if method == "logseq.DB.datascriptQuery":
                self.assertIn("20260717", args[0])
                return [[{"block/name": "jul 17th, 2026"}]]
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td, mock.patch.object(api, "_post", fake_post):
            out = api.append_to_journal(resolved(make_graph(td)), "note",
                                        "2026-07-17")
        self.assertEqual(out["via"], "api")
        self.assertEqual(out["target"], "jul 17th, 2026")


class TestFileFallback(unittest.TestCase):
    def _down(self, *a, **kw):
        raise api.ApiUnavailable("down")

    def test_journal_falls_back_to_file(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            with mock.patch.object(api, "_post", self._down):
                out = api.append_to_journal(resolved(g), "note", "2026-07-17")
            self.assertEqual(out["via"], "files")
            f = g / "journals" / "2026_07_17.md"
            self.assertEqual(f.read_text(), "- note\n")

    def test_page_falls_back_and_appends(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            (g / "pages" / "Inbox.md").write_text("- old\n")
            with mock.patch.object(api, "_post", self._down):
                out = api.append_to_page(resolved(g), "Inbox", "new")
            self.assertEqual(out["via"], "files")
            self.assertEqual((g / "pages" / "Inbox.md").read_text(),
                             "- old\n- new\n")

    def test_probe_false_when_down(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.object(api, "_post", self._down):
            self.assertFalse(api.probe(resolved(make_graph(td))))


class TestCreatePage(unittest.TestCase):
    def test_creates_file_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            out = api.create_page(resolved(g), "proj/plan", "- start\n")
            self.assertEqual(out["via"], "files")
            f = g / "pages" / "proj%2Fplan.md"
            self.assertEqual(f.read_text(), "- start\n")
            with self.assertRaises(FileExistsError):
                api.create_page(resolved(g), "proj/plan", "- again\n")


if __name__ == "__main__":
    unittest.main()
