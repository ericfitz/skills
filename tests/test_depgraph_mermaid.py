# tests/test_depgraph_mermaid.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.mermaid import to_mermaid


def graph(names, edges=None):
    return {"nodes": [{"id": f"package:{n}", "name": n, "category": "package",
                       "lifecycle": "build"} for n in names],
            "edges": edges or [], "cycles": []}


class TestMermaid(unittest.TestCase):
    def test_emits_a_flowchart_with_opaque_ids_and_labelled_nodes(self):
        out = to_mermaid(graph(["left-pad"]))
        self.assertTrue(out["mermaid"].startswith("flowchart LR"))
        self.assertIn('["left-pad"]', out["mermaid"])
        self.assertFalse(out["degraded"])

    def test_names_that_are_not_valid_mermaid_ids_still_work(self):
        """Verified against mmdc: opaque ids plus quoted labels render for all
        of these; using the name as the id does not."""
        for name in ("@babel/core", "github.com/sony/gobreaker", "x[1]", "a b (c)"):
            with self.subTest(name=name):
                out = to_mermaid(graph([name]))
                self.assertIn(f'["{name}"]', out["mermaid"])

    def test_a_double_quote_in_a_name_is_escaped(self):
        """A raw quote breaks Mermaid parsing; #quot; is the working escape."""
        out = to_mermaid(graph(['has"quote']))
        self.assertNotIn('has"quote', out["mermaid"])
        self.assertIn("has#quot;quote", out["mermaid"])

    def test_hash_and_angle_brackets_are_left_alone(self):
        out = to_mermaid(graph(["has#hash", "has<tag>"]))
        self.assertIn('["has#hash"]', out["mermaid"])
        self.assertIn('["has<tag>"]', out["mermaid"])

    def test_edges_are_emitted_between_the_opaque_ids(self):
        g = graph(["a", "b"], edges=[{"from": "package:a", "to": "package:b",
                                      "kind": "depends_on", "lifecycle": "build"}])
        out = to_mermaid(g)
        self.assertRegex(out["mermaid"], r"n\d+ --> n\d+")

    def test_an_edge_to_a_node_not_in_the_graph_is_skipped(self):
        g = graph(["a"], edges=[{"from": "package:a", "to": "package:ghost",
                                 "kind": "depends_on", "lifecycle": "build"}])
        self.assertNotIn("-->", to_mermaid(g)["mermaid"])

    def test_output_is_deterministic(self):
        g = graph(["b", "a"])
        self.assertEqual(to_mermaid(g)["mermaid"], to_mermaid(g)["mermaid"])


class TestNodeCap(unittest.TestCase):
    def test_above_the_cap_it_degrades_and_says_so(self):
        """Silent truncation would read as 'this is the whole graph'."""
        out = to_mermaid(graph([f"p{i}" for i in range(70)]), cap=60)
        self.assertTrue(out["degraded"])
        self.assertIsNone(out["mermaid"])
        self.assertIn("60", out["reason"])
        self.assertEqual(out["node_count"], 70)

    def test_at_the_cap_it_does_not_degrade(self):
        out = to_mermaid(graph([f"p{i}" for i in range(60)]), cap=60)
        self.assertFalse(out["degraded"])
        self.assertIsNotNone(out["mermaid"])


if __name__ == "__main__":
    unittest.main()
