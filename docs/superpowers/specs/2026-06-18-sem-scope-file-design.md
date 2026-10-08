# Design: Repo-local scope file for sem-annotate and dedupe (Issue #8)

**Date:** 2026-06-18
**Issue:** ericfitz/skills#8
**Status:** Approved design

## Summary

Running `/sem-annotate` (and by extension `/dedupe`) against a large repo with no path
argument scans the entire repo. For a real-world Angular app this surfaced ~5,800
entities — including build scripts, e2e Playwright helpers, and test mocks — that have
little value for the dedupe consumer and inflate annotation cost. Today the only way to
scope is to pass paths on every invocation, which is easy to forget and not discoverable.

This change adds a repo-local, gitignored scope file that defines default include/exclude
globs, honored by **both** `sem_annotate.py` and `dedupe.py` when no explicit path
argument is given.

## Scope file

**Path:** `<repo>/.local/sem-scope.json` (JSON, matching the existing `.local/` cache
convention — `projects.json`, `project-cache.json` — and avoiding a new PyYAML
dependency). The `.local/` directory is always gitignored.

**Shape:**
```json
{
  "include": ["src/", "e2e/"],
  "exclude": ["scripts/", "**/*.spec.ts"]
}
```

- Both keys optional. Missing/empty `include` ⇒ default to `["."]` (whole repo).
  Missing/empty `exclude` ⇒ no exclusions.
- Unknown keys are ignored (forward-compatible).
- A malformed JSON file is a hard error with a clear message (do not silently fall back
  to whole-repo, which would defeat the purpose).

## Shared module: `dev/scripts/sem_scope.py`

The glob/scope logic lives in **one** module imported by both `sem_annotate.py` and
`dedupe.py` (single source of truth; independently testable).

API:

- `load_scope(cwd) -> dict | None`
  - Reads `<cwd>/.local/sem-scope.json` (cwd defaults to process cwd).
  - Returns the parsed/validated dict, or `None` if the file is absent.
  - Raises a clear error on malformed JSON or wrong types.
- `glob_match(relpath, pattern) -> bool`
  - A small, tested glob→regex translator supporting:
    - `**` — matches across path separators (zero or more segments).
    - `*` — matches within a single path segment (not `/`).
    - `?` — single non-`/` character.
    - Trailing `/` (e.g. `scripts/`) — directory-prefix match: `relpath == "scripts"` or
      `relpath.startswith("scripts/")`.
  - Operates on POSIX-style relative paths (forward slashes); callers normalize
    backslashes before calling.
  - Implemented by translating the glob to a regex (avoids `pathlib` version differences
    around `**` / `full_match`).
- `is_excluded(relpath, scope) -> bool`
  - True if `relpath` matches any pattern in `scope["exclude"]` via `glob_match`.
- `include_paths(scope) -> list[str]`
  - Returns `scope["include"]` if non-empty, else `["."]`.

## Precedence and integration

**Universal precedence rule (both tools):** if the user passes explicit path arguments,
use them and **ignore the scope file entirely** (no include, no exclude). The scope file
only applies when no path argument is given. This matches the issue's "explicit args
override the file."

### `sem_annotate.py`

- Change the `scan` subcommand `paths` default from `["."]` to `None` so "user passed
  nothing" is distinguishable from "user passed `.`". (Apply the same to the top-level
  default-paths handling.)
- In `scan(...)`:
  - If `paths` is `None` (no explicit args): load the scope; if present, use
    `include_paths(scope)` as the entity-discovery paths and drop any entity whose file
    matches `is_excluded(...)`. If no scope file, fall back to `["."]`.
  - If `paths` is provided: behave exactly as today (no scope file consulted).
- `--update <files>` continues to operate on the explicit file list (treated as explicit
  args — scope file not consulted).

### `dedupe.py`

- The `load` subcommand already takes a `scope` positional (`nargs="*"`, default `[]`)
  used as prefix-based `scope_paths` in `_in_scope` / `_filter_graph`.
- When `scope` is empty (no explicit args): load the scope file; if present, set
  `scope_paths` from `include_paths(scope)` (prefix semantics, as today) and pass the
  `exclude` patterns through to filtering.
- Extend `_in_scope(path, scope_paths, exts)` (or its caller) to also drop a path when
  `is_excluded(relpath, scope)` is true.
- When `scope` is provided explicitly: behave as today (scope file not consulted).

## Documentation

- `dev/skills/sem-annotate/SKILL.md`: document `.local/sem-scope.json`, its JSON shape,
  that it is gitignored/machine-local, and the precedence rule.
- `dev/skills/dedupe/SKILL.md`: same note, pointing to the shared behavior.

## Acceptance criteria

- [ ] `sem_annotate.py scan` honors `.local/sem-scope.json` include/exclude when no path
      arg is passed; explicit args take precedence.
- [ ] `dedupe.py load` honors the same file's include/exclude when no scope arg is passed;
      explicit args take precedence.
- [ ] Shared `dev/scripts/sem_scope.py` implements `load_scope`, `glob_match`,
      `is_excluded`, `include_paths`, with unit tests covering `**`, `*`, `?`, and
      trailing-`/` directory patterns.
- [ ] Malformed scope JSON raises a clear error (no silent whole-repo fallback).
- [ ] Both SKILL.md files document the file and its precedence.

## Testing

- Unit tests for `glob_match` / `is_excluded`: `scripts/` excludes `scripts/build.ts`;
  `**/*.spec.ts` excludes `src/a/b.spec.ts` but not `src/a/b.ts`; `*` does not cross `/`.
- Unit test for `load_scope`: absent file → `None`; valid file → dict; malformed → error.
- Integration: `scan` with a scope file vs. with explicit args (precedence); dedupe
  `load` with empty scope vs. explicit scope.

## Out of scope

- A global (user-level) scope file. This is repo-local only.
- Per-language default exclude presets (could be a later enhancement).
