"""sem_db: SQLite annotation index (.local/sem.db) mirroring SEM markers.

Records the 'highest commit covered' (HEAD sha + commit count) so freshness vs. the
current HEAD is a one-line check. The DB is a regenerable mirror; in-source markers
remain the source of truth.
"""
import datetime
import os
import sqlite3
import subprocess

SCHEMA_VERSION = "1"
DB_REL = os.path.join(".local", "sem.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    file       TEXT NOT NULL,
    name       TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line   INTEGER,
    sha        TEXT,
    desc       TEXT,
    blame_sha  TEXT,
    updated_at TEXT,
    PRIMARY KEY (file, name, start_line)
);
CREATE INDEX IF NOT EXISTS idx_sem_entities_file ON entities(file);
"""


def db_path(cwd=None):
    base = cwd if cwd is not None else os.getcwd()
    return os.path.join(base, DB_REL)


def init_db(conn):
    conn.executescript(_SCHEMA)
    conn.commit()


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path)
    init_db(conn)
    return conn


def set_meta(conn, key, value):
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()


def get_meta(conn, key):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _git(args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip())
    return r.stdout.strip()


def git_head(cwd=None):
    """Return (sha, commit_count) for HEAD, or ('', '') if git/HEAD is unavailable."""
    try:
        sha = _git(["rev-parse", "HEAD"], cwd=cwd)
        count = _git(["rev-list", "--count", "HEAD"], cwd=cwd)
        return sha, count
    except Exception:
        return "", ""


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def stamp_head(conn, cwd=None):
    sha, count = git_head(cwd=cwd)
    set_meta(conn, "head_sha", sha)
    set_meta(conn, "head_commit_count", count)
    set_meta(conn, "schema_version", SCHEMA_VERSION)
    set_meta(conn, "updated_at", _now())


CODE_EXTS = (".go", ".ts", ".tsx", ".js", ".jsx", ".py")


def _entities_for(paths, cwd):
    import sem_annotate as sa
    out = []
    for e in sa.sem_entities(paths, cwd=cwd):
        if e.get("type") in sa.CODE_TYPES:
            out.append(e)
    return out


def index_files(conn, files, cwd=None):
    """Delete-then-insert rows for each file in `files`. Returns rows written."""
    import sem_annotate as sa
    written = 0
    now = _now()
    for f in files:
        conn.execute("DELETE FROM entities WHERE file=?", (f,))
        abspath = f if cwd is None else os.path.join(cwd, f)
        if sa.comment_prefix(f) is None or not os.path.exists(abspath):
            continue
        ents = [e for e in _entities_for([f], cwd) if (e.get("file") or f) == f]
        if not ents:
            continue
        lines = sa._read_text(abspath).splitlines()
        blame = {b["name"]: b for b in sa.sem_blame(f, cwd=cwd)}
        for e in ents:
            marker = sa.find_marker_above(lines, e["start_line"])
            conn.execute(
                "INSERT OR REPLACE INTO entities"
                "(file, name, start_line, end_line, sha, desc, blame_sha, updated_at)"
                " VALUES(?,?,?,?,?,?,?,?)",
                (f, e["name"], e["start_line"], e.get("end_line"),
                 marker["sha"] if marker else None,
                 marker["desc"] if marker else None,
                 blame.get(e["name"], {}).get("commit"), now),
            )
            written += 1
    conn.commit()
    return written


def _scope_files(cwd, paths):
    """Resolve the file list to index from explicit paths or the scope file."""
    import sem_annotate as sa
    import sem_scope
    scope = None
    if paths:
        scan_paths = list(paths)
    else:
        scope = sem_scope.load_scope(cwd)
        scan_paths = sem_scope.include_paths(scope)
    files = []
    seen = set()
    for e in _entities_for(scan_paths, cwd):
        f = e.get("file")
        if not f or f in seen:
            continue
        if scope is not None and sem_scope.is_excluded(f, scope):
            continue
        seen.add(f)
        files.append(f)
    return files


def build(cwd=None, paths=None):
    path = db_path(cwd)
    conn = connect(path)
    try:
        files = _scope_files(cwd, paths)
        if paths is None:
            conn.execute("DELETE FROM entities")
            conn.commit()
        n = index_files(conn, files, cwd=cwd)
        stamp_head(conn, cwd=cwd)
        return {"files": len(files), "entities": n}
    finally:
        conn.close()


def update(cwd=None, files=None):
    path = db_path(cwd)
    conn = connect(path)
    try:
        n = index_files(conn, list(files or []), cwd=cwd)
        stamp_head(conn, cwd=cwd)
        return {"files": len(files or []), "entities": n}
    finally:
        conn.close()


def changed_files(cwd, head_sha):
    """Code files differing from head_sha (incl. uncommitted) plus untracked code files."""
    files = set()
    if head_sha:
        try:
            out = _git(["diff", "--name-only", head_sha], cwd=cwd)
            files.update(x for x in out.splitlines() if x)
        except Exception:
            pass
    try:
        out = _git(["ls-files", "--others", "--exclude-standard"], cwd=cwd)
        files.update(x for x in out.splitlines() if x)
    except Exception:
        pass
    return [f for f in sorted(files) if f.endswith(CODE_EXTS)]


def auto_update(cwd=None):
    path = db_path(cwd)
    conn = connect(path)
    head = get_meta(conn, "head_sha")
    conn.close()
    if not head:
        res = build(cwd=cwd)
        res["mode"] = "full"
        return res
    import sem_scope
    scope = sem_scope.load_scope(cwd)
    include = (scope or {}).get("include") or []
    files = [f for f in changed_files(cwd, head)
             if (not include or any(f.startswith(p) for p in include))
             and not (scope is not None and sem_scope.is_excluded(f, scope))]
    conn = connect(path)
    try:
        n = index_files(conn, files, cwd=cwd)
        stamp_head(conn, cwd=cwd)
        return {"files": len(files), "entities": n, "mode": "auto"}
    finally:
        conn.close()


def status(cwd=None):
    path = db_path(cwd)
    conn = connect(path)
    try:
        stored_sha = get_meta(conn, "head_sha") or ""
        stored_count = get_meta(conn, "head_commit_count") or ""
    finally:
        conn.close()
    cur_sha, cur_count = git_head(cwd=cwd)
    if not stored_sha or not cur_sha:
        verdict = "unknown"
    elif stored_sha == cur_sha:
        verdict = "up-to-date"
    else:
        verdict = "stale"
    return {"stored_sha": stored_sha, "stored_count": stored_count,
            "current_sha": cur_sha, "current_count": cur_count, "verdict": verdict}
