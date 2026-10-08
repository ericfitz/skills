# Design: sem-powered code-health toolchain (`dedupe` rebuild + `sem-annotate` + `sem-auto`)

**Date:** 2026-06-18
**Status:** Approved design, pending implementation plan(s)

## Summary

Rebuild the `dedupe` skill around the `sem` MCP server (entity-level semantic code
intelligence backed by tree-sitter), and add two supporting skills that maintain a
durable semantic-description layer in source code.

The current `dedupe` skill is inefficient: it spawns a per-file analyzer agent for every
source file to *re-derive* semantic information (entity names, purposes, dependencies)
into a SQLite database. `sem` already provides all of that natively. This effort guts the
re-derivation machinery while **keeping the SQLite database as a coordination/result
spine** — that part earned its keep (it keeps the orchestrator's context window flat
regardless of repo size).

Three deliverables share one annotation convention:

1. **`dedupe`** (rebuilt) — find dead code and duplication using `sem`; produce a ranked,
   risk-assessed plan; optionally apply it.
2. **`sem-annotate`** (new) — generate and refresh `// SEM@<sha>:` intent markers on code
   entities. Independently useful (better `sem`/human comprehension).
3. **`sem-auto`** (new) — install a git hook that keeps markers fresh automatically, plus a
   `CLAUDE.md` note documenting the convention.

## Background: what `sem` actually provides

Empirically verified against this repo (six tools):

- **`sem_entities <path>`** — structural list of entities: `{file, name, type, start_line,
  end_line, parent_id, id}`. Types include `function`, `method`, `class`, plus non-code
  (`heading`, `chunk`, `property`, …). **No semantic description field.** One call covers a
  whole path. Output can be large (100s of KB) — must be piped into the DB, never held in
  the orchestrator's context.
- **`sem_impact <file> <entity>`** — `dependencies` (callees), `dependents` (callers),
  transitive `impact`, and affected `tests`. Per-entity. **`dependents.total == 0` is the
  dead-code signal.**
- **`sem_context <file> <entity> [budget]`** — actual source of the target entity plus its
  dependencies/dependents, packed to a token budget. This is the on-demand "description"
  (real code + docstrings), fetched only when a verifier needs it.
- **`sem_diff [base] [target] [file]`** — entity-level change set between two refs
  (`added/modified/deleted/moved/renamed/reordered`). Separates `reordered`/cosmetic from
  `modified`/logical. With no base, reports working-tree changes.
- **`sem_blame <file>`** — per-entity last-change commit + line range. One call per file.
- **`sem_log <entity> [file]`** — commit history for an entity.

**Key negative finding:** `sem` does **not** expose an AST, a normalized form, or any
content hash. It uses tree-sitter internally (and distinguishes cosmetic vs. logical
change in `sem_diff`/`sem_log`) but does not surface a reusable per-entity fingerprint.
This shapes the drift-detection design below.

## Shared convention: the SEM marker

A single-line comment immediately above an entity, carrying its intent and the commit at
which its body last logically changed:

```go
// SEM@4abcf04: Resolves the GitHub Project number for a repo, auto-detecting if unspecified
func findProject(owner, repo, projectArg string) (int, error) { ... }
```

- **Comment syntax is per-language:** `//` (Go, TypeScript), `#` (Python).
- **`@<sha>`** is the entity's last-change commit, obtained from `sem_blame` at write time.
- **Description** is one line of intent (what, not how).

### Drift detection (format-independent, zero new dependencies)

Because `sem` won't give us an AST hash, drift is detected by reusing `sem`'s own
tree-sitter-backed change classifier rather than a self-computed hash:

1. **Fast path:** `sem_blame` for the entity's file. If the entity's last-change commit
   equals its marker `@sha` → **fresh** (no further work).
2. **Slow path:** if the blame commit moved, `sem_diff(base=<marker sha>, file=…)` and check
   whether *this entity* appears in the `modified` set (logical change) vs only
   `reordered`/cosmetic. Logical change → **stale**. Cosmetic only → **fresh** (optionally
   refresh the stored `@sha`).
3. **Uncommitted edits:** `sem_diff` working-tree mode catches hand-edits not yet committed.

This is invariant to `gofmt`/`black`/`prettier` reformatting by construction (those land as
cosmetic/reordered), and is rename/move-aware (`sem` tracks moves with `prev_file_path`).

Trade-offs accepted: drift detection depends on git history and on `sem`'s classifier
accuracy; it requires the repo to be under git (true for all target projects).

### Description content standard (load-bearing for dedup recall)

The marker description **is** the duplicate-detection signal for `dedupe`'s cheap SQL
pre-filter (no embeddings are available; an LLM pass over every pair is too expensive at
scale). The pre-filter therefore only works if same-intent entities reliably produce
lexically-similar descriptions. Standardization is biased toward **recall** (true positives
/ minimizing false negatives): a false positive merely wastes one verifier subagent, while a
false negative misses a real duplicate permanently. Two coordinated levers:

**Write-side standard** — handed identically to every annotation subagent (in `sem-annotate`
and via the `sem-auto` hook), in priority order:

1. **Describe intent (the contract), never mechanism.** "validate a JWT and return its
   claims" — not "loop over header, split on '.', base64-decode each part". Intent converges
   across duplicates and drifts less than mechanism (so markers also stay fresh longer).
2. **Lead with a canonical verb** from a recommended lexicon (~30 verbs), mapping synonyms to
   one canonical form: `validate` (not check/verify/ensure), `fetch` (not get/retrieve/load
   for I/O reads), `store`, `build` (not create/make/construct), `convert`, `parse`,
   `format`, `serialize`/`deserialize`, `encode`/`decode`, `filter`, `map`, `compute`,
   `aggregate`, `register`, `route`, `dispatch`, `handle`, `authenticate`, `authorize`,
   `connect`, `subscribe`, `notify`, `retry`, `cache`, `lock`, `schedule`, `list`, `search`,
   `update`, `delete`.
3. **Name the subject with a canonical domain noun** — one consistent term per concept (a
   "session token", not token / auth-string / credential), reusing the project's existing
   vocabulary.
4. **Abstract incidental specifics** — describe roles, not identifiers/types: "the user's
   email", not "req.body.email" (a true duplicate elsewhere may use different names).
5. **One line, ≤ ~12 words, do not restate the entity name** (the name is already indexed;
   the description adds intent).
6. **Tag a strong side-effect when it discriminates** — `(pure)`, `(reads DB)`,
   `(mutates shared state)`. Aids the verifier and reduces false matches.

Examples:
```
// SEM@abc123: validate a JWT and return its claims; reject if expired (pure)
// SEM@abc123: fetch open issues for a repo from the GitHub API
// SEM@abc123: convert a domain User to its API DTO
```

**Compare-side normalization** — `dedupe` P3 normalizes before matching (belt-and-suspenders
for residual prose variation): lowercase, stem, drop stopwords, canonicalize the verb via a
small synonym table, then match on `(leading verb + subject)` exactly plus a token-set
Jaccard on the remainder, thresholded for recall.

Optional future lever (deferred): a small accumulating per-project glossary that
`sem-annotate` consults and grows, to stabilize canonical domain nouns across runs.

### Entity-granular updates (critical invariant)

A commit changes *files*, but a file may contain many entities. The `@sha` must mean "the
commit where **this entity's** body last logically changed." Therefore:

> **Marker rewrites are entity-granular, never file-granular.** When updating markers for a
> changed file, use `sem_diff(parent → commit, file)` to get the entities with a `modified`
> (logical) change, and rewrite markers for **only those** entities. Entities in the same
> file that did not change keep their existing markers untouched.

Rewriting an unchanged entity's marker would be incorrect: its code didn't move, its blame
didn't move, and bumping its `@sha` would mask future real drift.

## Skill 1: `sem-annotate` (new)

Owns the annotation lifecycle. Independently useful.

### Modes
- **Default (scope):** `/sem-annotate [path]` — annotate all entities under a path scope.
- **`--update <file(s)>`:** rebuild markers only for the affected file(s), entity-granular
  (only missing/stale entities within those files). This is the entry point the `sem-auto`
  hook calls.
- **`--rebuild [path]`:** ignore existing markers and regenerate all under the scope.

### Pipeline
1. `sem_entities <scope>` → code entities (filter out non-code types: `heading`, `chunk`,
   `property`, markdown, etc.).
2. One `grep` for existing `SEM@` markers, joined to entity line-ranges → coverage map.
3. `sem_blame` per file → classify each entity: **missing** / **stale** (logic changed
   since `@sha`, per drift rules) / **fresh**. `--rebuild` forces all to "missing".
4. Parallel subagents generate one-line intent descriptions for missing+stale entities
   (reading source via `sem_context`), and write markers into source with the current
   `@sha` from `sem_blame`. Fresh entities are skipped.
5. Present a reviewable diff of the inserted/updated markers.
6. Offer (once) to add a convention rule to the project's `CLAUDE.md` (see `sem-auto`,
   which is the primary owner of that note).

### Notes
- Description generation is the only LLM-heavy step; it is fully parallelizable and bounded
  by the number of missing/stale entities.
- Marker insertion must respect per-language comment syntax and not disturb existing
  leading comments/docstrings (insert above them, or update the existing `SEM@` line).

## Skill 2: `dedupe` (rebuilt)

SQLite spine, `sem` as data source. **SQL does everything deterministic; LLM subagents are
spent only on semantic judgment and per-candidate verification.**

General-purpose: works on any `sem`-indexed repo, takes a **path-scope argument** (e.g.
`/dedupe server/`) so unrelated tools/scripts can be excluded.

### Phases
- **P0 — Preflight & scope.** Parse path scope. Verify `sem` is reachable (one cheap
  `sem_entities` call); if absent, stop with a clear message. Initialize
  `.dedupe/dedupe.db`; reset the prior run's candidates/findings.
- **P1 — Load.** `sem_entities <scope>` once → a loader script imports code entities into
  the DB (dropping non-code types), recording exported-ness and an entry-point guess
  (`main`, `init`, exported/capitalized, `Test*`). A single `grep` ingests any existing SEM
  descriptions into `entities.description` (cheap accelerant; absence is fine). Output is
  piped straight to the DB — never held in orchestrator context.
- **P2 — Graph.** Parallel subagents shard the entity list, call `sem_impact` per entity,
  and write `edges(src_id → dst_id)` + `entity_tests` rows. One `sem_impact` call per entity
  yields both directions; dependents are also derivable in SQL by reversing `edges`. This is
  the only O(N) `sem` cost and is fully parallel. Subagents return only a status string.
- **P3 — Detect (SQL, no LLM).**
  - **Dead code** = entities with no incoming non-test edges, minus entry-point guesses.
    Entities reachable *only* from tests are flagged as a separate, lower-priority
    "production-dead" tier.
  - **Duplication candidates** = mechanical pre-filter → `candidate_clusters`: SEM-description
    similarity when descriptions are present (using the compare-side normalization in
    "Description content standard" above), else normalized-name / shared-n-gram /
    signature-shape matching. High recall; the LLM pass supplies precision.
- **P4 — Verify (parallel LLM, one subagent per candidate).**
  - **Dead-code verifier** actively tries to *refute* deadness — the failure modes a static
    graph misses: router/mux registration, interface satisfaction, reflection/codegen,
    struct-tag usage, exported-as-public-API. Verdict: `confirmed-dead | false-positive` +
    reason.
  - **Duplication verifier** reads both implementations via `sem_context` + `Read`, confirms
    real duplicate vs. coincidental similarity, and records **behavior differences** and
    consolidation feasibility.
  - Both write verdicts + impact/risk/effort scores + notes to `findings` and return only a
    status string. The orchestrator polls counts; it never ingests verifier transcripts.
- **P5 — Rank & present (SQL + short synthesis).** Order findings by impact × inverse-risk;
  group related work (e.g. several dead helpers in one file → one removal task; a duplicate
  cluster → one consolidation task). Emit a prioritized plan to `.dedupe/reports/`, with
  **Dead code** and **Duplication** sections; each item carries impact, risk, effort, and a
  concrete recommendation (`remove` / `consolidate` / `extract-common` / `leave-as-is`).
- **P6 — Apply (opt-in).** Present the plan, then offer to execute approved items via
  **subagent-driven development** (per global workflow): one fresh subagent per task, with
  review between tasks. Removals and consolidations are individually approvable units.

### Coverage offer
If SEM-comment coverage under the scope is low, `dedupe` makes a single per-run offer:
"N of M entities lack SEM comments — run `/sem-annotate` first for better duplicate
detection?" It never annotates inline.

### Removed from the current skill
Per-file analyzer agent, grouper agent, mtime/cache-validity machinery, language detection,
and the old `dedupe-report.py` (rewritten for the new schema). The result is meaningfully
simpler than today despite adding dead-code analysis.

### Database schema (sketch)
- `run_meta(run_id, scope, started_at, completed_at)`
- `phase_state(phase, status, started_at, completed_at, error_message)`
- `entities(id, file, name, type, start_line, end_line, signature, is_exported,
  is_entrypoint_guess, description, in_scope)`
- `edges(src_id, dst_id)` — call/use edges (from `sem_impact` dependencies)
- `entity_tests(entity_id, test_name)` — test-only reachability
- `dead_candidates(entity_id, tier, reason)` — SQL-populated
- `candidate_clusters(cluster_id, method, reason)` + `cluster_members(cluster_id, entity_id)`
- `findings(finding_id, kind, ref, verdict, behavior_diff, recommendation, impact, risk,
  effort, notes)` + `finding_entities(finding_id, entity_id)`

Concurrency: WAL mode + `busy_timeout` for safe parallel writes, as in the current skill.

## Skill 3: `sem-auto` (new)

Automates marker freshness for a project.

1. **Install a `post-commit` hook** that:
   - Bails out if a rebase / merge / cherry-pick / revert is in progress
     (`.git/MERGE_HEAD`, `.git/rebase-merge`, `.git/CHERRY_PICK_HEAD`, etc.) — appending a
     commit mid-operation would corrupt it. (A follow-up commit never rewrites history, so
     unlike `--amend` it is safe regardless of whether the original commit was pushed.)
   - Determines the commit's changed files, then runs `sem-annotate --update <files>`,
     which (entity-granular) rewrites markers only for entities that logically changed in
     this commit, referencing the **code commit's** sha.
   - Stages only the marker (comment-line) changes and creates a **separate follow-up
     commit** `chore(sem): update markers` — **not** an amend.
2. **Add a short `CLAUDE.md` note** explaining the convention: what `SEM@<sha>:` markers
   are, why they matter (durable intent layer powering `dedupe` and `sem` comprehension),
   that agents should add/update a marker on any new or logically-changed entity, and any
   efficiency/correctness guidance (entity-granular updates; trust fresh markers).

### Why follow-up commit, not amend (rationale)
`--amend` is **provably incompatible** with the `@sha` marker. Amending replaces the tip
commit with a new sha, which moves `git blame` for the just-committed lines to that new
sha. The marker written before the amend still references the old (now-orphaned) sha, so
every touched entity reads as stale immediately. Writing the new sha first is impossible
(it doesn't exist until the amend creates it; a corrective second amend produces yet
another sha). A follow-up commit avoids this: it only edits comment lines, so the entity's
**code** blame stays on the original commit and matches the marker's `@sha`.

The follow-up-commit hook **self-terminates**: its own `post-commit` re-runs
`sem-annotate --update`, finds all markers already fresh, writes nothing, and creates no
further commit. A sentinel guard is added as belt-and-suspenders, but the fixpoint is
natural.

## Cross-cutting risks & mitigations

- **Static-graph false positives for dead code** (dynamic dispatch, route registration,
  reflection, interface methods). *Mitigation:* SQL only *nominates*; a refutation-biased
  verifier subagent must clear each candidate before it reaches the plan.
- **Stale descriptions poisoning dedup.** *Mitigation:* `@sha` + `sem_diff` drift detection;
  `dedupe` treats descriptions as an accelerant and verifiers still read real source.
- **Large `sem_entities` output.** *Mitigation:* pipe to DB via a loader script; never hold
  in orchestrator context.
- **`sem` unavailable / repo not indexed.** *Mitigation:* P0 preflight stops with a clear
  message.
- **Per-entity `sem_impact` cost at scale.** *Mitigation:* parallel sharded subagents writing
  to the DB; only code entities (not headings/chunks/properties).

## Build sequencing

Each skill gets its own implementation plan:

1. **`sem-annotate` first** — smallest, self-contained, and `dedupe` consumes its output.
   Establishes the shared marker format and drift detection.
2. **`dedupe` rebuild** — depends on the marker format but degrades gracefully when markers
   are absent.
3. **`sem-auto`** — depends on `sem-annotate --update`; thin layer (hook + CLAUDE.md note).

## Open questions / deferred

- Exact mechanical-similarity thresholds for the dup pre-filter (tune during implementation
  against the tmi server codebase).
- Whether `sem-annotate` description generation should batch multiple entities per subagent
  call for throughput (implementation detail).
