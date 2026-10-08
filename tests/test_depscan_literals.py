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

    def test_redacts_userinfo_with_password(self):
        findings = scan({"compose.yml":
            "DSN: postgres://admin:sup3rs3cr3t@db:5432/x\n"})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "postgres://***@db:5432/x")
        self.assertEqual(findings["url_literals"][0]["host"], "db")

    def test_redacts_userinfo_without_password(self):
        findings = scan({"a.py": 'URL = "https://token@host/"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://***@host/")
        self.assertEqual(findings["url_literals"][0]["host"], "host")

    def test_leaves_urls_without_userinfo_unchanged(self):
        findings = scan({"client.go": 'const base = "https://api.stripe.com/v1"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://api.stripe.com/v1")

    def test_never_records_a_url_password(self):
        """A committed connection string with inline credentials must not
        reach the scan index verbatim -- url_literals is not exempt from
        the same rule secret_shaped_keys enforces for key values."""
        findings = scan({"compose.yml":
            "DSN: postgres://admin:sup3rs3cr3t@db:5432/x\n"})
        blob = json.dumps(findings)
        self.assertNotIn("sup3rs3cr3t", blob)

    def test_redacts_userinfo_password_containing_a_slash(self):
        """An unencoded '/' in the password must not defeat redaction or
        push the derived host off by one segment."""
        findings = scan({"a.env": "URL=https://user:pa/ss@host/x\n"})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://***@host/x")
        self.assertEqual(findings["url_literals"][0]["host"], "host")

    def test_redacts_secret_valued_query_parameter(self):
        findings = scan({"a.py":
            'URL = "https://api.example.com/v1?api_key=sk_live_abcDEF123"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://api.example.com/v1?api_key=***")

    def test_redacts_secret_valued_query_parameter_jdbc_form(self):
        """JDBC connection strings carry credentials as query parameters,
        not userinfo -- this is the standard Java database-URL shape."""
        findings = scan({"application.properties":
            "url=jdbc:mysql://dbhost:3306/app?user=root&password=hunter2xyz\n"})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "mysql://dbhost:3306/app?user=root&password=***")

    def test_redacts_secret_valued_fragment_parameter(self):
        findings = scan({"a.js":
            'const cb = "https://app.example.com/cb#access_token=eyJfaketok"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://app.example.com/cb#access_token=***")

    def test_leaves_non_secret_query_parameters_untouched(self):
        findings = scan({"a.py": 'URL = "https://example.com/x?page=2&sort=name"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://example.com/x?page=2&sort=name")

    def test_redacts_commonest_real_credential_query_params(self):
        """SECRET_NAME_RE alone catches ?api_key=/?password=/?token= but
        misses the commonest real-world credential parameter names -- Google
        API keys, Azure SAS signatures, AWS presigned-URL parameters, OAuth
        authorization codes. QUERY_SECRET_PARAM_NAMES must catch all of
        these, exact-match and case-insensitively."""
        cases = [
            ("?key=AIzaSyAAA", "?key=***"),
            ("?sig=SIGAAA", "?sig=***"),
            ("?X-Amz-Signature=abc123", "?X-Amz-Signature=***"),
            ("?code=oauthcodeAAA", "?code=***"),
            ("?pass=pw123", "?pass=***"),
            ("?pwd=pw456", "?pwd=***"),
            ("?auth=authAAA", "?auth=***"),
        ]
        for query, expected_suffix in cases:
            with self.subTest(query=query):
                findings = scan({"a.py": f'URL = "https://example.com/v1{query}"\n'})
                self.assertEqual(findings["url_literals"][0]["value"],
                                 f"https://example.com/v1{expected_suffix}")

    def test_leaves_a_non_secret_query_param_like_page_untouched(self):
        findings = scan({"a.py": 'URL = "https://example.com/v1?page=2"\n'})
        self.assertEqual(findings["url_literals"][0]["value"],
                         "https://example.com/v1?page=2")

    def test_never_records_a_query_or_fragment_secret_value(self):
        """A skill reading url_literals must never receive a query-string or
        fragment credential either -- the same guarantee as userinfo."""
        findings = scan({
            "a.py": 'URL = "https://api.example.com/v1?api_key=sk_live_abcDEF123"\n',
            "application.properties":
                "url=jdbc:mysql://dbhost:3306/app?user=root&password=hunter2xyz\n",
            "a.js": 'const cb = "https://app.example.com/cb#access_token=eyJfaketok"\n',
        })
        blob = json.dumps(findings)
        for secret in ("sk_live_abcDEF123", "hunter2xyz", "eyJfaketok"):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, blob)


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

    def test_ignores_a_schemeless_userinfo_credential(self):
        """bob:54321@example.com looks like host:port, but the digits before
        the '@' are a password, not a port."""
        findings = scan({"notes.txt": "bob:54321@example.com\n"})
        self.assertEqual(findings["host_port_literals"], [])


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
