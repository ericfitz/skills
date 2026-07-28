import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cats" / "scripts"))

from catslib import config as cfg

MINIMAL = """
version: 1
spec: openapi.json
server: http://localhost:8080
results_dir: test/results/cats
false_positives: test/cats/false-positives.yaml
identities:
  admin: {token_cmd: "echo tok"}
default_identity: admin
"""


class TestFindConfig(unittest.TestCase):
    def test_finds_config_by_walking_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local" / "cats").mkdir(parents=True)
            target = root / ".local" / "cats" / "config.yaml"
            target.write_text(MINIMAL)
            deep = root / "a" / "b" / "c"
            deep.mkdir(parents=True)
            self.assertEqual(cfg.find_config(deep), target)

    def test_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(cfg.find_config(Path(d)))

    def test_dotdot_does_not_escape_to_a_non_ancestor(self):
        # Config lives only under <root>/sub. A start path whose lexical ".."
        # navigation lands back at <root> must NOT find it, because <root>/sub
        # is not an ancestor of <root>.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sub" / ".local" / "cats").mkdir(parents=True)
            (root / "sub" / ".local" / "cats" / "config.yaml").write_text(MINIMAL)
            start = root / "sub" / "decoy" / ".." / ".."
            self.assertIsNone(cfg.find_config(start))

    def test_dotdot_normalizes_to_a_real_ancestor(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local" / "cats").mkdir(parents=True)
            target = root / ".local" / "cats" / "config.yaml"
            target.write_text(MINIMAL)
            start = root / "a" / "b" / ".." / ".."
            self.assertEqual(cfg.find_config(start), target)


class TestLoadConfig(unittest.TestCase):
    def _write(self, body):
        d = tempfile.mkdtemp()
        root = Path(d)
        (root / ".local" / "cats").mkdir(parents=True)
        p = root / ".local" / "cats" / "config.yaml"
        p.write_text(body)
        return p

    def test_defaults_applied(self):
        c = cfg.load_config(self._write(MINIMAL))
        self.assertEqual(c.default_identity, "admin")
        self.assertEqual(c.auth_header, "Authorization")
        self.assertEqual(c.auth_template, "Bearer {token}")
        self.assertFalse(c.retain_raw_report)
        self.assertFalse(c.allow_suppressing_5xx)
        self.assertEqual(c.cats.max_requests_per_minute, 3000)
        self.assertEqual(c.cats.http_methods, ["POST", "PUT", "GET", "DELETE", "PATCH"])
        self.assertIsNone(c.hooks.seed)
        self.assertEqual(c.keep_runs, 5)
        self.assertEqual(c.cats.skip_paths, [])
        self.assertEqual(c.max_unauthenticated_pct, 5.0)

    def test_skip_paths_parsed(self):
        c = cfg.load_config(self._write(MINIMAL + "\ncats:\n  skip_paths: [/me/logout]\n"))
        self.assertEqual(c.cats.skip_paths, ["/me/logout"])

    def test_skip_paths_rejects_scalar(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\ncats:\n  skip_paths: /me/logout\n"))
        self.assertIn("cats.skip_paths", str(ctx.exception))

    def test_max_unauthenticated_pct_custom_value_applied(self):
        c = cfg.load_config(self._write(MINIMAL + "\nmax_unauthenticated_pct: 0.5\n"))
        self.assertEqual(c.max_unauthenticated_pct, 0.5)

    def test_max_unauthenticated_pct_rejects_out_of_range(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\nmax_unauthenticated_pct: 101\n"))
        self.assertIn("max_unauthenticated_pct", str(ctx.exception))

    def test_keep_runs_custom_value_applied(self):
        c = cfg.load_config(self._write(MINIMAL + "\nkeep_runs: 10\n"))
        self.assertEqual(c.keep_runs, 10)

    def test_keep_runs_zero_allowed(self):
        c = cfg.load_config(self._write(MINIMAL + "\nkeep_runs: 0\n"))
        self.assertEqual(c.keep_runs, 0)

    def test_keep_runs_rejects_bool(self):
        # bool is an int subclass in Python; `keep_runs: true` must not be
        # silently accepted as 1.
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\nkeep_runs: true\n"))
        self.assertIn("keep_runs", str(ctx.exception))

    def test_keep_runs_rejects_negative(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\nkeep_runs: -1\n"))
        self.assertIn("keep_runs", str(ctx.exception))

    def test_keep_runs_rejects_non_integer(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\nkeep_runs: 2.5\n"))
        self.assertIn("keep_runs", str(ctx.exception))

    def test_paths_resolve_against_repo_root(self):
        p = self._write(MINIMAL)
        c = cfg.load_config(p)
        self.assertEqual(c.repo_root, p.parents[2])
        self.assertEqual(c.spec, c.repo_root / "openapi.json")
        self.assertEqual(c.results_dir, c.repo_root / "test" / "results" / "cats")

    def test_health_url_defaults_to_server(self):
        self.assertEqual(cfg.load_config(self._write(MINIMAL)).health_url,
                         "http://localhost:8080")

    def test_missing_required_key_names_the_key(self):
        body = MINIMAL.replace("server: http://localhost:8080\n", "")
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("server", str(ctx.exception))

    def test_unknown_top_level_key_rejected(self):
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(MINIMAL + "\nbogus: 1\n"))
        self.assertIn("bogus", str(ctx.exception))

    def test_default_identity_must_exist(self):
        body = MINIMAL.replace("default_identity: admin", "default_identity: nobody")
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("nobody", str(ctx.exception))

    def test_skip_fuzzers_for_extension_entry_parsed(self):
        body = MINIMAL + """
cats:
  skip_fuzzers_for_extension:
    - {extension: x-public-endpoint, value: "true", fuzzers: [BypassAuthentication]}
"""
        c = cfg.load_config(self._write(body))
        self.assertEqual(c.cats.skip_fuzzers_for_extension[0]["fuzzers"],
                         ["BypassAuthentication"])

    def test_skip_fuzzers_for_extension_missing_fuzzers_rejected(self):
        body = MINIMAL + """
cats:
  skip_fuzzers_for_extension:
    - {extension: x-public-endpoint, value: "true"}
"""
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("skip_fuzzers_for_extension", str(ctx.exception))

    def test_unsupported_version_rejected(self):
        body = MINIMAL.replace("version: 1", "version: 99")
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config(self._write(body))

    def test_missing_config_file_raises_config_error(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / ".local" / "cats" / "config.yaml"
            with self.assertRaises(cfg.ConfigError) as ctx:
                cfg.load_config(missing)
            self.assertIn(str(missing), str(ctx.exception))

    def test_wrong_type_server_rejected(self):
        body = MINIMAL.replace("server: http://localhost:8080", "server: 8080")
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("server", str(ctx.exception))

    def test_wrong_type_spec_rejected(self):
        body = MINIMAL.replace("spec: openapi.json", "spec: 1")
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("spec", str(ctx.exception))

    def test_wrong_type_results_dir_rejected(self):
        body = MINIMAL.replace("results_dir: test/results/cats", "results_dir: [a, b]")
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("results_dir", str(ctx.exception))

    def test_wrong_type_max_requests_per_minute_rejected(self):
        body = MINIMAL + "\ncats:\n  max_requests_per_minute: fast\n"
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("max_requests_per_minute", str(ctx.exception))

    def test_wrong_type_http_methods_rejected(self):
        body = MINIMAL + "\ncats:\n  http_methods: GET\n"
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("http_methods", str(ctx.exception))

    def test_wrong_type_token_cmd_rejected(self):
        body = MINIMAL.replace(
            'admin: {token_cmd: "echo tok"}', "admin: {token_cmd: 5}"
        )
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("token_cmd", str(ctx.exception))

    def test_non_mapping_auth_rejected(self):
        body = MINIMAL + "\nauth: bearer\n"
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("auth", str(ctx.exception))

    def test_non_mapping_hooks_rejected(self):
        body = MINIMAL + "\nhooks: [seed]\n"
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("hooks", str(ctx.exception))

    def test_non_mapping_cats_rejected(self):
        body = MINIMAL + "\ncats: none\n"
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("cats", str(ctx.exception))

    def test_retain_raw_report_wrong_type_rejected(self):
        # A quoted "false" must not silently coerce to True via bool(str).
        body = MINIMAL + '\nretain_raw_report: "false"\n'
        with self.assertRaises(cfg.ConfigError) as ctx:
            cfg.load_config(self._write(body))
        self.assertIn("retain_raw_report", str(ctx.exception))


class TestInitTemplate(unittest.TestCase):
    def test_rendered_config_round_trips(self):
        text = cfg.render_init_config(
            spec="api/openapi.json", server="http://localhost:3000",
            health_url="http://localhost:3000/health", results_dir="test/results/cats",
            rules="test/cats/false-positives.yaml")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local" / "cats").mkdir(parents=True)
            p = root / ".local" / "cats" / "config.yaml"
            p.write_text(text)
            c = cfg.load_config(p)
        self.assertEqual(c.server, "http://localhost:3000")
        self.assertEqual(c.health_url, "http://localhost:3000/health")
        self.assertEqual(c.keep_runs, 5)

    def test_template_documents_keep_runs(self):
        text = cfg.render_init_config(
            spec="s", server="http://h", health_url="http://h",
            results_dir="r", rules="f.yaml")
        self.assertIn("keep_runs:", text)

    def test_template_documents_validity_gates(self):
        # Both gates are only discoverable from the generated config; a project
        # that never learns `skip_paths` exists is the one that ships a campaign
        # which logs itself out (TMI #591).
        text = cfg.render_init_config(
            spec="s", server="http://h", health_url="http://h",
            results_dir="r", rules="f.yaml")
        for key in ("max_connection_error_pct:", "max_unauthenticated_pct:", "skip_paths:"):
            self.assertIn(key, text)

    def test_template_documents_hooks(self):
        text = cfg.render_init_config(
            spec="s", server="http://h", health_url="http://h",
            results_dir="r", rules="f.yaml")
        for key in ("seed:", "pre_run:", "post_run:", "token_cmd:"):
            self.assertIn(key, text)

    def test_starter_rules_are_stack_agnostic(self):
        from catslib import rules as R
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
            fh.write(cfg.INITIAL_RULES_YAML)
        loaded = R.load_rules(Path(fh.name))
        self.assertEqual([r.id for r in loaded], ["RATE_LIMIT_429", "CONNECTION_ERROR_999"])


if __name__ == "__main__":
    unittest.main()
