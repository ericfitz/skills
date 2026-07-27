import sqlite3
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cats_fixtures import ONE_RULE, build_db, cats_json, write_rules
from catslib import classify as C
from catslib import parse as P
from catslib import rules as R


class TestClassifyDb(unittest.TestCase):
    def test_flags_matching_rows(self):
        db = build_db([cats_json()])
        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.flagged, 1)
        self.assertEqual(result.by_rule, {"VALIDATION_400": 1})
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT is_false_positive, fp_rule FROM tests").fetchone()
        self.assertEqual(row, (1, "VALIDATION_400"))

    def test_success_rows_never_flagged(self):
        db = build_db([cats_json(result="success")])
        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.flagged, 0)

    def test_rule_matching_on_json_body_path(self):
        rules = write_rules("version: 1\nrules:\n  - id: ADDON\n    why: w\n"
                            "    when: {json_body.error_description: {contains: enum_values}}\n")
        db = build_db([cats_json()])
        self.assertEqual(C.classify_db(db, rules, allow_5xx=False).flagged, 1)

    def test_rules_table_populated_with_counts(self):
        db = build_db([cats_json()])
        C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        conn = sqlite3.connect(db)
        self.assertEqual(
            conn.execute("SELECT rule_id, why, match_count FROM fp_rules").fetchall(),
            [("VALIDATION_400", "correct rejection", 1)],
        )

    def test_zero_match_rule_recorded_for_staleness_detection(self):
        rules = write_rules(ONE_RULE + "  - id: NEVER\n    why: w\n    when: {response_code: 418}\n")
        db = build_db([cats_json()])
        C.classify_db(db, rules, allow_5xx=False)
        conn = sqlite3.connect(db)
        counts = dict(conn.execute("SELECT rule_id, match_count FROM fp_rules").fetchall())
        self.assertEqual(counts["NEVER"], 0)

    def test_5xx_violation_reported_and_not_suppressed(self):
        resp = {**cats_json()["response"], "responseCode": 500}
        db = build_db([cats_json(response=resp)])
        rules = write_rules("version: 1\nrules:\n  - id: TOO_BROAD\n    why: w\n    when: {fuzzer: HappyPath}\n")
        result = C.classify_db(db, rules, allow_5xx=False)
        self.assertEqual(result.flagged, 0)
        self.assertEqual(result.violations, [("TOO_BROAD", "Test 1")])

    def test_reclassify_reports_newly_suppressed(self):
        db = build_db([cats_json()])
        C.classify_db(db, [], allow_5xx=False)
        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.newly_suppressed, ["Test 1"])
        self.assertEqual(result.newly_surfaced, [])

    def test_reclassify_reports_newly_surfaced_when_rule_removed(self):
        db = build_db([cats_json()])
        C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        result = C.classify_db(db, [], allow_5xx=False)
        self.assertEqual(result.newly_surfaced, ["Test 1"])
        self.assertEqual(result.newly_suppressed, [])
        # The delta is computed before the write; assert the write actually
        # happened too, not just that the in-memory result object says so.
        conn = sqlite3.connect(db)
        row = conn.execute("SELECT is_false_positive, fp_rule FROM tests").fetchone()
        self.assertEqual(row, (0, None))

    def test_classification_is_idempotent(self):
        db = build_db([cats_json()])
        rules = write_rules(ONE_RULE)
        first = C.classify_db(db, rules, allow_5xx=False)
        conn = sqlite3.connect(db)
        state_after_first = conn.execute("SELECT is_false_positive, fp_rule FROM tests").fetchall()
        counts_after_first = dict(conn.execute("SELECT rule_id, match_count FROM fp_rules").fetchall())

        second = C.classify_db(db, rules, allow_5xx=False)
        self.assertEqual(first.flagged, second.flagged)
        self.assertEqual(second.newly_suppressed, [])
        self.assertEqual(second.newly_surfaced, [])
        # Re-running with the same rules must leave the DB itself unchanged, not
        # just report empty deltas.
        state_after_second = conn.execute("SELECT is_false_positive, fp_rule FROM tests").fetchall()
        counts_after_second = dict(conn.execute("SELECT rule_id, match_count FROM fp_rules").fetchall())
        self.assertEqual(state_after_first, state_after_second)
        self.assertEqual(counts_after_first, counts_after_second)

    def test_first_pass_returns_empty_deltas_even_when_rows_flagged(self):
        # A freshly parsed DB has is_false_positive=0 on every row, identical to
        # what a prior pass that suppressed nothing would also leave behind. Without
        # the explicit run_meta.classified_at marker, this first pass would
        # misreport every flagged row as "newly suppressed".
        db = build_db([cats_json()])
        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.flagged, 1)
        self.assertEqual(result.newly_suppressed, [])
        self.assertEqual(result.newly_surfaced, [])

    def test_missing_run_meta_row_treated_as_first_pass(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM run_meta")
        conn.commit()
        conn.close()

        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.flagged, 1)
        self.assertEqual(result.newly_suppressed, [])
        self.assertEqual(result.newly_surfaced, [])

        # classify_db must not fabricate a run_meta row, so every subsequent pass
        # on this DB stays a "first pass" indefinitely — no crash, no false deltas.
        result2 = C.classify_db(db, [], allow_5xx=False)
        self.assertEqual(result2.newly_surfaced, [])
        self.assertEqual(result2.newly_suppressed, [])

    def test_malformed_response_body_degrades_gracefully(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.execute("UPDATE responses SET response_body = ? WHERE test_id = 1", ("not valid json{",))
        conn.commit()
        conn.close()
        # VALIDATION_400 matches on response_code alone, so a malformed body
        # (which can only ever resolve json_body to None) must not stop it
        # from matching, and must not raise.
        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.total, 1)
        self.assertEqual(result.flagged, 1)

    def test_partial_failure_leaves_previous_classification_intact(self):
        db = build_db([cats_json()])
        first = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(first.flagged, 1)

        # Two Rule objects sharing an id collide on fp_rules' PRIMARY KEY during
        # the bulk INSERT, well after the tests UPDATE has already been issued
        # in the same `with conn:` transaction. A correct implementation must
        # roll the whole pass back rather than leave the tests table pointing
        # at a fp_rule/fp_rules pair that never got committed together.
        dup_rules = [
            R.Rule(id="DUP", why="w", when={"response_code": 400}, any_of=None, enabled=True),
            R.Rule(id="DUP", why="w2", when={"response_code": 401}, any_of=None, enabled=True),
        ]
        with self.assertRaises(sqlite3.IntegrityError):
            C.classify_db(db, dup_rules, allow_5xx=False)

        conn = sqlite3.connect(db)
        row = conn.execute("SELECT is_false_positive, fp_rule FROM tests").fetchone()
        self.assertEqual(row, (1, "VALIDATION_400"))
        self.assertEqual(
            conn.execute("SELECT rule_id FROM fp_rules").fetchall(), [("VALIDATION_400",)]
        )

    def test_record_from_db_unknown_id_raises(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with self.assertRaises(ValueError):
            C.record_from_db(conn, 999999)


class TestRecordEquivalence(unittest.TestCase):
    """`parse.record_from_json` (used to classify inline, during parsing) and
    `classify.record_from_db` (used to reclassify from a persisted database)
    must normalize the *same* CATS JSON to the *same* record — that agreement
    is this branch's central cross-module invariant. Each test here builds the
    record both ways from identical input and compares the full dicts, not a
    handful of spot-checked fields.
    """

    def _both(self, data):
        record_json = P.record_from_json(data)
        db = build_db([data])
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row_id = conn.execute(
            "SELECT id FROM tests WHERE test_id = ?", (data["testId"],)
        ).fetchone()[0]
        record_db = C.record_from_db(conn, row_id)
        return record_json, record_db

    def test_baseline(self):
        record_json, record_db = self._both(cats_json())
        self.assertEqual(record_json, record_db)

    def test_missing_json_body(self):
        data = cats_json()
        del data["response"]["jsonBody"]
        record_json, record_db = self._both(data)
        self.assertEqual(record_json, record_db)

    def test_null_response(self):
        record_json, record_db = self._both(cats_json(response=None))
        self.assertEqual(record_json, record_db)

    def test_duplicate_header_keys(self):
        data = cats_json()
        data["request"]["headers"] = [
            {"key": "X-Dup", "value": "first"},
            {"key": "x-dup", "value": "second"},
        ]
        record_json, record_db = self._both(data)
        self.assertEqual(record_json["request_headers"], {"x-dup": "second"})
        self.assertEqual(record_json, record_db)

    def test_non_json_body(self):
        # jsonBody need not be an object — CATS reports a bare JSON scalar/array
        # response body as-is.
        data = cats_json()
        data["response"]["jsonBody"] = "just a string"
        record_json, record_db = self._both(data)
        self.assertEqual(record_json["json_body"], "just a string")
        self.assertEqual(record_json, record_db)

    def test_empty_string_header_key_is_a_known_unreachable_divergence(self):
        # The one shape where the two builders genuinely disagree: parse.record_
        # from_json's _headers_dict skips a header whose key is "" (not just
        # falsy-but-present) when building the in-memory record, so the key is
        # absent entirely. The DB round trip does not apply that same filter at
        # insert time, so classify.record_from_db's _headers() reads the row back
        # and lower()s "" to "", producing a real (if empty) key. This can never
        # be observed through a rule: rules.field_value's "request_header."
        # prefix handling aside, rules.load_rules' _validate_field rejects any
        # field name of the form "request_header." with nothing after the
        # prefix at rule-*load* time (PREFIX_FIELDS requires len(name) >
        # len(prefix)), so no rule can ever be written that looks up the empty
        # header name to observe this divergence.
        data = cats_json()
        data["request"]["headers"] = [{"key": "", "value": "orphan"}]
        record_json, record_db = self._both(data)
        self.assertNotIn("", record_json["request_headers"])
        self.assertEqual(record_db["request_headers"].get(""), "orphan")


def _downgrade_run_meta_to_prefix_schema(db):
    """Simulate a DB parsed before run_meta.classified_at existed.

    Rebuilds run_meta with exactly the pre-migration 12-column shape and copies
    its one row across. Deliberately not `ALTER TABLE run_meta DROP COLUMN
    classified_at`: SQLite's DROP COLUMN rewrites the stored CREATE TABLE text, and
    (independently confirmed, unrelated to this codebase) it raises a spurious
    "incomplete input" OperationalError whenever 2+ consecutive `--` comment lines
    immediately precede the dropped column — which is exactly the shape of the
    comment schema.sql now carries above `classified_at`. Recreating the table
    directly sidesteps that SQLite quirk and is also just a more faithful model of
    "a database created before this column was added to schema.sql" than dropping
    a column that predates the DB never actually had.
    """
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT run_id, started_at, finished_at, identity, spec_path, spec_sha256, "
        "rules_sha256, git_sha, cats_version, cats_args, server, tool_version FROM run_meta"
    ).fetchone()
    conn.execute("DROP TABLE run_meta")
    conn.execute("""
        CREATE TABLE run_meta (
            run_id TEXT PRIMARY KEY,
            started_at TEXT,
            finished_at TEXT,
            identity TEXT,
            spec_path TEXT,
            spec_sha256 TEXT,
            rules_sha256 TEXT,
            git_sha TEXT,
            cats_version TEXT,
            cats_args TEXT,
            server TEXT,
            tool_version TEXT
        )
    """)
    if row is not None:
        conn.execute(
            "INSERT INTO run_meta (run_id, started_at, finished_at, identity, spec_path, "
            "spec_sha256, rules_sha256, git_sha, cats_version, cats_args, server, tool_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    conn.commit()
    conn.close()


class TestSchemaMigration(unittest.TestCase):
    def test_pre_fix_database_is_migrated_and_treated_as_first_pass(self):
        db = build_db([cats_json()])
        _downgrade_run_meta_to_prefix_schema(db)
        conn = sqlite3.connect(db)
        self.assertNotIn(
            "classified_at", [row[1] for row in conn.execute("PRAGMA table_info(run_meta)")]
        )
        conn.close()

        result = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(result.flagged, 1)
        self.assertEqual(result.newly_suppressed, [])
        self.assertEqual(result.newly_surfaced, [])

        conn = sqlite3.connect(db)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(run_meta)")]
        self.assertIn("classified_at", columns)

    def test_second_pass_after_migration_reports_real_transitions(self):
        db = build_db([cats_json()])
        _downgrade_run_meta_to_prefix_schema(db)

        C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        result = C.classify_db(db, [], allow_5xx=False)
        self.assertEqual(result.newly_surfaced, ["Test 1"])
        self.assertEqual(result.newly_suppressed, [])

    def test_migration_is_idempotent(self):
        db = build_db([cats_json()])
        _downgrade_run_meta_to_prefix_schema(db)

        first = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        second = C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertEqual(first.flagged, second.flagged)
        # Second call sees a DB that already has the column (with a value already
        # set by the first call), so it's a genuine second pass with no delta for
        # an unchanged rule set.
        self.assertEqual(second.newly_suppressed, [])
        self.assertEqual(second.newly_surfaced, [])
        conn = sqlite3.connect(db)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(run_meta)")]
        self.assertEqual(columns.count("classified_at"), 1)

    def test_database_without_run_meta_raises_classify_error(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.execute("DROP TABLE run_meta")
        conn.commit()
        conn.close()

        with self.assertRaises(C.ClassifyError) as ctx:
            C.classify_db(db, write_rules(ONE_RULE), allow_5xx=False)
        self.assertIn(str(db), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
