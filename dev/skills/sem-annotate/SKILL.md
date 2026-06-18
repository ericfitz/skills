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
