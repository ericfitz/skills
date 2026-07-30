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
import shutil
import sqlite3
import sys
import tempfile
import webbrowser
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from catslib import report as reporting
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
from catslib.runner import (
    FixtureError,
    HookError,
    PreflightError,
    RunResult,
    checks,
    execute,
    prune_run_dbs,
    run_id_for,
)

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


def print_table(headers: list[str], rows: Sequence[Sequence[object]]) -> None:
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


def _human_bytes(n: int) -> str:
    """Format a byte count as e.g. '4.2 GB' (binary units, one decimal place)."""
    if n < 1024:
        return f"{n} B"
    size = float(n)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{size:.1f} TB"  # unreachable, satisfies static analysis


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


def open_results_db(path: Path) -> sqlite3.Connection:
    """Open a CATS results database read-only, or exit 2 with a clean message.

    `resolve_db` only checks that *some* file exists at the path — a stale,
    truncated, or plain-wrong `--db` still reaches here. Without this guard, the
    first query against it (in `query`, `report`, or the post-`run` summary) would
    surface as a raw sqlite3 traceback instead of an actionable message; read-only
    mode additionally means a destructive `--sql` (e.g. `DROP TABLE tests`) fails
    the same clean way instead of corrupting a database — possibly the shared
    `latest.db` — that other commands depend on.
    """
    try:
        # Path.as_uri() percent-encodes reserved characters (spaces, '?', '#', ...)
        # that a raw f-string would pass through unescaped and sqlite3's URI parser
        # would then misinterpret as query-string syntax.
        uri = path.resolve().as_uri() + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        tables = {
            row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    except sqlite3.Error as exc:
        print(f"{path}: not a valid CATS results database ({exc})", file=sys.stderr)
        sys.exit(2)
    if "run_meta" not in tables:
        conn.close()
        print(
            f"{path}: no run_meta table — not created by catslib.parse.create_schema",
            file=sys.stderr,
        )
        sys.exit(2)
    return conn


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

    prompt = (
        f"No OpenAPI spec found automatically (tried: {tried}).\n"
        "Enter the path to your spec, relative to the repo root: "
    )
    while True:
        spec = input(prompt).strip()
        if not spec:
            print("No spec path entered.", file=sys.stderr)
            sys.exit(2)
        if (repo_root / spec).exists():
            return spec
        print(f"{repo_root / spec} does not exist. Try again, or Ctrl-C to cancel.", file=sys.stderr)
        prompt = "Enter the path to your spec, relative to the repo root: "


def cmd_init(args: argparse.Namespace) -> None:
    repo_root = Path.cwd()
    config_path = repo_root / ".local" / "cats" / "config.yaml"

    if config_path.exists() and not args.force:
        print(f"{config_path} already exists; pass --force to overwrite.")
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

def cmd_doctor(args: argparse.Namespace) -> None:
    """Print every environment check runner.checks() knows about, ✓ or ✗, and
    exit 1 if any failed. Deliberately does NOT call runner.preflight() — that
    function is fail-fast (raises on the first failing check) by design for
    `run`, so it physically cannot produce a full report. Both this and
    `preflight` are built from the same `runner.checks()` so they can't drift on
    wording or on what counts as "ready"."""
    config = load()
    all_ok = True
    for name, passed, detail in checks(config):
        mark = "✓" if passed else "✗"
        print(f"{mark} {name}: {detail}")
        all_ok = all_ok and passed

    sys.exit(0 if all_ok else 1)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

def _print_run_summary(result: RunResult) -> None:
    print(f"run_id: {result.run_id}")
    print(f"db: {result.db_path}")

    if result.parse_stats is None:
        print("(parse skipped; no result summary available)")
        return

    print(f"parsed: {result.parse_stats.processed} processed, "
          f"{result.parse_stats.skipped} skipped, {result.parse_stats.errors} errors")

    # Derived from reporting.summary() rather than its own queries so the printed
    # summary and the HTML report can't drift on the same numbers (they briefly
    # did: this used to run a top-10, no-fuzzer-column path query while report.py
    # ran a top-25 query with GROUP_CONCAT(DISTINCT fuzzer)). Trimmed to the
    # summary's top 10 paths here, dropping the fuzzer column, purely for
    # terminal width — the underlying data is the one true_positives_by_path list.
    data = reporting.summary(result.db_path)

    print("\nResults by type:")
    print_table(
        ["result", "count"],
        sorted(data["by_result"].items(), key=lambda kv: kv[1], reverse=True),
    )

    print(f"\nFalse positives: {data['false_positive_total']}")

    print("\nTop 10 true-positive paths:")
    print_table(
        ["path", "count"],
        [(r["path"], r["count"]) for r in data["true_positives_by_path"][:10]],
    )


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
        allow_port_forward=args.allow_port_forward,
        no_prune=args.no_prune,
    )
    _print_run_summary(result)

    if result.connection_errors is not None and result.total_tests:
        pct = 100.0 * result.connection_errors / result.total_tests
        print(
            f"\nConnection errors (code 953/999): {result.connection_errors} / "
            f"{result.total_tests} ({pct:.2f}%)"
        )

    if result.unauthenticated is not None and result.total_tests:
        pct = 100.0 * result.unauthenticated / result.total_tests
        print(
            f"Unauthenticated (non-false-positive 401): {result.unauthenticated} / "
            f"{result.total_tests} ({pct:.2f}%)"
        )

    if result.dead_fixtures:
        print(
            f"Fixtures destroyed by this campaign: {len(result.dead_fixtures)} "
            "(see RUN INVALID below)"
        )

    if result.pruned:
        print(
            f"\nPruned {len(result.pruned)} old run database(s), reclaimed "
            f"{_human_bytes(result.pruned_bytes)} (keep_runs: {config.keep_runs})"
        )

    reasons = result.contamination_reasons
    if reasons:
        detail = "\n".join(f"  - {reason}" for reason in reasons)
        print(
            f"\nRUN INVALID:\n{detail}\n"
            "Per-rule and per-path conclusions from this run are meaningless. "
            f"{result.db_path} was NOT made latest.db. Fix the cause and re-run.",
            file=sys.stderr,
        )
        sys.exit(3)

    sys.exit(result.cats_exit_code)


# ---------------------------------------------------------------------------
# prune
# ---------------------------------------------------------------------------

def cmd_prune(args: argparse.Namespace) -> None:
    """Standalone pruning of old per-run databases, outside a `run` invocation.

    Uses the same candidate regex and latest.db-target protection as the
    pruning `run` does automatically after a successful campaign (see
    `runner.prune_run_dbs`) — this is just a manually-triggered pass over
    whatever `results_dir` already holds.
    """
    config = load()
    keep = args.keep if args.keep is not None else config.keep_runs

    # Always preview first (dry_run=True never deletes) so file sizes can be
    # stat'd while the candidates still exist — once the real pass unlinks
    # them there is nothing left to stat.
    candidates = prune_run_dbs(config.results_dir, keep, dry_run=True)
    sizes: dict[Path, int] = {}
    for p in candidates:
        try:
            sizes[p] = p.stat().st_size
        except OSError:
            sizes[p] = 0
    total_bytes = sum(sizes.values())

    if not candidates:
        print(f"Nothing to prune (keep_runs: {keep}).")
        return

    verb = "Would delete" if args.dry_run else "Deleted"
    if not args.dry_run:
        prune_run_dbs(config.results_dir, keep)

    for p in candidates:
        print(f"{verb} {p.name} ({_human_bytes(sizes[p])})")
    print(f"\nTotal: {len(candidates)} database(s), {_human_bytes(total_bytes)} (keep_runs: {keep})")


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------

def cmd_parse(args: argparse.Namespace) -> None:
    config = load()
    report_dir = Path(args.report)
    if not report_dir.is_dir():
        print(f"Report directory not found: {report_dir}", file=sys.stderr)
        sys.exit(2)

    run_id = run_id_for(datetime.now(UTC))
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
    # --rules overrides the configured false-positives file for this invocation only —
    # config.false_positives (and the file on disk) is never written to. This is what
    # lets a caller dry-run a draft rule before it's ever added to the committed rules
    # file: point --rules at a scratch copy, and nothing here touches the real one.
    rules_path = Path(args.rules) if args.rules else config.false_positives
    rules = load_rules(rules_path)

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
    if args.json and not args.sql:
        print("--json requires --sql (the canned summaries are text-table only).", file=sys.stderr)
        sys.exit(2)

    config = load()
    db_path = resolve_db(config, args.db)
    conn = open_results_db(db_path)
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
    config = load()
    db_path = resolve_db(config, args.db)

    # open_results_db validates the DB and exits 2 with a clean message on a bad
    # one; reporting.render_html can't do that itself (it's a library, not a CLI
    # command, so it never calls sys.exit) — without this, a malformed --db would
    # surface as a raw sqlite3 traceback instead. Also doubles as the source for
    # the default output filename below, so the DB is only opened once here.
    conn = open_results_db(db_path)
    try:
        run_id_row = conn.execute("SELECT run_id FROM run_meta").fetchone()
    finally:
        conn.close()

    html = reporting.render_html(db_path)

    if args.out:
        out = Path(args.out)
    else:
        run_id = run_id_row[0] if run_id_row and run_id_row[0] else "unknown"
        out = config.results_dir / f"report-{run_id}.html"

    out.parent.mkdir(parents=True, exist_ok=True)
    # Explicit encoding: the document declares <meta charset="utf-8">, and without
    # this, write_text falls back to the locale's encoding — under a non-UTF-8
    # locale a fuzzer payload with exotic Unicode would either raise
    # UnicodeEncodeError or write bytes that contradict the declared charset.
    out.write_text(html, encoding="utf-8")
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
    p_run.add_argument(
        "--allow-port-forward", action="store_true",
        help="Permit fuzzing through a kubectl port-forward (normally a fatal preflight error)",
    )
    p_run.add_argument(
        "--no-prune", action="store_true",
        help="Skip pruning old run databases for this invocation, regardless of keep_runs",
    )
    p_run.set_defaults(func=cmd_run)

    p_parse = sub.add_parser("parse", help="Parse a CATS report directory into SQLite")
    p_parse.add_argument("--report", required=True)
    p_parse.add_argument("--db")
    p_parse.set_defaults(func=cmd_parse)

    p_classify = sub.add_parser("classify", help="Apply false-positive rules to a database")
    p_classify.add_argument("--db")
    p_classify.add_argument(
        "--rules",
        help="Classify against this rules file instead of the one in config.yaml "
             "(does not modify config.yaml or the configured rules file)",
    )
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

    p_prune = sub.add_parser("prune", help="Delete old run databases beyond keep_runs")
    p_prune.add_argument("--keep", type=int, help="Override config.yaml's keep_runs for this run")
    p_prune.add_argument("--dry-run", action="store_true")
    p_prune.set_defaults(func=cmd_prune)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    # sqlite3.Error closes this off at the class level rather than per call site.
    # open_results_db() already guards the call sites that go through it with a
    # more specific, better-worded message; this is the backstop for the rest —
    # e.g. reporting.summary()/render_html(), reached via report._connect(), which
    # can't call sys.exit itself since it's a library, not a CLI command — so a
    # malformed database doesn't traceback wherever it's touched next.
    except (
        ConfigError, RuleError, ClassifyError, FixtureError, HookError, PreflightError,
        sqlite3.Error,
    ) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        # main() already turns the five typed library errors into a clean message;
        # this catches only a truncated pipe (e.g. `cats_tool.py query | head`), so
        # that doesn't end in a traceback on stdout write. Python flushes stdout at
        # exit, so the closed pipe has to be replaced before exiting or the flush
        # itself re-raises the same error.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)
