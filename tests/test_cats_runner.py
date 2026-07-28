import http.server
import os
import sqlite3
import stat
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from cats_fixtures import CONFIG, make_config
from catslib import runner as run
from catslib.classify import ClassifyError


class TestRedact(unittest.TestCase):
    def test_replaces_every_occurrence(self):
        self.assertEqual(run.redact("a tok b tok", "tok"), "a [REDACTED] b [REDACTED]")

    def test_empty_token_is_noop(self):
        self.assertEqual(run.redact("abc", ""), "abc")


class TestResolveToken(unittest.TestCase):
    def test_captures_stdout_trimmed(self):
        c = make_config(self)
        self.assertEqual(run.resolve_token(c.identities["admin"], c.repo_root, {}), "secret-token")

    def test_empty_token_raises(self):
        # `printf ''` (single quotes) rather than `printf ""` — the latter breaks
        # the surrounding double-quoted YAML flow scalar (`{token_cmd: "printf """}`
        # is invalid YAML; PyYAML rejects it before resolve_token ever runs).
        c = make_config(self, CONFIG.replace('printf secret-token', "printf ''"))
        with self.assertRaises(run.HookError):
            run.resolve_token(c.identities["admin"], c.repo_root, {})

    def test_failing_command_raises_with_command_in_message(self):
        c = make_config(self, CONFIG.replace('printf secret-token', 'exit 3'))
        with self.assertRaises(run.HookError) as ctx:
            run.resolve_token(c.identities["admin"], c.repo_root, {})
        self.assertIn("exit 3", str(ctx.exception))

    def test_stderr_tail_included_in_failure_message(self):
        # stdout is the token channel; stderr is the diagnostic channel — a
        # failing token_cmd's stderr is safe to surface and makes the error
        # actionable instead of a bare exit code.
        c = make_config(self, CONFIG.replace(
            'printf secret-token', 'echo boom-diagnostic >&2; exit 3'
        ))
        with self.assertRaises(run.HookError) as ctx:
            run.resolve_token(c.identities["admin"], c.repo_root, {})
        self.assertIn("boom-diagnostic", str(ctx.exception))


class TestRunHook(unittest.TestCase):
    def test_success_is_silent(self):
        run.run_hook("seed", "true", Path("."), {})

    def test_nonzero_exit_raises_hook_error(self):
        with self.assertRaises(run.HookError) as ctx:
            run.run_hook("seed", "exit 7", Path("."), {})
        self.assertIn("seed", str(ctx.exception))

    def test_env_is_passed_through(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out"
            run.run_hook("seed", f'printf "$CATS_RUN_ID" > {out}', Path(d), {"CATS_RUN_ID": "R9"})
            self.assertEqual(out.read_text(), "R9")


class TestHeadersFile(unittest.TestCase):
    def test_written_with_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as d:
            p = run.write_headers_file(Path(d), "Authorization", "Bearer tok")
            self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
            self.assertIn("Authorization: Bearer tok", p.read_text())
            self.assertIn("all:", p.read_text())

    def test_special_characters_in_value_round_trip(self):
        # A value starting with a YAML-special character, or containing ": ",
        # must still produce a file CATS (a YAML parser) can read correctly —
        # an f-string would have broken on input like this.
        with tempfile.TemporaryDirectory() as d:
            value = '*starts-with-star and has: a colon-space'
            p = run.write_headers_file(Path(d), "Authorization", value)
            parsed = yaml.safe_load(p.read_text())
            self.assertEqual(parsed, {"all": {"Authorization": value}})

    def test_extra_headers_merge_into_the_same_all_block(self):
        with tempfile.TemporaryDirectory() as d:
            p = run.write_headers_file(
                Path(d), "Authorization", "Bearer tok", {"If-Match": "*", "X-Trace": "on"}
            )
            self.assertEqual(
                yaml.safe_load(p.read_text()),
                {"all": {"Authorization": "Bearer tok", "If-Match": "*", "X-Trace": "on"}},
            )

    def test_auth_header_wins_over_a_colliding_extra(self):
        # Config validation rejects this, so it should be unreachable; the
        # write order is the second line of defence, because the failure mode
        # is a silently unauthenticated campaign rather than an error.
        with tempfile.TemporaryDirectory() as d:
            p = run.write_headers_file(
                Path(d), "Authorization", "Bearer tok", {"Authorization": "Bearer WRONG"}
            )
            self.assertEqual(
                yaml.safe_load(p.read_text())["all"]["Authorization"], "Bearer tok"
            )

    def test_write_failure_removes_the_partial_file(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")), \
                    self.assertRaises(OSError):
                run.write_headers_file(Path(d), "Authorization", "Bearer tok")
            # mkstemp's file must not survive a chmod/write failure.
            self.assertEqual(list(Path(d).glob("cats-headers-*")), [])


class TestBuildArgv(unittest.TestCase):
    def _argv(self, **kw):
        c = make_config(self)
        return run.build_cats_argv(
            c, headers_file=Path("/tmp/h.yml"), report_dir=Path("/tmp/rep"),
            path_filter=kw.get("path_filter"), rate=kw.get("rate"),
            blackbox=kw.get("blackbox", False))

    def test_core_flags_present(self):
        argv = self._argv()
        self.assertEqual(argv[0], "cats")
        self.assertIn("--server=http://localhost:8080", argv)
        self.assertIn("--headers=/tmp/h.yml", argv)
        self.assertIn("--output=/tmp/rep", argv)
        self.assertIn("--maxRequestsPerMinute=500", argv)

    def test_token_never_appears_in_argv(self):
        self.assertNotIn("secret-token", " ".join(self._argv()))

    def test_skip_options_rendered(self):
        argv = " ".join(self._argv())
        self.assertIn("--skipFuzzers=DuplicateHeaders,EnumCaseVariantFields", argv)
        self.assertIn("--skipFieldFormat=uuid", argv)
        self.assertIn("--skipField=offset", argv)
        self.assertIn("--skipFuzzersForExtension=x-public-endpoint=true:BypassAuthentication", argv)

    def test_extra_args_appended(self):
        self.assertIn("--printExecutionStatistics", self._argv())

    def test_path_filter_and_blackbox_optional(self):
        self.assertNotIn("-b", self._argv())
        argv = self._argv(path_filter="/things", blackbox=True)
        self.assertIn("--paths=/things", argv)
        self.assertIn("-b", argv)

    def test_rate_override_wins_over_config(self):
        self.assertIn("--maxRequestsPerMinute=99", self._argv(rate=99))

    def test_rate_zero_is_respected(self):
        # `rate or opts.max_requests_per_minute` would treat 0 as falsy/unset
        # and silently fall back to the config default — 0 is a legitimate
        # (if extreme) override and must survive.
        self.assertIn("--maxRequestsPerMinute=0", self._argv(rate=0))

    def test_skip_paths_absent_when_unset(self):
        self.assertNotIn("--skipPaths", " ".join(self._argv()))

    def test_skip_paths_rendered_as_one_comma_list(self):
        body = CONFIG.replace(
            "  extra_args:", "  skip_paths: [/me/logout, /me/nuke]\n  extra_args:"
        )
        c = make_config(self, body)
        argv = run.build_cats_argv(
            c, headers_file=Path("/tmp/h.yml"), report_dir=Path("/tmp/rep"),
            path_filter=None, rate=None, blackbox=False)
        self.assertIn("--skipPaths=/me/logout,/me/nuke", argv)

    def test_explicit_path_filter_overrides_skip_paths(self):
        # `run --path /me/logout` exists precisely so a skipped path can be
        # fuzzed on its own; emitting both flags would make CATS test nothing.
        body = CONFIG.replace("  extra_args:", "  skip_paths: [/me/logout]\n  extra_args:")
        c = make_config(self, body)
        argv = run.build_cats_argv(
            c, headers_file=Path("/tmp/h.yml"), report_dir=Path("/tmp/rep"),
            path_filter="/me/logout", rate=None, blackbox=False)
        self.assertIn("--paths=/me/logout", argv)
        self.assertNotIn("--skipPaths", " ".join(argv))


class TestValidityGates(unittest.TestCase):
    """RunResult.contamination_reasons is the single source of truth for
    "is this run worth drawing conclusions from" (TMI #578 transport, #591 auth)."""

    def _result(self, **kw):
        return run.RunResult(
            run_id="R", db_path=Path("/tmp/x.db"), report_dir=Path("/tmp/r"),
            cats_exit_code=0, parse_stats=None, classify_result=None, **kw)

    def test_clean_run_has_no_reasons(self):
        r = self._result(connection_errors=6, unauthenticated=356, total_tests=10000)
        self.assertEqual(r.contamination_reasons, [])
        self.assertFalse(r.contaminated)

    def test_connection_errors_over_threshold(self):
        r = self._result(connection_errors=4600, unauthenticated=0, total_tests=10000)
        self.assertTrue(r.contaminated)
        self.assertIn("connection-error rate", r.contamination_reasons[0])

    def test_lost_credential_over_threshold(self):
        # The shape of TMI #591: a completed 118k-test campaign that silently
        # ran ~44% of itself unauthenticated after fuzzing /me/logout.
        r = self._result(connection_errors=70, unauthenticated=52340, total_tests=118448)
        self.assertTrue(r.contaminated)
        self.assertIn("unauthenticated rate", r.contamination_reasons[0])
        self.assertIn("skip_paths", r.contamination_reasons[0])

    def test_both_gates_reported_together(self):
        r = self._result(connection_errors=5000, unauthenticated=5000, total_tests=10000)
        self.assertEqual(len(r.contamination_reasons), 2)

    def test_no_stats_is_not_contaminated(self):
        # --skip-parse leaves every count None; absence of evidence must not
        # read as evidence of contamination.
        self.assertFalse(self._result().contaminated)

    def test_zero_test_run_is_not_contaminated(self):
        r = self._result(connection_errors=0, unauthenticated=0, total_tests=0)
        self.assertFalse(r.contaminated)


class TestRunId(unittest.TestCase):
    def test_format(self):
        self.assertEqual(
            run.run_id_for(datetime(2026, 7, 26, 22, 2, 0, tzinfo=timezone.utc)),
            "20260726T220200Z")


# --- preflight -----------------------------------------------------------


class _OKHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, fmt, *args):  # silence per-request stderr logging
        pass


class _NotFoundHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):  # silence per-request stderr logging
        pass


class _LiveServer:
    """A throwaway HTTP server for preflight/execute health checks."""

    def __init__(self, handler_cls=_OKHandler):
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), handler_cls)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


def _with_fake_cats(
    bindir: Path, extra_script: str = "", version_output: str = 'echo "CATS 11.0.0-fake"'
) -> Path:
    """Create a fake `cats` executable on a directory, for PATH injection."""
    script = bindir / "cats"
    script.write_text(
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then {version_output}; exit 0; fi\n'
        + extra_script
    )
    script.chmod(0o755)
    return script


class TestCatsVersion(unittest.TestCase):
    def test_absent_binary_returns_none(self):
        with mock.patch.object(run.subprocess, "run", side_effect=FileNotFoundError):
            self.assertIsNone(run._cats_version())

    def test_plain_output_without_digits_uses_first_line(self):
        with tempfile.TemporaryDirectory() as bindir:
            _with_fake_cats(Path(bindir), version_output='echo "cats (dev build)"')
            with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                self.assertEqual(run._cats_version(), "cats (dev build)")

    def test_banner_output_skips_decoration(self):
        # Reproduces the real CATS binary (verified against the actual `cats`
        # binary, not assumed): an ASCII-art banner precedes the actual
        # "CATS version X.Y.Z" line — naively taking the first non-empty line
        # returns banner noise instead of a version.
        with tempfile.TemporaryDirectory() as bindir:
            _with_fake_cats(
                Path(bindir),
                version_output='printf "# # # # #\\n#  CATS  #\\n# # # # #\\n\\nCATS version 13.8.0\\n"',
            )
            with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                self.assertEqual(run._cats_version(), "CATS version 13.8.0")


class TestChecksAndPreflightAgree(unittest.TestCase):
    """`checks()` (full report, used by `doctor`) and `preflight()` (fail-fast,
    used by `run`) are built from the same per-check logic on purpose — this
    guards against the two silently drifting in wording the way the hand-written
    duplicates they replaced already had (doctor said "server is not running at
    {url} ({exc})", preflight said "...; start it first ({exc})")."""

    def test_first_failing_check_message_matches_preflight_exactly(self):
        server = _LiveServer()
        self.addCleanup(server.stop)
        c = make_config(self, CONFIG.replace("http://localhost:8080", server.url))
        c.spec.unlink()

        with tempfile.TemporaryDirectory() as bindir:
            _with_fake_cats(Path(bindir))
            with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                results = run.checks(c)
                failing_details = [detail for _name, ok, detail in results if not ok]
                self.assertEqual(failing_details, [f"OpenAPI spec not found: {c.spec}"])

                with self.assertRaises(run.PreflightError) as ctx:
                    run.preflight(c)
                self.assertEqual(str(ctx.exception), failing_details[0])


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.server = _LiveServer()
        self.addCleanup(self.server.stop)

    def _config(self, **overrides):
        body = CONFIG.replace("http://localhost:8080", self.server.url)
        for old, new in overrides.items():
            body = body.replace(old, new)
        return make_config(self, body)

    def test_missing_spec_raises(self):
        c = self._config()
        c.spec.unlink()
        with self.assertRaises(run.PreflightError) as ctx:
            run.preflight(c)
        self.assertIn(str(c.spec), str(ctx.exception))

    def test_missing_cats_binary_raises(self):
        c = self._config()
        with mock.patch("shutil.which", return_value=None), \
                self.assertRaises(run.PreflightError) as ctx:
            run.preflight(c)
        self.assertIn("cats", str(ctx.exception).lower())

    def test_invalid_rules_raises(self):
        c = self._config()
        c.false_positives.write_text("not: [valid, rules")
        with self.assertRaises(run.PreflightError):
            run.preflight(c)

    def test_unreachable_server_raises(self):
        c = self._config()
        self.server.stop()
        with self.assertRaises(run.PreflightError) as ctx:
            run.preflight(c)
        self.assertIn(c.health_url, str(ctx.exception))

    def test_server_error_response_raises_with_distinct_message(self):
        # HTTPError subclasses URLError — a server that IS running but answers
        # health_url with 404/401/500 must not be reported as "not running".
        self.server.stop()
        error_server = _LiveServer(_NotFoundHandler)
        self.addCleanup(error_server.stop)
        c = make_config(self, CONFIG.replace("http://localhost:8080", error_server.url))
        with self.assertRaises(run.PreflightError) as ctx:
            run.preflight(c)
        message = str(ctx.exception)
        self.assertIn("404", message)
        self.assertNotIn("not running", message)

    def test_all_checks_pass_is_silent(self):
        c = self._config()
        with tempfile.TemporaryDirectory() as bindir:
            _with_fake_cats(Path(bindir))
            with mock.patch.dict(os.environ, {"PATH": f"{bindir}:{os.environ['PATH']}"}):
                run.preflight(c)  # must not raise


# --- execute ---------------------------------------------------------------


_FAKE_CATS_RUN = """
OUTPUT=""
for arg in "$@"; do
  case "$arg" in
    --output=*) OUTPUT="${arg#--output=}" ;;
  esac
done
mkdir -p "$OUTPUT"
cat > "$OUTPUT/Test1.json" <<'EOF'
{"testId":"Test 1","traceId":"t1","scenario":"s1","expectedResult":"2XX","result":"success",
 "fuzzer":"FakeFuzzer","path":"/x","server":"http://x","request":{"httpMethod":"GET","url":"http://x/x","headers":[]},
 "response":{"httpMethod":"GET","responseCode":200,"headers":[]}}
EOF
cat > "$OUTPUT/Test2.json" <<'EOF'
{"testId":"Test 2","traceId":"t2","scenario":"s2","expectedResult":"2XX","result":"warn",
 "fuzzer":"FakeFuzzer","path":"/y","server":"http://x","request":{"httpMethod":"GET","url":"http://x/y","headers":[]},
 "response":{"httpMethod":"GET","responseCode":500,"headers":[]}}
EOF
"""
# Callers append their own trailing `exit N` (or rely on the implicit 0 from the
# last heredoc) so the exit code test can override it without dead code after an
# early `exit 0`.

_FAKE_CATS_FAIL = 'echo "boom" >&2\nexit 9\n'


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.server = _LiveServer()
        self.addCleanup(self.server.stop)
        self.bindir = tempfile.mkdtemp()
        self._path_patch = mock.patch.dict(
            os.environ, {"PATH": f"{self.bindir}:{os.environ['PATH']}"}
        )
        self._path_patch.start()
        self.addCleanup(self._path_patch.stop)

    def _config(self, body=CONFIG):
        body = body.replace("http://localhost:8080", self.server.url)
        return make_config(self, body)

    def test_successful_run_parses_classifies_and_stamps_finished_at(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config()
        now = datetime(2026, 7, 26, 22, 2, 0, tzinfo=timezone.utc)

        result = run.execute(c, now=now)

        self.assertEqual(result.run_id, "20260726T220200Z")
        self.assertEqual(result.cats_exit_code, 0)
        self.assertIsNotNone(result.parse_stats)
        self.assertEqual(result.parse_stats.processed, 2)
        self.assertIsNotNone(result.classify_result)
        self.assertTrue(result.db_path.exists())

        conn = sqlite3.connect(result.db_path)
        try:
            row = conn.execute("SELECT finished_at FROM run_meta").fetchone()
        finally:
            conn.close()
        self.assertIsNotNone(row[0])

        latest = c.results_dir / "latest.db"
        self.assertTrue(latest.is_symlink())
        self.assertEqual(os.readlink(latest), result.db_path.name)

        # the headers file must not survive the run
        leftover = list(c.results_dir.glob("cats-headers-*"))
        self.assertEqual(leftover, [])

        # raw report is removed by default (retain_raw_report defaults to False)
        self.assertFalse(result.report_dir.exists())

    def test_token_never_appears_in_stored_command_line(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config()
        result = run.execute(c)
        conn = sqlite3.connect(result.db_path)
        try:
            cats_args = conn.execute("SELECT cats_args FROM run_meta").fetchone()[0]
        finally:
            conn.close()
        # The token never lands in argv in the first place (it travels via the
        # headers file), so cats_args has nothing to redact — this asserts the
        # stronger property directly rather than asserting redact() ran.
        self.assertNotIn("secret-token", cats_args)

    def test_finished_at_stays_null_when_classify_fails(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config()
        with mock.patch.object(run, "classify_db", side_effect=ClassifyError("boom")), \
                self.assertRaises(ClassifyError):
            run.execute(c)

        db_files = list(c.results_dir.glob("cats-results-*.db"))
        self.assertEqual(len(db_files), 1)
        conn = sqlite3.connect(db_files[0])
        try:
            row = conn.execute("SELECT finished_at FROM run_meta").fetchone()
        finally:
            conn.close()
        self.assertIsNone(row[0])

        # The headers file must not survive even a failed run — pins the
        # `finally` ordering so a future refactor that moves the try below
        # write_headers_file (or drops the finally) fails a test, not just
        # a review.
        self.assertEqual(list(c.results_dir.glob("cats-headers-*")), [])

    def test_seed_hook_failure_aborts_before_any_db_is_written(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace(
            "identities:", "hooks:\n  seed: \"exit 5\"\nidentities:"
        ))
        with self.assertRaises(run.HookError):
            run.execute(c)
        self.assertEqual(list(c.results_dir.glob("cats-results-*.db")), [])

    def test_skip_seed_bypasses_failing_seed_hook(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace(
            "identities:", "hooks:\n  seed: \"exit 5\"\nidentities:"
        ))
        result = run.execute(c, skip_seed=True)
        self.assertEqual(result.cats_exit_code, 0)

    def test_skip_parse_leaves_stats_none_and_no_db(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config()
        result = run.execute(c, skip_parse=True)
        self.assertEqual(result.cats_exit_code, 0)
        self.assertIsNone(result.parse_stats)
        self.assertIsNone(result.classify_result)
        self.assertFalse(result.db_path.exists())

    def test_post_run_hook_failure_warns_but_does_not_raise(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace(
            "identities:", "hooks:\n  post_run: \"exit 6\"\nidentities:"
        ))
        with self.assertLogs(run.__name__, level="WARNING") as ctx:
            result = run.execute(c)
        self.assertTrue(result.db_path.exists())
        self.assertTrue(any("post_run" in m for m in ctx.output))

    def test_nonzero_cats_exit_code_is_still_parsed(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN + "exit 2\n")
        c = self._config()
        result = run.execute(c)
        self.assertEqual(result.cats_exit_code, 2)
        self.assertIsNotNone(result.parse_stats)

    def test_token_never_appears_in_hook_environment(self):
        # The token is a local variable inside execute(); it is never added to
        # hook_env, so a hook that dumps its own environment must not see it —
        # even post_run, which runs after the token has been resolved.
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        with tempfile.TemporaryDirectory() as d:
            env_dump = Path(d) / "post_run_env.txt"
            c = self._config(CONFIG.replace(
                "identities:", f'hooks:\n  post_run: "env > {env_dump}"\nidentities:'
            ))
            run.execute(c)
            self.assertTrue(env_dump.exists())
            self.assertNotIn("secret-token", env_dump.read_text())

    def test_naive_now_is_rejected(self):
        c = self._config()
        with self.assertRaises(ValueError):
            run.execute(c, now=datetime(2026, 7, 26, 22, 2, 0))  # noqa: DTZ001 (naive on purpose)

    def test_successful_run_prunes_old_dbs_down_to_keep_runs(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace("identities:", "keep_runs: 2\nidentities:"))
        base = datetime(2026, 7, 26, 22, 0, 0, tzinfo=timezone.utc)

        for minute in range(3):
            result = run.execute(c, now=base.replace(minute=minute))

        # only the third (most recent) run should have pruned anything, since
        # keep_runs=2 first gets exceeded on that call
        self.assertEqual(len(result.pruned), 1)
        self.assertEqual(result.pruned[0].name, "cats-results-20260726T220000Z.db")
        remaining = {p.name for p in c.results_dir.glob("cats-results-*.db")}
        self.assertEqual(
            remaining,
            {"cats-results-20260726T220100Z.db", "cats-results-20260726T220200Z.db"},
        )

    def test_no_prune_flag_skips_pruning_for_this_invocation(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace("identities:", "keep_runs: 1\nidentities:"))
        base = datetime(2026, 7, 26, 22, 0, 0, tzinfo=timezone.utc)
        run.execute(c, now=base)

        result = run.execute(c, now=base.replace(minute=1), no_prune=True)

        self.assertEqual(result.pruned, [])
        self.assertEqual(len(list(c.results_dir.glob("cats-results-*.db"))), 2)

    def test_keep_runs_zero_disables_pruning(self):
        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        c = self._config(CONFIG.replace("identities:", "keep_runs: 0\nidentities:"))
        base = datetime(2026, 7, 26, 22, 0, 0, tzinfo=timezone.utc)
        for minute in range(3):
            result = run.execute(c, now=base.replace(minute=minute))

        self.assertEqual(result.pruned, [])
        self.assertEqual(len(list(c.results_dir.glob("cats-results-*.db"))), 3)

    def test_contaminated_run_does_not_prune(self):
        # A single connection-error (999) test with no other tests puts the
        # connection-error rate at 100%, over the default 1% threshold.
        _fake_contaminated = """
OUTPUT=""
for arg in "$@"; do
  case "$arg" in
    --output=*) OUTPUT="${arg#--output=}" ;;
  esac
done
mkdir -p "$OUTPUT"
cat > "$OUTPUT/Test1.json" <<'EOF'
{"testId":"Test 1","traceId":"t1","scenario":"s1","expectedResult":"2XX","result":"error",
 "fuzzer":"FakeFuzzer","path":"/x","server":"http://x","request":{"httpMethod":"GET","url":"http://x/x","headers":[]},
 "response":{"httpMethod":"GET","responseCode":999,"headers":[]}}
EOF
"""
        c = self._config(CONFIG.replace("identities:", "keep_runs: 1\nidentities:"))
        base = datetime(2026, 7, 26, 22, 0, 0, tzinfo=timezone.utc)

        _with_fake_cats(Path(self.bindir), _FAKE_CATS_RUN)
        run.execute(c, now=base)

        _with_fake_cats(Path(self.bindir), _fake_contaminated)
        result = run.execute(c, now=base.replace(minute=1))

        self.assertTrue(result.contaminated)
        self.assertEqual(result.pruned, [])
        # the earlier clean run must survive — a contaminated run must never
        # delete history that might be needed to debug what went wrong
        self.assertEqual(len(list(c.results_dir.glob("cats-results-*.db"))), 2)


if __name__ == "__main__":
    unittest.main()


class TestHookOrder(unittest.TestCase):
    """pre_run must run before seed (#595): pre_run is where a repo clears what
    the previous campaign left behind, and seeding is itself a burst of API
    calls that should not run against exhausted state."""

    def _order(self, body_extra, **kw):
        calls = []
        c = make_config(self, CONFIG.replace("identities:", body_extra + "identities:"))
        with mock.patch.object(run, "run_hook", side_effect=lambda n, *a, **k: calls.append(n)), \
                mock.patch.object(run, "preflight"), \
                mock.patch.object(run, "resolve_token", return_value="tok"), \
                mock.patch.object(run, "subprocess") as sp:
            sp.run.return_value = mock.Mock(returncode=0)
            run.execute(c, skip_parse=True, **kw)
        return calls

    HOOKS = 'hooks:\n  seed: "true"\n  pre_run: "true"\n  post_run: "true"\n'

    def test_pre_run_precedes_seed(self):
        calls = self._order(self.HOOKS)
        self.assertEqual(calls[:2], ["pre_run", "seed"])

    def test_post_run_still_last(self):
        self.assertEqual(self._order(self.HOOKS)[-1], "post_run")

    def test_skip_seed_still_runs_pre_run(self):
        calls = self._order(self.HOOKS, skip_seed=True)
        self.assertIn("pre_run", calls)
        self.assertNotIn("seed", calls)
