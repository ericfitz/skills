import unittest
from pathlib import Path
from unittest import mock

from bumplib.trackers import github as tr

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


class TestGitHubTracker(unittest.TestCase):
    def test_parse_issues(self):
        ctx = tr.parse_issues((FIX / "dep_issues.json").read_text())
        self.assertEqual(ctx.issues[0]["id"], "#7")
        self.assertIn("dependencies", ctx.issues[0]["labels"])

    def test_handle_missing_gh(self):
        """Regression test: missing gh binary returns empty Context."""
        with mock.patch("bumplib.trackers.github.shutil.which", return_value=None):
            ctx = tr.handle("issues", [])
            self.assertEqual(ctx.issues, [])
            self.assertEqual(ctx.pullRequests, [])


if __name__ == "__main__":
    unittest.main()
