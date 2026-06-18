# Design: SQLite annotation index with "highest commit covered" (Issue #10)

**Date:** 2026-06-18
**Issue:** ericfitz/skills#10
**Status:** Approved design

## Summary

`sem-annotate` writes `// SEM@<sha>: <intent>` markers inline in source files. This change
adds a SQLite database that mirrors those annotations into a queryable index and records
the **highest commit it covers**, so it is trivial to tell whether the index is up to date
with the repo's current HEAD. The database supports both a **full rebuild** and an
**incremental update** (re-index only changed files), so refreshing after a small edit
does not require re-reading every file.

## Location and ownership

- **Path:** `<repo>/.local/sem.db` — a gitignored, machine-local cache (per the `.local/`
  convention). Per-clone, regenerable.
- **Source of truth remains the in-source markers.** The database is a mirror/index, not
  the authority. It can be deleted and rebuilt at any time.
- Uses Python's stdlib `sqlite3`; no new dependency.

## Schema

```sql
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
-- keys: schema_version, head_sha, head_commit_count, updated_at

CREATE TABLE IF NOT EXISTS entities (
    file        TEXT NOT NULL,
    name        TEXT NOT NULL,
    start_line  INTEGER NOT NULL,
    end_line    INTEGER,
    sha         TEXT,        -- sha embedded in the SEM marker
    desc        TEXT,        -- marker description
    blame_sha   TEXT,        -- sem blame commit for the entity (optional)
    updated_at  TEXT,
    PRIMARY KEY (file, name, start_line)
);
CREATE INDEX IF NOT EXISTS idx_sem_entities_file ON entities(file);
```

- PK `(file, name, start_line)` accommodates overloaded/duplicate names within a file.
- `schema_version` enables forward migration.

## "Highest commit covered"

Stored in `meta` at every DB refresh:

- `head_sha = git rev-parse HEAD` — **authoritative** freshness key.
- `head_commit_count = git rev-list --count HEAD` — the human-friendly "commit #"
  (monotonic ordinal on linear history; noted as approximate across merges).
- `updated_at` — ISO timestamp of the refresh.

**Freshness check:** the index is "up to date" when stored `head_sha` equals the current
`git rev-parse HEAD`. `head_commit_count` gives a rough "N commits behind" sense.

Git is invoked via `subprocess` against the repo dir (`-C`/`--cwd`). If git is unavailable
or the repo has no commits, `head_sha`/`head_commit_count` are stored as empty and
`db status` reports "unknown".

## CLI: new `db` subcommand in `sem_annotate.py`

### `db build [paths] -C <repo>` — full pass

- Discover all code entities under `paths` (default per #8 scope file when no paths
  given; honors the same scope precedence rule).
- For each entity, read its current SEM marker (sha + desc) from the working-tree source
  (reusing the existing marker-parsing helpers), plus `end_line` from sem and optional
  `blame_sha`.
- Clear the rows for every file in the indexed scope (delete-then-insert per file, same
  as `db update`), so removed/renamed entities do not linger. A whole-repo build with no
  scope effectively rebuilds the full table.
- Stamp `meta` with current `head_sha`, `head_commit_count`, `updated_at`.

### `db update [files...] -C <repo>` — targeted incremental

- For each given file: `DELETE FROM entities WHERE file = ?`, then re-insert that file's
  current entities/markers. (Delete-then-insert handles entities removed or renamed within
  the file.)
- Re-stamp `meta` head to current HEAD.
- This pairs with the skill's `--update <files>` annotation flow.

### `db update` (no file args) — auto-incremental

- Read stored `head_sha` from `meta`. If absent (fresh/empty DB), fall back to a full
  `db build` and return.
- Compute the changed code-file set:
  - `git diff --name-only <head_sha>` — working tree vs the stamped commit, so it catches
    **uncommitted** marker writes as well as committed changes.
  - ∪ untracked files via `git ls-files --others --exclude-standard`.
  - Filter to supported code extensions and (when no explicit scope override) the #8
    scope include/exclude.
- Re-index only that file set (same delete-then-insert per file), then re-stamp head.
- Files that were deleted from the working tree have their rows removed.

### `db status -C <repo>`

- Print stored `head_sha` / `head_commit_count` / `updated_at`, the current HEAD, and a
  verdict: `up-to-date`, `stale (N commits behind / HEAD differs)`, or `unknown`.
- Exit code: `0` up-to-date, non-zero when stale (so it can gate scripts). Exact codes
  specified in the plan.

## Skill integration (`dev/skills/sem-annotate/SKILL.md`)

Add a DB-refresh step after "Write markers" (step 4):

- Full-scope annotate run ⇒ `db build [paths]`.
- `--update <files>` annotate run ⇒ `db update <files>`.
- Document `db status` as the freshness check, and that the DB lives at `.local/sem.db`
  (gitignored, regenerable).

## Acceptance criteria

- [ ] `sem_annotate.py db build` creates `.local/sem.db` if absent and fully indexes all
      code entities (file, name, start/end line, sha, desc, blame_sha).
- [ ] `db update <files>` re-indexes only the named files (delete-then-insert per file).
- [ ] `db update` (no args) re-indexes only files changed since the stamped `head_sha`
      (including uncommitted marker writes and untracked code files), falling back to a
      full build when no head is stored.
- [ ] `meta` records `head_sha` and `head_commit_count` ("highest commit covered") on
      every refresh.
- [ ] `db status` reports up-to-date vs stale by comparing stored head to current HEAD.
- [ ] The DB honors the #8 scope file when no explicit paths are passed.
- [ ] SKILL.md documents the DB, the refresh steps, and the freshness check.

## Testing

- Unit: schema init is idempotent; `meta` upsert round-trips; entity PK collision is an
  upsert, not a duplicate.
- Integration (temp git repo with a couple of annotated files):
  - `db build` populates rows + stamps head.
  - Edit one file's marker → `db update` (no args) re-indexes exactly that file; others
    untouched; head re-stamped.
  - `db status` flips from up-to-date to stale after a new commit, back to up-to-date
    after rebuild.
  - Removing an entity from a file and re-running `db update <file>` drops its row.

## Out of scope

- Committing the DB to the repo (decided: machine-local cache only).
- Having `dedupe` read from `sem.db` (dedupe keeps its own `.dedupe/dedupe.db`); a future
  enhancement could share the index.
- Concurrency/locking beyond sqlite defaults (single-user, local tool).
