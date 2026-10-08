# tests/test_depgraph_health.py
import json
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "dependency-model" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from depgraphlib.graph import link_graph
from depgraphlib.health import derive_health
from depgraphlib.merge import merge_envelopes

EXAMPLES = REPO / "dependency-model" / "references" / "contracts" / "examples"


def dep(id_, lifecycle="run", related=None, evidence=None, resilience=None, **details):
    return {"id": id_, "name": id_.split(":", 1)[1], "lifecycle": lifecycle,
            "evidence": evidence or [f"{id_}.go:1"], "related_ids": related or [],
            "resilience": resilience or {}, "details": details}


def document(*deps, components=()):
    cats = {}
    for d in deps:
        cats.setdefault(d["id"].split(":", 1)[0], []).append(d)
    merged = merge_envelopes([{"target": "t", "categories": {
        c: {"status": "discovered", "dependencies": v}}} for c, v in cats.items()])
    graph, _ = link_graph(merged, [{"name": c} for c in components])
    return {"inventory": merged, "graph": graph}


def conditions(result, service_id):
    entry = next(h for h in result["health"] if h["service_id"] == service_id)
    return [(c["kind"], c["subject_id"]) for c in entry["conditions"]]


class TestDerivationRules(unittest.TestCase):
    def test_service_gets_null_timeout_bound_when_nothing_declared(self):
        r = derive_health(document(dep("service:pg")))
        [c] = r["health"][0]["conditions"]
        self.assertEqual((c["kind"], c["expectation"], c["required_for"]), ("bound", None, []))
        self.assertEqual(c["evidence"], ["service:pg.go:1"])

    def test_declared_timeout_and_retry_become_bounds_with_expectation(self):
        r = derive_health(document(dep("service:pg", resilience={
            "timeout": {"value": "5s", "evidence": ["db.go:4"]},
            "retry": {"description": "3x", "evidence": ["db.go:9"]}})))
        exps = [c["expectation"] for c in r["health"][0]["conditions"]]
        self.assertEqual(exps, [{"value": "retry: 3x", "evidence": ["db.go:9"]},
                                {"value": "timeout: 5s", "evidence": ["db.go:4"]}])

    def test_linked_dependencies_contribute_by_kind(self):
        r = derive_health(document(
            dep("service:api", related=["service:pg", "network:api-443"]),
            dep("service:pg"),
            dep("config:pg-url", related=["service:api"], mechanism="env"),
            dep("security:api-key", related=["service:api"], kind="secret"),
            dep("platform:mem", related=["service:api"], kind="memory",
                declared_value="512Mi"),
            dep("network:api-443")))
        self.assertEqual(conditions(r, "service:api"), [
            ("presence", "config:pg-url"), ("presence", "network:api-443"),
            ("presence", "security:api-key"), ("bound", "platform:mem"),
            ("bound", "service:api"), ("upstream_health", "service:pg")])
        mem = next(c for c in r["health"][0]["conditions"]
                   if c["subject_id"] == "platform:mem")
        self.assertEqual(mem["expectation"],
                         {"value": "512Mi", "evidence": ["platform:mem.go:1"]})

    def test_packages_build_deps_and_runtime_versions_never_contribute(self):
        r = derive_health(document(
            dep("service:api", related=["package:lib", "security:ci-token",
                                        "platform:go-version"]),
            dep("package:lib"),
            dep("security:ci-token", lifecycle="build", kind="secret"),
            dep("platform:go-version", kind="runtime-version")))
        self.assertEqual(conditions(r, "service:api"), [("bound", "service:api")])
        self.assertEqual(r["unattached"], [])

    def test_build_service_gets_no_entry(self):
        self.assertEqual(derive_health(document(dep("service:ci", lifecycle="build")))["health"], [])

    def test_unattached_lists_failable_deps_with_no_service_link(self):
        r = derive_health(document(
            dep("config:flags", mechanism="remote"), dep("config:log-level", mechanism="env"),
            dep("network:dns-53"), dep("platform:cpu", kind="cpu"),
            dep("platform:img", kind="runtime-version"), dep("package:lib")))
        self.assertEqual(r, {"health": [],
                             "unattached": ["config:flags", "network:dns-53", "platform:cpu"]})

    def test_link_in_either_direction_yields_one_condition(self):
        r = derive_health(document(dep("service:redis", related=["network:redis-6379"]),
                                   dep("network:redis-6379", related=["service:redis"])))
        self.assertEqual(conditions(r, "service:redis"),
                         [("presence", "network:redis-6379"), ("bound", "service:redis")])


class TestComponentAnchors(unittest.TestCase):
    """#83: a first-party component is a health anchor keyed like a service."""

    def test_component_entry_gathers_its_links_and_has_no_own_bounds(self):
        r = derive_health(document(
            dep("network:api-8080", related=["component:api"], direction="inbound"),
            dep("service:pg", related=["component:api"]),
            dep("platform:api-mem", related=["component:api"], kind="memory"),
            components=["api"]))
        self.assertEqual(conditions(r, "component:api"), [
            ("presence", "network:api-8080"), ("bound", "platform:api-mem"),
            ("upstream_health", "service:pg")])
        self.assertNotIn("network:api-8080", r["unattached"])

    def test_a_service_link_written_as_service_attaches_to_the_component(self):
        r = derive_health(document(
            dep("network:api-8080", related=["service:api"]), components=["api"]))
        self.assertEqual(conditions(r, "component:api"), [("presence", "network:api-8080")])
        self.assertEqual(r["unattached"], [])

    def test_a_component_nothing_links_to_gets_no_entry(self):
        r = derive_health(document(dep("network:dns-53"), components=["api", "worker"]))
        self.assertEqual(r, {"health": [], "unattached": ["network:dns-53"]})

    def test_a_component_never_contributes_a_condition_to_a_service(self):
        r = derive_health(document(dep("service:pg", related=["component:api"]),
                                   components=["api"]))
        self.assertEqual(conditions(r, "service:pg"), [("bound", "service:pg")])

    def test_network_paths_chained_through_network_paths_attach(self):
        """An ingress fronting a listener is still the path to the component
        behind it: alb -> listener -> component, nodeport -> listener."""
        r = derive_health(document(
            dep("network:api-8080", related=["component:api"]),
            dep("network:alb-443", related=["network:api-8080"]),
            dep("network:dns-cname", related=["network:alb-443"]),
            dep("network:nodeport-30080", related=["network:api-8080"]),
            components=["api"]))
        self.assertEqual(conditions(r, "component:api"), [
            ("presence", "network:alb-443"), ("presence", "network:api-8080"),
            ("presence", "network:dns-cname"), ("presence", "network:nodeport-30080")])
        self.assertEqual(r["unattached"], [])

    def test_the_chain_walk_does_not_pass_through_a_non_network_node(self):
        r = derive_health(document(
            dep("network:api-8080", related=["component:api", "config:port"]),
            dep("config:port", related=["network:other-9090"], mechanism="env"),
            dep("network:other-9090"),
            components=["api"]))
        self.assertEqual(conditions(r, "component:api"),
                         [("presence", "network:api-8080")])
        self.assertEqual(r["unattached"], ["network:other-9090"])


class TestDeterminism(unittest.TestCase):
    def test_shuffled_input_gives_identical_output(self):
        doc = document(
            dep("service:api", related=["service:pg", "network:a", "config:b"]),
            dep("service:pg", related=["network:pg", "security:pw"]),
            dep("network:a"), dep("network:pg"), dep("config:b", mechanism="env"),
            dep("security:pw", kind="secret"), dep("platform:cpu", kind="cpu"))
        expected = json.dumps(derive_health(doc), sort_keys=True)
        rng = random.Random(7)
        for _ in range(5):
            shuffled = json.loads(json.dumps(doc))
            rng.shuffle(shuffled["graph"]["edges"])
            rng.shuffle(shuffled["graph"]["nodes"])
            for block in shuffled["inventory"]["categories"].values():
                rng.shuffle(block["dependencies"])
            self.assertEqual(json.dumps(derive_health(shuffled), sort_keys=True), expected)


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / "health.py"), *args],
                              capture_output=True, text=True)

    def test_output_validates_as_synthesis_health(self):
        synthesis = json.loads((EXAMPLES / "synthesis.example.json").read_text())
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "in.json"
            src.write_text(json.dumps(synthesis))
            first, second = self.run_cli(str(src)), self.run_cli(str(src))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            synthesis["health"] = json.loads(first.stdout)["health"]
            self.assertTrue(synthesis["health"])
            out = Path(tmp) / "out.json"
            out.write_text(json.dumps(synthesis))
            check = subprocess.run([sys.executable, str(SCRIPTS / "validate.py"),
                                    "synthesis", str(out)], capture_output=True, text=True)
        self.assertEqual(check.returncode, 0, check.stdout + check.stderr)

    def test_non_depgraph_input_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}")
            self.assertEqual(self.run_cli(str(bad)).returncode, 2)
            self.assertEqual(self.run_cli(str(Path(tmp) / "missing.json")).returncode, 2)


if __name__ == "__main__":
    unittest.main()
