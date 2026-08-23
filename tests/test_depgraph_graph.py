# tests/test_depgraph_graph.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.graph import build_graph


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

    def test_an_edge_to_an_unknown_id_is_dropped_not_dangling(self):
        g = build_graph(merged(service=[dep("service:a", "a", related=["service:ghost"])]))
        self.assertEqual(g["edges"], [])

    def test_edges_are_sorted_and_deduplicated(self):
        g = build_graph(merged(service=[
            dep("service:a", "a", related=["service:b", "service:b"]),
            dep("service:b", "b")]))
        self.assertEqual(len(g["edges"]), 1)


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
        artifact #50 and #51 consume)."""
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

        self.assertEqual(set(out), {"inventory", "graph", "mermaid"})
        self.assertEqual(out["inventory"]["categories"]["service"]["dependencies"],
                         [dep("service:pg", "postgres")])


if __name__ == "__main__":
    unittest.main()
