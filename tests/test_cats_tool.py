import argparse
import io
import json
import os
import sqlite3
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cats_tool as CT
from cats_fixtures import _tmp_dir, cats_json, make_config
from catslib import config as cfg
from catslib import parse as P
from catslib import runner as run
from catslib.classify import ClassifyError
from catslib.rules import RuleError


def make_db(case: unittest.TestCase, config) -> Path:
    """Parse one Test*.json into a real database under config.results_dir."""
    report = _tmp_dir(case)
    (report / "Test1.json").write_text(json.dumps(cats_json()))
    db = config.results_dir / "cats-results-R1.db"
    config.results_dir.mkdir(parents=True, exist_ok=True)
    P.parse_report(report, db, {"run_id": "R1"})
    return db


class TestResolveDb(unittest.TestCase):
    def test_missing_latest_exits_2(self):
        config = make_config(self)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(SystemExit) as ctx:
            CT.resolve_db(config, None)
        self.assertEqual(ctx.exception.code, 2)

    def test_latest_resolves_through_symlink(self):
        config = make_config(self)
        db = make_db(self, config)
        (config.results_dir / "latest.db").symlink_to(db.name)
        resolved = CT.resolve_db(config, "latest")
        self.assertEqual(resolved, db.resolve())

    def test_explicit_missing_path_exits_2(self):
        config = make_config(self)
        with self.assertRaises(SystemExit) as ctx:
            CT.resolve_db(config, str(config.results_dir / "nope.db"))
        self.assertEqual(ctx.exception.code, 2)

    def test_explicit_existing_path_returned(self):
        config = make_config(self)
        db = make_db(self, config)
        self.assertEqual(CT.resolve_db(config, str(db)), db)


class TestOpenResultsDb(unittest.TestCase):
    """Critical fix: resolve_db only checks that *some* file exists — a stale,
    truncated, or plain-wrong --db must not reach a raw sqlite3 traceback the
    first time a query touches it."""

    def test_non_sqlite_file_fails_cleanly(self):
        garbage = _tmp_dir(self) / "garbage.db"
        garbage.write_text("this is not a sqlite database")
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            CT.open_results_db(garbage)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("not a valid CATS results database", err.getvalue())

    def test_sqlite_db_without_run_meta_fails_cleanly(self):
        bogus = _tmp_dir(self) / "bogus.db"
        conn = sqlite3.connect(bogus)
        conn.execute("CREATE TABLE foo (x int)")
        conn.commit()
        conn.close()
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            CT.open_results_db(bogus)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("no run_meta table", err.getvalue())

    def test_valid_db_opens_read_only(self):
        config = make_config(self)
        db = make_db(self, config)
        conn = CT.open_results_db(db)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tests").fetchone()[0], 1)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DROP TABLE tests")
        finally:
            conn.close()


class TestClassifyDryRun(unittest.TestCase):
    def test_original_db_untouched(self):
        config = make_config(self)
        db = make_db(self, config)
        before = db.read_bytes()

        args = argparse.Namespace(db=str(db), dry_run=True, rules=None)
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(io.StringIO()):
            CT.cmd_classify(args)

        self.assertEqual(db.read_bytes(), before, "dry-run classify must not mutate the real database")

    def test_dry_run_still_reports_flagged_count(self):
        config = make_config(self)
        root = config.repo_root
        (root / "fp.yaml").write_text(
            "version: 1\nrules:\n  - id: R1\n    why: test\n    when: {response_code: 400}\n"
        )
        db = make_db(self, config)

        args = argparse.Namespace(db=str(db), dry_run=True, rules=None)
        out = io.StringIO()
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(out):
            CT.cmd_classify(args)
        self.assertIn("flagged: 1 / 1", out.getvalue())

    def test_non_dry_run_mutates_db(self):
        config = make_config(self)
        root = config.repo_root
        (root / "fp.yaml").write_text(
            "version: 1\nrules:\n  - id: R1\n    why: test\n    when: {response_code: 400}\n"
        )
        db = make_db(self, config)
        before = db.read_bytes()

        args = argparse.Namespace(db=str(db), dry_run=False, rules=None)
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(io.StringIO()):
            CT.cmd_classify(args)

        self.assertNotEqual(db.read_bytes(), before)

    def test_dry_run_with_rules_override_touches_neither_db_nor_configured_rules(self):
        """--rules lets a caller classify against a draft rules file — e.g. one rule
        not yet added anywhere — without writing to config.false_positives (fp.yaml)
        or the real database, even in a real (non-dry-run) sense for the rules file:
        classify never writes rules files at all, only --db does the dry-run copy."""
        config = make_config(self)
        root = config.repo_root
        db = make_db(self, config)
        before_db = db.read_bytes()
        before_configured_rules = (root / "fp.yaml").read_text()

        draft = root / "draft-rules.yaml"
        draft.write_text(
            "version: 1\nrules:\n  - id: DRAFT\n    why: test\n    when: {response_code: 400}\n"
        )

        args = argparse.Namespace(db=str(db), dry_run=True, rules=str(draft))
        out = io.StringIO()
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(out):
            CT.cmd_classify(args)

        self.assertIn("flagged: 1 / 1", out.getvalue())
        self.assertIn("DRAFT", out.getvalue())
        self.assertEqual(db.read_bytes(), before_db, "dry-run must not mutate the real database")
        self.assertEqual(
            (root / "fp.yaml").read_text(), before_configured_rules,
            "--rules must not modify the configured rules file",
        )


class TestTypedErrorsReachExit2(unittest.TestCase):
    """Every typed error from the five library modules must become a clean stderr
    message and exit(2) through main()'s central dispatch, never a traceback."""

    def _run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(sys, "argv", ["cats_tool.py", *argv]),
            redirect_stdout(out),
            redirect_stderr(err),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.main()
        return ctx.exception.code, err.getvalue()

    def test_config_error(self):
        with mock.patch.object(CT, "load", side_effect=cfg.ConfigError("boom config")):
            code, err = self._run_main(["doctor"])
        self.assertEqual(code, 2)
        self.assertIn("boom config", err)

    def test_rule_error(self):
        config = make_config(self)
        db = make_db(self, config)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "load_rules", side_effect=RuleError("boom rules")),
        ):
            code, err = self._run_main(["classify", "--db", str(db)])
        self.assertEqual(code, 2)
        self.assertIn("boom rules", err)

    def test_rule_error_from_rules_override_names_the_override_file(self):
        """A malformed --rules file must exit 2 through load_rules' real (unmocked)
        validation, naming the override path — not the configured false_positives
        path — since that's the file the caller actually pointed at."""
        config = make_config(self)
        db = make_db(self, config)
        bad_rules = config.repo_root / "bad-draft.yaml"
        bad_rules.write_text("version: 1\nrules:\n  - id: BAD\n    why: test\n")  # no when/any_of
        with mock.patch.object(CT, "load", return_value=config):
            code, err = self._run_main(["classify", "--db", str(db), "--rules", str(bad_rules)])
        self.assertEqual(code, 2)
        self.assertIn(str(bad_rules), err)

    def test_classify_error(self):
        config = make_config(self)
        db = make_db(self, config)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "classify_db", side_effect=ClassifyError("boom classify")),
        ):
            code, err = self._run_main(["classify", "--db", str(db)])
        self.assertEqual(code, 2)
        self.assertIn("boom classify", err)

    def test_hook_error(self):
        config = make_config(self)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "execute", side_effect=run.HookError("boom hook")),
        ):
            code, err = self._run_main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("boom hook", err)

    def test_preflight_error(self):
        config = make_config(self)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "execute", side_effect=run.PreflightError("boom preflight")),
        ):
            code, err = self._run_main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("boom preflight", err)

    def test_sqlite_error_from_run_summary(self):
        """A malformed database reached via a path that does NOT go through
        open_results_db (here: _print_run_summary -> reporting.summary() ->
        report._connect(), all inside cmd_run) must still exit 2, not traceback.
        Regression test for the class of bug fixed twice at two call sites
        (cmd_report directly, and here via the summary() rewiring) before being
        closed once at main()'s except tuple."""
        config = make_config(self)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        bad_db = config.results_dir / "bad.db"
        bad_db.write_text("not a real sqlite database")
        result = run.RunResult(
            run_id="R1", db_path=bad_db, report_dir=config.results_dir,
            cats_exit_code=0, parse_stats=P.ParseStats(processed=1), classify_result=None,
        )
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "execute", return_value=result),
        ):
            code, err = self._run_main(["run"])
        self.assertEqual(code, 2)
        # This backstop is intentionally less specific than open_results_db's
        # per-site guard (no path prefix) — it's just sqlite3's own message.
        self.assertIn("file is not a database", err)


class TestQueryCleanErrors(unittest.TestCase):
    """The `query` default (canned-summary) branch is the path a stale or
    mistyped --db actually hits; the --sql branch was already guarded."""

    def test_query_on_non_sqlite_db_exits_2_cleanly(self):
        config = make_config(self)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        garbage = config.results_dir / "garbage.db"
        garbage.write_text("nope")

        args = argparse.Namespace(db=str(garbage), sql=None, json=False)
        err = io.StringIO()
        with (
            mock.patch.object(CT, "load", return_value=config),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_query(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("not a valid CATS results database", err.getvalue())

    def test_query_on_non_catslib_db_exits_2_cleanly(self):
        config = make_config(self)
        config.results_dir.mkdir(parents=True, exist_ok=True)
        bogus = config.results_dir / "bogus.db"
        conn = sqlite3.connect(bogus)
        conn.execute("CREATE TABLE foo (x int)")
        conn.commit()
        conn.close()

        args = argparse.Namespace(db=str(bogus), sql=None, json=False)
        err = io.StringIO()
        with (
            mock.patch.object(CT, "load", return_value=config),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_query(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("no run_meta table", err.getvalue())

    def test_destructive_sql_fails_cleanly_and_db_is_unmodified(self):
        config = make_config(self)
        db = make_db(self, config)
        before = db.read_bytes()

        args = argparse.Namespace(db=str(db), sql="DROP TABLE tests", json=False)
        err = io.StringIO()
        with (
            mock.patch.object(CT, "load", return_value=config),
            redirect_stdout(io.StringIO()),
            redirect_stderr(err),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_query(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("SQL error", err.getvalue())
        self.assertEqual(db.read_bytes(), before, "query must open the database read-only")

    def test_json_without_sql_rejected(self):
        args = argparse.Namespace(db=None, sql=None, json=True)
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            CT.cmd_query(args)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("--json requires --sql", err.getvalue())

    def test_json_with_sql_still_works(self):
        config = make_config(self)
        db = make_db(self, config)
        args = argparse.Namespace(db=str(db), sql="SELECT COUNT(*) AS n FROM tests", json=True)
        out = io.StringIO()
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(out):
            CT.cmd_query(args)
        self.assertEqual(json.loads(out.getvalue()), [{"n": 1}])


class TestDoctorUsesSharedChecks(unittest.TestCase):
    """doctor must be a thin printer over runner.checks(), not an independent
    reimplementation — otherwise the two silently drift, as they had before."""

    def test_prints_every_check_and_exits_1_on_any_failure(self):
        config = make_config(self)
        fake_checks = [("a", True, "ok"), ("b", False, "bad detail")]
        out = io.StringIO()
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "checks", return_value=fake_checks),
            redirect_stdout(out),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_doctor(argparse.Namespace())
        self.assertEqual(ctx.exception.code, 1)
        self.assertIn("✓ a: ok", out.getvalue())
        self.assertIn("✗ b: bad detail", out.getvalue())

    def test_exits_0_when_all_pass(self):
        config = make_config(self)
        fake_checks = [("a", True, "ok")]
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "checks", return_value=fake_checks),
            redirect_stdout(io.StringIO()),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_doctor(argparse.Namespace())
        self.assertEqual(ctx.exception.code, 0)


class TestDiscoverSpec(unittest.TestCase):
    def test_single_match_used(self):
        root = _tmp_dir(self)
        (root / "openapi.json").write_text("{}")
        self.assertEqual(CT._discover_spec(root, non_interactive=True), "openapi.json")

    def test_multiple_matches_exit_2(self):
        root = _tmp_dir(self)
        (root / "docs").mkdir()
        (root / "docs" / "openapi.json").write_text("{}")
        (root / "docs" / "openapi-v2.json").write_text("{}")
        err = io.StringIO()
        with redirect_stderr(err), self.assertRaises(SystemExit) as ctx:
            CT._discover_spec(root, non_interactive=True)
        self.assertEqual(ctx.exception.code, 2)
        self.assertIn("Multiple OpenAPI spec candidates", err.getvalue())

    def test_no_matches_non_interactive_exits_2(self):
        root = _tmp_dir(self)
        with self.assertRaises(SystemExit) as ctx:
            CT._discover_spec(root, non_interactive=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_interactive_prompt_accepts_existing_path(self):
        root = _tmp_dir(self)
        (root / "my").mkdir()
        (root / "my" / "spec.json").write_text("{}")
        with mock.patch("builtins.input", return_value="my/spec.json"):
            self.assertEqual(CT._discover_spec(root, non_interactive=False), "my/spec.json")

    def test_interactive_reprompts_on_nonexistent_path(self):
        root = _tmp_dir(self)
        (root / "real.json").write_text("{}")
        with mock.patch("builtins.input", side_effect=["missing.json", "real.json"]):
            self.assertEqual(CT._discover_spec(root, non_interactive=False), "real.json")


class TestCmdInit(unittest.TestCase):
    def _chdir(self, path: Path) -> None:
        cwd = os.getcwd()
        os.chdir(path)
        self.addCleanup(os.chdir, cwd)

    def _args(self, **over):
        base = {
            "spec": None, "server": CT.DEFAULT_SERVER, "health_url": None,
            "results_dir": CT.DEFAULT_RESULTS_DIR, "rules": CT.DEFAULT_RULES,
            "non_interactive": True, "force": False,
        }
        base.update(over)
        return argparse.Namespace(**base)

    def test_writes_config_rules_and_results_dir(self):
        root = _tmp_dir(self)
        (root / "openapi.json").write_text("{}")
        self._chdir(root)

        with redirect_stdout(io.StringIO()):
            CT.cmd_init(self._args())

        config_path = root / ".local" / "cats" / "config.yaml"
        self.assertTrue(config_path.exists())
        loaded = cfg.load_config(config_path)
        self.assertEqual(loaded.server, CT.DEFAULT_SERVER)

        rules_path = root / CT.DEFAULT_RULES
        self.assertTrue(rules_path.exists())
        self.assertTrue((root / CT.DEFAULT_RESULTS_DIR).is_dir())

    def test_existing_config_without_force_exits_0_and_leaves_it(self):
        root = _tmp_dir(self)
        (root / "openapi.json").write_text("{}")
        self._chdir(root)
        config_path = root / ".local" / "cats" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("sentinel")

        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            CT.cmd_init(self._args())
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(config_path.read_text(), "sentinel")
        self.assertIn("already exists", out.getvalue())
        self.assertIn("--force", out.getvalue())

    def test_no_spec_non_interactive_exits_2(self):
        root = _tmp_dir(self)
        self._chdir(root)
        with (
            redirect_stdout(io.StringIO()),
            redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as ctx,
        ):
            CT.cmd_init(self._args())
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
