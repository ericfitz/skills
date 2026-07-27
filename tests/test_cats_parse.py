import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import parse as P


def cats_json(**over):
    data = {
        "testId": "Test 1", "traceId": "t-1", "fuzzer": "HappyPath",
        "path": "/things", "contractPath": "/things", "fullRequestPath": "/things",
        "scenario": "happy", "expectedResult": "Should return 200",
        "result": "error", "resultReason": "Unexpected Response Code: 400",
        "resultDetails": "details", "server": "http://h",
        "request": {"httpMethod": "POST", "url": "http://h/things",
                     "timestamp": "2026-07-26T00:00:00Z", "payload": '{"a":1}',
                     "headers": [{"key": "Accept", "value": "application/json"}]},
        "response": {"httpMethod": "POST", "responseCode": 400, "responseTimeInMs": 12,
                      "numberOfWordsInResponse": 3, "numberOfLinesInResponse": 1,
                      "contentLengthInBytes": 42, "responseContentType": "application/json",
                      "jsonBody": {"error": "bad"},
                      "headers": [{"key": "Content-Type", "value": "application/json"}]},
    }
    data.update(over)
    return data


class TestRecordNormalization(unittest.TestCase):
    def test_maps_cats_json_to_record(self):
        r = P.record_from_json(cats_json())
        self.assertEqual(r["result"], "error")
        self.assertEqual(r["response_code"], 400)
        self.assertEqual(r["method"], "POST")
        self.assertEqual(r["path"], "/things")
        self.assertEqual(r["json_body"], {"error": "bad"})
        self.assertEqual(json.loads(r["response_body"]), {"error": "bad"})
        self.assertEqual(r["request_body"], '{"a":1}')
        self.assertEqual(r["request_headers"], {"accept": "application/json"})

    def test_null_fields_become_empty_strings(self):
        r = P.record_from_json(cats_json(resultReason=None, resultDetails=None))
        self.assertEqual(r["result_reason"], "")
        self.assertEqual(r["result_details"], "")

    def test_absent_json_body_yields_empty_response_body(self):
        data = cats_json()
        del data["response"]["jsonBody"]
        r = P.record_from_json(data)
        self.assertIsNone(r["json_body"])
        self.assertEqual(r["response_body"], "")

    def test_null_headers_tolerated(self):
        data = cats_json()
        data["request"]["headers"] = None
        data["response"]["headers"] = None
        self.assertEqual(P.record_from_json(data)["request_headers"], {})

    def test_null_request_and_response_tolerated(self):
        data = cats_json()
        data["request"] = None
        data["response"] = None
        r = P.record_from_json(data)
        self.assertEqual(r["method"], "")
        self.assertEqual(r["url"], "")
        self.assertEqual(r["response_code"], 0)
        self.assertEqual(r["request_headers"], {})

    def test_non_mapping_request_and_response_tolerated(self):
        data = cats_json()
        data["request"] = "not-a-mapping"
        data["response"] = ["also", "not", "a", "mapping"]
        r = P.record_from_json(data)
        self.assertEqual(r["method"], "")
        self.assertEqual(r["response_code"], 0)

    def test_non_string_responsecode_becomes_zero(self):
        data = cats_json()
        data["response"]["responseCode"] = "not-a-number"
        self.assertEqual(P.record_from_json(data)["response_code"], 0)

    def test_non_mapping_header_entries_are_skipped(self):
        data = cats_json()
        data["request"]["headers"] = ["not-a-mapping", {"key": "X-Ok", "value": "1"}]
        self.assertEqual(P.record_from_json(data)["request_headers"], {"x-ok": "1"})


class TestExtractTestNumber(unittest.TestCase):
    def test_parses_spaced_and_unspaced_forms(self):
        self.assertEqual(P.extract_test_number("Test 42"), 42)
        self.assertEqual(P.extract_test_number("Test42"), 42)

    def test_unparseable_returns_zero(self):
        self.assertEqual(P.extract_test_number("weird"), 0)


class TestParseReport(unittest.TestCase):
    def _tmp_dir(self) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name)

    def _report(self, files):
        d = self._tmp_dir()
        for name, data in files.items():
            (d / name).write_text(json.dumps(data))
        return d

    def _db_path(self) -> Path:
        return self._tmp_dir() / "r.db"

    def _connect(self, db_path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path)
        self.addCleanup(conn.close)
        return conn

    def test_parses_files_into_db(self):
        report = self._report({
            "Test1.json": cats_json(),
            "Test2.json": cats_json(testId="Test 2", result="success",
                                    response={**cats_json()["response"], "responseCode": 200}),
        })
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1", "server": "http://h"})
        self.assertEqual(stats.processed, 2)
        conn = self._connect(db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT run_id FROM run_meta").fetchone()[0], "R1")

    def test_bodies_stored_only_for_error_and_warn(self):
        report = self._report({
            "Test1.json": cats_json(),                       # error -> body stored
            "Test2.json": cats_json(testId="Test 2", result="success"),
        })
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        rows = dict(conn.execute(
            "SELECT t.test_id, r.response_body FROM tests t JOIN responses r ON r.test_id = t.id"
        ).fetchall())
        self.assertIn("bad", rows["Test 1"])
        self.assertIsNone(rows["Test 2"])

    def test_request_body_stored_only_for_error_and_warn(self):
        report = self._report({
            "Test1.json": cats_json(),                       # error -> body stored
            "Test2.json": cats_json(testId="Test 2", result="success"),
        })
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        rows = dict(conn.execute(
            "SELECT t.test_id, req.request_body FROM tests t JOIN requests req ON req.test_id = t.id"
        ).fetchall())
        self.assertEqual(rows["Test 1"], '{"a":1}')
        self.assertIsNone(rows["Test 2"])

    def test_warn_result_stores_bodies_too(self):
        report = self._report({"Test1.json": cats_json(result="warn")})
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        row = conn.execute(
            "SELECT r.response_body FROM responses r "
            "JOIN result_types rt ON rt.name = 'warn'"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertIn("bad", row[0])

    def test_headers_persisted_in_order(self):
        report = self._report({"Test1.json": cats_json()})
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        self.assertEqual(
            conn.execute("SELECT header_key, header_order FROM request_headers").fetchall(),
            [("Accept", 0)],
        )
        self.assertEqual(
            conn.execute("SELECT header_key, header_order FROM response_headers").fetchall(),
            [("Content-Type", 0)],
        )

    def test_rows_are_never_pre_classified(self):
        report = self._report({"Test1.json": cats_json()})
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        is_fp, fp_rule = conn.execute(
            "SELECT is_false_positive, fp_rule FROM tests"
        ).fetchone()
        self.assertEqual(is_fp, 0)
        self.assertIsNone(fp_rule)

    def test_malformed_file_is_skipped_not_fatal(self):
        report = self._report({"Test1.json": cats_json()})
        (report / "Test2.json").write_text("{not json")
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.skipped, 1)

    def test_top_level_list_is_skipped(self):
        d = self._tmp_dir()
        (d / "Test1.json").write_text(json.dumps(["not", "an", "object"]))
        db = self._db_path()
        stats = P.parse_report(d, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_top_level_string_is_skipped(self):
        d = self._tmp_dir()
        (d / "Test1.json").write_text(json.dumps("just a string"))
        db = self._db_path()
        stats = P.parse_report(d, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_missing_test_id_is_skipped(self):
        report = self._report({})
        data = cats_json()
        del data["testId"]
        (report / "Test1.json").write_text(json.dumps(data))
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_null_request_response_do_not_crash_parse(self):
        report = self._report({})
        data = cats_json()
        data["request"] = None
        data["response"] = None
        (report / "Test1.json").write_text(json.dumps(data))
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.errors, 0)

    def test_null_scenario_is_recovered_not_dropped(self):
        # `scenario` is a required *key* but its value can still be JSON null.
        # record_from_json already normalizes that to "" — the insert must use
        # the normalized value, not the raw (and NOT NULL-violating) None.
        report = self._report({})
        data = cats_json(scenario=None)
        (report / "Test1.json").write_text(json.dumps(data))
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.errors, 0)
        conn = self._connect(db)
        self.assertEqual(conn.execute("SELECT scenario FROM tests").fetchone()[0], "")

    def test_null_test_id_still_fails_the_file(self):
        # Unlike scenario/traceId/expectedResult, testId is the unique key and the
        # test-number source; a null there must still fail (not silently coerce).
        report = self._report({})
        data = cats_json(testId=None)
        (report / "Test1.json").write_text(json.dumps(data))
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.errors, 1)

    def test_failed_insert_leaves_no_orphan_rows(self):
        # A non-scalar `request.timestamp` fails the *second* of five inserts for a
        # file (tests succeeds, requests fails). Without per-file atomicity, the
        # `tests` row from the failed file survives — invisible to every view (they
        # INNER JOIN requests/responses) but still counted by `SELECT COUNT(*) FROM
        # tests`, which is exactly the number the corpus verification reports.
        good = cats_json()
        bad = cats_json(testId="Test 2")
        bad["request"]["timestamp"] = ["not", "a", "scalar"]
        report = self._report({"Test1.json": good, "Test2.json": bad})
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.errors, 1)
        conn = self._connect(db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT test_id FROM tests").fetchone()[0], "Test 1")

    def test_failed_insert_on_responses_leaves_no_orphan_rows(self):
        # Same atomicity guarantee, but the failure lands on the third insert
        # (responses), after both `tests` and `requests` already succeeded for
        # that file — those two rows must also be rolled back together.
        good = cats_json()
        bad = cats_json(testId="Test 2")
        bad["response"]["responseContentType"] = ["not", "a", "scalar"]
        report = self._report({"Test1.json": good, "Test2.json": bad})
        db = self._db_path()
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.errors, 1)
        conn = self._connect(db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0], 1)

    def test_views_exist(self):
        report = self._report({"Test1.json": cats_json()})
        db = self._db_path()
        P.parse_report(report, db, {"run_id": "R1"})
        conn = self._connect(db)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'").fetchall()}
        self.assertIn("true_positives_view", names)
        self.assertIn("test_results_filtered_view", names)


if __name__ == "__main__":
    unittest.main()
