"""dedupe: find dead code and duplication via the sem CLI entity graph."""
import json
import os
import re
import sqlite3
import subprocess

CODE_TYPES = {"function", "method", "type", "constant"}

CODE_FILE_EXTS = (".go", ".py", ".ts", ".tsx", ".js", ".jsx")
_SKIP_DIRS = {"vendor", "node_modules", ".git", ".dedupe", "dist", "build",
              "__pycache__", ".venv", "venv", "testdata"}
_TOKEN_RE = re.compile(r"[A-Za-z_]\w*")

_ENTRYPOINT_PREFIXES = ("Test", "Benchmark", "Example", "Fuzz")

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


def is_unexported(name, file_path):
    """Check if a name is unexported (private) based on file type and naming convention."""
    _, ext = os.path.splitext(file_path)
    if ext.lower() == ".go":
        return bool(name) and name[0].islower()
    # python / ts / js convention: leading underscore is private
    return name.startswith("_")


def is_entrypoint(name):
    """Check if a name is a special entrypoint (main, init, Test*, Benchmark*, Example*, Fuzz*)."""
    return name in ("main", "init") or name.startswith(_ENTRYPOINT_PREFIXES)


def is_test(file_path):
    """Check if a file path indicates a test file."""
    p = file_path
    base = os.path.basename(p)
    if any(s in p for s in ("_test.go", ".test.", ".spec.",
                            "/test/", "/tests/", "/__tests__/")):
        return True
    if p.startswith(("test/", "tests/")):
        return True
    return base.startswith("test_")


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
