import os
import sqlite3
import sys
import tempfile
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


class TestDeadCandidates(unittest.TestCase):
    def _ent(self, conn, eid, name, etype, exp, ep, test, sl=1, el=2):
        conn.execute("""INSERT INTO entities
            (id,name,entity_type,file_path,start_line,end_line,
             is_exported,is_entrypoint,is_test)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (eid, name, etype, eid.split("::")[0], sl, el, exp, ep, test))

    def test_flags_unreferenced_prod_funcs_regardless_of_export(self):
        conn = mem_db()
        self._ent(conn, "a.go::function::dead", "dead", "function", 0, 0, 0)
        self._ent(conn, "a.go::function::Exported", "Exported", "function", 1, 0, 0)  # exported IS a candidate now
        self._ent(conn, "a.go::function::live", "live", "function", 0, 0, 0)   # has incoming
        self._ent(conn, "a.go::function::main", "main", "function", 0, 1, 0)   # entrypoint
        self._ent(conn, "a_test.go::function::helper", "helper", "function", 0, 0, 1)  # test
        self._ent(conn, "a.go::type::Thing", "Thing", "type", 0, 0, 0)         # not func/method
        conn.execute("INSERT INTO edges VALUES ('a.go::function::dead','a.go::function::live','calls')")
        conn.commit()
        dd.find_dead_candidates(conn)
        ids = {r[0] for r in conn.execute("SELECT entity_id FROM dead_candidates")}
        self.assertEqual(ids, {"a.go::function::dead", "a.go::function::Exported"})

    def test_idempotent(self):
        conn = mem_db()
        self._ent(conn, "a.go::function::dead", "dead", "function", 0, 0, 0)
        conn.commit()
        dd.find_dead_candidates(conn)
        dd.find_dead_candidates(conn)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM dead_candidates").fetchone()[0], 1)

    def test_usage_refutation_removes_referenced_names(self):
        with tempfile.TemporaryDirectory() as d:
            # candidate `readPump` is defined at lines 1-2 of hub.go and launched via `go c.readPump()` in run.go
            with open(os.path.join(d, "hub.go"), "w") as f:
                f.write("func (c *Client) readPump() {}\n// def end\n")
            with open(os.path.join(d, "run.go"), "w") as f:
                f.write("func start(c *Client) {\n    go c.readPump()\n}\n")
            with open(os.path.join(d, "lonely.go"), "w") as f:
                f.write("func (c *Client) orphan() {}\n")
            conn = mem_db()
            self._ent(conn, "hub.go::method::readPump", "readPump", "method", 0, 0, 0, sl=1, el=2)
            self._ent(conn, "lonely.go::method::orphan", "orphan", "method", 0, 0, 0, sl=1, el=1)
            conn.commit()
            dd.find_dead_candidates(conn)  # both are candidates (zero edges)
            removed = dd.refute_dead_by_usage(conn, cwd=d)
            self.assertEqual(removed, 1)  # readPump refuted by the `go c.readPump()` use
            ids = {r[0] for r in conn.execute("SELECT entity_id FROM dead_candidates")}
            self.assertEqual(ids, {"lonely.go::method::orphan"})  # orphan survives


class TestDupCandidates(unittest.TestCase):
    def _ent(self, conn, eid, name):
        conn.execute("""INSERT INTO entities
            (id,name,entity_type,file_path,start_line,end_line,
             is_exported,is_entrypoint,is_test)
            VALUES (?,?, 'function', ?, 1, 2, 1, 0, 0)""",
            (eid, name, eid.split("::")[0]))

    def test_normalize_name_synonyms_and_tokens(self):
        self.assertEqual(dd.normalize_name("getUser"), dd.normalize_name("fetchUser"))
        self.assertEqual(dd.normalize_name("validate_token"),
                         dd.normalize_name("checkToken"))

    def test_clusters_cross_file_synonym_dupes(self):
        conn = mem_db()
        self._ent(conn, "a.go::function::getUser", "getUser")
        self._ent(conn, "b.go::function::fetchUser", "fetchUser")
        self._ent(conn, "c.go::function::unrelated", "unrelated")
        conn.commit()
        n = dd.find_dup_candidates(conn)
        self.assertEqual(n, 1)
        members = {r[0] for r in conn.execute(
            "SELECT entity_id FROM cluster_members")}
        self.assertEqual(members,
                         {"a.go::function::getUser", "b.go::function::fetchUser"})

    def test_same_file_not_clustered(self):
        conn = mem_db()
        self._ent(conn, "a.go::function::getUser", "getUser")
        self._ent(conn, "a.go::function::fetchUser", "fetchUser")  # same file
        conn.commit()
        self.assertEqual(dd.find_dup_candidates(conn), 0)


class TestFindingsAndReport(unittest.TestCase):
    def test_record_and_rank(self):
        conn = mem_db()
        dd.record_finding(conn, "dead", "confirmed",
                          entity_id="a.go::function::dead",
                          impact="low", risk="low",
                          recommendation="remove")
        dd.record_finding(conn, "dead", "confirmed",
                          entity_id="a.go::function::big",
                          impact="high", risk="low",
                          recommendation="remove")
        dd.record_finding(conn, "dead", "false-positive",
                          entity_id="a.go::function::fp")
        report = dd.render_report(conn)
        self.assertIn("Dead code", report)
        # high-impact ranked above low-impact; false-positive excluded
        self.assertLess(report.index("a.go::function::big"),
                        report.index("a.go::function::dead"))
        self.assertNotIn("a.go::function::fp", report)

    def test_dup_section_and_limitation_note(self):
        conn = mem_db()
        dd.record_finding(conn, "dup", "real-dup", cluster_id=1,
                          impact="medium", risk="medium",
                          recommendation="consolidate",
                          behavior_diff="one uses RS256, other HS256")
        report = dd.render_report(conn)
        self.assertIn("Duplication", report)
        self.assertIn("RS256", report)
        self.assertIn("exported", report.lower())  # the sem-limitation note

    def test_parse_args_load(self):
        ns = dd.parse_args(["load", "server/", "--exts", ".go", "-C", "/repo"])
        self.assertEqual(ns.cmd, "load")
        self.assertEqual(ns.scope, ["server/"])
        self.assertEqual(ns.exts, [".go"])
        self.assertEqual(ns.cwd, "/repo")


class TestScopeFile(unittest.TestCase):
    def test_in_scope_excludes_glob(self):
        # include prefix kept, exclude glob drops the file
        self.assertTrue(dd._in_scope("src/a.ts", ["src/"], dd.CODE_FILE_EXTS, exclude=["**/*.spec.ts"]))
        self.assertFalse(dd._in_scope("src/a.spec.ts", ["src/"], dd.CODE_FILE_EXTS, exclude=["**/*.spec.ts"]))

    def test_in_scope_no_exclude_unchanged(self):
        self.assertTrue(dd._in_scope("src/a.ts", ["src/"], dd.CODE_FILE_EXTS))
        self.assertFalse(dd._in_scope("other/a.ts", ["src/"], dd.CODE_FILE_EXTS))


class TestRunSemGraphJSON(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "_orig"):
            dd.subprocess.run = self._orig

    def test_malformed_json_raises_semerror(self):
        class FakeProc:
            returncode = 0
            stdout = "{not json"
            stderr = ""
        self._orig = dd.subprocess.run
        dd.subprocess.run = lambda *a, **k: FakeProc()
        with self.assertRaises(dd.SemError):
            dd.run_sem_graph([])

    def test_valid_json_still_parses(self):
        class FakeProc:
            returncode = 0
            stdout = '{"entities": [], "edges": []}'
            stderr = ""
        self._orig = dd.subprocess.run
        dd.subprocess.run = lambda *a, **k: FakeProc()
        self.assertEqual(dd.run_sem_graph([]), {"entities": [], "edges": []})


class TestReportFilename(unittest.TestCase):
    def test_report_filename_is_timestamped(self):
        import io, json, re, tempfile, os as _os
        with tempfile.TemporaryDirectory() as d:
            db = _os.path.join(d, "dedupe.db")
            # initialize the db so the report subcommand can connect/query
            conn = dd._connect(db)
            conn.close()
            buf = io.StringIO()
            _orig = sys.stdout
            sys.stdout = buf
            try:
                rc = dd.main(["report", "--db", db])
            finally:
                sys.stdout = _orig
            self.assertEqual(rc, 0)
            path = json.loads(buf.getvalue())["report"]
            self.assertRegex(_os.path.basename(path), r"^dedupe-\d{8}T\d{6}\.md$")
            self.assertTrue(_os.path.exists(path))


if __name__ == "__main__":
    unittest.main()
