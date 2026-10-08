# dedupe Report Timestamp + JSON Hardening Implementation Plan (#6/#7)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Timestamp the dedupe report filename (#6) and wrap malformed `sem graph` JSON in `SemError` (#7).

**Architecture:** Two small, independent edits in `dev/scripts/dedupe.py` with `unittest` coverage in `tests/test_dedupe.py`.

**Tech Stack:** Python 3 stdlib (`datetime`, `json`), `unittest`.

## Global Constraints

- Full suite: `python3 -m unittest discover -s tests -t . -q` must stay green (currently 148 tests).
- Tests import via `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev" / "scripts"))`; module is `import dedupe as dd`.
- `#7` scope: only `run_sem_graph`. Do not touch unrelated `json.loads` call sites.

---

### Task 1: Wrap malformed sem-graph JSON in `SemError` (#7)

**Files:**
- Modify: `dev/scripts/dedupe.py` (`run_sem_graph`)
- Modify: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `run_sem_graph(exts, cwd=None)` raises `dd.SemError` (not `json.JSONDecodeError`) when `sem graph` emits malformed JSON.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dedupe.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_dedupe.TestRunSemGraphJSON -v`
Expected: `test_malformed_json_raises_semerror` FAILS (raises `json.JSONDecodeError`, not `SemError`).

- [ ] **Step 3: Implement**

In `dev/scripts/dedupe.py`, change the end of `run_sem_graph` from:

```python
    return json.loads(r.stdout)
```

to:

```python
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise SemError(f"sem graph returned invalid JSON: {e}")
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_dedupe.TestRunSemGraphJSON -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "fix(dedupe): wrap malformed sem-graph JSON in SemError (#7)"
```

---

### Task 2: Timestamp the report filename (#6)

**Files:**
- Modify: `dev/scripts/dedupe.py` (imports + `report` branch of `main`)
- Modify: `tests/test_dedupe.py`

**Interfaces:**
- Produces: `dedupe.py report` writes `reports/dedupe-<YYYYMMDDThhmmss>.md` and prints `{"report": <path>}`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_dedupe.py` (uses `io`/`json`/`re`/`tempfile`; add any missing imports at the top of the file):

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest tests.test_dedupe.TestReportFilename -v`
Expected: FAIL (basename is the fixed `dedupe-report.md`, not the timestamped pattern).

- [ ] **Step 3: Implement**

In `dev/scripts/dedupe.py`:

(a) Add `import datetime` to the imports block (after `import argparse`).

(b) In the `report` branch of `main`, replace:

```python
        path = os.path.join(os.path.dirname(ns.db) or ".", "reports",
                            "dedupe-report.md")
```

with:

```python
        fname = f"dedupe-{datetime.datetime.now():%Y%m%dT%H%M%S}.md"
        path = os.path.join(os.path.dirname(ns.db) or ".", "reports", fname)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest tests.test_dedupe.TestReportFilename -v`
Expected: PASS.

- [ ] **Step 5: Run full suite**

Run: `python3 -m unittest discover -s tests -t . -q`
Expected: OK (all green).

- [ ] **Step 6: Commit**

```bash
git add dev/scripts/dedupe.py tests/test_dedupe.py
git commit -m "fix(dedupe): timestamp report filename to preserve history (#6)"
```

## Self-Review

- Spec coverage: #7 SemError wrap (Task 1) ✓; #6 timestamped filename (Task 2) ✓; both tests ✓.
- No placeholders. `datetime.datetime.now()` is standard Python (not a Workflow script), so it is allowed.
- Type consistency: `SemError`, `run_sem_graph`, `main(["report", ...])` names match the codebase.
