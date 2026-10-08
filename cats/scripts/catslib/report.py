"""Summarize a classified CATS results database and render it as a self-contained
HTML report.

The two entry points serve different consumers: `summary()` returns plain data
(dicts/lists) that both `render_html()` and cmd_run's printed post-run summary
consume, so it never prints and never touches HTML. `render_html()` is presentation
only — it calls `summary()` and formats the result as one standalone HTML document
(inline `<style>`, no external URLs, everything escaped) for cmd_report to write to
a file.
"""

from __future__ import annotations

import html
import re
import sqlite3
from pathlib import Path
from typing import Any

# Individual true positives can run in the tens of thousands on a real fuzzing
# campaign; without a cap the report itself becomes the 100MB+ file this plugin
# exists to avoid. The path-grouped table is the "whole story" view, so it gets a
# smaller cap — 25 rows is already more distinct paths than a human will read.
TRUE_POSITIVE_ROW_CAP = 500
TRUE_POSITIVE_PATH_CAP = 25


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a CATS results database read-only.

    A report generator has no business being able to write to the database it
    reads. This is the library-internal sibling of cats_tool.open_results_db: same
    read-only URI technique, but this module can't call sys.exit on a bad path
    (it's a library, not a CLI command), so an invalid database surfaces here as a
    plain sqlite3.Error instead of a clean exit-2 message.
    """
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def summary(db_path: Path) -> dict[str, Any]:
    """Aggregate a classified run's provenance, counts, and true positives.

    Keys: run_meta, by_result, false_positive_total, by_rule, zero_match_rules,
    true_positives_by_path, true_positives_by_path_total, true_positives.
    """
    conn = _connect(db_path)
    try:
        run_meta_row = conn.execute("SELECT * FROM run_meta LIMIT 1").fetchone()
        run_meta = dict(run_meta_row) if run_meta_row else {}

        by_result = dict(
            conn.execute(
                "SELECT rt.name, COUNT(*) FROM tests t "
                "JOIN result_types rt ON t.result_type_id = rt.id GROUP BY rt.name"
            ).fetchall()
        )

        false_positive_total = conn.execute(
            "SELECT COUNT(*) FROM tests WHERE is_false_positive = 1"
        ).fetchone()[0]

        by_rule = dict(
            conn.execute(
                "SELECT rule_id, match_count FROM fp_rules "
                "WHERE match_count > 0 ORDER BY match_count DESC"
            ).fetchall()
        )

        zero_match_rules = [
            row[0]
            for row in conn.execute(
                "SELECT rule_id FROM fp_rules WHERE match_count = 0 ORDER BY order_index"
            )
        ]

        true_positives_by_path = [
            {"path": row[0], "count": row[1], "fuzzers": row[2]}
            for row in conn.execute(
                "SELECT path, COUNT(*) c, GROUP_CONCAT(DISTINCT fuzzer) "
                "FROM true_positives_view GROUP BY path ORDER BY c DESC LIMIT ?",
                (TRUE_POSITIVE_PATH_CAP,),
            )
        ]

        # Denominator for "Top 25 of N affected paths" — without it a reader can't
        # tell 25-of-26 (basically everything) from 25-of-400 (a small slice).
        true_positives_by_path_total = conn.execute(
            "SELECT COUNT(DISTINCT path) FROM true_positives_view"
        ).fetchone()[0]

        true_positives = [
            dict(row)
            for row in conn.execute(
                "SELECT test_id, result, fuzzer, path, http_method, response_code, "
                "scenario, result_reason FROM true_positives_view "
                "ORDER BY response_code DESC, path LIMIT ?",
                (TRUE_POSITIVE_ROW_CAP,),
            )
        ]
    finally:
        conn.close()

    return {
        "run_meta": run_meta,
        "by_result": by_result,
        "false_positive_total": false_positive_total,
        "by_rule": by_rule,
        "zero_match_rules": zero_match_rules,
        "true_positives_by_path": true_positives_by_path,
        "true_positives_by_path_total": true_positives_by_path_total,
        "true_positives": true_positives,
    }


# C0 controls other than \t and \n, plus the Unicode bidi-override/embedding
# (U+202A-202E) and bidi-isolate (U+2066-2069) characters. html.escape only
# touches `& < > " '` — it does nothing about these, and CATS genuinely sends
# them (e.g. a scenario containing U+202E RIGHT-TO-LEFT OVERRIDE). They can't
# execute, so this isn't the same class of bug as unescaped markup, but a bidi
# override left as-is visually reorders the text around it, which is a spoofing
# risk in a report a human uses to judge whether a finding is real.
_DANGEROUS_CHARS_RE = re.compile("[\x00-\x08\x0b-\x1f\u202a-\u202e\u2066-\u2069]")


def _defang(text: str) -> str:
    return _DANGEROUS_CHARS_RE.sub(lambda m: f"&#x{ord(m.group()):x};", text)


def _esc(value: Any) -> str:
    if value is None:
        return ""
    # html.escape first, then defang: _defang's own output ("&#x...;") must not be
    # re-escaped, so the "&" it introduces has to land after html.escape has run.
    return _defang(html.escape(str(value)))


def _table(headers: list[str], rows: list[tuple[Any, ...]], *, max_height: str | None = None) -> str:
    """Render a table, escaped, wrapped in a horizontally scrollable container so
    a wide row (long scenario strings, response reasons, ...) never forces the
    whole page to scroll sideways. `max_height` additionally bounds the container
    vertically (with its own scrollbar) so the CSS `th { position: sticky }` rule
    has a scrolling ancestor to stick within — without a bounded height it's a
    no-op, since horizontal-only overflow never triggers sticky positioning."""
    if not rows:
        return '<p class="empty">(none)</p>'
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{_esc(v)}</td>" for v in row) + "</tr>" for row in rows
    )
    style = "overflow-x:auto"
    if max_height is not None:
        style += f";overflow-y:auto;max-height:{max_height}"
    return (
        f'<div style="{style}">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
        "</div>"
    )


_STYLE = """
<style>
  body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif;
         margin: 2rem; color: #1a1a1a; background: #fff; }
  h1 { margin-bottom: 0.25rem; }
  h2 { margin-top: 2.5rem; border-bottom: 1px solid #ccc; padding-bottom: 0.25rem; }
  .note { color: #555; font-size: 0.9rem; }
  .warning { color: #7a1f1f; background: #fdecec; border: 1px solid #f3b8b8;
             padding: 0.5rem 0.75rem; border-radius: 4px; display: inline-block; }
  table { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
  th, td { border: 1px solid #ddd; padding: 0.35rem 0.6rem; text-align: left;
           vertical-align: top; }
  th { background: #f5f5f5; position: sticky; top: 0; }
  td { font-family: SFMono-Regular, Consolas, Menlo, monospace; word-break: break-word; }
  tr:nth-child(even) { background: #fafafa; }
  .empty { color: #777; font-style: italic; }
  dl { display: grid; grid-template-columns: max-content 1fr; gap: 0.15rem 1rem; }
  dt { font-weight: 600; color: #333; }
  dd { margin: 0; font-family: SFMono-Regular, Consolas, Menlo, monospace; }
</style>
"""

_PROVENANCE_FIELDS = [
    ("run_id", "Run ID"),
    ("started_at", "Started"),
    ("finished_at", "Finished"),
    ("classified_at", "Classified"),
    ("identity", "Identity"),
    ("server", "Server"),
    ("spec_path", "Spec"),
    ("spec_sha256", "Spec SHA-256"),
    ("rules_sha256", "Rules SHA-256"),
    ("git_sha", "Git SHA"),
    ("cats_version", "CATS version"),
    ("tool_version", "Tool version"),
    ("cats_args", "CATS args"),
]


def _provenance_section(run_meta: dict[str, Any]) -> str:
    if not run_meta:
        return "<h2>Run</h2><p class=\"empty\">No run_meta row found.</p>"

    parts = ["<h2>Run</h2>"]
    # A latest.db symlink only ever points at a run whose finished_at was stamped
    # by execute() after parse AND classify both succeeded (see runner.py); a NULL
    # here means this database is from a run that was interrupted mid-pipeline, so
    # its contents may be partial or unclassified. That has to be visible, not
    # rendered as if it were an ordinary complete run.
    if not run_meta.get("finished_at"):
        parts.append(
            '<p class="warning">This run never finished (no finished_at recorded) '
            "— results below may be partial or unclassified.</p>"
        )
    rows = [
        (label, run_meta[key])
        for key, label in _PROVENANCE_FIELDS
        if run_meta.get(key) not in (None, "")
    ]
    dl = "".join(f"<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>" for label, value in rows)
    parts.append(f"<dl>{dl}</dl>")
    return "".join(parts)


def render_html(db_path: Path) -> str:
    """Render one self-contained HTML document summarizing a classified run."""
    data = summary(db_path)
    run_meta = data["run_meta"]
    by_result = data["by_result"]
    true_positives = data["true_positives"]

    total_errors_warns = by_result.get("error", 0) + by_result.get("warn", 0)
    true_positive_total = total_errors_warns - data["false_positive_total"]

    title = f"CATS report — {run_meta.get('run_id') or 'unknown run'}"

    sections = [_provenance_section(run_meta)]

    sections.append("<h2>Result mix</h2>")
    sections.append(
        _table(
            ["Result", "Count"],
            sorted(by_result.items(), key=lambda kv: kv[1], reverse=True),
        )
    )

    sections.append("<h2>False positives</h2>")
    sections.append(f"<p>{data['false_positive_total']} test(s) suppressed as false positives.</p>")
    sections.append("<h3>By rule</h3>")
    sections.append(_table(["Rule ID", "Matches"], list(data["by_rule"].items())))

    sections.append("<h3>Zero-match rules</h3>")
    sections.append(
        '<p class="note">Rules that never matched — candidates for staleness review.</p>'
    )
    if data["zero_match_rules"]:
        items = "".join(f"<li>{_esc(r)}</li>" for r in data["zero_match_rules"])
        sections.append(f"<ul>{items}</ul>")
    else:
        sections.append('<p class="empty">(none)</p>')

    path_total = data["true_positives_by_path_total"]
    sections.append("<h2>True positives by path</h2>")
    if path_total > len(data["true_positives_by_path"]):
        sections.append(
            f'<p class="note">Top {TRUE_POSITIVE_PATH_CAP} of {path_total} '
            "affected paths, by true-positive count.</p>"
        )
    else:
        sections.append(f'<p class="note">{path_total} affected path(s).</p>')
    sections.append(
        _table(
            ["Path", "Count", "Fuzzers"],
            [(r["path"], r["count"], r["fuzzers"]) for r in data["true_positives_by_path"]],
        )
    )

    sections.append("<h2>Individual true positives</h2>")
    if true_positive_total > len(true_positives):
        sections.append(
            f'<p class="note">Showing {len(true_positives)} of {true_positive_total} '
            f"true positives (capped at {TRUE_POSITIVE_ROW_CAP}, ordered by response "
            "code desc then path). Use `cats_tool.py query` for the rest.</p>"
        )
    else:
        sections.append(f'<p class="note">{len(true_positives)} true positive(s).</p>')
    sections.append(
        _table(
            ["Test ID", "Result", "Fuzzer", "Path", "Method", "Code", "Scenario", "Reason"],
            [
                (
                    tp["test_id"], tp["result"], tp["fuzzer"], tp["path"],
                    tp["http_method"], tp["response_code"], tp["scenario"],
                    tp["result_reason"],
                )
                for tp in true_positives
            ],
            max_height="600px",
        )
    )

    body = "\n".join(sections)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n"
        f"{_STYLE}\n"
        "</head>\n"
        "<body>\n"
        f"<h1>{_esc(title)}</h1>\n"
        f"{body}\n"
        "</body>\n"
        "</html>\n"
    )
