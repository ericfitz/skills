import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import classify as C
from catslib import parse as P
from catslib import report as Rep
from catslib import rules as R

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_cats_classify import build_db, cats_json, write_rules  # noqa: E402


class TestSummary(unittest.TestCase):
    def setUp(self):
        self.db = build_db([cats_json(), cats_json(testId="Test 2", fuzzer="Other")])
        C.classify_db(self.db, write_rules(
            "version: 1\nrules:\n  - id: ONLY_HAPPY\n    why: w\n    when: {fuzzer: HappyPath}\n"),
            allow_5xx=False)

    def test_counts_split_by_classification(self):
        s = Rep.summary(self.db)
        self.assertEqual(s["false_positive_total"], 1)
        self.assertEqual(s["by_rule"]["ONLY_HAPPY"], 1)
        self.assertEqual(len(s["true_positives"]), 1)
        self.assertEqual(s["true_positives"][0]["fuzzer"], "Other")

    def test_zero_match_rules_listed(self):
        C.classify_db(self.db, write_rules(
            "version: 1\nrules:\n  - id: NEVER\n    why: w\n    when: {response_code: 418}\n"),
            allow_5xx=False)
        self.assertEqual(Rep.summary(self.db)["zero_match_rules"], ["NEVER"])


class TestRenderHtml(unittest.TestCase):
    def test_self_contained_and_escaped(self):
        db = build_db([cats_json(scenario="<script>alert(1)</script>")])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertIn("<!doctype html>", html.lower())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        for marker in ("http://cdn", "https://cdn", "src=\"http"):
            self.assertNotIn(marker, html)

    def test_reports_true_positive_paths(self):
        db = build_db([cats_json()])
        C.classify_db(db, [], allow_5xx=False)
        self.assertIn("/things", Rep.render_html(db))


if __name__ == "__main__":
    unittest.main()
