# Plugin Regrouping Implementation Plan

> **For agentic workers:** Tasks 1–6 are independent per-plugin restructures on disjoint subtrees — dispatch as parallel subagents doing filesystem `mv` + content edits ONLY (no git). Tasks 7–10 are serial orchestrator work (shared files, staging, validation, push).

**Goal:** Consolidate 16 single-skill plugins into 8 multi-skill plugins in the `efitz-skills` marketplace.

**Architecture:** Move each old plugin's nested skill dir (`X/skills/X/`) into `<newplugin>/skills/<newskill>/`, relocate bundled scripts to plugin-root `scripts/`, update `name:` frontmatter + `${CLAUDE_PLUGIN_ROOT}` refs + intra-loc `[[wiki-links]]`, drop command wrappers, then rewrite the shared `marketplace.json`, `verify-marketplace.sh`, and root `README.md`.

**Tech Stack:** bash (`mv`, `rm`), markdown/JSON edits. Validation: `scripts/verify-marketplace.sh`.

**Mapping (new ← old):**
loc: analyze←analyze-localization-files, coverage←validate-localization-coverage, detect-nonloc←detect-non-localizable, translate-to←translate-to-language, update-json←update-json-localization-file, validate-translation←validate-translation, backfill←localization-backfill ·
security: vet-plugin←plugin-vetter, race-cond←race-condition-audit ·
github: backlog←backlog-next, file-bug←file-github-bug ·
ui: vrt←visual-regression-triage · wiki: verify-doc←verify-migrate-doc · dev: dedupe←dedupe ·
writing/deps: unchanged.

**Intra-loc `[[wiki-link]]` renames** (apply in backfill + coverage SKILL.md):
`[[analyze-localization-files]]`→`[[analyze]]`, `[[validate-localization-coverage]]`→`[[coverage]]`, `[[detect-non-localizable]]`→`[[detect-nonloc]]`, `[[translate-to-language]]`→`[[translate-to]]`, `[[update-json-localization-file]]`→`[[update-json]]`. (`[[validate-translation]]` stays.) Do NOT touch `[[var]]`/`[[user]]` in translate-to (literal examples).

**Per-skill self-reference rule:** in each moved SKILL.md, replace example paths `efitz-skills/<oldplugin>/<version>/` → `efitz-skills/<newplugin>/<version>/`, and any `skills/<oldskill>/` subpath → `skills/<newskill>/`. Update `name:` frontmatter to the new skill name. Descriptions unchanged.

---

### Task 1: Build the `loc` plugin (largest)

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1: Move the 7 skill dirs**
```bash
cd /Users/efitz/Projects/skills
mkdir -p loc/skills loc/scripts
mv analyze-localization-files/skills/analyze-localization-files loc/skills/analyze
mv validate-localization-coverage/skills/validate-localization-coverage loc/skills/coverage
mv detect-non-localizable/skills/detect-non-localizable loc/skills/detect-nonloc
mv translate-to-language/skills/translate-to-language loc/skills/translate-to
mv update-json-localization-file/skills/update-json-localization-file loc/skills/update-json
mv validate-translation/skills/validate-translation loc/skills/validate-translation
mv localization-backfill/skills/localization-backfill loc/skills/backfill
```

- [ ] **Step 2: Consolidate scripts** (check-i18n is identical in analyze+coverage → one copy)
```bash
mv loc/skills/analyze/scripts/check-i18n.py loc/scripts/check-i18n.py
rm -rf loc/skills/analyze/scripts loc/skills/coverage/scripts
mv localization-backfill/scripts/find_duplicate_localizations.py loc/scripts/find_duplicate_localizations.py
```

- [ ] **Step 3: Remove the 7 emptied old top-level dirs + the backfill command wrapper**
```bash
rm -rf analyze-localization-files validate-localization-coverage detect-non-localizable \
       translate-to-language update-json-localization-file validate-translation localization-backfill
```
(The `localization-backfill/commands/` wrapper goes with it.)

- [ ] **Step 4: Update `name:` frontmatter** in each SKILL.md to the new skill name:
`loc/skills/analyze/SKILL.md`→`name: analyze`; `coverage`→`name: coverage`; `detect-nonloc`→`name: detect-nonloc`; `translate-to`→`name: translate-to`; `update-json`→`name: update-json`; `validate-translation`→`name: validate-translation`; `backfill`→`name: backfill`.

- [ ] **Step 5: Fix check-i18n script refs** in `loc/skills/analyze/SKILL.md` and `loc/skills/coverage/SKILL.md`: replace every `${CLAUDE_PLUGIN_ROOT}/skills/analyze-localization-files/scripts/check-i18n.py` and `${CLAUDE_PLUGIN_ROOT}/skills/validate-localization-coverage/scripts/check-i18n.py` with `${CLAUDE_PLUGIN_ROOT}/scripts/check-i18n.py`. Reword the verbose `${CLAUDE_PLUGIN_ROOT}` paragraph so it points at `${CLAUDE_PLUGIN_ROOT}/scripts/check-i18n.py` (plugin-root scripts/, not a `skills/<skill>/` subpath).

- [ ] **Step 6: Update self-reference example paths** in all 7 SKILL.md: `efitz-skills/<oldplugin>/` → `efitz-skills/loc/`; `skills/<oldskill>/` → `skills/<newskill>/`. backfill keeps `${CLAUDE_PLUGIN_ROOT}/scripts/find_duplicate_localizations.py` (valid).

- [ ] **Step 7: Update intra-loc `[[wiki-links]]`** in `loc/skills/backfill/SKILL.md` and `loc/skills/coverage/SKILL.md` per the rename list in the header.

- [ ] **Step 8: Write `loc/.claude-plugin/plugin.json`**
```json
{
  "name": "loc",
  "version": "1.0.0",
  "description": "Localization/i18n toolkit: analyze missing keys, measure coverage, detect non-localizable strings, translate, validate translations, update JSON locale files, and backfill every locale. Use for i18n auditing, translation, and locale-file maintenance.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 9: Self-check & report**
```bash
ls loc/scripts/   # check-i18n.py + find_duplicate_localizations.py
ls loc/skills/    # 7 dirs
rg -l 'CLAUDE_PLUGIN_ROOT}/skills/(analyze-localization-files|validate-localization-coverage)' loc/ || echo "no stale check-i18n subpath refs"
```
Return a summary of files moved/edited and any anomalies.

---

### Task 2: Build the `security` plugin

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1: Move skills, remove old dirs**
```bash
cd /Users/efitz/Projects/skills
mkdir -p security/skills
mv plugin-vetter/skills/plugin-vetter security/skills/vet-plugin
mv race-condition-audit/skills/race-condition-audit security/skills/race-cond
rm -rf plugin-vetter race-condition-audit
```
- [ ] **Step 2: Frontmatter** — `security/skills/vet-plugin/SKILL.md`→`name: vet-plugin`; `security/skills/race-cond/SKILL.md`→`name: race-cond`.
- [ ] **Step 3: Self-reference paths** — replace `efitz-skills/plugin-vetter/`→`efitz-skills/security/`, `efitz-skills/race-condition-audit/`→`efitz-skills/security/`, and any `skills/plugin-vetter/`→`skills/vet-plugin/`, `skills/race-condition-audit/`→`skills/race-cond/`.
- [ ] **Step 4: plugin.json** `security/.claude-plugin/plugin.json`:
```json
{
  "name": "security",
  "version": "1.0.0",
  "description": "Security toolkit: vet plugins/skills before install (vet-plugin) and audit code for race conditions and concurrency bugs (race-cond). Use before installing third-party agent extensions or when reviewing concurrent code.",
  "author": { "name": "efitz" }
}
```
- [ ] **Step 5: Report** files moved/edited.

---

### Task 3: Build the `github` plugin

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1: Move skills + backlog script, drop wrapper, remove old dirs**
```bash
cd /Users/efitz/Projects/skills
mkdir -p github/skills github/scripts
mv backlog-next/skills/backlog-next github/skills/backlog
mv backlog-next/scripts/gh-issues.py github/scripts/gh-issues.py
mv file-github-bug/skills/file-github-bug github/skills/file-bug
rm -rf backlog-next file-github-bug
```
- [ ] **Step 2: Frontmatter** — `github/skills/backlog/SKILL.md`→`name: backlog`; `github/skills/file-bug/SKILL.md`→`name: file-bug`.
- [ ] **Step 3: Self-reference paths** — `efitz-skills/backlog-next/`→`efitz-skills/github/`, `efitz-skills/file-github-bug/`→`efitz-skills/github/`, `skills/backlog-next/`→`skills/backlog/`, `skills/file-github-bug/`→`skills/file-bug/`. backlog keeps `${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py` (valid at new plugin root).
- [ ] **Step 4: plugin.json** `github/.claude-plugin/plugin.json`:
```json
{
  "name": "github",
  "version": "1.0.0",
  "description": "GitHub workflow toolkit: pick the next issue to work on from a milestone/backlog (backlog) and file detailed bug reports into a repo/Project (file-bug). Use for issue triage and bug filing.",
  "author": { "name": "efitz" }
}
```
- [ ] **Step 5: Report** files moved/edited.

---

### Task 4: Build the `ui` plugin

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1**
```bash
cd /Users/efitz/Projects/skills
mkdir -p ui/skills
mv visual-regression-triage/skills/visual-regression-triage ui/skills/vrt
rm -rf visual-regression-triage
```
- [ ] **Step 2: Frontmatter** — `ui/skills/vrt/SKILL.md`→`name: vrt`.
- [ ] **Step 3: Self-reference paths** — `efitz-skills/visual-regression-triage/`→`efitz-skills/ui/`, `skills/visual-regression-triage/`→`skills/vrt/`.
- [ ] **Step 4: plugin.json** `ui/.claude-plugin/plugin.json`:
```json
{
  "name": "ui",
  "version": "1.0.0",
  "description": "UI testing toolkit: triage Playwright visual-regression (screenshot) failures — baseline vs actual vs diff, framed against task context, to decide bug vs expected change (vrt).",
  "author": { "name": "efitz" }
}
```
- [ ] **Step 5: Report**.

---

### Task 5: Build the `wiki` plugin

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1**
```bash
cd /Users/efitz/Projects/skills
mkdir -p wiki/skills
mv verify-migrate-doc/skills/verify-migrate-doc wiki/skills/verify-doc
rm -rf verify-migrate-doc
```
- [ ] **Step 2: Frontmatter** — `wiki/skills/verify-doc/SKILL.md`→`name: verify-doc`.
- [ ] **Step 3: Self-reference paths** — `efitz-skills/verify-migrate-doc/`→`efitz-skills/wiki/`, `skills/verify-migrate-doc/`→`skills/verify-doc/`.
- [ ] **Step 4: plugin.json** `wiki/.claude-plugin/plugin.json`:
```json
{
  "name": "wiki",
  "version": "1.0.0",
  "description": "Documentation toolkit: verify a doc's accuracy against source code and external references, then migrate it into a project wiki (verify-doc).",
  "author": { "name": "efitz" }
}
```
- [ ] **Step 5: Report**.

---

### Task 6: Build the `dev` plugin (dedupe — has script + 3 agents)

**Subagent — filesystem + edits only, NO git.**

- [ ] **Step 1: Move skill, script, agents; drop wrapper; remove old dir**
```bash
cd /Users/efitz/Projects/skills
mkdir -p dev/skills dev/scripts dev/agents
mv dedupe/skills/dedupe dev/skills/dedupe
mv dedupe/scripts/dedupe-report.py dev/scripts/dedupe-report.py
mv dedupe/agents/dedupe-analyzer.md dev/agents/dedupe-analyzer.md
mv dedupe/agents/dedupe-grouper.md dev/agents/dedupe-grouper.md
mv dedupe/agents/dedupe-deduplicator.md dev/agents/dedupe-deduplicator.md
rm -rf dedupe
```
- [ ] **Step 2: Frontmatter** — `dev/skills/dedupe/SKILL.md` keeps `name: dedupe` (skill name unchanged).
- [ ] **Step 3: Self-reference paths** — `efitz-skills/dedupe/`→`efitz-skills/dev/`. SKILL.md keeps `${CLAUDE_PLUGIN_ROOT}/scripts/dedupe-report.py` and `${CLAUDE_PLUGIN_ROOT}/agents/dedupe-*.md` (valid at new plugin root). Note `skills/dedupe/` subpath is unchanged (skill still named dedupe).
- [ ] **Step 4: plugin.json** `dev/.claude-plugin/plugin.json`:
```json
{
  "name": "dev",
  "version": "1.0.0",
  "description": "Developer toolkit: find and analyze duplicate or overlapping functionality across a codebase (dedupe). Supports Go, Python, and TypeScript; orchestrates per-file analysis, grouping, and deep comparison via worker agents.",
  "author": { "name": "efitz" }
}
```
- [ ] **Step 5: Report**.

---

### Task 7: Rewrite `.claude-plugin/marketplace.json` (orchestrator)

- [ ] Replace the 16 plugin entries with 8. Keep the existing `writing` and `deps` entries verbatim. Add/replace with these 6 (categories per spec):
  - `loc` → category `localization`, source `./loc`
  - `security` → category `security`, source `./security`
  - `github` → category `development`, source `./github`
  - `ui` → category `development`, source `./ui`
  - `wiki` → category `documentation`, source `./wiki`
  - `dev` → category `development`, source `./dev`
  Use each plugin's plugin.json `description` as the marketplace `description`.
- [ ] Validate JSON: `python3 -c "import json;print(len(json.load(open('.claude-plugin/marketplace.json'))['plugins']))"` → expect `8`.

---

### Task 8: Rewrite `scripts/verify-marketplace.sh` (orchestrator)

- [ ] Restructure to validate multi-skill plugins. Replace the `PLUGINS` array with a plugin→skills map:
```bash
# "plugin:category:skill1,skill2,..."
declare -a PLUGINS=(
  "loc:localization:analyze,coverage,detect-nonloc,translate-to,update-json,validate-translation,backfill"
  "security:security:vet-plugin,race-cond"
  "github:development:backlog,file-bug"
  "ui:development:vrt"
  "wiki:documentation:verify-doc"
  "dev:development:dedupe"
  "writing:writing:boring"
  "deps:development:bump"
)
```
  For each plugin: plugin.json exists + `name==plugin` + `version==1.0.0`; marketplace entry exists with matching category; for each skill in the list, `<plugin>/skills/<skill>/SKILL.md` exists with frontmatter `name==<skill>`.
- [ ] Set expected plugin count to **8**.
- [ ] Bundled-scripts presence check: `loc/scripts/check-i18n.py`, `loc/scripts/find_duplicate_localizations.py`, `github/scripts/gh-issues.py`, `dev/scripts/dedupe-report.py`.
- [ ] Agents check: `dev/agents/dedupe-{analyzer,grouper,deduplicator}.md` exist with a `name:` frontmatter, and `dev/skills/dedupe/SKILL.md` references each via `${CLAUDE_PLUGIN_ROOT}/agents/<agent>.md`.
- [ ] Remove the command-wrapper section entirely (all dropped). Keep the legacy-path scan and the `repo-root commands/ removed` check.
- [ ] Add a check: no `*/commands/` dirs exist under any plugin.

---

### Task 9: Update root `README.md` (orchestrator)

- [ ] Replace the per-plugin sections with one section per new plugin (loc, security, github, ui, wiki, dev, writing, deps), each listing its skills in one line. Keep it terse.

---

### Task 10: Stage, validate, commit, push (orchestrator)

- [ ] `git add -A` (review `git status` first — only expected renames/moves + shared-file edits).
- [ ] `git diff --cached --find-renames --name-status -M | rg '^R' | wc -l` — confirm moved skill dirs detected as renames.
- [ ] Run `bash scripts/verify-marketplace.sh` → expect **0 FAIL**, 8 plugins. Fix any failures.
- [ ] Spot checks:
```bash
test ! -d analyze-localization-files && echo "old loc dirs gone"
find . -path ./.git -prune -o -type d -name commands -print | grep -v node_modules || echo "no commands/ dirs"
ls loc/scripts/check-i18n.py dev/agents/dedupe-analyzer.md
rg -rn 'efitz-skills/(analyze-localization-files|plugin-vetter|backlog-next|dedupe|visual-regression-triage|verify-migrate-doc)/' --glob '*/skills/**/SKILL.md' || echo "no stale old-plugin example paths"
```
- [ ] Commit:
```bash
git commit -m "Regroup 16 single-skill plugins into 8 multi-skill plugins"
```
- [ ] Push: `git push`.
- [ ] Print the `/plugin` reinstall commands for the user (uninstall old set, install loc/security/github/ui/wiki/dev; writing/deps already installed but writing reinstall still pending from earlier).

## Self-review notes

- Spec coverage: every spec convention (1–10) maps to a task. ✓
- check-i18n dedup → Task 1 Step 2. Wiki-links → Task 1 Step 7. Wrappers dropped → Tasks 1/3/6 + Task 8 removes the check. ✓
- Skill name unchanged for `dedupe` (Task 6 Step 2) and `validate-translation` (stays). ✓
- No placeholders; all `mv`/JSON shown literally. ✓
