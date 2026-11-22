---
name: conventions
description: Determine how tests are written and run in a project — frameworks, runner commands, how integration tests are separated from unit tests, house style, and reusable fixtures and helpers. Use before writing or designing tests in an unfamiliar codebase. Emits the test-integration:conventions contract.
---

# conventions

Determine how this project writes and runs tests, so new tests match it and get run.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/test-frameworks.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/conventions.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/conventions.example.json`

## Usage

    /test-integration:conventions [path]

## Input

You are normally handed a `discover:stack` contract. Use its `inventory` for
`test_files`, `test_dirs`, `test_config`, and `ci`.

You may also be handed a `discover:docs` contract. Its corpus often contains a
CONTRIBUTING file or a testing guide, which is the most direct statement of house style
and runner commands available anywhere. Prefer it over inference — then check it against
what CI actually runs, because guides go stale and CI does not.

**Standalone invocation:** if you were not handed one, invoke the `discover:stack`
skill and use its output. If the `discover` plugin is not available, read the repo
directly using the fingerprint tables in `references/test-frameworks.md`, and say
in your summary that you ran without an inventory.

Never invoke `discover`'s inventory script by path. Inventory data reaches this
plugin only through the `stack` contract.

## Procedure

1. Identify `frameworks` from imports in the census's test files and from
   `test_config`, using the fingerprint table.
2. Determine `runner_commands` following the source order in "Finding the runner
   commands". CI is the strongest evidence: it shows what actually runs.
3. Determine `integration_separation` — the single most consequential output. Find
   how existing integration tests are distinguished, and write `how_to_add` as a
   concrete instruction someone can follow without reading anything else. If nothing
   in the repo separates them, `mechanism` is `none`; if you cannot tell, it is
   `unknown` and goes in `convention_gaps`.
4. Read enough test files to describe `house_style` accurately — naming, layout,
   fixture mechanism, setup and teardown, assertion style.
5. Collect `reusable_helpers` per "What counts as a reusable helper", with real
   signatures. Downstream work reuses these instead of inventing parallel fixtures.
6. Record `convention_gaps` — anything a newcomer would get wrong.
7. Emit the contract, then a short prose summary.

## Rules

- Read-only. Do not run the test suite.
- Describe what this repo does, not what it should do. Quality assessment belongs to
  `/test-integration:critique`.
- Every framework and separation claim carries `file:line` evidence.
