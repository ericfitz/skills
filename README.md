# skills

efitz's personal agent-skills marketplace (`efitz-skills`). Thirteen plugins,
each bundling one or more skills, installable into **Claude Code** or
**OpenAI Codex CLI** — the repo carries native manifests for both harnesses.
Invoke a skill as `/<plugin>:<skill>`.

## Installation

One step, idempotent, installs into whichever CLIs are on your PATH:

```sh
scripts/install.sh            # both Claude Code and Codex (default: all)
scripts/install.sh claude     # Claude Code only
scripts/install.sh codex      # Codex CLI only
```

Or manually, in either CLI:

```sh
claude plugin marketplace add ericfitz/skills
claude plugin install <plugin>@efitz-skills

codex plugin marketplace add ericfitz/skills
codex plugin install <plugin>@efitz-skills
```

The Claude Code manifests (`.claude-plugin/`) are the source of truth; the
Codex manifests (`.agents/plugins/marketplace.json` and each plugin's
`.codex-plugin/plugin.json`) are generated from them by
`scripts/gen_codex_manifests.py` and verified in CI with `--check`.

Run `/env:check` after installing to confirm the CLI tools, config files, and
auth sessions the plugins depend on are present.

## Plugins

### loc — localization / i18n

- **analyze** — Build a translation task manifest: per-language lists of missing keys with their source values, via the bundled `check-i18n.py` script.
- **coverage** — Audit translation completeness across all target locales; per-locale and summary coverage report with threshold flagging.
- **detect-nonloc** — Decide whether a string value should be translated or left as-is; returns a boolean and the matched pattern.
- **translate-to** — Translate UI strings and i18n values into a target language while preserving placeholders, formatting, capitalization, and tone.
- **update-json** — Modify a JSON i18n file (add/update/delete keys) while preserving formatting and writing atomically.
- **validate-translation** — Verify a translated string or i18n file update: placeholder preservation, length, encoding, and common translation errors.
- **backfill** — Translate every missing or untranslated key across all locale files using the master locale as the source. Tool-agnostic; reads the project's i18n configuration.

### security

- **vet-plugin** — Security-first vetting of plugins/skills before installing from any marketplace, GitHub, or other source. Checks for red flags, permission scope, and suspicious patterns.
- **race-cond** — Systematic identification of race conditions, concurrency bugs, and thread-safety issues. Supports TypeScript, JavaScript, Python, Go, Rust, C++, Java, and Kotlin.

### github

- **backlog** — Pick the next GitHub issue to work on: fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one.
- **create-issue** — File a detailed issue (bug, feature, task, chore) against a repo, optionally adding it to a GitHub Project (v2) with milestone and initial status, using the locally-provisioned metadata cache (`.local/gh-projects.json`).

### ui

- **vrt** — Triage Playwright visual-regression (screenshot) failures: presents baseline, actual, and diff images framed against the current task context to decide bug vs. expected change.

### wiki

- **verify-doc** — Verify a documentation file's accuracy against source code and external references, then migrate it into a project wiki. Reads target repo and wiki path from `.local/repos.json`.

### dev — sem-powered developer toolkit

- **sem-annotate** — Generate and refresh durable `SEM@<sha>` intent markers on code entities using the sem CLI. Modes: full-scope, `--update <files>`, `--rebuild`.
- **sem-auto** — Set up a project so SEM markers stay maintained: installs a SEM-marker convention block into the project's CLAUDE.md so markers are updated as part of normal editing.
- **dedupe** — Find dead code and duplication across a codebase using the sem CLI, then produce a ranked, risk-assessed plan and optionally apply it. Takes a path scope to exclude unrelated tools/scripts.

All three support Go, TypeScript/JavaScript, and Python.

### writing

- **boring** — Evaluate technical business writing for "boringness" across 20 sub-dimensions on four axes (Direction, Density, Texture, Surprise). Combines a deterministic mechanical analyzer (15 sub-dimensions, runs as a Python script) with five LLM-judged sub-dimensions.

### deps

- **bump** — Update dependencies safely across Go, Python, and Node ecosystems. Auto-detects ecosystems, applies safe patch/minor updates with build+test+lint validation, bisects failures to isolate bad packages, and surfaces a prioritized plan for majors and held packages.

### logseq

- **capture** — Capture a note, TODO, or meeting summary into the local Logseq graph — today's journal by default, or a named page.
- **query** — Answer questions from the graph: search pages and journals, follow backlinks, surface TODOs and tagged content. Read-only.
- **lint** — Find consistency problems — broken links, case-conflicting link spellings, orphan pages, near-duplicate page names, unparseable pages — and apply chosen fixes.
- **organize** — Merge/dedupe and restructure pages: combine duplicate topic pages (rewriting inbound links), split overgrown pages, promote journal content into topic pages.
- **from-obsidian** — Convert and import notes from a local Obsidian vault — a single note, a folder, or the whole vault. Repeatable; unchanged already-imported notes are skipped.

### cats — CATS API fuzzing

- **init** — Bootstrap per-repo CATS fuzzing configuration (`.local/cats/config.yaml`).
- **run** — Execute a fuzz campaign against the repo's configured server and spec through config-declared shell hooks, via a background subagent.
- **report** — Query and render results from SQLite; also documents the results schema (tables, views, worked queries).
- **analyze** — Triage true positives into a remediation plan: real bug, spec gap, or false-positive candidate.
- **fp** — Add, review, and reclassify declarative false-positive rules (a committed YAML file).

Portable across repos: setup is gitignored and repo-local; false-positive
rules are committed.

### profile — project discovery

- **stack** — Identify what a codebase is built with: languages, runtimes, package managers, build commands, and monorepo layout.
- **docs** — Read the documentary record (PRDs, requirements, specs, ADRs, wiki pages) and extract requirements, user-workflow evidence, domain vocabulary, and invariants.
- **topology** — Determine how the system deploys and what it depends on: components, real dependencies, third-party services, configuration, startup order, and standup difficulty.
- **journeys** — Identify the key workflows users actually perform, mined from documentation, routes, CLI commands, and UI entry points, ranked by business criticality with dependency edges.

Read-only inference backed by `scripts/profile_inventory.py`, a deterministic
repo census. Each skill emits a versioned JSON contract under
`references/contracts/`; those contracts are the supported interface for other
plugins.

### itest — integration test design

- **design** — Orchestrates the whole workflow: discovers stack, documented requirements, deployment shape, customer journeys, test conventions, existing-test quality, and state affordances, then synthesizes a prioritized scenario plan.
- **conventions** — Determine how tests are written and run: frameworks, runner commands, how integration tests are separated from unit tests, house style, and reusable fixtures.
- **critique** — Assess existing integration tests for over-mocking, implementation-detail assertions, non-determinism, shared state, and missing failure paths; recommends keep, repair, replace, or delete for each.
- **state** — Discover how test state can be established: writable stores, factories and builders, seed tooling, test-only endpoints, ID generation, and teardown affordances.

Requires the `profile` plugin. Discovery is read-only: nothing is built,
booted, or run, and every unproven inference is carried into the plan as an
explicit assumption. Where a normative document and the code disagree, the
plan reports the conflict and both readings. Output conforms to
`references/contracts/scenario.schema.json`.

### env

- **check** — Preflight the environment for this marketplace's plugins: required CLI tools, config files, and auth sessions. Reports hard failures, degraded (optional) capability loss, and undeclared plugins; supports checking a single plugin and an explicit `--fix` mode.

---

`writing-style/` is an experimental, agentic writing-style reviewer and is not
yet published as a marketplace plugin.
