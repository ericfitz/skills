# Codex Marketplace Support — Design

**Date:** 2026-07-30
**Status:** Approved

## Goal

The repo currently works as a Claude Code plugin marketplace
(`.claude-plugin/marketplace.json` + per-plugin `.claude-plugin/plugin.json`).
Make it also installable as a plugin marketplace in OpenAI Codex, consumed by
anyone via the GitHub URL (`ericfitz/skills`), without giving up the Claude
manifests as the single source of truth.

## Background

Codex's plugin system (Codex CLI ≥ ~0.135) mirrors Claude Code's:

- Marketplace catalog locations: `$REPO_ROOT/.agents/plugins/marketplace.json`
  (repo), `~/.agents/plugins/marketplace.json` (personal). A legacy
  compatibility path reads `$REPO_ROOT/.claude-plugin/marketplace.json`, but we
  do not rely on it for the "works for others" guarantee.
- Per-plugin manifest: `.codex-plugin/plugin.json` with `name`, `version`,
  `description`, `author`, and a `skills` path field.
- Marketplace entries use structured sources; for a repo-hosted marketplace,
  `{"source": "local", "path": "./<dir>"}` resolves inside the clone when the
  marketplace is added by git URL.
- Hooks/scripts receive `CLAUDE_PLUGIN_ROOT` / `CLAUDE_PLUGIN_DATA` as
  compatibility aliases, so the many `${CLAUDE_PLUGIN_ROOT}` references in
  SKILL.md files keep working.
- Codex has no subagent equivalent; `agents/*.md` in the `dev` and `cats`
  plugins is ignored there. Decision: graceful degradation now (skills work,
  subagent dispatch instructions execute inline), with a follow-up GitHub
  issue for full-parity rework of Claude-specific skill content.

## Design

### Generated files (committed)

Source of truth is unchanged: `.claude-plugin/marketplace.json` and each
plugin's `.claude-plugin/plugin.json`. From those, a generator emits:

1. `.agents/plugins/marketplace.json` — Codex-native catalog.
   - Marketplace `name`: `efitz-skills` (unchanged).
   - One entry per plugin: `name`, `category`, and
     `"source": {"source": "local", "path": "./<plugin-dir>"}`.
   - Only documented fields; no `policy` or other extras.
2. `<plugin>/.codex-plugin/plugin.json` (one per plugin, 12 today) —
   `name`, `version`, `description`, `author` copied from the Claude manifest,
   plus `"skills": "./skills/"`.

Claude Code ignores both additions. Both files are committed (no build step at
install time); the generator is rerun when plugins change.

### Generator

`scripts/gen_codex_manifests.py`, invoked as
`uv run scripts/gen_codex_manifests.py`. Matches repo tooling conventions
(non-package uv project, ruff as sole linter).

- Reads the Claude marketplace and per-plugin manifests.
- Emits the Codex files with stable formatting: 2-space indent, trailing
  newline, deterministic key order — so regeneration is diff-clean.
- Fails loudly (non-zero exit, clear message) on:
  - a marketplace entry whose plugin dir lacks `.claude-plugin/plugin.json`;
  - a plugin without a `skills/` directory;
  - duplicate plugin names.
- `--check` flag: regenerate in memory, compare against committed files, exit
  non-zero on drift, write nothing.

### Testing / CI

New `tests/test_codex_manifests.py`, in the style of
`test_plugin_structure.py`:

- `.agents/plugins/marketplace.json` and every `.codex-plugin/plugin.json`
  exist, parse as JSON, and exactly match a fresh regeneration (drift check).
- Every Claude marketplace entry has a Codex counterpart and vice versa.
- Each Codex `plugin.json`'s `skills` path exists on disk.

`scripts/verify-marketplace.sh` fixes: derive the expected plugin count from
`marketplace.json` instead of the stale hardcoded 9, and invoke the
generator's `--check` so the shell check also catches drift.

### End-to-end verification

Structural checks are necessary but not sufficient; verify in real Codex:

1. Locate or install the Codex CLI (binary not currently on PATH).
2. `/plugin marketplace add` the GitHub repo (`ericfitz/skills`).
3. Install one plugin (`loc`); confirm its skills appear via `/skills` and one
   triggers.
4. Anything Codex rejects is fixed in the generator, never by hand-editing
   generated output.

### Follow-up

File a GitHub issue (via the `github:create-issue` flow) to rework
Claude-specific skill content for full Codex parity: subagent dispatch
instructions, `allowed-tools` frontmatter, and any Task-tool assumptions.

## Out of scope

- Rewriting SKILL.md content for Codex (follow-up issue).
- Codex `hooks/`, `.mcp.json`, `.app.json`, `interface` metadata — no plugin
  here uses them.
- Publishing to any curated/official Codex plugin directory.
