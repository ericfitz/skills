import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.ecosystems import go  # noqa: E402


class TestGoOutdated(unittest.TestCase):
    def test_parses_bracketed_updates_only(self):
        recs = go.parse_outdated((FIX / "go_list.txt").read_text())
        names = {r.name: r for r in recs}
        self.assertIn("github.com/gin-gonic/gin", names)
        self.assertEqual(names["github.com/gin-gonic/gin"].current, "v1.10.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].latest, "v1.11.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].bump, "minor")
        # up-to-date line must be excluded
        self.assertNotIn("golang.org/x/sys", names)

    def test_replace_and_pinned(self):
        gomod = ("module x\nrequire (\n\tgithub.com/foo/bar v1.2.3 // pinned: compat\n)\n"
                 "replace github.com/foo/bar => ./local\n")
        self.assertIn("github.com/foo/bar", go.replace_targets(gomod))
        self.assertIn("github.com/foo/bar", go.pinned_names(gomod))

    def test_replace_targets_block_form_two_entries(self):
        gomod = (
            "module x\n"
            "replace (\n"
            "\tgithub.com/foo/bar => ./local\n"
            "\tgithub.com/baz/qux v1.0.0 => github.com/baz/qux v1.0.1\n"
            ")\n"
        )
        targets = go.replace_targets(gomod)
        self.assertEqual({"github.com/foo/bar", "github.com/baz/qux"}, targets)
        self.assertNotIn("(", targets)

    def test_replace_targets_single_line(self):
        gomod = "module x\nreplace github.com/foo/bar => ./local\n"
        targets = go.replace_targets(gomod)
        self.assertEqual({"github.com/foo/bar"}, targets)
        self.assertNotIn("(", targets)

    def test_pinned_names_single_line_require(self):
        gomod = "module x\nrequire github.com/foo/bar v1.2.3 // pinned: compat\n"
        names = go.pinned_names(gomod)
        self.assertIn("github.com/foo/bar", names)
        self.assertNotIn("require", names)

    def test_pinned_names_block_form_require(self):
        gomod = (
            "module x\n"
            "require (\n"
            "\tgithub.com/foo/bar v1.2.3 // pinned: compat\n"
            "\tgithub.com/other/pkg v2.0.0\n"
            ")\n"
        )
        names = go.pinned_names(gomod)
        self.assertIn("github.com/foo/bar", names)
        self.assertNotIn("github.com/other/pkg", names)
        self.assertNotIn("require", names)


class TestGoParseVuln(unittest.TestCase):
    def test_parse_vuln(self):
        text = (FIX / "govulncheck.json").read_text()
        advs = go.parse_vuln(text)
        self.assertEqual(len(advs), 1)
        self.assertEqual(advs[0].ids, ["GO-2024-1234"])
        self.assertEqual(advs[0].package, "github.com/foo/bar")


if __name__ == "__main__":
    unittest.main()
