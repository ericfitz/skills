# tests/test_depgraph_cli.py
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

import depgraph

ENVELOPE = {"categories": {}}


def run(topology):
    """Run depgraph.main with a temp envelope and topology; return (code, stdout, stderr)."""
    with tempfile.TemporaryDirectory() as d:
        env, topo = Path(d, "env.json"), Path(d, "topology.json")
        env.write_text(json.dumps(ENVELOPE))
        topo.write_text(json.dumps(topology))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = depgraph.main([str(env), "--topology", str(topo)])
    return code, out.getvalue(), err.getvalue()


class TopologyErrorsTest(unittest.TestCase):
    def assert_exit_2(self, topology):
        code, _, err = run(topology)
        self.assertEqual(code, 2)
        self.assertIn("component ids", json.loads(err)["error"])

    def test_topology_not_an_object(self):
        self.assert_exit_2([])

    def test_component_name_null(self):
        self.assert_exit_2({"components": [{"name": None}]})

    def test_component_name_empty_slug(self):
        self.assert_exit_2({"components": [{"name": "!!"}]})

    def test_component_id_collision(self):
        self.assert_exit_2({"components": [{"name": "a b"}, {"name": "a-b"}]})

    def test_valid_topology_exits_0(self):
        code, out, _ = run({"components": [{"name": "migrate / dbtool"}]})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["components"][0]["id"], "component:migrate-dbtool")


class UsedByErrorsTest(unittest.TestCase):
    def run_with(self, used_by):
        envelope = {"categories": {"service": {"status": "discovered", "assumptions": [],
            "dependencies": [{"id": "service:pg", "name": "pg", "lifecycle": "run",
                              "details": {"used_by": used_by}}]}}}
        with tempfile.TemporaryDirectory() as d:
            env = Path(d, "env.json")
            env.write_text(json.dumps(envelope))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = depgraph.main([str(env)])
        return code, err.getvalue()

    def test_bare_string_entry_rejected(self):
        code, err = self.run_with(["component:api"])
        self.assertEqual(code, 2)
        self.assertIn("error", json.loads(err))

    def test_missing_component_id_rejected(self):
        code, err = self.run_with([{"evidence": ["a:1"]}])
        self.assertEqual(code, 2)
        self.assertIn("component_id", json.loads(err)["error"])

    def test_duplicate_component_names_agree_with_ids(self):
        code, out, _ = run({"components": [{"name": "api"}, {"name": "api"}]})
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertEqual(len(doc["components"]), 1)
        self.assertEqual(len([n for n in doc["graph"]["nodes"]
                              if n["category"] == "component"]), 1)


if __name__ == "__main__":
    unittest.main()
