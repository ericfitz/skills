# tests/test_logseq_convert.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import convert as cv  # noqa: E402


class TestFrontmatter(unittest.TestCase):
    def test_simple_and_inline_list(self):
        r = cv.convert_note("---\ntitle: My Note\ntags: [a, b]\n---\nBody.\n",
                            "My Note")
        self.assertEqual(r.content,
                         "title:: My Note\ntags:: a, b\n\n- Body.\n")
        self.assertEqual(r.warnings, [])

    def test_nested_value_warns_and_drops(self):
        r = cv.convert_note("---\nmeta:\n  deep: 1\n---\nBody.\n", "t")
        self.assertTrue(any("meta" in w for w in r.warnings))
        self.assertNotIn("meta", r.content)


class TestBody(unittest.TestCase):
    def test_paragraphs_and_headings(self):
        r = cv.convert_note("# Head\n\nPara one\nstill one\n\nPara two\n", "t")
        self.assertEqual(r.content,
                         "- # Head\n- Para one\n  still one\n- Para two\n")

    def test_lists_keep_nesting(self):
        r = cv.convert_note("- a\n  - a1\n- b\n", "t")
        self.assertEqual(r.content, "- a\n  - a1\n- b\n")

    def test_numbered_list_flattens_with_warning(self):
        r = cv.convert_note("1. one\n2. two\n", "t")
        self.assertEqual(r.content, "- one\n- two\n")
        self.assertTrue(any("numbered" in w for w in r.warnings))

    def test_code_fence_single_block(self):
        r = cv.convert_note("```python\nx = 1\n```\n", "t")
        self.assertEqual(r.content, "- ```python\n  x = 1\n  ```\n")

    def test_callout_known_type(self):
        r = cv.convert_note("> [!note] Heads up\n> body line\n", "t")
        self.assertEqual(r.content,
                         "- #+BEGIN_NOTE\n  Heads up\n  body line\n"
                         "  #+END_NOTE\n")

    def test_callout_unknown_type_warns(self):
        r = cv.convert_note("> [!zany] eh\n", "t")
        self.assertTrue(any("zany" in w for w in r.warnings))
        self.assertIn("- > [!zany] eh", r.content)

    def test_plain_blockquote(self):
        r = cv.convert_note("> quoted\n> more\n", "t")
        self.assertEqual(r.content, "- > quoted\n  > more\n")


class TestEmbedsAssets(unittest.TestCase):
    def test_note_embed(self):
        r = cv.convert_note("![[Other Note]]\n", "t")
        self.assertEqual(r.content, "- {{embed [[Other Note]]}}\n")
        self.assertEqual(r.assets, [])

    def test_asset_embed_and_md_image(self):
        r = cv.convert_note("![[shot.png]]\n\n![alt](img/pic.jpg)\n", "t")
        self.assertIn("- ![shot.png](../assets/shot.png)", r.content)
        self.assertIn("- ![alt](../assets/pic.jpg)", r.content)
        self.assertEqual(sorted(r.assets), ["img/pic.jpg", "shot.png"])

    def test_url_image_untouched(self):
        r = cv.convert_note("![x](https://e.com/a.png)\n", "t")
        self.assertIn("- ![x](https://e.com/a.png)", r.content)
        self.assertEqual(r.assets, [])

    def test_wikilinks_tags_pass_through(self):
        r = cv.convert_note("See [[Page]] #tag\n", "t")
        self.assertEqual(r.content, "- See [[Page]] #tag\n")


if __name__ == "__main__":
    unittest.main()
