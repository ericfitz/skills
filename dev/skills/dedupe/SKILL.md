---
name: dedupe
version: 2.0.0
description: Find dead code and duplication across a codebase using the sem CLI, then produce a ranked, risk-assessed plan and optionally apply it. Use when the user asks to dedupe, find duplicate or redundant code, or find dead/unused code. Takes a path scope (e.g. /dedupe server/) to exclude unrelated tools/scripts. Supports Go, TypeScript/JavaScript, and Python.
---

# dedupe

Find dead code and duplication with the `sem` CLI, verify candidates with parallel
subagents, and produce a prioritized plan. SQLite is the coordination spine; the LLM is
spent only on per-candidate verification.

Bundled tool: `${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py`.
Bundled agents: `${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dead.md`, `dedupe-verify-dup.md`.

## Usage

```
/dedupe [path ...]            # scope to these dirs (default: whole repo)
/dedupe server/ --exts .go    # scope to a dir and language
```

## Scope file

When no path argument is given, `load` consults `.local/sem-scope.json` in the repo root for
default include/exclude globs. Explicit path arguments fully override this file (it is not
consulted at all).

**Shape:**
```json
{
  "include": ["src/", "pkg/"],
  "exclude": ["**/*.spec.ts", "scripts/"]
}
```

Both keys are optional lists of glob patterns. An absent or empty `include` means whole-repo
(dedupe passes no prefix filter to `sem graph`). `exclude` glob patterns drop matching files
from the entity graph before dead-code and duplication analysis.

**Glob syntax:** `**` crosses path separators; `*` and `?` do not; a trailing `/` is a
directory-prefix match (e.g. `scripts/` matches `scripts` itself and any file underneath).

The file lives in `.local/` and is gitignored (machine-local convention). Create it with
`mkdir -p .local && echo '{"include":["src/"],"exclude":["**/*.spec.ts"]}' > .local/sem-scope.json`.

## Scope of detection (important)
- **Dead code** (Go, Python, TypeScript): candidates are non-entrypoint, non-test
  functions/methods with no callers in sem's graph, then filtered by a deterministic
  whole-repo usage scan that removes any whose name is referenced anywhere outside its
  definition (this catches interface dispatch, goroutine launches, and cross-module
  imports sem misses). The small residual is verified by a subagent. Detection favors
  precision (never flags used code) over recall (may miss some dead code). Residual
  **exported** symbols are flagged for a public-API check — they may be called from outside
  the repo.
- **Duplication** covers all functions/methods (name/description based; independent of the
  call graph).

## Process

### 1. Preflight
- Confirm `sem` is available: `sem --version`. If missing, stop and tell the user to install it.
- Determine repo dir (default cwd) and path scope from arguments. Ensure `.dedupe/` is gitignored.

### 2. Load + detect (one tool call)
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py load <scope> [--exts ...] -C <repo-dir>
```
This runs `sem graph --json` once, filters to in-scope code entities, ingests any SEM
marker descriptions, derives raw dead-code candidates, runs the deterministic whole-repo
usage refutation, and derives duplication candidates — all into `.dedupe/dedupe.db`. Read
the JSON summary (entities, edges, descriptions, dead_candidates_raw,
dead_refuted_by_usage, dead_candidates, dup_clusters).

If SEM-description coverage is low, make a single offer: "Run /sem-annotate first for
better duplicate detection?" — never annotate inline.

### 3. Get candidates
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py candidates -C <repo-dir> > /tmp/dedupe-cands.json
```
This yields `{"dead": [...], "dup_clusters": {...}}`.

### 4. Verify (parallel subagents, BATCHED)
- **Batch** candidates (~15–20 per subagent) — do NOT spawn one subagent per candidate.
  For each batch of dead candidates, dispatch a `general-purpose` subagent following
  `${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dead.md` with the batch JSON and
  `REPO_DIR=<repo-dir>`. For dup clusters, batch similarly with
  `dedupe-verify-dup.md`. Run batches in parallel (one message, multiple Task calls).
- **Cap:** if there are more than ~120 dead candidates or ~60 dup clusters, verify the
  first N (ordered as returned) and `log` exactly how many were deferred — never silently
  drop. Report the cap in the final summary.
- Each subagent returns ONLY a JSON array of verdicts. Collect them.

### 5. Record verdicts
Write every verdict to the DB with a single python call per kind, e.g.:
```bash
python3 -c "
import sys,json; sys.dont_write_bytecode=True
sys.path.insert(0,'${CLAUDE_PLUGIN_ROOT}/scripts'); import dedupe as dd
conn=dd._connect('.dedupe/dedupe.db')
for v in json.load(open('/tmp/dead-verdicts.json')):
    dd.record_finding(conn,'dead',v['verdict'],entity_id=v['entity_id'],
        impact=v.get('impact',''),risk=v.get('risk',''),effort=v.get('effort',''),
        recommendation=v.get('recommendation',''),notes=v.get('notes',''))
"
```
(Do the analogous loop for dup verdicts with `cluster_id` and `behavior_diff`.)

### 6. Rank + report
```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/dedupe.py report -C <repo-dir>
```
Show the user the report path and a short summary (counts, top items). The report ranks by
impact × inverse-risk and groups dead-code and duplication separately.

### 7. Offer to apply (opt-in)
Present the plan, then offer to execute approved items via **subagent-driven development**:
one fresh subagent per item (a dead-code removal, or a duplication consolidation), with
review between. Removals and consolidations are individually approvable. Never apply
without explicit approval.

## Notes
- The tool owns all deterministic work; the only LLM steps are candidate verification and
  (optionally) applying approved changes.
- `.dedupe/dedupe.db` persists; re-running `load` refreshes it.
