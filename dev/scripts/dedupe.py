"""dedupe: find dead code and duplication via the sem CLI entity graph."""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys

CODE_TYPES = {"function", "method", "type", "constant"}

_VERB_SYNONYMS = {
    "get": "fetch", "retrieve": "fetch", "load": "fetch",
    "check": "validate", "verify": "validate", "ensure": "validate",
    "create": "build", "make": "build", "construct": "build",
    "remove": "delete",
}

_CAMEL_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")

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


def normalize_name(name):
    """Normalize a name by splitting camelCase/snake_case into tokens, lowercasing,
    applying verb synonyms, and returning sorted tokens joined by spaces."""
    tokens = [t.lower() for t in _CAMEL_RE.findall(name) if t]
    tokens = [_VERB_SYNONYMS.get(t, t) for t in tokens]
    return " ".join(sorted(tokens))


def find_dup_candidates(conn):
    """Cluster functions/methods (non-test) that share a normalized signature
    across different files. Keep only clusters with ≥2 members spanning ≥2 distinct files.
    Returns the cluster count. Idempotent."""
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
