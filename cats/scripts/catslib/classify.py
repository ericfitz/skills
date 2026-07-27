"""Apply declarative rules to a parsed CATS database."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .rules import Rule, classify_record

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
    rows = conn.execute(
        "SELECT header_key, header_value FROM request_headers rh "
        "JOIN requests r ON rh.request_id = r.id WHERE r.test_id = ?",
        (row_id,),
    ).fetchall()
    return {(k or "").lower(): v or "" for k, v in rows}


def _record(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    body = row["response_body"] or ""
    try:
        json_body = json.loads(body) if body else None
    except json.JSONDecodeError:
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


def record_from_db(conn: sqlite3.Connection, test_row_id: int) -> dict:
    """Rebuild the normalized record for one test row, by its internal `tests.id`.

    `conn.row_factory` must be `sqlite3.Row` (as `classify_db` sets on its own
    connection) — this function reads columns by name, not position.
    """
    row = conn.execute(SELECT_CANDIDATES + " AND t.id = ?", (test_row_id,)).fetchone()
    if row is None:
        raise ValueError(f"no error/warn test row with id={test_row_id}")
    return _record(conn, row)


def classify_db(db_path: Path, rules: list[Rule], *, allow_5xx: bool) -> ClassifyResult:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    result = ClassifyResult()
    counts = {rule.id: 0 for rule in rules}
    updates: list[tuple[int, str | None, int]] = []
    try:
        for row in conn.execute(SELECT_CANDIDATES):
            result.total += 1
            record = _record(conn, row)
            is_fp, rule_id, violation = classify_record(rules, record, allow_5xx=allow_5xx)
            if violation:
                result.violations.append((violation, row["test_id"]))
            was_fp = bool(row["is_false_positive"])
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
        result.by_rule = {k: v for k, v in counts.items() if v}
    finally:
        conn.close()
    return result
