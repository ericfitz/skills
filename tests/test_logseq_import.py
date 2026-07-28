# tests/test_logseq_import.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import convert as cv


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

    def test_batch_collision_different_bytes_gets_suffixed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = root / "vault"
            (vault / "a").mkdir(parents=True)
            (vault / "b").mkdir(parents=True)
            # Path-qualified refs so each note resolves to its own same-named
            # asset via _find_asset's direct (vault / ref) lookup, rather
            # than the ambiguous basename fallback picking one for both.
            (vault / "a" / "Note.md").write_text("![[a/pic.png]]\n")
            (vault / "b" / "Note.md").write_text("![[b/pic.png]]\n")
            (vault / "a" / "pic.png").write_bytes(b"A")
            (vault / "b" / "pic.png").write_bytes(b"B")
            graph = root / "graph"
            (graph / "pages").mkdir(parents=True)
            (graph / "logseq").mkdir()
            (graph / "assets").mkdir()

            plans = cv.plan_import(vault, graph)
            pairs = cv.asset_copies(vault, graph, plans)

            dests = {dest for _src, dest in pairs}
            self.assertEqual(len(pairs), 2)
            self.assertEqual(len(dests), 2)
            self.assertIn(graph / "assets" / "pic.png", dests)
            suffixed = dests - {graph / "assets" / "pic.png"}
            self.assertEqual(len(suffixed), 1)
            suffixed_name = next(iter(suffixed)).name
            self.assertRegex(suffixed_name, r"^pic-[0-9a-f]{8}\.png$")

            cv.copy_assets(pairs)
            contents = {dest.read_bytes() for _src, dest in pairs}
            self.assertEqual(contents, {b"A", b"B"})

    def test_batch_same_asset_referenced_twice_dedupes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = root / "vault"
            (vault / "a").mkdir(parents=True)
            (vault / "b").mkdir(parents=True)
            (vault / "a" / "Note.md").write_text("![[shared.png]]\n")
            (vault / "b" / "Note.md").write_text("![[shared.png]]\n")
            (vault / "shared.png").write_bytes(b"SHARED")
            graph = root / "graph"
            (graph / "pages").mkdir(parents=True)
            (graph / "logseq").mkdir()
            (graph / "assets").mkdir()

            plans = cv.plan_import(vault, graph)
            pairs = cv.asset_copies(vault, graph, plans)

            self.assertEqual(pairs, [(vault / "shared.png",
                                      graph / "assets" / "shared.png")])

    def test_batch_collision_identical_bytes_different_files_dedupes(self):
        # Two distinct source files (different dirs, same basename) that
        # happen to hold identical bytes should collapse to one copy pair,
        # not one plain + one duplicate write to the same dest.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            vault = root / "vault"
            (vault / "a").mkdir(parents=True)
            (vault / "b").mkdir(parents=True)
            (vault / "a" / "Note.md").write_text("![[a/pic.png]]\n")
            (vault / "b" / "Note.md").write_text("![[b/pic.png]]\n")
            (vault / "a" / "pic.png").write_bytes(b"SAME")
            (vault / "b" / "pic.png").write_bytes(b"SAME")
            graph = root / "graph"
            (graph / "pages").mkdir(parents=True)
            (graph / "logseq").mkdir()
            (graph / "assets").mkdir()

            plans = cv.plan_import(vault, graph)
            pairs = cv.asset_copies(vault, graph, plans)

            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0][1], graph / "assets" / "pic.png")


class TestFindAsset(unittest.TestCase):
    def test_find_asset_deterministic_among_duplicates(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            (vault / "aaa").mkdir()
            (vault / "zzz").mkdir()
            (vault / "zzz" / "dup.png").write_bytes(b"Z")
            (vault / "aaa" / "dup.png").write_bytes(b"A")

            found = cv._find_asset(vault, "dup.png")
            self.assertEqual(found, vault / "aaa" / "dup.png")


if __name__ == "__main__":
    unittest.main()
