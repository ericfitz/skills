---
name: stack
description: Identify what a codebase is built with — languages, runtimes, package managers, build commands, and monorepo layout. Use when profiling an unfamiliar project, before test design, dependency work, or onboarding documentation. Emits the profile:stack contract.
---

# stack

Identify the ecosystem of a repository and emit the `stack` contract.

This is the gate phase for downstream discovery: every other phase's search strategy
depends on knowing the ecosystem, and the inventory this phase produces is passed
forward inside its contract so no downstream phase re-runs the script.

Bundled tool: `${CLAUDE_PLUGIN_ROOT}/scripts/profile_inventory.py`
Reference: `${CLAUDE_PLUGIN_ROOT}/references/ecosystems.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/stack.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/stack.example.json`

## Usage

    /profile:stack [path]     # default: current directory

## Procedure

1. Run the inventory script:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/profile_inventory.py <path>

   `--script` is required: it isolates the run from the target repo's own project
   config, which would otherwise be resolved and can fail on repos with private
   indexes or unpublished dependencies.

   If `uv` is not installed, run the same path under `python3` — this script
   declares no dependencies — and mention the fallback in your summary.

   Exit 2 means the path is unusable — stop and report that.

2. Read `coverage_confidence` and `unclassified`.
   - `high` — trust the census; go to step 4.
   - `partial` or `low` — the script found things it could not classify. Go to step 3.

3. **Fallback reading.** Follow the order in `references/ecosystems.md` under
   "When the script comes back low-confidence". Read the repo yourself. Correct
   or extend the script's findings; never discard them silently.

4. Determine `runtimes` and `build_commands` from the version files and build-command
   tables in `references/ecosystems.md`. Prefer a command actually present in a
   Makefile, justfile, or CI workflow over the ecosystem default.

5. Determine `monorepo`: true when manifests appear in two or more distinct
   directories. List those directories in `monorepo.packages`.

6. Emit the contract. Set `inventory` to the script's full JSON output verbatim.
   Set `confidence` to the script's `coverage_confidence`, downgraded one level if
   your fallback reading contradicted the script.

## Rules

- Everything you could not identify goes in `unknowns[]`. Never guess a language
  from a single file.
- `primary_language` is the language with the largest share, or `null` when no
  language was recognized.
- Emit exactly one JSON object conforming to the contract, then a short prose
  summary. Nothing else.
