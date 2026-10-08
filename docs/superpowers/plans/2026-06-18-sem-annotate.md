# sem-annotate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `sem-annotate` skill that generates and refreshes `// SEM@<sha>:` intent markers on code entities, using the `sem` CLI for entity/blame/diff data and parallel subagents for description generation.

**Architecture:** A single testable Python tool (`dev/scripts/sem_annotate.py`) owns all deterministic work — calling the `sem` CLI, parsing/classifying existing markers, and writing markers into source with correct per-language comment syntax and the entity's last-change SHA. The skill orchestration (`SKILL.md`) runs the tool's `scan` to get a worklist, dispatches description-writer subagents (`dev/agents/sem-describe.md`) that follow the description content standard, then runs the tool's `write` to apply markers. Drift is detected via `sem diff <sha>..HEAD --no-cosmetics`, which surfaces only logical changes.

**Tech Stack:** Python 3.14 (stdlib only: `re`, `json`, `subprocess`, `argparse`, `pathlib`, `unittest`), the `sem` CLI (`/opt/homebrew/bin/sem`), Claude Code skills + agents.

## Global Constraints

- **Python: stdlib only.** No third-party deps (matches `github/scripts` convention). Tests use `unittest`, run via `python3 -m unittest`.
- **No bytecode in plugin dirs:** every script and test sets `sys.dont_write_bytecode = True` before imports that touch plugin dirs (the installer ships the working tree, not just git-tracked files).
- **Tests live at repo-root `tests/`** (outside plugin dirs so they are not distributed), importing the module under test via `sys.path.insert(0, <plugin>/scripts)`.
- **Marker format (verbatim):** `<comment-prefix> SEM@<sha>: <description>` where `<comment-prefix>` is `//` (Go/TS/JS) or `#` (Python). `<sha>` is the entity's last-change commit (short or full hex). One line, placed on the line immediately above the entity's definition.
- **Comment syntax by extension:** `//` for `.go .ts .tsx .js .jsx`; `#` for `.py`. Other extensions are unsupported and skipped.
- **Entity-granular updates (invariant):** never rewrite a marker for an entity that did not logically change. A commit/file touching one entity must not bump sibling entities' SHAs.
- **Description content standard:** intent not mechanism; lead with a canonical verb; canonical domain noun subject; abstract incidental identifiers; ≤ ~12 words; do not restate the entity name; tag a strong side-effect when it discriminates. (Full standard reproduced in Task 7.)
- **sem CLI invocation:** always pass `--json`; target a repo with `-C <dir>` when not running in cwd; `sem entities` omits the `file` field for single-file args (fall back to the queried path).

## File Structure

- `dev/scripts/sem_annotate.py` — the tool: CLI subprocess wrappers, marker parse/build/apply, classification, `scan`/`write`, `main()` with subcommands.
- `dev/skills/sem-annotate/SKILL.md` — orchestration prose (scan → dispatch describers → write → diff → offer CLAUDE.md note).
- `dev/agents/sem-describe.md` — description-writer subagent prompt embedding the content standard.
- `tests/test_sem_annotate.py` — unit tests for the tool's pure functions and arg parsing.
- `dev/.claude-plugin/plugin.json` — bump description to mention sem-annotate.
- `.claude-plugin/marketplace.json` — update the `dev` plugin description.

---

### Task 1: Script scaffold, constants, comment-prefix resolver

**Files:**
- Create: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces: `COMMENT_BY_EXT: dict[str,str]`, `comment_prefix(path: str) -> str | None`, `SEM_MARKER_RE: re.Pattern`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sem_annotate.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))

import sem_annotate as sa


class TestCommentPrefix(unittest.TestCase):
    def test_go_ts_js_use_slashes(self):
        for p in ("a/b/x.go", "x.ts", "x.tsx", "x.js", "x.jsx"):
            self.assertEqual(sa.comment_prefix(p), "//", p)

    def test_python_uses_hash(self):
        self.assertEqual(sa.comment_prefix("pkg/mod/x.py"), "#")

    def test_unsupported_returns_none(self):
        self.assertIsNone(sa.comment_prefix("README.md"))
        self.assertIsNone(sa.comment_prefix("x.rs"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sem_annotate'`.

- [ ] **Step 3: Write minimal implementation**

```python
# dev/scripts/sem_annotate.py
"""sem-annotate: generate and refresh SEM@<sha> intent markers on code entities."""
import re
import os

COMMENT_BY_EXT = {
    ".go": "//", ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//",
    ".py": "#",
}

# Matches a SEM marker line: indent, comment prefix, short/full hex sha, description.
SEM_MARKER_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>//|#)\s*SEM@(?P<sha>[0-9a-fA-F]{4,40}):\s?(?P<desc>.*)$"
)


def comment_prefix(path):
    """Return the line-comment prefix for a file path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    return COMMENT_BY_EXT.get(ext.lower())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): script scaffold + comment-prefix resolver"
```

---

### Task 2: Parse existing markers and find the marker above an entity

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Consumes: `SEM_MARKER_RE`.
- Produces: `parse_markers(text: str) -> dict[int, dict]` (0-based line index → `{"sha": str, "desc": str}`); `find_marker_above(lines: list[str], start_line: int) -> dict | None` (looks at the line directly above the 1-based `start_line`).

- [ ] **Step 1: Write the failing test**

```python
class TestParseMarkers(unittest.TestCase):
    SRC = (
        "package auth\n"                                  # 0
        "\n"                                              # 1
        "// SEM@b14a829: validate an oauth token (pure)\n"  # 2
        "func Validate() {}\n"                            # 3
        "    # SEM@deadbee: parse a config file\n"        # 4 (indented, hash)
        "x = 1\n"                                         # 5
    )

    def test_parse_returns_indexed_markers(self):
        got = sa.parse_markers(self.SRC)
        self.assertEqual(set(got), {2, 4})
        self.assertEqual(got[2]["sha"], "b14a829")
        self.assertEqual(got[2]["desc"], "validate an oauth token (pure)")
        self.assertEqual(got[4]["sha"], "deadbee")

    def test_find_marker_above_entity(self):
        lines = self.SRC.splitlines()
        m = sa.find_marker_above(lines, 4)   # entity 'func Validate' is on 1-based line 4
        self.assertIsNotNone(m)
        self.assertEqual(m["sha"], "b14a829")

    def test_find_marker_above_none_when_absent(self):
        lines = self.SRC.splitlines()
        self.assertIsNone(sa.find_marker_above(lines, 6))  # line above 'x = 1' is a marker? no — it's line 5 'x = 1'? 
```

Note: in `test_find_marker_above_none_when_absent`, entity 1-based line 6 is `x = 1`; the line above (1-based 5) is the indented `# SEM@deadbee` marker, so adjust the assertion below.

Replace the last test with:

```python
    def test_find_marker_above_none_when_not_a_marker(self):
        lines = self.SRC.splitlines()
        # entity on 1-based line 2 ('// SEM...') -> line above is blank line 1 -> no marker
        self.assertIsNone(sa.find_marker_above(lines, 2))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — `AttributeError: module 'sem_annotate' has no attribute 'parse_markers'`.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_markers(text):
    """Return {0-based line index: {'sha', 'desc'}} for every SEM marker line."""
    out = {}
    for i, line in enumerate(text.splitlines()):
        m = SEM_MARKER_RE.match(line)
        if m:
            out[i] = {"sha": m.group("sha"), "desc": m.group("desc")}
    return out


def find_marker_above(lines, start_line):
    """Return the SEM marker dict on the line directly above 1-based start_line, or None."""
    above_idx = start_line - 2  # line above the entity, 0-based
    if above_idx < 0 or above_idx >= len(lines):
        return None
    m = SEM_MARKER_RE.match(lines[above_idx])
    if not m:
        return None
    return {"sha": m.group("sha"), "desc": m.group("desc")}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): parse markers + find marker above entity"
```

---

### Task 3: Build and apply markers (insert or replace, indentation-matched)

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Consumes: `SEM_MARKER_RE`, `comment_prefix`.
- Produces: `build_marker(prefix: str, indent: str, sha: str, desc: str) -> str`; `apply_marker(lines: list[str], start_line: int, prefix: str, sha: str, desc: str) -> list[str]` (replaces an existing marker directly above the entity, else inserts one; indent copied from the entity line).

- [ ] **Step 1: Write the failing test**

```python
class TestApplyMarker(unittest.TestCase):
    def test_build_marker_format(self):
        self.assertEqual(
            sa.build_marker("//", "  ", "abc1234", "validate a token"),
            "  // SEM@abc1234: validate a token",
        )

    def test_insert_when_absent(self):
        lines = ["package p", "", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "abc1234", "compute a checksum")
        self.assertEqual(out[2], "// SEM@abc1234: compute a checksum")
        self.assertEqual(out[3], "func F() {}")
        self.assertEqual(len(out), 4)

    def test_replace_when_present(self):
        lines = ["package p", "// SEM@old1111: stale desc", "func F() {}"]
        out = sa.apply_marker(lines, 3, "//", "new2222", "fresh desc")
        self.assertEqual(out, ["package p", "// SEM@new2222: fresh desc", "func F() {}"])

    def test_indentation_matches_entity(self):
        lines = ["class C:", "    def m(self): pass"]
        out = sa.apply_marker(lines, 2, "#", "abc1234", "handle a request")
        self.assertEqual(out[1], "    # SEM@abc1234: handle a request")
        self.assertEqual(out[2], "    def m(self): pass")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — no attribute `build_marker`.

- [ ] **Step 3: Write minimal implementation**

```python
def build_marker(prefix, indent, sha, desc):
    return f"{indent}{prefix} SEM@{sha}: {desc}"


def apply_marker(lines, start_line, prefix, sha, desc):
    """Insert or replace the SEM marker directly above 1-based start_line.

    Indentation is copied from the entity definition line. Returns a NEW list.
    """
    lines = list(lines)
    idx = start_line - 1                       # entity line, 0-based
    entity_line = lines[idx] if 0 <= idx < len(lines) else ""
    indent = entity_line[: len(entity_line) - len(entity_line.lstrip())]
    marker = build_marker(prefix, indent, sha, desc)
    above = idx - 1
    if above >= 0 and SEM_MARKER_RE.match(lines[above]):
        lines[above] = marker
    else:
        lines.insert(idx, marker)
    return lines
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): build + apply markers (insert/replace, indent-matched)"
```

---

### Task 4: Classify entities (missing / stale / fresh) with short-SHA matching

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces: `classify(existing_sha: str | None, blame_commit: str, logic_changed: bool) -> str` returning `"missing" | "stale" | "fresh"`. SHA comparison is prefix-based (markers store short SHAs; blame returns full).

- [ ] **Step 1: Write the failing test**

```python
class TestClassify(unittest.TestCase):
    FULL = "b14a829fd98bc22eaf2939ee51854649b9620cb0"

    def test_missing_when_no_marker(self):
        self.assertEqual(sa.classify(None, self.FULL, False), "missing")

    def test_fresh_when_sha_prefix_matches_blame(self):
        self.assertEqual(sa.classify("b14a829", self.FULL, True), "fresh")

    def test_stale_when_blame_moved_and_logic_changed(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, True), "stale")

    def test_fresh_when_blame_moved_but_cosmetic_only(self):
        self.assertEqual(sa.classify("deadbee", self.FULL, False), "fresh")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — no attribute `classify`.

- [ ] **Step 3: Write minimal implementation**

```python
def classify(existing_sha, blame_commit, logic_changed):
    """missing (no marker) / fresh (sha current or change cosmetic) / stale (logic changed)."""
    if not existing_sha:
        return "missing"
    if blame_commit.startswith(existing_sha):
        return "fresh"
    return "stale" if logic_changed else "fresh"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): classify entities missing/stale/fresh w/ short-sha match"
```

---

### Task 5: sem CLI wrappers + `scan()` worklist builder

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces:
  - `run_sem(args: list[str], cwd: str | None) -> str` — runs `sem <args> --json`, returns stdout; raises `SemError` on failure.
  - `sem_entities(paths, cwd=None) -> list[dict]`, `sem_blame(file, cwd=None) -> list[dict]`, `logic_changed_entities(base_sha, file, cwd=None) -> set[str]` (entity names with a non-cosmetic change since `base_sha`, via `sem diff <sha>..HEAD --no-cosmetics -- <file>`).
  - `CODE_TYPES = {"function", "method", "class", "type"}`.
  - `scan(paths, cwd=None, rebuild=False) -> list[dict]` — worklist items `{"file","name","start_line","end_line","status","blame_sha","existing_desc"}` for entities classified `missing`/`stale` (or all code entities when `rebuild=True`).
- Consumes: `comment_prefix`, `find_marker_above`, `classify`, `sem_entities`, `sem_blame`, `logic_changed_entities`.

- [ ] **Step 1: Write the failing test** (pure logic tested via monkeypatched sem wrappers)

```python
import types

class TestScan(unittest.TestCase):
    def setUp(self):
        self.files = {}  # path -> source text

        def fake_read(path):
            return self.files[path]

        self._orig_read = sa._read_text
        sa._read_text = fake_read

    def tearDown(self):
        sa._read_text = self._orig_read

    def test_scan_flags_missing_and_stale_only(self):
        path = "auth/x.go"
        self.files[path] = (
            "package auth\n"
            "// SEM@aaaaaaa: validate a token\n"   # fresh: sha matches blame below
            "func Fresh() {}\n"
            "func Missing() {}\n"                   # no marker -> missing
        )
        entities = [
            {"name": "Fresh", "type": "function", "start_line": 3, "end_line": 3},
            {"name": "Missing", "type": "function", "start_line": 4, "end_line": 4},
        ]
        blame = [
            {"name": "Fresh", "lines": [3, 3], "commit": "aaaaaaa000111222333"},
            {"name": "Missing", "lines": [4, 4], "commit": "bbbbbbb000111222333"},
        ]
        sa.sem_entities = lambda paths, cwd=None: entities
        sa.sem_blame = lambda f, cwd=None: blame
        sa.logic_changed_entities = lambda base, f, cwd=None: set()

        work = sa.scan([path])
        names = {w["name"]: w["status"] for w in work}
        self.assertEqual(names, {"Missing": "missing"})
        self.assertEqual(work[0]["blame_sha"], "bbbbbbb000111222333")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — no attribute `scan` / `_read_text`.

- [ ] **Step 3: Write minimal implementation**

```python
import json
import subprocess

CODE_TYPES = {"function", "method", "class", "type"}


class SemError(RuntimeError):
    pass


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run_sem(args, cwd=None):
    cmd = ["sem"] + args + ["--json"]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SemError("'sem' CLI not found on PATH")
    except subprocess.CalledProcessError as e:
        raise SemError(f"sem {' '.join(args)} failed: {e.stderr.strip()}")
    return r.stdout


def sem_entities(paths, cwd=None):
    out = run_sem(["entities", *paths], cwd=cwd)
    return json.loads(out)


def sem_blame(file, cwd=None):
    return json.loads(run_sem(["blame", file], cwd=cwd))


def logic_changed_entities(base_sha, file, cwd=None):
    """Names of entities in `file` with a non-cosmetic change since base_sha."""
    out = run_sem(["diff", f"{base_sha}..HEAD", "--no-cosmetics", "--", file], cwd=cwd)
    data = json.loads(out)
    names = set()
    for ch in data.get("changes", []):
        n = ch.get("name") or ch.get("entity")
        if n:
            names.add(n)
    return names


def scan(paths, cwd=None, rebuild=False):
    entities = [e for e in sem_entities(paths, cwd=cwd) if e.get("type") in CODE_TYPES]
    by_file = {}
    for e in entities:
        f = e.get("file") or (paths[0] if len(paths) == 1 else None)
        if f:
            by_file.setdefault(f, []).append(e)

    work = []
    for f, ents in by_file.items():
        text = _read_text(f if cwd is None else os.path.join(cwd, f))
        lines = text.splitlines()
        blame = {b["name"]: b for b in sem_blame(f, cwd=cwd)}
        for e in ents:
            marker = find_marker_above(lines, e["start_line"])
            existing_sha = marker["sha"] if marker else None
            blame_sha = blame.get(e["name"], {}).get("commit", "")
            if rebuild:
                status = "missing"
            else:
                logic = False
                if existing_sha and blame_sha and not blame_sha.startswith(existing_sha):
                    logic = e["name"] in logic_changed_entities(existing_sha, f, cwd=cwd)
                status = classify(existing_sha, blame_sha, logic)
            if status in ("missing", "stale"):
                work.append({
                    "file": f, "name": e["name"],
                    "start_line": e["start_line"], "end_line": e["end_line"],
                    "status": status, "blame_sha": blame_sha,
                    "existing_desc": marker["desc"] if marker else None,
                })
    return work
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS.

- [ ] **Step 5: Integration check against tmi (real sem CLI)**

Run:
```bash
cd /Users/efitz/Projects/skills && python3 -c "
import sys; sys.dont_write_bytecode=True
sys.path.insert(0,'dev/scripts'); import sem_annotate as sa
w = sa.scan(['auth/provider.go'], cwd='/Users/efitz/Projects/tmi')
print(len(w), 'entities need descriptions')
for x in w[:3]: print(x['status'], x['name'], x['blame_sha'][:7])
"
```
Expected: prints a count > 0 and several `missing` entities with 7-char SHAs (the file has no markers yet).

- [ ] **Step 6: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): sem CLI wrappers + scan() worklist builder"
```

---

### Task 6: `write()` + CLI `main()` (scan / write / --update / --rebuild)

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces:
  - `write(updates, cwd=None) -> int` — `updates` is a list of `{"file","start_line","sha","desc"}`; applies markers grouped per file (bottom-up so earlier insertions don't shift later line numbers), writes files, returns count.
  - `parse_args(argv) -> argparse.Namespace` and `main(argv=None) -> int` with subcommands: `scan PATHS... [--rebuild] [-C DIR]` (prints worklist JSON to stdout) and `write [-C DIR]` (reads updates JSON from stdin, applies, prints count). `--update FILE...` is sugar for `scan FILE...` over specific files.
- Consumes: `apply_marker`, `comment_prefix`, `scan`.

- [ ] **Step 1: Write the failing test**

```python
import io, json, tempfile, os

class TestWrite(unittest.TestCase):
    def test_write_applies_bottom_up(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\nfunc B() {}\n")
            n = sa.write([
                {"file": p, "start_line": 2, "sha": "aaa1111", "desc": "build A"},
                {"file": p, "start_line": 3, "sha": "bbb2222", "desc": "build B"},
            ])
            self.assertEqual(n, 1)  # one file written
            out = open(p).read().splitlines()
            self.assertEqual(out[1], "// SEM@aaa1111: build A")
            self.assertEqual(out[2], "func A() {}")
            self.assertEqual(out[3], "// SEM@bbb2222: build B")
            self.assertEqual(out[4], "func B() {}")


class TestArgs(unittest.TestCase):
    def test_scan_subcommand(self):
        ns = sa.parse_args(["scan", "auth/", "-C", "/repo"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["auth/"])
        self.assertEqual(ns.cwd, "/repo")
        self.assertFalse(ns.rebuild)

    def test_update_is_scan_over_files(self):
        ns = sa.parse_args(["--update", "a.go", "b.go"])
        self.assertEqual(ns.cmd, "scan")
        self.assertEqual(ns.paths, ["a.go", "b.go"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: FAIL — no attribute `write` / `parse_args`.

- [ ] **Step 3: Write minimal implementation**

```python
import argparse
import sys


def write(updates, cwd=None):
    by_file = {}
    for u in updates:
        by_file.setdefault(u["file"], []).append(u)
    written = 0
    for f, ups in by_file.items():
        abspath = f if cwd is None else os.path.join(cwd, f)
        prefix = comment_prefix(f)
        if prefix is None:
            continue
        lines = _read_text(abspath).splitlines()
        # Apply bottom-up so insertions above don't shift later start_lines.
        for u in sorted(ups, key=lambda x: x["start_line"], reverse=True):
            lines = apply_marker(lines, u["start_line"], prefix, u["sha"], u["desc"])
        with open(abspath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written += 1
    return written


def parse_args(argv):
    p = argparse.ArgumentParser(prog="sem_annotate")
    p.add_argument("--update", nargs="+", metavar="FILE",
                   help="scan only these files (entity-granular update)")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scan")
    s.add_argument("paths", nargs="*", default=["."])
    s.add_argument("--rebuild", action="store_true")
    s.add_argument("-C", "--cwd", default=None)
    w = sub.add_parser("write")
    w.add_argument("-C", "--cwd", default=None)
    ns = p.parse_args(argv)
    if ns.update:
        ns.cmd = "scan"
        ns.paths = ns.update
        ns.rebuild = getattr(ns, "rebuild", False)
        ns.cwd = getattr(ns, "cwd", None)
    return ns


def main(argv=None):
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    if ns.cmd == "scan":
        print(json.dumps(scan(ns.paths, cwd=ns.cwd, rebuild=ns.rebuild), indent=2))
        return 0
    if ns.cmd == "write":
        updates = json.load(sys.stdin)
        n = write(updates, cwd=ns.cwd)
        print(json.dumps({"files_written": n}))
        return 0
    print("usage: sem_annotate [scan|write|--update FILES]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS (all tests across tasks 1–6).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): write() + CLI main (scan/write/--update/--rebuild)"
```

---

### Task 7: Description-writer subagent prompt

**Files:**
- Create: `dev/agents/sem-describe.md`

This is a documentation deliverable (a subagent prompt); its "test" is a dry-run review in Task 9, not a unit test.

- [ ] **Step 1: Write the agent prompt**

Create `dev/agents/sem-describe.md` with this content:

```markdown
---
name: SEM Describer
description: Internal worker for the sem-annotate skill. Given a batch of code entities (file, name, line range), reads each entity's source and writes a one-line intent description following the SEM description content standard. Returns a JSON array of {file, name, start_line, sha, desc}.
tools: Read, Bash
model: sonnet
---

# SEM Describer Agent

You write one-line intent descriptions for code entities. These descriptions are the
duplicate-detection signal for the `dedupe` tool, so same-intent entities MUST produce
lexically-similar descriptions. Follow the standard exactly.

## Input

You receive a JSON array of work items on the prompt: each item is
`{"file","name","start_line","end_line","blame_sha","status","existing_desc"}`.
You also receive `REPO_DIR` (absolute path to the repository root).

## Steps

1. For each item, read the entity's source. Prefer:
   `sem context <name> --json -C <REPO_DIR>` for the file (or `Read` the file at the line
   range `start_line..end_line`). Read enough to understand intent, not mechanism.
2. Write a description following the content standard below.
3. Emit a JSON array of `{"file","name","start_line","sha","desc"}` where `sha` is the
   item's `blame_sha` (use the full value provided) and `desc` is your description.

## Description content standard (follow in priority order)

1. **Describe intent (the contract), never mechanism.** What the caller gets — not the
   implementation steps. "validate a JWT and return its claims" — not "loop over header,
   split on '.', base64-decode".
2. **Lead with a canonical verb.** Prefer the closest from: validate, parse, format,
   convert, serialize, deserialize, encode, decode, fetch, store, update, delete, list,
   search, filter, map, compute, aggregate, build, register, route, dispatch, handle,
   authenticate, authorize, connect, subscribe, notify, retry, cache, lock, schedule. Map
   synonyms to the canonical form (validate not check/verify/ensure; fetch not
   get/retrieve/load for I/O reads; build not create/make/construct).
3. **Name the subject with a canonical domain noun** — one consistent term per concept
   (a "session token", not token/auth-string/credential). Reuse the project's vocabulary.
4. **Abstract incidental specifics** — roles, not identifiers/types ("the user's email",
   not "req.body.email").
5. **One line, ≤ ~12 words, do NOT restate the entity name.**
6. **Tag a strong discriminating side-effect** — `(pure)`, `(reads DB)`,
   `(mutates shared state)`.

Examples:
- `validate a JWT and return its claims; reject if expired (pure)`
- `fetch open issues for a repo from the GitHub API`
- `convert a domain User to its API DTO`

## Output

Respond with ONLY the JSON array. No prose, no markdown fences.
```

- [ ] **Step 2: Commit**

```bash
git add dev/agents/sem-describe.md
git commit -m "feat(sem-annotate): SEM describer subagent prompt"
```

---

### Task 8: Skill orchestration (SKILL.md)

**Files:**
- Create: `dev/skills/sem-annotate/SKILL.md`

Documentation deliverable; verified by the dry-run in Task 9.

- [ ] **Step 1: Write the skill**

Create `dev/skills/sem-annotate/SKILL.md`:

````markdown
---
name: sem-annotate
version: 1.0.0
description: Generate and refresh SEM@<sha> intent markers on code entities using the sem CLI. Use when the user asks to annotate code with SEM markers, add or refresh entity descriptions, or prepare a codebase for dedupe. Supports Go, TypeScript/JavaScript, and Python. Modes: full-scope, --update <files>, --rebuild.
---

# sem-annotate

Generate and refresh `// SEM@<sha>: <intent>` markers on code entities. Markers are a
durable, format-independent semantic layer consumed by the `dedupe` skill and useful for
human and `sem` comprehension. Drift is detected via `sem diff --no-cosmetics`, so
reformatting (gofmt/black/prettier) never marks a marker stale.

Bundled tool: `${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py`.
Bundled agent: `${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md`.

## Usage

```
/sem-annotate [path ...]          # annotate all code entities under the path(s)
/sem-annotate --update <files>    # refresh markers only for these files (entity-granular)
/sem-annotate --rebuild [path]    # regenerate ALL markers, ignoring existing ones
```

If the target repository is not the current directory, pass it through to the tool via
`-C <repo-dir>` (the tool forwards it to the `sem` CLI).

## Process

### 1. Preflight
- Confirm the `sem` CLI is available: `sem --version`. If missing, stop and tell the user to
  install it (`brew install sem` / see sem docs).
- Determine the repo dir (default: cwd) and the path scope from arguments.

### 2. Scan for work
Run the tool's `scan` (or `--update`) and capture the JSON worklist:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py scan <paths> -C <repo-dir> > /tmp/sem-work.json
# or, for specific files:
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py --update <files> -C <repo-dir> > /tmp/sem-work.json
# add --rebuild to regenerate everything
```

Read the count. If empty, report "All markers fresh — nothing to do." and stop.

### 3. Generate descriptions (parallel subagents)
Split the worklist into batches (~20 entities each). For each batch, dispatch a
`general-purpose` subagent that follows `${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md`,
passing the batch JSON and `REPO_DIR=<repo-dir>`. Each subagent returns a JSON array of
`{file, name, start_line, sha, desc}`. Collect and concatenate all arrays into one JSON
array `/tmp/sem-updates.json`.

Dispatch batches in parallel (one message, multiple Task calls). Subagents return only the
JSON array — do not read large transcripts back.

### 4. Write markers
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py write -C <repo-dir> < /tmp/sem-updates.json
```

### 5. Review
Show the user `git diff` (markers only) for a quick review. Do not commit automatically
unless asked — `sem-auto` owns the commit-time workflow.

### 6. Offer the CLAUDE.md convention note (once)
If the project's `CLAUDE.md` does not already mention SEM markers, offer to add a short
note (this is `sem-auto`'s primary job; offer to run `/sem-auto` if the user wants the
git hook too).

## Notes
- The tool is the source of truth for all deterministic work (entity discovery, drift
  classification, marker writing). The only LLM step is description generation.
- Entity-granular: `--update` and the default scan only rewrite markers for entities that
  are missing or whose body logically changed; untouched entities keep their markers.
````

- [ ] **Step 2: Commit**

```bash
git add dev/skills/sem-annotate/SKILL.md
git commit -m "feat(sem-annotate): skill orchestration (SKILL.md)"
```

---

### Task 9: Register the skill + end-to-end verification against tmi

**Files:**
- Modify: `dev/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Update the dev plugin description**

In `dev/.claude-plugin/plugin.json`, replace the `description` value with:

```
"Developer toolkit: annotate code with durable SEM@<sha> intent markers (sem-annotate), and find/analyze duplicate or overlapping functionality (dedupe). Uses the sem CLI for entity-level semantic intelligence. Supports Go, TypeScript/JavaScript, and Python."
```

- [ ] **Step 2: Update the marketplace entry**

In `.claude-plugin/marketplace.json`, set the `dev` plugin's `description` to the same string as Step 1.

- [ ] **Step 3: Run the full unit suite**

Run: `cd /Users/efitz/Projects/skills && python3 -m unittest tests.test_sem_annotate -v`
Expected: PASS (all tests, tasks 1–6).

- [ ] **Step 4: End-to-end dry run against a tmi copy**

Work on a throwaway copy so we never mutate tmi during verification:

```bash
rm -rf /tmp/tmi-annotate && cp -R /Users/efitz/Projects/tmi/auth /tmp/tmi-annotate-auth-src
mkdir -p /tmp/tmi-annotate && cp -R /Users/efitz/Projects/tmi /tmp/tmi-annotate/repo 2>/dev/null || true
# Scan one real file:
cd /Users/efitz/Projects/skills
python3 dev/scripts/sem_annotate.py scan auth/provider.go -C /Users/efitz/Projects/tmi | python3 -c "import sys,json;d=json.load(sys.stdin);print('work items:',len(d))"
```
Expected: prints `work items: N` with N > 0.

Then verify the write path on a COPY (not tmi itself):
```bash
cp /Users/efitz/Projects/tmi/auth/provider.go /tmp/provider.go
cd /Users/efitz/Projects/skills
# Hand-build a tiny updates file from the first scanned entity and apply it to the copy dir:
python3 -c "
import sys,json; sys.dont_write_bytecode=True; sys.path.insert(0,'dev/scripts'); import sem_annotate as sa
w = sa.scan(['auth/provider.go'], cwd='/Users/efitz/Projects/tmi')[:1]
u=[{'file':'provider.go','start_line':x['start_line'],'sha':x['blame_sha'][:7],'desc':'TEST marker'} for x in w]
print(sa.write(u, cwd='/tmp'))
"
grep -n "SEM@" /tmp/provider.go | head
```
Expected: one `// SEM@<sha>: TEST marker` line appears immediately above the first entity in `/tmp/provider.go`; the file still compiles-shaped (marker is a comment).

- [ ] **Step 5: Commit**

```bash
git add dev/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "feat(sem-annotate): register skill in dev plugin + marketplace"
```

---

## Self-Review

**Spec coverage:**
- Marker format `// SEM@<sha>:` + per-language syntax → Tasks 1, 3 (Global Constraints).
- Drift detection (blame fast-path + `--no-cosmetics` slow-path) → Tasks 4, 5.
- Entity-granular updates → Task 5 (`scan` per-entity classify) + Task 6 (`--update`).
- Modes default/`--update`/`--rebuild` → Task 6.
- Description content standard → Task 7 (agent) + restated in Task 8.
- Parallel description subagents → Task 8.
- Reviewable diff, no auto-commit → Task 8 step 5.
- CLAUDE.md note offer (sem-auto is primary owner) → Task 8 step 6.
- Plugin registration → Task 9.

**Placeholder scan:** No TBD/TODO; all code and tests are concrete. "TEST marker" in Task 9 is intentional throwaway verification data on a copy, not a placeholder in shipped code.

**Type consistency:** `scan()` emits items with keys `file/name/start_line/end_line/status/blame_sha/existing_desc`; the describer consumes these and emits `file/name/start_line/sha/desc`; `write()` consumes `file/start_line/sha/desc`. Consistent across Tasks 5, 7, 8, 6. `comment_prefix` returns `//`/`#`/`None` everywhere. SHA matching is prefix-based in both `classify` (Task 4) and `scan` (Task 5).

## Deferred to later plans
- `dedupe` rebuild (separate plan) — will consume these markers and use `sem graph` for the dependency graph in one call.
- `sem-auto` (separate plan) — installs the post-commit follow-up-commit hook calling `sem_annotate.py --update`, plus the CLAUDE.md note.
