import sqlite3
import unittest

from cats_fixtures import build_db, cats_json, write_rules
from catslib import classify as C
from catslib import report as Rep


def _set_run_meta(db, **columns):
    """Directly mutate run_meta for tests that need provenance fields build_db's
    helper (which only ever sets run_id) can't reach."""
    conn = sqlite3.connect(db)
    try:
        for key, value in columns.items():
            conn.execute(f"UPDATE run_meta SET {key} = ?", (value,))
        conn.commit()
    finally:
        conn.close()


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


class TestConnectReadOnly(unittest.TestCase):
    def test_connection_rejects_writes(self):
        db = build_db([cats_json()])
        conn = Rep._connect(db)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM tests")
        finally:
            conn.close()


class TestRenderHtml(unittest.TestCase):
    def test_self_contained_and_escaped(self):
        db = build_db([cats_json(scenario="<script>alert(1)</script>")])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertIn("<!doctype html>", html.lower())
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        for marker in ("<script", "<link", "url(", "@import", "//fonts."):
            self.assertNotIn(marker, html)

    def test_reports_true_positive_paths(self):
        db = build_db([cats_json()])
        C.classify_db(db, [], allow_5xx=False)
        self.assertIn("/things", Rep.render_html(db))


class TestEscapingAcrossSites(unittest.TestCase):
    """test_self_contained_and_escaped only exercises the <td> path (via
    scenario). Every other interpolation site needs its own hostile payload."""

    def test_run_id_escaped_in_title_and_heading(self):
        db = build_db([cats_json()])
        _set_run_meta(db, run_id='R"><img src=x onerror=alert(1)>')
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn("<img src=x onerror=alert(1)>", html)
        self.assertIn("&lt;img", html)

    def test_provenance_field_escaped_in_dd(self):
        db = build_db([cats_json()])
        _set_run_meta(db, identity="<script>evil()</script>")
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn("<script>evil()</script>", html)
        self.assertIn("&lt;script&gt;evil()&lt;/script&gt;", html)

    def test_zero_match_rule_id_escaped_in_li(self):
        db = build_db([cats_json()])
        rules = write_rules(
            'version: 1\nrules:\n  - id: "<img src=x onerror=alert(2)>"\n'
            "    why: w\n    when: {response_code: 418}\n"
        )
        C.classify_db(db, rules, allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn("<img src=x onerror=alert(2)>", html)
        self.assertIn("&lt;img", html)


class TestBidiAndControlCharsDefanged(unittest.TestCase):
    def test_rlo_override_is_defanged(self):
        rlo = "\u202e"
        db = build_db([cats_json(scenario=f"safe{rlo}evil")])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn(rlo, html)
        self.assertIn("&#x202e;", html)

    def test_c0_control_is_defanged(self):
        db = build_db([cats_json(scenario="a\x01b")])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn("\x01", html)
        self.assertIn("&#x1;", html)


class TestRunProvenance(unittest.TestCase):
    def test_interrupted_run_shows_warning(self):
        # A bare parse+classify (no runner.execute()) never stamps finished_at.
        db = build_db([cats_json()])
        C.classify_db(db, [], allow_5xx=False)
        self.assertIn("never finished", Rep.render_html(db))

    def test_finished_run_has_no_warning(self):
        db = build_db([cats_json()])
        _set_run_meta(db, finished_at="2026-01-01T00:00:00+00:00")
        C.classify_db(db, [], allow_5xx=False)
        self.assertNotIn("never finished", Rep.render_html(db))


class TestTruePositiveCapNotice(unittest.TestCase):
    def test_cap_notice_shown_when_exceeded(self):
        cap = Rep.TRUE_POSITIVE_ROW_CAP
        db = build_db([cats_json(testId=f"Test {i}") for i in range(cap + 1)])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertIn(f"Showing {cap} of {cap + 1} true positives", html)

    def test_no_cap_notice_under_cap(self):
        db = build_db([cats_json()])
        C.classify_db(db, [], allow_5xx=False)
        html = Rep.render_html(db)
        self.assertNotIn("capped at", html)


if __name__ == "__main__":
    unittest.main()
