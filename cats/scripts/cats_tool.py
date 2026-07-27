#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml"]
# ///
"""CATS fuzzing toolkit: run, parse, classify, query and report API fuzz results."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catslib.classify import ClassifyError, classify_db
from catslib.config import (
    INITIAL_RULES_YAML,
    Config,
    ConfigError,
    find_config,
    load_config,
    render_init_config,
)
from catslib.parse import parse_report
from catslib.rules import RuleError, load_rules
from catslib.runner import HookError, PreflightError, execute, run_id_for

DEFAULT_SERVER = "http://localhost:8080"
DEFAULT_RESULTS_DIR = "test/results/cats"
DEFAULT_RULES = "test/cats/false-positives.yaml"
DEFAULT_TOKEN_CMD = "echo REPLACE_ME"

# Tried in order; the first pattern that yields any match decides the outcome (one
# match: use it; several: ambiguous, stop and ask for --spec). Later patterns are
# only tried if an earlier one matched nothing at all. Deliberately stack-agnostic —
# no project-specific directory names (e.g. a source repo's own schema-folder
# convention) belong in this list.
SPEC_GLOB_PATTERNS = (
    "openapi.json",
    "openapi.yaml",
    "api/openapi*.json",
    "api/openapi*.yaml",
    "docs/openapi*.json",
    "docs/openapi*.yaml",
)

DELTA_CAP = 20


def print_table(headers: list[str], rows: list) -> None:
    """Print rows as a column-aligned table with header and separator."""
    if not rows:
        print("  (no results)")
        return
    widths = [len(h) for h in headers]
    str_rows = [[str(v) for v in row] for row in rows]
    for row in str_rows:
        for i, val in enumerate(row):
            if i < len(widths):
                widths[i] = max(widths[i], len(val))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in str_rows:
        print(fmt.format(*row))


def _print_capped(label: str, items: list[str], cap: int = DELTA_CAP) -> None:
    if not items:
        return
    print(f"{label} ({len(items)}):")
    for item in items[:cap]:
        print(f"  {item}")
    if len(items) > cap:
        print(f"  ... and {len(items) - cap} more")


def load() -> Config:
    """Find and load the repo's config, or exit 2 with an actionable message."""
    path = find_config(Path.cwd())
    if path is None:
        print("No .local/cats/config.yaml found. Run /cats:init to create one.", file=sys.stderr)
        sys.exit(2)
    return load_config(path)


def resolve_db(config: Config, value: str | None) -> Path:
    """Resolve --db: 'latest'/None goes through results_dir/latest.db, which only
    ever points at the most recent COMPLETE run (see runner._update_latest_symlink)
    — a run that failed before finishing parse+classify never moves it."""
    if value is None or value == "latest":
        latest = config.results_dir / "latest.db"
        if not latest.exists():
            print(
                f"No completed CATS run found in {config.results_dir} "
                "(latest.db is missing, or points at a run that never finished). "
                "Run `cats_tool.py run` to fuzz and produce one, or pass --db <file> "
                "to use a specific database.",
                file=sys.stderr,
            )
            sys.exit(2)
        return latest.resolve()
    path = Path(value)
    if not path.is_file():
        print(f"Database not found: {path}", file=sys.stderr)
        sys.exit(2)
    return path


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------

def _discover_spec(repo_root: Path, *, non_interactive: bool) -> str:
    for pattern in SPEC_GLOB_PATTERNS:
        matches = sorted(repo_root.glob(pattern))
        if len(matches) == 1:
            return matches[0].relative_to(repo_root).as_posix()
        if len(matches) > 1:
            print("Multiple OpenAPI spec candidates found:", file=sys.stderr)
            for m in matches:
                print(f"  {m.relative_to(repo_root).as_posix()}", file=sys.stderr)
            print("Pass --spec to choose one.", file=sys.stderr)
            sys.exit(2)

    tried = ", ".join(SPEC_GLOB_PATTERNS)
    if non_interactive:
        print(
            f"No OpenAPI spec found automatically (tried: {tried}). Pass --spec explicitly.",
            file=sys.stderr,
        )
        sys.exit(2)

    spec = input(
        f"No OpenAPI spec found automatically (tried: {tried}).\n"
        "Enter the path to your spec, relative to the repo root: "
    ).strip()
    if not spec:
        print("No spec path entered.", file=sys.stderr)
        sys.exit(2)
    return spec


def cmd_init(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    config_path = repo_root / ".local" / "cats" / "config.yaml"

    if config_path.exists() and not args.force:
        print(config_path)
        sys.exit(0)

    spec = args.spec or _discover_spec(repo_root, non_interactive=args.non_interactive)
    server = args.server
    health_url = args.health_url or server
    results_dir = args.results_dir
    rules = args.rules

    config_text = render_init_config(
        spec=spec, server=server, health_url=health_url,
        results_dir=results_dir, rules=rules,
    )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(config_text)
    print(f"Wrote {config_path}")

    rules_path = repo_root / rules
    if rules_path.exists():
        print(f"Rules file already exists, left untouched: {rules_path}")
    else:
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(INITIAL_RULES_YAML)
        print(f"Wrote {rules_path}")

    results_path = repo_root / results_dir
    results_path.mkdir(parents=True, exist_ok=True)

    gitignore_line = results_dir.rstrip("/") + "/"
    print()
    print("Add this line to your .gitignore (not done automatically):")
    print(f"  {gitignore_line}")
    print()
    print(
        f"IMPORTANT: identities.default.token_cmd is a placeholder ({DEFAULT_TOKEN_CMD!r}). "
        "Nothing will work — not even `doctor`'s health check working around it — "
        "until you replace it with a real command that prints a bearer token on stdout."
    )


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

_VERSION_NUMBER = re.compile(r"\d+\.\d+\.\d+")


def _cats_version() -> str | None:
    """Best-effort summary of `cats --version`; None if cats is unavailable.

    The real CATS binary prints a decorative ASCII banner before the actual
    version line, so "the first non-empty line" (naively) returns banner noise
    instead of a version. Prefer a line that looks like it contains a semver
    number; fall back to the first non-empty line for --version output that
    doesn't follow that shape at all.
    """
    try:
        proc = subprocess.run(["cats", "--version"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    lines = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    for line in lines:
        if _VERSION_NUMBER.search(line):
            return line
    return lines[0] if lines else None


def cmd_doctor(args: argparse.Namespace) -> None:
    config = load()
    checks: list[tuple[str, bool, str]] = []

    if config.spec.exists():
        checks.append(("spec", True, str(config.spec)))
    else:
        checks.append(("spec", False, f"not found: {config.spec}"))

    cats_path = shutil.which("cats")
    if cats_path is None:
        checks.append((
            "cats binary", False,
            "not found on PATH; install CATS (https://github.com/Endava/cats)",
        ))
    else:
        version = _cats_version()
        checks.append(("cats binary", True, version or f"found at {cats_path} (version unknown)"))

    try:
        rules = load_rules(config.false_positives)
    except RuleError as exc:
        checks.append(("rules", False, str(exc)))
    else:
        checks.append(("rules", True, f"{len(rules)} rule(s) in {config.false_positives}"))

    try:
        with urllib.request.urlopen(config.health_url, timeout=5):
            pass
    except urllib.error.HTTPError as exc:
        detail = (f"{config.health_url} responded with HTTP {exc.code}; "
                  "check that health_url points at a working endpoint")
        checks.append(("server health", False, detail))
    except (urllib.error.URLError, OSError) as exc:
        checks.append(("server health", False, f"server is not running at {config.health_url} ({exc})"))
    else:
        checks.append(("server health", True, config.health_url))

    all_ok = True
    for name, passed, detail in checks:
        mark = "✓" if passed else "✗"
        print(f"{mark} {name}: {detail}")
        all_ok = all_ok and passed

    sys.exit(0 if all_ok else 1)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _print_run_summary(result) -> None:
    print(f"run_id: {result.run_id}")
    print(f"db: {result.db_path}")

    if result.parse_stats is None:
        print("(parse skipped; no result summary available)")
        return

    print(f"parsed: {result.parse_stats.processed} processed, "
          f"{result.parse_stats.skipped} skipped, {result.parse_stats.errors} errors")

    conn = sqlite3.connect(result.db_path)
    conn.row_factory = sqlite3.Row
    try:
        print("\nResults by type:")
        rows = conn.execute(
            "SELECT rt.name AS result, COUNT(*) AS count FROM tests t "
            "JOIN result_types rt ON t.result_type_id = rt.id "
            "GROUP BY rt.name ORDER BY count DESC"
        ).fetchall()
        print_table(["result", "count"], [(r["result"], r["count"]) for r in rows])

        fp_total = conn.execute(
            "SELECT COUNT(*) FROM tests WHERE is_false_positive = 1"
        ).fetchone()[0]
        print(f"\nFalse positives: {fp_total}")

        print("\nTop 10 true-positive paths:")
        rows = conn.execute(
            "SELECT path, COUNT(*) AS count FROM true_positives_view "
            "GROUP BY path ORDER BY count DESC LIMIT 10"
        ).fetchall()
        print_table(["path", "count"], [(r["path"], r["count"]) for r in rows])
    finally:
        conn.close()


def cmd_run(args: argparse.Namespace) -> None:
    config = load()
    result = execute(
        config,
        identity_name=args.identity,
        path_filter=args.path,
        rate=args.rate,
        blackbox=args.blackbox,
        skip_seed=args.skip_seed,
        skip_parse=args.skip_parse,
    )
    _print_run_summary(result)
    sys.exit(result.cats_exit_code)


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> None:
    config = load()
    report_dir = Path(args.report)
    if not report_dir.is_dir():
        print(f"Report directory not found: {report_dir}", file=sys.stderr)
        sys.exit(2)

    run_id = run_id_for(datetime.now(timezone.utc))
    if args.db:
        db_path = Path(args.db)
        db_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        config.results_dir.mkdir(parents=True, exist_ok=True)
        db_path = config.results_dir / f"cats-results-{run_id}.db"

    stats = parse_report(report_dir, db_path, {"run_id": run_id})
    print(f"db: {db_path}")
    print(f"processed: {stats.processed}")
    print(f"skipped: {stats.skipped}")
    print(f"errors: {stats.errors}")


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------

def cmd_classify(args: argparse.Namespace) -> None:
    config = load()
    db_path = resolve_db(config, args.db)
    rules = load_rules(config.false_positives)

    target = db_path
    tmp_path: Path | None = None
    if args.dry_run:
        fd, tmp_name = tempfile.mkstemp(prefix="cats-classify-dryrun-", suffix=".db")
        os.close(fd)
        tmp_path = Path(tmp_name)
        shutil.copyfile(db_path, tmp_path)
        target = tmp_path

    try:
        result = classify_db(target, rules, allow_5xx=config.allow_suppressing_5xx)
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    if args.dry_run:
        print(f"(dry run against a copy of {db_path}; original database not modified)\n")

    print(f"flagged: {result.flagged} / {result.total}")

    if result.by_rule:
        print("\nBy rule:")
        print_table(
            ["rule_id", "matches"],
            sorted(result.by_rule.items(), key=lambda kv: kv[1], reverse=True),
        )

    zero_match = [r.id for r in rules if r.id not in result.by_rule]
    if zero_match:
        print("\nZero-match rules:")
        for rule_id in zero_match:
            print(f"  {rule_id}")

    _print_capped("\nNewly suppressed", result.newly_suppressed)
    _print_capped("\nNewly surfaced", result.newly_surfaced)

    if result.violations:
        print(f"\n{len(result.violations)} rule match(es) refused for hitting a 5xx response:")
        for rule_id, test_id in result.violations[:DELTA_CAP]:
            print(f"  {rule_id}: {test_id}")
        if len(result.violations) > DELTA_CAP:
            print(f"  ... and {len(result.violations) - DELTA_CAP} more")
        sys.exit(1)


# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------

def _query_canned(conn: sqlite3.Connection) -> None:
    print("Summary (excluding false positives):")
    print_table(
        ["result", "count", "percentage"],
        conn.execute(
            """
            SELECT rt.name, COUNT(*), ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2)
            FROM tests t
            JOIN result_types rt ON t.result_type_id = rt.id
            WHERE t.is_false_positive = 0
            GROUP BY rt.name
            ORDER BY COUNT(*) DESC
            """
        ).fetchall(),
    )

    print("\nFalse positives:")
    fp_count = conn.execute("SELECT COUNT(*) FROM tests WHERE is_false_positive = 1").fetchone()[0]
    print(f"  {fp_count}")

    print("\nErrors by path (top 10, true positives only):")
    print_table(
        ["path", "error_count", "fuzzers"],
        conn.execute(
            """
            SELECT p.path, COUNT(*), GROUP_CONCAT(DISTINCT f.name)
            FROM tests t
            JOIN result_types rt ON t.result_type_id = rt.id
            JOIN paths p ON t.path_id = p.id
            JOIN fuzzers f ON t.fuzzer_id = f.id
            WHERE rt.name = 'error' AND t.is_false_positive = 0
            GROUP BY p.path
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """
        ).fetchall(),
    )

    print("\nWarnings by path (top 10, true positives only):")
    print_table(
        ["path", "warn_count"],
        conn.execute(
            """
            SELECT p.path, COUNT(*)
            FROM tests t
            JOIN result_types rt ON t.result_type_id = rt.id
            JOIN paths p ON t.path_id = p.id
            WHERE rt.name = 'warn' AND t.is_false_positive = 0
            GROUP BY p.path
            ORDER BY COUNT(*) DESC
            LIMIT 10
            """
        ).fetchall(),
    )


def cmd_query(args: argparse.Namespace) -> None:
    config = load()
    db_path = resolve_db(config, args.db)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if args.sql:
            try:
                cur = conn.execute(args.sql)
            except sqlite3.Error as exc:
                print(f"SQL error: {exc}", file=sys.stderr)
                sys.exit(2)
            rows = cur.fetchall()
            if args.json:
                print(json.dumps([dict(row) for row in rows], indent=2, default=str))
            else:
                headers = [d[0] for d in cur.description] if cur.description else []
                print_table(headers, [tuple(row) for row in rows])
        else:
            _query_canned(conn)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def cmd_report(args: argparse.Namespace) -> None:
    try:
        from catslib import report as reporting
    except ImportError as exc:
        print(
            "cats_tool.py report requires catslib.report, which isn't available yet "
            f"in this checkout ({exc}).",
            file=sys.stderr,
        )
        sys.exit(2)

    config = load()
    db_path = resolve_db(config, args.db)
    html = reporting.render_html(db_path)

    if args.out:
        out = Path(args.out)
    else:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT run_id FROM run_meta").fetchone()
        finally:
            conn.close()
        run_id = row[0] if row and row[0] else "unknown"
        out = config.results_dir / f"report-{run_id}.html"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"report: {out}")

    if args.open:
        webbrowser.open(out.resolve().as_uri())


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cats_tool.py",
        description="Run, parse, classify, query and report CATS API fuzz results.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="Create .local/cats/config.yaml for this repo")
    p_init.add_argument("--spec")
    p_init.add_argument("--server", default=DEFAULT_SERVER)
    p_init.add_argument("--health-url")
    p_init.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    p_init.add_argument("--rules", default=DEFAULT_RULES)
    p_init.add_argument("--non-interactive", action="store_true")
    p_init.add_argument("--force", action="store_true")
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="Run a CATS fuzzing campaign")
    p_run.add_argument("--identity")
    p_run.add_argument("--path")
    p_run.add_argument("--rate", type=int)
    p_run.add_argument("--blackbox", action="store_true")
    p_run.add_argument("--skip-seed", action="store_true")
    p_run.add_argument("--skip-parse", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_parse = sub.add_parser("parse", help="Parse a CATS report directory into SQLite")
    p_parse.add_argument("--report", required=True)
    p_parse.add_argument("--db")
    p_parse.set_defaults(func=cmd_parse)

    p_classify = sub.add_parser("classify", help="Apply false-positive rules to a database")
    p_classify.add_argument("--db")
    p_classify.add_argument("--dry-run", action="store_true")
    p_classify.set_defaults(func=cmd_classify)

    p_query = sub.add_parser("query", help="Query a results database")
    p_query.add_argument("--db")
    p_query.add_argument("--sql")
    p_query.add_argument("--json", action="store_true")
    p_query.set_defaults(func=cmd_query)

    p_report = sub.add_parser("report", help="Render a self-contained HTML report")
    p_report.add_argument("--db")
    p_report.add_argument("--out")
    p_report.add_argument("--open", action="store_true")
    p_report.set_defaults(func=cmd_report)

    p_doctor = sub.add_parser("doctor", help="Check the environment is ready to fuzz")
    p_doctor.set_defaults(func=cmd_doctor)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except (ConfigError, RuleError, ClassifyError, HookError, PreflightError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
