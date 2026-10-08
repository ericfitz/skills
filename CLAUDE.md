# CLAUDE.md — efitz-skills marketplace

A dual-harness agent-skills marketplace. Each top-level directory is a plugin bundling one or more skills, installable into Claude Code or OpenAI Codex CLI. Skills are invoked as `/<plugin>:<skill>`.

## Exit criteria

Run all four CI checks (`.github/workflows/ci.yml`) before calling any change complete, whatever the change was:

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```

This is a non-package uv project: `uv run` everything; never invoke `python`, `pytest`, or `ruff` directly. `ruff` is the sole linter.

Tests live in a flat `tests/` directory; `tests/repobuilder.py` builds fixture repositories and `tests/schema_check.py` is the stdlib-only schema validator.

## Derived artifacts (update in the same commit)

Several files are derived from the plugin/skill tree; editing the tree without them leaves `verify-marketplace.sh` failing on `main` for whoever lands next.

**Adding, removing, or renaming a plugin:**

1. `<plugin>/.claude-plugin/plugin.json` — `name` equals the directory name; `version` is semver `X.Y.Z`
2. `.claude-plugin/marketplace.json` — add the entry, with a `category` declared in `scripts/verify-marketplace.sh`
3. `scripts/verify-marketplace.sh` — the `PLUGINS` array, format `"plugin:category:skill1,skill2,..."`, skills in directory-listing order
4. `uv run scripts/gen_codex_manifests.py` — regenerate the Codex manifests and commit the output
5. `README.md` — the plugin-count sentence in the opening paragraph, and a `### <plugin>` section under `## Plugins`
6. `docs/ARCHITECTURE.md` — a node in the dependency graph and a row in the skill catalog, if the plugin produces or consumes anything another plugin reads
7. `<plugin>/requirements.json` — every CLI tool, config file, and auth session the plugin needs, each marked required or optional (`/env:check` discovers these by glob; no change to the `env` plugin is needed)

**Adding, removing, or renaming a skill:** items 3, 4, and 5, plus the skill's `SKILL.md` frontmatter `name` must equal its directory name and the directory must live under `<plugin>/skills/`.

**Changing what one plugin hands another** (a contract schema, a well-known artifact path, a `.local/` config file): update `docs/ARCHITECTURE.md`. If the Mermaid dependency graph changes, re-render it rather than eyeballing it:

```bash
npx -y -p @mermaid-js/mermaid-cli mmdc -i <extracted.mmd> -o /tmp/out.svg
```

## Conventions

- **Contracts.** A plugin that hands structured data to another publishes a versioned JSON schema under `<plugin>/references/contracts/` with a worked example in `examples/`. Consumers are handed the contract or invoke the producing skill by name — never by reaching into another plugin's directory by path.
- **Discovery skills are read-only.** They execute nothing and modify nothing. Factual claims carry `file:line` evidence; anything inferred but unconfirmed goes in `assumptions[]`.
- **Skills never dump credentials.** A skill may record that a secret is referenced, its name, and where it is read — never its value.
- **Design before implementation.** Non-trivial work goes brainstorm → spec in `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md` → plan in `docs/superpowers/plans/` → implementation.

## Learned Preferences

- Plugin and contract versions move only when the user explicitly declares a feature done and productionized; never bump on a schema or interface change, and ask before bumping any version.
