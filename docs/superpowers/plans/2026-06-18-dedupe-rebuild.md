# dedupe Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `dedupe` skill on the `sem` CLI: detect dead code (via the one-call entity graph) and duplication (via names + SEM descriptions), verify candidates with parallel subagents, and produce a ranked plan — replacing the old per-file-analyzer/SQLite-rederivation pipeline.

**Architecture:** A single testable Python tool (`dev/scripts/dedupe.py`) owns all deterministic work — it runs `sem graph --json` once, filters to in-scope code entities/edges into a SQLite DB, derives dead-code and duplicate *candidates* with SQL, stores verifier findings, and renders the ranked report. The skill orchestration (`SKILL.md`) runs the tool, dispatches refutation-biased verifier subagents in batches (dead-code and duplication), then renders the plan and offers to apply it. SQLite is the context-saving spine; the LLM is spent only on per-candidate verification.

**Tech Stack:** Python 3.14 (stdlib only: `sqlite3`, `json`, `subprocess`, `argparse`, `re`, `os`, `unittest`), the `sem` CLI (`/opt/homebrew/bin/sem`, esp. `sem graph --json` and `sem context`), Claude Code skills + agents.

## Global Constraints

- **Python stdlib only.** No third-party deps. Tests use `unittest`, run via `python3 -m unittest`. Tests live at repo-root `tests/`, import via `sys.path.insert(0, <plugin>/scripts)`, and set `sys.dont_write_bytecode = True` before importing.
- **`sem graph --json [PATH]` returns the WHOLE repo** (entities incl. markdown headings); it does NOT scope by PATH. Scope by filtering `filePath` prefixes and `--file-exts`.
- **`sem graph` JSON shape (verbatim):** `{"entities":[{"id","name","entityType","filePath","startLine","endLine"}], "edges":[{"fromEntity","toEntity","refType"}], "stats":{...}}`. Entity `id` format is `"<filePath>::<kind>::<name>"`. Edge endpoints are entity `id`s. `refType` ∈ {`calls`, `typeref`}. `entityType` ∈ {`function`,`method`,`type`,`constant`,`variable`,`heading`,…}.
- **Dead-code reliability (Go, Python, TypeScript) comes from a two-stage refutation, not from sem alone.** sem edges do NOT capture interface dispatch, `go`-routine launches, reflection, cross-module imports, or router/framework registration — so "zero incoming edges" massively over-reports for all three languages. The pipeline is therefore: (1) sem generates candidates (`entityType ∈ {function, method}`, non-entrypoint, non-test, zero incoming edges — **export status is NOT used to filter**, since the casing/underscore convention doesn't generalize across languages); (2) a **deterministic whole-repo usage scan** refutes any candidate whose name appears as an identifier token anywhere outside a same-name definition span (catches the interface/goroutine/import/call-site uses sem misses); (3) only the residual goes to the LLM verifier.
- **The usage scan is high-precision by construction.** It errs toward "in use" (a textual reference of a function-name token is treated as a use), so it never wrongly removes used code; it may leave some genuinely-dead code unflagged (acceptable — precision over recall for removals). It scans the WHOLE repo (not just the scope) so out-of-scope callers refute in-scope candidates.
- **Per-candidate verification is mandatory for the residual.** Residual candidates have zero sem edges AND zero textual references, so they are likely unused — but the verifier still checks what text can't: reflection/dynamic-string dispatch, whether an **exported** symbol is an intended external/public API, build-tag/platform-excluded callers, and codegen. Exported residuals are treated more conservatively (may be external API).
- **Duplication detection** is name/description-based (independent of edge completeness) and stays broad.
- **CODE_TYPES** = `{"function","method","type","constant"}` for loading; **dead-code** considers only `{"function","method"}`.
- **Unexported test** (`is_unexported`): Go → `name[0].islower()`; Python/TS → `name.startswith("_")`. Determined by file extension.
- **Entry points** (`is_entrypoint`): name == `main` or `init`, or starts with any of `Test`,`Benchmark`,`Example`,`Fuzz`.
- **Test file** (`is_test`): path contains `_test.go`, `.test.`, `.spec.`, `/test/`, `/tests/`, `/__tests__/`, or starts with `test/` / `tests/`, or basename starts with `test_`.
- **DB at `.dedupe/dedupe.db`; reports at `.dedupe/reports/`; `.dedupe/` gitignored.** WAL mode + `busy_timeout=10000`.
- **Version bump:** the `dev` plugin goes `1.0.0` → `2.0.0` (breaking: dedupe's interface changes from language-arg to path-scope, old worker agents removed; also folds in the unversioned `sem-annotate`). Bump `dev/.claude-plugin/plugin.json` AND the `dev` entry's description note in `.claude-plugin/marketplace.json`.

## File Structure

- `dev/scripts/dedupe.py` — the tool: DB schema, graph loader, SEM-description ingestion, dead/dup candidate detection, findings storage, ranking + markdown report, CLI.
- `dev/skills/dedupe/SKILL.md` — rewritten orchestration (preflight → load → detect → batched verify → rank → report → offer apply).
- `dev/agents/dedupe-verify-dead.md` — refutation-biased dead-code verifier subagent.
- `dev/agents/dedupe-verify-dup.md` — duplication verifier subagent (reads both impls, records behavior diffs).
- `tests/test_dedupe.py` — unit tests (synthetic graph JSON + in-memory SQLite; no real sem needed).
- **Delete:** `dev/agents/dedupe-analyzer.md`, `dev/agents/dedupe-grouper.md`, `dev/agents/dedupe-deduplicator.md`, `dev/scripts/dedupe-report.py`.
- `dev/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` — version + description.

---

### Task 1: Tool scaffold + DB schema

**Files:**
- Create: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `init_db(conn)` (creates all tables/indexes, sets WAL + busy_timeout); `CODE_TYPES: set`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dedupe.py
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dedupe'`.

- [ ] **Step 3: Write minimal implementation**

```python
# dev/scripts/dedupe.py
"""dedupe: find dead code and duplication via the sem CLI entity graph."""
import sqlite3

CODE_TYPES = {"function", "method", "type", "constant"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_meta (
    run_id TEXT PRIMARY KEY, scope TEXT, file_exts TEXT,
    started_at TEXT, completed_at TEXT);
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, entity_type TEXT NOT NULL,
    file_path TEXT NOT NULL, start_line INTEGER, end_line INTEGER,
    is_exported INTEGER, is_entrypoint INTEGER, is_test INTEGER, description TEXT);
CREATE INDEX IF NOT EXISTS idx_entities_file ON entities(file_path);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE TABLE IF NOT EXISTS edges (from_id TEXT, to_id TEXT, ref_type TEXT);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
CREATE TABLE IF NOT EXISTS dead_candidates (entity_id TEXT PRIMARY KEY, reason TEXT);
CREATE TABLE IF NOT EXISTS dup_clusters (
    cluster_id INTEGER PRIMARY KEY AUTOINCREMENT, method TEXT, key TEXT);
CREATE TABLE IF NOT EXISTS cluster_members (cluster_id INTEGER, entity_id TEXT);
CREATE TABLE IF NOT EXISTS findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, verdict TEXT, entity_id TEXT, cluster_id INTEGER,
    impact TEXT, risk TEXT, effort TEXT, recommendation TEXT,
    notes TEXT, behavior_diff TEXT);
"""


def init_db(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(_SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): tool scaffold + SQLite schema"
```

---

### Task 2: Entity classification helpers

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `is_unexported(name, file_path) -> bool`; `is_entrypoint(name) -> bool`; `is_test(file_path) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `is_unexported`.

- [ ] **Step 3: Write minimal implementation**

```python
import os

_ENTRYPOINT_PREFIXES = ("Test", "Benchmark", "Example", "Fuzz")


def is_unexported(name, file_path):
    _, ext = os.path.splitext(file_path)
    if ext.lower() == ".go":
        return bool(name) and name[0].islower()
    # python / ts / js convention: leading underscore is private
    return name.startswith("_")


def is_entrypoint(name):
    return name in ("main", "init") or name.startswith(_ENTRYPOINT_PREFIXES)


def is_test(file_path):
    p = file_path
    base = os.path.basename(p)
    if any(s in p for s in ("_test.go", ".test.", ".spec.",
                            "/test/", "/tests/", "/__tests__/")):
        return True
    if p.startswith(("test/", "tests/")):
        return True
    return base.startswith("test_")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): entity classification helpers (unexported/entrypoint/test)"
```

---

### Task 3: Graph filter + loader

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces:
  - `_filter_graph(graph, scope_paths, exts) -> (entity_rows, edge_rows)`. `entity_rows` are dicts with keys `id,name,entity_type,file_path,start_line,end_line,is_exported,is_entrypoint,is_test`. Keep only entities whose `entityType ∈ CODE_TYPES` AND `filePath` starts with one of `scope_paths` (empty `scope_paths` = keep all) AND (no `exts` or `filePath` ends with one of `exts`). Keep only edges whose BOTH endpoints are kept entities.
  - `load_graph(conn, scope_paths, exts=None, cwd=None) -> dict` (runs `sem graph --json` with `--file-exts` when `exts` given, filters, bulk-inserts into `entities`/`edges`, returns `{"entities": n, "edges": m}`).
  - `run_sem_graph(exts, cwd) -> dict` (subprocess wrapper; module-level for patchability).
- Consumes: `CODE_TYPES`, `is_unexported`, `is_entrypoint`, `is_test`.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `_filter_graph`.

- [ ] **Step 3: Write minimal implementation**

```python
import json
import subprocess


class SemError(RuntimeError):
    pass


def run_sem_graph(exts, cwd=None):
    cmd = ["sem", "graph", "--json"]
    if exts:
        cmd += ["--file-exts", *exts]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SemError("'sem' CLI not found on PATH")
    except subprocess.CalledProcessError as e:
        raise SemError(f"sem graph failed: {e.stderr.strip()}")
    return json.loads(r.stdout)


def _in_scope(path, scope_paths, exts):
    if scope_paths and not any(path.startswith(s) for s in scope_paths):
        return False
    if exts and not any(path.endswith(x) for x in exts):
        return False
    return True


def _filter_graph(graph, scope_paths, exts):
    entity_rows = []
    kept = set()
    for e in graph.get("entities", []):
        if e.get("entityType") not in CODE_TYPES:
            continue
        fp = e.get("filePath", "")
        if not _in_scope(fp, scope_paths, exts):
            continue
        name = e.get("name", "")
        kept.add(e["id"])
        entity_rows.append({
            "id": e["id"], "name": name, "entity_type": e["entityType"],
            "file_path": fp, "start_line": e.get("startLine"),
            "end_line": e.get("endLine"),
            "is_exported": 0 if is_unexported(name, fp) else 1,
            "is_entrypoint": 1 if is_entrypoint(name) else 0,
            "is_test": 1 if is_test(fp) else 0,
        })
    edge_rows = []
    for ed in graph.get("edges", []):
        if ed.get("fromEntity") in kept and ed.get("toEntity") in kept:
            edge_rows.append({"from_id": ed["fromEntity"],
                              "to_id": ed["toEntity"],
                              "ref_type": ed.get("refType")})
    return entity_rows, edge_rows


def load_graph(conn, scope_paths, exts=None, cwd=None):
    graph = run_sem_graph(exts, cwd=cwd)
    ents, edges = _filter_graph(graph, scope_paths, exts)
    conn.executemany(
        """INSERT OR REPLACE INTO entities
        (id,name,entity_type,file_path,start_line,end_line,
         is_exported,is_entrypoint,is_test)
        VALUES (:id,:name,:entity_type,:file_path,:start_line,:end_line,
                :is_exported,:is_entrypoint,:is_test)""", ents)
    conn.executemany(
        "INSERT INTO edges (from_id,to_id,ref_type) VALUES (:from_id,:to_id,:ref_type)",
        edges)
    conn.commit()
    return {"entities": len(ents), "edges": len(edges)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS.

- [ ] **Step 5: Integration check against tmi (real sem CLI)**

Run:
```bash
cd /Users/efitz/Projects/skills && python3 -c "
import sqlite3, sys; sys.dont_write_bytecode=True
sys.path.insert(0,'dev/scripts'); import dedupe as dd
c=sqlite3.connect(':memory:'); dd.init_db(c)
print(dd.load_graph(c, ['api/'], exts=['.go'], cwd='/Users/efitz/Projects/tmi'))
"
```
Expected: prints `{'entities': <thousands>, 'edges': <thousands>}` scoped to `api/` Go files.

- [ ] **Step 6: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): sem graph filter + loader"
```

---

### Task 4: SEM-description ingestion

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `ingest_descriptions(conn, cwd=None) -> int` — for each entity row, read its file once, look at the line directly above `start_line` for a `SEM@<sha>: <desc>` marker, and set `entities.description`. Returns the number of descriptions attached. Reads files via module-level `_read_lines(path)` (patchable).
- Consumes: a marker regex.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `ingest_descriptions`.

- [ ] **Step 3: Write minimal implementation**

```python
import re

_SEM_MARKER_RE = re.compile(
    r"^\s*(?://|#)\s*SEM@[0-9a-fA-F]{4,40}:\s?(?P<desc>.*)$")


def _read_lines(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().splitlines()


def ingest_descriptions(conn, cwd=None):
    rows = conn.execute(
        "SELECT id, file_path, start_line FROM entities").fetchall()
    by_file = {}
    for eid, fp, start in rows:
        by_file.setdefault(fp, []).append((eid, start))
    attached = 0
    for fp, ents in by_file.items():
        path = fp if cwd is None else os.path.join(cwd, fp)
        try:
            lines = _read_lines(path)
        except OSError:
            continue
        for eid, start in ents:
            if not start or start < 2 or start - 2 >= len(lines):
                continue
            m = _SEM_MARKER_RE.match(lines[start - 2])
            if m:
                conn.execute("UPDATE entities SET description=? WHERE id=?",
                             (m.group("desc"), eid))
                attached += 1
    conn.commit()
    return attached
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): ingest SEM marker descriptions into entities"
```

---

### Task 5: Dead-code candidate detection + deterministic usage refutation

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

The deliverable is the *trustworthy* dead-candidate set: sem generates candidates, then a whole-repo usage scan removes the textually-referenced ones. Two functions, one deliverable.

**Interfaces:**
- Produces:
  - `find_dead_candidates(conn) -> int` — inserts into `dead_candidates` every entity where `entity_type IN ('function','method')` AND `is_entrypoint=0` AND `is_test=0` AND `id` is not the `to_id` of any edge. **Export status is NOT used.** `reason` = `"no incoming edges (non-entrypoint, production)"`. Idempotent (clears first). Returns the count.
  - `refute_dead_by_usage(conn, cwd=None, exts=CODE_FILE_EXTS) -> int` — scans every code file under `cwd` (default `.`), skipping `_SKIP_DIRS`; for each identifier token that matches a dead-candidate name and is NOT inside a same-name definition span, marks that name "used" and deletes all candidates with that name from `dead_candidates`. Returns the number removed. Language-agnostic (token scan).
  - `CODE_FILE_EXTS`, `_SKIP_DIRS`, `_iter_code_files(root, exts)` (module-level; file iteration patchable for tests).

- [ ] **Step 1: Write the failing test**

```python
import os, tempfile

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `find_dead_candidates`.

- [ ] **Step 3: Write minimal implementation**

```python
CODE_FILE_EXTS = (".go", ".py", ".ts", ".tsx", ".js", ".jsx")
_SKIP_DIRS = {"vendor", "node_modules", ".git", ".dedupe", "dist", "build",
              "__pycache__", ".venv", "venv", "testdata"}
_TOKEN_RE = re.compile(r"[A-Za-z_]\w*")


def find_dead_candidates(conn):
    conn.execute("DELETE FROM dead_candidates")
    conn.execute("""
        INSERT INTO dead_candidates (entity_id, reason)
        SELECT e.id, 'no incoming edges (non-entrypoint, production)'
        FROM entities e
        WHERE e.entity_type IN ('function','method')
          AND e.is_entrypoint = 0 AND e.is_test = 0
          AND e.id NOT IN (SELECT to_id FROM edges)
    """)
    conn.commit()
    return conn.execute("SELECT COUNT(*) FROM dead_candidates").fetchone()[0]


def _iter_code_files(root, exts):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(tuple(exts)):
                yield os.path.join(dirpath, fn)


def refute_dead_by_usage(conn, cwd=None, exts=CODE_FILE_EXTS):
    rows = conn.execute(
        """SELECT d.entity_id, e.name FROM dead_candidates d
           JOIN entities e ON e.id = d.entity_id""").fetchall()
    if not rows:
        return 0
    names = {}                       # name -> [entity_id, ...]
    for eid, name in rows:
        names.setdefault(name, []).append(eid)
    # definition spans to exclude, per relative file path: name -> list of (start,end)
    defspans = {}
    qmarks = ",".join("?" * len(names))
    for name, fp, sl, el in conn.execute(
        f"SELECT name,file_path,start_line,end_line FROM entities WHERE name IN ({qmarks})",
            tuple(names)):
        defspans.setdefault(fp, {}).setdefault(name, []).append((sl or 0, el or 0))
    root = cwd or "."
    used = set()
    pending = set(names)
    for path in _iter_code_files(root, exts):
        if not pending:
            break
        rel = os.path.relpath(path, root)
        file_spans = defspans.get(rel, {})
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for lineno, line in enumerate(f, 1):
                    for m in _TOKEN_RE.finditer(line):
                        tok = m.group(0)
                        if tok not in pending:
                            continue
                        spans = file_spans.get(tok, ())
                        if any(s <= lineno <= e for (s, e) in spans):
                            continue  # this is (part of) a definition of tok
                        used.add(tok)
                        pending.discard(tok)
        except OSError:
            continue
    removed = 0
    for name in used:
        for eid in names[name]:
            conn.execute("DELETE FROM dead_candidates WHERE entity_id=?", (eid,))
            removed += 1
    conn.commit()
    return removed
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS.

- [ ] **Step 5: Integration check against tmi (the refutation's real impact)**

Run:
```bash
cd /Users/efitz/Projects/skills && python3 -c "
import sqlite3, sys; sys.dont_write_bytecode=True
sys.path.insert(0,'dev/scripts'); import dedupe as dd
c=sqlite3.connect(':memory:'); dd.init_db(c)
dd.load_graph(c, ['api/'], exts=['.go'], cwd='/Users/efitz/Projects/tmi')
raw=dd.find_dead_candidates(c)
removed=dd.refute_dead_by_usage(c, cwd='/Users/efitz/Projects/tmi')
print(f'raw candidates: {raw}; refuted by usage: {removed}; residual: {raw-removed}')
"
```
Expected: `raw` is large (hundreds+), `refuted` removes most, and `residual` is small (the usage scan is doing its job — e.g. `readPump`/`writePump`-style goroutine methods get refuted).

- [ ] **Step 6: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): dead-code detection + whole-repo usage refutation (Go/Py/TS)"
```

---

### Task 6: Duplication candidate pre-filter (SQL/Python)

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces:
  - `normalize_name(name) -> str` — lowercased, split camelCase/snake_case into a sorted token tuple joined by spaces, with a small verb-synonym map applied (`get/retrieve/load→fetch`, `check/verify/ensure→validate`, `create/make/construct→build`, `delete/remove→delete`). Returns the normalized signature string.
  - `find_dup_candidates(conn) -> int` — clusters entities (functions/methods, non-test) that share a normalized signature across **different files**, into `dup_clusters` (`method='name'`, `key=<signature>`) + `cluster_members`. Only clusters with ≥2 members in ≥2 distinct files are kept. Returns the cluster count. Idempotent.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `normalize_name`.

- [ ] **Step 3: Write minimal implementation**

```python
_VERB_SYNONYMS = {
    "get": "fetch", "retrieve": "fetch", "load": "fetch",
    "check": "validate", "verify": "validate", "ensure": "validate",
    "create": "build", "make": "build", "construct": "build",
    "remove": "delete",
}

_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def normalize_name(name):
    tokens = [t.lower() for t in _CAMEL_RE.findall(name) if t]
    tokens = [_VERB_SYNONYMS.get(t, t) for t in tokens]
    return " ".join(sorted(tokens))


def find_dup_candidates(conn):
    conn.execute("DELETE FROM cluster_members")
    conn.execute("DELETE FROM dup_clusters")
    rows = conn.execute(
        """SELECT id, name, file_path FROM entities
           WHERE entity_type IN ('function','method') AND is_test = 0""").fetchall()
    groups = {}
    for eid, name, fp in rows:
        groups.setdefault(normalize_name(name), []).append((eid, fp))
    clusters = 0
    for key, members in groups.items():
        if len(members) < 2:
            continue
        if len({fp for _, fp in members}) < 2:
            continue
        cur = conn.execute(
            "INSERT INTO dup_clusters (method, key) VALUES ('name', ?)", (key,))
        cid = cur.lastrowid
        conn.executemany(
            "INSERT INTO cluster_members (cluster_id, entity_id) VALUES (?, ?)",
            [(cid, eid) for eid, _ in members])
        clusters += 1
    conn.commit()
    return clusters
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): duplication candidate pre-filter (normalized cross-file names)"
```

---

### Task 7: Findings storage + ranking + report + CLI

**Files:**
- Modify: `dev/scripts/dedupe.py`
- Test: `tests/test_dedupe.py`

**Interfaces:**
- Produces:
  - `record_finding(conn, kind, verdict, entity_id=None, cluster_id=None, impact="", risk="", effort="", recommendation="", notes="", behavior_diff="") -> int`.
  - `render_report(conn) -> str` — markdown with a Dead-code section and a Duplication section, each listing confirmed findings ordered by `(impact desc, risk asc)` using the rank map `{"high":3,"medium":2,"low":1,"":0}`; includes the sem-limitation note for dead code. Only `verdict` in (`confirmed`,`real-dup`) appear.
  - `parse_args(argv)` / `main(argv=None)` with subcommands: `load SCOPE... [--exts ...] [-C DIR]` (init DB at `.dedupe/dedupe.db`, load graph, ingest descriptions, detect dead+dup candidates, print a JSON summary); `candidates [-C DIR]` (print dead + dup candidates JSON for the orchestrator to hand to verifiers); `report [-C DIR]` (write `.dedupe/reports/dedupe-<ts>.md` from findings, print its path). `--db` overrides the DB path (default `.dedupe/dedupe.db`).
- Consumes: all prior functions.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: FAIL — no attribute `record_finding`.

- [ ] **Step 3: Write minimal implementation**

```python
import argparse
import sys

_RANK = {"high": 3, "medium": 2, "low": 1, "": 0, None: 0}
DEAD_LIMITATION = (
    "_Method: candidates are functions/methods with no callers in sem's graph, after "
    "removing any whose name is referenced anywhere in the repo (a deterministic usage "
    "scan that catches interface dispatch, goroutine launches, and cross-module imports "
    "sem misses), then cleared by a verifier. Residual exported symbols may still be an "
    "external/public API — confirm before removing. Detection favors precision over "
    "recall: some genuinely-dead code may not be listed._")


def record_finding(conn, kind, verdict, entity_id=None, cluster_id=None,
                   impact="", risk="", effort="", recommendation="",
                   notes="", behavior_diff=""):
    cur = conn.execute(
        """INSERT INTO findings
        (kind,verdict,entity_id,cluster_id,impact,risk,effort,
         recommendation,notes,behavior_diff)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (kind, verdict, entity_id, cluster_id, impact, risk, effort,
         recommendation, notes, behavior_diff))
    conn.commit()
    return cur.lastrowid


def _ranked(conn, kind, verdicts):
    rows = [dict(zip(
        ["finding_id", "entity_id", "cluster_id", "impact", "risk", "effort",
         "recommendation", "notes", "behavior_diff"], r))
        for r in conn.execute(
            """SELECT finding_id,entity_id,cluster_id,impact,risk,effort,
                      recommendation,notes,behavior_diff
               FROM findings WHERE kind=? AND verdict IN ({})""".format(
                ",".join("?" * len(verdicts))), (kind, *verdicts))]
    rows.sort(key=lambda r: (-_RANK.get(r["impact"], 0), _RANK.get(r["risk"], 0)))
    return rows


def render_report(conn):
    out = ["# Dedupe Report", ""]
    out += ["## Dead code", "", DEAD_LIMITATION, ""]
    dead = _ranked(conn, "dead", ["confirmed"])
    if not dead:
        out.append("_No confirmed dead code._")
    for r in dead:
        out.append(f"- **{r['entity_id']}** — impact {r['impact'] or 'n/a'}, "
                   f"risk {r['risk'] or 'n/a'}, effort {r['effort'] or 'n/a'} — "
                   f"{r['recommendation']}. {r['notes']}".rstrip())
    out += ["", "## Duplication", ""]
    dup = _ranked(conn, "dup", ["real-dup"])
    if not dup:
        out.append("_No confirmed duplication._")
    for r in dup:
        line = (f"- cluster {r['cluster_id']} — impact {r['impact'] or 'n/a'}, "
                f"risk {r['risk'] or 'n/a'}, effort {r['effort'] or 'n/a'} — "
                f"{r['recommendation']}.")
        if r["behavior_diff"]:
            line += f" Behavior diff: {r['behavior_diff']}."
        if r["notes"]:
            line += f" {r['notes']}"
        out.append(line.rstrip())
    return "\n".join(out) + "\n"


def parse_args(argv):
    p = argparse.ArgumentParser(prog="dedupe")
    p.add_argument("--db", default=".dedupe/dedupe.db")
    sub = p.add_subparsers(dest="cmd")
    lo = sub.add_parser("load")
    lo.add_argument("scope", nargs="*", default=[])
    lo.add_argument("--exts", nargs="+", default=None)
    lo.add_argument("-C", "--cwd", default=None)
    ca = sub.add_parser("candidates")
    ca.add_argument("-C", "--cwd", default=None)
    re_ = sub.add_parser("report")
    re_.add_argument("-C", "--cwd", default=None)
    return p.parse_args(argv)
```

(Note: `main()` is added in the next step's code along with the CLI wiring; keep `parse_args` testable on its own.)

- [ ] **Step 4: Add `main()` wiring and run the full test**

Append to `dedupe.py`:

```python
def _connect(db_path):
    d = os.path.dirname(db_path)
    if d:
        os.makedirs(d, exist_ok=True)
    conn = sqlite3.connect(db_path)
    init_db(conn)
    return conn


def main(argv=None):
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    if ns.cmd == "load":
        conn = _connect(ns.db)
        stats = load_graph(conn, ns.scope, exts=ns.exts, cwd=ns.cwd)
        descs = ingest_descriptions(conn, cwd=ns.cwd)
        raw_dead = find_dead_candidates(conn)
        refuted = refute_dead_by_usage(conn, cwd=ns.cwd)
        dup = find_dup_candidates(conn)
        print(json.dumps({**stats, "descriptions": descs,
                          "dead_candidates_raw": raw_dead,
                          "dead_refuted_by_usage": refuted,
                          "dead_candidates": raw_dead - refuted,
                          "dup_clusters": dup}))
        return 0
    if ns.cmd == "candidates":
        conn = _connect(ns.db)
        dead = [dict(zip(["entity_id", "name", "file_path", "start_line",
                          "end_line", "description", "is_exported"], r))
                for r in conn.execute(
            """SELECT e.id,e.name,e.file_path,e.start_line,e.end_line,
                      e.description,e.is_exported
               FROM dead_candidates d JOIN entities e ON e.id=d.entity_id""")]
        dups = {}
        for cid, eid, name, fp, sl, el, desc in conn.execute(
            """SELECT c.cluster_id,e.id,e.name,e.file_path,e.start_line,
                      e.end_line,e.description
               FROM cluster_members c JOIN entities e ON e.id=c.entity_id
               ORDER BY c.cluster_id"""):
            dups.setdefault(cid, []).append(
                {"entity_id": eid, "name": name, "file_path": fp,
                 "start_line": sl, "end_line": el, "description": desc})
        print(json.dumps({"dead": dead, "dup_clusters": dups}))
        return 0
    if ns.cmd == "report":
        conn = _connect(ns.db)
        os.makedirs(os.path.join(os.path.dirname(ns.db) or ".", "reports"),
                    exist_ok=True)
        path = os.path.join(os.path.dirname(ns.db) or ".", "reports",
                            "dedupe-report.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_report(conn))
        print(json.dumps({"report": path}))
        return 0
    print("usage: dedupe [load|candidates|report]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe -v`
Expected: PASS (all tasks 1–7).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): findings storage, ranking, markdown report, CLI"
```

---

### Task 8: Dead-code verifier subagent prompt

**Files:**
- Create: `dev/agents/dedupe-verify-dead.md`

Documentation deliverable; verified by the e2e run in Task 11.

- [ ] **Step 1: Write the agent prompt**

```markdown
---
name: Dedupe Dead-Code Verifier
description: Internal worker for the dedupe skill. Given a batch of dead-code candidates (entity id, name, file, line range), tries to REFUTE that each is dead, and returns a verdict per candidate. Invoked by the dedupe orchestrator.
tools: Read, Grep, Bash
model: sonnet
---

# Dead-Code Verifier

You receive dead-code candidates that have ALREADY passed two filters: sem's call graph
shows no callers, AND a deterministic whole-repo scan found no identifier-token reference
to the name anywhere outside its definition. So they are likely unused. Your job is to
catch the few false positives that a text scan cannot — usages that don't spell the name
as a plain token. Default to `false-positive` whenever you find ANY plausible use.

## Input
A JSON array on the prompt: each item `{entity_id, name, file_path, start_line, end_line, is_exported}`.
Plus `REPO_DIR` (absolute repo path). Work from REPO_DIR.

## For each candidate, check (any hit ⇒ false-positive)
1. **Reflection / dynamic dispatch by string:** `grep -rn '"<name>"' REPO_DIR` — is the name
   invoked by string (reflection, registries, RPC routers, serialization tags, template
   lookups)? A quoted-string use won't appear in the token scan.
2. **Codegen / build-tagged callers:** is there a caller in a generated file or behind a
   build tag / platform guard that the scan's file set may have skipped?
3. **External / public API (especially when `is_exported` is true):** could this be called
   from OUTSIDE this repository (a published package, plugin entry point, exported handler
   referenced by a framework)? Be conservative: for exported symbols with a plausible
   external-API role, return `false-positive` and note "possible external API".
4. **Framework registration:** is it registered with a router/DI container/scheduler by
   reference in a way the scan missed (e.g. constructed via a factory map keyed by string)?

Use `sem context <name> --file <relative-path> --json` (run from REPO_DIR) or `Read` the
definition to understand intent.

## Verdict per candidate
- `confirmed` — no use after the checks above; safe to recommend removal.
- `false-positive` — a plausible use exists (name the mechanism in `notes`).

For `confirmed`, estimate `impact` (high/medium/low — size & blast radius of removal),
`risk` (low if clearly unused; medium for exported or uncertain), `effort` (low/medium),
and set `recommendation` = "remove".

## Output
Respond with ONLY a JSON array of:
`{entity_id, verdict, impact, risk, effort, recommendation, notes}`.
No prose, no fences.
```

- [ ] **Step 2: Commit**

```bash
git add dev/agents/dedupe-verify-dead.md
git commit -m "feat(dedupe): dead-code verifier subagent prompt"
```

---

### Task 9: Duplication verifier subagent prompt

**Files:**
- Create: `dev/agents/dedupe-verify-dup.md`

- [ ] **Step 1: Write the agent prompt**

```markdown
---
name: Dedupe Duplication Verifier
description: Internal worker for the dedupe skill. Given candidate duplicate clusters (entities that share a normalized name across files), reads each implementation and returns a verdict with behavior differences. Invoked by the dedupe orchestrator.
tools: Read, Bash
model: sonnet
---

# Duplication Verifier

You receive candidate clusters: groups of functions/methods that share a normalized name
across different files. Confirm whether each cluster is a REAL duplicate (same intent,
consolidatable) or coincidental, and record behavior differences.

## Input
A JSON object on the prompt: `{cluster_id: [ {entity_id,name,file_path,start_line,end_line,description}, ... ], ... }`.
Plus `REPO_DIR` (absolute repo path). Work from REPO_DIR.

## For each cluster
1. Read each member's implementation: `sem context <name> --file <relative-path> --json`
   (run from REPO_DIR) or `Read` the file at the line range.
2. Decide:
   - `real-dup` — the implementations do the same thing and could be consolidated.
   - `not-dup` — same name, genuinely different behavior/context.
3. If `real-dup`, record concrete **behavior differences** between the implementations
   (algorithms, error handling, edge cases, parameters) — these matter for a safe merge.
4. Recommend one of: `consolidate` (merge into one), `extract-common` (factor a shared
   helper), or `leave-as-is` (differences make merging net-negative).
5. Estimate `impact` (duplication's maintenance/bug-risk cost), `risk` (of consolidating),
   `effort`.

## Output
Respond with ONLY a JSON array of:
`{cluster_id, verdict, recommendation, impact, risk, effort, behavior_diff, notes}`.
No prose, no fences.
```

- [ ] **Step 2: Commit**

```bash
git add dev/agents/dedupe-verify-dup.md
git commit -m "feat(dedupe): duplication verifier subagent prompt"
```

---

### Task 10: Skill orchestration (SKILL.md)

**Files:**
- Modify (overwrite): `dev/skills/dedupe/SKILL.md`

- [ ] **Step 1: Overwrite SKILL.md**

Replace the entire file with:

````markdown
---
name: dedupe
version: 2.0.0
description: Find dead code and duplication across a codebase using the sem CLI, then produce a ranked, risk-assessed plan and optionally apply it. Use when the user asks to dedupe, find duplicate or redundant code, or find dead/unused code. Takes a path scope (e.g. /dedupe server/) to exclude unrelated tools/scripts. Supports Go, TypeScript/JavaScript, and Python.
---

# dedupe

Find dead code and duplication with the `sem` CLI, verify candidates with parallel
subagents, and produce a prioritized plan. SQLite is the coordination spine; the LLM is
spent only on per-candidate verification.

Bundled tool: `${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py`.
Bundled agents: `${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dead.md`, `dedupe-verify-dup.md`.

## Usage

```
/dedupe [path ...]            # scope to these dirs (default: whole repo)
/dedupe server/ --exts .go    # scope to a dir and language
```

## Scope of detection (important)
- **Dead code** (Go, Python, TypeScript): candidates are non-entrypoint, non-test
  functions/methods with no callers in sem's graph, then filtered by a deterministic
  whole-repo usage scan that removes any whose name is referenced anywhere outside its
  definition (this catches interface dispatch, goroutine launches, and cross-module
  imports sem misses). The small residual is verified by a subagent. Detection favors
  precision (never flags used code) over recall (may miss some dead code). Residual
  **exported** symbols are flagged for a public-API check — they may be called from outside
  the repo.
- **Duplication** covers all functions/methods (name/description based; independent of the
  call graph).

## Process

### 1. Preflight
- Confirm `sem` is available: `sem --version`. If missing, stop and tell the user to install it.
- Determine repo dir (default cwd) and path scope from arguments. Ensure `.dedupe/` is gitignored.

### 2. Load + detect (one tool call)
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py load <scope> [--exts ...] -C <repo-dir>
```
This runs `sem graph --json` once, filters to in-scope code entities, ingests any SEM
marker descriptions, derives raw dead-code candidates, runs the deterministic whole-repo
usage refutation, and derives duplication candidates — all into `.dedupe/dedupe.db`. Read
the JSON summary (entities, edges, descriptions, dead_candidates_raw,
dead_refuted_by_usage, dead_candidates, dup_clusters).

If SEM-description coverage is low, make a single offer: "Run /sem-annotate first for
better duplicate detection?" — never annotate inline.

### 3. Get candidates
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py candidates -C <repo-dir> > /tmp/dedupe-cands.json
```
This yields `{"dead": [...], "dup_clusters": {...}}`.

### 4. Verify (parallel subagents, BATCHED)
- **Batch** candidates (~15–20 per subagent) — do NOT spawn one subagent per candidate.
  For each batch of dead candidates, dispatch a `general-purpose` subagent following
  `${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dead.md` with the batch JSON and
  `REPO_DIR=<repo-dir>`. For dup clusters, batch similarly with
  `dedupe-verify-dup.md`. Run batches in parallel (one message, multiple Task calls).
- **Cap:** if there are more than ~120 dead candidates or ~60 dup clusters, verify the
  first N (ordered as returned) and `log` exactly how many were deferred — never silently
  drop. Report the cap in the final summary.
- Each subagent returns ONLY a JSON array of verdicts. Collect them.

### 5. Record verdicts
Write every verdict to the DB with a single python call per kind, e.g.:
```bash
python3 -c "
import sys,json; sys.dont_write_bytecode=True
sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/scripts'); import dedupe as dd
conn=dd._connect('.dedupe/dedupe.db')
for v in json.load(open('/tmp/dead-verdicts.json')):
    dd.record_finding(conn,'dead',v['verdict'],entity_id=v['entity_id'],
        impact=v.get('impact',''),risk=v.get('risk',''),effort=v.get('effort',''),
        recommendation=v.get('recommendation',''),notes=v.get('notes',''))
"
```
(Do the analogous loop for dup verdicts with `cluster_id` and `behavior_diff`.)

### 6. Rank + report
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py report -C <repo-dir>
```
Show the user the report path and a short summary (counts, top items). The report ranks by
impact × inverse-risk and groups dead-code and duplication separately.

### 7. Offer to apply (opt-in)
Present the plan, then offer to execute approved items via **subagent-driven development**:
one fresh subagent per item (a dead-code removal, or a duplication consolidation), with
review between. Removals and consolidations are individually approvable. Never apply
without explicit approval.

## Notes
- The tool owns all deterministic work; the only LLM steps are candidate verification and
  (optionally) applying approved changes.
- `.dedupe/dedupe.db` persists; re-running `load` refreshes it.
````

- [ ] **Step 2: Commit**

```bash
git add dev/skills/dedupe/SKILL.md
git commit -m "feat(dedupe): rewrite SKILL.md orchestration for sem-based flow"
```

---

### Task 11: Remove old artifacts, version bump, register, e2e verify

**Files:**
- Delete: `dev/agents/dedupe-analyzer.md`, `dev/agents/dedupe-grouper.md`, `dev/agents/dedupe-deduplicator.md`, `dev/scripts/dedupe-report.py`
- Modify: `dev/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Delete the obsolete worker agents + old report script**

```bash
cd /Users/efitz/Projects/skills
git rm dev/agents/dedupe-analyzer.md dev/agents/dedupe-grouper.md \
       dev/agents/dedupe-deduplicator.md dev/scripts/dedupe-report.py
```

- [ ] **Step 2: Bump the dev plugin version to 2.0.0 + refresh description**

In `dev/.claude-plugin/plugin.json`, set `"version": "2.0.0"` and replace `description` with:
```
"Developer toolkit (sem-powered): annotate code with durable SEM@<sha> intent markers (sem-annotate), and find dead code + duplication and produce a ranked plan (dedupe). Uses the sem CLI entity graph. Supports Go, TypeScript/JavaScript, and Python."
```
In `.claude-plugin/marketplace.json`, set the `dev` plugin entry's `description` to the SAME string. Validate both with `python3 -m json.tool`.

Bumping the version is what lets a `claude` plugin update pick up sem-annotate + the dedupe rebuild.

- [ ] **Step 3: Run the full unit suite**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_dedupe tests.test_sem_annotate -v`
Expected: PASS (dedupe + sem-annotate suites).

- [ ] **Step 4: End-to-end run against tmi (read-only)**

```bash
cd /Users/efitz/Projects/skills
rm -rf /tmp/dedupe-e2e && mkdir -p /tmp/dedupe-e2e
python3 dev/scripts/dedupe.py --db /tmp/dedupe-e2e/dedupe.db load api/ --exts .go -C /Users/efitz/Projects/tmi
python3 dev/scripts/dedupe.py --db /tmp/dedupe-e2e/dedupe.db candidates -C /Users/efitz/Projects/tmi | python3 -c "import sys,json;d=json.load(sys.stdin);print('dead:',len(d['dead']),'dup clusters:',len(d['dup_clusters']))"
```
Expected: the `load` summary prints non-zero entities/edges and a tractable dead-candidate count (tens); `candidates` prints dead + dup counts. tmi is never mutated (read-only graph + report to /tmp).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(dedupe): remove old worker agents, bump dev plugin to 2.0.0, register"
```

---

## Self-Review

**Spec coverage:**
- SQLite spine + sem data source → Tasks 1–3.
- `sem graph` one-call graph (replaces per-entity impact) → Task 3 + Global Constraints.
- SEM-description ingestion (accelerant, graceful absence) → Task 4.
- Dead code = no incoming edges + deterministic whole-repo usage refutation (Go/Py/TS) + verifier for residual + limitation note → Tasks 5, 7, 8, 10.
- Reliable across Go, Python, TypeScript via the language-agnostic token usage scan → Task 5 (`refute_dead_by_usage`), unit-tested with Go-style fixture; classifiers handle `.py`/`.ts` → Task 2.
- Duplication mechanical pre-filter → Task 6.
- Parallel batched verifiers (refutation-biased dead; behavior-diff dup) → Tasks 8, 9, 10.
- Rank by impact × inverse-risk; report → Task 7.
- Offer to apply via subagent-driven dev → Task 10.
- Coverage offer for /sem-annotate → Task 10.
- Remove old analyzer/grouper/deduplicator + old report script → Task 11.
- Path-scope arg; Go/TS/Python → Global Constraints, Tasks 2, 3, 10.
- Version bump so updates propagate → Task 11.

**Placeholder scan:** No TBD/TODO; all code/tests concrete. The verification cap (Task 10) is an explicit, logged bound, not a silent truncation.

**Type consistency:** `_filter_graph` emits entity dicts with `id/name/entity_type/file_path/start_line/end_line/is_exported/is_entrypoint/is_test`; `load_graph` inserts those columns; `candidates` emits `entity_id/name/file_path/start_line/end_line/description`; verifier agents consume those and emit `entity_id`/`cluster_id` + verdict fields; `record_finding`/`render_report` consume those. `find_dead_candidates` and `find_dup_candidates` both clear-then-insert (idempotent). Consistent across tasks.

## Deferred to a later plan
- `sem-auto` (post-commit follow-up-commit hook calling `sem-annotate --update`) — its own plan.
- Higher dead-code *recall* (finding more genuinely-dead code without lowering precision) via language-native reachability tools (e.g. Go `deadcode`, TS `ts-prune`, Python `vulture`) as an optional cross-check — future enhancement. See also issue #5 (embeddings/standardization) for duplication recall.
