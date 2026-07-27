import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import classify as C
from catslib import parse as P
from catslib import rules as R


def cats_json(**over):
    data = {
        "testId": "Test 1", "traceId": "t-1", "fuzzer": "HappyPath",
        "path": "/things", "contractPath": "/things", "scenario": "s",
        "expectedResult": "200", "result": "error",
        "resultReason": "Unexpected Response Code: 400", "resultDetails": "",
        "server": "http://h",
        "request": {"httpMethod": "POST", "url": "http://h/things",
                     "timestamp": "", "payload": "", "headers": []},
        "response": {"httpMethod": "POST", "responseCode": 400, "responseTimeInMs": 1,
                      "numberOfWordsInResponse": 1, "numberOfLinesInResponse": 1,
                      "contentLengthInBytes": 1, "responseContentType": "application/json",
                      "jsonBody": {"error_description": "bad enum_values"}, "headers": []},
    }
    data.update(over)
    return data


def build_db(tests):
    report = Path(tempfile.mkdtemp())
    for i, data in enumerate(tests, 1):
        (report / f"Test{i}.json").write_text(json.dumps(data))
    db = Path(tempfile.mkdtemp()) / "r.db"
    P.parse_report(report, db, {"run_id": "R1"})
    return db


def write_rules(text):
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        fh.write(text)
    return R.load_rules(Path(fh.name))


ONE_RULE = "version: 1\nrules:\n  - id: VALIDATION_400\n    why: correct rejection\n    when: {response_code: 400}\n"


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

    def test_classification_is_idempotent(self):
        db = build_db([cats_json()])
        rules = write_rules(ONE_RULE)
        first = C.classify_db(db, rules, allow_5xx=False)
        second = C.classify_db(db, rules, allow_5xx=False)
        self.assertEqual(first.flagged, second.flagged)
        self.assertEqual(second.newly_suppressed, [])
        self.assertEqual(second.newly_surfaced, [])

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

    def test_record_from_db_matches_classification_record(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        row_id = conn.execute("SELECT id FROM tests WHERE test_id = 'Test 1'").fetchone()[0]
        record = C.record_from_db(conn, row_id)
        self.assertEqual(record["response_code"], 400)
        self.assertEqual(record["fuzzer"], "HappyPath")
        self.assertEqual(record["result"], "error")
        self.assertEqual(record["json_body"], {"error_description": "bad enum_values"})

    def test_record_from_db_unknown_id_raises(self):
        db = build_db([cats_json()])
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        with self.assertRaises(ValueError):
            C.record_from_db(conn, 999999)


if __name__ == "__main__":
    unittest.main()
