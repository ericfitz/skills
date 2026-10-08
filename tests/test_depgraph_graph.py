# tests/test_depgraph_graph.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.graph import build_graph, link_graph, slug


def dep(id_, name, lifecycle="run", related=None, depends=None):
    d = {"id": id_, "name": name, "lifecycle": lifecycle,
         "evidence": [], "related_ids": related or [], "details": {}}
    if depends is not None:
        d["details"]["depends_on"] = depends
    return d


def merged(**cats):
    return {"categories": {k: {"status": "discovered", "dependencies": v,
                               "assumptions": []} for k, v in cats.items()}}


class TestNodes(unittest.TestCase):
    def test_one_node_per_dependency_carrying_category_and_lifecycle(self):
        g = build_graph(merged(service=[dep("service:pg", "postgres")]))
        self.assertEqual(g["nodes"], [{"id": "service:pg", "name": "postgres",
                                       "category": "service", "lifecycle": "run"}])

    def test_nodes_are_sorted_by_id(self):
        g = build_graph(merged(service=[dep("service:b", "b"), dep("service:a", "a")]))
        self.assertEqual([n["id"] for n in g["nodes"]], ["service:a", "service:b"])


class TestEdges(unittest.TestCase):
    def test_depends_on_edges_come_from_package_details(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build")]))
        self.assertEqual(g["edges"], [{"from": "package:a-1", "to": "package:b-2",
                                       "kind": "depends_on", "lifecycle": "build"}])

    def test_relates_to_edges_come_from_related_ids(self):
        g = build_graph(merged(
            service=[dep("service:pg", "postgres", related=["network:pg-5432"])],
            network=[dep("network:pg-5432", "postgres:5432")]))
        self.assertEqual(g["edges"], [{"from": "service:pg", "to": "network:pg-5432",
                                       "kind": "relates_to", "lifecycle": "run"}])

    def test_the_two_edge_kinds_are_not_conflated(self):
        """A consumer asking what must be reachable at runtime filters to run
        edges; one asking what we build against filters to build."""
        g = build_graph(merged(
            package=[dep("package:a-1", "a", "build", depends=["package:b-2"]),
                     dep("package:b-2", "b", "build")],
            service=[dep("service:pg", "pg", related=["network:x"])],
            network=[dep("network:x", "x")]))
        kinds = {e["kind"] for e in g["edges"]}
        self.assertEqual(kinds, {"depends_on", "relates_to"})

    def test_an_edge_to_an_unknown_id_is_reported_unresolved_not_dropped(self):
        g, unresolved = link_graph(merged(service=[dep("service:a", "a", related=["service:ghost"]),
                                        dep("service:b", "b", depends=["service:gone"])]))
        self.assertEqual(g["edges"], [])
        self.assertEqual(unresolved, [
            {"from": "service:a", "to": "service:ghost", "kind": "relates_to"},
            {"from": "service:b", "to": "service:gone", "kind": "depends_on"}])

    def test_a_case_or_underscore_variant_resolves_to_the_real_node(self):
        g, unresolved = link_graph(merged(
            network=[dep("network:nats-4222", "nats", related=["config:TMI_NATS_URL"])],
            config=[dep("config:tmi-nats-url", "TMI_NATS_URL")]))
        self.assertEqual([(e["from"], e["to"]) for e in g["edges"]],
                         [("network:nats-4222", "config:tmi-nats-url")])
        self.assertEqual(unresolved, [])

    def test_an_ambiguous_canonical_match_stays_unresolved(self):
        g, unresolved = link_graph(merged(
            service=[dep("service:a", "a", related=["config:X-Y"])],
            config=[dep("config:x_y", "x_y"), dep("config:x-y", "x-y")]))
        self.assertEqual(g["edges"], [])
        self.assertEqual(len(unresolved), 1)

    def test_edges_are_sorted_and_deduplicated(self):
        g = build_graph(merged(service=[
            dep("service:a", "a", related=["service:b", "service:b"]),
            dep("service:b", "b")]))
        self.assertEqual(len(g["edges"]), 1)


class TestComponents(unittest.TestCase):
    """#83: first-party components from the topology contract are graph nodes."""

    def test_slug_follows_the_categories_md_rule(self):
        self.assertEqual(slug("tooling CLIs"), "tooling-clis")
        self.assertEqual(slug("TMI_NATS/url.v2"), "tmi-nats-url.v2")

    def test_each_component_is_a_run_node_outside_the_inventory(self):
        g = build_graph(merged(service=[dep("service:pg", "postgres")]),
                        [{"name": "tmiserver"}, {"name": "tooling CLIs"}])
        self.assertEqual([n for n in g["nodes"] if n["category"] == "component"], [
            {"id": "component:tmiserver", "name": "tmiserver",
             "category": "component", "lifecycle": "run"},
            {"id": "component:tooling-clis", "name": "tooling CLIs",
             "category": "component", "lifecycle": "run"}])

    def test_a_link_to_a_component_id_resolves(self):
        g, unresolved = link_graph(
            merged(network=[dep("network:api-8080", "api:8080", related=["component:api"])]),
            [{"name": "api"}])
        self.assertEqual(unresolved, [])
        self.assertEqual(g["edges"], [{"from": "network:api-8080", "to": "component:api",
                                       "kind": "relates_to", "lifecycle": "run"}])

    def test_a_service_link_naming_a_component_resolves_to_the_component(self):
        """The system's own listener is not a service (categories.md), so
        service:<x> written for a first-party component means component:<x>."""
        g, unresolved = link_graph(
            merged(network=[dep("network:api-8080", "api:8080", related=["service:api"])]),
            [{"name": "api"}])
        self.assertEqual(unresolved, [])
        self.assertEqual(g["edges"][0]["to"], "component:api")

    def test_a_real_service_node_wins_over_a_same_named_component(self):
        g, unresolved = link_graph(
            merged(service=[dep("service:api", "api")],
                   network=[dep("network:api-8080", "api:8080", related=["service:api"])]),
            [{"name": "api"}])
        self.assertEqual(unresolved, [])
        self.assertEqual(g["edges"][0]["to"], "service:api")

    def test_without_components_a_service_link_to_a_non_node_stays_unresolved(self):
        _, unresolved = link_graph(
            merged(network=[dep("network:api-8080", "api:8080", related=["service:api"])]))
        self.assertEqual(unresolved, [{"from": "network:api-8080", "to": "service:api",
                                       "kind": "relates_to"}])


class TestCycles(unittest.TestCase):
    def test_a_two_node_cycle_is_reported(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build", depends=["package:a-1"])]))
        self.assertEqual(len(g["cycles"]), 1)
        self.assertEqual(sorted(g["cycles"][0]), ["package:a-1", "package:b-2"])

    def test_an_acyclic_graph_reports_none(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build")]))
        self.assertEqual(g["cycles"], [])

    def test_a_self_loop_is_a_cycle(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:a-1"])]))
        self.assertEqual(g["cycles"], [["package:a-1"]])

    def test_cycles_are_deterministic(self):
        m = merged(package=[dep("package:a-1", "a", "build", depends=["package:b-2"]),
                            dep("package:b-2", "b", "build", depends=["package:a-1"])])
        self.assertEqual(build_graph(m)["cycles"], build_graph(m)["cycles"])

    def test_a_symmetric_relates_to_pair_is_not_reported_as_a_cycle(self):
        """A2: cycle detection walks the depends_on adjacency only.
        related_ids links are routinely symmetric, so walking the combined
        edge set would report a 2-cycle for every service<->network
        association -- noise that would drown any real depends_on cycle."""
        g = build_graph(merged(
            service=[dep("service:pg", "pg", related=["network:x"])],
            network=[dep("network:x", "x", related=["service:pg"])]))
        self.assertEqual({e["kind"] for e in g["edges"]}, {"relates_to"})
        self.assertEqual(len(g["edges"]), 2)
        self.assertEqual(g["cycles"], [])


class TestInvalidDependency(unittest.TestCase):
    def test_missing_lifecycle_raises_invalid_dependency_not_a_keyerror(self):
        from depgraphlib.graph import InvalidDependencyError

        bad = {"id": "service:pg", "name": "postgres",
               "evidence": [], "related_ids": [], "details": {}}
        with self.assertRaises(InvalidDependencyError):
            build_graph(merged(service=[bad]))

    def test_cli_reports_a_missing_lifecycle_as_a_clean_exit_2_not_a_traceback(self):
        """A4: depgraph.py's own docstring documents only exit 0 and exit 2.
        A dependency missing a required field must fail the same clean way
        an unreadable envelope does, not crash with an uncaught KeyError."""
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr

        import depgraph

        bad = {"id": "service:pg", "name": "postgres",
               "evidence": [], "related_ids": [], "details": {}}
        envelope = {"contract_version": "1.0.0", "target": "/r",
                   "categories": {"service": {"status": "discovered",
                                              "dependencies": [bad],
                                              "assumptions": []}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(envelope, f)
            path = f.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        buf = io.StringIO()
        with redirect_stderr(buf):
            code = depgraph.main([path, "--indent", "0"])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(buf.getvalue()))

    def _run_cli_with_envelope(self, envelope):
        """Write envelope to a temp file, run depgraph.main over it, and
        return (exit_code, stderr_text)."""
        import io
        import json
        import tempfile
        from contextlib import redirect_stderr

        import depgraph

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(envelope, f)
            path = f.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        buf = io.StringIO()
        with redirect_stderr(buf):
            code = depgraph.main([path, "--indent", "0"])
        return code, buf.getvalue()

    def test_a_bare_string_dependency_is_exit_2_not_a_traceback(self):
        """I6: this shape crashes in merge.py before build_graph's own
        InvalidDependencyError ever runs, so widening _require alone would
        not catch it."""
        import json

        envelope = {"contract_version": "1.0.0", "target": "/r",
                   "categories": {"service": {"status": "discovered",
                                              "dependencies": ["just-a-string"],
                                              "assumptions": []}}}
        code, err = self._run_cli_with_envelope(envelope)
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_a_null_details_object_is_exit_2_not_a_traceback(self):
        import json

        bad = {"id": "service:pg", "name": "postgres", "lifecycle": "run",
               "evidence": [], "related_ids": [], "details": None}
        envelope = {"contract_version": "1.0.0", "target": "/r",
                   "categories": {"service": {"status": "discovered",
                                              "dependencies": [bad],
                                              "assumptions": []}}}
        code, err = self._run_cli_with_envelope(envelope)
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_a_non_dict_category_value_is_exit_2_not_a_traceback(self):
        import json

        envelope = {"contract_version": "1.0.0", "target": "/r",
                   "categories": {"service": "oops"}}
        code, err = self._run_cli_with_envelope(envelope)
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))


class TestCliOutputShape(unittest.TestCase):
    def test_contract_bound_keys_match_the_synthesis_contract(self):
        """depgraph.py's contract-bound keys -- inventory and graph -- must
        already appear under the same names and nesting synthesis.schema.json
        uses, so the synthesize skill that adds contract_version/target/
        health/assumptions is purely additive. mermaid is a deliberate extra:
        a working-document rendering the report skill consumes, which the
        contract itself does not carry (D4 keeps presentation out of the
        artifact #50 and #51 consume). unresolved is the other extra: links
        synthesize must reconcile before it builds the contract."""
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout

        import depgraph

        envelope = {"contract_version": "1.0.0", "target": "/r",
                   "categories": {"service": {"status": "discovered",
                                              "dependencies": [dep("service:pg", "postgres")],
                                              "assumptions": []}}}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(envelope, f)
            path = f.name
        self.addCleanup(lambda: Path(path).unlink(missing_ok=True))

        buf = io.StringIO()
        with redirect_stdout(buf):
            depgraph.main([path, "--indent", "0"])
        out = json.loads(buf.getvalue())

        self.assertEqual(set(out), {"inventory", "components", "graph", "mermaid", "unresolved"})
        self.assertEqual(set(out["graph"]), {"nodes", "edges", "cycles"})
        self.assertEqual(out["inventory"]["categories"]["service"]["dependencies"],
                         [dep("service:pg", "postgres")])
        self.assertEqual(out["components"], [])

    def test_topology_components_become_contract_shaped_components_and_nodes(self):
        import io
        import json
        import tempfile
        from contextlib import redirect_stdout

        import depgraph

        envelope = {"contract_version": "1.0.0", "target": "/r",
                    "categories": {"network": {"status": "discovered",
                                               "dependencies": [dep("network:api-8080", "api:8080",
                                                                    related=["service:api"])],
                                               "assumptions": []}}}
        topology = {"components": [{"name": "api", "role": "HTTP API",
                                    "evidence": ["cmd/api/main.go:1"]}]}
        paths = []
        for doc in (envelope, topology):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                json.dump(doc, f)
                paths.append(f.name)
        for path in paths:
            self.addCleanup(lambda p=path: Path(p).unlink(missing_ok=True))

        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(depgraph.main([paths[0], "--topology", paths[1], "--indent", "0"]), 0)
        out = json.loads(buf.getvalue())
        self.assertEqual(out["components"], [{"id": "component:api", "name": "api",
                                              "role": "HTTP API",
                                              "evidence": ["cmd/api/main.go:1"]}])
        self.assertIn({"id": "component:api", "name": "api", "category": "component",
                       "lifecycle": "run"}, out["graph"]["nodes"])
        self.assertEqual(out["unresolved"], [])
        self.assertIn('[["api"]]', out["mermaid"]["mermaid"])


if __name__ == "__main__":
    unittest.main()
