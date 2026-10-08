# Design: Run sem-describe subagents on Sonnet (Issue #9)

**Date:** 2026-06-18
**Issue:** ericfitz/skills#9
**Status:** Approved design

## Summary

The `sem-annotate` skill dispatches parallel subagents to generate one-line intent
descriptions for code entities. These descriptions are short, mechanical, and
well-bounded — they do not require a frontier model. A full first-time annotation of a
real Angular app produced ~5,500 entities (~275 batches); running those on Opus is
wasteful. This change makes the description subagents run on Sonnet by default.

## Root cause

The bundled agent `dev/agents/sem-describe.md` **already declares** `model: sonnet` in
its frontmatter and is registered as the `dev:SEM Describer` agent. However, SKILL.md
step 3 instructs the orchestrator to dispatch a **`general-purpose`** subagent that merely
"follows" the `sem-describe.md` file. Because the dispatched agent type is
`general-purpose`, the `sem-describe.md` frontmatter `model: sonnet` is never applied —
the subagent inherits the orchestrator's model (often Opus).

## Change

Docs-only change to `dev/skills/sem-annotate/SKILL.md`, step 3 ("Generate descriptions
(parallel subagents)"):

- Dispatch the registered **`dev:SEM Describer`** agent type (which carries
  `model: sonnet` and `tools: Read, Bash`) instead of a `general-purpose` agent that
  "follows" the markdown file.
- Add an explicit statement that the description subagents run on **Sonnet**.
- Keep the batch/parallel-dispatch instructions otherwise unchanged: batches of ~20
  entities, parallel dispatch in one message, each subagent returns only the JSON array
  of `{file, name, start_line, sha, desc}`.

The `dev/agents/sem-describe.md` frontmatter already has `model: sonnet`; no change is
required there, but the spec confirms it as the single source of the model choice.

## What does NOT change

- The deterministic orchestrator steps (preflight, `scan`, `write`, review) are
  untouched and continue to run on whatever model the user invoked the skill with.
- The description content standard in `sem-describe.md` is unchanged.

## Acceptance criteria

- [ ] `sem-describe` description subagents run on Sonnet by default (via the
      `dev:SEM Describer` agent type's frontmatter).
- [ ] SKILL.md step 3 dispatches the registered agent type, not `general-purpose`, and
      explicitly notes the Sonnet model.
- [ ] `dev/agents/sem-describe.md` frontmatter retains `model: sonnet`.
- [ ] Orchestrator (deterministic) steps are unaffected.

## Verification

- Inspect SKILL.md step 3 to confirm it references `dev:SEM Describer` and states Sonnet.
- Confirm `dev/agents/sem-describe.md` frontmatter still has `model: sonnet`.
- Manual: run `/sem-annotate` on a small scope and confirm the dispatched description
  subagents report running on Sonnet.

## Out of scope

- Changing the description content standard.
- Making the model configurable per-invocation (could be a later enhancement).
