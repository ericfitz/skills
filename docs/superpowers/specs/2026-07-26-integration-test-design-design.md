# Integration Test Design — `profile` + `itest` plugins

**Date:** 2026-07-26
**Status:** Approved design, not yet implemented

## Problem

Designing integration tests for an unfamiliar (or half-remembered) codebase requires
answering the same questions every time: what is this built with, how are tests written
here, how does the thing actually deploy and what does it depend on, what do customers
actually do with it, what state must exist before a given workflow can run, and which of
the tests that already exist are lying to us.

Doing that by hand is slow and inconsistent. Doing it in one agent context on a large repo
buries the resulting plan under a pile of file reads.

## Solution

Two plugins in the `efitz-skills` marketplace.

`profile` performs general-purpose project discovery — facts about a codebase that are
useful to any consumer, not just testing. `itest` performs testing-specific discovery and
synthesizes an integration test design from both.

The deliverable is an in-session plan: presented conversationally as it is built, emitted
once as a complete markdown document, and offered for saving to a path the user names. No
persistence convention, no `docs/` requirement.

Building the tests is out of scope for this spec. The handoff seam to a future build skill
is specified (see [Scenario record](#scenario-record)); the build skill itself is not.

## Decisions

These were settled during design and are not open for reinterpretation during
implementation:

| Decision | Choice |
|---|---|
| Deliverable | In-session plan, printed as markdown, optionally saved to a user-named path |
| Test boundary | Not fixed by the skill — discovered per project, chosen during synthesis, stated explicitly |
| Journey source | Mine artifacts, then confirm with the user at a human gate |
| Deployment analysis | Read-only inference; nothing is executed |
| Existing tests | Mined for conventions, mapped for coverage gaps, and critiqued for quality |
| Packaging | Orchestrator + phase skills, dispatched as subagents, each also standalone-invocable |
| Discovery split | Separate `profile` plugin now, coupled to `itest` only by versioned contracts |
| Detection | Bundled inventory script for the mechanical parts, model fallback for anything it cannot classify |
| Build phase | Out of scope; handoff seam specified |

### Read-only inference: accepted tradeoff

The design phases never execute anything — no booting containers, no running the existing
suite, no health checks. This keeps the skill safe to run on any repo, at the cost that the
plan rests on assumptions that were never proven.

That cost is paid explicitly rather than hidden: the `topology` phase records every
unconfirmed inference in `assumptions[]`, and synthesis carries them into the plan's risk
section and into each scenario's `open_assumptions[]`, where the future build skill must
confirm them on first run.

## Architecture

### Plugin layout

```
profile/
  .claude-plugin/plugin.json
  skills/
    stack/SKILL.md              # /profile:stack
    topology/SKILL.md           # /profile:topology
    journeys/SKILL.md           # /profile:journeys
  scripts/profile_inventory.py
  references/
    ecosystems.md
    deployment-shapes.md
    journey-sources.md
    contracts/stack.schema.json
    contracts/topology.schema.json
    contracts/journeys.schema.json

itest/
  .claude-plugin/plugin.json
  skills/
    design/SKILL.md             # /itest:design — orchestrator
    conventions/SKILL.md        # /itest:conventions
    critique/SKILL.md           # /itest:critique
    state/SKILL.md              # /itest:state
  references/
    test-frameworks.md
    test-design.md              # the quality doctrine
    state-and-fixtures.md
    contracts/conventions.schema.json
    contracts/critique.schema.json
    contracts/state.schema.json
    contracts/scenario.schema.json
```

The inventory script lives in `profile` — a census of languages, manifests, CI files,
containers, and test files is a project fact, not a testing artifact.

**`itest` phases never invoke that script.** They receive its results as the `stack`
contract, passed by the orchestrator. The contract is the only coupling between the
plugins, which is the property that makes the split worth having.

### Execution graph for `/itest:design`

```
  preflight: profile:{stack,topology,journeys} present in skill listing?
        │
        ▼
  profile:stack   (gate — every other phase's search strategy depends on the ecosystem)
        │           runs profile_inventory.py itself, then interprets and corrects it;
        │           emits the stack contract, which carries the inventory forward
        │
        ├────────────┬────────────┬────────────┬────────────┐   ← five parallel subagents
        ▼            ▼            ▼            ▼            ▼
  profile:topology  profile:journeys  itest:conventions  itest:critique  itest:state
        │            │                │            │            │
        │      candidates             │            │            │
        │            ▼                │            │            │
        │     ── HUMAN GATE ──        │            │            │
        └────────────┴────────────────┴────────────┴────────────┘
                             ▼
                        SYNTHESIS (main context)
                             ▼
              plan → markdown → offer to save
```

Notes on the graph:

- **`stack` is a gate, not a parallel peer.** It is cheap — mostly interpreting script
  output — but every other phase needs to know the ecosystem before it knows what to look
  for.
- **`critique` runs parallel to `conventions`, not after it.** It works from the script's
  test-file census plus the doctrine in `test-design.md`; over-mocking and
  implementation-detail assertions are defects regardless of house style. Both phases
  re-read some test files. That duplicated read is an accepted cost. Where the two phases
  disagree about which tests are integration tests, synthesis reports the disagreement
  rather than silently picking a side.
- **The human gate lives in the main context.** Subagents cannot ask the user anything, so
  `journeys` returns ranked candidates with evidence and the orchestrator runs the
  approve / edit / add conversation itself. The gate also confirms prerequisite
  relationships between journeys, which the user usually knows faster than the skill can
  infer them.

### Cross-plugin dependency mechanics

`/itest:design` runs in the main context, where the available-skills listing is already
present. Preflight is a direct check for `profile:stack`, `profile:topology`, and
`profile:journeys` in that listing.

If any are absent, the orchestrator stops immediately with an actionable message — install
`profile` from the `efitz-skills` marketplace — rather than failing three subagents deep.

When present, each discovery subagent is dispatched with an instruction to invoke the phase
skill **by name** and return its contract JSON. `${CLAUDE_PLUGIN_ROOT}` never crosses a
plugin boundary, and no phase reads another phase's files.

**Standalone invocation of an `itest` phase** (for example `/itest:critique` alone) needs
inventory data it will not have been handed. Rule: invoke `profile:stack` first if
available; otherwise fall back to lightweight discovery driven by the phase's own reference
file. Only the orchestrator hard-requires `profile`; no individual phase does.

### Extraction discipline

The `profile` phases must contain no testing vocabulary in their instructions or their
outputs. Two specific corrections that came out of design and are binding:

- `topology` emits **`standup_notes`** — per component, how hard it is to stand up,
  what configuration it needs, what is externally reachable. It does **not** emit test
  boundary options. Synthesis converts those notes into boundary options, because that
  framing is test-specific reasoning.
- `journeys` does **not** emit any hint about existing test coverage. Synthesis builds the
  gap map from `critique` and `conventions` data.

## Components

### `profile_inventory.py`

```
profile_inventory.py [path] [--json]
```

Walks the repo honoring `.gitignore`, skipping `node_modules`, `.venv`, `vendor`, `dist`,
`build`, and `.git`. Emits a single JSON object:

- `languages[]` — name, file count, share
- `manifests[]` — path, ecosystem, package manager
- `test_files[]` — path, language, `kind: unit|integration|e2e|unknown`, and the `signals[]`
  that produced that guess (`dir:tests/integration`, `marker:pytest.mark.integration`,
  `buildtag:integration`, `suffix:_test.go`)
- `test_dirs[]`, `test_config[]` — path, framework
- `ci[]`, `containers[]`, `iac[]`, `entrypoints[]`, `docs[]`
- `unclassified[]` — every path the script recognized as significant but could not classify
- `coverage_confidence` — `high | partial | low`

**The rule that makes the model fallback work: the script classifies what it recognizes and
explicitly lists what it does not. It never guesses silently.** A populated `unclassified[]`
or a `low` confidence is the signal that tells `stack` to fall back to reading the repo
itself against `references/ecosystems.md`.

Exit 0 on success including partial results; exit 2 only on an unusable path. A script crash
degrades the run to full model-driven discovery rather than failing it.

### Phase contracts

Each phase returns a JSON block conforming to its schema, plus a short prose summary.

**`profile:stack`** — `primary_language`, `languages[]`, `package_managers[]`, `runtimes[]`,
`build_commands[]`, `monorepo{is, packages[]}`, `unknowns[]`, `confidence`. Also corrects
script misclassifications.

**`profile:topology`** — `shape` (monolith | service+deps | multi-service | serverless | cli
| library | desktop | hybrid), `components[]`,
`real_dependencies[{name, kind, how_started, config_source}]`,
`external_third_parties[{name, used_for}]`, `config_mechanism`, `ports_and_endpoints[]`,
`startup_sequence`, `standup_notes[{component, standup_difficulty, config_needed,
externally_reachable, evidence}]`, `assumptions[]`.

Because the phase is read-only, every factual claim carries `evidence` as `file:line`, and
everything it could not confirm goes in `assumptions[]`.

**`profile:journeys`** — `candidates[{id, name, actor, narrative, entry_point, evidence[],
business_criticality, rank, rationale}]` (at most ~12), `sources_read[]`,
`surface_coverage`. Mined from README, `docs/`, wiki, API routes, CLI commands, UI entry
points, and issue/milestone titles.

**`itest:conventions`** — `frameworks[]`, `runner_commands{unit, integration, all}`,
**`integration_separation{mechanism, how_to_add}`**, `house_style{naming, layout,
fixture_mechanism, setup_teardown, assertion_style}`, **`reusable_helpers[]`**,
`existing_fixtures[]`, `ci_invocation`, `convention_gaps[]`.

`integration_separation` is how a *new* integration test gets picked up by the right runner
and not the unit run — build tag, pytest marker, directory, filename suffix, separate
config. Getting this wrong means every test the build phase writes is either never run or
run in the wrong context.

**`itest:critique`** — `assessed[{path, verdict: sound|weak|misleading,
issues[{type, severity, evidence}], recommendation: keep|repair|replace|delete}]`,
`systemic_issues[]`.

`issues[].type` is drawn from a fixed vocabulary defined in `test-design.md`: over-mocking
at the boundary under test; asserting implementation details; non-determinism (sleeps,
wall-clock, ordering, randomness); shared mutable state across tests; tautological
assertions; assertion-free smoke tests; testing the framework rather than the system;
missing failure-path coverage.

**`itest:state`** — the state-establishment affordances this project offers. Reads schema
and migrations, ORM models, seed tooling, factory/builder libraries, fixture data files,
admin or test-only endpoints, whether IDs are client- or server-generated, and teardown
affordances (transactional rollback, truncate, per-test namespacing, ephemeral containers).

Outputs `writable_stores[{name, direct_write_possible, how, evidence}]`,
`builders_and_factories[]`, `seed_tooling[]`, `test_only_endpoints[]`,
`id_generation{client|server, implications}`, `teardown_affordances[]`, `assumptions[]`.

Whether injection is even possible — can a test write to the store directly, or is the
store reachable only through the service — is a discovered fact, not a design choice.

## Synthesis

Runs in the main context, in seven ordered steps.

**1. Boundary selection.** `standup_notes` × `integration_separation` × state affordances
→ one chosen boundary, stated explicitly with rationale, plus what is real and what is
stubbed at that boundary. This is the single most important sentence in the plan and it is
written down, not assumed.

**2. Journey → scenario expansion.** Each approved journey yields one happy path plus the
failure scenarios that earn their place at this tier.

The rule: an integration test is justified when the failure arises **from integration** — a
dependency unavailable or slow, partial failure mid-sequence, concurrent access to the same
entity, authorization boundaries, data crossing a serialization boundary, transaction
rollback. Input-validation permutations and pure logic branches are pushed down to unit
tests. Without this rule the most expensive tier suffers combinatorial explosion, which is
how integration suites become the thing everyone disables.

**3. Precondition design.** Build a DAG over journeys — "delete object" depends on "create
object", which is itself a journey under test — then resolve each edge to compose or
inject, and choose the isolation and cleanup strategy. Doctrine in
[Compose vs inject](#compose-vs-inject).

**4. Assertion design.** For each scenario, what is actually observable at the chosen
boundary and what to assert on it: response, persisted state read back *through the
interface*, emitted event, observable effect on a real dependency. Never internals. Plus
negative assertions where they matter ("and nothing else was modified"), which is where
most real bugs hide, and explicit determinism controls — frozen time, seeded randomness,
waiting on conditions rather than sleeping.

**5. Gap map.** Approved journeys × `critique` verdicts × existing coverage →
**covered / weak / missing / misleading**, prioritized. Misleading ranks above missing: a
test that passes while the journey is broken is worse than no test.

**6. Risks and assumptions.** Every `topology` and `state` assumption that was inferred but
not executed, listed as something the build phase must confirm on first run. Plus flakiness
risks and rough cost.

**7. Emission.** Markdown block, then an offer to save to a user-named path.

### Compose vs inject

The doctrine lives in `references/test-design.md` and must be stated as an applicable rule,
not a menu:

- **Compose by default when the prerequisite is itself a journey under test.** State is
  valid by construction, and the create path gets extra coverage for free.
- **Inject when** the chain is deep enough that composition dominates runtime; or the state
  is unreachable through the public interface (produced by a background job, aged by time,
  migrated legacy data); or it belongs to a third party being stubbed; or a corrupt or
  edge-case state is specifically what is under test.
- **Never inject state the real system could not itself produce**, unless resilience to
  exactly that corruption is what is being tested. Otherwise the test asserts on fiction and
  passes forever.
- **Composed setup must be asserted on, or fail loudly.** If `create` silently half-fails,
  the `delete` test reports a delete bug. Failure attribution is the main hidden cost of
  composition, and it is payable.
- **Prefer per-test isolation over hoisted shared setup**, even at a runtime cost, until
  setup cost is *measured* as prohibitive. Hoisting is what introduces order dependence.

Cleanup is decided in the same step by the same affordances: whatever was injected must be
removable.

## Scenario record

The handoff seam to a future build skill. Everything above converges on producing these,
and a build skill needs nothing else from the design session. Schema:
`itest/references/contracts/scenario.schema.json`.

```yaml
id, journey_id, title, priority, est_cost
boundary                    # restated, so the record stands alone
preconditions[]             # ordered: {state, method: compose|inject, via, assert_established}
steps[]                     # actions through the entry point
assertions[]
negative_assertions[]
dependencies: {real[], stubbed[]}
isolation: {strategy, cleanup[]}
determinism_controls[]
fixtures_to_reuse[]         # from conventions.reusable_helpers
new_helpers_needed[]
placement: {file_path, naming, marker_or_tag}   # from conventions.integration_separation
runner_invocation
open_assumptions[]          # build must confirm these at first run
```

`placement` and `runner_invocation` are what stop the build phase from writing tests the
runner never picks up. `open_assumptions[]` is what carries the read-only caveat forward
instead of losing it.

## Testing

Three layers, all runnable without an LLM.

**`tests/test_profile_inventory.py`** — synthetic mini-repos under
`tests/fixtures/profile_inventory/`: Python + pytest, Go + compose, TypeScript monorepo, and
a deliberately unrecognizable stack. Asserts language and manifest classification,
`test_files[].kind` signals, and that the unrecognizable stack produces a populated
`unclassified[]` with `coverage_confidence: low` rather than a confident wrong answer.

**`tests/test_itest_contracts.py`** — every `references/contracts/*.schema.json` in both
plugins is valid JSON Schema, and committed example documents validate against them. This
gives the cross-plugin seam teeth: if `profile:stack`'s output shape drifts from what
`itest` expects, a test fails rather than a workflow.

**`tests/test_plugin_structure.py`** — new, and useful beyond these two plugins. Every
`SKILL.md` has `name` and `description` frontmatter; every `${CLAUDE_PLUGIN_ROOT}`-relative
path referenced in a skill body exists; every plugin directory has a `marketplace.json`
entry.

## Repo integration

Two `.claude-plugin/marketplace.json` entries and two README sections, matching existing
house style.

## Out of scope

- The build skill that implements scenarios (seam specified, skill deferred)
- Executing anything during discovery — no container boots, no test runs, no health checks
- Persisting the plan by convention; saving is offered, never assumed
- Unit test design, performance testing, and security testing
