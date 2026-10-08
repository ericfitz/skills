# sem-annotate Scan Robustness + SHA Anchoring Implementation Plan (#11/#12/#13)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sem_annotate.py scan`/`classify` robust to dirty trees and bad hashes, stamp the authoritative SHA in the tool (not the LLM), and anchor markers to the entity's last logical change so freshly-written markers classify `fresh`.

**Architecture:** All code changes are in `dev/scripts/sem_annotate.py`; doc/prompt changes in `dev/agents/sem-describe.md` and `dev/skills/sem-annotate/SKILL.md`. New helpers: `_is_uncommitted`, `InvalidRevError`, `sem_log_entity`, `entity_logic_sha`, `head_sha`. `scan` and `write` are rewritten; the worklist anchor field is renamed `blame_sha → anchor_sha`.

**Tech Stack:** Python 3 stdlib (`re`, `json`, `subprocess`, `os`), `unittest`. The `sem` CLI (0.13.0) is mocked in tests.

## Global Constraints

- Status vocabulary: `missing`, `fresh`, `stale`, `uncommitted`, `invalid-sha`. The `scan` worklist surfaces ONLY `missing`, `stale`, `invalid-sha`. `fresh`/`uncommitted` are excluded.
- The SEM Describer agent must NOT emit a SHA; the tool stamps the authoritative `anchor_sha`.
- Marker anchor = newest `sem log` entry whose `change_type` ∈ {`"added"`, `"modified (logic)"`}; fallback to `sem blame` commit, then `""`.
- No new dependencies. Full suite: `python3 -m unittest discover -s tests -t . -q` must stay green (currently 129 tests). Module import in tests: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))`.
- Known cost (acceptable): `scan` now calls `sem log` once per entity. Correctness over speed; do not micro-optimize in this plan.

---

### Task 1: `classify` robustness + `_is_uncommitted`

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`classify`, add `_is_uncommitted`, ensure `re` imported)
- Modify: `tests/test_sem_annotate.py` (add uncommitted tests)

**Interfaces:**
- Produces: `_is_uncommitted(sha) -> bool` (True for None/""/all-zeros); `classify(existing_sha, anchor_sha, logic_changed) -> str` returning `missing|uncommitted|fresh|stale`.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sem_annotate.py` (the existing `TestClassify` class uses `self.FULL`; add a new class):

```python
class TestClassifyRobust(unittest.TestCase):
    def test_uncommitted_none(self):
        self.assertEqual(sa.classify("b14a829", None, False), "uncommitted")

    def test_uncommitted_empty(self):
        self.assertEqual(sa.classify("b14a829", "", False), "uncommitted")

    def test_uncommitted_all_zeros(self):
        self.assertEqual(sa.classify("b14a829", "0000000000000000000000000000000000000000", False), "uncommitted")

    def test_missing_takes_precedence_over_uncommitted(self):
        self.assertEqual(sa.classify(None, None, False), "missing")

    def test_is_uncommitted_helper(self):
        self.assertTrue(sa._is_uncommitted(None))
        self.assertTrue(sa._is_uncommitted(""))
        self.assertTrue(sa._is_uncommitted("0000000"))
        self.assertFalse(sa._is_uncommitted("b14a829"))
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestClassifyRobust -v`
Expected: FAIL (`AttributeError: ... '_is_uncommitted'` / `NoneType.startswith`).

- [ ] **Step 3: Implement**

In `dev/scripts/sem_annotate.py`, confirm `import re` is present (it is). Add near `classify`:

```python
_ZERO_SHA_RE = re.compile(r"0{7,40}")


def _is_uncommitted(sha):
    """True for a missing/blank/all-zeros blame sha (git's 'Not Committed Yet')."""
    return not sha or _ZERO_SHA_RE.fullmatch(sha) is not None
```

Replace `classify` with:

```python
def classify(existing_sha, anchor_sha, logic_changed):
    """Classify entity status.

    missing      no marker
    uncommitted  marker present but anchor is uncommitted/blank (dirty tree)
    fresh        anchor sha current, or change cosmetic
    stale        anchor moved and a logical change occurred
    """
    if not existing_sha:
        return "missing"
    if _is_uncommitted(anchor_sha):
        return "uncommitted"
    if anchor_sha.startswith(existing_sha):
        return "fresh"
    return "stale" if logic_changed else "fresh"
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_sem_annotate.TestClassifyRobust tests.test_sem_annotate.TestClassify -v`
Expected: PASS (both classes; the original `TestClassify` still passes since it passes string blames).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "fix(sem-annotate): classify handles uncommitted/blank anchor (#11)"
```

---

### Task 2: `InvalidRevError` from `run_sem`

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`run_sem`, add `InvalidRevError`, `_is_revspec_not_found`)
- Modify: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces: `class InvalidRevError(SemError)`; `run_sem` raises `InvalidRevError` when a sem command fails with a "revspec not found" stderr.

- [ ] **Step 1: Write failing tests**

```python
class TestInvalidRevError(unittest.TestCase):
    def _patch(self, stderr):
        import subprocess as sp
        def fake_run(cmd, cwd=None, capture_output=True, text=True, check=True):
            raise sp.CalledProcessError(1, cmd, stderr=stderr)
        self._orig = sa.subprocess.run
        sa.subprocess.run = fake_run

    def tearDown(self):
        if hasattr(self, "_orig"):
            sa.subprocess.run = self._orig

    def test_revspec_not_found_raises_invalidrev(self):
        self._patch("Error: git error: revspec 'abc123' not found; class=Reference (4); code=NotFound (-3)")
        with self.assertRaises(sa.InvalidRevError):
            sa.run_sem(["diff", "abc123..HEAD", "--no-cosmetics", "--", "x.ts"])

    def test_invalidrev_is_semerror(self):
        self.assertTrue(issubclass(sa.InvalidRevError, sa.SemError))

    def test_other_failure_is_plain_semerror(self):
        self._patch("some unrelated failure")
        with self.assertRaises(sa.SemError):
            sa.run_sem(["entities", "."])
        # and NOT InvalidRevError
        with self.assertRaises(sa.SemError):
            try:
                sa.run_sem(["entities", "."])
            except sa.InvalidRevError:
                self.fail("should be plain SemError, not InvalidRevError")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestInvalidRevError -v`
Expected: FAIL (`AttributeError: ... 'InvalidRevError'`).

- [ ] **Step 3: Implement**

In `dev/scripts/sem_annotate.py`, add after `class SemError`:

```python
class InvalidRevError(SemError):
    """A sem command failed because a commit/revspec does not exist."""


def _is_revspec_not_found(stderr):
    s = (stderr or "").lower()
    return "not found" in s and ("revspec" in s or "reference" in s)
```

Update the `except subprocess.CalledProcessError` branch of `run_sem`:

```python
    except subprocess.CalledProcessError as e:
        msg = f"sem {' '.join(args)} failed: {e.stderr.strip()}"
        if _is_revspec_not_found(e.stderr):
            raise InvalidRevError(msg)
        raise SemError(msg)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_sem_annotate.TestInvalidRevError -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "fix(sem-annotate): run_sem raises InvalidRevError on bad revspec (#12)"
```

---

### Task 3: `sem_log_entity` + `entity_logic_sha` + `head_sha`

**Files:**
- Modify: `dev/scripts/sem_annotate.py`
- Modify: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces:
  - `sem_log_entity(name, file, cwd=None) -> dict` (parsed `sem log --json`; `{"changes": []}` on failure)
  - `entity_logic_sha(name, file, cwd=None, fallback_sha="") -> str` (newest added/logic commit sha; else `fallback_sha`)
  - `head_sha(cwd=None) -> str` (`git rev-parse HEAD`; `""` on failure)

- [ ] **Step 1: Write failing tests**

```python
class TestEntityLogicSha(unittest.TestCase):
    def setUp(self):
        self._orig_log = sa.sem_log_entity

    def tearDown(self):
        sa.sem_log_entity = self._orig_log

    def test_picks_newest_logic_ignoring_later_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}},
            {"change_type": "modified (logic)", "commit": {"sha": "bbb222"}},
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}},
        ]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "bbb222")

    def test_added_only(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "added", "commit": {"sha": "aaa111"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "aaa111")

    def test_fallback_when_only_cosmetic(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": [
            {"change_type": "modified (cosmetic)", "commit": {"sha": "ccc333"}}]}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")

    def test_fallback_when_empty(self):
        sa.sem_log_entity = lambda n, f, cwd=None: {"changes": []}
        self.assertEqual(sa.entity_logic_sha("E", "f.py", fallback_sha="zzz999"), "zzz999")
        self.assertEqual(sa.entity_logic_sha("E", "f.py"), "")

    def test_sem_log_entity_returns_empty_on_semerror(self):
        def boom(args, cwd=None):
            raise sa.SemError("nope")
        orig = sa.run_sem
        sa.run_sem = boom
        try:
            self.assertEqual(sa.sem_log_entity("E", "f.py"), {"changes": []})
        finally:
            sa.run_sem = orig
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestEntityLogicSha -v`
Expected: FAIL (`AttributeError: ... 'sem_log_entity'`).

- [ ] **Step 3: Implement**

Add to `dev/scripts/sem_annotate.py` (near the other sem wrappers):

```python
_LOGIC_CHANGE_TYPES = ("added", "modified (logic)")


def sem_log_entity(name, file, cwd=None):
    """Parsed `sem log --json <name> --file <file>`; {'changes': []} on any failure."""
    try:
        out = run_sem(["log", name, "--file", file], cwd=cwd)
    except SemError:
        return {"changes": []}
    try:
        data = json.loads(out)
    except (ValueError, json.JSONDecodeError):
        return {"changes": []}
    if not isinstance(data, dict):
        return {"changes": []}
    return data


def entity_logic_sha(name, file, cwd=None, fallback_sha=""):
    """SHA of the entity's newest added/logic change (cosmetic-aware anchor).

    `sem log` changes are oldest-first, so the last matching entry is newest.
    Falls back to fallback_sha (e.g. the entity's sem blame commit) when there
    is no added/logic entry.
    """
    sha = ""
    for ch in sem_log_entity(name, file, cwd=cwd).get("changes", []):
        if ch.get("change_type") in _LOGIC_CHANGE_TYPES:
            s = (ch.get("commit") or {}).get("sha")
            if s:
                sha = s
    return sha or (fallback_sha or "")


def head_sha(cwd=None):
    """git rev-parse HEAD, or '' if unavailable."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except Exception:
        return ""
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_sem_annotate.TestEntityLogicSha -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "feat(sem-annotate): entity_logic_sha anchors markers to last logic change (#13)"
```

---

### Task 4: Rewrite `scan` to use `anchor_sha`, `invalid-sha`, `uncommitted`

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`scan`)
- Modify: `tests/test_sem_annotate.py` (update existing scan tests; add invalid-sha + #13 regression)

**Interfaces:**
- Consumes: `entity_logic_sha`, `_is_uncommitted`, `InvalidRevError`, `classify`, `logic_changed_entities`, `sem_blame`, `sem_entities`, `find_marker_above`.
- Produces: `scan(...)` worklist items shaped `{file, name, start_line, end_line, status, anchor_sha, existing_desc}` (plus `bad_sha` when `status == "invalid-sha"`). The worklist anchor key is `anchor_sha` (NOT `blame_sha`).

- [ ] **Step 1: Update existing scan tests + write new failing tests**

In `tests/test_sem_annotate.py`:

(a) In `TestScan.test_scan_flags_missing_and_stale_only`, the existing tail asserts `work[0]["blame_sha"]`. Change that assertion to `anchor_sha`, and monkeypatch `entity_logic_sha` so scan does not call real `sem log`. Add to that test's setup of mocks:
```python
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": \
            {"Fresh": "aaaaaaa000111222333", "Missing": "bbbbbbb000111222333"}.get(name, "")
```
and change the final assertion:
```python
        self.assertEqual(work[0]["anchor_sha"], "bbbbbbb000111222333")
```
Also restore `sa.entity_logic_sha` in that class's `tearDown` (capture the original in `setUp`).

(b) In `TestScanScope` (added for #8), add `sa.entity_logic_sha` to the saved/restored originals and stub it so scan doesn't hit real `sem log`:
```python
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "ccc" if f.startswith("src/") else "ddd"
```
(Both `A` and `B` have no marker → `missing` regardless of anchor, so the exclude assertions still hold.)

(c) Add new tests:
```python
class TestScanInvalidSha(unittest.TestCase):
    def setUp(self):
        self.files = {"src/a.ts": "// SEM@deadbee: old\nfunction A() {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.entity_logic_sha, sa.logic_changed_entities)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "A", "type": "function", "file": "src/a.ts", "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "A", "commit": "ffff999"}]
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "ffff999"
        def boom(base, f, cwd=None):
            raise sa.InvalidRevError("revspec not found")
        sa.logic_changed_entities = boom

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.entity_logic_sha, sa.logic_changed_entities) = self._orig

    def test_bad_hash_reported_not_crashed(self):
        work = sa.scan(["src/a.ts"])
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["status"], "invalid-sha")
        self.assertEqual(work[0]["bad_sha"], "deadbee")
        self.assertEqual(work[0]["name"], "A")


class TestScanFreshAfterWrite(unittest.TestCase):
    """#13 regression: marker anchored to the entity's last logic change is fresh."""
    def setUp(self):
        # decl-line blame is commit A, but body last changed in commit B; marker carries B.
        self.files = {"src/g.ts": "// SEM@bbbbbbb: guard\nclass G {}\n"}
        self._orig = (sa._read_text, sa.sem_entities, sa.sem_blame,
                      sa.entity_logic_sha, sa.logic_changed_entities)
        sa._read_text = lambda p: self.files[p]
        sa.sem_entities = lambda paths, cwd=None: [
            {"name": "G", "type": "class", "file": "src/g.ts", "start_line": 2, "end_line": 2}]
        sa.sem_blame = lambda f, cwd=None: [{"name": "G", "commit": "aaaaaaa_declline"}]
        sa.entity_logic_sha = lambda name, f, cwd=None, fallback_sha="": "bbbbbbb000111"  # commit B
        # Must NOT be consulted: anchor already prefix-matches the marker, so classify
        # returns fresh without a logic diff. Make it explode to prove that.
        def must_not_call(base, f, cwd=None):
            raise AssertionError("logic_changed_entities should not be called when anchor matches marker")
        sa.logic_changed_entities = must_not_call

    def tearDown(self):
        (sa._read_text, sa.sem_entities, sa.sem_blame,
         sa.entity_logic_sha, sa.logic_changed_entities) = self._orig

    def test_marker_matching_anchor_is_fresh(self):
        # anchor 'bbbbbbb000111' startswith marker 'bbbbbbb' -> fresh, logic check skipped
        work = sa.scan(["src/g.ts"])
        names = {w["name"]: w["status"] for w in work}
        self.assertNotIn("G", names)  # fresh -> not surfaced
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestScanInvalidSha tests.test_sem_annotate.TestScanFreshAfterWrite -v`
Expected: FAIL (scan still uses `blame_sha`/old logic; no `invalid-sha`).

- [ ] **Step 3: Rewrite `scan`'s per-entity loop**

Replace the `work = []` ... `return work` block of `scan` with:

```python
    work = []
    for f, ents in by_file.items():
        read_path = f if cwd is None else os.path.join(cwd, f)
        text = _read_text(read_path)
        lines = text.splitlines()
        blame_by_name = {b["name"]: (b.get("commit") or "")
                         for b in sem_blame(f, cwd=cwd)}
        for e in ents:
            marker = find_marker_above(lines, e["start_line"])
            existing_sha = marker["sha"] if marker else None
            anchor_sha = entity_logic_sha(
                e["name"], f, cwd=cwd,
                fallback_sha=blame_by_name.get(e["name"], "")) or ""
            existing_desc = marker["desc"] if marker else None
            if rebuild:
                status = "missing"
            else:
                logic = False
                if existing_sha and not _is_uncommitted(anchor_sha) \
                        and not anchor_sha.startswith(existing_sha):
                    try:
                        logic = e["name"] in logic_changed_entities(existing_sha, f, cwd=cwd)
                    except InvalidRevError:
                        work.append({
                            "file": f, "name": e["name"],
                            "start_line": e["start_line"], "end_line": e["end_line"],
                            "status": "invalid-sha", "anchor_sha": anchor_sha,
                            "existing_desc": existing_desc, "bad_sha": existing_sha,
                        })
                        continue
                status = classify(existing_sha, anchor_sha, logic)
            if status in ("missing", "stale"):
                work.append({
                    "file": f, "name": e["name"],
                    "start_line": e["start_line"], "end_line": e["end_line"],
                    "status": status, "anchor_sha": anchor_sha,
                    "existing_desc": existing_desc,
                })
    return work
```

- [ ] **Step 4: Run new tests + full suite**

Run: `python3 -m unittest tests.test_sem_annotate.TestScanInvalidSha tests.test_sem_annotate.TestScanFreshAfterWrite tests.test_sem_annotate.TestScan tests.test_sem_annotate.TestScanScope -v`
Expected: PASS.
Run: `python3 -m unittest discover -s tests -t . -q`
Expected: still green except the `write` tests (fixed in Task 5). If only `TestWrite`/write-subcommand tests fail, that is expected at this point.

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "fix(sem-annotate): scan uses entity anchor, reports invalid-sha, no crash on dirty tree (#11/#12/#13)"
```

---

### Task 5: Rewrite `write` to stamp the authoritative SHA + `--worklist` CLI

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`write`, `parse_args`, `main`)
- Modify: `tests/test_sem_annotate.py` (rewrite write tests)

**Interfaces:**
- Consumes: `head_sha`, `comment_prefix`, `apply_marker`, `_read_text`.
- Produces: `write(descriptions, worklist, cwd=None) -> {"files_written", "markers", "skipped"}`. Descriptions are `{file, name, start_line, desc}`; the SHA comes from the worklist's `anchor_sha` keyed by `(file, name, start_line)` (or `head_sha` when blank). CLI: `write --worklist <path> -C <repo> < descriptions.json`.

- [ ] **Step 1: Rewrite the write tests (failing)**

Replace `TestWrite.test_write_applies_bottom_up` and the write-subcommand test with:

```python
class TestWrite(unittest.TestCase):
    def test_write_stamps_worklist_sha_and_desc(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\nfunc B() {}\n")
            worklist = [
                {"file": p, "name": "A", "start_line": 2, "anchor_sha": "aaa1111"},
                {"file": p, "name": "B", "start_line": 3, "anchor_sha": "bbb2222"},
            ]
            descriptions = [
                {"file": p, "name": "A", "start_line": 2, "desc": "build A"},
                {"file": p, "name": "B", "start_line": 3, "desc": "build B"},
            ]
            res = sa.write(descriptions, worklist)
            self.assertEqual(res["files_written"], 1)
            self.assertEqual(res["markers"], 2)
            self.assertEqual(res["skipped"], 0)
            out = open(p).read().splitlines()
            self.assertEqual(out[1], "// SEM@aaa1111: build A")
            self.assertEqual(out[3], "// SEM@bbb2222: build B")

    def test_write_skips_unmatched_description(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\n")
            res = sa.write(
                [{"file": p, "name": "A", "start_line": 2, "desc": "x"},
                 {"file": p, "name": "Ghost", "start_line": 99, "desc": "y"}],
                [{"file": p, "name": "A", "start_line": 2, "anchor_sha": "aaa1111"}])
            self.assertEqual(res["skipped"], 1)
            self.assertEqual(res["markers"], 1)

    def test_write_blank_anchor_falls_back_to_head(self):
        orig = sa.head_sha
        sa.head_sha = lambda cwd=None: "headfff"
        try:
            with tempfile.TemporaryDirectory() as d:
                p = os.path.join(d, "x.go")
                with open(p, "w") as f:
                    f.write("package p\nfunc A() {}\n")
                sa.write([{"file": p, "name": "A", "start_line": 2, "desc": "x"}],
                         [{"file": p, "name": "A", "start_line": 2, "anchor_sha": ""}])
                self.assertEqual(open(p).read().splitlines()[1], "// SEM@headfff: x")
        finally:
            sa.head_sha = orig
```

Also update `TestCLI.test_write_subcommand_with_cwd` (if present) to the new flow:

```python
    def test_write_subcommand_with_worklist(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.go")
            with open(p, "w") as f:
                f.write("package p\nfunc A() {}\n")
            wl = os.path.join(d, "wl.json")
            json.dump([{"file": "x.go", "name": "A", "start_line": 2, "anchor_sha": "aaa1111"}], open(wl, "w"))
            stdin = io.StringIO(json.dumps([{"file": "x.go", "name": "A", "start_line": 2, "desc": "build A"}]))
            _orig = sys.stdin
            sys.stdin = stdin
            try:
                rc = sa.main(["write", "--worklist", wl, "-C", d])
            finally:
                sys.stdin = _orig
            self.assertEqual(rc, 0)
            self.assertEqual(open(p).read().splitlines()[1], "// SEM@aaa1111: build A")
```

(If the old `test_write_subcommand_with_cwd` exists, replace it with the above; remove any other test that calls `sa.write` with the old single-list signature.)

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_sem_annotate.TestWrite -v`
Expected: FAIL (old `write` signature).

- [ ] **Step 3: Rewrite `write`**

Replace the `write` function:

```python
def write(descriptions, worklist, cwd=None):
    """Apply markers, stamping the authoritative anchor_sha from the worklist.

    descriptions: list of {"file","name","start_line","desc"} (LLM output, no sha).
    worklist:     list of {"file","name","start_line","anchor_sha", ...} (scan output).
    The sha is taken from the worklist (NEVER the LLM); a blank anchor falls back to
    the current HEAD sha. Returns {"files_written","markers","skipped"}.
    """
    anchors = {(w["file"], w["name"], w["start_line"]): (w.get("anchor_sha") or "")
               for w in worklist}
    by_file = {}
    skipped = 0
    for d in descriptions:
        key = (d["file"], d["name"], d["start_line"])
        if key not in anchors:
            skipped += 1
            continue
        sha = anchors[key] or head_sha(cwd)
        by_file.setdefault(d["file"], []).append(
            {"start_line": d["start_line"], "sha": sha, "desc": d["desc"]})
    written = 0
    markers = 0
    for f, ups in by_file.items():
        abspath = f if cwd is None else os.path.join(cwd, f)
        prefix = comment_prefix(f)
        if prefix is None:
            continue
        lines = _read_text(abspath).splitlines()
        for u in sorted(ups, key=lambda x: x["start_line"], reverse=True):
            lines = apply_marker(lines, u["start_line"], prefix, u["sha"], u["desc"])
        with open(abspath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written += 1
        markers += len(ups)
    return {"files_written": written, "markers": markers, "skipped": skipped}
```

In `parse_args`, change the `write` subparser:

```python
    w = sub.add_parser("write")
    w.add_argument("--worklist", required=True)
    w.add_argument("-C", "--cwd", default=None)
```

In `main`, replace the `write` branch:

```python
    if ns.cmd == "write":
        descriptions = json.load(sys.stdin)
        with open(ns.worklist, "r", encoding="utf-8") as wf:
            worklist = json.load(wf)
        res = write(descriptions, worklist, cwd=ns.cwd)
        print(json.dumps(res))
        return 0
```

- [ ] **Step 4: Run write tests + FULL suite**

Run: `python3 -m unittest tests.test_sem_annotate.TestWrite -v`
Expected: PASS.
Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK (all green).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "fix(sem-annotate): write stamps authoritative anchor_sha; LLM no longer supplies sha (#12)"
```

---

### Task 6: Agent + SKILL.md orchestration

**Files:**
- Modify: `dev/agents/sem-describe.md`
- Modify: `dev/skills/sem-annotate/SKILL.md`

- [ ] **Step 1: Drop the SHA from the agent contract**

In `dev/agents/sem-describe.md`:
- Change the described output schema from `{file, name, start_line, sha, desc}` to `{file, name, start_line, desc}` (frontmatter description line AND the Steps section).
- Remove the instruction (currently step 3: "emit `sha` = the item's `blame_sha` (use the full value provided)"). Replace with: emit `{file, name, start_line, desc}` only — the SHA is stamped by the tool, never by you.
- The input items may still include `anchor_sha`/`status` for context; state the agent must ignore them for output.

- [ ] **Step 2: Update SKILL.md Steps 3–5**

In `dev/skills/sem-annotate/SKILL.md`:
- Step 3: subagents return `{file, name, start_line, desc}` (no sha); concatenate into `/tmp/sem-updates.json`.
- Step 4: change the write command to:
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py write --worklist /tmp/sem-work.json -C <repo-dir> < /tmp/sem-updates.json
  ```
  and note `write` stamps the authoritative SHA from the worklist (the LLM never supplies a SHA).
- Step 5: note the post-write re-scan works on a dirty tree (anchors come from committed history via `sem log`, so just-written markers read `fresh`; a clean pass re-scans to `{missing: 0}` with no `stale`). Document the new statuses: `uncommitted` (dirty tree) and `invalid-sha` (a previously-written marker carries a bad hash; it will be re-annotated).

- [ ] **Step 3: Verify**

Run: `grep -n "sha\|--worklist\|invalid-sha\|uncommitted" dev/skills/sem-annotate/SKILL.md dev/agents/sem-describe.md`
Expected: agent schema shows `{file, name, start_line, desc}`; SKILL.md Step 4 uses `--worklist`; statuses documented.

- [ ] **Step 4: Commit**

```bash
git add dev/agents/sem-describe.md dev/skills/sem-annotate/SKILL.md
git commit -m "docs(sem-annotate): agent drops sha; write takes --worklist; document new statuses (#12/#11)"
```

## Self-Review

- **Spec coverage:** classify uncommitted (T1) ✓; InvalidRevError (T2) ✓; entity_logic_sha anchor via sem log (T3) ✓; scan invalid-sha + dirty-tree + anchor + rename (T4) ✓; write stamps authoritative sha + CLI (T5) ✓; agent drops sha + SKILL orchestration + statuses (T6) ✓; #13 regression test (T4) ✓.
- **Placeholder scan:** none.
- **Type consistency:** worklist key `anchor_sha` used in T4 (produced) and T5 (consumed) ✓; `write(descriptions, worklist, cwd)` signature consistent T5/T6 ✓; `entity_logic_sha(..., fallback_sha="")` consistent T3/T4 ✓; `InvalidRevError` raised T2, caught T4 ✓.
- Note: Task 4 Step 4 intentionally tolerates the write tests failing until Task 5 (sequenced).
