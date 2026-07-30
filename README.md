# skills

efitz's personal Claude Code marketplace (`efitz-skills`). Twelve plugins, each
bundling one or more skills. Invoke a skill as `/<plugin>:<skill>`.

## loc — localization / i18n

`analyze` (missing-key manifests) · `coverage` (per-locale completeness) ·
`detect-nonloc` (should-this-be-translated) · `translate-to` (translate a
string) · `update-json` (atomic JSON locale edits) · `validate-translation`
(verify a translated string) · `backfill` (translate every missing key across
all locales).

## security

`vet-plugin` (vet a plugin/skill before installing) · `race-cond` (audit code
for race conditions and concurrency bugs).

## github

`backlog` (pick the next issue to work on) · `create-issue` (file a detailed issue into a
repo/Project using a locally-provisioned metadata cache).

## ui

`vrt` (triage Playwright visual-regression / screenshot failures).

## wiki

`verify-doc` (verify a doc against source + references, then migrate it into a
project wiki).

## dev

`dedupe` (find and analyze duplicate/overlapping functionality across a
codebase).

## profile — project discovery

`stack` (languages, runtimes, package managers, build commands) · `docs`
(requirements, glossary, and domain invariants extracted from PRDs, specs, ADRs,
and wiki pages) · `topology` (deployment shape, real dependencies, third parties,
standup difficulty) · `journeys` (ranked candidate user workflows with dependency
edges).

Read-only inference backed by `scripts/profile_inventory.py`, a deterministic
repo census. `docs` reaches documentation outside the repo only through
capabilities already available in the session — an MCP server, a web fetch, a
local path — and reports anything it cannot reach with a concrete remedy rather
than working around it. Each skill emits a versioned JSON contract under
`references/contracts/`; those contracts are the supported interface for other
plugins.

## itest — integration test design

`design` (orchestrates the whole workflow) · `conventions` (frameworks, runner
commands, how integration tests are separated) · `critique` (quality assessment of
existing tests — over-mocking, implementation-detail assertions, non-determinism) ·
`state` (writable stores, factories, seed tooling, teardown affordances).

Requires the `profile` plugin, which supplies stack, documented requirements,
deployment topology, and candidate user journeys. Scenarios trace back to the
requirement they cover, and requirements no journey owns are surfaced separately
rather than dropped. Where a normative document and the code disagree, the plan
reports the conflict and both readings and offers to open a tracking issue.

Discovery is read-only: nothing is built, booted, or run, and every unproven
inference is carried into the plan as an explicit assumption. Output is a scenario
set conforming to `references/contracts/scenario.schema.json`, the handoff seam to
a future build phase.

## writing

`boring` (evaluate technical business writing for "boringness" across 20
sub-dimensions; mechanical analyzer + LLM-judged dimensions).

## deps

`bump` (update dependencies safely across Go/Python/Node — patch/minor auto,
build+test+lint validated, bisects failures, plans majors).

## logseq

`capture` (add notes/TODOs to today's journal or a page) · `query` (answer
questions from the graph, read-only) · `lint` (broken links, case conflicts,
orphans, near-duplicates) · `organize` (merge/dedupe and restructure pages
with safe changesets) · `from-obsidian` (convert + import an Obsidian vault,
repeatable with hash-skip).

## cats — CATS API fuzzing

`init` (bootstrap per-repo `.local/cats/config.yaml`) · `run` (execute a fuzz
campaign through config-declared shell hooks, via a background subagent) ·
`report` (query and render results from SQLite — also the schema reference) ·
`analyze` (triage true positives into a remediation plan) · `fp` (add/review/
reclassify declarative false-positive rules). Portable across repos: setup is
gitignored and repo-local, false-positive rules are a committed YAML file.

---

`writing-style/` is an experimental, agentic writing-style reviewer and is not
yet published as a marketplace plugin.
