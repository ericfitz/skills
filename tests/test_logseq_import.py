# tests/test_logseq_import.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import convert as cv  # noqa: E402


def build(td: str) -> tuple[Path, Path]:
    root = Path(td)
    vault = root / "vault"
    (vault / "sub").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    (vault / "Simple.md").write_text("Hello\n")
    (vault / "sub" / "Deep.md").write_text("Deep note ![[pic.png]]\n")
    (vault / "pic.png").write_bytes(b"PNG")
    (vault / ".obsidian" / "junk.md").write_text("skip me\n")
    graph = root / "graph"
    (graph / "pages").mkdir(parents=True)
    (graph / "logseq").mkdir()
    (graph / "assets").mkdir()
    return vault, graph


class TestPlanImport(unittest.TestCase):
    def test_statuses_and_naming(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            src_hash = cv.source_hash((vault / "Simple.md").read_text())
            # pre-existing native page -> collision
            (graph / "pages" / "sub%2FDeep.md").write_text("- native\n")
            plans = {p.page_name: p for p in cv.plan_import(vault, graph)}
            self.assertEqual(plans["Simple"].status, "new")
            self.assertIn(f"import-hash:: {src_hash}",
                          plans["Simple"].content)
            self.assertIn("imported-from:: Simple.md", plans["Simple"].content)
            self.assertEqual(plans["sub/Deep"].status, "collision")
            self.assertNotIn(".obsidian/junk", plans)

    def test_unchanged_and_changed(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            plans = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            cv_changes = cv.import_changes(plans)
            for ch in cv_changes:
                ch.path.parent.mkdir(parents=True, exist_ok=True)
                ch.path.write_text(ch.new_content)
            again = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            self.assertEqual(again[0].status, "unchanged")
            (vault / "Simple.md").write_text("Hello edited\n")
            third = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            self.assertEqual(third[0].status, "changed")

    def test_scope_dir(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            plans = cv.plan_import(vault, graph, scope=vault / "sub")
            self.assertEqual([p.page_name for p in plans], ["sub/Deep"])


class TestAssets(unittest.TestCase):
    def test_asset_copy_pairs_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            (vault / "sub" / "Gone.md").write_text("![[nope.png]]\n")
            plans = cv.plan_import(vault, graph, scope=vault / "sub")
            pairs = cv.asset_copies(vault, graph, plans)
            self.assertEqual(pairs, [(vault / "pic.png",
                                      graph / "assets" / "pic.png")])
            gone = next(p for p in plans if p.page_name == "sub/Gone")
            self.assertTrue(any("nope.png" in w for w in gone.warnings))
            dests = cv.copy_assets(pairs)
            self.assertEqual((graph / "assets" / "pic.png").read_bytes(),
                             b"PNG")
            self.assertEqual(dests, [str(graph / "assets" / "pic.png")])


if __name__ == "__main__":
    unittest.main()
