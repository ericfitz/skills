import argparse
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

import cats_tool as CT
from catslib import config as cfg
from catslib import parse as P
from catslib import runner as run
from catslib.classify import ClassifyError
from catslib.rules import RuleError

CONFIG = """
version: 1
spec: openapi.json
server: http://localhost:8080
results_dir: results
false_positives: fp.yaml
identities:
  admin: {token_cmd: "echo tok"}
default_identity: admin
"""

CATS_JSON = {
    "testId": "Test 1", "traceId": "t-1", "fuzzer": "HappyPath",
    "path": "/things", "contractPath": "/things", "scenario": "s",
    "expectedResult": "200", "result": "error",
    "resultReason": "Unexpected Response Code: 400", "resultDetails": "",
    "server": "http://h",
    "request": {"httpMethod": "POST", "url": "http://h/things",
                 "timestamp": "", "payload": "", "headers": []},
    "response": {"httpMethod": "POST", "responseCode": 400, "responseTimeInMs": 1,
                  "numberOfWordsInResponse": 1, "numberOfLinesInResponse": 1,
                  "contentLengthInBytes": 1, "responseContentType": "application/json",
                  "jsonBody": {"error_description": "bad"}, "headers": []},
}


def _tmp_dir() -> Path:
    d = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(d.cleanup)
    return Path(d.name)


def make_config(body=CONFIG):
    root = _tmp_dir()
    (root / ".local" / "cats").mkdir(parents=True)
    p = root / ".local" / "cats" / "config.yaml"
    p.write_text(body)
    (root / "openapi.json").write_text("{}")
    (root / "fp.yaml").write_text("version: 1\nrules: []\n")
    return cfg.load_config(p)


def make_db(config) -> Path:
    """Parse one Test*.json into a real database under config.results_dir."""
    report = _tmp_dir()
    (report / "Test1.json").write_text(json.dumps(CATS_JSON))
    db = config.results_dir / "cats-results-R1.db"
    config.results_dir.mkdir(parents=True, exist_ok=True)
    P.parse_report(report, db, {"run_id": "R1"})
    return db


class TestResolveDb(unittest.TestCase):
    def test_missing_latest_exits_2(self):
        config = make_config()
        config.results_dir.mkdir(parents=True, exist_ok=True)
        with self.assertRaises(SystemExit) as ctx:
            CT.resolve_db(config, None)
        self.assertEqual(ctx.exception.code, 2)

    def test_latest_resolves_through_symlink(self):
        config = make_config()
        db = make_db(config)
        (config.results_dir / "latest.db").symlink_to(db.name)
        resolved = CT.resolve_db(config, "latest")
        self.assertEqual(resolved, db.resolve())

    def test_explicit_missing_path_exits_2(self):
        config = make_config()
        with self.assertRaises(SystemExit) as ctx:
            CT.resolve_db(config, str(config.results_dir / "nope.db"))
        self.assertEqual(ctx.exception.code, 2)

    def test_explicit_existing_path_returned(self):
        config = make_config()
        db = make_db(config)
        self.assertEqual(CT.resolve_db(config, str(db)), db)


class TestClassifyDryRun(unittest.TestCase):
    def test_original_db_untouched(self):
        config = make_config()
        db = make_db(config)
        before = db.read_bytes()

        args = argparse.Namespace(db=str(db), dry_run=True)
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(io.StringIO()):
            CT.cmd_classify(args)

        self.assertEqual(db.read_bytes(), before, "dry-run classify must not mutate the real database")

    def test_dry_run_still_reports_flagged_count(self):
        config = make_config()
        root = config.repo_root
        (root / "fp.yaml").write_text(
            "version: 1\nrules:\n  - id: R1\n    why: test\n    when: {response_code: 400}\n"
        )
        db = make_db(config)

        args = argparse.Namespace(db=str(db), dry_run=True)
        out = io.StringIO()
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(out):
            CT.cmd_classify(args)
        self.assertIn("flagged: 1 / 1", out.getvalue())

    def test_non_dry_run_mutates_db(self):
        config = make_config()
        root = config.repo_root
        (root / "fp.yaml").write_text(
            "version: 1\nrules:\n  - id: R1\n    why: test\n    when: {response_code: 400}\n"
        )
        db = make_db(config)
        before = db.read_bytes()

        args = argparse.Namespace(db=str(db), dry_run=False)
        with mock.patch.object(CT, "load", return_value=config), redirect_stdout(io.StringIO()):
            CT.cmd_classify(args)

        self.assertNotEqual(db.read_bytes(), before)


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
        config = make_config()
        db = make_db(config)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "load_rules", side_effect=RuleError("boom rules")),
        ):
            code, err = self._run_main(["classify", "--db", str(db)])
        self.assertEqual(code, 2)
        self.assertIn("boom rules", err)

    def test_classify_error(self):
        config = make_config()
        db = make_db(config)
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "classify_db", side_effect=ClassifyError("boom classify")),
        ):
            code, err = self._run_main(["classify", "--db", str(db)])
        self.assertEqual(code, 2)
        self.assertIn("boom classify", err)

    def test_hook_error(self):
        config = make_config()
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "execute", side_effect=run.HookError("boom hook")),
        ):
            code, err = self._run_main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("boom hook", err)

    def test_preflight_error(self):
        config = make_config()
        with (
            mock.patch.object(CT, "load", return_value=config),
            mock.patch.object(CT, "execute", side_effect=run.PreflightError("boom preflight")),
        ):
            code, err = self._run_main(["run"])
        self.assertEqual(code, 2)
        self.assertIn("boom preflight", err)


def _with_fake_cats(bindir: Path, version_script: str) -> None:
    """Create a fake `cats` executable on a directory, for PATH injection."""
    script = bindir / "cats"
    script.write_text(f"#!/bin/sh\nif [ \"$1\" = \"--version\" ]; then {version_script}; fi\n")
    script.chmod(0o755)


class TestCatsVersion(unittest.TestCase):
    def test_absent_binary_returns_none(self):
        with mock.patch.object(CT.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(CT._cats_version())

    def test_plain_output_uses_first_line(self):
        bindir = _tmp_dir()
        _with_fake_cats(bindir, 'echo "CATS 11.0.0-fake"')
        with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
            self.assertEqual(CT._cats_version(), "CATS 11.0.0-fake")

    def test_banner_output_skips_decoration(self):
        # Reproduces the real CATS binary: an ASCII-art banner precedes the
        # actual "CATS version X.Y.Z" line — naively taking the first
        # non-empty line returns banner noise instead of a version.
        bindir = _tmp_dir()
        _with_fake_cats(
            bindir,
            'printf "# # # # #\\n#  CATS  #\\n# # # # #\\n\\nCATS version 13.8.0\\n"',
        )
        with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
            self.assertEqual(CT._cats_version(), "CATS version 13.8.0")


class TestDiscoverSpec(unittest.TestCase):
    def test_single_match_used(self):
        root = _tmp_dir()
        (root / "openapi.json").write_text("{}")
        self.assertEqual(CT._discover_spec(root, non_interactive=True), "openapi.json")

    def test_multiple_matches_exit_2(self):
        root = _tmp_dir()
        (root / "api-schema").mkdir()
        (root / "api-schema" / "a.json").write_text("{}")
        (root / "api-schema" / "b.json").write_text("{}")
        with self.assertRaises(SystemExit) as ctx:
            CT._discover_spec(root, non_interactive=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_no_matches_non_interactive_exits_2(self):
        root = _tmp_dir()
        with self.assertRaises(SystemExit) as ctx:
            CT._discover_spec(root, non_interactive=True)
        self.assertEqual(ctx.exception.code, 2)

    def test_no_matches_interactive_prompts(self):
        root = _tmp_dir()
        with mock.patch("builtins.input", return_value="my/spec.json"):
            self.assertEqual(CT._discover_spec(root, non_interactive=False), "my/spec.json")


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
        root = _tmp_dir()
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
        root = _tmp_dir()
        (root / "openapi.json").write_text("{}")
        self._chdir(root)
        config_path = root / ".local" / "cats" / "config.yaml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text("sentinel")

        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            CT.cmd_init(self._args())
        self.assertEqual(ctx.exception.code, 0)
        self.assertEqual(config_path.read_text(), "sentinel")

    def test_no_spec_non_interactive_exits_2(self):
        root = _tmp_dir()
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
