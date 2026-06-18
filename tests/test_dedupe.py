import sqlite3
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import dedupe as dd


def mem_db():
    conn = sqlite3.connect(":memory:")
    dd.init_db(conn)
    return conn


class TestSchema(unittest.TestCase):
    def test_tables_created(self):
        conn = mem_db()
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"entities", "edges", "dead_candidates",
                         "dup_clusters", "cluster_members", "findings"} <= names)

    def test_code_types(self):
        self.assertEqual(dd.CODE_TYPES, {"function", "method", "type", "constant"})


class TestClassifiers(unittest.TestCase):
    def test_is_unexported_go(self):
        self.assertTrue(dd.is_unexported("helper", "api/x.go"))
        self.assertFalse(dd.is_unexported("Helper", "api/x.go"))

    def test_is_unexported_python_ts(self):
        self.assertTrue(dd.is_unexported("_priv", "pkg/x.py"))
        self.assertFalse(dd.is_unexported("pub", "pkg/x.py"))
        self.assertTrue(dd.is_unexported("_priv", "src/x.ts"))

    def test_is_entrypoint(self):
        for n in ("main", "init", "TestFoo", "BenchmarkX", "ExampleY", "FuzzZ"):
            self.assertTrue(dd.is_entrypoint(n), n)
        self.assertFalse(dd.is_entrypoint("doWork"))

    def test_is_test(self):
        for p in ("api/x_test.go", "src/x.test.ts", "src/x.spec.ts",
                  "test/util.go", "pkg/__tests__/a.ts", "tests/test_x.py"):
            self.assertTrue(dd.is_test(p), p)
        self.assertFalse(dd.is_test("api/handler.go"))


class TestFilterGraph(unittest.TestCase):
    GRAPH = {
        "entities": [
            {"id": "api/h.go::function::handle", "name": "handle",
             "entityType": "function", "filePath": "api/h.go",
             "startLine": 10, "endLine": 20},
            {"id": "api/h.go::function::Public", "name": "Public",
             "entityType": "function", "filePath": "api/h.go",
             "startLine": 22, "endLine": 30},
            {"id": "tools/gen.go::function::helper", "name": "helper",
             "entityType": "function", "filePath": "tools/gen.go",
             "startLine": 1, "endLine": 5},
            {"id": "README.md::heading::Intro", "name": "Intro",
             "entityType": "heading", "filePath": "README.md",
             "startLine": 1, "endLine": 1},
        ],
        "edges": [
            {"fromEntity": "api/h.go::function::handle",
             "toEntity": "api/h.go::function::Public", "refType": "calls"},
            {"fromEntity": "api/h.go::function::handle",
             "toEntity": "tools/gen.go::function::helper", "refType": "calls"},
        ],
        "stats": {},
    }

    def test_scope_and_type_filtering(self):
        ents, edges = dd._filter_graph(self.GRAPH, ["api/"], None)
        ids = {e["id"] for e in ents}
        self.assertEqual(ids, {"api/h.go::function::handle",
                               "api/h.go::function::Public"})  # tools/ + README dropped
        # the edge to tools/ is dropped (endpoint out of scope); the in-scope edge kept
        self.assertEqual(len(edges), 1)
        self.assertEqual(edges[0]["to_id"], "api/h.go::function::Public")

    def test_classifier_columns(self):
        ents, _ = dd._filter_graph(self.GRAPH, ["api/"], None)
        by_name = {e["name"]: e for e in ents}
        self.assertEqual(by_name["handle"]["is_exported"], 0)
        self.assertEqual(by_name["Public"]["is_exported"], 1)

    def test_load_graph_inserts(self):
        conn = mem_db()
        dd.run_sem_graph = lambda exts, cwd=None: self.GRAPH
        stats = dd.load_graph(conn, ["api/"])
        self.assertEqual(stats["entities"], 2)
        self.assertEqual(stats["edges"], 1)
        n = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        self.assertEqual(n, 2)


class TestIngestDescriptions(unittest.TestCase):
    def test_attaches_marker_desc_above_entity(self):
        conn = mem_db()
        conn.execute("""INSERT INTO entities
            (id,name,entity_type,file_path,start_line,end_line,
             is_exported,is_entrypoint,is_test)
            VALUES ('api/h.go::function::handle','handle','function','api/h.go',
                    3,9,0,0,0)""")
        conn.commit()
        dd._read_lines = lambda path: [
            "package api",                                  # 1
            "// SEM@abc1234: handle an inbound request",    # 2  (above start_line 3)
            "func handle() {}",                             # 3
        ]
        n = dd.ingest_descriptions(conn)
        self.assertEqual(n, 1)
        desc = conn.execute(
            "SELECT description FROM entities WHERE name='handle'").fetchone()[0]
        self.assertEqual(desc, "handle an inbound request")

    def test_no_marker_leaves_null(self):
        conn = mem_db()
        conn.execute("""INSERT INTO entities
            (id,name,entity_type,file_path,start_line,end_line,
             is_exported,is_entrypoint,is_test)
            VALUES ('api/h.go::function::handle','handle','function','api/h.go',
                    2,2,0,0,0)""")
        conn.commit()
        dd._read_lines = lambda path: ["package api", "func handle() {}"]
        self.assertEqual(dd.ingest_descriptions(conn), 0)


if __name__ == "__main__":
    unittest.main()
