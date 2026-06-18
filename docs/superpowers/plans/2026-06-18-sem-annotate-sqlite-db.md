# SQLite Annotation Index Implementation Plan (Issue #10)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `.local/sem.db` SQLite index that mirrors SEM markers and records the "highest commit covered" (HEAD sha + commit count), with full-build and incremental update, plus a freshness `status` command.

**Architecture:** A new module `dev/scripts/sem_db.py` owns all DB logic (schema, meta/head stamping, per-file indexing, git queries). `sem_annotate.py` gains a `db` subcommand (`build` / `update` / `status`) that calls into it. The DB is a regenerable mirror; in-source markers remain the source of truth.

**Tech Stack:** Python 3 stdlib (`sqlite3`, `subprocess`, `datetime`, `os`, `re`), `unittest`.

## Global Constraints

- DB path: `<repo>/.local/sem.db` (machine-local, gitignored). stdlib `sqlite3` only.
- "Highest commit covered" = `head_sha` (authoritative) + `head_commit_count` (= `git rev-list --count HEAD`), stamped on every refresh.
- DB honors `.local/sem-scope.json` (from Issue #8 / `sem_scope.py`) when no explicit paths are passed. **This plan depends on `sem_scope.py` existing** (land the Issue #8 plan first).
- Reuse existing `sem_annotate` helpers (`sem_entities`, `sem_blame`, `find_marker_above`, `_read_text`, `comment_prefix`) — do not duplicate marker parsing.
- Full suite: `python3 -m unittest discover -s tests -t . -q` must stay green.

---

### Task 1: `sem_db.py` — schema, connection, meta/head stamping

**Files:**
- Create: `dev/scripts/sem_db.py`
- Create: `tests/test_sem_db.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION = "1"`, `DB_REL = ".local/sem.db"`
  - `db_path(cwd=None) -> str`
  - `connect(path) -> sqlite3.Connection` (creates parent dir, inits schema)
  - `init_db(conn) -> None`
  - `set_meta(conn, key, value) -> None` / `get_meta(conn, key) -> str | None`
  - `git_head(cwd=None) -> tuple[str, str]` — `(sha, count)`; `("", "")` if unavailable
  - `stamp_head(conn, cwd=None) -> None` — writes `head_sha`, `head_commit_count`, `updated_at`, `schema_version`

- [ ] **Step 1: Write failing tests**

Create `tests/test_sem_db.py`:

```python
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_db as db


class TestSchemaMeta(unittest.TestCase):
    def test_connect_creates_db_and_schema(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".local", "sem.db")
            conn = db.connect(p)
            self.assertTrue(os.path.exists(p))
            tbls = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("meta", tbls)
            self.assertIn("entities", tbls)
            conn.close()

    def test_meta_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, "sem.db"))
            db.set_meta(conn, "head_sha", "abc123")
            db.set_meta(conn, "head_sha", "def456")  # upsert, not duplicate
            self.assertEqual(db.get_meta(conn, "head_sha"), "def456")
            self.assertIsNone(db.get_meta(conn, "missing"))
            conn.close()

    def test_stamp_head_uses_git_head(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, "sem.db"))
            db.git_head = lambda cwd=None: ("deadbeef", "42")
            db.stamp_head(conn, cwd=d)
            self.assertEqual(db.get_meta(conn, "head_sha"), "deadbeef")
            self.assertEqual(db.get_meta(conn, "head_commit_count"), "42")
            self.assertEqual(db.get_meta(conn, "schema_version"), db.SCHEMA_VERSION)
            self.assertIsNotNone(db.get_meta(conn, "updated_at"))
            conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_db -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sem_db'`.

- [ ] **Step 3: Implement schema/meta/head**

Create `dev/scripts/sem_db.py`:

```python
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
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_sem_db -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_db.py tests/test_sem_db.py
git commit -m "feat(sem-db): schema + meta/head stamping for .local/sem.db (#10)"
```

---

### Task 2: Per-file indexing (`index_files`) + `build` / `update`

**Files:**
- Modify: `dev/scripts/sem_db.py`
- Modify: `tests/test_sem_db.py`

**Interfaces:**
- Consumes: `sem_annotate.sem_entities`, `sem_annotate.sem_blame`, `sem_annotate.find_marker_above`, `sem_annotate._read_text`, `sem_annotate.comment_prefix`; `sem_scope` (for scope-aware build); `git_head`/`stamp_head` from Task 1.
- Produces:
  - `index_files(conn, files, cwd=None) -> int` — for each file: DELETE its rows, then re-insert one row per code entity (file, name, start/end line, marker sha+desc, blame_sha). Returns rows written. A file that no longer exists ends with zero rows (its old rows are deleted).
  - `build(cwd=None, paths=None) -> dict` — discover code files under `paths` (or scope file when `paths` falsy), `index_files` them, `stamp_head`. Returns `{"files": n, "entities": m}`.
  - `update(cwd=None, files=None) -> dict` — `index_files(files)` then `stamp_head`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sem_db.py` (monkeypatch `sem_annotate` so no real `sem` CLI is needed):

```python
import sem_annotate as sa


class TestIndexFiles(unittest.TestCase):
    def setUp(self):
        self.files = {
            "src/a.ts": "// SEM@aaaaaaa: build a thing\nfunction A() {}\n",
        }
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame)
        sa._read_text = lambda p, *a, **k: self.files[p.replace(self.repo + "/", "")] \
            if p.startswith(self.repo) else self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts",
             "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "aaaaaaa999"}]

    def tearDown(self):
        sa._read_text, sa.sem_entities, sa.sem_blame = self._orig

    def test_index_then_reindex_replaces(self):
        with tempfile.TemporaryDirectory() as d:
            self.repo = d
            os.makedirs(os.path.join(d, "src"))
            with open(os.path.join(d, "src", "a.ts"), "w") as f:
                f.write(self.files["src/a.ts"])
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            n = db.index_files(conn, ["src/a.ts"], cwd=d)
            self.assertEqual(n, 1)
            row = conn.execute(
                "SELECT name, sha, desc, blame_sha FROM entities WHERE file='src/a.ts'"
            ).fetchone()
            self.assertEqual(row[0], "A")
            self.assertEqual(row[1], "aaaaaaa")          # marker sha
            self.assertEqual(row[2], "build a thing")
            self.assertEqual(row[3], "aaaaaaa999")       # blame sha
            # re-index is idempotent (delete-then-insert; still one row)
            db.index_files(conn, ["src/a.ts"], cwd=d)
            cnt = conn.execute(
                "SELECT COUNT(*) FROM entities WHERE file='src/a.ts'").fetchone()[0]
            self.assertEqual(cnt, 1)
            conn.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_db.TestIndexFiles -v`
Expected: FAIL (`AttributeError: module 'sem_db' has no attribute 'index_files'`).

- [ ] **Step 3: Implement `index_files` / `build` / `update`**

Append to `dev/scripts/sem_db.py` (note the lazy import of `sem_annotate` inside functions to avoid an import cycle):

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_sem_db.TestIndexFiles -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_db.py tests/test_sem_db.py
git commit -m "feat(sem-db): per-file indexing + build/update (#10)"
```

---

### Task 3: Auto-incremental `update` (no args) + `status`

**Files:**
- Modify: `dev/scripts/sem_db.py`
- Modify: `tests/test_sem_db.py`

**Interfaces:**
- Produces:
  - `changed_files(cwd, head_sha) -> list[str]` — `git diff --name-only <head_sha>` (working tree vs stamped commit, so uncommitted marker writes count) ∪ `git ls-files --others --exclude-standard`, filtered to `CODE_EXTS`.
  - `auto_update(cwd=None) -> dict` — read stored `head_sha`; if absent ⇒ `build(cwd)`. Else compute `changed_files`, apply scope exclude, `index_files` them, `stamp_head`. Returns `{"files": n, "entities": m, "mode": "auto"|"full"}`.
  - `status(cwd=None) -> dict` — `{"stored_sha", "stored_count", "current_sha", "current_count", "verdict"}` where verdict ∈ `up-to-date` / `stale` / `unknown`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sem_db.py`:

```python
class TestAutoAndStatus(unittest.TestCase):
    def test_auto_update_falls_back_to_build_when_no_head(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            conn.close()
            called = {"build": 0}
            orig = db.build
            db.build = lambda cwd=None, paths=None: called.__setitem__("build", 1) or {"files": 0, "entities": 0, "mode": "full"}
            try:
                res = db.auto_update(cwd=d)
                self.assertEqual(called["build"], 1)
            finally:
                db.build = orig

    def test_status_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            conn = db.connect(os.path.join(d, ".local", "sem.db"))
            db.set_meta(conn, "head_sha", "aaaa")
            db.set_meta(conn, "head_commit_count", "5")
            conn.close()
            db.git_head = lambda cwd=None: ("aaaa", "5")
            self.assertEqual(db.status(cwd=d)["verdict"], "up-to-date")
            db.git_head = lambda cwd=None: ("bbbb", "6")
            self.assertEqual(db.status(cwd=d)["verdict"], "stale")
            db.git_head = lambda cwd=None: ("", "")
            self.assertEqual(db.status(cwd=d)["verdict"], "unknown")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_db.TestAutoAndStatus -v`
Expected: FAIL (`AttributeError: ... 'auto_update'`).

- [ ] **Step 3: Implement `changed_files`, `auto_update`, `status`**

Append to `dev/scripts/sem_db.py`:

```python
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
    files = [f for f in changed_files(cwd, head)
             if not (scope is not None and sem_scope.is_excluded(f, scope))]
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m unittest tests.test_sem_db.TestAutoAndStatus -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_db.py tests/test_sem_db.py
git commit -m "feat(sem-db): auto-incremental update + status freshness check (#10)"
```

---

### Task 4: `db` subcommand in `sem_annotate.py` CLI

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`parse_args`, `main`)
- Modify: `tests/test_sem_annotate.py`

**Interfaces:**
- Consumes: `sem_db.build`, `sem_db.update`, `sem_db.auto_update`, `sem_db.status` (lazy import inside `main`).
- Produces CLI: `sem_annotate.py db build [paths] -C <dir>` / `db update [files] -C <dir>` / `db status -C <dir>`. `db update` with no files ⇒ `auto_update`. Each prints a JSON result line.

- [ ] **Step 1: Write failing test**

Add to `tests/test_sem_annotate.py` (CLI-dispatch test; monkeypatch `sa`'s lazy `sem_db` by patching the module attribute it imports). Use a simple dispatch check:

```python
class TestDbSubcommand(unittest.TestCase):
    def test_db_status_dispatches(self):
        import sem_db
        orig = sem_db.status
        sem_db.status = lambda cwd=None: {"verdict": "up-to-date", "stored_sha": "x",
                                          "stored_count": "1", "current_sha": "x",
                                          "current_count": "1"}
        out = io.StringIO()
        _stdout = sys.stdout
        sys.stdout = out
        try:
            rc = sa.main(["db", "status", "-C", "/tmp"])
        finally:
            sys.stdout = _stdout
            sem_db.status = orig
        self.assertEqual(rc, 0)
        self.assertIn("up-to-date", out.getvalue())

    def test_db_update_no_files_is_auto(self):
        import sem_db
        called = {"auto": 0}
        orig = sem_db.auto_update
        sem_db.auto_update = lambda cwd=None: called.__setitem__("auto", 1) or {"mode": "auto", "files": 0, "entities": 0}
        try:
            rc = sa.main(["db", "update", "-C", "/tmp"])
        finally:
            sem_db.auto_update = orig
        self.assertEqual(rc, 0)
        self.assertEqual(called["auto"], 1)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestDbSubcommand -v`
Expected: FAIL (unknown subcommand `db` / argparse error).

- [ ] **Step 3: Implement the `db` subcommand**

In `dev/scripts/sem_annotate.py` `parse_args`, register the subparser:

```python
    dbp = sub.add_parser("db")
    dbp.add_argument("db_action", choices=["build", "update", "status"])
    dbp.add_argument("paths", nargs="*", default=None)
    dbp.add_argument("-C", "--cwd", default=None)
```

In `main`, add a branch (lazy import to avoid an import cycle at module load):

```python
    if ns.cmd == "db":
        import sem_db
        action = ns.db_action
        paths = ns.paths or None
        if action == "build":
            res = sem_db.build(cwd=ns.cwd, paths=paths)
        elif action == "update":
            res = sem_db.update(cwd=ns.cwd, files=paths) if paths \
                else sem_db.auto_update(cwd=ns.cwd)
        else:  # status
            res = sem_db.status(cwd=ns.cwd)
        print(json.dumps(res))
        return 0
```

Update the usage line at the bottom of `main` to mention `db`.

- [ ] **Step 4: Run db tests + full suite**

Run: `python3 -m unittest tests.test_sem_annotate.TestDbSubcommand -v`
Expected: PASS.
Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): db subcommand (build/update/status) (#10)"
```

---

### Task 5: Skill integration + docs

**Files:**
- Modify: `dev/skills/sem-annotate/SKILL.md`

- [ ] **Step 1: Add a DB-refresh step after "Write markers"**

In `dev/skills/sem-annotate/SKILL.md`, after Step 4 (Write markers), add a step:
- Full-scope annotate ⇒ `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py db build [paths] -C <repo-dir>`.
- `--update <files>` annotate ⇒ `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py db update <files> -C <repo-dir>`.
- Note `.local/sem.db` is a gitignored, regenerable mirror; the source markers remain the source of truth.

- [ ] **Step 2: Document the freshness check**

Add a short note: run `... db status -C <repo-dir>` to compare the stored "highest commit covered" (`head_sha` / `head_commit_count`) against current HEAD; `db update` (no files) re-indexes only files changed since the stamped commit.

- [ ] **Step 3: Verify**

Run: `grep -n "db build\|db update\|db status\|sem.db" dev/skills/sem-annotate/SKILL.md`
Expected: all present.

- [ ] **Step 4: Commit**

```bash
git add dev/skills/sem-annotate/SKILL.md
git commit -m "docs(sem-annotate): document sem.db index + freshness check (#10)"
```

## Self-Review

- Spec coverage: `.local/sem.db` + schema (Task 1) ✓; head sha+count "highest commit covered" (Task 1) ✓; per-file index + full build (Task 2) ✓; targeted `update <files>` (Task 2) ✓; auto `update` via `git diff <head_sha>` + untracked, scope-filtered, fallback to build (Task 3) ✓; `status` verdict (Task 3) ✓; scope-file honored (Task 2 `_scope_files`, Task 3 auto) ✓; CLI subcommand (Task 4) ✓; skill docs (Task 5) ✓.
- Type consistency: `index_files`/`build`/`update`/`auto_update`/`status`/`git_head`/`stamp_head`/`changed_files` names consistent across tasks ✓.
- Dependency on `sem_scope.py` (Issue #8) called out in Global Constraints ✓.
- No placeholders.
