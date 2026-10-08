import unittest
from pathlib import Path
from unittest import mock

from bumplib.codehosts import github as gh

BASE = Path(__file__).resolve().parents[1]
FIX = BASE / "tests" / "fixtures" / "bump"


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


class TestOpenPrSurfacesStderr(unittest.TestCase):
    """#36: `gh pr create` writes its failure reason to stderr and only the PR URL to
    stdout, so an adapter that returns stdout alone reports every failure as "".
    The skill scrapes the URL out of `output` on success, so stderr must be appended
    only on the failure path (gh may warn on stderr even when it succeeds)."""

    def _handle(self, rc, stdout, stderr):
        with mock.patch("bumplib.codehosts.github.shutil.which", return_value="/usr/bin/gh"), \
                mock.patch("bumplib.codehosts.github._run",
                           return_value=mock.Mock(returncode=rc, stdout=stdout, stderr=stderr)):
            return gh.handle("open-pr", ["bump-x", "title", "body"])

    def test_failure_includes_stderr(self):
        err = 'a pull request for branch "bump-x" into branch "main" already exists:\n' \
              'https://github.com/o/r/pull/856\n'
        result = self._handle(1, "", err)
        self.assertFalse(result["ok"])
        self.assertIn("already exists", result["output"])
        self.assertIn("pull/856", result["output"])

    def test_failure_keeps_stdout_too(self):
        result = self._handle(1, "partial\n", "HTTP 503\n")
        self.assertEqual(result["output"], "partial\nHTTP 503")

    def test_success_output_is_stdout_only(self):
        result = self._handle(0, "https://github.com/o/r/pull/857\n",
                              "Warning: 1 uncommitted change\n")
        self.assertTrue(result["ok"])
        self.assertEqual(result["output"], "https://github.com/o/r/pull/857")


if __name__ == "__main__":
    unittest.main()
