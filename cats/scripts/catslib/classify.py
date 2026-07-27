"""Apply declarative rules to a parsed CATS database."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .rules import Rule, classify_record


class ClassifyError(Exception):
    """The database is not one classify_db can work with."""


# `:test_row_id` lets classify_db (all rows) and record_from_db (one row) share this
# query without string-concatenating a trailing clause onto it — a later ORDER BY or
# LIMIT added to the base would otherwise silently swallow a concatenated predicate.
SELECT_CANDIDATES = """
SELECT t.id, t.test_id, t.is_false_positive, rt.name AS result, t.result_reason,
       t.result_details, t.scenario, f.name AS fuzzer, p.path, p.contract_path,
       req.url, m.method, req.request_body, resp.response_code,
       resp.response_content_type, resp.response_body
FROM tests t
JOIN result_types rt ON t.result_type_id = rt.id
JOIN fuzzers f ON t.fuzzer_id = f.id
JOIN paths p ON t.path_id = p.id
JOIN requests req ON req.test_id = t.id
JOIN http_methods m ON req.http_method_id = m.id
JOIN responses resp ON resp.test_id = t.id
WHERE rt.name IN ('error', 'warn')
  AND (:test_row_id IS NULL OR t.id = :test_row_id)
"""


@dataclass
class ClassifyResult:
    total: int = 0
    flagged: int = 0
    by_rule: dict[str, int] = field(default_factory=dict)
    violations: list[tuple[str, str]] = field(default_factory=list)
    newly_suppressed: list[str] = field(default_factory=list)
    newly_surfaced: list[str] = field(default_factory=list)


def _headers(conn: sqlite3.Connection, row_id: int) -> dict[str, str]:
    # ORDER BY header_order so a duplicate header key resolves last-wins in the same
    # order parse.record_from_json's _headers_dict does (JSON array order) — without
    # it, "last" depends on whatever order SQLite happens to return rows in.
    rows = conn.execute(
        "SELECT header_key, header_value FROM request_headers rh "
        "JOIN requests r ON rh.request_id = r.id WHERE r.test_id = ? "
        "ORDER BY rh.header_order",
        (row_id,),
    ).fetchall()
    return {(k or "").lower(): v or "" for k, v in rows}


def _record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    body = row["response_body"] or ""
    try:
        json_body = json.loads(body) if body else None
    except (json.JSONDecodeError, TypeError):
        # TypeError covers a non-str value in response_body: SQLite's flexible typing
        # permits it even though the column is declared TEXT (e.g. a hand-edited or
        # otherwise corrupted DB), and json.loads raises TypeError, not
        # JSONDecodeError, for a non-str/bytes argument.
        json_body = None
    return {
        "result": row["result"],
        "response_code": row["response_code"],
        "fuzzer": row["fuzzer"],
        "path": row["path"],
        "contract_path": row["contract_path"] or "",
        "method": row["method"],
        "url": row["url"] or "",
        "scenario": row["scenario"] or "",
        "result_reason": row["result_reason"] or "",
        "result_details": row["result_details"] or "",
        "response_body": body,
        "response_content_type": row["response_content_type"] or "",
        "request_body": row["request_body"] or "",
        "json_body": json_body,
        "request_headers": _headers(conn, row["id"]),
    }


def record_from_db(conn: sqlite3.Connection, test_row_id: int) -> dict[str, Any]:
    """Rebuild the normalized record for one test row, by its internal `tests.id`.

    `conn.row_factory` must be `sqlite3.Row` (as `classify_db` sets on its own
    connection) — this function reads columns by name, not position.
    """
    row = conn.execute(SELECT_CANDIDATES, {"test_row_id": test_row_id}).fetchone()
    if row is None:
        raise ValueError(f"no error/warn test row with id={test_row_id}")
    return _record(conn, row)


def _ensure_classified_at_column(conn: sqlite3.Connection, db_path: Path) -> None:
    """Idempotent migration: add run_meta.classified_at if this DB predates it.

    `parse.create_schema` only ever runs `CREATE TABLE IF NOT EXISTS`, so a database
    parsed before this column existed keeps a `run_meta` without it forever — nothing
    alters an existing table. Re-parsing a 100k+-row report just to pick up one
    nullable column would be a poor trade, and reclassifying without re-parsing is
    the whole point of separating classify_db from parse_report. So this migrates
    in place instead.

    A migrated pre-fix database ends up with `classified_at = NULL`, which is
    correct, not a shortcut: we genuinely don't know what rule set produced
    whatever classifications it already has, so its next pass is rightly treated as
    a first pass (empty deltas) by `_is_first_pass`.

    Raises `ClassifyError` (not a raw `sqlite3.OperationalError`) if `run_meta`
    itself is missing — a database this module didn't create at all.
    """
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "run_meta" not in tables:
        raise ClassifyError(f"{db_path}: no run_meta table — not created by catslib.parse.create_schema")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(run_meta)")}
    if "classified_at" not in columns:
        conn.execute("ALTER TABLE run_meta ADD COLUMN classified_at TEXT")
        conn.commit()


def _is_first_pass(conn: sqlite3.Connection) -> bool:
    """True if this DB has never been classified before.

    `tests.is_false_positive` starts at 0 for every row at parse time (see
    parse.py), so on a genuine first pass every "flagged" row would otherwise look
    identical to a "newly suppressed" one — the delta would list the entire flagged
    set instead of reporting nothing changed. `run_meta.classified_at` is the
    explicit marker that disambiguates the two: NULL (or no `run_meta` row at all —
    e.g. one deleted by hand) means first pass. classify_db sets it at the end of
    every pass it can find a row for; if no row exists it never fabricates one, so a
    DB missing run_meta stays a "first pass" on every future call, indefinitely.
    """
    row = conn.execute("SELECT classified_at FROM run_meta").fetchone()
    return row is None or row[0] is None


def classify_db(db_path: Path, rules: list[Rule], *, allow_5xx: bool) -> ClassifyResult:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    result = ClassifyResult()
    counts = {rule.id: 0 for rule in rules}
    updates: list[tuple[int, str | None, int]] = []
    try:
        _ensure_classified_at_column(conn, db_path)
        first_pass = _is_first_pass(conn)
        for row in conn.execute(SELECT_CANDIDATES, {"test_row_id": None}):
            result.total += 1
            record = _record(conn, row)
            is_fp, rule_id, violation = classify_record(rules, record, allow_5xx=allow_5xx)
            if violation:
                result.violations.append((violation, row["test_id"]))
            was_fp = bool(row["is_false_positive"])
            if not first_pass:
                if is_fp and not was_fp:
                    result.newly_suppressed.append(row["test_id"])
                elif was_fp and not is_fp:
                    result.newly_surfaced.append(row["test_id"])
            if is_fp:
                result.flagged += 1
                counts[rule_id] = counts.get(rule_id, 0) + 1
            updates.append((1 if is_fp else 0, rule_id, row["id"]))

        with conn:
            conn.executemany(
                "UPDATE tests SET is_false_positive = ?, fp_rule = ? WHERE id = ?", updates
            )
            conn.execute("DELETE FROM fp_rules")
            conn.executemany(
                "INSERT INTO fp_rules (rule_id, why, order_index, enabled, match_count) "
                "VALUES (?, ?, ?, ?, ?)",
                [(r.id, r.why, r.order_index, 1 if r.enabled else 0, counts.get(r.id, 0))
                 for r in rules],
            )
            # No WHERE clause: run_meta always has at most one row (parse_report
            # inserts exactly one). If that row is missing, this affects zero rows
            # rather than fabricating one — _is_first_pass's docstring covers why.
            conn.execute(
                "UPDATE run_meta SET classified_at = ?",
                (datetime.now(timezone.utc).isoformat(),),
            )
        result.by_rule = {k: v for k, v in counts.items() if v}
    finally:
        conn.close()
    return result
