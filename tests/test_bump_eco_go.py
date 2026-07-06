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


if __name__ == "__main__":
    unittest.main()
