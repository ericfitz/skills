# Skills Marketplace Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert `~/.claude/commands/{bump,dedupe,backlog-next}.md`, the `dedupe-*` worker agents, and the in-repo `commands/localization-backfill.md` into four Claude Code plugins; reshape the 12 existing skill directories into plugins; turn `~/Projects/skills/` into a marketplace listing all 16 plugins.

**Architecture:** Each plugin is a self-contained directory with `.claude-plugin/plugin.json` plus `skills/<name>/SKILL.md`. The 4 command→skill plugins also include a thin `commands/<name>.md` wrapper that forwards `$ARGUMENTS` to the Skill tool. The dedupe plugin additionally bundles 3 worker agents under `agents/`. Scripts referenced by skill bodies are bundled in the plugin and addressed via `${CLAUDE_PLUGIN_ROOT}`. A single `.claude-plugin/marketplace.json` at the repo root advertises all 16 plugins via local-path `source` entries.

**Tech Stack:** Claude Code plugin format (`.claude-plugin/{plugin,marketplace}.json`), shell, git.

---

## Reference Material

### Source artifacts (read-only inputs)

- `/Users/efitz/.claude/commands/bump.md` (819 lines)
- `/Users/efitz/.claude/commands/dedupe.md` (966 lines)
- `/Users/efitz/.claude/commands/backlog-next.md` (128 lines)
- `/Users/efitz/.claude/agents/dedupe-analyzer.md`
- `/Users/efitz/.claude/agents/dedupe-deduplicator.md`
- `/Users/efitz/.claude/agents/dedupe-grouper.md`
- `/Users/efitz/.claude/scripts/gh-issues.py`
- `/Users/efitz/.claude/scripts/dedupe-report.py`
- `/Users/efitz/Projects/skills/commands/localization-backfill.md` (214 lines)
- `/Users/efitz/Projects/skills/commands/localization-backfill.scripts/find_duplicate_localizations.py`

### Plugin format references

- `${CLAUDE_PLUGIN_ROOT}` — env var auto-injected by Claude Code, resolves to the installed plugin's absolute path. Documented in `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/plugin-dev/skills/command-development/SKILL.md:562-603`. Example use in `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/commands/ralph-loop.md`.
- Marketplace schema example: `~/.claude/plugins/marketplaces/claude-plugins-official/.claude-plugin/marketplace.json`
- Plugin.json example: `~/.claude/plugins/marketplaces/claude-plugins-official/plugins/ralph-loop/.claude-plugin/plugin.json`

### Pre-extracted skill descriptions (use verbatim in plugin.json + marketplace.json)

| Plugin | Description (verbatim from existing frontmatter, single-line) |
|---|---|
| `boring` | Evaluate technical business writing for "boringness" across 20 sub-dimensions on four axes (Direction, Density, Texture, Surprise). Combines a mechanical analyzer (15 sub-dimensions, deterministic, runs as a Python script) with five LLM-judged sub-dimensions that require semantic judgment. Use when the user asks to review a document for engagement, clarity, or "is this boring", or for prose-mechanics issues in technical writing. |
| `plugin-vetter` | Security-first plugin vetting for AI agents. Use before installing any plugin (skill, plugin, command, etc.) from any Marketplace, GitHub, or other sources. Checks for red flags, permission scope, and suspicious patterns. |
| `race-condition-audit` | Systematic identification of race conditions, concurrency bugs, and thread-safety issues across codebases. Use when asked to find race conditions, audit concurrent code, debug non-deterministic behavior, review thread safety, find data races, or analyze async/parallel code. Supports TypeScript, JavaScript, Python, Go, Rust, C++, Java, and Kotlin. |
| `analyze-localization-files` | Use when building a translation task manifest for an i18n project — produces per-language lists of missing keys with their source values by running the bundled check-i18n.py script. |
| `detect-non-localizable` | Use when filtering localization keys, validating translation files, or deciding whether a string value should be translated or left as-is. Returns a boolean and the matched pattern. |
| `file-github-bug` | Use when filing a detailed bug report against a GitHub repo with evidence, optionally adding it to a GitHub Project (v2), setting milestone from current branch, and marking initial status. Reads repo/project metadata from .local-projects.json so the skill is repo-agnostic. |
| `translate-to-language` | Use when translating UI strings, i18n values, or short localized content into a specific target language while preserving placeholders, formatting, capitalization, and tone. |
| `update-json-localization-file` | Use when modifying a JSON i18n file with additions, updates, or deletions while preserving formatting and writing atomically. |
| `validate-localization-coverage` | Use when auditing i18n translation completeness across all target locales or identifying locales below a coverage threshold. Produces a per-locale and summary coverage report. |
| `validate-translation` | Use when reviewing a translated string or validating an i18n file update, to verify placeholder preservation, length, encoding, and common translation errors. |
| `verify-migrate-doc` | Use when asked to verify a documentation file's accuracy against source code and external references, then migrate it into a project wiki. Reads target repo and wiki path from .local-projects.json. |
| `visual-regression-triage` | Use when a Playwright visual regression test fails (screenshot mismatch) or a user mentions a screenshot test failure. Presents baseline, actual, and diff images framed against the current task context, then helps the user decide bug vs. expected change. |
| `localization-backfill` | Translate every missing or untranslated key across all i18n locale files using the master locale as the source. Tool-agnostic; reads project i18n configuration. |

Descriptions for the 3 new command-derived plugins (write fresh, model these on the existing ones):

| Plugin | New description |
|---|---|
| `bump` | Update dependencies safely across Go/Python/Node ecosystems. Use when the user asks to bump deps, update packages, fix Dependabot alerts, or run a dependency upgrade. Detects ecosystems, applies safe updates with build/test/lint validation, and surfaces a plan for packages that need manual review. |
| `dedupe` | Find and analyze duplicate or overlapping functionality across a codebase. Use when the user asks to dedupe, find duplicate code, look for redundant functions, or audit for code duplication. Supports Go, Python, and TypeScript. Orchestrates per-file analysis, candidate grouping, and deep comparison through a shared SQLite database. |
| `backlog-next` | Pick the next GitHub issue to work on. Use when the user asks what to work on next, requests the next backlog item, or wants an issue prioritized for the current milestone. Fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one. |

### Categories used in marketplace.json

| Plugin | Category |
|---|---|
| bump, dedupe, backlog-next | `development` |
| plugin-vetter, race-condition-audit | `security` |
| boring | `writing` |
| analyze-localization-files, detect-non-localizable, translate-to-language, update-json-localization-file, validate-localization-coverage, validate-translation, localization-backfill | `localization` |
| file-github-bug, verify-migrate-doc, visual-regression-triage | `misc` |

### Known body-content rewrites required after reshape/conversion

These are existing references that will break unless rewritten:

| File | Current | Rewrite to |
|---|---|---|
| `analyze-localization-files/SKILL.md:76` | `uv run "$SKILL_DIR/scripts/check-i18n.py" -y` | `uv run "${CLAUDE_PLUGIN_ROOT}/skills/analyze-localization-files/scripts/check-i18n.py" -y` |
| `validate-localization-coverage/SKILL.md:66` | `uv run "$SKILL_DIR/scripts/check-i18n.py" -y` | `uv run "${CLAUDE_PLUGIN_ROOT}/skills/validate-localization-coverage/scripts/check-i18n.py" -y` |
| `commands/localization-backfill.md:43` | `uv run "$COMMAND_DIR/localization-backfill.scripts/find_duplicate_localizations.py" \` | `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/find_duplicate_localizations.py" \` |
| `commands/localization-backfill.md:14` | `localization-backfill.scripts/find_duplicate_localizations.py` (descriptive text) | `scripts/find_duplicate_localizations.py` |
| `boring/src/SKILL.md:279,298` | self-references to `src/` layout | update to reflect new `skills/boring/` layout (or delete if stale dev-only docs) |
| `bump.md`, `dedupe.md`, `backlog-next.md` | `$ARGUMENTS` literal | the skill version parses intent from natural language; the command wrapper keeps `$ARGUMENTS` |
| `backlog-next.md:16,92` | `python3 ~/.claude/scripts/gh-issues.py` | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py` |
| `dedupe.md` (any references) | `~/.claude/scripts/dedupe-report.py` | `${CLAUDE_PLUGIN_ROOT}/scripts/dedupe-report.py` |

`race-condition-audit`'s `references/<lang>.md` relative links are safe — that directory moves intact into `skills/race-condition-audit/references/`.

---

## File Structure (end-state at `~/Projects/skills/`)

Per the spec. Sixteen plugin directories at the repo root, each with `.claude-plugin/plugin.json` and a `skills/<name>/SKILL.md`. Four also have `commands/<name>.md` wrappers and `scripts/` (and `dedupe` has `agents/`). One `.claude-plugin/marketplace.json` at the repo root.

---

## Phases overview

- **Phase A — Marketplace scaffolding** (Tasks 1–2): create the marketplace.json, ready the repo to advertise plugins.
- **Phase B — Reshape existing simple skills** (Tasks 3–13): 11 flat-layout skills.
- **Phase C — Reshape boring** (Task 14): the non-standard one.
- **Phase D — Build the 4 new plugins** (Tasks 15–18): one task per new plugin.
- **Phase E — Wire marketplace, install, smoke-test** (Tasks 19–22).
- **Phase F — Cutover: delete originals** (Tasks 23–24).

Each task is independently committable. No test framework is involved — verification is structural (files exist, JSON parses) and functional (plugin installs, command/skill triggers). The "test" for each task is `command runs and produces expected output."

---

## Task 1: Initialize marketplace metadata

**Files:**
- Create: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

This task creates the marketplace shell with an empty `plugins: []` array. Subsequent reshape and build tasks append their plugin to this array. We initialize empty so each per-plugin task can be verified independently.

- [ ] **Step 1: Create the .claude-plugin directory**

```bash
mkdir -p /Users/efitz/Projects/skills/.claude-plugin
```

- [ ] **Step 2: Write marketplace.json with empty plugin list**

Write `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`:

```json
{
  "$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "efitz-skills",
  "description": "efitz's personal Claude Code skills, commands, and tools",
  "owner": { "name": "efitz" },
  "plugins": []
}
```

- [ ] **Step 3: Verify JSON parses**

Run: `python3 -c "import json; json.load(open('/Users/efitz/Projects/skills/.claude-plugin/marketplace.json'))"`
Expected: exits cleanly with no output.

- [ ] **Step 4: Commit**

```bash
cd /Users/efitz/Projects/skills
git add .claude-plugin/marketplace.json
git commit -m "feat(marketplace): initialize empty marketplace.json"
```

---

## Task 2: Helper — define the reshape and append routine

This task is documentation, not code. Future reshape tasks (Tasks 3–13) follow the exact same pattern. Read this once; then each per-skill task is short.

**Standard reshape procedure for a flat-layout skill `<NAME>`:**

1. `mkdir -p <NAME>/.claude-plugin <NAME>/skills/<NAME>`
2. `cd <NAME> && git mv SKILL.md skills/<NAME>/SKILL.md`
3. For each existing subdir at `<NAME>/<DIR>` (e.g., `scripts/`, `references/`): `git mv <DIR> skills/<NAME>/<DIR>`
4. Apply any body-content rewrites listed in the Reference Material table.
5. Write `<NAME>/.claude-plugin/plugin.json`:

   ```json
   {
     "name": "<NAME>",
     "version": "1.0.0",
     "description": "<DESCRIPTION from the table above>",
     "author": { "name": "efitz" }
   }
   ```

6. Append a plugin entry to `marketplace.json`'s `plugins` array:

   ```json
   { "name": "<NAME>", "description": "<DESCRIPTION>", "source": "./<NAME>", "category": "<CATEGORY>" }
   ```

7. Verify with:
   ```bash
   test -f <NAME>/.claude-plugin/plugin.json
   test -f <NAME>/skills/<NAME>/SKILL.md
   python3 -c "import json; json.load(open('<NAME>/.claude-plugin/plugin.json'))"
   python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
   ```

8. Commit:
   ```bash
   git add <NAME>/ .claude-plugin/marketplace.json
   git commit -m "feat(<NAME>): reshape to plugin layout"
   ```

No checkbox steps for this task — it's a reference for tasks below.

---

## Task 3: Reshape `plugin-vetter`

**Files:**
- Modify: `/Users/efitz/Projects/skills/plugin-vetter/` (move SKILL.md into `skills/plugin-vetter/`)
- Create: `/Users/efitz/Projects/skills/plugin-vetter/.claude-plugin/plugin.json`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

Simplest case — `plugin-vetter/` contains only `SKILL.md`.

- [ ] **Step 1: Make new directories**

```bash
cd /Users/efitz/Projects/skills
mkdir -p plugin-vetter/.claude-plugin plugin-vetter/skills/plugin-vetter
```

- [ ] **Step 2: Move SKILL.md**

```bash
cd /Users/efitz/Projects/skills/plugin-vetter
git mv SKILL.md skills/plugin-vetter/SKILL.md
```

- [ ] **Step 3: Write plugin.json**

Write `/Users/efitz/Projects/skills/plugin-vetter/.claude-plugin/plugin.json`:

```json
{
  "name": "plugin-vetter",
  "version": "1.0.0",
  "description": "Security-first plugin vetting for AI agents. Use before installing any plugin (skill, plugin, command, etc.) from any Marketplace, GitHub, or other sources. Checks for red flags, permission scope, and suspicious patterns.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 4: Append to marketplace.json**

Edit `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json` — replace `"plugins": []` with:

```json
"plugins": [
  { "name": "plugin-vetter", "description": "Security-first plugin vetting for AI agents. Use before installing any plugin (skill, plugin, command, etc.) from any Marketplace, GitHub, or other sources. Checks for red flags, permission scope, and suspicious patterns.", "source": "./plugin-vetter", "category": "security" }
]
```

- [ ] **Step 5: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f plugin-vetter/.claude-plugin/plugin.json && test -f plugin-vetter/skills/plugin-vetter/SKILL.md && echo OK
python3 -c "import json; json.load(open('plugin-vetter/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
```

Expected: `OK` printed, both python commands exit with no output.

- [ ] **Step 6: Commit**

```bash
cd /Users/efitz/Projects/skills
git add plugin-vetter/ .claude-plugin/marketplace.json
git commit -m "feat(plugin-vetter): reshape to plugin layout"
```

---

## Task 4: Reshape `race-condition-audit`

**Files:**
- Modify: `/Users/efitz/Projects/skills/race-condition-audit/` (move SKILL.md and references/ into `skills/race-condition-audit/`)
- Create: `/Users/efitz/Projects/skills/race-condition-audit/.claude-plugin/plugin.json`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

Same pattern as Task 3, but also moves the `references/` subdir.

- [ ] **Step 1: Make new directories**

```bash
cd /Users/efitz/Projects/skills
mkdir -p race-condition-audit/.claude-plugin race-condition-audit/skills/race-condition-audit
```

- [ ] **Step 2: Move SKILL.md and references/**

```bash
cd /Users/efitz/Projects/skills/race-condition-audit
git mv SKILL.md skills/race-condition-audit/SKILL.md
git mv references skills/race-condition-audit/references
```

- [ ] **Step 3: Verify references/ links still resolve**

Run: `grep -n "references/" /Users/efitz/Projects/skills/race-condition-audit/skills/race-condition-audit/SKILL.md`
Expected: lines reference `references/<lang>.md` — these are relative to SKILL.md and remain valid since references/ moved with it.

- [ ] **Step 4: Write plugin.json**

Write `/Users/efitz/Projects/skills/race-condition-audit/.claude-plugin/plugin.json`:

```json
{
  "name": "race-condition-audit",
  "version": "1.0.0",
  "description": "Systematic identification of race conditions, concurrency bugs, and thread-safety issues across codebases. Use when asked to find race conditions, audit concurrent code, debug non-deterministic behavior, review thread safety, find data races, or analyze async/parallel code. Supports TypeScript, JavaScript, Python, Go, Rust, C++, Java, and Kotlin.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 5: Append to marketplace.json**

Edit `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json` — append a new entry to the `plugins` array (after the `plugin-vetter` entry, comma-separated):

```json
{ "name": "race-condition-audit", "description": "Systematic identification of race conditions, concurrency bugs, and thread-safety issues across codebases. Use when asked to find race conditions, audit concurrent code, debug non-deterministic behavior, review thread safety, find data races, or analyze async/parallel code. Supports TypeScript, JavaScript, Python, Go, Rust, C++, Java, and Kotlin.", "source": "./race-condition-audit", "category": "security" }
```

- [ ] **Step 6: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f race-condition-audit/.claude-plugin/plugin.json && test -f race-condition-audit/skills/race-condition-audit/SKILL.md && test -d race-condition-audit/skills/race-condition-audit/references && echo OK
python3 -c "import json; json.load(open('race-condition-audit/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
```

Expected: `OK` printed, both python commands exit cleanly.

- [ ] **Step 7: Commit**

```bash
cd /Users/efitz/Projects/skills
git add race-condition-audit/ .claude-plugin/marketplace.json
git commit -m "feat(race-condition-audit): reshape to plugin layout"
```

---

## Task 5: Reshape `analyze-localization-files` (includes path rewrite)

**Files:**
- Modify: `/Users/efitz/Projects/skills/analyze-localization-files/` (move SKILL.md and scripts/ into `skills/analyze-localization-files/`)
- Modify: `/Users/efitz/Projects/skills/analyze-localization-files/skills/analyze-localization-files/SKILL.md` (path rewrite)
- Create: `/Users/efitz/Projects/skills/analyze-localization-files/.claude-plugin/plugin.json`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

Reshape PLUS rewrite the `$SKILL_DIR` reference to `${CLAUDE_PLUGIN_ROOT}/skills/analyze-localization-files`.

- [ ] **Step 1: Make new directories and move files**

```bash
cd /Users/efitz/Projects/skills
mkdir -p analyze-localization-files/.claude-plugin analyze-localization-files/skills/analyze-localization-files
cd analyze-localization-files
git mv SKILL.md skills/analyze-localization-files/SKILL.md
git mv scripts skills/analyze-localization-files/scripts
```

- [ ] **Step 2: Rewrite `$SKILL_DIR` references in SKILL.md**

In `/Users/efitz/Projects/skills/analyze-localization-files/skills/analyze-localization-files/SKILL.md`, replace every occurrence of:
```
$SKILL_DIR
```
with:
```
${CLAUDE_PLUGIN_ROOT}/skills/analyze-localization-files
```

Verify: `grep -n "SKILL_DIR\|CLAUDE_PLUGIN_ROOT" /Users/efitz/Projects/skills/analyze-localization-files/skills/analyze-localization-files/SKILL.md` should show only `CLAUDE_PLUGIN_ROOT` lines, no `$SKILL_DIR` remaining.

- [ ] **Step 3: Write plugin.json**

Write `/Users/efitz/Projects/skills/analyze-localization-files/.claude-plugin/plugin.json`:

```json
{
  "name": "analyze-localization-files",
  "version": "1.0.0",
  "description": "Use when building a translation task manifest for an i18n project — produces per-language lists of missing keys with their source values by running the bundled check-i18n.py script.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 4: Append to marketplace.json**

Append to the `plugins` array:

```json
{ "name": "analyze-localization-files", "description": "Use when building a translation task manifest for an i18n project — produces per-language lists of missing keys with their source values by running the bundled check-i18n.py script.", "source": "./analyze-localization-files", "category": "localization" }
```

- [ ] **Step 5: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f analyze-localization-files/skills/analyze-localization-files/scripts/check-i18n.py && echo OK
python3 -c "import json; json.load(open('analyze-localization-files/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
```

- [ ] **Step 6: Commit**

```bash
cd /Users/efitz/Projects/skills
git add analyze-localization-files/ .claude-plugin/marketplace.json
git commit -m "feat(analyze-localization-files): reshape to plugin layout, rewrite \$SKILL_DIR to \${CLAUDE_PLUGIN_ROOT}"
```

---

## Task 6: Reshape `validate-localization-coverage` (includes path rewrite)

**Files:**
- Modify: `/Users/efitz/Projects/skills/validate-localization-coverage/`
- Create: `/Users/efitz/Projects/skills/validate-localization-coverage/.claude-plugin/plugin.json`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

Same shape as Task 5 (reshape + `$SKILL_DIR` rewrite).

- [ ] **Step 1: Move files**

```bash
cd /Users/efitz/Projects/skills
mkdir -p validate-localization-coverage/.claude-plugin validate-localization-coverage/skills/validate-localization-coverage
cd validate-localization-coverage
git mv SKILL.md skills/validate-localization-coverage/SKILL.md
git mv scripts skills/validate-localization-coverage/scripts
```

- [ ] **Step 2: Rewrite `$SKILL_DIR` references**

In `/Users/efitz/Projects/skills/validate-localization-coverage/skills/validate-localization-coverage/SKILL.md`, replace every occurrence of `$SKILL_DIR` with `${CLAUDE_PLUGIN_ROOT}/skills/validate-localization-coverage`.

Verify: `grep -n "SKILL_DIR" /Users/efitz/Projects/skills/validate-localization-coverage/skills/validate-localization-coverage/SKILL.md` returns no matches.

- [ ] **Step 3: Write plugin.json**

```json
{
  "name": "validate-localization-coverage",
  "version": "1.0.0",
  "description": "Use when auditing i18n translation completeness across all target locales or identifying locales below a coverage threshold. Produces a per-locale and summary coverage report.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 4: Append to marketplace.json**

```json
{ "name": "validate-localization-coverage", "description": "Use when auditing i18n translation completeness across all target locales or identifying locales below a coverage threshold. Produces a per-locale and summary coverage report.", "source": "./validate-localization-coverage", "category": "localization" }
```

- [ ] **Step 5: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('validate-localization-coverage/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add validate-localization-coverage/ .claude-plugin/marketplace.json
git commit -m "feat(validate-localization-coverage): reshape to plugin layout, rewrite \$SKILL_DIR"
```

---

## Task 7: Reshape `detect-non-localizable`

Simple reshape, no path rewrites.

- [ ] **Step 1: Move files**

```bash
cd /Users/efitz/Projects/skills
mkdir -p detect-non-localizable/.claude-plugin detect-non-localizable/skills/detect-non-localizable
cd detect-non-localizable
git mv SKILL.md skills/detect-non-localizable/SKILL.md
# move any other subdirs that exist:
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/detect-non-localizable/$d"
done
```

- [ ] **Step 2: Write plugin.json**

```json
{
  "name": "detect-non-localizable",
  "version": "1.0.0",
  "description": "Use when filtering localization keys, validating translation files, or deciding whether a string value should be translated or left as-is. Returns a boolean and the matched pattern.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 3: Append to marketplace.json**

```json
{ "name": "detect-non-localizable", "description": "Use when filtering localization keys, validating translation files, or deciding whether a string value should be translated or left as-is. Returns a boolean and the matched pattern.", "source": "./detect-non-localizable", "category": "localization" }
```

- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('detect-non-localizable/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add detect-non-localizable/ .claude-plugin/marketplace.json
git commit -m "feat(detect-non-localizable): reshape to plugin layout"
```

---

## Task 8: Reshape `translate-to-language`

Same pattern as Task 7.

- [ ] **Step 1: Move files** (use the bash loop pattern from Task 7, substituting `translate-to-language`)
- [ ] **Step 2: Write plugin.json** (substitute name + description: `Use when translating UI strings, i18n values, or short localized content into a specific target language while preserving placeholders, formatting, capitalization, and tone.`)
- [ ] **Step 3: Append to marketplace.json** (category: `localization`)
- [ ] **Step 4: Verify + commit** with message `feat(translate-to-language): reshape to plugin layout`

```bash
cd /Users/efitz/Projects/skills
mkdir -p translate-to-language/.claude-plugin translate-to-language/skills/translate-to-language
cd translate-to-language
git mv SKILL.md skills/translate-to-language/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/translate-to-language/$d"
done
```

plugin.json:
```json
{
  "name": "translate-to-language",
  "version": "1.0.0",
  "description": "Use when translating UI strings, i18n values, or short localized content into a specific target language while preserving placeholders, formatting, capitalization, and tone.",
  "author": { "name": "efitz" }
}
```

marketplace entry:
```json
{ "name": "translate-to-language", "description": "Use when translating UI strings, i18n values, or short localized content into a specific target language while preserving placeholders, formatting, capitalization, and tone.", "source": "./translate-to-language", "category": "localization" }
```

---

## Task 9: Reshape `update-json-localization-file`

```bash
cd /Users/efitz/Projects/skills
mkdir -p update-json-localization-file/.claude-plugin update-json-localization-file/skills/update-json-localization-file
cd update-json-localization-file
git mv SKILL.md skills/update-json-localization-file/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/update-json-localization-file/$d"
done
```

plugin.json:
```json
{
  "name": "update-json-localization-file",
  "version": "1.0.0",
  "description": "Use when modifying a JSON i18n file with additions, updates, or deletions while preserving formatting and writing atomically.",
  "author": { "name": "efitz" }
}
```

marketplace entry (category `localization`):
```json
{ "name": "update-json-localization-file", "description": "Use when modifying a JSON i18n file with additions, updates, or deletions while preserving formatting and writing atomically.", "source": "./update-json-localization-file", "category": "localization" }
```

- [ ] **Step 1: Move files** (above)
- [ ] **Step 2: Write plugin.json** (above)
- [ ] **Step 3: Append to marketplace.json** (above)
- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('update-json-localization-file/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add update-json-localization-file/ .claude-plugin/marketplace.json
git commit -m "feat(update-json-localization-file): reshape to plugin layout"
```

---

## Task 10: Reshape `validate-translation`

```bash
cd /Users/efitz/Projects/skills
mkdir -p validate-translation/.claude-plugin validate-translation/skills/validate-translation
cd validate-translation
git mv SKILL.md skills/validate-translation/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/validate-translation/$d"
done
```

plugin.json:
```json
{
  "name": "validate-translation",
  "version": "1.0.0",
  "description": "Use when reviewing a translated string or validating an i18n file update, to verify placeholder preservation, length, encoding, and common translation errors.",
  "author": { "name": "efitz" }
}
```

marketplace entry (category `localization`):
```json
{ "name": "validate-translation", "description": "Use when reviewing a translated string or validating an i18n file update, to verify placeholder preservation, length, encoding, and common translation errors.", "source": "./validate-translation", "category": "localization" }
```

- [ ] **Step 1: Move files**
- [ ] **Step 2: Write plugin.json**
- [ ] **Step 3: Append to marketplace.json**
- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('validate-translation/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add validate-translation/ .claude-plugin/marketplace.json
git commit -m "feat(validate-translation): reshape to plugin layout"
```

---

## Task 11: Reshape `file-github-bug`

```bash
cd /Users/efitz/Projects/skills
mkdir -p file-github-bug/.claude-plugin file-github-bug/skills/file-github-bug
cd file-github-bug
git mv SKILL.md skills/file-github-bug/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/file-github-bug/$d"
done
```

plugin.json:
```json
{
  "name": "file-github-bug",
  "version": "1.0.0",
  "description": "Use when filing a detailed bug report against a GitHub repo with evidence, optionally adding it to a GitHub Project (v2), setting milestone from current branch, and marking initial status. Reads repo/project metadata from .local-projects.json so the skill is repo-agnostic.",
  "author": { "name": "efitz" }
}
```

marketplace entry (category `misc`):
```json
{ "name": "file-github-bug", "description": "Use when filing a detailed bug report against a GitHub repo with evidence, optionally adding it to a GitHub Project (v2), setting milestone from current branch, and marking initial status. Reads repo/project metadata from .local-projects.json so the skill is repo-agnostic.", "source": "./file-github-bug", "category": "misc" }
```

- [ ] **Step 1: Move files**
- [ ] **Step 2: Write plugin.json**
- [ ] **Step 3: Append to marketplace.json**
- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('file-github-bug/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add file-github-bug/ .claude-plugin/marketplace.json
git commit -m "feat(file-github-bug): reshape to plugin layout"
```

---

## Task 12: Reshape `verify-migrate-doc`

```bash
cd /Users/efitz/Projects/skills
mkdir -p verify-migrate-doc/.claude-plugin verify-migrate-doc/skills/verify-migrate-doc
cd verify-migrate-doc
git mv SKILL.md skills/verify-migrate-doc/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/verify-migrate-doc/$d"
done
```

plugin.json:
```json
{
  "name": "verify-migrate-doc",
  "version": "1.0.0",
  "description": "Use when asked to verify a documentation file's accuracy against source code and external references, then migrate it into a project wiki. Reads target repo and wiki path from .local-projects.json.",
  "author": { "name": "efitz" }
}
```

marketplace entry (category `misc`):
```json
{ "name": "verify-migrate-doc", "description": "Use when asked to verify a documentation file's accuracy against source code and external references, then migrate it into a project wiki. Reads target repo and wiki path from .local-projects.json.", "source": "./verify-migrate-doc", "category": "misc" }
```

- [ ] **Step 1: Move files**
- [ ] **Step 2: Write plugin.json**
- [ ] **Step 3: Append to marketplace.json**
- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('verify-migrate-doc/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add verify-migrate-doc/ .claude-plugin/marketplace.json
git commit -m "feat(verify-migrate-doc): reshape to plugin layout"
```

---

## Task 13: Reshape `visual-regression-triage`

```bash
cd /Users/efitz/Projects/skills
mkdir -p visual-regression-triage/.claude-plugin visual-regression-triage/skills/visual-regression-triage
cd visual-regression-triage
git mv SKILL.md skills/visual-regression-triage/SKILL.md
for d in $(ls -d */ 2>/dev/null | grep -v -E "^(skills|\.claude-plugin)/"); do
  git mv "$d" "skills/visual-regression-triage/$d"
done
```

plugin.json:
```json
{
  "name": "visual-regression-triage",
  "version": "1.0.0",
  "description": "Use when a Playwright visual regression test fails (screenshot mismatch) or a user mentions a screenshot test failure. Presents baseline, actual, and diff images framed against the current task context, then helps the user decide bug vs. expected change.",
  "author": { "name": "efitz" }
}
```

marketplace entry (category `misc`):
```json
{ "name": "visual-regression-triage", "description": "Use when a Playwright visual regression test fails (screenshot mismatch) or a user mentions a screenshot test failure. Presents baseline, actual, and diff images framed against the current task context, then helps the user decide bug vs. expected change.", "source": "./visual-regression-triage", "category": "misc" }
```

- [ ] **Step 1: Move files**
- [ ] **Step 2: Write plugin.json**
- [ ] **Step 3: Append to marketplace.json**
- [ ] **Step 4: Verify + commit**

```bash
cd /Users/efitz/Projects/skills
python3 -c "import json; json.load(open('visual-regression-triage/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
git add visual-regression-triage/ .claude-plugin/marketplace.json
git commit -m "feat(visual-regression-triage): reshape to plugin layout"
```

---

## Task 14: Reshape `boring` (non-standard layout)

**Files:**
- Modify: `/Users/efitz/Projects/skills/boring/` (move src/SKILL.md to skills/boring/SKILL.md; move tools/, calibration/, samples/, docs/, dist/ under skills/boring/; remove now-empty src/)
- Modify: `/Users/efitz/Projects/skills/boring/skills/boring/SKILL.md` (rewrite stale self-references at lines 279, 298)
- Create: `/Users/efitz/Projects/skills/boring/.claude-plugin/plugin.json`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

The boring skill currently has SKILL.md at `boring/src/SKILL.md` and bundles `tools/`, `calibration/`, `samples/`, `docs/`, `dist/` at the boring root level.

- [ ] **Step 1: Make new directories**

```bash
cd /Users/efitz/Projects/skills/boring
mkdir -p .claude-plugin skills/boring
```

- [ ] **Step 2: Move SKILL.md and supporting subdirs**

```bash
cd /Users/efitz/Projects/skills/boring
git mv src/SKILL.md skills/boring/SKILL.md
for d in tools calibration samples docs dist; do
  if [ -d "$d" ]; then git mv "$d" "skills/boring/$d"; fi
done
# Check if anything remains in src/:
ls src/ 2>/dev/null
```

- [ ] **Step 3: Move any remaining files from src/**

If `ls src/` showed other files (e.g., `calibration.toml`, `pyproject.toml`, `uv.lock`, `rubrics/`, `scripts/`), move them into `skills/boring/`:

```bash
cd /Users/efitz/Projects/skills/boring
for f in src/*; do
  [ -e "$f" ] && git mv "$f" "skills/boring/$(basename "$f")"
done
rmdir src
```

- [ ] **Step 4: Rewrite stale self-references in SKILL.md**

Open `/Users/efitz/Projects/skills/boring/skills/boring/SKILL.md`. Around line 279 there is a directory tree comment `boring/ ← (this file lives in src/; tree shows shipped layout)`. Around line 298 there is text `In the development repo this skill is built from boring/src/.` Either:

(a) Update both to reflect the new `skills/boring/` layout, OR
(b) Delete both — they are dev-only documentation that becomes stale.

Choose (b) (delete the stale comments) — simpler and these comments don't add user value.

Verify: `grep -n "boring/src\|src/SKILL" /Users/efitz/Projects/skills/boring/skills/boring/SKILL.md` should return no matches.

- [ ] **Step 5: Check any other relative-path references**

Run: `grep -n "scripts/\|tools/\|calibration/\|samples/" /Users/efitz/Projects/skills/boring/skills/boring/SKILL.md | head -20`

For each match, confirm the path is relative to the SKILL.md location (e.g., `scripts/analyzer/`) — these are still valid because the subdirs moved alongside SKILL.md. If any reference points to a path that's been broken, rewrite it.

- [ ] **Step 6: Write plugin.json**

Write `/Users/efitz/Projects/skills/boring/.claude-plugin/plugin.json`:

```json
{
  "name": "boring",
  "version": "1.0.0",
  "description": "Evaluate technical business writing for \"boringness\" across 20 sub-dimensions on four axes (Direction, Density, Texture, Surprise). Combines a mechanical analyzer (15 sub-dimensions, deterministic, runs as a Python script) with five LLM-judged sub-dimensions that require semantic judgment. Use when the user asks to review a document for engagement, clarity, or \"is this boring\", or for prose-mechanics issues in technical writing.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 7: Append to marketplace.json**

```json
{ "name": "boring", "description": "Evaluate technical business writing for \"boringness\" across 20 sub-dimensions on four axes (Direction, Density, Texture, Surprise). Combines a mechanical analyzer (15 sub-dimensions, deterministic, runs as a Python script) with five LLM-judged sub-dimensions that require semantic judgment. Use when the user asks to review a document for engagement, clarity, or \"is this boring\", or for prose-mechanics issues in technical writing.", "source": "./boring", "category": "writing" }
```

- [ ] **Step 8: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f boring/.claude-plugin/plugin.json && test -f boring/skills/boring/SKILL.md && echo OK
test ! -d boring/src && echo "src/ removed"
python3 -c "import json; json.load(open('boring/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
```

- [ ] **Step 9: Commit**

```bash
cd /Users/efitz/Projects/skills
git add boring/ .claude-plugin/marketplace.json
git commit -m "feat(boring): reshape to plugin layout, remove stale src/ comments"
```

---

## Task 15: Build `bump` plugin (command → skill + wrapper)

**Files:**
- Create: `/Users/efitz/Projects/skills/bump/.claude-plugin/plugin.json`
- Create: `/Users/efitz/Projects/skills/bump/skills/bump/SKILL.md`
- Create: `/Users/efitz/Projects/skills/bump/commands/bump.md`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

- [ ] **Step 1: Make directory structure**

```bash
cd /Users/efitz/Projects/skills
mkdir -p bump/.claude-plugin bump/skills/bump bump/commands
```

- [ ] **Step 2: Copy command body to skill**

```bash
cp /Users/efitz/.claude/commands/bump.md /Users/efitz/Projects/skills/bump/skills/bump/SKILL.md
```

- [ ] **Step 3: Add skill frontmatter**

Open `/Users/efitz/Projects/skills/bump/skills/bump/SKILL.md`. Prepend (as the very first lines, before the existing `# Bump Command` heading):

```markdown
---
name: bump
version: 1.0.0
description: Update dependencies safely across Go/Python/Node ecosystems. Use when the user asks to bump deps, update packages, fix Dependabot alerts, or run a dependency upgrade. Detects ecosystems, applies safe updates with build/test/lint validation, and surfaces a plan for packages that need manual review.
---

```

- [ ] **Step 4: Rewrite `$ARGUMENTS` parsing to natural-language parsing**

In `/Users/efitz/Projects/skills/bump/skills/bump/SKILL.md`, find the section "Phase 0: Parse Arguments and Detect Ecosystems" (around line 38 of the original) and replace the `$ARGUMENTS` parsing instructions. The original says:

```
1. Parse `$ARGUMENTS`:
   - If an ecosystem name is given (`go`, `python`/`py`, `node`/`npm`/`pnpm`/`js`/`ts`): target that ecosystem only.
   - If no argument: auto-detect all ecosystems present.
```

Replace with:

```
1. Parse the user's request for an ecosystem hint:
   - If the request mentions `go`, target Go only.
   - If the request mentions `python`, `py`, `pip`, or `uv`, target Python only.
   - If the request mentions `node`, `npm`, `pnpm`, `js`, or `ts`, target Node only.
   - If invoked via the `/bump` command wrapper, the user's arguments are passed as the skill's args — parse them the same way.
   - If no ecosystem hint is present, auto-detect all ecosystems.
```

- [ ] **Step 5: No bundled scripts for bump**

The bump command does not reference any scripts in `~/.claude/scripts/`. Verify: `grep -n "~/.claude/scripts\|\.claude/scripts" /Users/efitz/Projects/skills/bump/skills/bump/SKILL.md` returns nothing.

- [ ] **Step 6: Write plugin.json**

```json
{
  "name": "bump",
  "version": "1.0.0",
  "description": "Update dependencies safely across Go/Python/Node ecosystems. Use when the user asks to bump deps, update packages, fix Dependabot alerts, or run a dependency upgrade. Detects ecosystems, applies safe updates with build/test/lint validation, and surfaces a plan for packages that need manual review.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 7: Write the command wrapper**

Write `/Users/efitz/Projects/skills/bump/commands/bump.md`:

```markdown
---
description: Update dependencies safely across Go/Python/Node ecosystems
---

Invoke the `bump:bump` skill with these arguments: $ARGUMENTS
```

- [ ] **Step 8: Append to marketplace.json**

```json
{ "name": "bump", "description": "Update dependencies safely across Go/Python/Node ecosystems. Use when the user asks to bump deps, update packages, fix Dependabot alerts, or run a dependency upgrade. Detects ecosystems, applies safe updates with build/test/lint validation, and surfaces a plan for packages that need manual review.", "source": "./bump", "category": "development" }
```

- [ ] **Step 9: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f bump/.claude-plugin/plugin.json && test -f bump/skills/bump/SKILL.md && test -f bump/commands/bump.md && echo OK
python3 -c "import json; json.load(open('bump/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
head -6 bump/skills/bump/SKILL.md  # should show frontmatter
```

- [ ] **Step 10: Commit**

```bash
cd /Users/efitz/Projects/skills
git add bump/ .claude-plugin/marketplace.json
git commit -m "feat(bump): convert /bump command to plugin with skill and wrapper"
```

---

## Task 16: Build `backlog-next` plugin

**Files:**
- Create: `/Users/efitz/Projects/skills/backlog-next/.claude-plugin/plugin.json`
- Create: `/Users/efitz/Projects/skills/backlog-next/skills/backlog-next/SKILL.md`
- Create: `/Users/efitz/Projects/skills/backlog-next/commands/backlog-next.md`
- Create: `/Users/efitz/Projects/skills/backlog-next/scripts/gh-issues.py` (copy of `~/.claude/scripts/gh-issues.py`)
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

- [ ] **Step 1: Make directory structure**

```bash
cd /Users/efitz/Projects/skills
mkdir -p backlog-next/.claude-plugin backlog-next/skills/backlog-next backlog-next/commands backlog-next/scripts
```

- [ ] **Step 2: Copy script**

```bash
cp /Users/efitz/.claude/scripts/gh-issues.py /Users/efitz/Projects/skills/backlog-next/scripts/gh-issues.py
```

- [ ] **Step 3: Copy command body to skill**

```bash
cp /Users/efitz/.claude/commands/backlog-next.md /Users/efitz/Projects/skills/backlog-next/skills/backlog-next/SKILL.md
```

- [ ] **Step 4: Add skill frontmatter**

Prepend to `/Users/efitz/Projects/skills/backlog-next/skills/backlog-next/SKILL.md`:

```markdown
---
name: backlog-next
version: 1.0.0
description: Pick the next GitHub issue to work on. Use when the user asks what to work on next, requests the next backlog item, or wants an issue prioritized for the current milestone. Fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one.
---

```

- [ ] **Step 5: Rewrite script paths**

In the SKILL.md, replace both occurrences of `python3 ~/.claude/scripts/gh-issues.py` with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py`.

Verify: `grep -n "gh-issues.py" /Users/efitz/Projects/skills/backlog-next/skills/backlog-next/SKILL.md` shows only `${CLAUDE_PLUGIN_ROOT}` references, no `~/.claude/scripts/` references.

- [ ] **Step 6: No `$ARGUMENTS` to rewrite**

The backlog-next command does not branch on `$ARGUMENTS`. Verify: `grep -n "ARGUMENTS" /Users/efitz/Projects/skills/backlog-next/skills/backlog-next/SKILL.md` returns nothing.

- [ ] **Step 7: Write plugin.json**

```json
{
  "name": "backlog-next",
  "version": "1.0.0",
  "description": "Pick the next GitHub issue to work on. Use when the user asks what to work on next, requests the next backlog item, or wants an issue prioritized for the current milestone. Fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 8: Write command wrapper**

Write `/Users/efitz/Projects/skills/backlog-next/commands/backlog-next.md`:

```markdown
---
description: Pick the next GitHub issue to work on
---

Invoke the `backlog-next:backlog-next` skill with these arguments: $ARGUMENTS
```

- [ ] **Step 9: Append to marketplace.json**

```json
{ "name": "backlog-next", "description": "Pick the next GitHub issue to work on. Use when the user asks what to work on next, requests the next backlog item, or wants an issue prioritized for the current milestone. Fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one.", "source": "./backlog-next", "category": "development" }
```

- [ ] **Step 10: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f backlog-next/scripts/gh-issues.py && echo OK
python3 -c "import json; json.load(open('backlog-next/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
```

- [ ] **Step 11: Commit**

```bash
cd /Users/efitz/Projects/skills
git add backlog-next/ .claude-plugin/marketplace.json
git commit -m "feat(backlog-next): convert /backlog-next command to plugin with bundled gh-issues.py"
```

---

## Task 17: Build `dedupe` plugin (command + 3 worker agents)

**Files:**
- Create: `/Users/efitz/Projects/skills/dedupe/.claude-plugin/plugin.json`
- Create: `/Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md`
- Create: `/Users/efitz/Projects/skills/dedupe/commands/dedupe.md`
- Create: `/Users/efitz/Projects/skills/dedupe/scripts/dedupe-report.py`
- Create: `/Users/efitz/Projects/skills/dedupe/agents/dedupe-analyzer.md`
- Create: `/Users/efitz/Projects/skills/dedupe/agents/dedupe-grouper.md`
- Create: `/Users/efitz/Projects/skills/dedupe/agents/dedupe-deduplicator.md`
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

Largest of the new plugins.

- [ ] **Step 1: Make directory structure**

```bash
cd /Users/efitz/Projects/skills
mkdir -p dedupe/.claude-plugin dedupe/skills/dedupe dedupe/commands dedupe/scripts dedupe/agents
```

- [ ] **Step 2: Copy script and agent files**

```bash
cp /Users/efitz/.claude/scripts/dedupe-report.py /Users/efitz/Projects/skills/dedupe/scripts/dedupe-report.py
cp /Users/efitz/.claude/agents/dedupe-analyzer.md /Users/efitz/Projects/skills/dedupe/agents/dedupe-analyzer.md
cp /Users/efitz/.claude/agents/dedupe-grouper.md /Users/efitz/Projects/skills/dedupe/agents/dedupe-grouper.md
cp /Users/efitz/.claude/agents/dedupe-deduplicator.md /Users/efitz/Projects/skills/dedupe/agents/dedupe-deduplicator.md
```

- [ ] **Step 3: Copy command body to skill**

```bash
cp /Users/efitz/.claude/commands/dedupe.md /Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md
```

- [ ] **Step 4: Add skill frontmatter**

Prepend to `/Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md`:

```markdown
---
name: dedupe
version: 1.0.0
description: Find and analyze duplicate or overlapping functionality across a codebase. Use when the user asks to dedupe, find duplicate code, look for redundant functions, or audit for code duplication. Supports Go, Python, and TypeScript. Orchestrates per-file analysis, candidate grouping, and deep comparison through a shared SQLite database.
---

```

- [ ] **Step 5: Rewrite `$ARGUMENTS` parsing**

In `/Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md`, find "Phase 0: Parse Arguments and Detect Language" (around line 37) and replace the `$ARGUMENTS` parsing block:

Original:
```
1. Parse the user's arguments from `$ARGUMENTS`:
   - If `clean`: delete `.dedupe/dedupe.db` and `.dedupe/reports/` contents, then stop.
   - If a language name is given (go, python, typescript, ts, py): use that language.
   - If `tests` is given: set includeTests=true.
   - If no language specified: proceed to auto-detection.
```

Replace with:
```
1. Parse the user's request for language and option hints:
   - If the user says "clean" (or asks to reset/clear dedupe state): delete `.dedupe/dedupe.db` and `.dedupe/reports/` contents, then stop.
   - If the user mentions `go`, `python`, `typescript`, `ts`, or `py`: target that language only.
   - If the user mentions `tests` (e.g., "include tests"): set includeTests=true.
   - If invoked via the `/dedupe` command wrapper, the user's arguments are passed as the skill's args — parse them the same way.
   - If no language hint is present, proceed to auto-detection.
```

- [ ] **Step 6: Rewrite any `~/.claude/scripts/` references**

Run: `grep -n "~/.claude/scripts\|\.claude/scripts/dedupe-report" /Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md`

For each match, replace the `~/.claude/scripts/` prefix with `${CLAUDE_PLUGIN_ROOT}/scripts/`. Re-verify with grep that no `~/.claude/scripts` references remain.

- [ ] **Step 7: Verify worker agent names in SKILL.md still match the agent files**

The dedupe skill body dispatches workers by name (e.g., `subagent_type: "Duplicate Candidate Grouper"`). Verify the names match the `name:` field in each agent file:

```bash
for f in /Users/efitz/Projects/skills/dedupe/agents/*.md; do
  echo "=== $(basename $f) ==="
  awk '/^---$/{c++; next} c==1 && /^name:/' "$f"
done
```

Then grep for these names in SKILL.md:
```bash
grep -n "Code Analyzer\|Code Deduplicator\|Duplicate Candidate Grouper" /Users/efitz/Projects/skills/dedupe/skills/dedupe/SKILL.md
```

Expected: every name referenced in SKILL.md matches a `name:` field in the agents/. If anything's off, list the mismatches and stop — names must match for the Agent tool to dispatch.

- [ ] **Step 8: Write plugin.json**

```json
{
  "name": "dedupe",
  "version": "1.0.0",
  "description": "Find and analyze duplicate or overlapping functionality across a codebase. Use when the user asks to dedupe, find duplicate code, look for redundant functions, or audit for code duplication. Supports Go, Python, and TypeScript. Orchestrates per-file analysis, candidate grouping, and deep comparison through a shared SQLite database.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 9: Write command wrapper**

Write `/Users/efitz/Projects/skills/dedupe/commands/dedupe.md`:

```markdown
---
description: Find and analyze duplicate or overlapping functionality across a codebase
---

Invoke the `dedupe:dedupe` skill with these arguments: $ARGUMENTS
```

- [ ] **Step 10: Append to marketplace.json**

```json
{ "name": "dedupe", "description": "Find and analyze duplicate or overlapping functionality across a codebase. Use when the user asks to dedupe, find duplicate code, look for redundant functions, or audit for code duplication. Supports Go, Python, and TypeScript. Orchestrates per-file analysis, candidate grouping, and deep comparison through a shared SQLite database.", "source": "./dedupe", "category": "development" }
```

- [ ] **Step 11: Verify**

```bash
cd /Users/efitz/Projects/skills
test -f dedupe/skills/dedupe/SKILL.md && test -f dedupe/scripts/dedupe-report.py && echo OK
ls dedupe/agents/  # should list 3 files
python3 -c "import json; json.load(open('dedupe/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
grep -c "CLAUDE_PLUGIN_ROOT" dedupe/skills/dedupe/SKILL.md  # should be ≥1 if dedupe-report was referenced
```

- [ ] **Step 12: Commit**

```bash
cd /Users/efitz/Projects/skills
git add dedupe/ .claude-plugin/marketplace.json
git commit -m "feat(dedupe): convert /dedupe command + worker agents to plugin"
```

---

## Task 18: Build `localization-backfill` plugin

**Files:**
- Create: `/Users/efitz/Projects/skills/localization-backfill/.claude-plugin/plugin.json`
- Create: `/Users/efitz/Projects/skills/localization-backfill/skills/localization-backfill/SKILL.md`
- Create: `/Users/efitz/Projects/skills/localization-backfill/commands/localization-backfill.md`
- Create: `/Users/efitz/Projects/skills/localization-backfill/scripts/find_duplicate_localizations.py`
- Delete: `/Users/efitz/Projects/skills/commands/localization-backfill.md` and `/Users/efitz/Projects/skills/commands/localization-backfill.scripts/` (after migration)
- Modify: `/Users/efitz/Projects/skills/.claude-plugin/marketplace.json`

- [ ] **Step 1: Make directory structure**

```bash
cd /Users/efitz/Projects/skills
mkdir -p localization-backfill/.claude-plugin localization-backfill/skills/localization-backfill localization-backfill/commands localization-backfill/scripts
```

- [ ] **Step 2: Move the bundled script using git mv**

```bash
cd /Users/efitz/Projects/skills
git mv commands/localization-backfill.scripts/find_duplicate_localizations.py localization-backfill/scripts/find_duplicate_localizations.py
rmdir commands/localization-backfill.scripts 2>/dev/null
```

- [ ] **Step 3: Move the command body to the skill**

```bash
cd /Users/efitz/Projects/skills
git mv commands/localization-backfill.md localization-backfill/skills/localization-backfill/SKILL.md
```

- [ ] **Step 4: Update frontmatter — change `name:` if needed and add `version:`**

Open `/Users/efitz/Projects/skills/localization-backfill/skills/localization-backfill/SKILL.md`. The existing frontmatter has `name: localization-backfill` and `description:` already set. Verify those values; add `version: 1.0.0` on its own line under `name:`. Final frontmatter should look like:

```markdown
---
name: localization-backfill
version: 1.0.0
description: Translate every missing or untranslated key across all i18n locale files using the master locale as the source. Tool-agnostic; reads project i18n configuration.
---
```

(Preserve any other frontmatter fields like `allowed-tools:` or `argument-hint:` that may exist.)

- [ ] **Step 5: Rewrite `$COMMAND_DIR` references and descriptive paths**

In `/Users/efitz/Projects/skills/localization-backfill/skills/localization-backfill/SKILL.md`:

a. Around line 14, the descriptive text says `localization-backfill.scripts/find_duplicate_localizations.py — bundled dedupe analyzer used in Step 1 of this command.` Replace with `scripts/find_duplicate_localizations.py — bundled dedupe analyzer used in Step 1 of this skill.`

b. Around line 43, the command is `uv run "$COMMAND_DIR/localization-backfill.scripts/find_duplicate_localizations.py" \`. Replace with `uv run "${CLAUDE_PLUGIN_ROOT}/scripts/find_duplicate_localizations.py" \`.

c. Search for any other `$COMMAND_DIR` references and rewrite them to `${CLAUDE_PLUGIN_ROOT}`. Run: `grep -n "COMMAND_DIR\|localization-backfill.scripts" /Users/efitz/Projects/skills/localization-backfill/skills/localization-backfill/SKILL.md` — should return nothing after rewrite.

- [ ] **Step 6: Write plugin.json**

```json
{
  "name": "localization-backfill",
  "version": "1.0.0",
  "description": "Translate every missing or untranslated key across all i18n locale files using the master locale as the source. Tool-agnostic; reads project i18n configuration.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 7: Write command wrapper**

Write `/Users/efitz/Projects/skills/localization-backfill/commands/localization-backfill.md`:

```markdown
---
description: Translate every missing/untranslated key across all i18n locale files
---

Invoke the `localization-backfill:localization-backfill` skill with these arguments: $ARGUMENTS
```

- [ ] **Step 8: Append to marketplace.json**

```json
{ "name": "localization-backfill", "description": "Translate every missing or untranslated key across all i18n locale files using the master locale as the source. Tool-agnostic; reads project i18n configuration.", "source": "./localization-backfill", "category": "localization" }
```

- [ ] **Step 9: Verify and clean up the empty commands/ directory**

```bash
cd /Users/efitz/Projects/skills
test -f localization-backfill/scripts/find_duplicate_localizations.py && test -f localization-backfill/skills/localization-backfill/SKILL.md && echo OK
python3 -c "import json; json.load(open('localization-backfill/.claude-plugin/plugin.json'))"
python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"
# The repo-root commands/ dir should now be empty:
ls commands/ 2>/dev/null
rmdir commands 2>/dev/null && echo "commands/ removed" || echo "commands/ still has content — investigate"
```

- [ ] **Step 10: Commit**

```bash
cd /Users/efitz/Projects/skills
git add localization-backfill/ .claude-plugin/marketplace.json
git add -A commands/ 2>/dev/null  # capture the rmdir
git commit -m "feat(localization-backfill): convert from repo-root commands/ to plugin"
```

---

## Task 19: Local marketplace install — add the marketplace

**Files:** (none modified; this is a smoke test)

- [ ] **Step 1: Add the local marketplace to Claude Code**

In a Claude Code session, run the slash command:
```
/plugin marketplace add /Users/efitz/Projects/skills
```

Expected: Claude Code reports the marketplace `efitz-skills` was added.

- [ ] **Step 2: List the marketplace's plugins**

Run:
```
/plugin marketplace list
```

Or, from the Bash tool:
```bash
cat /Users/efitz/Projects/skills/.claude-plugin/marketplace.json | python3 -c "import sys, json; d = json.load(sys.stdin); print(f'{len(d[\"plugins\"])} plugins:'); [print(f'  {p[\"name\"]} ({p[\"category\"]})') for p in d['plugins']]"
```

Expected output:
```
16 plugins:
  plugin-vetter (security)
  race-condition-audit (security)
  analyze-localization-files (localization)
  validate-localization-coverage (localization)
  detect-non-localizable (localization)
  translate-to-language (localization)
  update-json-localization-file (localization)
  validate-translation (localization)
  file-github-bug (misc)
  verify-migrate-doc (misc)
  visual-regression-triage (misc)
  boring (writing)
  bump (development)
  backlog-next (development)
  dedupe (development)
  localization-backfill (localization)
```

(Order may vary; count must be 16.)

If anything fails, fix the marketplace.json (likely a syntax issue from concatenation across tasks 3–18) before proceeding.

---

## Task 20: Install and smoke-test `bump`

- [ ] **Step 1: Install the bump plugin**

```
/plugin install bump@efitz-skills
```

Expected: Claude Code reports the plugin installed.

- [ ] **Step 2: Verify the command appears**

The `/bump` slash command should be listed in the user-invocable commands section in subsequent prompts. (If the system shows skills only, verify the `bump:bump` skill is listed.)

- [ ] **Step 3: Smoke-test the slash command**

In a session, invoke:
```
/bump python
```

Expected: Claude proceeds with the bump process targeting Python. No errors about missing skill or unresolved paths.

- [ ] **Step 4: Smoke-test the auto-trigger (skill route)**

In a fresh session, type without using the slash command:
```
please bump my node dependencies
```

Expected: Claude invokes the `bump:bump` skill, then proceeds with the bump process targeting Node.

If either smoke test fails, do NOT proceed to Task 23 (cutover). Diagnose and fix.

---

## Task 21: Install and smoke-test `dedupe`

- [ ] **Step 1: Install the dedupe plugin**

```
/plugin install dedupe@efitz-skills
```

- [ ] **Step 2: Verify worker agents are registered**

The three workers (`Code Analyzer`, `Code Deduplicator`, `Duplicate Candidate Grouper`) must be visible. In a session, you should see them listed in the agent registry, or successfully dispatchable via the Agent tool. Check by inspecting the system prompt or by attempting:

```bash
ls ~/.claude/plugins/cache/efitz-skills/dedupe/*/agents/ 2>/dev/null || ls ~/.claude/plugins/*/dedupe/agents/ 2>/dev/null
```

Expected: 3 .md files visible at the install path.

- [ ] **Step 3: Smoke-test `/dedupe`**

```
/dedupe go
```

Expected: Phase 0 logic runs, language is set to Go, no errors about missing `${CLAUDE_PLUGIN_ROOT}` substitution or missing worker agents.

- [ ] **Step 4: Smoke-test the auto-trigger**

In a fresh session:
```
find duplicate code in this typescript project
```

Expected: `dedupe:dedupe` skill invokes, language=typescript.

---

## Task 22: Install and smoke-test the remaining plugins

- [ ] **Step 1: Install the remaining 14 plugins**

```
/plugin install backlog-next@efitz-skills
/plugin install localization-backfill@efitz-skills
/plugin install plugin-vetter@efitz-skills
/plugin install race-condition-audit@efitz-skills
/plugin install boring@efitz-skills
/plugin install analyze-localization-files@efitz-skills
/plugin install detect-non-localizable@efitz-skills
/plugin install translate-to-language@efitz-skills
/plugin install update-json-localization-file@efitz-skills
/plugin install validate-localization-coverage@efitz-skills
/plugin install validate-translation@efitz-skills
/plugin install file-github-bug@efitz-skills
/plugin install verify-migrate-doc@efitz-skills
/plugin install visual-regression-triage@efitz-skills
```

Expected: each install succeeds; no missing-file errors.

- [ ] **Step 2: Verify all skills auto-trigger as expected**

The reshaped skills' triggers haven't changed (same `description:` field). They should auto-trigger from the same kinds of natural-language prompts as before. Spot-check three:

a. `plugin-vetter`: in a session, say "I'm about to install a plugin from github, can you check it" — expect Claude to invoke `plugin-vetter:plugin-vetter`.

b. `race-condition-audit`: say "audit this Go code for race conditions" — expect `race-condition-audit:race-condition-audit`.

c. `boring`: say "review this RFC for boringness" — expect `boring:boring`.

If any fails, check the skill's frontmatter survived reshape correctly. Do NOT proceed to cutover if any reshape smoke-test fails.

- [ ] **Step 3: Verify the scripts referenced via `${CLAUDE_PLUGIN_ROOT}` resolve**

For each plugin that uses `${CLAUDE_PLUGIN_ROOT}` (analyze-localization-files, validate-localization-coverage, backlog-next, dedupe, localization-backfill), run an end-to-end action that exercises the bundled script. The simplest: trigger the skill and verify the script runs without "file not found" errors.

---

## Task 23: Cutover — delete originals

Only after Tasks 20–22 all pass.

**Files to delete:**
- `/Users/efitz/.claude/commands/bump.md`
- `/Users/efitz/.claude/commands/dedupe.md`
- `/Users/efitz/.claude/commands/backlog-next.md`
- `/Users/efitz/.claude/agents/dedupe-analyzer.md`
- `/Users/efitz/.claude/agents/dedupe-deduplicator.md`
- `/Users/efitz/.claude/agents/dedupe-grouper.md`
- `/Users/efitz/.claude/scripts/gh-issues.py`
- `/Users/efitz/.claude/scripts/dedupe-report.py`

- [ ] **Step 1: Determine whether `~/.claude/` is a git repo**

```bash
cd /Users/efitz/.claude && git rev-parse --is-inside-work-tree 2>/dev/null
```

If yes (output is `true`), use `git rm` for deletions and commit. If no, use plain `rm` and skip the commit step.

- [ ] **Step 2: Delete the original command files**

```bash
cd /Users/efitz/.claude
# If git repo:
git rm commands/bump.md commands/dedupe.md commands/backlog-next.md
# Else:
# rm commands/bump.md commands/dedupe.md commands/backlog-next.md
```

- [ ] **Step 3: Delete the original agent files**

```bash
cd /Users/efitz/.claude
# If git repo:
git rm agents/dedupe-analyzer.md agents/dedupe-deduplicator.md agents/dedupe-grouper.md
# Else:
# rm agents/dedupe-*.md
```

- [ ] **Step 4: Delete the original script files**

```bash
cd /Users/efitz/.claude
# If git repo:
git rm scripts/gh-issues.py scripts/dedupe-report.py
# Else:
# rm scripts/gh-issues.py scripts/dedupe-report.py
```

- [ ] **Step 5: Verify the slash commands now resolve from the plugin, not the original**

In a fresh session, run `/bump --help` or simply `/bump` and confirm it works (sourced from the plugin). The original files are gone; the plugin is the only source.

- [ ] **Step 6: Commit the cutover (if git repo)**

```bash
cd /Users/efitz/.claude
git commit -m "chore: remove commands/agents/scripts now served by efitz-skills marketplace plugins"
```

---

## Task 24: Optional — clean up duplicate skill copies in `~/.claude/skills/`

The 12 existing skills may also be present in `~/.claude/skills/` from manual copies. With plugins installed, those copies become a parallel source of truth that could cause conflicts.

- [ ] **Step 1: List skills present in both locations**

```bash
for d in /Users/efitz/.claude/skills/*/; do
  name=$(basename "$d")
  if [ -d "/Users/efitz/Projects/skills/$name/skills/$name" ]; then
    echo "DUPLICATE: $name (in ~/.claude/skills/ AND in efitz-skills plugin)"
  fi
done
```

- [ ] **Step 2: For each duplicate, ask the user whether to remove the `~/.claude/skills/` copy**

This step is interactive. Do not auto-delete. For each listed duplicate, ask: "Plugin is now installed. Remove the manual copy at `~/.claude/skills/<name>/`?"

- [ ] **Step 3: Remove approved duplicates**

```bash
# For each approved name:
rm -rf "/Users/efitz/.claude/skills/$name"
```

Skip this task entirely if no duplicates exist.

---

## Final verification

After Task 23, run a sanity check across the whole refactor:

```bash
cd /Users/efitz/Projects/skills
echo "Plugins in marketplace:"
python3 -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); print(len(d['plugins']))"

echo "Directories with .claude-plugin/plugin.json:"
find . -maxdepth 2 -name "plugin.json" -path "*/.claude-plugin/*" | wc -l

echo "Directories with skills/<name>/SKILL.md:"
find . -maxdepth 4 -name "SKILL.md" -path "*/skills/*/SKILL.md" | wc -l
```

Expected: all three counts are 16 (or 17 if `Final verification` is run before Task 24).

End of plan.
