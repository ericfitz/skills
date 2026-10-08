# sem-describe Sonnet Model Implementation Plan (Issue #9)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `sem-annotate` description-generation subagents run on Sonnet by default.

**Architecture:** Docs-only change. The bundled agent `dev/agents/sem-describe.md` already declares `model: sonnet` and is registered as the `dev:SEM Describer` agent type. SKILL.md currently dispatches a `general-purpose` agent that "follows" the file, so the frontmatter model is never applied. Fix: dispatch the registered agent type.

**Tech Stack:** Markdown (skill + agent docs).

## Global Constraints

- No code/tool changes; deterministic orchestrator steps (preflight, scan, write, review) stay model-agnostic.
- The model choice lives in exactly one place: `dev/agents/sem-describe.md` frontmatter (`model: sonnet`).

---

### Task 1: Point SKILL.md step 3 at the registered Sonnet agent

**Files:**
- Modify: `dev/skills/sem-annotate/SKILL.md` (Step 3, "Generate descriptions (parallel subagents)")
- Verify (no change expected): `dev/agents/sem-describe.md` frontmatter

**Interfaces:**
- Consumes: the registered agent type `dev:SEM Describer` (frontmatter `model: sonnet`, `tools: Read, Bash`).
- Produces: nothing for other tasks (standalone).

- [ ] **Step 1: Confirm the agent already declares Sonnet**

Run: `sed -n '1,6p' dev/agents/sem-describe.md`
Expected: frontmatter includes `model: sonnet` and `name: SEM Describer`. If missing, add `model: sonnet` to the frontmatter before proceeding.

- [ ] **Step 2: Rewrite SKILL.md Step 3 to dispatch the registered agent**

In `dev/skills/sem-annotate/SKILL.md`, replace the Step 3 body so it dispatches the registered `dev:SEM Describer` agent type (which carries `model: sonnet`) instead of a `general-purpose` agent that "follows" the markdown. The new text must:
- Name the agent type to dispatch: **`dev:SEM Describer`**.
- State explicitly that these description subagents run on **Sonnet** (cost: a full pass can be hundreds of batches; Sonnet is sufficient for one-line descriptions).
- Keep the rest unchanged: split worklist into ~20-entity batches; dispatch batches in parallel (one message, multiple Task calls); each subagent returns only the JSON array of `{file, name, start_line, sha, desc}`; concatenate into `/tmp/sem-updates.json`.

Replacement text for Step 3:

```markdown
### 3. Generate descriptions (parallel subagents)
Split the worklist into batches (~20 entities each). For each batch, dispatch a
**`dev:SEM Describer`** subagent (defined by `${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md`),
passing the batch JSON and `REPO_DIR=<repo-dir>`. This agent runs on **Sonnet** by default
(via its frontmatter `model: sonnet`) — description writing is short and mechanical, and a
full pass can be hundreds of batches, so Sonnet is the right cost/quality point. Each
subagent returns a JSON array of `{file, name, start_line, sha, desc}`. Collect and
concatenate all arrays into one JSON array `/tmp/sem-updates.json`.

Dispatch batches in parallel (one message, multiple Task calls). Subagents return only the
JSON array — do not read large transcripts back.
```

- [ ] **Step 3: Verify the edit**

Run: `grep -n "SEM Describer\|Sonnet\|general-purpose" dev/skills/sem-annotate/SKILL.md`
Expected: Step 3 now references `dev:SEM Describer` and `Sonnet`; the old `general-purpose` dispatch for descriptions is gone.

- [ ] **Step 4: Commit**

```bash
git add dev/skills/sem-annotate/SKILL.md dev/agents/sem-describe.md
git commit -m "feat(sem-annotate): dispatch description subagents on Sonnet (#9)"
```

## Self-Review

- Spec coverage: subagents run on Sonnet (Step 2) ✓; docs/frontmatter reflect choice (Steps 1-2) ✓; orchestrator unaffected (no code change) ✓.
- No placeholders.
