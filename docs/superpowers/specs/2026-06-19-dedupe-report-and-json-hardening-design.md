# Design: dedupe report timestamping + sem-graph JSON hardening (Issues #6, #7)

**Date:** 2026-06-19
**Issues:** ericfitz/skills#6, #7
**Status:** Approved (trivial chores; fixes specified in the issues)

## Summary

Two small, independent robustness chores in `dev/scripts/dedupe.py`, found in the dedupe
rebuild's final review and deferred:

- **#6** — `dedupe.py report` writes a fixed `reports/dedupe-report.md`, overwriting prior
  reports. Use a timestamped filename so history is preserved.
- **#7** — `run_sem_graph` calls `json.loads(r.stdout)` unguarded; a `sem graph` that exits
  0 but emits malformed JSON leaks a bare `json.JSONDecodeError`. Wrap it in `SemError`.

## #6 — Timestamped report filename

In the `report` branch of `main()` (`dev/scripts/dedupe.py`), build the filename as
`f"dedupe-{datetime.datetime.now():%Y%m%dT%H%M%S}.md"` instead of the fixed
`"dedupe-report.md"`. Keep creating the `reports/` directory and printing the resulting
path (already done). Add `import datetime` (not currently imported).

Each run now writes a distinct file (e.g. `reports/dedupe-20260619T142233.md`); old reports
are retained.

## #7 — Wrap malformed sem-graph JSON in SemError

In `run_sem_graph`, replace the trailing `return json.loads(r.stdout)` with a guarded
parse that raises the tool's own `SemError` on malformed JSON:

```python
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise SemError(f"sem graph returned invalid JSON: {e}")
```

Scope: only `run_sem_graph` (the sole `sem` subprocess→JSON wrapper in `dedupe.py`). The
other `json.loads` call sites in `dedupe.py` parse local/SQLite data, not sem output, and
are out of scope.

## Testing (stdlib `unittest`, `tests/test_dedupe.py`)

- **#6:** invoke `dd.main(["report", "--db", <tempdb>])`, capture stdout, assert the
  reported path matches `r"dedupe-\d{8}T\d{6}\.md$"` and the file exists.
- **#7:** monkeypatch `dd.subprocess.run` to return an object whose `stdout` is malformed
  JSON (`"{not json"`) with `returncode 0`; assert `dd.run_sem_graph([])` raises
  `dd.SemError` (not `json.JSONDecodeError`).

## Out of scope

- #5 (embeddings / recall investigation) — a deferred research spike, not a code fix.
- Hardening `json.loads` in unrelated, non-sem call sites.
