# tests/test_idmap_cli.py
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "dependency-model" / "scripts" / "idmap.py"
TMI = REPO / "tests" / "fixtures" / "dependency_model" / "topology_tmi.json"


def run(path, *flags, umask=None):
    preexec = None if umask is None else (lambda: os.umask(umask))
    return subprocess.run([sys.executable, str(SCRIPT), str(path), *flags],
                          capture_output=True, text=True, preexec_fn=preexec)


def run_doc(doc, *flags):
    """Run on `doc` in a fresh temp dir; return (result, dir listing after)."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "topology.json"
        path.write_text(doc if isinstance(doc, str) else json.dumps(doc))
        result = run(path, *flags)
        return result, sorted(p.name for p in Path(tmp).iterdir())


def topo(components=(), real=(), ext=()):
    return {"components": [{"name": n} for n in components],
            "real_dependencies": [{"name": n} for n in real],
            "external_third_parties": [{"name": n} for n in ext]}


class IdmapCliTest(unittest.TestCase):
    def test_tmi_topology(self):
        result = run(TMI)
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.assertIn({"id": "service:nats", "name": "nats (JetStream)",
                       "source": "real_dependencies"}, doc["services"])
        oauth = [s for s in doc["services"]
                 if s["id"] == "service:oauth-2.0-oidc-identity-providers"]
        self.assertEqual(len(oauth), 1)
        self.assertEqual(oauth[0]["source"], "external_third_parties")
        ids = [c["id"] for c in doc["components"]]
        self.assertIn("component:tmi-server", ids)
        self.assertIn("component:migrate-dbtool-genconfig-worker-probe-dedup-group-members", ids)
        self.assertEqual(doc["skipped"], [])
        for key in ("components", "services"):
            got = [e["id"] for e in doc[key]]
            self.assertEqual(got, sorted(got))
        self.assertTrue(result.stdout.endswith("\n"))

    def test_name_in_both_lists_appears_once_as_real_dependency(self):
        result, _ = run_doc(topo(real=["redis"], ext=["redis", "stripe"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        services = json.loads(result.stdout)["services"]
        self.assertEqual(services, [
            {"id": "service:redis", "name": "redis", "source": "real_dependencies"},
            {"id": "service:stripe", "name": "stripe", "source": "external_third_parties"},
        ])

    def test_service_matching_a_component_is_skipped(self):
        result, _ = run_doc(topo(components=["tmi-server", "api"], real=["tmi-server", "redis"],
                                 ext=["api"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        doc = json.loads(result.stdout)
        self.assertEqual([s["name"] for s in doc["services"]], ["redis"])
        self.assertEqual([k["name"] for k in doc["skipped"]], ["api", "tmi-server"])
        self.assertIn("component:api", doc["skipped"][0]["reason"])
        self.assertIn("component:tmi-server", doc["skipped"][1]["reason"])

    def test_collision_fallback(self):
        result, _ = run_doc(topo(real=["db (a)", "db (b)"]))
        self.assertEqual(result.returncode, 0, result.stderr)
        ids = {s["name"]: s["id"] for s in json.loads(result.stdout)["services"]}
        self.assertEqual(ids, {"db (a)": "service:db-a", "db (b)": "service:db-b"})

    def test_unresolvable_collision_exits_2_and_writes_nothing(self):
        result, files = run_doc(topo(real=["Redis", "redis"]), "--write")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))
        self.assertIn("Redis", result.stderr)
        self.assertIn("redis", result.stderr)
        self.assertEqual(files, ["topology.json"])

    def test_unsluggable_name_exits_2(self):
        result, files = run_doc(topo(real=["()"]), "--write")
        self.assertEqual(result.returncode, 2)
        self.assertIn("()", json.loads(result.stderr)["error"])
        self.assertEqual(files, ["topology.json"])

    def test_entry_without_name_exits_2(self):
        for doc in ({"components": [{"role": "x"}]},
                    {"real_dependencies": [{"name": 3}]},
                    {"external_third_parties": ["redis"]}):
            with self.subTest(doc=doc):
                result, _ = run_doc(doc)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error", json.loads(result.stderr))

    def test_list_that_is_not_a_list_exits_2(self):
        for key in ("components", "real_dependencies", "external_third_parties"):
            for value in ({"name": "x"}, 0, False, "", "redis"):
                with self.subTest(key=key, value=value):
                    result, _ = run_doc({key: value})
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(key, json.loads(result.stderr)["error"])

    def test_null_lists_are_empty(self):
        result, _ = run_doc({"components": None, "real_dependencies": None,
                             "external_third_parties": None})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"components": [], "services": [], "skipped": []})

    def test_non_object_entry_says_so(self):
        result, _ = run_doc({"external_third_parties": ["redis"]})
        self.assertEqual(result.returncode, 2)
        self.assertIn("is not an object", result.stderr)

    def test_invalid_json_exits_2(self):
        result, files = run_doc("{not json", "--write")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))
        self.assertEqual(files, ["topology.json"])

    def test_unreadable_file_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(Path(tmp) / "missing.json")
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))

    def test_non_object_exits_2(self):
        result, _ = run_doc([1, 2])
        self.assertEqual(result.returncode, 2)
        self.assertIn("error", json.loads(result.stderr))

    def test_missing_lists_are_empty(self):
        result, _ = run_doc({})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout),
                         {"components": [], "services": [], "skipped": []})

    def test_written_mode_follows_umask(self):
        """ids.json gets the mode any new file would: 0666 less the umask."""
        for umask, mode in ((0o022, 0o644), (0o077, 0o600), (0o002, 0o664)):
            with self.subTest(umask=oct(umask)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "topology.json"
                path.write_text(json.dumps(topo(components=["api"])))
                result = run(path, "--write", umask=umask)
                self.assertEqual(result.returncode, 0, result.stderr)
                written = Path(tmp) / "ids.json"
                self.assertEqual(stat.S_IMODE(written.stat().st_mode), mode)

    def test_write_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology.json"
            path.write_text(TMI.read_text())
            first = run(path, "--write")
            self.assertEqual(first.returncode, 0, first.stderr)
            out = Path(tmp) / "ids.json"
            self.assertEqual(Path(first.stdout.strip()).resolve(), out.resolve())
            before = out.read_bytes()
            second = run(path, "--write")
            self.assertEqual(second.stdout, first.stdout)
            self.assertEqual(out.read_bytes(), before)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()),
                             ["ids.json", "topology.json"])
            self.assertEqual(json.loads(before), json.loads(run(path).stdout))


if __name__ == "__main__":
    unittest.main()
