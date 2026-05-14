#!/usr/bin/env python3
"""Generate a dedupe markdown report from the SQLite database.

Usage: python3 dedupe-report.py <DB_PATH> <OUTPUT_PATH>

Queries the dedupe database and generates a full markdown report.
Prints JSON stats to stdout for the orchestrator.
Leaves {{EXECUTIVE_SUMMARY}} placeholder for LLM-generated summary.
"""

import json
import sqlite3
import sys
from datetime import datetime


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 dedupe-report.py <DB_PATH> <OUTPUT_PATH>", file=sys.stderr)
        sys.exit(1)

    db_path = sys.argv[1]
    output_path = sys.argv[2]

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get run metadata
    run = conn.execute(
        "SELECT * FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    if not run:
        print('{"error": "No run data found"}')
        sys.exit(1)
    run = dict(run)

    # Get statistics
    total_files = conn.execute("SELECT COUNT(*) FROM file_metadata").fetchone()[0]
    analyzed_ok = conn.execute(
        "SELECT COUNT(*) FROM file_metadata WHERE analysis_status='done'"
    ).fetchone()[0]
    failed_files = conn.execute(
        "SELECT COUNT(*) FROM file_metadata WHERE analysis_status='error'"
    ).fetchone()[0]
    total_units = conn.execute("SELECT COUNT(*) FROM code_units").fetchone()[0]
    total_groups = conn.execute("SELECT COUNT(*) FROM groups").fetchone()[0]

    total_findings = conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    high_count = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE priority='high'"
    ).fetchone()[0]
    medium_count = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE priority='medium'"
    ).fetchone()[0]
    low_count = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE priority='low'"
    ).fetchone()[0]
    groups_with_findings = conn.execute(
        "SELECT COUNT(DISTINCT group_name) FROM findings WHERE scope='intra-group'"
    ).fetchone()[0]
    cross_group_count = conn.execute(
        "SELECT COUNT(*) FROM findings WHERE scope='cross-group'"
    ).fetchone()[0]

    # Build report
    lines = []
    lines.append("# Code Deduplication Analysis Report")
    lines.append("")
    lines.append(f"**Generated**: {datetime.now().isoformat()}")
    lines.append(f"**Project**: {run['project_root']}")
    lines.append(f"**Language**: {run['language']}")
    excluded = run.get("excluded_test_files") or 0
    files_note = f"{analyzed_ok} successfully analyzed"
    if failed_files > 0:
        files_note += f", {failed_files} failed"
    lines.append(
        f"**Files Discovered**: {total_files} ({excluded} test files excluded)"
    )
    lines.append(f"**Files Analyzed**: {files_note}")
    lines.append(f"**Code Units Analyzed**: {total_units}")
    lines.append(f"**Duplications Found**: {total_findings}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append("")
    lines.append("{{EXECUTIVE_SUMMARY}}")
    lines.append("")

    # Findings by Package (intra-group)
    intra_groups = conn.execute(
        "SELECT DISTINCT group_name FROM findings WHERE scope='intra-group' ORDER BY group_name"
    ).fetchall()

    if intra_groups:
        lines.append("## Findings by Package")
        lines.append("")

        for group_row in intra_groups:
            group_name = group_row["group_name"]
            domain_row = conn.execute(
                "SELECT domain FROM groups WHERE group_name = ?", (group_name,)
            ).fetchone()
            domain = domain_row["domain"] if domain_row else "other"

            lines.append(f"### Package: {group_name} ({domain})")
            lines.append("")

            for priority in ("high", "medium", "low"):
                findings = conn.execute(
                    """SELECT * FROM findings
                    WHERE scope='intra-group' AND group_name = ? AND priority = ?
                    ORDER BY finding_id""",
                    (group_name, priority),
                ).fetchall()

                if not findings:
                    continue

                lines.append(f"#### {priority.capitalize()} Priority")
                lines.append("")

                for f in findings:
                    f = dict(f)
                    lines.append(f"##### {f['description']}")
                    lines.append("**Files Involved:**")

                    ff_rows = conn.execute(
                        "SELECT * FROM finding_files WHERE finding_id = ?",
                        (f["finding_id"],),
                    ).fetchall()
                    for ff in ff_rows:
                        ff = dict(ff)
                        loc = (
                            f" ({ff['lines_of_code']} lines)"
                            if ff.get("lines_of_code")
                            else ""
                        )
                        lines.append(
                            f"- `{ff['file_path']}` - `{ff['unit_name']}()`{loc}"
                        )

                    lines.append("")
                    lines.append(
                        f"**Similarity Analysis:** {f['similarity_analysis']}"
                    )
                    lines.append(f"**Differences:** {f['differences']}")
                    lines.append(
                        f"**Impact:** Complexity: {f['impact_complexity']} | "
                        f"Criticality: {f['impact_criticality']} | "
                        f"Risk: {f['impact_risk_of_inconsistency']}"
                    )
                    rec_display = f["recommendation"].replace("-", " ").title()
                    lines.append(f"**Recommendation:** {rec_display}")
                    lines.append(f"**Rationale:** {f['rationale']}")
                    if f.get("refactoring_approach"):
                        lines.append(
                            f"**Refactoring Approach:** {f['refactoring_approach']}"
                        )
                    lines.append(
                        f"**Effort:** {f['effort']} | **Value:** {f['value']}"
                    )
                    if f.get("generated_file_involved"):
                        lines.append(
                            "*Note: Generated file involved — cannot be refactored directly.*"
                        )
                    lines.append("")
                    lines.append("---")
                    lines.append("")

    # Cross-package findings
    cross_findings = conn.execute(
        """SELECT * FROM findings WHERE scope='cross-group'
        ORDER BY CASE priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END""",
    ).fetchall()

    if cross_findings:
        lines.append("## Cross-Package Duplications")
        lines.append("")

        for f in cross_findings:
            f = dict(f)
            groups_list = json.loads(f["groups_json"]) if f.get("groups_json") else []
            groups_str = " <-> ".join(groups_list)

            lines.append(f"### {f['description']}")
            lines.append(f"**Priority:** {f['priority'].capitalize()}")
            lines.append(f"**Packages:** {groups_str}")
            lines.append("**Files Involved:**")

            ff_rows = conn.execute(
                "SELECT * FROM finding_files WHERE finding_id = ?",
                (f["finding_id"],),
            ).fetchall()
            for ff in ff_rows:
                ff = dict(ff)
                loc = (
                    f" ({ff['lines_of_code']} lines)"
                    if ff.get("lines_of_code")
                    else ""
                )
                lines.append(f"- `{ff['file_path']}` - `{ff['unit_name']}()`{loc}")

            lines.append("")
            lines.append(f"**Similarity Analysis:** {f['similarity_analysis']}")
            lines.append(f"**Differences:** {f['differences']}")
            lines.append(
                f"**Impact:** Complexity: {f['impact_complexity']} | "
                f"Criticality: {f['impact_criticality']} | "
                f"Risk: {f['impact_risk_of_inconsistency']}"
            )
            rec_display = f["recommendation"].replace("-", " ").title()
            lines.append(f"**Recommendation:** {rec_display}")
            lines.append(f"**Rationale:** {f['rationale']}")
            if f.get("refactoring_approach"):
                lines.append(
                    f"**Refactoring Approach:** {f['refactoring_approach']}"
                )
            lines.append(f"**Effort:** {f['effort']} | **Value:** {f['value']}")
            if f.get("generated_file_involved"):
                lines.append(
                    "*Note: Generated file involved — cannot be refactored directly.*"
                )
            lines.append("")
            lines.append("---")
            lines.append("")

    # Recommendations Summary
    lines.append("## Recommendations Summary")
    lines.append("")

    top_findings = conn.execute(
        """SELECT f.description, f.priority, f.recommendation, f.effort, f.value,
            GROUP_CONCAT(ff.file_path || ':' || ff.unit_name, ', ') as files
        FROM findings f
        JOIN finding_files ff ON f.finding_id = ff.finding_id
        WHERE f.recommendation != 'leave-as-is'
        GROUP BY f.finding_id
        ORDER BY
            CASE f.priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END,
            CASE f.value WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 END
        LIMIT 10"""
    ).fetchall()

    for i, rec in enumerate(top_findings, 1):
        rec = dict(rec)
        rec_display = rec["recommendation"].replace("-", " ").title()
        lines.append(
            f"{i}. **[{rec['priority'].upper()}]** {rec['description']} "
            f"— {rec_display} (effort: {rec['effort']}, value: {rec['value']})"
        )
    lines.append("")

    # Failed files section (if any)
    if failed_files > 0:
        failed_rows = conn.execute(
            """SELECT file_path, error_message, retry_count
            FROM file_metadata WHERE analysis_status='error'
            ORDER BY file_path"""
        ).fetchall()
        lines.append("## Analysis Failures")
        lines.append("")
        lines.append(
            f"{failed_files} file(s) could not be analyzed after retries "
            "and were excluded from duplicate detection:"
        )
        lines.append("")
        for fr in failed_rows:
            fr = dict(fr)
            err = fr.get("error_message") or "unknown error"
            retries = fr.get("retry_count") or 0
            lines.append(
                f"- `{fr['file_path']}` — {err} (retried {retries} time(s))"
            )
        lines.append("")

    # Statistics
    lines.append("## Statistics")
    lines.append("")
    lines.append(f"- Total files discovered: {total_files}")
    lines.append(f"- Successfully analyzed: {analyzed_ok}")
    if failed_files > 0:
        lines.append(f"- Failed analysis: {failed_files}")
    lines.append(f"- Total duplications found: {total_findings}")
    lines.append(f"- High priority: {high_count}")
    lines.append(f"- Medium priority: {medium_count}")
    lines.append(f"- Low priority: {low_count}")
    lines.append(f"- Packages with duplications: {groups_with_findings}/{total_groups}")
    lines.append(f"- Cross-package duplications: {cross_group_count}")
    lines.append("")

    conn.close()

    # Write report
    report = "\n".join(lines)
    with open(output_path, "w") as fh:
        fh.write(report)

    # Print stats JSON to stdout for orchestrator
    stats = {
        "total_findings": total_findings,
        "high": high_count,
        "medium": medium_count,
        "low": low_count,
        "groups_with_findings": groups_with_findings,
        "total_groups": total_groups,
        "cross_group": cross_group_count,
        "total_files": total_files,
        "analyzed_ok": analyzed_ok,
        "failed_files": failed_files,
        "total_code_units": total_units,
        "report_path": output_path,
        "top_recommendations": [
            {
                "description": dict(r)["description"],
                "priority": dict(r)["priority"],
                "recommendation": dict(r)["recommendation"],
            }
            for r in top_findings[:5]
        ],
    }
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
