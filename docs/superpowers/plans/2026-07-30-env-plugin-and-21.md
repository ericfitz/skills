# env Plugin + Issue #21 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `env` plugin per its approved spec (`docs/superpowers/specs/2026-07-26-env-check-design.md`), then complete issue #21: requirements declarations for every remaining plugin, preflight retrofits, and undeclared-messaging update.

**Architecture:** Per the spec — read it first; it is authoritative for all behavior (discovery layouts, declaration contract, report categories, exit codes 0/1/2, probe safety). This plan adds only sequencing, file lists, and repo-integration details the spec leaves open. The repo gains a 13th plugin (`env`), registered in the Claude marketplace, with regenerated Codex manifests.

**Tech Stack:** Python 3.11+ stdlib only, unittest-style tests, `uv run pytest`, ruff, existing `scripts/gen_codex_manifests.py`.

## Global Constraints

- The spec file `docs/superpowers/specs/2026-07-26-env-check-design.md` governs all `env` behavior; deviations require stopping and reporting BLOCKED.
- Probes are argv arrays executed with `shell=False`; the checker never reads `~/.keys/`; only declared probes run. These are security invariants — a test must pin each.
- Requirements describe what a plugin needs to run, never what a target repo might need (`go`, `npm` for target repos are explicitly OUT).
- All commits go directly to `main` and are pushed after each task (user instruction). Never `git add -A`.
- Lint `uv run ruff check .`; tests `uv run pytest -q` (suite currently fully green — 686 passed, 0 errors; keep it that way). CI runs on push — check `gh run list --workflow ci` after pushing.
- End every commit message with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_018a81HJnmo8CacJVPNDL127`

---

### Task 1: Declaration contract — schema, authoring guide, three exemplar declarations

**Files:**
- Create: `env/references/requirements.schema.json`, `env/references/writing-declarations.md`, `env/requirements.json`, `github/requirements.json`, `dev/requirements.json`
- Test: `tests/test_env_declarations.py`

**Interfaces:**
- Produces: the schema path `env/references/requirements.schema.json`; declaration files at `<plugin>/requirements.json` (spec's "declaration contract" section defines the shape — `requirements_version`, `plugin`, `tools[]`, `config[]`, `auth[]` with the exact per-entry fields shown in the spec's JSON example). Tasks 2 and 4 consume both.

- [ ] **Step 1: Write failing tests** — `tests/test_env_declarations.py`, unittest style matching `tests/test_plugin_structure.py` (REPO constant, subTest loops). Tests: (a) every committed `*/requirements.json` parses and validates against the schema — validation via a small stdlib validator function in the test module (check required keys, types, enum'd `scope`, `probe` is list-of-str; do NOT add a jsonschema dependency); (b) every `probe` in every committed declaration is a JSON array of strings, never a string (spec's safety test); (c) each declaration's `plugin` field matches its directory name; (d) `requirements_version` is `1.0.0`.
- [ ] **Step 2: Run to verify RED** (no declarations exist yet — tests must skip-or-fail meaningfully; assert at least the three exemplar files exist so the run is RED).
- [ ] **Step 3: Write the schema** — JSON Schema draft-07 shape mirroring the spec's example exactly: top-level required `requirements_version`, `plugin`; optional `tools`, `config`, `auth` arrays. `tools[]` entries require `name`, `required`, `why`, `probe`; optional `version_pattern`, `min_version`, `install` (object: platform keys + `docs`). `config[]` entries require `path`, `scope` (`repo`|`home`), `required`, `why`, `remedy`. `auth[]` entries require `name`, `probe`, `why`, `remedy`.
- [ ] **Step 4: Write `writing-declarations.md`** — short authoring guide: read the plugin's skills first; requirement vs incidental mention; target-repo toolchains are out; `why` must name the consuming skill(s); probes must be cheap, read-only, argv arrays.
- [ ] **Step 5: Write the three exemplar declarations** — content per the spec: `github` (hard `gh` tool with version probe + optional `.local/gh-projects.json` config + `gh auth status` auth probe — the spec's JSON example verbatim is the starting point), `dev` (single hard tool `sem`, probe `["sem", "--version"]`, why: sem entity graph for dedupe/sem-annotate; install docs pointer), `env` (its own: `uv` hard — `uv run` invokes the checker; probe `["uv", "--version"]`).
- [ ] **Step 6: GREEN + lint + commit + push** — `feat(env): declaration contract, schema, and exemplar requirements (env, github, dev)`. Watch CI.

---

### Task 2: The checker — `env/scripts/env_check.py` + unit tests

**Files:**
- Create: `env/scripts/env_check.py`
- Test: `tests/test_env_check.py`

**Interfaces:**
- Consumes: schema/declarations from Task 1.
- Produces: CLI `python3 env/scripts/env_check.py [check] [--plugin NAME] [--root PATH]` emitting the spec's JSON report (categories: missing-hard, degraded, undeclared, ok; exit 0/1/2) and `probe <plugin> <name>` subcommand. `--root` overrides discovery for tests. Task 3's SKILL.md documents this exact CLI.

- [ ] **Step 1: Failing tests first.** Cover, with fixture repos built in tmp dirs (fake declarations + fake probe commands — tiny executable scripts on a prepended PATH, mirroring `tests/test_cats_runner.py`'s `_with_fake_cats` idiom): discovery in flat source layout; discovery in versioned cache layout (`cache/<mkt>/<plugin>/<version>/`) picking highest version and reporting it; degraded no-siblings discovery reports self only; version comparison (`2.40` vs `2.41.1`, equal, missing output, unparseable → treated as unknown, not failure); required-vs-optional driving exit code (hard failure → 1, only optional failures → 0); undeclared plugins listed neutrally; probe subcommand runs only declared probes (unknown probe name → exit 2); probes executed with `shell=False` argv (assert via a fake probe that echoes argv); auth probe output recorded as status + one line, never token-like content.
- [ ] **Step 2: RED**, then implement. Key internals: `discover(root: Path|None) -> dict[str, tuple[version|None, Path]]`; `run_probe(argv: list[str]) -> tuple[int, str]` using `subprocess.run(argv, shell=False, capture_output=True, timeout=30)`; `compare_versions(found: str, minimum: str) -> bool` (tuple-of-ints compare, pad short); report assembly per spec categories. No third-party deps.
- [ ] **Step 3: GREEN + full suite + lint + commit + push** — `feat(env): env_check.py — read-only environment checker per spec`. Watch CI.

---

### Task 3: The plugin — SKILL.md, manifests, marketplace registration

**Files:**
- Create: `env/skills/check/SKILL.md`, `env/.claude-plugin/plugin.json` (version 1.0.0)
- Modify: `.claude-plugin/marketplace.json` (add `env`, category `development`), `scripts/verify-marketplace.sh` (PLUGINS array += `"env:development:check"`)
- Regenerate: Codex manifests (`uv run scripts/gen_codex_manifests.py` → adds `env/.codex-plugin/plugin.json`, updates `.agents/plugins/marketplace.json`)

**Interfaces:**
- Consumes: the Task 2 CLI.
- Produces: `/env:check [plugin] [--fix]` skill. Frontmatter description must trigger on "is my environment ready", "check requirements", "env check", "preflight". Body: run the checker via `${CLAUDE_PLUGIN_ROOT}/scripts/env_check.py`, render grouped report (hard failures first, each with why + remedy); `--fix` flow per spec — only declared `install` strings for the detected platform, one confirmation per item, re-verify via `probe` subcommand after each install, print `docs` URL when no platform key. Note for harnesses without AskUserQuestion: ask in plain conversation.

- [ ] **Step 1:** Write SKILL.md + plugin.json; register in marketplace.json; regenerate Codex manifests; extend PLUGINS array.
- [ ] **Step 2:** `uv run pytest -q` (structure + codex-manifest tests must pass with the 13th plugin — plugin-count guards derive dynamically, so no hardcoded updates beyond the PLUGINS array) + `REPO="$PWD" bash scripts/verify-marketplace.sh` + lint.
- [ ] **Step 3:** Commit + push — `feat(env): env plugin with /env:check skill, registered in both marketplaces`. Watch CI.

---

### Task 4: Issue #21 proper — remaining declarations + retrofits + messaging

**Files:**
- Create: `loc/requirements.json`, `security/requirements.json`, `ui/requirements.json`, `wiki/requirements.json`, `writing/requirements.json`, `deps/requirements.json`, `logseq/requirements.json`, `cats/requirements.json`, `profile/requirements.json`, `itest/requirements.json` (10 — the issue says eight but predates `cats`, `profile`, `itest` landing; `profile`+`itest` were listed jointly)
- Modify: `dev/skills/dedupe/SKILL.md`, `dev/skills/sem-annotate/SKILL.md`, `github/skills/create-issue/SKILL.md` (replace ad-hoc preflights with a `/env:check <plugin>` pointer, keeping a one-line inline fallback for harnesses without the env plugin installed), `env/scripts/env_check.py` + its test (undeclared-category message: once all marketplace plugins are declared, undeclared becomes a warning-toned message rather than neutral — per issue item 3)

**Requirements per declaration:** author each by READING that plugin's skills, not from the issue's survey table (it is explicitly a starting point; `go`/`npm` mentions are target-repo concerns and excluded). Candidate seeds from the issue: loc (`uv`, `jq`, `git`), security (`jq`, `curl`), ui (`gh`, `jq`, `npx`/playwright), wiki (`git` + `.local/repos.json` config), writing (`uv`; boring's spacy extra as optional/degraded), deps (`gh`, `jq`, `uv`, `npm` — but `npm` only if the plugin itself invokes it regardless of target repo; verify by reading), logseq (`uv`, `curl`, Logseq HTTP endpoint as optional config/auth), cats (the `cats` binary — hard; `uv`), profile (`uv` only — inventory script), itest (none beyond profile contracts → config entries pointing at profile output files, optional). Every entry gets a `why` naming the consuming skill.

- [ ] **Step 1:** Author the 10 declarations (schema tests auto-cover them).
- [ ] **Step 2:** Retrofit the three skills; keep wording minimal.
- [ ] **Step 3:** Undeclared-messaging update + test adjustment.
- [ ] **Step 4:** Full suite + lint + verify script. Patch-bump `dev` and `github` plugin versions (skill content changed) + regenerate Codex manifests. (Declarations alone don't ship in skills' behavior, but bump `loc`…`itest` too ONLY if their SKILL.md changed — it shouldn't in this task.)
- [ ] **Step 5:** Commit + push — `feat(env): requirements declarations for all plugins; preflights delegate to /env:check (#21)`. Watch CI.
- [ ] **Step 6:** Close #21: `gh issue close 21 --repo ericfitz/skills --comment` summarizing declarations added, retrofits, messaging change, and noting env plugin implementation landed as its prerequisite.

---

## Self-Review (completed)

- **Spec coverage:** contract+exemplars (T1), checker+probe subcommand+safety (T2), skill+`--fix`+registration (T3), #21's three numbered scope items (T4). Spec's out-of-scope list untouched.
- **Placeholders:** behavioral detail intentionally delegated to the committed spec (authoritative); file lists, CLI shapes, test inventories, and declaration seeds are concrete here.
- **Consistency:** exit codes 0/1/2, `--root` override, and declaration field names match the spec's contract throughout.
