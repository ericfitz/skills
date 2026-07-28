# tests/test_logseq_refactor.py
import tempfile
import unittest
from pathlib import Path

from logseqlib import refactor, scan


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

    def test_skips_unreadable_file_without_raising(self):
        with tempfile.TemporaryDirectory() as td:
            g = build_graph(td)
            (g / "pages" / "Bad.md").write_bytes(b"\xff\xfe- foo\n")
            index = scan.scan_graph(g)
            changes = refactor.rename_refs(index, "foo", "Food Court")
            by_rel = {str(c.path.relative_to(g)): c.new_content
                      for c in changes}
            self.assertNotIn("pages/Bad.md", by_rel)
            self.assertIn("pages/Bar.md", by_rel)  # good files still processed


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

    def test_unknown_source_raises_with_message(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            with self.assertRaises(KeyError) as ctx:
                refactor.merge_pages(index, "Nope", "Bar", "- x\n")
            self.assertIn("unknown page", str(ctx.exception))

    def test_unknown_target_raises_with_message(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            with self.assertRaises(KeyError) as ctx:
                refactor.merge_pages(index, "Foo", "Nope", "- x\n")
            self.assertIn("unknown page", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
