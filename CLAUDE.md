# CLAUDE.md — efitz-skills marketplace

Instructions for agents working in this repository.

## What this repo is

A dual-harness agent-skills marketplace. Each top-level directory is a plugin
bundling one or more skills, installable into Claude Code or OpenAI Codex CLI.
Skills are invoked as `/<plugin>:<skill>`.

## Exit criteria

**No task in this repo is complete until every check that applies has been run and
its output confirmed.** Do not report work as done on the strength of having made
the edits. Run the commands, read the output, then report.

### Always — the four CI checks

These are the jobs in `.github/workflows/ci.yml`. Run all four before calling any
change complete, whatever the change was.

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```

This is a non-package uv project — `uv run` everything; never invoke `python`,
`pytest`, or `ruff` directly. `ruff` is the sole linter.

### Derived artifacts must be updated in the same commit

Several files are derived from the plugin and skill tree. Editing that tree without
updating them leaves the repo in a state where `verify-marketplace.sh` fails on
`main` for whoever lands next.

**When adding, removing, or renaming a plugin:**

1. `<plugin>/.claude-plugin/plugin.json` — `name` must equal the directory name;
   `version` must be semver `X.Y.Z`
2. `.claude-plugin/marketplace.json` — add the entry, with a `category` matching the
   one declared in `scripts/verify-marketplace.sh`
3. `scripts/verify-marketplace.sh` — the `PLUGINS` array, format
   `"plugin:category:skill1,skill2,..."`, skills in the array order the directory
   listing gives
4. `uv run scripts/gen_codex_manifests.py` — regenerate the Codex manifests, then
   commit what it wrote
5. `README.md` — the plugin-count sentence in the opening paragraph, and a
   `### <plugin>` section in `## Plugins`
6. `docs/ARCHITECTURE.md` — a node in the dependency graph and a row in the skill
   catalog, if the plugin produces or consumes anything another plugin reads
7. `<plugin>/requirements.json` — declare every CLI tool, config file, and auth
   session the plugin needs, marking each required or optional. `/env:check`
   discovers these by glob; no change to the `env` plugin is needed

**When adding, removing, or renaming a skill:**

Items 3, 4, and 5 above, plus: the skill's `SKILL.md` frontmatter `name` must equal
its directory name, and the skill directory must live under `<plugin>/skills/`.

**When changing what one plugin hands another** — a contract schema, a well-known
artifact path, a `.local/` config file — update `docs/ARCHITECTURE.md`. If the
change touches the Mermaid dependency graph, **re-render it rather than eyeballing
it**:

```bash
npx -y -p @mermaid-js/mermaid-cli mmdc -i <extracted.mmd> -o /tmp/out.svg
```

### When the change is a script

Run the build and unit tests for that script, not only the repo suite. Tests live
in a flat `tests/` directory; `tests/repobuilder.py` builds fixture repositories and
`tests/schema_check.py` is the stdlib-only schema validator.

### When the change is a test

Run that test and fix what it surfaces before moving on.

## Conventions

**Contracts.** A plugin that hands structured data to another plugin publishes a
versioned JSON schema under `<plugin>/references/contracts/`, with a worked example
in `examples/`. Consumers are handed the contract or invoke the producing skill by
name — never by reaching into another plugin's directory by path.

**Discovery skills are read-only.** They execute nothing and modify nothing. Factual
claims carry `file:line` evidence; anything inferred but unconfirmed goes in
`assumptions[]`.

**Skills never dump credentials.** A skill may record that a secret is referenced,
what it is named, and where it is read. It must not read the value, and must not
open files under `~/.keys/`.

**Design before implementation.** Non-trivial work goes brainstorm → spec in
`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` → plan in
`docs/superpowers/plans/` → implementation.

**Local config.** Machine-local per-repo config lives under `.local/` and is
git-ignored. Skills read `.local/repos.json` and `.local/gh-projects.json`; they
never write them.

**Git hygiene.** Stage only files relevant to the task. Never `git add -A` without
reviewing for untracked noise.
