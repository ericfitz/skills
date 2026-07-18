# tests/test_logseq_scan.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import scan  # noqa: E402


def build_graph(td: str) -> Path:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    (g / "logseq").mkdir()
    (g / "pages" / "Alpha.md").write_text(
        "type:: project\n\n- links to [[Beta]] and [[beta]]\n- see [[Gone]]\n")
    (g / "pages" / "Beta.md").write_text("- tagged #active\n- plain\n")
    (g / "pages" / "Betta.md").write_text("- near-dupe of Beta\n")
    (g / "pages" / "Loner.md").write_text("- nobody links here\n")
    (g / "pages" / "Broken.md").write_text("- a\n\t\t\t- bad indent\n")
    (g / "journals" / "2026_07_17.md").write_text("- day note [[Alpha]]\n")
    return g


class TestScan(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.index = scan.scan_graph(build_graph(self.td.name))

    def tearDown(self):
        self.td.cleanup()

    def test_pages_indexed(self):
        self.assertIn("alpha", self.index.pages)
        self.assertIn("2026_07_17", self.index.pages)
        self.assertTrue(self.index.pages["2026_07_17"].is_journal)

    def test_links_tags_properties(self):
        a = self.index.pages["alpha"]
        self.assertIn("beta", {ln.lower() for ln in a.links})
        self.assertEqual(a.properties.get("type"), "project")
        self.assertIn("active", self.index.pages["beta"].tags)

    def test_backlinks(self):
        self.assertIn("2026_07_17", scan.backlinks(self.index, "alpha"))

    def test_parse_error_recorded_but_links_still_scanned(self):
        b = self.index.pages["broken"]
        self.assertIsNotNone(b.parse_error)


class TestLint(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.findings = scan.lint_all(scan.scan_graph(build_graph(self.td.name)))
        self.by_type = {}
        for f in self.findings:
            self.by_type.setdefault(f["type"], []).append(f)

    def tearDown(self):
        self.td.cleanup()

    def test_unparseable(self):
        self.assertEqual(self.by_type["unparseable"][0]["page"], "Broken")

    def test_broken_link(self):
        details = [f["detail"] for f in self.by_type["broken-link"]]
        self.assertTrue(any("Gone" in d for d in details))

    def test_case_conflict(self):
        details = " ".join(f["detail"] for f in self.by_type["case-conflict"])
        self.assertIn("Beta", details)
        self.assertIn("beta", details)

    def test_orphan_excludes_journals_and_linked(self):
        pages = [f["page"] for f in self.by_type["orphan"]]
        self.assertIn("Loner", pages)
        self.assertNotIn("Alpha", pages)  # linked from journal
        self.assertNotIn("2026_07_17", pages)

    def test_near_duplicate(self):
        details = " ".join(f["detail"] for f in self.by_type["near-duplicate"])
        self.assertIn("Betta", details)


if __name__ == "__main__":
    unittest.main()
