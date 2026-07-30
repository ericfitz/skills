# Codex Skill Parity (issue #23) — Design

**Date:** 2026-07-30
**Status:** Approved
**Tracks:** https://github.com/ericfitz/skills/issues/23

## Goal

Skills that rely on Claude Code subagent dispatch currently degrade
implicitly in Codex (the model improvises when it has no Task tool). Make
the degradation explicit and correct: every dispatching skill states exactly
what to do when subagents are unavailable, verified by dry-run comprehension
checks in real Codex.

## Background

- The repo ships as a plugin marketplace for both Claude Code and Codex
  (see `docs/superpowers/specs/2026-07-30-codex-marketplace-design.md`).
- Codex has no subagent/Task-tool equivalent; it executes skill
  instructions in a single agent loop. `${CLAUDE_PLUGIN_ROOT}` works there
  (compatibility alias), so bundled `agents/*.md` worker files ARE readable
  from installed plugins.
- Codex caches installed plugins by version
  (`~/.codex/plugins/cache/<marketplace>/<plugin>/<version>`), so content
  changes require a version bump to propagate to installs.
- Survey results (2026-07-30):
  - Subagent dispatch: `cats/run`, `dev/dedupe`, `dev/sem-annotate`,
    `itest/design`, `loc/backfill`, `security/race-cond`.
  - `security/race-cond` already carries a Codex note but references
    `security/COMPATIBILITY.md`, which does not exist (dangling link;
    no test catches relative markdown links today).
  - `allowed-tools` frontmatter (`github/create-issue`,
    `wiki/verify-doc`): permissive scoping only — each list already covers
    everything the skill needs, so a harness that ignores it grants more
    tools, never fewer. No correctness dependency; no changes needed.
  - No skill uses `AskUserQuestion`.

## Design

### 1. Inline fallback notes (6 skills)

Each affected skill gets one standardized block, placed immediately at the
skill's first dispatch instruction. For skills with bundled worker files
(`cats/run`, `dev/dedupe`, `dev/sem-annotate`):

> **No-subagent fallback:** If your harness cannot dispatch subagents (no
> Task tool), do the worker's job inline: read
> `${CLAUDE_PLUGIN_ROOT}/agents/<worker>.md` and process each batch
> yourself, sequentially, following it exactly. Same batch sizes, same
> output contracts.

(`<worker>` names the skill's actual agent file(s).) For generic-subagent
skills (`itest/design`, `loc/backfill`): the same marker, with the body
"run the per-phase / per-locale work sequentially inline, following the
same instructions you would have handed each subagent." For
`security/race-cond`: replace the dangling `../../COMPATIBILITY.md`
sentence with the standardized block; keep its existing tool-name examples.

The bold marker text `**No-subagent fallback:**` is identical everywhere —
greppable and testable.

### 2. Version bumps + manifest regeneration

Bump the patch version in `.claude-plugin/plugin.json` for each edited
plugin (`cats`, `dev`, `itest`, `loc`, `security`), then run
`uv run scripts/gen_codex_manifests.py`. The existing drift tests fail if
regeneration is skipped; the bump is what makes Codex installs refresh.

### 3. Guard tests (extend `tests/test_plugin_structure.py`)

1. **Relative markdown links resolve:** every `[text](relative/path)` link
   in every SKILL.md must exist on disk (anchors and external URLs
   excluded). Catches the `COMPATIBILITY.md` class of dangling reference.
2. **Dispatchers declare their fallback:** any SKILL.md whose body matches
   the dispatch pattern (`subagent`, `Task tool`/`Task(`, or `dispatch`
   used in the agent sense) must contain the `No-subagent fallback:`
   marker. New dispatching skills cannot merge without one.

### 4. Verification (dry-run comprehension checks)

After editing and version-bumping, refresh the `efitz-skills` marketplace
in Codex from the local checkout and reinstall the edited plugins. For
`dev/dedupe` and `cats/run` (the issue's acceptance pair), run a cheap
`codex exec` with a prompt of the form: "You have no subagent capability.
Read skill X and state, step by step, how you would execute it." Pass =
the stated plan processes batches sequentially inline following the worker
instructions (no invented delegation). Paste both transcripts (or their
relevant excerpts) into a closing comment on #23.

### 5. Audit sweep

One pass over all SKILL.md files for remaining Claude-only assumptions:
`Task(`, Skill-tool invocation syntax, hardcoded `~/.claude/` plugin-cache
paths, claude.ai URLs. Trivial fixes (wording, a path) fold into this
change; anything structural is listed in the #23 closing comment as
explicitly out of scope rather than silently ignored.

## Out of scope

- Full functional runs of dev/cats skills inside Codex (needs prepared
  targets and CLI deps; revisit when naturally using those skills from
  Codex).
- `allowed-tools` changes (analyzed: no correctness dependency).
- Any porting of Claude Code subagent *performance* (parallelism) to
  Codex — the fallback is sequential by design.
