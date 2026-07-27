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
    def _report(self, files):
        d = Path(tempfile.mkdtemp())
        for name, data in files.items():
            (d / name).write_text(json.dumps(data))
        return d

    def test_parses_files_into_db(self):
        report = self._report({
            "Test1.json": cats_json(),
            "Test2.json": cats_json(testId="Test 2", result="success",
                                    response={**cats_json()["response"], "responseCode": 200}),
        })
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(report, db, {"run_id": "R1", "server": "http://h"})
        self.assertEqual(stats.processed, 2)
        conn = sqlite3.connect(db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT run_id FROM run_meta").fetchone()[0], "R1")

    def test_bodies_stored_only_for_error_and_warn(self):
        report = self._report({
            "Test1.json": cats_json(),                       # error -> body stored
            "Test2.json": cats_json(testId="Test 2", result="success"),
        })
        db = Path(tempfile.mkdtemp()) / "r.db"
        P.parse_report(report, db, {"run_id": "R1"})
        conn = sqlite3.connect(db)
        rows = dict(conn.execute(
            "SELECT t.test_id, r.response_body FROM tests t JOIN responses r ON r.test_id = t.id"
        ).fetchall())
        self.assertIn("bad", rows["Test 1"])
        self.assertIn(rows["Test 2"], (None, ""))

    def test_headers_persisted_in_order(self):
        report = self._report({"Test1.json": cats_json()})
        db = Path(tempfile.mkdtemp()) / "r.db"
        P.parse_report(report, db, {"run_id": "R1"})
        conn = sqlite3.connect(db)
        self.assertEqual(
            conn.execute("SELECT header_key, header_order FROM request_headers").fetchall(),
            [("Accept", 0)],
        )

    def test_malformed_file_is_skipped_not_fatal(self):
        report = self._report({"Test1.json": cats_json()})
        (report / "Test2.json").write_text("{not json")
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.skipped, 1)

    def test_top_level_list_is_skipped(self):
        d = Path(tempfile.mkdtemp())
        (d / "Test1.json").write_text(json.dumps(["not", "an", "object"]))
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(d, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_top_level_string_is_skipped(self):
        d = Path(tempfile.mkdtemp())
        (d / "Test1.json").write_text(json.dumps("just a string"))
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(d, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_missing_test_id_is_skipped(self):
        report = self._report({})
        data = cats_json()
        del data["testId"]
        (report / "Test1.json").write_text(json.dumps(data))
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 0)
        self.assertEqual(stats.skipped, 1)

    def test_null_request_response_do_not_crash_parse(self):
        report = self._report({})
        data = cats_json()
        data["request"] = None
        data["response"] = None
        (report / "Test1.json").write_text(json.dumps(data))
        db = Path(tempfile.mkdtemp()) / "r.db"
        stats = P.parse_report(report, db, {"run_id": "R1"})
        self.assertEqual(stats.processed, 1)
        self.assertEqual(stats.errors, 0)

    def test_views_exist(self):
        report = self._report({"Test1.json": cats_json()})
        db = Path(tempfile.mkdtemp()) / "r.db"
        P.parse_report(report, db, {"run_id": "R1"})
        conn = sqlite3.connect(db)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'").fetchall()}
        self.assertIn("true_positives_view", names)
        self.assertIn("test_results_filtered_view", names)


if __name__ == "__main__":
    unittest.main()
