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


class TestComponentShape(unittest.TestCase):
    def test_a_component_node_gets_the_subroutine_shape(self):
        g = graph(["lib"])
        g["nodes"].append({"id": "component:api", "name": "api", "category": "component",
                           "lifecycle": "run"})
        out = to_mermaid(g)["mermaid"]
        self.assertIn('[["api"]]', out)
        self.assertIn('["lib"]', out)


class TestNodeCap(unittest.TestCase):
    def test_above_the_cap_it_degrades_and_says_so(self):
        """Silent truncation would read as 'this is the whole graph'."""
        g = graph([])
        g["nodes"] = [{"id": f"service:s{i}", "name": f"s{i}", "category": "service",
                       "lifecycle": "run"} for i in range(70)]
        out = to_mermaid(g, cap=60)
        self.assertTrue(out["degraded"])
        self.assertIsNone(out["mermaid"])
        self.assertIn("60", out["reason"])
        self.assertEqual(out["node_count"], 70)

    def test_at_the_cap_it_does_not_degrade(self):
        out = to_mermaid(graph([f"p{i}" for i in range(60)]), cap=60)
        self.assertFalse(out["degraded"])
        self.assertIsNotNone(out["mermaid"])


def big_graph(n_packages, services=("pg", "redis"), components=("api",)):
    nodes = [{"id": f"package:p{i}", "name": f"p{i}", "category": "package",
              "lifecycle": "build"} for i in range(n_packages)]
    nodes += [{"id": f"component:{c}", "name": c, "category": "component",
               "lifecycle": "run"} for c in components]
    nodes += [{"id": f"service:{s}", "name": s, "category": "service",
               "lifecycle": "run"} for s in services]
    return {"nodes": nodes, "edges": [], "cycles": []}


def edge(a, b, kind="depends_on"):
    return {"from": a, "to": b, "kind": kind, "lifecycle": "build"}


class TestCollapsedView(unittest.TestCase):
    def test_full_view_flag(self):
        out = to_mermaid(graph(["a", "b"]))
        self.assertEqual(out["view"], "full")
        self.assertEqual(out["collapsed"], {})

    def test_collapsed_keeps_components_and_services(self):
        g = big_graph(61)
        g["edges"] = [edge("package:p0", "service:pg"), edge("package:p1", "service:pg"),
                      edge("package:p0", "package:p1"), edge("package:p2", "package:p3")]
        out = to_mermaid(g)
        self.assertEqual(out["view"], "collapsed")
        self.assertFalse(out["degraded"])
        self.assertEqual(out["collapsed"], {"package": 61})
        self.assertEqual(out["node_count"], 64)
        self.assertIn("64", out["reason"])
        self.assertIn("60", out["reason"])
        text = out["mermaid"]
        self.assertEqual(text.count('["package (61)"]'), 1)
        self.assertIn('[["api"]]', text)
        self.assertIn('["pg"]', text)
        self.assertIn('["redis"]', text)
        ids = {line.split("[")[0].strip(): line for line in text.splitlines()
               if "[" in line}
        rollup = next(i for i, line in ids.items() if "package (61)" in line)
        pg = next(i for i, line in ids.items() if '["pg"]' in line)
        self.assertEqual(text.count(f"{rollup} --> {pg}"), 1)
        self.assertNotIn(f"{rollup} --> {rollup}", text)
        self.assertEqual(text.count("-->"), 1)

    def test_rollup_nodes_sort_after_kept_nodes(self):
        out = to_mermaid(big_graph(61))
        lines = [ln for ln in out["mermaid"].splitlines()[1:] if "[" in ln]
        self.assertIn("package (61)", lines[-1])

    def test_collapsed_with_only_rollups(self):
        out = to_mermaid(graph([f"p{i}" for i in range(70)]))
        self.assertEqual(out["view"], "collapsed")
        self.assertEqual(out["collapsed"], {"package": 70})
        self.assertEqual(out["mermaid"].count("package (70)"), 1)
        self.assertFalse(out["degraded"])

    def test_still_over_cap_degrades(self):
        g = big_graph(0, services=("a", "b", "c", "d"), components=())
        out = to_mermaid(g, cap=3)
        self.assertTrue(out["degraded"])
        self.assertIsNone(out["mermaid"])
        self.assertIsNone(out["view"])
        self.assertEqual(out["collapsed"], {})
        self.assertEqual(out["node_count"], 4)
        self.assertIn("3", out["reason"])


if __name__ == "__main__":
    unittest.main()
