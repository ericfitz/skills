# tests/test_logseq_page.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import page as pg  # noqa: E402

SIMPLE = "- alpha\n- beta\n"

NESTED_TABS = "- a\n\t- a1\n\t\t- a1x\n- b\n"

NESTED_SPACES = "- a\n  - a1\n    - a1x\n- b\n"

PROPS = (
    "title:: My Page\n"
    "tags:: project, active\n"
    "\n"
    "- first block\n"
    "  id:: 6650some-uuid\n"
    "- TODO call [[Alice]]\n"
)

OPAQUE = (
    "- notes\n"
    "\t- ```python\n"
    "\t  x = 1\n"
    "\t  ```\n"
    "\t- {{query (todo TODO)}}\n"
    "- DONE ship it\n"
    "  :LOGBOOK:\n"
    "  CLOCK: [2026-07-16 Thu 09:00]\n"
    "  :END:\n"
)

NO_FINAL_NEWLINE = "- a"

NESTED_NO_FINAL_NEWLINE = "- a\n\t- a1\n\t\t- a1x\n- b"


class TestRoundTrip(unittest.TestCase):
    def test_round_trips(self):
        for text in (SIMPLE, NESTED_TABS, NESTED_SPACES, PROPS, OPAQUE, "",
                     NO_FINAL_NEWLINE, NESTED_NO_FINAL_NEWLINE):
            self.assertEqual(pg.write(pg.parse(text)), text)

    def test_no_final_newline_single_block(self):
        self.assertEqual(pg.write(pg.parse("- a")), "- a")

    def test_no_final_newline_nested(self):
        pg_text = NESTED_NO_FINAL_NEWLINE
        p = pg.parse(pg_text)
        self.assertFalse(p.final_newline)
        self.assertEqual(pg.write(p), pg_text)


class TestStructure(unittest.TestCase):
    def test_simple_two_blocks(self):
        p = pg.parse(SIMPLE)
        self.assertEqual([b.content for b in p.blocks], ["alpha", "beta"])
        self.assertEqual(p.pre_lines, [])

    def test_nesting_tabs(self):
        p = pg.parse(NESTED_TABS)
        self.assertEqual(p.indent_unit, "\t")
        a = p.blocks[0]
        self.assertEqual(a.content, "a")
        self.assertEqual(a.children[0].content, "a1")
        self.assertEqual(a.children[0].children[0].content, "a1x")
        self.assertEqual(p.blocks[1].content, "b")

    def test_nesting_spaces(self):
        p = pg.parse(NESTED_SPACES)
        self.assertEqual(p.indent_unit, "  ")
        self.assertEqual(p.blocks[0].children[0].children[0].content, "a1x")

    def test_continuation_lines_stay_with_block(self):
        p = pg.parse(OPAQUE)
        code = p.blocks[0].children[0]
        self.assertEqual(code.lines[0], "- ```python")
        self.assertEqual(len(code.lines), 3)
        done = p.blocks[1]
        self.assertEqual(done.content, "DONE ship it")
        self.assertEqual(len(done.lines), 4)  # bullet + 3 logbook lines

    def test_page_properties(self):
        p = pg.parse(PROPS)
        self.assertEqual(pg.page_properties(p),
                         {"title": "My Page", "tags": "project, active"})
        first = p.blocks[0]
        self.assertEqual(pg.block_properties(first), {"id": "6650some-uuid"})

    def test_first_bullet_props_page(self):
        text = "- title:: Alt Style\n  alias:: other\n- body\n"
        p = pg.parse(text)
        self.assertEqual(pg.page_properties(p),
                         {"title": "Alt Style", "alias": "other"})

    def test_bad_indent_raises(self):
        with self.assertRaises(pg.PageParseError):
            pg.parse("- a\n\t\t\t- too deep\n")
        with self.assertRaises(pg.PageParseError):
            pg.parse("- a\n   - ragged (3 spaces vs 2-space unit)\n  - ok\n")


if __name__ == "__main__":
    unittest.main()
