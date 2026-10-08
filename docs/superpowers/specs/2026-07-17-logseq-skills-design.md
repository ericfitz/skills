# Logseq Skills Plugin — Design

**Date:** 2026-07-17
**Status:** Approved (section-by-section, in-session)

## Goal

A new `logseq` plugin in the `efitz-skills` marketplace: five skills that let
Claude capture into, query, lint, reorganize, and import (from Obsidian) a
classic file-based Logseq graph on the local machine.

## Requirements

- Target: classic file-based Logseq (graph = folder of `.md` files under
  `pages/` and `journals/`). The DB version is out of scope.
- Access mechanism: **hybrid** — read from files; write via Logseq's local
  HTTP API when the app is running and the API is enabled, falling back to
  direct file edits otherwise.
- Configuration: machine-local config file, with auto-discovery fallback when
  the config is missing or stale.
- Workflows: capture/append, query/search, consistency lint, merge/dedupe,
  restructure, and an Obsidian → Logseq converter scoped to a single note, a
  folder, or the whole vault (same engine).
- Architecture: approach A — skill-per-workflow over a shared, tested core
  library. Judgment lives in SKILL.md instructions; deterministic mechanics
  live in a Python library exercised by pytest.

## Section 1 — Plugin layout & configuration

### Layout

```
logseq/
  .claude-plugin/plugin.json
  skills/
    capture/SKILL.md
    query/SKILL.md
    lint/SKILL.md
    organize/SKILL.md
    from-obsidian/SKILL.md
  scripts/
    logseq-cli.py            # single CLI entry, subcommand per operation
    logseqlib/               # shared package: config, page, api, scan, convert
tests/
  test_logseq_*.py           # alongside the existing bump tests
```

Plus a `logseq` entry in `.claude-plugin/marketplace.json` and a README
section. Skills invoke the CLI via `${CLAUDE_PLUGIN_ROOT}/scripts/logseq-cli.py`,
with the same CLAUDE_PLUGIN_ROOT resolution/fallback note used by `deps:bump`.

### Configuration

`~/.config/logseq-skills/config.json`:

```json
{
  "graphs": { "<name>": { "path": "/abs/path/to/graph" } },
  "default_graph": "<name>",
  "obsidian_vault": "/abs/path/to/vault",
  "api": { "url": "http://127.0.0.1:12315", "token_env": "LOGSEQ_API_TOKEN" }
}
```

- The API token stays out of the file: it is read from the environment
  variable named by `token_env`.
- `obsidian_vault` is set the first time `from-obsidian` runs (asked once).

### Auto-discovery fallback

When the config is missing, or a configured `path` does not exist or is not a
Logseq graph (no `logseq/` metadata dir inside), the CLI reads Logseq's own
recent-graphs list (`~/.logseq/graphs/*.transit` — filenames encode graph
paths) to locate candidates:

- Exactly one candidate → use it and offer to write/refresh the config.
- Several candidates → the skill asks the user which one.

All skills resolve the graph the same way, through one
`logseqlib.config.resolve()` call.

## Section 2 — Core library (`logseqlib`)

Four modules behind the CLI (plus `config`, above), each independently
testable.

### `page` — Logseq markdown parser/writer

- Parses a page file into a block tree: each top-level bullet is a block;
  indentation (tab or 2-space, detected per file) defines children;
  `key:: value` lines attach as page properties (top of file) or block
  properties.
- **Round-trip fidelity is the contract:** `parse(text) → write(tree) == text`
  for untouched blocks, byte-for-byte.
- Anything v1 does not model — `{{query …}}`, `{{embed …}}`, org-style
  drawers (`:LOGBOOK:`), code fences — is carried as opaque text and never
  rewritten.
- This module carries the bulk of the test weight.

### `api` — hybrid access layer

- Thin client for Logseq's local HTTP API (`POST /api` with bearer token).
- Probes once per invocation (app up? token valid?). If available, writes go
  through structured calls (`logseq.Editor.appendBlockInPage`, `insertBlock`,
  …) and Datalog queries become available to the `query` skill. If not,
  writes fall back to `page`-module file edits.
- One function per logical operation (`append_to_page`, `append_to_journal`,
  `create_page`) hides which path was taken — but the CLI reports it
  (`via: api` / `via: files`).

### `scan` — read-only graph walker

- Iterates `pages/` + `journals/`, yields parsed pages, builds the link graph
  (wikilinks, tags, properties) once per run.
- Used by `query`, `lint`, and `organize`.
- Lint checks (broken links, orphans, tag/name-case inconsistencies,
  near-duplicate page names) are pure functions over this index that emit
  structured findings; Claude judges the findings, the CLI applies chosen
  fixes.

### `convert` — Obsidian conversion engine

- Frontmatter → `property::` lines.
- Prose paragraphs → top-level bullets; existing lists keep their nesting.
- `![[embeds]]` → `{{embed …}}`; `#tags` and `[[wikilinks]]` pass through;
  callouts → Logseq admonitions; assets copied into `assets/`.
- Emits a per-note report of anything that did not map cleanly.
- Never overwrites an existing Logseq page — collisions become findings for
  the user to resolve.

## Section 3 — The five skills

Each SKILL.md is thin: resolve the graph, call the CLI for mechanics, apply
judgment where the operation needs it.

### `capture`

"Add this to Logseq." Takes free text (a note, TODO, meeting summary); Claude
decides destination — today's journal (default) or a named page if specified —
formats it as outline blocks (TODO keywords, tags, links where apt), then
appends via the hybrid layer. Reports what was written, where, and via which
path.

### `query`

"Answer from my graph." Claude picks the cheapest sufficient strategy: `rg`
over the graph for keyword lookups; the scan index for structural questions
(backlinks, tagged pages, orphans); Datalog via the API when it is running and
the question warrants it. Answers cite pages as `[[Page Name]]` plus file
paths. Read-only, always.

### `lint`

Runs the scan checks, presents findings grouped by type with proposed fixes
(e.g. unify `[[foo]]`/`[[Foo]]`, repair a renamed-page link, list orphans).
The user chooses which groups to apply; fixes run through the CLI with a
dry-run diff first. Nothing auto-applies.

### `organize`

Merge/dedupe and restructure — the judgment-heavy skill.

- **Merges:** candidate pairs come from scan (name similarity, heavy link
  overlap); Claude reads both pages, proposes a merged outline and which title
  survives; on approval the CLI writes the merge and rewrites all inbound
  references.
- **Restructures** (split a page, promote journal content into a topic page):
  Claude proposes the block moves, the CLI executes them.
- Every operation shows its plan before touching files.

### `from-obsidian`

Takes a vault path (asked once, stored in config as `obsidian_vault`) plus a
scope: one note, a folder, or the whole vault. Runs `convert` in dry-run to
produce the report (page collisions, unmapped syntax, asset moves), the user
approves, then it imports. Repeatable: already-imported notes are detected via
two page properties stamped on import — `imported-from::` (vault-relative
source path) and `import-hash::` (source content hash) — and skipped unless
the source changed.

## Section 4 — Safety, error handling, testing

### Safety model

- Every mutating operation supports `--dry-run` (unified diff of what would
  change); skills always show the diff before applying anything beyond a
  single-block append.
- Before a multi-file operation (merge, lint fixes, bulk import), the CLI
  snapshots affected files to a timestamped backup dir under the graph's
  `logseq/.backups/` and prints the restore path.
- If the graph is itself a git repo, multi-file operations additionally
  require a clean working tree or explicit override, so git becomes the real
  undo.
- Single-page captures skip the ceremony.

### Hybrid edge cases

- API probe failures (app closed, server disabled, bad token) degrade
  silently to file mode — reported, never fatal.
- File writes while the app is running are safe for **new** blocks/pages
  (Logseq's watcher picks them up); for **rewrites** of existing pages
  (merge, lint fixes) with the app running but the API unavailable, the skill
  warns the user to avoid editing that page in-app until done.
- API errors mid-batch stop the batch and report what was applied.

### Error reporting

- The CLI exits nonzero with a structured message on anything unexpected
  (unparseable page, permission error, collision); skills surface these
  verbatim rather than improvising.
- A page that fails to parse is never written back — it is flagged and
  skipped.

### Testing

Pytest in the existing `tests/` dir:

- Round-trip corpus for the parser (real-world page shapes: nested outlines,
  properties, logbook drawers, code fences, queries).
- Converter fixtures (Obsidian input → expected Logseq output, including
  collision and edge cases).
- Config resolution against a fake `~/.logseq`.
- API client against a mocked server, including fallback paths.
- `scripts/verify-marketplace.sh` must pass with the new plugin entry.
- Lint + full test run before any task is called done.

## Out of scope (v1)

- Logseq DB version.
- Task-hygiene workflows (stale-TODO sweeps) — explicitly deprioritized.
- Parsing of `{{query}}`/`{{embed}}` internals, logbook drawers — opaque
  pass-through only.
- Sync with external tools (GitHub, calendars, etc.).
