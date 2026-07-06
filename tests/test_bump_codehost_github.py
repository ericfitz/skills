import sys
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.codehosts import github as gh  # noqa: E402


class TestGitHubCodeHost(unittest.TestCase):
    def test_parse_alerts(self):
        advs = gh.parse_alerts((FIX / "dependabot_alerts.json").read_text())
        self.assertEqual(advs[0].package, "qs")
        self.assertEqual(advs[0].severity, "HIGH")
        self.assertEqual(advs[0].fixed, "6.14.2")

    def test_parse_alerts_null_first_patched_version(self):
        """Regression: an alert with first_patched_version=null (no fix
        released yet, e.g. nltk GHSA-p4gq-832x-fm9v) must parse, not crash,
        and yield an empty `fixed`."""
        advs = gh.parse_alerts((FIX / "dependabot_alerts.json").read_text())
        nltk = next(a for a in advs if a.package == "nltk")
        self.assertEqual(nltk.fixed, "")
        self.assertEqual(nltk.severity, "HIGH")

    def test_parse_prs(self):
        ctx = gh.parse_prs((FIX / "dep_prs.json").read_text())
        self.assertEqual(ctx.pullRequests[0]["id"], "#42")

    def test_merge_cmd(self):
        self.assertEqual(gh.merge_cmd(42),
                         ["gh", "pr", "merge", "42", "--squash", "--delete-branch"])

    def test_open_pr_cmd_passes_title_as_arg(self):
        # title with shell metacharacters must appear as its own list element, unescaped
        cmd = gh.open_pr_cmd("bump-x", "bump; rm -rf /", "body")
        self.assertIn("bump; rm -rf /", cmd)
        self.assertEqual(cmd[0:2], ["gh", "pr"])

    def test_alerts_missing_gh_binary(self):
        """Regression test: alerts verb should return [] when gh is missing."""
        with mock.patch("bumplib.codehosts.github.shutil.which", return_value=None):
            result = gh.handle("alerts", [])
            self.assertEqual(result, [])

    def test_prs_missing_gh_binary(self):
        """Regression test: prs verb should return empty Context when gh is missing."""
        with mock.patch("bumplib.codehosts.github.shutil.which", return_value=None):
            result = gh.handle("prs", [])
            # Should be an empty Context
            self.assertEqual(result.issues, [])
            self.assertEqual(result.pullRequests, [])


if __name__ == "__main__":
    unittest.main()
