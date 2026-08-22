# tests/test_depscan_literals.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from depscanlib.literals import scan_literals
from depscanlib.walk import walk_repo
from repobuilder import build_repo


def scan(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        paths, _ = walk_repo(root)
        return scan_literals(root, paths)


class TestUrlLiterals(unittest.TestCase):
    def test_extracts_scheme_and_host(self):
        findings = scan({"client.go": 'const base = "https://api.stripe.com/v1"\n'})
        self.assertEqual(findings["url_literals"], [{
            "value": "https://api.stripe.com/v1", "scheme": "https",
            "host": "api.stripe.com", "file": "client.go", "line": 1}])

    def test_extracts_non_http_schemes(self):
        findings = scan({".env": "DATABASE_URL=postgres://user@db:5432/app\n"
                                 "AMQP=amqp://guest@rabbit:5672\n"})
        self.assertEqual(sorted(u["scheme"] for u in findings["url_literals"]),
                         ["amqp", "postgres"])

    def test_strips_trailing_quotes_and_punctuation(self):
        findings = scan({"a.py": 'URL = "https://example.com/x",\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://example.com/x")

    def test_ignores_schema_urls_in_json_documents(self):
        """A $schema pointer is a document identifier, not a dependency."""
        findings = scan({"c.json": json.dumps(
            {"$schema": "https://json-schema.org/draft/2020-12/schema"}) + "\n"})
        self.assertEqual(findings["url_literals"], [])


class TestHostPortLiterals(unittest.TestCase):
    def test_extracts_hostname_and_port(self):
        findings = scan({"docker-compose.yml":
            'services:\n  app:\n    environment:\n      REDIS: "redis:6379"\n'})
        self.assertEqual(findings["host_port_literals"], [{
            "host": "redis", "port": 6379,
            "file": "docker-compose.yml", "line": 4}])

    def test_extracts_ipv4_and_port(self):
        findings = scan({"conf.ini": "backend = 10.0.1.5:8080\n"})
        self.assertEqual(findings["host_port_literals"][0]["host"], "10.0.1.5")

    def test_ignores_a_bare_time_of_day(self):
        findings = scan({"README.md": "The standup is at 09:30 every day.\n"})
        self.assertEqual(findings["host_port_literals"], [])

    def test_ignores_an_image_tag(self):
        """postgres:16 is a version, not an endpoint."""
        findings = scan({"docker-compose.yml":
            "services:\n  db:\n    image: postgres:16\n"})
        self.assertEqual(findings["host_port_literals"], [])

    def test_port_is_an_integer_not_a_string(self):
        findings = scan({"a.env": "ADDR=db:5432\n"})
        self.assertIsInstance(findings["host_port_literals"][0]["port"], int)


class TestSecretShapedKeys(unittest.TestCase):
    def test_finds_secret_shaped_env_keys(self):
        findings = scan({".env": "STRIPE_API_KEY=sk_live_abc123\n"
                                 "DB_PASSWORD=hunter2\n"
                                 "LOG_LEVEL=debug\n"})
        self.assertEqual(sorted(k["name"] for k in findings["secret_shaped_keys"]),
                         ["DB_PASSWORD", "STRIPE_API_KEY"])

    def test_never_records_the_value(self):
        """A discovery skill that writes credentials into a contract is a leak.
        The scanner must not hand it one to write."""
        findings = scan({".env": "STRIPE_API_KEY=sk_live_abc123\n",
                         "app.py": 'TOKEN = "ghp_realtokenvalue"\n',
                         "k8s.yaml": "apiVersion: v1\nkind: Secret\n"
                                     "data:\n  password: aHVudGVyMg==\n"})
        blob = json.dumps(findings)
        for secret in ("sk_live_abc123", "ghp_realtokenvalue", "aHVudGVyMg=="):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, blob)

    def test_records_only_name_file_and_line(self):
        findings = scan({".env": "API_KEY=x\n"})
        self.assertEqual(sorted(findings["secret_shaped_keys"][0]),
                         ["file", "line", "name"])

    def test_matches_yaml_and_source_keys_not_only_env_files(self):
        findings = scan({"k8s.yaml": "apiVersion: v1\nkind: Secret\n"
                                     "stringData:\n  client_secret: x\n",
                         "app.py": 'PRIVATE_KEY = load()\n'})
        self.assertEqual(sorted(k["name"] for k in findings["secret_shaped_keys"]),
                         ["PRIVATE_KEY", "client_secret"])

    def test_key_shaped_words_in_prose_are_not_matched(self):
        findings = scan({"README.md":
            "The api key is supplied by the operator at deploy time.\n"})
        self.assertEqual(findings["secret_shaped_keys"], [])

    def test_findings_are_sorted_by_file_then_line(self):
        findings = scan({"b.env": "API_KEY=1\n", "a.env": "API_KEY=2\n"})
        self.assertEqual([k["file"] for k in findings["secret_shaped_keys"]],
                         ["a.env", "b.env"])


class TestBinaryAndLargeFiles(unittest.TestCase):
    def test_unreadable_bytes_do_not_crash_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n"})
            (Path(root) / "blob.bin").write_bytes(b"\x00\xff\xfe" * 100)
            paths, _ = walk_repo(root)
            self.assertEqual(scan_literals(root, paths)["url_literals"], [])


if __name__ == "__main__":
    unittest.main()
