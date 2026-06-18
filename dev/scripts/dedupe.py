"""dedupe: find dead code and duplication via the sem CLI entity graph."""
import os
import sqlite3

CODE_TYPES = {"function", "method", "type", "constant"}

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
