# Plugin Renaming and Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `estack` plugin a descriptive name, merge `profile` + `dependency-model` into `discover`, move `dev` to `old-skills` as `sem`, and add four shortcut skills, with every live reference updated.

**Architecture:** Four stages on one branch (`chore/plugin-renaming`), each commit green on the four exit checks. Renames are `git mv` plus a scripted rewrite driven by an explicit rule table (never a blind substitution, because `cats`, `openapi`, `github`, `env`, `dev` are also tool or ordinary words); the rule table doubles as the final sweep. The `discover` merge first pins every directory-wide test guard to explicit per-origin lists, then moves files.

**Tech Stack:** git, git-filter-repo, uv (`uv run` for everything), pytest/unittest, ruff, bash, `mmdc` via `npx` (nvm node).

**Spec:** `docs/superpowers/specs/2026-11-21-plugin-renaming-design.md`

## Global Constraints

- Final names: `cats`→`test-api-fuzzing`, `itest`→`test-integration`, `ui`→`test-ui`, `openapi`→`test-api-workflows`, `github`→`issues`, `deps`→`dependencies`, `loc`→`localization`, `env`→`environment`, `profile`+`dependency-model`→`discover`, `dev`→`sem` in `old-skills`. `session` unchanged. `estack` ends with 10 plugins.
- Skill renames only: `itest:design`→`integration-test-plan`, `profile:report`→`project-report`, `dependency-model:report`→`dependency-report`.
- Not plugin references, never rewritten: the CATS tool (`cats` binary, `cats_tool.py`, `catslib`, `.local/cats/`), OpenAPI the standard (`.local/openapi/`, "OpenAPI spec", `openapi:` YAML keys), GitHub the product, `gh`. Python library names (`catslib`, `bumplib`) and test file names keep their names.
- Versions: renamed plugins keep `version`; no `contract_version` changes; `discover` is `1.0.0`. Marketplace `category` values do not change.
- Labels switch by text substitution only; add no `const` and no label validation.
- `docs/superpowers/**` is historical and is never edited (except this plan's checkboxes).
- Exit checks, run after every commit, in both repos where touched: `uv run ruff check .`, `uv run pytest -q`, `uv run scripts/gen_codex_manifests.py --check`, `bash scripts/verify-marketplace.sh`.
- No PRs in either marketplace repo: merge locally into `main`. **Every push is its own step and needs Eric's explicit approval:** stop, send the one-line `Approve: ...` text given in the step, and wait. Never push on your own.
- American English; never `git add -A`; `rg` always with an explicit path.

## Review Focus

1. **Machines with the old names installed** (stale `~/.codex/hooks.json` entry pointing at `cache/estack/github/`, `cats@estack` still installed, a bare `/dependency-model` resolving to the old plugin): the spec declares no backward compatibility, so the user must be told, not surprised. Pinned by `test_codex_hook_resolves_the_issues_plugin` (Task 3) and the reinstall step (Task 7).
2. **A line holding both a tool name and a plugin reference** (`cats_tool.py:113` "No .local/cats/config.yaml found. Run /cats:init"): only the invocation changes. Pinned by the rewrite script's self-test (Task 3).
3. **Re-running or interrupting the rewrite script**: it must write nothing unless every expectation holds, and a second run must fail loudly, not corrupt. Pinned by the self-test and Task 3 Step 6.
4. **A new schema added to `discover/references/contracts/` with no origin**: must fail a test, not go unguarded. Pinned by `tests/test_discover_origins.py` (Task 4).
5. **A shortcut that names a skill outside its plugin, or whose chain is extracted as empty**: must fail, not pass vacuously. Pinned by `tests/test_shortcut_skills.py` (Task 5).

---

## Conventions used by every task

- `SCRATCH` is your session scratchpad directory. Scripts longer than one line go in `$SCRATCH/*.sh`, start with `set -euo pipefail`, and are run with `bash`.
- Line numbers are as of `main` at `154c156`; an anchor string is quoted wherever an earlier task shifts them.
- The pytest pass counts and `PASS:` counts in verification steps are predictions computed from the baseline (1390 passed, `PASS: 39`). `FAIL: 0` and zero test failures are requirements; a different count must be explained in the task report (which tests were added or removed), never forced.
- **Checks.** `bash "$SCRATCH/checks.sh" <repo>` prints the four summary lines (write it once in Task 1):

```bash
#!/usr/bin/env bash
set -uo pipefail
cd "$1"
uv run ruff check . 2>&1 | tail -1
uv run pytest -q 2>&1 | tail -1
uv run scripts/gen_codex_manifests.py --check 2>&1 | tail -1
REPO="$1" bash scripts/verify-marketplace.sh 2>&1 | rg -e '^(PASS|FAIL):' -e '^  - '
```

- **Mermaid re-render** (every task that edits the graph in `docs/ARCHITECTURE.md`): extract the block with `awk '/^```mermaid$/{f=1;next} /^```$/{f=0} f' docs/ARCHITECTURE.md > "$SCRATCH/arch.mmd"`, then `export NVM_DIR=~/.nvm; . "$NVM_DIR/nvm.sh"; npx -y -p @mermaid-js/mermaid-cli mmdc -i "$SCRATCH/arch.mmd" -o "$SCRATCH/arch.svg"`. Expected: exit 0 and a non-empty SVG. Keep existing node and subgraph IDs; change labels only, unless a step says otherwise.
- After each `git mv <old> <new>`, the old directory may linger holding only ignored files (`__pycache__`, `.ruff_cache`, `.DS_Store`). Confirm `git ls-files <old>` prints nothing, then `rm -rf <old>`.

## The rewrite script (used by Tasks 3, 4, 6, 7)

`$SCRATCH/rename_plugins.py`, stdlib only, run as `uv run python "$SCRATCH/rename_plugins.py" ...` from the target repo. Not committed.

**CLI contract**

| Invocation | Behavior |
|---|---|
| `--self-test` | Runs the embedded cases below against the rule engine. Prints `self-test: N cases, N passed, 0 failed`; exit 1 on any failure. |
| `--repo PATH --stage {2,3,outside}` | Dry run. Prints one line per (plugin, rule) with its match count; exit 1 naming each rule marked "must match" that matched zero times. Writes nothing. |
| `... --apply` | Counts everything first. If any "must match" rule has zero matches, writes nothing and exits 1 (`0 matches for <plugin> <rule>: already applied, or run before git mv?`). Otherwise rewrites files, writes per-file detail to `$SCRATCH/rename-stage<N>.log`, prints `replacements: M in K files`. |
| `--repo PATH --stage {2,3,outside,all} --expect-none` | Exit 0 and `expect-none: 0 matches` only if no rule matches anywhere; otherwise lists `file:line: text` and exits 1. This is the idempotence check and the final precise sweep. |

Files considered: `git ls-files` in `--repo`, minus `docs/superpowers/**`, `uv.lock`, `.agents/**`, `*/.codex-plugin/**` (the last two are regenerated). State: a second `--apply` exits 1 and writes nothing; it never leaves a partial rewrite because counting precedes writing; if the process dies mid-write, `git restore .` (tracked files only; the `git mv`s stay staged) and rerun.

**Plugin table** (`SKILLS` is the label alternation, longest first; it includes contract labels that are not skills)

| Stage | OLD | NEW | SKILLS | R0 special |
|---|---|---|---|---|
| 2 | `cats` | `test-api-fuzzing` | analyze, fp, init, report, run | |
| 2 | `itest` | `test-integration` | conventions, critique, state | `design`→`integration-test-plan` |
| 2 | `ui` | `test-ui` | vrt | |
| 2 | `openapi` | `test-api-workflows` | arazzo, init | |
| 2 | `github` | `issues` | backlog, create-issue | |
| 2 | `deps` | `dependencies` | bump | |
| 2 | `loc` | `localization` | analyze, backfill, coverage, detect-nonloc, translate-to, update-json, validate-translation | |
| 2 | `env` | `environment` | check | |
| 3 | `profile` | `discover` | docs, journeys, stack, topology | `report`→`project-report` |
| 3 | `dependency-model` | `discover` | config, network, package, platform, security, service, synthesize, discovery, synthesis | `report`→`dependency-report` |
| sweep only | `dev` | (none) | dedupe, sem-annotate, sem-auto | |

**Rule table** (applied in this order per plugin; Python `re`)

| Rule | Pattern | Replacement | Files | Must match for |
|---|---|---|---|---|
| R0 | `(?<![\w.-])OLD:OLDSKILL(?![\w-])` | `NEW:NEWSKILL` | all | itest, profile, dependency-model |
| R1 | `(?<![\w.-])OLD:(SKILLS)(?![\w-])` | `NEW:\1` | all | all but ui |
| R2 | `cache/estack/OLD/` | `cache/estack/NEW/` | all | github, deps, loc, env |
| R3 | `(?<![\w.-])OLD/(scripts\|skills\|references\|hooks\|agents\|requirements\.json)\b` | `NEW/\1` | all | cats, github, deps, loc, env, profile, dependency-model |
| R4 | `"plugin": "OLD"` | `"plugin": "NEW"` | `NEW/requirements.json` | stage 2: all |
| R5 | `"name": "OLD"` and `"source": "./OLD"` | same with NEW | `NEW/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` | stage 2: all |
| R6 | `"OLD:(localization\|development\|testing\|productivity):` | `"NEW:\1:` | `scripts/verify-marketplace.sh` | stage 2: all |
| R7 | `(REPO\|PLUGIN\|parents\[1\])(\s*/\s*)"OLD"` | `\1\2"NEW"` | `tests/*.py` | itest, openapi, github, env, profile, dependency-model |
| R8 | `(?<![\w.-])OLD plugin\b` | `NEW plugin` | all | cats, github, env, profile, dependency-model |
| R9 | `` `OLD` `` | `` `NEW` `` | only the F9 list | itest, ui, github, deps, loc, env, profile |
| R10 | `(?m)^### OLD\b` | `### NEW` | `README.md`, `docs/ARCHITECTURE.md` | stage 2: all |

In this table `\|` is Markdown escaping for the regex alternation `|`. R4, R5, R6 and R10 run in stage 2 only (stage 3 writes the merged manifest, `PLUGINS` entry and doc sections by hand). R9 never runs for `cats`, `openapi` or `dependency-model`. In `--expect-none` mode every rule is evaluated for every row it can apply to, whatever its stage (the R9 exclusions still hold; the `dev` row has no NEW, so its path-scoped rules are skipped). **F9** (post-rename paths): `README.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`, `test-integration/references/test-design.md`, `environment/references/writing-declarations.md`, `environment/skills/check/SKILL.md`; stage 3 adds `test-integration/skills/*/SKILL.md` and `tests/test_itest_coupling.py`. Everywhere else a backticked `` `github` ``, `` `env` ``, `` `cats` `` or `` `deps` `` is an adapter name, a config mechanism, the binary, or an issue label, and stays.

**Stage `outside`** (other repos; all must-match flags off, `--expect-none` used after): `(?<![\w.-])cats:(analyze|fp|init|report|run|\*)`→`test-api-fuzzing:\1`; `cats@efitz-skills`→`test-api-fuzzing@estack`; `cache/efitz-skills/cats/`→`cache/estack/test-api-fuzzing/`; `Projects/skills/cats\b`→`Projects/skills/test-api-fuzzing`; `(?<![\w.-])cats plugin\b`→`test-api-fuzzing plugin`; `(?<![\w.-])deps:bump\b`→`dependencies:bump`.

**Self-test cases** (each is input → expected; "same" means unchanged)

- `Run /cats:init to create .local/cats/config.yaml` → `Run /test-api-fuzzing:init to create .local/cats/config.yaml`
- `"cats/scripts",` → `"test-api-fuzzing/scripts",`; `itest:design` → `test-integration:integration-test-plan`; `itest:state` → `test-integration:state`
- `REPO / "itest" / "skills"` → `REPO / "test-integration" / "skills"`; `root / "env" / "requirements.json"` → same
- `cache/estack/loc/<version>/` → `cache/estack/localization/<version>/`; `"loc:localization:analyze` (in `scripts/verify-marketplace.sh`) → `"localization:localization:analyze`
- `profile:report` → `discover:project-report`; `dependency-model:report` → `discover:dependency-report`; `dependency-model:synthesis` → `discover:synthesis`; `dependency-model:synthesize` → `discover:synthesize`
- Same: `brew install endava/tap/cats`, `import catslib`, `test/results/cats/`, `openapi: 3.1.0`, `.local/openapi/config.yaml`, `.github/workflows/ci.yml`, `https://github.com/Endava/cats`, `"codeHost": "github"`, `"github:o/r"`, `gh auth login`, `2>/dev/null`, `process.env.API_URL`, `mechanism="env"`, `{"integration", "it", "itest"}`, `font: system-ui`, `chore(deps): bump`, `dependency-model-<key>`

---

### Task 1: Stage 1a — bring `dev` into `old-skills` as `sem`

**Files** (all in `/Users/efitz/Projects/old-skills`, branch `feat/sem-plugin`):
- Create (from filtered history): `sem/**` (13 files), `tests/test_sem_annotate.py`, `tests/test_sem_db.py`, `tests/test_sem_scope.py`, `tests/test_dedupe.py`
- Modify: `sem/.claude-plugin/plugin.json`, `sem/requirements.json`, `sem/skills/sem-annotate/SKILL.md:60,87`, `sem/skills/dedupe/SKILL.md:68`, `.claude-plugin/marketplace.json`, `scripts/verify-marketplace.sh`, `pyproject.toml`, `tests/__init__.py`, `README.md`; regenerated `.agents/plugins/marketplace.json`, `sem/.codex-plugin/plugin.json`

**Interfaces:**
- Consumes: `/Users/efitz/Projects/skills` `main` still containing `dev/` (read-only here).
- Produces: `old-skills` `main` with plugin `sem` (skills `dedupe`, `sem-annotate`, `sem-auto`), which Task 2 relies on before deleting `dev`.

The dev-only test set is exactly those four files: they import only `sem_annotate`, `sem_db`, `sem_scope`, `dedupe` and the stdlib, use no fixtures directory, and carry no `sys.path.insert` lines.

- [ ] **Step 1: Write `$SCRATCH/checks.sh`** (Conventions) and record baselines: `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/old-skills` → `All checks passed!`, `116 passed, 9 subtests passed`, `OK: 5 Codex manifests in sync`, `PASS: 15`, `FAIL: 0`. In `skills`: `uv run pytest -q tests/test_sem_annotate.py tests/test_sem_db.py tests/test_sem_scope.py tests/test_dedupe.py` → `97 passed`.

- [ ] **Step 2: Filter a fresh clone**

```bash
git clone --no-local --branch main /Users/efitz/Projects/skills "$SCRATCH/dev-extract"
git -C "$SCRATCH/dev-extract" filter-repo --path dev --path tests/test_sem_annotate.py \
  --path tests/test_sem_db.py --path tests/test_sem_scope.py --path tests/test_dedupe.py \
  --path-rename dev/:sem/
```

If `$SCRATCH/dev-extract` already exists from a failed run, delete it and start this step again.

- [ ] **Step 3: Prove nothing was lost, before any edit**

`git -C /Users/efitz/Projects/skills rev-parse main:dev` must equal `git -C "$SCRATCH/dev-extract" rev-parse HEAD:sem` (tree `412c40bd31a320abf55a2fbb708a6828d014891b` at `154c156`); each of the four `main:tests/<file>` blob hashes must equal `HEAD:tests/<file>` in the clone; `git -C "$SCRATCH/dev-extract" ls-files | wc -l` is `17`. Stop on any mismatch.

- [ ] **Step 4: Merge into `old-skills` without committing**

```bash
cd /Users/efitz/Projects/old-skills && git checkout -b feat/sem-plugin
git remote add dev-extract "$SCRATCH/dev-extract" && git fetch dev-extract
git merge --allow-unrelated-histories --no-commit dev-extract/main
git remote remove dev-extract
```

- [ ] **Step 5: Rename and register (same commit as the merge, so the commit is green)**

- `sem/.claude-plugin/plugin.json`: `"name": "sem"`; version `2.4.4` and description unchanged. `sem/requirements.json`: `"plugin": "sem"`.
- `.claude-plugin/marketplace.json`: add `{name: "sem", description: <dev's description from skills marketplace.json:10>, source: "./sem", category: "development"}`.
- `scripts/verify-marketplace.sh`: `PLUGINS` += `"sem:development:dedupe,sem-annotate,sem-auto"`; `SCRIPTS` += `sem/scripts/dedupe.py`, `sem/scripts/sem_annotate.py`; port the `dev worker agents` section (skills `scripts/verify-marketplace.sh:139-156`) with every `dev` → `sem`.
- `pyproject.toml`: add `"sem/scripts"` to `[tool.ty.environment] extra-paths` and `[tool.pytest.ini_options] pythonpath`; copy the `[[tool.ty.overrides]]` block (skills `pyproject.toml:59-68`). `tests/__init__.py`: add `"sem/scripts"` to the `_rel` tuple.
- `sem/skills/sem-annotate/SKILL.md:87`: `dev:SEM Describer` → `sem:SEM Describer`. Lines `:60` and `sem/skills/dedupe/SKILL.md:68`: replace the "run `/env:check dev` if the env plugin is installed; otherwise probe directly" clause with a direct `sem --version` probe (estack's environment check only sees plugins in its own marketplace).
- `README.md`: "Four plugins" → "Five plugins"; add `### sem` with the three bullets from skills `README.md:67-69`.
- `uv run scripts/gen_codex_manifests.py`.
- `tests/test_sem_annotate.py:405,413` keep `"dev/scripts/sem_annotate.py"` (opaque payload data).

- [ ] **Step 6: Verify, commit**

`bash "$SCRATCH/checks.sh" /Users/efitz/Projects/old-skills` → `All checks passed!`, `213 passed, 9 subtests passed`, `OK: 6 Codex manifests in sync`, `PASS: 24`, `FAIL: 0`. The four dev test files alone → `97 passed` (identical to Step 1). If ruff reports import sorting in `sem/scripts`, add the named modules to `known-first-party` and rerun. Commit the merge: `feat(sem): import the dev plugin from estack as sem, history preserved`.

- [ ] **Step 7: Merge locally** — `git checkout main && git merge --no-ff feat/sem-plugin`, rerun checks (same output), `git branch -d feat/sem-plugin`.

- [ ] **Step 8: PUSH GATE** — stop and ask: `Approve: git push origin main in /Users/efitz/Projects/old-skills`. Push only after approval. If declined, continue; Task 7 repeats the gate.

### Task 2: Stage 1b — remove `dev` from `estack`

**Files** (`/Users/efitz/Projects/skills`, new branch `chore/plugin-renaming` from `main`):
- Delete: `dev/**`, `tests/test_sem_annotate.py`, `tests/test_sem_db.py`, `tests/test_sem_scope.py`, `tests/test_dedupe.py`
- Modify: `.claude-plugin/marketplace.json:10`, `scripts/verify-marketplace.sh:46,121-122,139-156`, `pyproject.toml:54,61,77`, `tests/__init__.py:4,37`, `tests/test_env_declarations.py:14,38`, `tests/test_dependency_model_coupling.py:289`, `env/references/writing-declarations.md:73`, `README.md:3,39-40,65-71`, `docs/ARCHITECTURE.md:64-68,121-122,147,252-258,281`; regenerated `.agents/plugins/marketplace.json`

**Interfaces:**
- Consumes: Task 1 Step 6 green (the plugin exists in `old-skills`).
- Produces: an 11-plugin tree; `EXEMPLAR_PLUGINS = ["env", "github"]`; README says "Eleven plugins".

- [ ] **Step 1:** `git checkout -b chore/plugin-renaming`; `git rm -r dev` plus the four test files; `rm -rf dev`.
- [ ] **Step 2: Edit the listed files.** Remove the marketplace entry, the `PLUGINS` line, both `dev/scripts/*` `SCRIPTS` lines, and the whole `dev worker agents` section. Drop `"dev/scripts"` from both `pyproject.toml` lists and the `_rel` tuple; drop `sem_*` from the `tests/__init__.py` docstring and the `sa.sem_blame` example from the ty-override comment. `EXEMPLAR_PLUGINS = ["env", "github"]` and rename `test_three_exemplar_declarations_exist` → `test_exemplar_declarations_exist`. `"Twelve plugins"` → `"Eleven plugins"` in the test and in `README.md:3`. `env/references/writing-declarations.md:73`: the minimal single-hard-tool example `dev/requirements.json` → `env/requirements.json` (one required tool, `uv`). README: delete the `### dev` section and the `dev:dedupe` clause of the Architecture paragraph. ARCHITECTURE: delete the `dev` subgraph, the two `d_*` edges, `envchk ... .-> dev`, the `### dev` catalog section and the "Find dead code and duplication" entry-point row. `docs/upstream/sem-orphaned-anchor-staleness.md` stays (a retracted upstream report about this repo's issue #30).
- [ ] **Step 3:** `uv run scripts/gen_codex_manifests.py`; re-render Mermaid (Conventions).
- [ ] **Step 4: Verify** — `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/skills` → `All checks passed!`, `1293 passed` (1390 − 97), `OK: 12 Codex manifests in sync`, `PASS: 30`, `FAIL: 0`.
- [ ] **Step 5: Commit** — `chore!: move dev to old-skills as sem`.

### Task 3: Stage 2 — eight mechanical renames and `integration-test-plan`

**Files:**
- Create (scratch, not committed): `$SCRATCH/rename_plugins.py`
- Rename: `cats`→`test-api-fuzzing`, `itest`→`test-integration`, `ui`→`test-ui`, `openapi`→`test-api-workflows`, `github`→`issues`, `deps`→`dependencies`, `loc`→`localization`, `env`→`environment`; then `test-integration/skills/design`→`test-integration/skills/integration-test-plan`
- Modify by script: whatever the stage 2 rules match
- Modify by hand: listed in Step 5
- Test: `tests/test_install_sh.py` (one new test)

**Interfaces:**
- Consumes: Task 2's tree.
- Produces: `rename_plugins.py` with the CLI contract above (Tasks 4, 6, 7 reuse it); the eight new plugin directories; skill `test-integration:integration-test-plan`; `EXEMPLAR_PLUGINS = ["environment", "issues"]`.

- [ ] **Step 1: Write the script's self-test cases, then the script.** Run `uv run python "$SCRATCH/rename_plugins.py" --self-test` before the engine exists (expected: fails), then implement to the contract, rule table and cases above. Expected after: `self-test: N cases, N passed, 0 failed`.

- [ ] **Step 2: Write the failing install test** in `tests/test_install_sh.py`:

```python
def test_codex_hook_resolves_the_issues_plugin(self):
    text = INSTALL_SH.read_text(encoding="utf-8")
    self.assertIn("cache/estack/issues/*/scripts/refresh_gh_projects.py", text)
    self.assertNotIn("cache/estack/github/", text)
```

Run `uv run pytest -q tests/test_install_sh.py` → 1 failed (the path still says `github`).

- [ ] **Step 3: Move the directories** — the nine `git mv` commands above, then remove each leftover old directory (Conventions).

- [ ] **Step 4: Dry run, then apply**

`uv run python "$SCRATCH/rename_plugins.py" --repo /Users/efitz/Projects/skills --stage 2` → exit 0, every must-match rule non-zero (approximate counts measured at `154c156`: R1 cats 32, itest 29 incl. R0, openapi 11, github 20, env 6, deps 1, loc 1; R7 itest 10, openapi 4, github 3, env 2; a count far from these is a reason to stop and look). Then the same command with `--apply` → `replacements: M in K files`.

- [ ] **Step 5: Hand edits** (anchors given; none is covered by a rule)

- `test-integration/skills/integration-test-plan/SKILL.md`: frontmatter `name: integration-test-plan`; heading `# design` → `# integration-test-plan`.
- Skill-directory name `design` → `integration-test-plan`: `scripts/verify-marketplace.sh` `PLUGINS` entry (`conventions,critique,integration-test-plan,state`); `tests/test_itest_coupling.py:16` list and `:40,48,56,65,78` path segments; `tests/test_openapi_coupling.py:55`; `README.md:106` bullet; `docs/ARCHITECTURE.md:45` node label and `:202` catalog row; `test-integration/references/test-design.md:4`; "(design)" in `.claude-plugin/marketplace.json` and `test-integration/.claude-plugin/plugin.json` descriptions.
- `tests/test_itest_coupling.py:37`: `assertNotIn("itest", ...)` → `assertNotIn("test-integration", ...)`.
- `tests/test_env_declarations.py:14`: `EXEMPLAR_PLUGINS = ["environment", "issues"]`.
- `test-integration/references/contracts/scenario.schema.json:3`: title `itest scenario set` → `test-integration scenario set`.
- `scripts/verify-marketplace.sh:132,134,136`: the `loc` comment and the two `"loc: check-i18n.py ..."` messages → `localization`.
- `environment/scripts/env_check.py:140,141,149,152`: docstring mentions of the `env` directory → `environment`.
- `issues/skills/create-issue/SKILL.md:179`: `/environment:check github` → `/environment:check issues`; `environment/skills/check/SKILL.md:50`: `--plugin github` → `--plugin issues`.
- `docs/ARCHITECTURE.md:44,51,56`: subgraph labels → `test-integration — integration test design`, `test-api-workflows`, `test-api-fuzzing — API fuzzing` (IDs unchanged).
- Leave alone: `profile/scripts/inventorylib/testfiles.py:10,14` (`"itest"` is a directory-name heuristic); `tests/test_env_check.py` fixture plugin names (`"env"`, `"ui"`, `"github"`, `"dev"` are synthetic temp-dir fixtures; only its line 12 path changes, via R7); `session/scripts/repo-state.sh:125` `== github` (a GitHub-state section).

- [ ] **Step 6: Regenerate and check idempotence** — `uv run scripts/gen_codex_manifests.py`; re-render Mermaid; `uv run python "$SCRATCH/rename_plugins.py" --repo /Users/efitz/Projects/skills --stage 2 --expect-none` → `expect-none: 0 matches`; the same command with `--apply` instead → exit 1, no file changed (`git status --short` identical before and after).

- [ ] **Step 7: Verify** — `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/skills` → `All checks passed!`, `1294 passed`, `OK: 12 Codex manifests in sync`, `PASS: 30`, `FAIL: 0`. Also `rg -n 'test-integration:design|skills/design' . -g '!docs/superpowers/**'` → no output.

- [ ] **Step 8: Commit** — review `git status --short` for stray untracked files, stage the renamed trees and modified files by path, `chore!: rename eight plugins to descriptive names`.

### Task 4: Stage 3 — merge `profile` and `dependency-model` into `discover`

**Files:**
- Create: `tests/discover_origins.py`, `tests/test_discover_origins.py`
- Rename: `profile`→`discover`; every tracked child of `dependency-model/{skills,scripts,references}` into `discover/`; `discover/skills/report`→`project-report` (profile's) and dependency-model's `skills/report`→`discover/skills/dependency-report`
- Delete: `dependency-model/.claude-plugin/plugin.json`, `dependency-model/.codex-plugin/plugin.json`, `dependency-model/requirements.json`
- Modify by hand: `discover/.claude-plugin/plugin.json`, `discover/requirements.json`, `.claude-plugin/marketplace.json`, `scripts/verify-marketplace.sh`, `README.md`, `docs/ARCHITECTURE.md`, `discover/scripts/profile_report.py:58,67`, the test files in Steps 3 and 7
- Modify by script: whatever the stage 3 rules match

**Interfaces:**
- Consumes: `rename_plugins.py`; Task 3's tree.
- Produces: `tests/discover_origins.py`:

```python
PROFILE_SKILLS: tuple[str, ...]      # docs, journeys, project-report, stack, topology
PROFILE_SCHEMAS = ("docs", "journeys", "stack", "topology")
DEPENDENCY_SCHEMAS = ("config", "dependency-core", "discovery", "network", "package",
                      "platform", "security", "service", "synthesis")
def schema_paths(contracts_dir: Path, names: Iterable[str]) -> list[Path]
def schema_drift(contracts_dir: Path, listed: Iterable[str]) -> tuple[list[str], list[str]]
    # (unlisted, missing): schema basenames present but not listed, and listed but absent; each sorted
```

**Commit A — pin the guards (no file moves; `PROFILE_SKILLS` uses today's skill name `report`)**

- [ ] **Step 1: Write the failing tests** in `tests/test_discover_origins.py`:

```python
def test_unlisted_schema_is_reported(self):      # tmp dir holding a.schema.json and rogue.schema.json
    self.assertEqual(schema_drift(tmp, ["a"]), (["rogue"], []))
def test_missing_schema_is_reported(self):       # tmp dir holding only a.schema.json
    self.assertEqual(schema_drift(tmp, ["a", "b"]), ([], ["b"]))
def test_real_contract_dirs_match_the_origin_lists(self):
    self.assertTrue(set(PROFILE_SCHEMAS).isdisjoint(DEPENDENCY_SCHEMAS))
    self.assertEqual(schema_drift(REPO / "profile" / "references" / "contracts", PROFILE_SCHEMAS), ([], []))
    self.assertEqual(schema_drift(REPO / "dependency-model" / "references" / "contracts", DEPENDENCY_SCHEMAS), ([], []))
```

- [ ] **Step 2:** `uv run pytest -q tests/test_discover_origins.py` → fails with `ModuleNotFoundError: discover_origins`. Implement `tests/discover_origins.py`; rerun → `3 passed`.

- [ ] **Step 3: Replace every directory-wide glob over the two plugins with the lists**

| Location | Today | Becomes |
|---|---|---|
| `tests/test_profile_contracts.py:48-51,60` | `CONTRACTS.glob("*.schema.json")` and the pinned four-name list | `schema_paths(CONTRACTS, PROFILE_SCHEMAS)` (the pin now lives in `discover_origins`) |
| `tests/test_profile_html_inputs.py:215` | `allowed.update(CONTRACTS.glob(...))` | `allowed.update(schema_paths(CONTRACTS, PROFILE_SCHEMAS))` |
| `tests/test_dependency_model_contracts.py:58-63` | glob equals expected list | every `schema_paths(CONTRACTS, DEPENDENCY_SCHEMAS)` entry `is_file()` |
| `tests/test_dependency_model_contracts.py:280,290,308,417` | loops over the glob | loops over `schema_paths(CONTRACTS, DEPENDENCY_SCHEMAS)` |
| `tests/test_dependency_model_coupling.py:13,53` | `SKILLS` glob; glob names compared to `ALL_SKILLS` | `SKILLS = [skill_path(n) for n in ALL_SKILLS]` (`ALL_SKILLS` at `:16` is already an explicit list); the test asserts each `is_file()` |
| `tests/test_dependency_model_coupling.py:78` and `tests/test_itest_coupling.py:10` | glob of `profile/skills` | paths built from `PROFILE_SKILLS` |

`discover/scripts/validate.py:142` keeps its glob: it only lists valid names in a usage error.

- [ ] **Step 4: Verify and commit** — checks → `1297 passed`, others as Task 3. Commit `test: pin contract and skill guards to explicit per-origin lists`.

**Commit B — the merge**

- [ ] **Step 5: Move files**

`git mv profile discover`; `git mv discover/skills/report discover/skills/project-report`; `git mv dependency-model/skills/report discover/skills/dependency-report`; then `git mv` each remaining child of `dependency-model/skills`, `dependency-model/scripts`, `dependency-model/references` (the four `.md` files, each `contracts/*.schema.json`, each `contracts/examples/*.json`) into the same place under `discover/`. `git rm` the three files listed under Delete after copying `requirements.json`'s tools; `rm -rf dependency-model profile`. A `git mv` that reports a destination collision is a stop condition (the spec verified there are none).

- [ ] **Step 6: Apply the stage 3 rules** — dry run, then `--apply`, as in Task 3 Step 4 (approximate counts at `154c156`: R1+R0 profile 104, dependency-model 38; R7 15 and 29).

- [ ] **Step 7: Hand edits**

- Manifests: `discover/.claude-plugin/plugin.json` (`name: discover`, `version: 1.0.0`, one description naming all 13 skills); one marketplace entry `discover` (`source: ./discover`, category `development`) replacing both; `discover/requirements.json` = union (`plugin: discover`; `syft` stays `required: true`; one `uv` entry with both reasons; `git`, `mmdc`).
- `scripts/verify-marketplace.sh`: one `PLUGINS` entry replacing two: `"discover:development:config,dependency-report,docs,journeys,network,package,platform,project-report,security,service,stack,synthesize,topology"`.
- Both report skills: frontmatter `name:` and `# report` heading → `project-report` / `dependency-report`. Bare `report` mentions that mean the dependency report → `dependency-report`: `discover/skills/synthesize/SKILL.md:69,161`, `discover/skills/service/SKILL.md:152`, `discover/skills/network/SKILL.md:119`, `discover/references/running-discovery.md:5,7,125,132` (`:7` also `skills/report/SKILL.md` → `skills/dependency-report/SKILL.md`), `discover/requirements.json` mmdc `why`.
- `discover/skills/service/SKILL.md:156`: reword to "Never run the inventory script by path; invoke `discover:topology` by name."
- `profile-report.html` → `project-report.html`: `discover/scripts/profile_report.py:58,67`, `discover/skills/project-report/SKILL.md:35,39`, `README.md:100`, `tests/test_profile_html_cli.py:42,167`. `depscanlib/run.py:94` (`dependency-model-<key>`) is unchanged.
- `tests/discover_origins.py`: `report` → `project-report` in `PROFILE_SKILLS`; `tests/test_discover_origins.py` real-dir test → one call: `schema_drift(REPO / "discover" / "references" / "contracts", PROFILE_SCHEMAS + DEPENDENCY_SCHEMAS) == ([], [])`.
- `tests/test_dependency_model_coupling.py`: `LAYER2 = ["dependency-report", "synthesize"]`; `skill_path("report")` → `skill_path("dependency-report")` (`:112,326,332`); `TestRegistration` (`:246-292`): name `discover`, source `./discover`, the new `PLUGINS` string, `data["plugin"] == "discover"`, `"### discover"`, `"Ten plugins"`; `:335` row prefix ``| `dependency-report` | Renders``; `:72` comment.
- `tests/test_dependency_model_references.py:149`: `f"/dependency-model:{category}"` → `f"/discover:{category}"`. `tests/test_itest_coupling.py:30` comment `../profile/...` → `../discover/...`.
- New test in `tests/test_dependency_model_contracts.py`, pinning decision 4:

```python
def test_seeded_by_label_is_not_validated(self):
    schema = resolve_refs(load(CONTRACTS / "discovery.schema.json"), CONTRACTS)
    for label in ("discover:topology", "profile" + ":topology"):   # split: keeps the retired-name sweeps empty
        instance = load(EXAMPLES / "service.example.json")
        instance["seeded_by"]["contract"] = label
        self.assertEqual(validate(instance, schema), [])
```

- `README.md`: "Eleven plugins" → "Ten plugins"; replace `### profile` and `### dependency-model` with one `### discover` section (13 bullets, `**project-report**` and `**dependency-report**`, both explanatory paragraphs).
- `docs/ARCHITECTURE.md`: replace the `profile` and `depmodel` subgraphs with one `subgraph discover["discover — project and dependency discovery"]` holding all `p_*` and `x_*` nodes (labels `project-report — saved artifacts only`, `dependency-report`); the two `envchk` edges become one to `discover`; one `### discover` catalog section (13 rows plus the existing paragraph); reword `:179-181` (the seed relationship is now inside one plugin) and prose still naming `dependency-model` as a plugin. Prose that uses "dependency-model" as the concept, not followed by `:` or `/`, may stay (`discover/references/categories.md:3`, `running-discovery.md:3`, schema titles without a colon).

- [ ] **Step 8: Regenerate; prove the unknown-schema guard on the real directory**

`uv run scripts/gen_codex_manifests.py`; re-render Mermaid; `--stage 3 --expect-none` → `expect-none: 0 matches`. Then `touch discover/references/contracts/rogue.schema.json` and run `uv run pytest -q tests/test_discover_origins.py` → 1 failed, message shows `(['rogue'], [])`; `rm` the file; rerun → `3 passed`. Report both results.

- [ ] **Step 9: Verify and commit** — checks → `All checks passed!`, `1298 passed`, `OK: 11 Codex manifests in sync`, `PASS: 29`, `FAIL: 0`. Commit `feat!: merge profile and dependency-model into discover`.

### Task 5: Stage 4 — shortcut skills

**Files:**
- Create: `discover/skills/dependency-model/SKILL.md`, `discover/skills/project-profile/SKILL.md`, `test-api-fuzzing/skills/api-fuzz/SKILL.md`, `test-api-workflows/skills/api-workflows/SKILL.md`, `tests/test_shortcut_skills.py`
- Modify: `scripts/verify-marketplace.sh` (three `PLUGINS` entries), `README.md`, `docs/ARCHITECTURE.md` (entry-point table), `tests/test_dependency_model_coupling.py` (`PLUGINS` string in `TestRegistration`), plugin and marketplace descriptions where they enumerate skills

**Interfaces:**
- Consumes: Task 4's skill names.
- Produces: four user-invoked skills; `SHORTCUTS` in the test is the single statement of each chain.

- [ ] **Step 1: Write the failing test** `tests/test_shortcut_skills.py`:

```python
SHORTCUTS = {
    ("discover", "dependency-model"): ["synthesize", "dependency-report"],
    ("discover", "project-profile"): ["stack", "docs", "journeys", "topology", "project-report"],
    ("test-api-fuzzing", "api-fuzz"): ["init", "run", "report", "analyze"],
    ("test-api-workflows", "api-workflows"): ["init", "arazzo"],
}
REF = re.compile(r"`/?([a-z0-9-]+):([a-z0-9-]+)`")   # backticked plugin:skill tokens in the body

class TestShortcutSkills(unittest.TestCase):
    def test_frontmatter_disables_model_invocation(self):
        # per shortcut, on the frontmatter block:
        self.assertRegex(front, rf"(?m)^name: {re.escape(name)}$")
        self.assertRegex(front, r"(?m)^disable-model-invocation: true$")

    def test_names_only_skills_in_its_own_plugin(self):
        refs = REF.findall(body)
        self.assertTrue(refs, "no skill references found")
        for ref_plugin, ref_skill in refs:
            self.assertEqual(ref_plugin, plugin)
            self.assertTrue((REPO / plugin / "skills" / ref_skill / "SKILL.md").is_file())

    def test_chain_order_is_pinned(self):
        seen = list(dict.fromkeys(skill for _, skill in REF.findall(body) if skill != name))
        self.assertEqual(seen, chain)
```

Each test loops over `SHORTCUTS` with `subTest`. Run → 3 failed (files missing).

- [ ] **Step 2: Write the four SKILL.md files.** Frontmatter exactly:

```yaml
---
name: dependency-model
description: Shortcut that builds a system's whole dependency model in one command — runs synthesize (topology, the six dependency discovery skills, and the merge), then dependency-report to render docs/dependencies.md. Chains existing skills only.
argument-hint: "[path] [--ref <branch>] [--out <file.md>]"
disable-model-invocation: true
---
```
```yaml
---
name: project-profile
description: Shortcut that profiles a project end to end — runs stack, docs, journeys and topology, saves the four contracts, then project-report to render one offline HTML report. Chains existing skills only.
argument-hint: "[path] [--out <file.html>] [--title <text>] [--no-open]"
disable-model-invocation: true
---
```
```yaml
---
name: api-fuzz
description: Shortcut that runs a whole CATS API fuzzing pass — init when .local/cats/config.yaml is missing, then run, report and analyze. Chains existing skills only.
argument-hint: "[flags passed through to run, e.g. --identity NAME --path PATTERN]"
disable-model-invocation: true
---
```
```yaml
---
name: api-workflows
description: Shortcut that produces an Arazzo workflow spec — init when no OpenAPI spec is recorded in .local/openapi/config.yaml, then arazzo. Chains existing skills only.
argument-hint: "[journeys-doc-path]"
disable-model-invocation: true
---
```

Ordered chains (each skill written in the body as a backticked `` `<plugin>:<skill>` `` token, first mentions in this order):

| Shortcut | Step | Invoke | Arguments and hand-offs |
|---|---|---|---|
| `dependency-model` | 1 | `discover:synthesize` | `[path] [--ref <branch>]` |
| | 2 | `discover:dependency-report` | same `[path] [--ref]`, plus `[--out]`; hand it step 1's synthesis contract so it does not rerun synthesize |
| `project-profile` | 0 | (setup) | `mktemp -d "${TMPDIR:-/tmp}/project-profile-XXXXXX"` as the artifact directory, never inside the target repo |
| | 1 | `discover:stack` | `[path]`; artifact directory as its run dir (it saves `stack.json`) |
| | 2 | `discover:docs` | `[path]` and the stack contract; save its reply as `docs.json` |
| | 3 | `discover:journeys` | `[path]`, stack and docs contracts; save its reply as `journeys.json`; say in the final message that journeys are unconfirmed candidates |
| | 4 | `discover:topology` | `[path]`; artifact directory as its run dir (it saves `topology.json`) |
| | 5 | `discover:project-report` | `<artifact_dir> [--out] [--title] [--no-open]`; report both paths |
| `api-fuzz` | 1 | `test-api-fuzzing:init` | only if `.local/cats/config.yaml` is missing; otherwise say it was skipped |
| | 2 | `test-api-fuzzing:run` | all user flags, unchanged; wait for the campaign; a failed validity gate is a failed step |
| | 3 | `test-api-fuzzing:report` | latest database |
| | 4 | `test-api-fuzzing:analyze` | latest database |
| `api-workflows` | 1 | `test-api-workflows:init` | only if `.local/openapi/config.yaml` is missing or has no `openapi_spec`; otherwise say it was skipped |
| | 2 | `test-api-workflows:arazzo` | `[journeys-doc-path]`; its own preflight offers apply |

Every body also states: a `## Usage` line with the namespaced form, plus a note that the bare form (`/dependency-model`) works in Claude Code when no other command has that name and that Codex uses the namespaced form; skills are invoked by name, never by script path; each chained skill's own confirmation gates apply and are never answered for the user; stop at the first step that fails or that the user declines, reporting `Stopped at step N (<skill>): <reason>` and what completed; no new behavior. Do not write the word "subagent" (`tests/test_plugin_structure.py:110` would then require a fallback note), and do not put another plugin's skill in backticks.

- [ ] **Step 3:** `uv run pytest -q tests/test_shortcut_skills.py` → `3 passed`.

- [ ] **Step 4: Register and document.** `PLUGINS`: `test-api-fuzzing` → `analyze,api-fuzz,fp,init,report,run`; `test-api-workflows` → `api-workflows,arazzo,init`; `discover` → `config,dependency-model,dependency-report,docs,journeys,network,package,platform,project-profile,project-report,security,service,stack,synthesize,topology` (same string in `TestRegistration`). README: a bullet per shortcut in its plugin section, giving bare and namespaced forms and "Codex: namespaced form only". ARCHITECTURE entry-point table: "Understand an unfamiliar repo" → `/project-profile`; "Audit a system's deployment shape and dependencies" → `/dependency-model`; "Fuzz an API" → `/api-fuzz`; "Generate an Arazzo workflow spec" keeps `/test-integration:integration-test-plan` first, then `/api-workflows`. `uv run scripts/gen_codex_manifests.py`.

- [ ] **Step 5: Verify and commit** — checks → `All checks passed!`, `1301 passed`, `OK: 11 Codex manifests in sync`, `PASS: 29`, `FAIL: 0`. Commit `feat: add end-to-end shortcut skills`.

### Task 6: Outside-repo references (local commits only; pushes are in Task 7)

**Files:**
- `/Users/efitz/Projects/tmi`: `Makefile:524,526,534,535,543`, `.claude/CLAUDE.md:48`, `.claude/skills/cats-tmi/SKILL.md:8,10,11,17`, `.claude/skills/test/SKILL.md:111,112,120,161`, `.claude/skills/test-oci/SKILL.md:107,108,116,154`, `scripts/README.md:48`, `.github/workflows/deps-bump.yml:312`
- `/Users/efitz/Projects/agentmesh`: `scripts/cats-precommit.sh:219`, `docs/cats.md:59-69`
- `/Users/efitz/Projects/renamer/CLAUDE.md:51`, `/Users/efitz/Projects/scan-namer/CLAUDE.md:61`
- `~/.claude/commands/bump.md:2,6` (not a repo)

**Interfaces:**
- Consumes: `rename_plugins.py --stage outside`; new plugin names from Tasks 3-5.
- Produces: one unpushed commit per repo.

The spec lists fewer lines than exist (it predates this `rg`); the list above is what `rg` finds today. Tool names stay: `make cats-fuzz`, `CATS_TOOL`, `cats_tool.py`, `.local/cats/`, `api/cats-false-positives.yaml`.

- [ ] **Step 1: Per repo, look before editing.** Record `git -C <repo> branch --show-current` and `git -C <repo> status --short`. Today: `tmi` is on `dev/1.21/settings-fixes`, `agentmesh` and `scan-namer` are on clean `main`, and `renamer/CLAUDE.md` has an uncommitted rewrite that includes line 51. **If a file to edit is already dirty, do not edit or stage it: stop and ask Eric** how to sequence it. Then run the dry run (`--repo <repo> --stage outside`) and compare its hits with the list above; report any extra file.

- [ ] **Step 2: Apply and review.** `--stage outside --apply` in each repo, then `git -C <repo> --no-pager diff --no-ext-diff --stat`. Must not change: `tmi/.github/workflows/deps-bump.yml:243-250` (it vendors `deps/skills/bump` from a pinned `SKILL_SHA` that predates the rename; changing the path without moving the pin breaks tmi CI). Add one comment line above `SKILL_SHA`: "When this SHA moves past the estack plugin rename, change `deps/skills/bump` below to `dependencies/skills/bump`."

- [ ] **Step 3: Verify.** `--stage outside --expect-none` → `expect-none: 0 matches` in each repo. In `tmi`: `make -n cats-fuzz 2>&1 | rg -m1 'uv run .*cats_tool.py'` shows `~/Projects/skills/test-api-fuzzing/scripts/cats_tool.py` (the checkout fallback, which exists while `skills` has the renamed tree checked out; today it resolves to the stale `cache/efitz-skills/cats/0.1.2/`; the new cache path appears after Task 7's reinstall). Run each repo's own done gate if its `CLAUDE.md` declares one that covers docs or Makefile edits, and report it.

- [ ] **Step 4: Exit checks.** No estack file changes in this task: `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/skills` must still print Task 5's output (`All checks passed!`, `1301 passed`, `OK: 11 Codex manifests in sync`, `PASS: 29`, `FAIL: 0`).

- [ ] **Step 5: Commit per repo**, on the branch that is checked out, staging only the edited files: `docs: follow estack plugin renames` (`tmi`: `chore: follow estack plugin renames`).

- [ ] **Step 6:** Edit `~/.claude/commands/bump.md:2,6` with the Edit tool: `deps:bump` → `dependencies:bump`.

### Task 7: Final verification, merge, and pushes

**Files:** none new. `$SCRATCH/sweep-allow.txt` (scratch).

**Interfaces:**
- Consumes: everything above.
- Produces: `main` in both marketplace repos with the work merged; pushes only as approved.

- [ ] **Step 1: Full exit criteria, both repos.** `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/skills` → `All checks passed!`, `1301 passed`, `OK: 11 Codex manifests in sync`, `PASS: 29`, `FAIL: 0`. `bash "$SCRATCH/checks.sh" /Users/efitz/Projects/old-skills` → `213 passed`, `OK: 6 Codex manifests in sync`, `PASS: 24`, `FAIL: 0`.

- [ ] **Step 2: Precise sweep.** `uv run python "$SCRATCH/rename_plugins.py" --repo /Users/efitz/Projects/skills --stage all --expect-none` → `expect-none: 0 matches`.

- [ ] **Step 3: The spec's broad sweep, with its exceptions.** Write `$SCRATCH/sweep-allow.txt` with exactly these eight lines (one regex per line):

```text
\.local/(cats|openapi)/
test/(results/)?cats/
cats:(\s*$|`|\\n| CatsOptions)
openapi:(\\s| ["']?3|\\n)|openapi/swagger
\.github/|"github:o/r"
\bin deps:
env: dict\[|env:"|`env:`|env:\s*$|std::env::|env/file/flag
/dev/null|[a-z]\.dev/|k8s/dev/|prod/dev/|dev/x\.y\.z|dev/test-only
```

In order, these are: the per-repo config folders (decision 4); CATS results and rules directories; the `cats:` YAML section and its Python field; the OpenAPI version key; GitHub the product and an npm spec fixture; a Python loop variable; parameters, Go struct tags, YAML keys and Rust paths named `env`; devices, domains, fixture paths and a branch-name example containing `dev/`. The spec names only the first, fourth and fifth kinds; the rest are ordinary-word collisions the literal sweep cannot avoid.

```bash
rg -n --hidden -g '!.git/**' -g '!docs/superpowers/**' -g '!uv.lock' \
  -e '(^|[^\w-])(cats|itest|ui|openapi|github|deps|loc|env|profile|dependency-model|dev)[:/]' \
  /Users/efitz/Projects/skills | rg -v -f "$SCRATCH/sweep-allow.txt"
```

The leading `(^|[^\w-])` (not `\b`) keeps the new name `test-ui:` from matching as `ui:`. Expected: no output. Any line printed is either a missed plugin reference (fix it, rerun the checks, amend into a `fix:` commit) or a new non-plugin use (add a regex with its reason and report it); never silence a line without classifying it.

- [ ] **Step 4: Mermaid.** Re-render `docs/ARCHITECTURE.md` (Conventions) → exit 0; confirm the SVG contains `discover`, `test-integration`, `test-api-workflows`, `test-api-fuzzing` and none of the eleven old names as a subgraph label (`rg -c 'profile —|dependency-model —|itest —|cats —' "$SCRATCH/arch.svg"` → 0).

- [ ] **Step 5: Merge locally.** `git -C /Users/efitz/Projects/skills checkout main && git merge --no-ff chore/plugin-renaming`; rerun Step 1 for `skills` on `main` (same output). Keep the branch until the push is done.

- [ ] **Step 6: PUSH GATE (old-skills)**, if not approved in Task 1 — `Approve: git push origin main in /Users/efitz/Projects/old-skills`.
- [ ] **Step 7: PUSH GATE (skills)** — `Approve: git push origin main in /Users/efitz/Projects/skills`. After a successful push and an empty `git log origin/main..chore/plugin-renaming`, delete the branch.
- [ ] **Step 8: PUSH GATE (tmi)** — `Approve: git push origin <current branch> in /Users/efitz/Projects/tmi` (name the branch recorded in Task 6).
- [ ] **Step 9: PUSH GATE (agentmesh)** — `Approve: git push origin main in /Users/efitz/Projects/agentmesh`.
- [ ] **Step 10: PUSH GATE (renamer)** — `Approve: git push origin main in /Users/efitz/Projects/renamer` (only if Task 6 produced a commit there).
- [ ] **Step 11: PUSH GATE (scan-namer)** — `Approve: git push origin main in /Users/efitz/Projects/scan-namer`.

Each gate is separate: one approval never covers another repo. The outside repos come after `skills` so that their new names exist upstream first.

- [ ] **Step 12: Hand to Eric (manual, after the skills push).** Ask him to: uninstall the old-name plugins (`cats`, `deps`, `dependency-model` are in `~/.claude/plugins/cache/estack/` today) and run `scripts/install.sh`; remove any `~/.codex/hooks.json` entry that still names `cache/estack/github/` and rerun `scripts/install.sh codex --codex-session-hook` (the installer leaves an existing `refresh_gh_projects.py` entry untouched, so the stale path would otherwise silently do nothing); then type `/dependency-model`, `/project-profile`, `/api-fuzz`, `/api-workflows` and `/integration-test-plan` in a real session. A bare name that does not resolve is reported, not renamed; the namespaced form still works.

- [ ] **Step 13: Report** the four check outputs for both repos, both sweep results, the Task 4 Step 8 before/after proof, which pushes were approved, and any follow-up (file a GitHub issue per item, e.g. the tmi `SKILL_SHA` pin).
