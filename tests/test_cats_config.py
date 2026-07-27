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

    def test_skip_fuzzers_for_extension_shape_validated(self):
        body = MINIMAL + """
cats:
  skip_fuzzers_for_extension:
    - {extension: x-public-endpoint, value: "true", fuzzers: [BypassAuthentication]}
"""
        c = cfg.load_config(self._write(body))
        self.assertEqual(c.cats.skip_fuzzers_for_extension[0]["fuzzers"],
                         ["BypassAuthentication"])

    def test_unsupported_version_rejected(self):
        body = MINIMAL.replace("version: 1", "version: 99")
        with self.assertRaises(cfg.ConfigError):
            cfg.load_config(self._write(body))


if __name__ == "__main__":
    unittest.main()
