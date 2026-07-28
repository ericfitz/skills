# tests/test_logseq_apply.py
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import apply as ap

STAMP = "20260717T120000Z"


def graph_with_page(td: str) -> tuple[Path, Path]:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "logseq").mkdir()
    f = g / "pages" / "A.md"
    f.write_text("- old\n")
    return g, f


class TestDryRunAndDiff(unittest.TestCase):
    def test_dry_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            out = ap.apply_changeset(
                g, [ap.Change(f, "- new\n")], STAMP, dry_run=True)
            self.assertTrue(out["dry_run"])
            self.assertIn("-- old", out["diff"].replace("\n", " "))
            self.assertEqual(f.read_text(), "- old\n")

    def test_diff_covers_create_and_delete(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            new = g / "pages" / "B.md"
            d = ap.diff_changeset(g, [ap.Change(new, "- born\n"),
                                      ap.Change(f, None)])
            self.assertIn("pages/B.md", d)
            self.assertIn("+- born", d)
            self.assertIn("-- old", d)  # deletion of the "- old" line


class TestApply(unittest.TestCase):
    def test_apply_writes_backs_up_and_deletes(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            other = g / "pages" / "B.md"
            out = ap.apply_changeset(
                g, [ap.Change(f, None), ap.Change(other, "- hi\n")], STAMP)
            self.assertFalse(f.exists())
            self.assertEqual(other.read_text(), "- hi\n")
            bdir = g / "logseq" / ".backups" / STAMP
            self.assertEqual((bdir / "pages" / "A.md").read_text(), "- old\n")
            self.assertEqual(out["backup"], str(bdir))
            self.assertIn("pages/B.md", out["applied"])

    def test_path_outside_graph_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            g, _ = graph_with_page(td)
            with tempfile.TemporaryDirectory() as td2:
                stray = Path(td2) / "x.md"
                with self.assertRaises(ap.ApplyError):
                    ap.apply_changeset(g, [ap.Change(stray, "- x\n")], STAMP)


class TestGitGuard(unittest.TestCase):
    def _git(self, g, *args):
        subprocess.run(["git", "-C", str(g), *args], check=True,
                       capture_output=True)

    def test_dirty_tree_blocks_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            self._git(g, "init", "-q")
            self._git(g, "add", "-A")
            self._git(g, "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "init")
            f.write_text("- dirty\n")  # uncommitted change
            with self.assertRaises(ap.ApplyError):
                ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            out = ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP,
                                     force=True)
            self.assertEqual(f.read_text(), "- new\n")
            self.assertIn("pages/A.md", out["applied"])

    def test_non_git_graph_needs_no_force(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            self.assertEqual(f.read_text(), "- new\n")

    def test_dirty_tree_blocks_when_graph_is_subdirectory_of_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git(root, "init", "-q")
            (root / "graph").mkdir()
            g, f = graph_with_page(str(root / "graph"))
            self._git(root, "add", "-A")
            self._git(root, "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "init")
            f.write_text("- dirty\n")  # uncommitted change, outside graph dir
            with self.assertRaises(ap.ApplyError):
                ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            out = ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP,
                                     force=True)
            self.assertEqual(f.read_text(), "- new\n")
            self.assertIn("pages/A.md", out["applied"])

    def test_clean_tree_applies_when_graph_is_subdirectory_of_repo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._git(root, "init", "-q")
            (root / "graph").mkdir()
            g, f = graph_with_page(str(root / "graph"))
            self._git(root, "add", "-A")
            self._git(root, "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "init")
            ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            self.assertEqual(f.read_text(), "- new\n")


if __name__ == "__main__":
    unittest.main()
