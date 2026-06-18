# Repo-local Scope File Implementation Plan (Issue #8)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a repo-local, gitignored `.local/sem-scope.json` scope file (include/exclude globs) honored by both `sem_annotate.py scan` and `dedupe.py load` when no explicit path arg is given.

**Architecture:** A new shared module `dev/scripts/sem_scope.py` owns scope loading and glob matching. Both tools import it. Explicit path args always fully override the file.

**Tech Stack:** Python 3 stdlib (`json`, `os`, `re`), `unittest`.

## Global Constraints

- JSON only (no PyYAML). File path: `<repo>/.local/sem-scope.json`.
- Precedence: explicit path args ⇒ ignore the scope file entirely (no include, no exclude).
- Malformed scope JSON ⇒ raise a clear error (never silently fall back to whole-repo).
- Run the full suite with: `python3 -m unittest discover -s tests -t . -q` (must stay green; currently 102 tests).
- Tests import modules via `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))`.

---

### Task 1: Shared `sem_scope.py` module + unit tests

**Files:**
- Create: `dev/scripts/sem_scope.py`
- Create: `tests/test_sem_scope.py`

**Interfaces:**
- Produces (used by Tasks 2 and 3):
  - `load_scope(cwd=None) -> dict | None` — parse `<cwd>/.local/sem-scope.json`; `None` if absent; raises `ValueError`/`json.JSONDecodeError` on malformed.
  - `glob_match(relpath: str, pattern: str) -> bool` — glob over POSIX relpaths; `**` crosses `/`, `*`/`?` do not; trailing `/` = directory-prefix.
  - `is_excluded(relpath: str, scope: dict | None) -> bool` — true if `relpath` matches any `scope["exclude"]` pattern.
  - `include_paths(scope: dict | None) -> list[str]` — `scope["include"]` if non-empty else `["."]` (sem-annotate semantics; dedupe reads raw `include`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_sem_scope.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_scope as ss


class TestGlobMatch(unittest.TestCase):
    def test_dir_prefix_trailing_slash(self):
        self.assertTrue(ss.glob_match("scripts", "scripts/"))
        self.assertTrue(ss.glob_match("scripts/build.ts", "scripts/"))
        self.assertFalse(ss.glob_match("scriptsx/build.ts", "scripts/"))

    def test_doublestar_crosses_slashes(self):
        self.assertTrue(ss.glob_match("src/a/b.spec.ts", "**/*.spec.ts"))
        self.assertTrue(ss.glob_match("b.spec.ts", "**/*.spec.ts"))
        self.assertFalse(ss.glob_match("src/a/b.ts", "**/*.spec.ts"))

    def test_single_star_does_not_cross_slash(self):
        self.assertTrue(ss.glob_match("a.ts", "*.ts"))
        self.assertFalse(ss.glob_match("a/b.ts", "*.ts"))

    def test_question_mark(self):
        self.assertTrue(ss.glob_match("a.ts", "?.ts"))
        self.assertFalse(ss.glob_match("ab.ts", "?.ts"))
        self.assertFalse(ss.glob_match("a/c", "a?c"))   # ? must not cross '/'


class TestIsExcluded(unittest.TestCase):
    def test_any_pattern_matches(self):
        scope = {"exclude": ["scripts/", "**/*.spec.ts"]}
        self.assertTrue(ss.is_excluded("scripts/x.ts", scope))
        self.assertTrue(ss.is_excluded("src/a.spec.ts", scope))
        self.assertFalse(ss.is_excluded("src/a.ts", scope))

    def test_none_scope_or_no_exclude(self):
        self.assertFalse(ss.is_excluded("a.ts", None))
        self.assertFalse(ss.is_excluded("a.ts", {}))

    def test_backslashes_normalized(self):
        self.assertTrue(ss.is_excluded("scripts\\x.ts", {"exclude": ["scripts/"]}))


class TestIncludePaths(unittest.TestCase):
    def test_default_when_empty(self):
        self.assertEqual(ss.include_paths(None), ["."])
        self.assertEqual(ss.include_paths({}), ["."])
        self.assertEqual(ss.include_paths({"include": []}), ["."])

    def test_returns_include(self):
        self.assertEqual(ss.include_paths({"include": ["src/", "e2e/"]}), ["src/", "e2e/"])


class TestLoadScope(unittest.TestCase):
    def test_absent_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(ss.load_scope(d))

    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                json.dump({"include": ["src/"], "exclude": ["scripts/"]}, f)
            scope = ss.load_scope(d)
            self.assertEqual(scope["include"], ["src/"])
            self.assertEqual(scope["exclude"], ["scripts/"])

    def test_malformed_json_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                f.write("{not json")
            with self.assertRaises(Exception):
                ss.load_scope(d)

    def test_wrong_type_raises(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, ".local"))
            with open(os.path.join(d, ".local", "sem-scope.json"), "w") as f:
                json.dump({"include": "src/"}, f)  # not a list
            with self.assertRaises(ValueError):
                ss.load_scope(d)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_sem_scope -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sem_scope'`.

- [ ] **Step 3: Implement `sem_scope.py`**

Create `dev/scripts/sem_scope.py`:

```python
"""sem_scope: shared repo-local scope file (.local/sem-scope.json) for the sem tools.

When a tool is invoked with no explicit path argument it consults this file for default
include/exclude globs. Explicit path arguments always fully override the file.
"""
import json
import os
import re

SCOPE_REL = os.path.join(".local", "sem-scope.json")

_REGEX_CACHE = {}


def load_scope(cwd=None):
    """Return the parsed .local/sem-scope.json dict, or None if the file is absent.

    Raises on malformed JSON or wrong value types (never silently falls back).
    """
    base = cwd if cwd is not None else os.getcwd()
    path = os.path.join(base, SCOPE_REL)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{SCOPE_REL}: expected a JSON object")
    for key in ("include", "exclude"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"{SCOPE_REL}: '{key}' must be a list of strings")
    return data


def _compile(pattern):
    """Compile a glob pattern to a regex over POSIX relative paths (cached)."""
    rx = _REGEX_CACHE.get(pattern)
    if rx is not None:
        return rx
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        rx = re.compile(re.escape(prefix) + r"(?:/.*)?\Z", re.S)
    else:
        i, n = 0, len(pattern)
        out = []
        while i < n:
            c = pattern[i]
            if c == "*":
                j = i
                while j < n and pattern[j] == "*":
                    j += 1
                if j - i >= 2:  # '**'
                    if pattern[j:j + 1] == "/":
                        out.append("(?:.*/)?")
                        j += 1
                    else:
                        out.append(".*")
                    i = j
                    continue
                out.append("[^/]*")
                i += 1
            elif c == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(c))
                i += 1
        rx = re.compile("".join(out) + r"\Z", re.S)
    _REGEX_CACHE[pattern] = rx
    return rx


def glob_match(relpath, pattern):
    """True if POSIX-style relpath matches glob pattern.

    '**' crosses path separators; '*' and '?' do not; a trailing '/' is a directory prefix.
    """
    relpath = relpath.replace("\\", "/")
    return _compile(pattern).match(relpath) is not None


def is_excluded(relpath, scope):
    """True if relpath matches any pattern in scope['exclude']."""
    if not scope:
        return False
    for pat in scope.get("exclude") or []:
        if glob_match(relpath, pat):
            return True
    return False


def include_paths(scope):
    """Entity-discovery paths from scope['include'], defaulting to ['.'] when empty.

    Note: this default ('.') suits sem-annotate, which must pass a path to `sem entities`.
    dedupe treats an empty include as 'whole repo' and reads scope['include'] directly.
    """
    inc = (scope or {}).get("include") or []
    return list(inc) if inc else ["."]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_sem_scope -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_scope.py tests/test_sem_scope.py
git commit -m "feat(sem): shared sem_scope.py scope-file loader + glob matcher (#8)"
```

---

### Task 2: Wire scope into `sem_annotate.py scan`

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`scan`, `parse_args`, top of file)
- Modify: `tests/test_sem_annotate.py` (add scope-precedence tests)

**Interfaces:**
- Consumes: `sem_scope.load_scope`, `sem_scope.include_paths`, `sem_scope.is_excluded`.
- Produces: `scan(paths, cwd=None, rebuild=False)` where `paths=None`/`[]` ⇒ consult scope file; non-empty `paths` ⇒ explicit (scope ignored).

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sem_annotate.py` (inside the existing scan test class or a new class; reuse the monkeypatch pattern from `TestScan.setUp`). The class must monkeypatch `sa._read_text`, `sa.sem_entities`, `sa.sem_blame`, `sa.logic_changed_entities`, and also `sa.sem_scope.load_scope`:

```python
class TestScanScope(unittest.TestCase):
    def setUp(self):
        # No markers => both entities classify as "missing" (surfaced by scan).
        self.files = {"src/a.ts": "function A() {}\n",
                      "scripts/b.ts": "function B() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.logic_changed_entities, sa.sem_scope.load_scope)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 1, "end_line": 1},
            {"name": "B", "type": "function", "file": "scripts/b.ts", "start_line": 1, "end_line": 1},
        ]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ccc"}, {"name": "B", "commit": "ddd"}]
        sa.logic_changed_entities = lambda base, f, cwd=None: set()

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.logic_changed_entities, sa.sem_scope.load_scope) = self._orig

    def test_scope_exclude_drops_entities(self):
        sa.sem_scope.load_scope = lambda cwd=None: {"include": ["src/", "scripts/"],
                                                    "exclude": ["scripts/"]}
        work = sa.scan(None)
        names = {w["name"] for w in work}
        self.assertIn("A", names)            # src/ kept (missing marker -> surfaced)
        self.assertNotIn("B", names)         # scripts/ excluded by scope

    def test_explicit_paths_ignore_scope(self):
        called = {"n": 0}
        def boom(cwd=None):
            called["n"] += 1
            return {"exclude": ["**/*"]}
        sa.sem_scope.load_scope = boom
        sa.scan(["src/a.ts"])
        self.assertEqual(called["n"], 0)     # explicit args => scope file never consulted
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestScanScope -v`
Expected: FAIL (`AttributeError: module 'sem_annotate' has no attribute 'sem_scope'`, and/or `scan(None)` errors).

- [ ] **Step 3: Implement the wiring**

In `dev/scripts/sem_annotate.py`:

a. Add `import sem_scope` near the other imports.

b. Change `scan` to consult the scope file when no explicit paths, and drop excluded entities. Replace the head of `scan`:

```python
def scan(paths, cwd=None, rebuild=False):
    """Worklist for entities classified missing/stale (or all when rebuild=True).

    paths is None or [] => consult .local/sem-scope.json (include/exclude). Non-empty
    paths are explicit and bypass the scope file entirely.
    """
    if paths:
        scope = None
        scan_paths = list(paths)
    else:
        scope = sem_scope.load_scope(cwd)
        scan_paths = sem_scope.include_paths(scope)
    entities = [e for e in sem_entities(scan_paths, cwd=cwd) if e.get("type") in CODE_TYPES]
    by_file = {}
    for e in entities:
        f = e.get("file") or (scan_paths[0] if len(scan_paths) == 1 else None)
        if f is None:
            continue
        if scope is not None and sem_scope.is_excluded(f, scope):
            continue
        by_file.setdefault(f, []).append(e)
    # ... (rest of the existing per-file loop unchanged)
```

Keep the remainder of `scan` (the `for f, ents in by_file.items()` loop) exactly as it is.

c. In `parse_args`, change the `scan` positional default so "no args" is distinguishable:

```python
    s = sub.add_parser("scan")
    s.add_argument("paths", nargs="*", default=None)
```

and where the top-level `--update` branch sets `ns.paths`, leave it (those are explicit). Ensure `main`'s `scan` call passes `ns.paths` (which is `None`/`[]` when nothing was given).

- [ ] **Step 4: Run scope tests + full suite**

Run: `python3 -m unittest tests.test_sem_annotate.TestScanScope -v`
Expected: PASS.
Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK (no regressions).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): honor .local/sem-scope.json when no path arg (#8)"
```

---

### Task 3: Wire scope into `dedupe.py load`

**Files:**
- Modify: `dev/scripts/dedupe.py` (`_in_scope`, `_filter_graph`, `load_graph`, `main` load branch, imports)
- Modify: `tests/test_dedupe.py` (add scope tests)

**Interfaces:**
- Consumes: `sem_scope.load_scope`, `sem_scope.is_excluded`.
- Note: dedupe uses raw `scope["include"]` as path **prefixes** (empty ⇒ whole repo), NOT `include_paths()` (whose `['.']` default would break dedupe's `startswith` semantics).

- [ ] **Step 1: Read the current functions**

Run: `sed -n '102,152p' dev/scripts/dedupe.py`
Note the exact signatures of `_in_scope`, `_filter_graph`, `load_graph` and how `main` calls `load_graph` in the `load` branch.

- [ ] **Step 2: Write failing tests**

Add to `tests/test_dedupe.py` a class that exercises exclude filtering through `_in_scope` (adapt names/signature to what Step 1 shows):

```python
class TestScopeFile(unittest.TestCase):
    def test_in_scope_excludes_glob(self):
        # include prefix kept, exclude glob drops the file
        self.assertTrue(dd._in_scope("src/a.ts", ["src/"], dd.CODE_FILE_EXTS, exclude=["**/*.spec.ts"]))
        self.assertFalse(dd._in_scope("src/a.spec.ts", ["src/"], dd.CODE_FILE_EXTS, exclude=["**/*.spec.ts"]))

    def test_in_scope_no_exclude_unchanged(self):
        self.assertTrue(dd._in_scope("src/a.ts", ["src/"], dd.CODE_FILE_EXTS))
        self.assertFalse(dd._in_scope("other/a.ts", ["src/"], dd.CODE_FILE_EXTS))
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest tests.test_dedupe.TestScopeFile -v`
Expected: FAIL (`_in_scope() got an unexpected keyword argument 'exclude'`).

- [ ] **Step 4: Implement the wiring**

In `dev/scripts/dedupe.py`:

a. Add `import sem_scope` near the imports.

b. Add an optional `exclude` parameter to `_in_scope` and apply it after the prefix check:

```python
def _in_scope(path, scope_paths, exts, exclude=None):
    if scope_paths and not any(path.startswith(s) for s in scope_paths):
        return False
    if exclude and sem_scope.is_excluded(path, {"exclude": exclude}):
        return False
    # ... existing extension check unchanged ...
```

c. Thread `exclude` through `_filter_graph(graph, scope_paths, exts, exclude=None)` and `load_graph(conn, scope_paths, exts=None, cwd=None, exclude=None)` (pass it down to `_in_scope`/`_filter_graph`). Keep existing call sites working by defaulting `exclude=None`.

d. In `main`'s `load` branch, when the `scope` positional is empty, consult the scope file:

```python
    scope_paths = list(ns.scope)
    exclude = None
    if not scope_paths:
        scope_file = sem_scope.load_scope(ns.cwd)
        if scope_file:
            scope_paths = list(scope_file.get("include") or [])   # [] => whole repo
            exclude = scope_file.get("exclude") or None
    # then pass scope_paths + exclude into load_graph(...)
```

- [ ] **Step 5: Run scope tests + full suite**

Run: `python3 -m unittest tests.test_dedupe.TestScopeFile -v`
Expected: PASS.
Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK.

- [ ] **Step 6: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "feat(dedupe): honor .local/sem-scope.json when no scope arg (#8)"
```

---

### Task 4: Document the scope file in both SKILL.md files

**Files:**
- Modify: `dev/skills/sem-annotate/SKILL.md`
- Modify: `dev/skills/dedupe/SKILL.md`

- [ ] **Step 1: Add a "Scope file" note to sem-annotate SKILL.md**

Add a short subsection (near Usage/Preflight) describing `.local/sem-scope.json`:
- JSON shape `{ "include": [...], "exclude": [...] }`, both optional.
- Used as the default scope when no path argument is passed; explicit paths fully override.
- Machine-local and gitignored (`.local/` convention); globs support `**`, `*`, `?`, and trailing-`/` directory prefixes.

- [ ] **Step 2: Add the same note to dedupe SKILL.md**

Describe the same file and precedence; note that an empty/absent `include` means whole-repo, and `exclude` globs drop matching files.

- [ ] **Step 3: Verify**

Run: `grep -rn "sem-scope.json" dev/skills/`
Expected: both SKILL.md files mention it.

- [ ] **Step 4: Commit**

```bash
git add dev/skills/sem-annotate/SKILL.md dev/skills/dedupe/SKILL.md
git commit -m "docs(sem): document .local/sem-scope.json scope file (#8)"
```

## Self-Review

- Spec coverage: shared module (Task 1) ✓; sem-annotate wiring + precedence (Task 2) ✓; dedupe wiring + precedence (Task 3) ✓; glob `**`/`*`/`?`/dir-prefix tests (Task 1) ✓; malformed-JSON error (Task 1) ✓; docs (Task 4) ✓.
- Type consistency: `load_scope`/`is_excluded`/`include_paths`/`glob_match` names identical across tasks ✓.
- No placeholders.
