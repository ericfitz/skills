# tests/test_logseq_page_mutate.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import page as pg  # noqa: E402


class TestMakeAppend(unittest.TestCase):
    def test_make_block_single_line(self):
        b = pg.make_block("TODO buy milk")
        self.assertEqual(b.lines, ["- TODO buy milk"])

    def test_make_block_multiline(self):
        b = pg.make_block("meeting notes\nwith [[Alice]]")
        self.assertEqual(b.lines, ["- meeting notes", "  with [[Alice]]"])

    def test_append_block_preserves_existing(self):
        text = "- a\n\t- a1\n"
        p = pg.parse(text)
        pg.append_block(p, "new one")
        self.assertEqual(pg.write(p), text + "- new one\n")


class TestNaming(unittest.TestCase):
    def test_journal_filename(self):
        self.assertEqual(pg.journal_filename("2026-07-17"), "2026_07_17.md")

    def test_page_filename_roundtrip(self):
        self.assertEqual(pg.page_filename("project/roadmap"),
                         "project%2Froadmap.md")
        self.assertEqual(pg.filename_to_page_name("project%2Froadmap"),
                         "project/roadmap")
        self.assertEqual(pg.page_filename("Plain Name"), "Plain Name.md")


class TestAppendToFile(unittest.TestCase):
    def test_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "j.md"
            f.write_text("- existing\n")
            pg.append_to_file(f, "added")
            self.assertEqual(f.read_text(), "- existing\n- added\n")

    def test_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "new.md"
            pg.append_to_file(f, "first")
            self.assertEqual(f.read_text(), "- first\n")

    def test_never_writes_unparseable(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bad.md"
            bad = "- a\n\t\t\t- too deep\n"
            f.write_text(bad)
            with self.assertRaises(pg.PageParseError):
                pg.append_to_file(f, "x")
            self.assertEqual(f.read_text(), bad)  # untouched

    def test_appends_without_final_newline(self):
        # File has no trailing newline; append must still produce a valid
        # outline and preserve the file's final_newline=False state.
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "j.md"
            f.write_text("- a")
            pg.append_to_file(f, "b")
            self.assertEqual(f.read_text(), "- a\n- b")


if __name__ == "__main__":
    unittest.main()
