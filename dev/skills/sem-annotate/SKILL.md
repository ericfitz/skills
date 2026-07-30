---
name: sem-annotate
version: 1.0.0
description: "Generate and refresh SEM@<sha> intent markers on code entities using the sem CLI. Use when the user asks to annotate code with SEM markers, add or refresh entity descriptions, or prepare a codebase for dedupe. Supports Go, TypeScript/JavaScript, and Python. Modes: full-scope, --update <files>, --rebuild."
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

## Scope file

When no path argument is given, `scan` consults `.local/sem-scope.json` in the repo root for
default include/exclude globs. Explicit path arguments fully override this file (it is not
consulted at all).

**Shape:**
```json
{
  "include": ["src/", "pkg/"],
  "exclude": ["**/*.spec.ts", "scripts/"]
}
```

Both keys are optional. An absent or empty `include` defaults to scanning the whole repo
(`"."`). `exclude` patterns drop matching files from the scan.

`include` entries are **path prefixes** (directories like `src/`, `pkg/`) — they are matched
by `str.startswith`, NOT glob-matched. Use directory paths ending in `/`.

`exclude` entries are **glob patterns** — they support `**` (crosses path separators), `*`
and `?` (do not cross `/`), and a trailing `/` as a directory-prefix match (e.g. `scripts/`
matches `scripts` itself and any file underneath).

**Glob syntax (exclude only):** `**` crosses path separators; `*` and `?` do not; a trailing
`/` is a directory-prefix match.

The file lives in `.local/` and is gitignored (machine-local convention). Create it with
`mkdir -p .local && echo '{"include":["src/"],"exclude":["**/*.spec.ts"]}' > .local/sem-scope.json`.

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

**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), do the worker's job inline: read
`${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md` and process each batch
yourself, sequentially, following it exactly (the Sonnet model note below
applies only to dispatched subagents). Same batch sizes, same output
contract.

Split the worklist into batches (~20 entities each). For each batch, dispatch a
**`dev:SEM Describer`** subagent (defined by `${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md`),
passing the batch JSON and `REPO_DIR=<repo-dir>`. This agent runs on **Sonnet** by default
(via its frontmatter `model: sonnet`) — description writing is short and mechanical, and a
full pass can be hundreds of batches, so Sonnet is the right cost/quality point. Each
subagent returns a JSON array of `{file, name, start_line, desc}` — no `sha` field; the
SHA is stamped by the tool in Step 4. Collect and concatenate all arrays into one JSON
array `/tmp/sem-updates.json`.

Dispatch batches in parallel (one message, multiple Task calls). Subagents return only the
JSON array — do not read large transcripts back.

### 4. Write markers
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py write --worklist /tmp/sem-work.json -C <repo-dir> < /tmp/sem-updates.json
```

The `write` command stamps the authoritative SHA from the worklist (the `anchor_sha` field
from each scan entry). The LLM never supplies a SHA. If an entity's `anchor_sha` is blank,
`write` falls back to the current HEAD sha.

**After running `write`, check the returned JSON and warn loudly if:**
- `skipped > 0` — descriptions whose `(file, name, start_line)` triple did not match the
  worklist were silently dropped; those entities got NO marker. This usually means the
  subagent recomputed or renumbered `start_line` instead of echoing it exactly.
- `markers` is less than the number of items in the worklist — some entities were not
  written (either skipped due to mismatch, or their file type is unsupported).

In either case, surface the count to the user before proceeding to Step 4b.

### 4b. Refresh the `.local/sem.db` index

After writing markers, update the SQLite annotation index so it reflects the new state:

- **Full-scope annotate** (no `--update`):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py db build [paths] -C <repo-dir>
  ```
- **`--update <files>` annotate** (targeted refresh):
  ```bash
  python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py db update <files> -C <repo-dir>
  ```

`.local/sem.db` is a gitignored, regenerable mirror of in-source markers. The source markers
remain the source of truth. Run `db update` (no files) to re-index only files changed since
the stamped HEAD commit (auto-incremental); run `db build` to rebuild everything from scratch.

**Freshness check:** run
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/sem_annotate.py db status -C <repo-dir>
```
to compare the stored "highest commit covered" (`head_sha` / `head_commit_count`) against the
current HEAD. Verdict is one of `up-to-date`, `stale`, or `unknown`. When stale, run
`db update` (no files) to re-index only files changed since the stamped commit.

### 5. Review
Show the user `git diff` (markers only) for a quick review. Do not commit automatically
unless asked — `sem-auto` owns the commit-time workflow.

**Post-write re-scan:** after writing markers, a re-scan (`scan`) works correctly on a
dirty (uncommitted) tree. Anchors come from committed history via `sem log`, so
just-written markers whose `anchor_sha` matches will read `fresh`. A clean pass re-scans
to `{missing: 0}` with no `stale` entries.

**Status vocabulary:**
- `missing` — no marker exists yet
- `stale` — marker present but entity has a logical change since the anchored commit
- `uncommitted` — marker present but the anchor SHA is blank or all-zeros (dirty tree with
  no committed history for this entity); will resolve once changes are committed
- `invalid-sha` — a previously-written marker carries a SHA that `sem diff` cannot resolve
  (the commit was garbage-collected or the SHA is corrupt); the entity will be re-annotated
  by the next annotate pass

### 6. Offer the CLAUDE.md convention note (once)
If the project's `CLAUDE.md` does not already mention SEM markers, offer to add a short
note (this is `sem-auto`'s primary job; offer to run `/sem-auto` if the user wants the
git hook too).

## Notes
- The tool is the source of truth for all deterministic work (entity discovery, drift
  classification, marker writing). The only LLM step is description generation.
- Entity-granular: `--update` and the default scan only rewrite markers for entities that
  are missing or whose body logically changed; untouched entities keep their markers.
