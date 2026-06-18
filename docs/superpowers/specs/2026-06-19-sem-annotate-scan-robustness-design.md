# Design: sem-annotate scan/classify robustness + correct SHA anchoring (Issues #11, #12, #13)

**Date:** 2026-06-19
**Issues:** ericfitz/skills#11, #12, #13
**Status:** Approved design

## Summary

Three linked defects in the `sem-annotate` pipeline, all in `sem_annotate.py`'s
scan/classify/blame path:

- **#11** — `scan` crashes (`NoneType.startswith`) on a dirty tree because `classify`
  assumes `blame_commit` is always a string.
- **#12** — the description LLM can corrupt the blame SHA it is told to copy verbatim
  (observed: 5/5474 markers), and a later `scan` hard-crashes on the first marker whose
  SHA is not a valid commit.
- **#13** — freshly-written markers on multi-commit entities are reported `stale` because
  the marker SHA is the declaration-line blame while staleness is judged by an
  entity-level `sem diff`.

The fix makes `scan`/`classify` robust to imperfect inputs, removes the SHA from the LLM's
responsibilities entirely (the tool stamps it), and anchors the marker SHA to the entity's
last *logical* change so a freshly-written marker is internally consistent (`fresh`).

## Approved decisions

1. **#12 root cause:** the tool stamps the authoritative SHA; the SEM Describer agent no
   longer emits a SHA. The LLM never touches it.
2. **#13 anchor:** marker SHA = the entity's newest logic-change commit from
   `sem log <entity> --file <f>` (cosmetic-aware, matches `sem diff --no-cosmetics`).
3. One combined spec/plan.
4. Plugin minor bump `2.2.0 → 2.3.0` at landing.

## Status vocabulary

`classify` returns one of: `missing`, `fresh`, `stale`, `uncommitted`, `invalid-sha`.
The `scan` worklist surfaces only the statuses that need (re)annotation:
`missing`, `stale`, `invalid-sha`. `fresh` and `uncommitted` are excluded (so a post-write
re-scan over a clean annotation reports nothing to do).

## Component 1 — Entity-level anchor SHA (#13)

New `sem log` wrapper and selector in `sem_annotate.py`:

- `sem_log_entity(name, file, cwd=None) -> dict` — runs `sem log --json <name> --file
  <file>` and returns the parsed payload (`{"changes": [...], ...}`). On `SemError`
  (entity not found in history, etc.) returns `{"changes": []}`.
- `entity_logic_sha(name, file, cwd=None) -> str` — returns the SHA of the **newest**
  entry in `changes` whose `change_type` is `"modified (logic)"` or `"added"` (iterating
  the list, which is oldest-first, and taking the last match). Fallback chain when no
  logic/added entry exists or `sem log` is empty: `sem blame` commit for the entity →
  `""`.

`scan` uses `anchor_sha = entity_logic_sha(name, file, cwd)` as the entity's anchor
(replacing the old declaration-line `blame_sha`). Because the anchor is the last logical
change, `sem diff <anchor_sha>..HEAD --no-cosmetics` is empty right after writing, so the
just-written marker classifies `fresh`. Drift detection is unaffected: when a later logical
change lands, the recomputed anchor advances past the marker's SHA and the existing
`logic_changed_entities` check flags `stale`.

**Worklist field rename:** the per-item anchor field is `anchor_sha` (was `blame_sha`).

## Component 2 — Tool stamps the SHA; agent drops it (#12 root cause)

**Agent (`dev/agents/sem-describe.md`):** output schema becomes
`{file, name, start_line, desc}` — drop `sha`. Remove the instruction to emit
`sha = blame_sha`. The input items may keep `anchor_sha`/`status` for context, but the
agent must not return a SHA.

**`write` (`sem_annotate.py`):** signature and CLI change so the tool owns the SHA:

- New CLI: `sem_annotate.py write --worklist <path> -C <repo> < <descriptions.json>`.
- `write(descriptions, worklist, cwd=None) -> dict`:
  - Build an index of the worklist by `(file, name, start_line) -> anchor_sha`.
  - For each description `(file, name, start_line, desc)`: look up `anchor_sha`. If found,
    apply the marker with the **authoritative** `anchor_sha` and the agent's `desc`. If a
    description has no matching worklist row, skip it and increment a `skipped` counter.
  - Apply markers bottom-up per file (unchanged logic), skipping files whose
    `comment_prefix` is `None`.
  - Return `{"files_written": n, "markers": m, "skipped": k}`.
- If `anchor_sha` for a matched row is empty (uncommitted/new entity with no history),
  stamp the current HEAD sha via a small `head_sha(cwd)` helper (so a marker always
  carries a real-ish commit and never an empty SHA). Document this edge.

The LLM-supplied SHA corruption class is eliminated: SHAs only ever come from the tool's
own `sem log`/`sem blame`/HEAD reads.

## Component 3 — Robust `classify` / `scan` (#11 + #12 symptom)

**`classify(existing_sha, anchor_sha, logic_changed)`:**

```
if not existing_sha:                      return "missing"
if _is_uncommitted(anchor_sha):           return "uncommitted"   # None / "" / all-zeros
if anchor_sha.startswith(existing_sha):   return "fresh"
return "stale" if logic_changed else "fresh"
```

`_is_uncommitted(sha)` is true for `None`, `""`, or an all-zeros SHA
(`re.fullmatch(r"0{7,40}", sha)`) — git's "Not Committed Yet" sentinel.

**`run_sem` invalid-revspec detection:** add `class InvalidRevError(SemError)`. In
`run_sem`, when a command fails and stderr matches a not-found revspec (e.g. contains
`"not found"` together with `"revspec"` or `"Reference"`), raise `InvalidRevError` instead
of a plain `SemError`.

**`scan`:** for each entity:
- Coerce blame/anchor `None` → `""`.
- Compute `logic` only when `existing_sha` and `anchor_sha` and they differ; wrap the
  `logic_changed_entities` call in `try/except InvalidRevError` → on catch, set status
  `invalid-sha` (the existing marker points at a non-existent commit) and surface the
  entity with `file`, `name`, and the bad `sha` (the marker's `existing_sha`).
- Otherwise `status = classify(existing_sha, anchor_sha, logic)`.
- Append to the worklist when `status in {"missing", "stale", "invalid-sha"}`, carrying
  `file, name, start_line, end_line, status, anchor_sha, existing_desc` (and `bad_sha` for
  `invalid-sha`).

A single malformed hash anywhere in scope no longer aborts the scan; it degrades to a
reported `invalid-sha` item that the next annotation round re-stamps correctly.

## Component 4 — Orchestration (`dev/skills/sem-annotate/SKILL.md`)

- **Step 3:** the `dev:SEM Describer` subagents return `{file, name, start_line, desc}`
  (no SHA). Concatenate into `/tmp/sem-updates.json`.
- **Step 4:** `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py write
  --worklist /tmp/sem-work.json -C <repo-dir> < /tmp/sem-updates.json`.
- **Step 5:** note that the post-write re-scan now works on a dirty tree — anchors come
  from committed history via `sem log`, so just-written (uncommitted) markers read
  `fresh`; a clean pass re-scans to `{missing: 0}` with no `stale`.
- Document the new statuses (`uncommitted`, `invalid-sha`) and that an `invalid-sha` item
  means a previously-written marker carries a bad hash and will be re-annotated.

## Error handling

- Missing `sem` CLI: unchanged (`SemError` at preflight).
- `sem log` failure for an entity: treated as "no history" → fallback anchor, never fatal.
- Invalid revspec in `sem diff`: caught → `invalid-sha`, never fatal.
- Dirty tree / uncommitted entities: `uncommitted` status, never fatal.

## Testing (stdlib `unittest`, mocking `sem_log_entity`/`sem_blame`/`run_sem`)

- `classify`: `uncommitted` for `None` / `""` / all-zeros anchor; `missing`/`fresh`/`stale`
  paths unchanged.
- `entity_logic_sha`: picks the newest `modified (logic)`/`added` commit; a later
  `modified (cosmetic)` entry does not move the anchor (it still anchors to the logic
  commit); falls back to `sem blame` then `""` when there is no logic/added entry.
- `run_sem` / `InvalidRevError`: a "revspec not found" stderr raises `InvalidRevError`.
- `scan`: a marker with a bogus 40-hex SHA yields a single `invalid-sha` worklist item
  (no crash); other entities still classified.
- `scan` dirty tree: an entity whose anchor is `None`/all-zeros does not crash and is not
  surfaced as `missing`.
- `write`: joins descriptions to the worklist, stamps the worklist's `anchor_sha` (not any
  agent value), skips unmatched descriptions with a count.
- **#13 regression:** an entity whose body changed in a commit later than its
  declaration-line blame (mock `sem_log_entity` to return a newer logic commit) is `fresh`
  immediately after annotation (marker SHA == anchor).

## Out of scope

- Changing the description content standard.
- Persisting `invalid-sha` reports anywhere beyond the worklist output.
- The `.local/sem.db` index (Issue #10, already shipped) — unaffected, though a future
  `db build` will naturally pick up the corrected SHAs.
