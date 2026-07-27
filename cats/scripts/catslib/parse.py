"""Parse a CATS report directory into a normalized SQLite database."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_TEST_NUM = re.compile(r"(\d+)")

# Fields the source JSON must have before a record can be normalized. Missing
# any of these makes the file unusable, so it is counted as skipped.
_REQUIRED_FIELDS = (
    "testId", "traceId", "scenario", "expectedResult",
    "result", "fuzzer", "path", "server", "request", "response",
)

_RUN_META_COLUMNS = (
    "run_id", "started_at", "finished_at", "identity", "spec_path",
    "spec_sha256", "rules_sha256", "git_sha", "cats_version", "cats_args",
    "server", "tool_version",
)


@dataclass
class ParseStats:
    processed: int = 0
    skipped: int = 0
    errors: int = 0


class _SkipFile(Exception):
    """Raised internally when a report file cannot be normalized into a record."""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


def extract_test_number(test_id: str) -> int:
    match = _TEST_NUM.search(test_id if isinstance(test_id, str) else "")
    return int(match.group(1)) if match else 0


def _coerce_str(value: Any) -> str:
    """Normalize a JSON scalar (or anything else) to a string; None becomes ''."""
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _headers_dict(headers: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for h in headers or []:
        if not isinstance(h, dict):
            continue
        key = h.get("key")
        if not isinstance(key, str) or not key:
            continue
        result[key.lower()] = _coerce_str(h.get("value"))
    return result


def record_from_json(data: dict[str, Any]) -> dict[str, Any]:
    request = data.get("request")
    request = request if isinstance(request, dict) else {}
    response = data.get("response")
    response = response if isinstance(response, dict) else {}
    json_body = response.get("jsonBody")
    try:
        response_code = int(response.get("responseCode") or 0)
    except (TypeError, ValueError):
        response_code = 0
    result_raw = data.get("result")
    return {
        "result": result_raw.lower() if isinstance(result_raw, str) else "",
        "response_code": response_code,
        "fuzzer": data.get("fuzzer") or "",
        "path": data.get("path") or "",
        "contract_path": data.get("contractPath") or "",
        "method": request.get("httpMethod") or "",
        "url": request.get("url") or "",
        "scenario": data.get("scenario") or "",
        "result_reason": data.get("resultReason") or "",
        "result_details": data.get("resultDetails") or "",
        "response_body": json.dumps(json_body) if json_body is not None else "",
        "response_content_type": response.get("responseContentType") or "",
        "request_body": request.get("payload") or "",
        "json_body": json_body,
        "request_headers": _headers_dict(request.get("headers")),
    }


def _load_json_file(path: Path) -> dict[str, Any]:
    """Load and minimally validate one report file; raise _SkipFile if unusable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise _SkipFile(f"{path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise _SkipFile(f"{path.name}: top level JSON is not an object")
    missing = [f for f in _REQUIRED_FIELDS if f not in data]
    if missing:
        raise _SkipFile(f"{path.name}: missing fields {missing}")
    return data


class _Loader:
    """Holds the open connection, lookup caches, and per-run insert logic."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.result_type_cache: dict[str, int] = {}
        self.fuzzer_cache: dict[str, int] = {}
        self.server_cache: dict[str, int] = {}
        self.path_cache: dict[str, int] = {}
        self.method_cache: dict[str, int] = {}
        self._load_caches()

    def _load_caches(self) -> None:
        c = self.conn
        self.result_type_cache = {
            row[1]: row[0] for row in c.execute("SELECT id, name FROM result_types")
        }
        self.fuzzer_cache = {row[1]: row[0] for row in c.execute("SELECT id, name FROM fuzzers")}
        self.server_cache = {row[1]: row[0] for row in c.execute("SELECT id, base_url FROM servers")}
        self.path_cache = {
            row[1]: row[0] for row in c.execute("SELECT id, path FROM paths")
        }
        self.method_cache = {row[1]: row[0] for row in c.execute("SELECT id, method FROM http_methods")}

    def _get_or_create(self, cache: dict, table: str, column: str, value: str) -> int:
        if value in cache:
            return cache[value]
        self.conn.execute(f"INSERT OR IGNORE INTO {table} ({column}) VALUES (?)", (value,))
        row = self.conn.execute(f"SELECT id FROM {table} WHERE {column} = ?", (value,)).fetchone()
        cache[value] = row[0]
        return row[0]

    def _get_or_create_path(self, path: str, contract_path: str) -> int:
        # `paths.path` alone is UNIQUE (schema.sql), so the cache and the lookup
        # must key on `path` alone too — keying on (path, contract_path) let two
        # files with the same path but different contract_path race the INSERT OR
        # IGNORE into a no-op followed by a SELECT that could return no row. The
        # first contract_path seen for a given path wins; later ones are ignored,
        # same as the constraint enforces.
        if path in self.path_cache:
            return self.path_cache[path]
        self.conn.execute(
            "INSERT OR IGNORE INTO paths (path, contract_path) VALUES (?, ?)",
            (path, contract_path or None),
        )
        row = self.conn.execute(
            "SELECT id FROM paths WHERE path = ?", (path,)
        ).fetchone()
        self.path_cache[path] = row[0]
        return row[0]

    def insert(self, data: dict[str, Any], source_file: str) -> None:
        record = record_from_json(data)

        result_type_id = self._get_or_create(self.result_type_cache, "result_types", "name", record["result"])
        fuzzer_id = self._get_or_create(self.fuzzer_cache, "fuzzers", "name", record["fuzzer"])
        server_id = self._get_or_create(self.server_cache, "servers", "base_url", data.get("server") or "")
        path_id = self._get_or_create_path(record["path"], record["contract_path"])

        cursor = self.conn.execute(
            """
            INSERT INTO tests (
                test_id, test_number, trace_id, scenario, expected_result,
                result_type_id, fuzzer_id, server_id, path_id,
                result_reason, result_details, source_file, is_false_positive, fp_rule
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)
            """,
            (
                data["testId"],
                extract_test_number(data["testId"]),
                data.get("traceId") or "",
                record["scenario"],
                data.get("expectedResult") or "",
                result_type_id,
                fuzzer_id,
                server_id,
                path_id,
                record["result_reason"],
                record["result_details"],
                source_file,
            ),
        )
        test_row_id = cursor.lastrowid

        store_body = record["result"] in ("error", "warn")

        request = data.get("request") if isinstance(data.get("request"), dict) else {}
        method_id = self._get_or_create(self.method_cache, "http_methods", "method", record["method"])
        cursor = self.conn.execute(
            """
            INSERT INTO requests (test_id, http_method_id, url, timestamp, request_body)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                test_row_id,
                method_id,
                record["url"],
                request.get("timestamp") or "",
                record["request_body"] if store_body else None,
            ),
        )
        request_row_id = cursor.lastrowid

        response = data.get("response") if isinstance(data.get("response"), dict) else {}
        resp_method_id = self._get_or_create(
            self.method_cache, "http_methods", "method", response.get("httpMethod") or ""
        )
        cursor = self.conn.execute(
            """
            INSERT INTO responses (
                test_id, http_method_id, response_code, response_time_ms,
                num_words, num_lines, content_length_bytes, response_content_type, response_body
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                test_row_id,
                resp_method_id,
                record["response_code"],
                _safe_int(response.get("responseTimeInMs")),
                _safe_int(response.get("numberOfWordsInResponse")),
                _safe_int(response.get("numberOfLinesInResponse")),
                _safe_int(response.get("contentLengthInBytes")),
                record["response_content_type"],
                record["response_body"] if store_body else None,
            ),
        )
        response_row_id = cursor.lastrowid

        req_headers = [
            (request_row_id, h.get("key"), _coerce_str(h.get("value")), idx)
            for idx, h in enumerate(request.get("headers") or [])
            if isinstance(h, dict) and isinstance(h.get("key"), str)
        ]
        if req_headers:
            self.conn.executemany(
                "INSERT INTO request_headers (request_id, header_key, header_value, header_order) "
                "VALUES (?, ?, ?, ?)",
                req_headers,
            )

        resp_headers = [
            (response_row_id, h.get("key"), _coerce_str(h.get("value")), idx)
            for idx, h in enumerate(response.get("headers") or [])
            if isinstance(h, dict) and isinstance(h.get("key"), str)
        ]
        if resp_headers:
            self.conn.executemany(
                "INSERT INTO response_headers (response_id, header_key, header_value, header_order) "
                "VALUES (?, ?, ?, ?)",
                resp_headers,
            )


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def parse_report(
    report_dir: Path, db_path: Path, run_meta: dict[str, Any], *, batch_size: int = 500
) -> ParseStats:
    """Load every Test*.json file in report_dir into a fresh SQLite database at db_path."""
    stats = ParseStats()

    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
        create_schema(conn)

        conn.execute(
            f"INSERT INTO run_meta ({', '.join(_RUN_META_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _RUN_META_COLUMNS)})",
            tuple(run_meta.get(col) for col in _RUN_META_COLUMNS),
        )
        conn.commit()

        loader = _Loader(conn)

        files = sorted(report_dir.glob("Test*.json"), key=lambda p: extract_test_number(p.stem))

        batch: list[Path] = []
        for i, path in enumerate(files, 1):
            batch.append(path)
            if len(batch) >= batch_size or i == len(files):
                batch_processed = 0
                batch_skipped = 0
                batch_errors = 0
                conn.execute("BEGIN")
                try:
                    for file_path in batch:
                        try:
                            data = _load_json_file(file_path)
                        except _SkipFile:
                            batch_skipped += 1
                            continue
                        # A savepoint isolates one file's five inserts (tests, requests,
                        # responses, both header tables) from the rest of the batch: a
                        # failure partway through must not leave an orphan `tests` row
                        # (or a headerless-but-committed request/response) behind for a
                        # file that's ultimately being counted as an error.
                        conn.execute("SAVEPOINT file_insert")
                        try:
                            loader.insert(data, file_path.name)
                        except (sqlite3.Error, TypeError, ValueError, KeyError):
                            # Broadened beyond sqlite3.Error: a single malformed
                            # file (e.g. a non-string testId reaching
                            # extract_test_number, or any other shape surprise in
                            # record_from_json/insert) must count as one file
                            # error, not escape the savepoint and abort the run.
                            conn.execute("ROLLBACK TO SAVEPOINT file_insert")
                            conn.execute("RELEASE SAVEPOINT file_insert")
                            batch_errors += 1
                        else:
                            conn.execute("RELEASE SAVEPOINT file_insert")
                            batch_processed += 1
                    conn.commit()
                except sqlite3.Error:
                    conn.rollback()
                    # The commit itself failed: every insert in this batch (including
                    # ones that individually succeeded above) was rolled back, so none
                    # of them are actually processed. Files that were skipped before
                    # ever touching the transaction are unaffected by this failure.
                    stats.skipped += batch_skipped
                    stats.errors += batch_errors + batch_processed
                    batch = []
                    continue
                stats.processed += batch_processed
                stats.skipped += batch_skipped
                stats.errors += batch_errors
                batch = []
    finally:
        conn.close()

    return stats
