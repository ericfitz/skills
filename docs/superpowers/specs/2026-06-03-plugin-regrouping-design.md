# Plugin regrouping: 16 single-skill plugins → 8 multi-skill plugins

**Date:** 2026-06-03
**Status:** Approved (user waived spec review; proceed to plan + implementation)

## Goal

Consolidate the `efitz-skills` marketplace from 16 single-skill plugins into 8
plugins, grouping related skills under one plugin each and giving skills terse
names. Mirrors the established `deps`/`bump` and `writing`/`boring` pattern
(plugin name ≠ skill name) but at the level of *multiple* skills per plugin.

## Final plugin → skill mapping

| Plugin | Category | Skill (new) | From (old plugin) |
|---|---|---|---|
| **loc** | localization | `analyze` | analyze-localization-files |
| | | `coverage` | validate-localization-coverage |
| | | `detect-nonloc` | detect-non-localizable |
| | | `translate-to` | translate-to-language |
| | | `update-json` | update-json-localization-file |
| | | `validate-translation` | validate-translation |
| | | `backfill` | localization-backfill |
| **security** | security | `vet-plugin` | plugin-vetter |
| | | `race-cond` | race-condition-audit |
| **github** | development | `backlog` | backlog-next |
| | | `file-bug` | file-github-bug |
| **ui** | development | `vrt` | visual-regression-triage |
| **wiki** | documentation | `verify-doc` | verify-migrate-doc |
| **dev** | development | `dedupe` | dedupe |
| **writing** | writing | `boring` | *(unchanged)* |
| **deps** | development | `bump` | *(unchanged — not moved)* |

`writing` and `deps` are already in final form and are NOT touched.

## Conventions

1. **Layout:** `<plugin>/skills/<skill>/SKILL.md`. Move the *nested* skill dir
   (old `X/skills/X/`) to `<plugin>/skills/<newskill>/`. Delete the emptied old
   top-level plugin dir (`.claude-plugin/`, empty `skills/`, `commands/`).
2. **Skill frontmatter:** update `name:` to the new short name. **Descriptions
   stay unchanged** (they drive triggering and remain accurate).
3. **Scripts → plugin-root `scripts/`** (the convention backlog/dedupe/backfill
   already use):
   - `check-i18n.py` is byte-identical in analyze + coverage → collapse to ONE
     `loc/scripts/check-i18n.py`; delete the second copy.
   - `find_duplicate_localizations.py` → `loc/scripts/`.
   - `gh-issues.py` → `github/scripts/` (already plugin-root; moves with plugin).
   - `dedupe-report.py` → `dev/scripts/` (already plugin-root).
4. **Agents:** `dedupe/agents/*` → `dev/agents/*`. Refs
   (`${CLAUDE_PLUGIN_ROOT}/agents/…`) unchanged.
5. **SKILL.md ref edits:**
   - `analyze` + `coverage`: change `${CLAUDE_PLUGIN_ROOT}/skills/<oldskill>/scripts/check-i18n.py`
     → `${CLAUDE_PLUGIN_ROOT}/scripts/check-i18n.py` (and fix the surrounding
     verbose explanatory paragraph that describes the `skills/<skill>/` subpath).
   - All moved skills: in the "typically `~/.claude/plugins/cache/efitz-skills/<oldplugin>/<version>/`"
     example paths, replace `<oldplugin>` with the new plugin name.
   - backlog/dedupe/backfill keep `${CLAUDE_PLUGIN_ROOT}/scripts/…` and
     `/agents/…` (still valid); only update the example plugin name.
6. **Command wrappers dropped:** delete `backlog-next/commands/`,
   `dedupe/commands/`, `localization-backfill/commands/`. Per the `deps`
   precedent, an in-repo wrapper is namespaced (`/dev:dedupe`) and redundant with
   the skill. Bare commands belong in personal `~/.claude/commands`.
7. **plugin.json:** one per new plugin — `name`, `version: 1.0.0`, `description`
   (short summary for multi-skill; mirror the skill for single-skill), `author`.
8. **marketplace.json:** 16 → 8 entries; `source: ./<plugin>`, category per table.
9. **verify-marketplace.sh:** rewrite to validate multi-skill plugins (per-plugin
   skill lists), updated script/agent paths, plugin count 8, no command-wrapper
   section (all dropped).
10. **Root README.md:** replace the per-plugin sections with the new 8-plugin set.

## Inventory facts (verified)

- Bundled scripts: `analyze`/`coverage` → `check-i18n.py` (identical, under skill
  dir); `backlog-next`, `dedupe`, `localization-backfill` → plugin-root `scripts/`.
- Agents: only `dedupe` (3: analyzer/grouper/deduplicator).
- Command wrappers: only `backlog-next`, `dedupe`, `localization-backfill`.
- No scripts/agents/wrappers in: plugin-vetter, race-condition-audit,
  file-github-bug, verify-migrate-doc, visual-regression-triage.

## Implementation strategy

Six independent per-plugin restructure tasks operate on **disjoint** subtrees and
run as parallel subagents doing filesystem `mv` + content edits ONLY (no git
commands, to avoid index-lock races):

- **loc** (largest): 7 skills, 2 scripts (dedup check-i18n), drop backfill wrapper.
- **security**: 2 skills.
- **github**: 2 skills (backlog has script + wrapper to drop), file-bug.
- **ui**: vrt.
- **wiki**: verify-doc.
- **dev**: dedupe (script + 3 agents + wrapper to drop).

Then the orchestrator (single-threaded) does the shared-file work:
marketplace.json (8 entries), verify-marketplace.sh rewrite, root README, then
`git add -A`, run verify-marketplace.sh + smoke checks, fix, commit, push.

## Validation

- `verify-marketplace.sh` → 0 failures (after its rewrite), plugin count 8.
- `git diff --find-renames` shows the moved skill dirs as renames.
- Spot-check: `loc/scripts/check-i18n.py` exists once; analyze+coverage SKILL.md
  reference it at the new path; `dev/agents/dedupe-*.md` present; no
  `*/commands/` dirs remain.

## ~/.claude follow-up (user runs)

Reinstall: `marketplace update efitz-skills`, uninstall the old plugin names,
install the 8 new ones. Orchestrator provides the exact `/plugin` commands.

## Out of scope

- `writing` and `deps` (already final).
- Purging history (done previously).
- Changing skill descriptions/behavior — names and locations only.
