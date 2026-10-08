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

`path` may be an extracted snapshot rather than a live checkout: an orchestrator running on a `--ref` snapshot
passes the scan's `scan_root` (a `git archive` of the branch). To profile a branch
standalone, check it out or extract it (`git archive <ref> | tar -x -C <dir>`) and pass
that directory; this skill takes no `--ref` itself.

## Output location

Emit the contract as your reply. When an orchestrating skill gives you a run dir, also save it to
`<run_dir>/stack.json`. Standalone, keep it in the reply (or the session scratchpad if it
is large) — never write it into the target repo.

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
   - `high` with an empty `unclassified` — trust the census; go to step 4.
   - `high` with a non-empty `unclassified` — read those files. Anything you cannot
     account for goes in `unknowns[]` and caps `confidence` at `partial` (step 6).
   - `partial` or `low` — the script found things it could not classify. Go to step 3.

3. **Fallback reading.** Follow the order in `references/ecosystems.md` under
   "When the script comes back low-confidence". Read the repo yourself. Correct
   or extend the script's findings; never discard them silently.

4. Determine `runtimes` and `build_commands` from the version files and build-command
   tables in `references/ecosystems.md`. Prefer a command actually present in a
   Makefile, justfile, or CI workflow over the ecosystem default.

5. Determine `monorepo`: true when manifests appear in two or more distinct
   directories. List every such directory in `monorepo.packages` — one per `go.mod`, `package.json`, etc.;
   never collapse multiple Go modules into one. Take the `manifests` entries from the inventory.

6. Emit the contract. Set `inventory` to the script's full JSON output verbatim.
   Set `confidence` to the script's `coverage_confidence`, downgraded one level if
   your fallback reading contradicted the script, and never `high` while `unknowns[]`
   holds unexplained unclassified files.

## Rules

- Everything you could not identify goes in `unknowns[]`. Never guess a language
  from a single file.
- `primary_language` is the language with the largest share, or `null` when no
  language was recognized.
- Emit exactly one JSON object conforming to the contract, then a short prose
  summary. Nothing else.
