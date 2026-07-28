# tests/test_bump_config.py
import json
import tempfile
import unittest
from pathlib import Path

from bumplib import config as cfg


class TestClaudeExclusions(unittest.TestCase):
    def test_parses_bullets_under_heading(self):
        text = ("# Project\n\n## Bump Exclusions\n"
                "- @angular/*\n- zone.js\n\n## Other\n- not-this\n")
        self.assertEqual(cfg.parse_claude_exclusions(text), ["@angular/*", "zone.js"])

    def test_no_heading_returns_empty(self):
        self.assertEqual(cfg.parse_claude_exclusions("# X\n- a\n"), [])


class TestMerge(unittest.TestCase):
    def _root(self, td, claude=None, bump_cfg=None):
        root = Path(td)
        if claude is not None:
            (root / "CLAUDE.md").write_text(claude)
        if bump_cfg is not None:
            (root / ".bump-config.json").write_text(json.dumps(bump_cfg))
        return root

    def test_merges_both_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, claude="## Bump Exclusions\n- a/*\n",
                              bump_cfg={"exclude": ["b"], "hold": {"c": "later"}})
            excl, holds = cfg.merged_exclusions(root)
            self.assertIn("a/*", excl)
            self.assertIn("b", excl)
            self.assertEqual(holds["c"], "later")


class TestResolveAdapter(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(cfg.resolve_adapter("issueTracker", {"issueTracker": "jira"}, None), "jira")

    def test_autodetect_github(self):
        self.assertEqual(cfg.resolve_adapter("codeHost", {}, "git@github.com:o/r.git"), "github")

    def test_none_when_not_github(self):
        self.assertEqual(cfg.resolve_adapter("codeHost", {}, "git@gitlab.com:o/r.git"), "none")


if __name__ == "__main__":
    unittest.main()
