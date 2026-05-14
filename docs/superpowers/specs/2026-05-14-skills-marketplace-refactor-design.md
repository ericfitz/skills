# Skills Marketplace Refactor — Design Spec

**Date:** 2026-05-14
**Status:** Draft for review
**Author:** efitz (with Claude)

## Summary

Convert `~/.claude/agents/` and `~/.claude/commands/` artifacts into Claude Code skills, and reshape `~/Projects/skills/` from a flat collection of skill directories into a **Claude Code plugin marketplace**. Each existing skill becomes its own plugin; the three commands (`bump`, `dedupe`, `backlog-next`) plus the legacy `commands/localization-backfill.md` become four new plugins, each containing a skill, a thin command wrapper, and (for `dedupe`) bundled worker agents.

After the refactor:
- `~/Projects/skills/` is a marketplace listing every plugin via `.claude-plugin/marketplace.json`.
- Every artifact at the repo root is a plugin: `<plugin>/.claude-plugin/plugin.json` + `<plugin>/skills/<name>/SKILL.md`.
- Users install with `/plugin install <name>@efitz-skills`.
- The original `~/.claude/commands/*.md`, `~/.claude/agents/dedupe-*.md`, and `~/.claude/scripts/{gh-issues,dedupe-report}.py` are deleted after each new plugin passes smoke-test.

## Motivation

The user maintains three flavors of Claude Code customization scattered across `~/.claude/`: commands, agents, and a separate `~/Projects/skills/` repo. The skills repo is a flat directory of `<name>/SKILL.md` files — not distributable via Claude Code's plugin system. Goals:

1. Unify everything as plugins so each artifact is installable via `/plugin install`.
2. Preserve the slash-command UX (e.g., `/bump python` continues to work).
3. Bundle worker agents alongside the skill that owns them, instead of having them live in a shared `~/.claude/agents/` directory.
4. Make the skills repo a marketplace others can subscribe to.

## Non-Goals

- Rewriting any skill or command logic. This is a packaging refactor.
- Migrating logic between skills. Each artifact stays internally the same.
- Adding hooks, MCP servers, or other plugin features beyond what the source artifacts already do.
- Publishing the marketplace to a remote URL. Local-path install (`/plugin marketplace add /path/to/skills`) is sufficient.
- Versioning policy beyond starting every plugin at `1.0.0`.

## Current State

### `~/.claude/agents/`
Three programmatic worker agents dispatched by the dedupe command via the Agent tool with templated parameters:
- `dedupe-analyzer.md`
- `dedupe-deduplicator.md`
- `dedupe-grouper.md`

### `~/.claude/commands/`
Three slash commands:
- `backlog-next.md` — picks next GitHub issue based on milestone, priority, exclusion rules
- `bump.md` — auto-updates safe dependencies across Go/Python/Node
- `dedupe.md` — orchestrates the 3 worker agents to find duplicate code

### `~/.claude/scripts/`
Supporting scripts referenced by commands:
- `gh-issues.py` — used by `backlog-next`
- `dedupe-report.py` — used by `dedupe`

### `~/Projects/skills/`
Flat layout, 12 existing skills:
- `boring/` — non-standard, SKILL.md at `src/SKILL.md`, plus `tools/`, `calibration/`, `samples/`, `docs/`, `dist/`
- `plugin-vetter/`, `race-condition-audit/` — flat with `<name>/SKILL.md` and optional `references/` or `scripts/`
- 8 localization-related skills (`analyze-localization-files`, `detect-non-localizable`, `translate-to-language`, `update-json-localization-file`, `validate-localization-coverage`, `validate-translation`, plus `file-github-bug`, `verify-migrate-doc`, `visual-regression-triage`)
- `commands/localization-backfill.md` and `commands/localization-backfill.scripts/` — leftover command-style content in the repo

## End-State Repository Layout

```
~/Projects/skills/                                    # marketplace root
├── .claude-plugin/
│   └── marketplace.json                              # NEW: lists ALL plugins
├── README.md                                         # updated
│
├── bump/                                             # NEW (command→plugin)
│   ├── .claude-plugin/plugin.json
│   ├── skills/bump/SKILL.md
│   └── commands/bump.md
├── dedupe/                                           # NEW (command + 3 workers)
│   ├── .claude-plugin/plugin.json
│   ├── skills/dedupe/SKILL.md
│   ├── commands/dedupe.md
│   ├── agents/
│   │   ├── dedupe-analyzer.md
│   │   ├── dedupe-grouper.md
│   │   └── dedupe-deduplicator.md
│   └── scripts/dedupe-report.py
├── backlog-next/                                     # NEW
│   ├── .claude-plugin/plugin.json
│   ├── skills/backlog-next/SKILL.md
│   ├── commands/backlog-next.md
│   └── scripts/gh-issues.py
├── localization-backfill/                            # NEW (from repo's commands/)
│   ├── .claude-plugin/plugin.json
│   ├── skills/localization-backfill/SKILL.md
│   ├── commands/localization-backfill.md
│   └── scripts/ (contents of localization-backfill.scripts/)
│
├── boring/                                           # RESHAPED
│   ├── .claude-plugin/plugin.json
│   ├── README.md
│   └── skills/boring/
│       ├── SKILL.md   (was src/SKILL.md)
│       ├── tools/
│       ├── calibration/
│       ├── samples/
│       ├── docs/
│       └── dist/
├── plugin-vetter/                                    # RESHAPED
│   ├── .claude-plugin/plugin.json
│   └── skills/plugin-vetter/SKILL.md
├── race-condition-audit/                             # RESHAPED
│   ├── .claude-plugin/plugin.json
│   └── skills/race-condition-audit/
│       ├── SKILL.md
│       └── references/
├── analyze-localization-files/                       # RESHAPED
│   ├── .claude-plugin/plugin.json
│   └── skills/analyze-localization-files/
│       ├── SKILL.md
│       └── scripts/
├── detect-non-localizable/                           # RESHAPED (analogous)
├── translate-to-language/                            # RESHAPED
├── update-json-localization-file/                    # RESHAPED
├── validate-localization-coverage/                   # RESHAPED
├── validate-translation/                             # RESHAPED
├── file-github-bug/                                  # RESHAPED
├── verify-migrate-doc/                               # RESHAPED
└── visual-regression-triage/                         # RESHAPED
```

The leftover `commands/` dir at the repo root is removed once `localization-backfill` is migrated.

## Plugin Anatomy

### `plugin.json` (every plugin)

```json
{
  "name": "<plugin-name>",
  "version": "1.0.0",
  "description": "<from existing SKILL.md frontmatter>",
  "author": { "name": "efitz" }
}
```

The `description` field is copied verbatim from the existing skill's frontmatter `description:` so marketplace listings match what the skill says about itself. Plugin `name` equals the directory name.

### `marketplace.json`

At `~/Projects/skills/.claude-plugin/marketplace.json`:

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "efitz-skills",
  "description": "efitz's personal Claude Code skills, commands, and tools",
  "owner": { "name": "efitz" },
  "plugins": [
    { "name": "bump",                          "description": "...", "source": "./bump",                          "category": "development" },
    { "name": "dedupe",                        "description": "...", "source": "./dedupe",                        "category": "development" },
    { "name": "backlog-next",                  "description": "...", "source": "./backlog-next",                  "category": "development" },
    { "name": "localization-backfill",         "description": "...", "source": "./localization-backfill",         "category": "localization" },
    { "name": "boring",                        "description": "...", "source": "./boring",                        "category": "writing" },
    { "name": "plugin-vetter",                 "description": "...", "source": "./plugin-vetter",                 "category": "security" },
    { "name": "race-condition-audit",          "description": "...", "source": "./race-condition-audit",          "category": "security" },
    { "name": "analyze-localization-files",    "description": "...", "source": "./analyze-localization-files",    "category": "localization" },
    { "name": "detect-non-localizable",        "description": "...", "source": "./detect-non-localizable",        "category": "localization" },
    { "name": "translate-to-language",         "description": "...", "source": "./translate-to-language",         "category": "localization" },
    { "name": "update-json-localization-file", "description": "...", "source": "./update-json-localization-file", "category": "localization" },
    { "name": "validate-localization-coverage","description": "...", "source": "./validate-localization-coverage","category": "localization" },
    { "name": "validate-translation",          "description": "...", "source": "./validate-translation",          "category": "localization" },
    { "name": "file-github-bug",               "description": "...", "source": "./file-github-bug",               "category": "misc" },
    { "name": "verify-migrate-doc",            "description": "...", "source": "./verify-migrate-doc",            "category": "misc" },
    { "name": "visual-regression-triage",      "description": "...", "source": "./visual-regression-triage",      "category": "misc" }
  ]
}
```

Local-path `source` entries because every plugin lives in the same repo as the marketplace metadata. Categories chosen to mirror conventions seen in Anthropic's official marketplace. The `"..."` descriptions above are visual placeholders — at implementation time each is replaced with the verbatim `description:` field from the corresponding skill's frontmatter (same string used in that plugin's `plugin.json`).

### Command wrapper (the 4 command→skill plugins)

`<plugin>/commands/<name>.md`:

```markdown
---
description: <one-line, shown in /help>
---

Invoke the `<plugin-name>:<skill-name>` skill with these arguments: $ARGUMENTS
```

The wrapper has no duplicated logic. The model reads the wrapper, calls the Skill tool with the fully-qualified skill name and the user's arguments, and the skill body does the work.

### Skill conversion (the 4 command→skill plugins)

The new `skills/<name>/SKILL.md` is the existing command body with three modifications:

1. **Frontmatter.** Add `name:`, `description:`, `version:`. The `description:` is what makes the skill auto-trigger when the user phrases a request without using the slash command. Crafted to match the surface area of the command's job. Example for bump:

   > "Update dependencies safely across Go/Python/Node ecosystems. Use when the user asks to bump deps, update packages, fix Dependabot alerts, or run a dependency upgrade. Accepts optional ecosystem hint (go/python/node)."

2. **`$ARGUMENTS` parsing → natural-language parsing.** The existing commands have a "Phase 0: Parse Arguments" section that branches on `$ARGUMENTS`. In the skill body, this becomes guidance for the model to infer the same choices from the user's request: *"If the user's request mentions a specific ecosystem (go, python/py, node/npm/pnpm/js/ts), target that ecosystem only. If the user says 'clean', perform the clean operation. Otherwise auto-detect."* When invoked through the command wrapper, `$ARGUMENTS` is passed as the skill's `args` and the skill parses it the same way.

3. **Script paths.** References to `~/.claude/scripts/gh-issues.py` and `~/.claude/scripts/dedupe-report.py` are rewritten as `${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py` and `${CLAUDE_PLUGIN_ROOT}/scripts/dedupe-report.py`. This matches the convention used by Anthropic's official `ralph-loop` plugin and works regardless of where the plugin is installed.

The rest of the command body — process steps, exclusion rules, output formats, etc. — is copied verbatim.

### Worker agents (dedupe plugin only)

The 3 worker agent files move from `~/.claude/agents/dedupe-*.md` to `dedupe/agents/dedupe-*.md`. Frontmatter (`name:`, `description:`, `tools:`, `model:`) is unchanged. The dedupe skill body already calls them by their declared `name:` (e.g., `subagent_type: "Duplicate Candidate Grouper"`), so no skill-side changes are required.

When the `dedupe` plugin is installed, Claude Code registers these agents under their declared names and they become dispatchable via the Agent tool exactly as today.

## Reshape Procedure for Existing Skills

For each of the 12 existing skill directories, the reshape is mechanical:

**Case A — flat layout (11 skills):**
- Current: `<name>/SKILL.md` plus optional `<name>/references/`, `<name>/scripts/`.
- Target: `<name>/.claude-plugin/plugin.json` + `<name>/skills/<name>/SKILL.md` + `<name>/skills/<name>/references/` etc.
- Steps:
  1. `mkdir -p <name>/.claude-plugin <name>/skills/<name>`
  2. `git mv <name>/SKILL.md <name>/skills/<name>/SKILL.md`
  3. For each supporting subdir: `git mv <name>/<dir> <name>/skills/<name>/<dir>`
  4. Write `<name>/.claude-plugin/plugin.json` with name/version/description.

**Case B — `boring` (non-standard):**
- Current: `boring/src/SKILL.md` + `boring/{tools,calibration,samples,docs,dist}/`
- Target: `boring/.claude-plugin/plugin.json` + `boring/skills/boring/SKILL.md` + `boring/skills/boring/{tools,calibration,samples,docs,dist}/`
- Steps:
  1. `mkdir -p boring/.claude-plugin boring/skills/boring`
  2. `git mv boring/src/SKILL.md boring/skills/boring/SKILL.md`
  3. `git mv boring/{tools,calibration,samples,docs,dist} boring/skills/boring/`
  4. `rmdir boring/src` (now empty)
  5. Write plugin.json. Leave `boring/README.md` at the plugin root.
  6. Check `SKILL.md` for any relative path references to moved dirs; update if needed.

**Skill content is not modified.** Frontmatter stays as-is. Body stays as-is. Only directory structure changes.

## Cutover Plan

The cutover is per-plugin and reversible until originals are deleted:

1. **Phase A — repo refactor (no user-facing impact yet):**
   - Reshape all 12 existing skills (Cases A & B above).
   - Write all 16 `plugin.json` files (12 reshaped + 4 new).
   - Write `marketplace.json`.
   - Commit. The repo is now a marketplace, but nothing is installed from it yet.

2. **Phase B — new plugin construction:**
   - Build `bump`, `dedupe`, `backlog-next`, `localization-backfill` plugins.
   - Copy the relevant scripts into each plugin's `scripts/` dir.
   - For `dedupe`: copy the 3 worker agents into `dedupe/agents/`.
   - Write command wrappers.
   - Convert command bodies to skill bodies (rewrite frontmatter, `$ARGUMENTS` parsing, script paths).
   - Commit.

3. **Phase C — install and smoke-test:**
   - `/plugin marketplace add /Users/efitz/Projects/skills`
   - For each new plugin: `/plugin install <name>@efitz-skills`, then smoke-test (`/bump python`, `/dedupe`, `/backlog-next`, `/localization-backfill` if applicable).
   - For the 12 existing plugins: `/plugin install <name>@efitz-skills` and verify the skill auto-triggers as before.

4. **Phase D — delete originals (only after Phase C passes):**
   - `git rm ~/.claude/commands/{bump,dedupe,backlog-next}.md`
   - `git rm ~/.claude/agents/dedupe-*.md`
   - `git rm ~/.claude/scripts/{gh-issues,dedupe-report}.py`
   - Decide whether `~/.claude/skills/` copies of existing skills should also be removed (they'll now be served from the installed plugins).

## Risks and Mitigations

- **Risk:** `${CLAUDE_PLUGIN_ROOT}` substitution might behave differently in skill bodies vs. command bodies. (Confirmed working in `ralph-loop`'s command file.)
  - **Mitigation:** Smoke-test each new plugin's scripts before deleting originals.
- **Risk:** Plugin-scoped skill names (`plugin-name:skill-name`) might not match what the user expects when typing in the chat. Anthropic's official plugins use this format (e.g., `ralph-loop:ralph-loop`).
  - **Mitigation:** Skills auto-trigger from their description regardless of qualified name; the qualified name only matters for the wrapper's `Skill` tool invocation.
- **Risk:** Reshape moves break relative paths inside existing skill bodies that reference their own `scripts/` or `references/` subdirs.
  - **Mitigation:** Per-skill grep for relative-path references after the move; update to `${CLAUDE_PLUGIN_ROOT}/...` form if found.
- **Risk:** Two copies of a skill (one in `~/.claude/skills/`, one served by the installed plugin) could cause confusion or conflicting auto-trigger behavior.
  - **Mitigation:** Phase D explicitly decides whether to delete the `~/.claude/skills/` copies. Default: delete, since the plugin install supersedes them.

## Open Questions

None remaining. Q1 (localization-backfill placement) resolved as its own plugin. Q2 (script path strategy) resolved as `${CLAUDE_PLUGIN_ROOT}`.
