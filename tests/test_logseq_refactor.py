# tests/test_logseq_refactor.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import refactor, scan  # noqa: E402


def build_graph(td: str) -> Path:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    (g / "logseq").mkdir()
    (g / "pages" / "Foo.md").write_text("- the foo page\n")
    (g / "pages" / "Bar.md").write_text(
        "- see [[foo]] and [[Foo]] but not [[foo-timer]]\n- tag #foo here\n")
    (g / "pages" / "Baz.md").write_text("- links [[Bar]]\n")
    return g


class TestRenameRefs(unittest.TestCase):
    def test_case_insensitive_whole_target_only(self):
        with tempfile.TemporaryDirectory() as td:
            g = build_graph(td)
            index = scan.scan_graph(g)
            changes = refactor.rename_refs(index, "foo", "Food Court")
            by_rel = {str(c.path.relative_to(g)): c.new_content
                      for c in changes}
            self.assertEqual(
                by_rel["pages/Bar.md"],
                "- see [[Food Court]] and [[Food Court]] but not "
                "[[foo-timer]]\n- tag #Food Court here\n")
            self.assertNotIn("pages/Baz.md", by_rel)  # untouched pages omitted

    def test_no_matches_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            self.assertEqual(refactor.rename_refs(index, "nothere", "x"), [])


class TestMergePages(unittest.TestCase):
    def test_merge_deletes_source_rewrites_refs(self):
        with tempfile.TemporaryDirectory() as td:
            g = build_graph(td)
            index = scan.scan_graph(g)
            merged = "- combined\n- from [[foo]]\n"
            changes = refactor.merge_pages(index, "Foo", "Bar", merged)
            by_rel = {str(c.path.relative_to(g)): c.new_content
                      for c in changes}
            self.assertIsNone(by_rel["pages/Foo.md"])  # delete
            self.assertEqual(by_rel["pages/Bar.md"],
                             "- combined\n- from [[Bar]]\n")

    def test_unknown_page_raises(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            with self.assertRaises(KeyError):
                refactor.merge_pages(index, "Nope", "Bar", "- x\n")


if __name__ == "__main__":
    unittest.main()
