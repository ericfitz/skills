# Integration Test Design — `profile` + `itest` plugins

**Date:** 2026-07-26
**Revised:** 2026-07-29 — documentation analysis added (`profile:docs`)
**Status:** Approved design, not yet implemented

## Problem

Designing integration tests for an unfamiliar (or half-remembered) codebase requires
answering the same questions every time: what is this built with, how are tests written
here, how does the thing actually deploy and what does it depend on, what do customers
actually do with it, what did anyone ever write down about what it is supposed to do, what
state must exist before a given workflow can run, and which of the tests that already exist
are lying to us.

Doing that by hand is slow and inconsistent. Doing it in one agent context on a large repo
buries the resulting plan under a pile of file reads.

Mining code alone answers "what does it do" but never "what was it supposed to do." Journeys
inferred purely from routes and CLI commands describe the surface, not the intent behind it,
and the acceptance criteria that would make good assertions live in PRDs and specs rather
than in source.

## Solution

Two plugins in the `efitz-skills` marketplace.

`profile` performs general-purpose project discovery — facts about a codebase that are
useful to any consumer, not just testing. This includes the project's own documentary
record: requirements documents, PRDs, specifications, design docs, ADRs, and wiki pages.
`itest` performs testing-specific discovery and synthesizes an integration test design from
both.

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
| Journey source | Mine artifacts and documentation, then confirm with the user at a human gate |
| Deployment analysis | Read-only inference; nothing is executed |
| Existing tests | Mined for conventions, mapped for coverage gaps, and critiqued for quality |
| Packaging | Orchestrator + phase skills, dispatched as subagents, each also standalone-invocable |
| Discovery split | Separate `profile` plugin now, coupled to `itest` only by versioned contracts |
| Detection | Bundled inventory script for the mechanical parts, model fallback for anything it cannot classify |
| Documentation | First-class `profile:docs` gate phase; in-repo docs always, external sources only where the user names them |
| Doc retrieval | No new retrieval mechanism is ever built — use an existing capability or report its absence with a remedy |
| Doc vs code conflicts | Reconciled at synthesis, never inside `docs`; reported with both readings, never adjudicated |
| Cross-cutting requirements | Surface as a second candidate list at the existing human gate |
| Build phase | Out of scope; handoff seam specified |

### Read-only inference: accepted tradeoff

The design phases never execute anything — no booting containers, no running the existing
suite, no health checks. This keeps the skill safe to run on any repo, at the cost that the
plan rests on assumptions that were never proven.

That cost is paid explicitly rather than hidden: the `topology` phase records every
unconfirmed inference in `assumptions[]`, and synthesis carries them into the plan's risk
section and into each scenario's `open_assumptions[]`, where the future build skill must
confirm them on first run.

### Documentation is evidence, not truth

Docs drift. A requirement extracted from a specification is a claim about intent, not a
statement of fact about the code, and the design treats it that way throughout: `docs`
extracts with provenance and staleness signals but never reads code to verify, and synthesis
— which by then holds `topology`, `conventions`, and `critique` — is the only place where
doc and code are compared.

A normative document contradicting the code is the highest-signal finding the skill can
produce, because it is either a live defect or a specification nobody maintained. Synthesis
reports the conflict and both readings; it does not decide which one is true.

## Architecture

### Plugin layout

```
profile/
  .claude-plugin/plugin.json
  skills/
    stack/SKILL.md              # /profile:stack
    docs/SKILL.md               # /profile:docs
    topology/SKILL.md           # /profile:topology
    journeys/SKILL.md           # /profile:journeys
  scripts/profile_inventory.py
  references/
    ecosystems.md
    deployment-shapes.md
    doc-sources.md
    journey-sources.md
    contracts/stack.schema.json
    contracts/docs.schema.json
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
containers, documentation, and test files is a project fact, not a testing artifact.

**`itest` phases never invoke that script.** They receive its results as the `stack`
contract, passed by the orchestrator. The contract is the only coupling between the
plugins, which is the property that makes the split worth having.

### Execution graph for `/itest:design`

```
  preflight: profile:{stack,docs,topology,journeys} present in skill listing?
             orchestrator asks for external doc pointers
        │
        ▼
  profile:stack   (gate — every other phase's search strategy depends on the ecosystem)
        │           runs profile_inventory.py itself, then interprets and corrects it;
        │           emits the stack contract, which carries the inventory forward
        ▼
  profile:docs    (gate — every downstream phase reads from the documentary record)
        │
        ├────────────┬────────────┬────────────┬────────────┐   ← five parallel subagents
        ▼            ▼            ▼            ▼            ▼
  profile:topology  profile:journeys  itest:conventions  itest:critique  itest:state
        │            │                │            │            │
        └────────────┴────────────────┴────────────┴────────────┘
                             ▼
             GATE PREP (main context): map requirements → journey candidates
                             ▼
                     ── HUMAN GATE ──
                             ▼
                        SYNTHESIS (main context)
                             ▼
              plan → markdown → offer to save → conflict disposition
```

Notes on the graph:

- **`stack` is a gate, not a parallel peer.** It is cheap — mostly interpreting script
  output — but every other phase needs to know the ecosystem before it knows what to look
  for. It also tells `docs` where documentation conventionally lives in this ecosystem.
- **`docs` is the second gate.** All five downstream phases benefit, not just `journeys`:
  architecture documents sharpen `topology`'s `assumptions[]`, a CONTRIBUTING or testing
  guide is the strongest possible input to `conventions`, and seeding documentation feeds
  `state`. Running `docs` parallel would mean five phases independently re-deriving the same
  prose and disagreeing about it.

  The cost is named rather than hidden: two serial gates now precede the fan-out, and unlike
  `stack` this one is not cheap. That is the price of every phase reading from one
  documentary record instead of five private readings of it.
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
present. Preflight is a direct check for `profile:stack`, `profile:docs`,
`profile:topology`, and `profile:journeys` in that listing.

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
outputs. Three specific corrections that came out of design and are binding:

- `topology` emits **`standup_notes`** — per component, how hard it is to stand up,
  what configuration it needs, what is externally reachable. It does **not** emit test
  boundary options. Synthesis converts those notes into boundary options, because that
  framing is test-specific reasoning.
- `journeys` does **not** emit any hint about existing test coverage. Synthesis builds the
  gap map from `critique` and `conventions` data.
- `docs` emits **requirements**, not test ideas, and **`journey_evidence`**, not journey
  candidates. `profile:journeys` retains sole ownership of candidate formation and ranking;
  `docs` only gives it a far better corpus to work from. One owner per artifact.

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
- `ci[]`, `containers[]`, `iac[]`, `entrypoints[]`
- `docs[{path, doc_type_guess, size, last_modified}]` — every documentation-shaped file
- `docs_sites[{path, generator}]` — `mkdocs.yml`, `docusaurus.config.js`, Sphinx `conf.py`,
  and equivalents, so `docs` knows a rendered site exists and can read its navigation
- `unclassified[]` — every path the script recognized as significant but could not classify
- `coverage_confidence` — `high | partial | low`

**The rule that makes the model fallback work: the script classifies what it recognizes and
explicitly lists what it does not. It never guesses silently.** A populated `unclassified[]`
or a `low` confidence is the signal that tells `stack` to fall back to reading the repo
itself against `references/ecosystems.md`. The same rule applies to documentation: a
doc-shaped file the script cannot type is `doc_type_guess: unknown`, not a confident wrong
label.

Exit 0 on success including partial results; exit 2 only on an unusable path. A script crash
degrades the run to full model-driven discovery rather than failing it.

### `profile:docs`

Reads the project's documentary record and extracts what it says the system is supposed to
do. Doctrine lives in `references/doc-sources.md`.

#### Source acquisition

The binding rule: **the phase never builds a retrieval mechanism, never scrapes, and never
guesses a URL.** It uses a capability that already exists in the session, or reports its
absence. Three tiers:

1. **In-repo** — always available, no configuration. Seeded from the inventory's `docs[]`
   and `docs_sites[]`: README, CONTRIBUTING, `docs/`, ADR trees, `*.md|rst|adoc` outside
   code directories, docs-site navigation, and API description files (OpenAPI, AsyncAPI,
   GraphQL SDL). Read with Read, Glob, and Grep.
2. **User-named external** — collected by the orchestrator preflight, then matched to an
   existing capability: a URL to WebFetch; Confluence or Jira to the Atlassian MCP *if it is
   present in the session's tool listing*; any other MCP or skill the user names; a local
   path outside the repo to Read.
3. **Unreachable** — a named source with no available capability is not improvised around.
   It is recorded in `unavailable_sources[{locator, reason, suggested_remedy}]` and the
   phase continues. Remedies are concrete and actionable: enable the relevant MCP, export
   the page into the repo or a local path, paste the text into a file and re-run. The
   orchestrator surfaces these at the human gate so the user can supply them and re-run, or
   knowingly proceed without them.

#### Triage

Three steps, no user interaction inside the phase.

- **Census** — every candidate: locator, title, headings, size, last-modified (`git log -1`
  for in-repo files), `doc_type` guess.
- **Rank** by likely requirement density. Signals: `doc_type` (`prd`/`requirements`/`spec` >
  `design`/`architecture` > `adr` > `user_guide` > `readme` > `api_reference` >
  `changelog`), recency, presence of normative language (a cheap `rg` for
  `MUST|SHALL|SHOULD|acceptance criteria`), and position in a docs-site navigation.
- **Deep-read** down that ranking until the budget is reached — default ~25 documents.
  Everything below the line goes to `deferred[]` with its census entry and rank.

**The cap is always reported, never silent.** A run that read 25 of 300 documents says so,
and the human gate can pull a deferred document in.

`doc_type` is a fixed vocabulary so downstream phases can reason about it:
`prd | requirements | spec | design | architecture | adr | runbook | api_reference |
user_guide | tutorial | readme | changelog | unknown`.

### Phase contracts

Each phase returns a JSON block conforming to its schema, plus a short prose summary.

**`profile:stack`** — `primary_language`, `languages[]`, `package_managers[]`, `runtimes[]`,
`build_commands[]`, `monorepo{is, packages[]}`, `unknowns[]`, `confidence`. Also corrects
script misclassifications.

**`profile:docs`** —

```
sources_available[{kind, locator, capability_used}]
unavailable_sources[{locator, reason, suggested_remedy}]
corpus[{id, locator, doc_type, title, last_modified, authority, read: full|skimmed}]
deferred[{locator, doc_type, rank, why_deferred}]
requirements[{id, statement, modality: must|should|may,
              actors[], acceptance_criteria[], preconditions_stated,
              source_refs[{corpus_id, anchor}],
              staleness{last_modified, version_refs[], stated_status},
              confidence}]
journey_evidence[{narrative, actor, entry_point_hint, source_refs[]}]
glossary[{term, definition, source_refs[]}]
domain_invariants[]
open_questions[]
coverage_confidence: high|partial|low
```

Three properties of this contract are load-bearing:

`authority` — `normative | descriptive | historical | unknown` — is what makes later
conflict handling meaningful. A normative specification contradicting the code is a defect
candidate; a historical design note contradicting it is merely old.

**There is deliberately no `scope: journey | cross_cutting` field.** Whether a requirement
cuts across journeys is a judgment about the journey set, which does not exist when `docs`
runs. Classifying it here would be guessing. The mapping happens in gate prep, where both
artifacts are in hand.

`glossary` and `domain_invariants` are the quiet win. Scenario titles and assertions written
in the project's own vocabulary — "a settled invoice", "an orphaned tenant" — read as though
someone who knows the domain wrote them, and stated invariants are exactly the material that
produces good negative assertions.

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
`surface_coverage`. Mined from the `docs` contract's `journey_evidence[]` and `glossary[]`,
plus API routes, CLI commands, UI entry points, and issue/milestone titles.

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

## Gate prep and the human gate

**Gate prep** runs in the main context once the fan-out returns. It maps each requirement to
the journey candidates it plausibly belongs to. Requirements that map to none are the
cross-cutting set — the "every response carries a request-id", "all writes are audited",
"tenant data never crosses tenants" class of requirement that no single journey owns.

**The gate** then presents four things, tightest first:

1. Ranked journey candidates — approve, edit, or add
2. Unmapped requirements, ordered by modality (MUST first) then `authority` — approve, drop,
   or attach to a journey
3. `unavailable_sources[]` with their remedies — proceed without them, or abort and re-run
   once they are supplied
4. `deferred[]` — pull one in if journey coverage looks thin

This gate now carries real weight, and its presentation matters: short default-approve
lists, not four separate interrogations.

## Synthesis

Runs in the main context, in eight ordered steps (2b is a sub-step of journey expansion,
not a stage of its own).

**1. Boundary selection.** `standup_notes` × `integration_separation` × state affordances
→ one chosen boundary, stated explicitly with rationale, plus what is real and what is
stubbed at that boundary. This is the single most important sentence in the plan and it is
written down, not assumed.

**2. Journey → scenario expansion.** Each approved journey yields one happy path plus the
failure scenarios that earn their place at this tier. Each scenario carries
`requirement_ids[]` for the requirements it satisfies; documented acceptance criteria supply
failure cases that code-mining alone would not reveal.

The rule: an integration test is justified when the failure arises **from integration** — a
dependency unavailable or slow, partial failure mid-sequence, concurrent access to the same
entity, authorization boundaries, data crossing a serialization boundary, transaction
rollback. Input-validation permutations and pure logic branches are pushed down to unit
tests. This rule applies to documented requirements exactly as it applies to mined ones: a
specified input-validation rule is still a unit test. Without it the most expensive tier
suffers combinatorial explosion, which is how integration suites become the thing everyone
disables.

**2b. Cross-cutting requirement → scenario.** Approved unmapped requirements become
scenarios with `provenance: requirement`. Only approved ones — the gate is where scope is
set.

**3. Precondition design.** Build a DAG over journeys — "delete object" depends on "create
object", which is itself a journey under test — then resolve each edge to compose or
inject, and choose the isolation and cleanup strategy. `preconditions_stated` from the
requirements is an input here. Doctrine in [Compose vs inject](#compose-vs-inject).

**4. Assertion design.** For each scenario, what is actually observable at the chosen
boundary and what to assert on it: response, persisted state read back *through the
interface*, emitted event, observable effect on a real dependency. Never internals.
Documented `acceptance_criteria` become assertions verbatim wherever they are observable at
the boundary, and `domain_invariants` become negative assertions — "and nothing else was
modified" — which is where most real bugs hide. Plus explicit determinism controls: frozen
time, seeded randomness, waiting on conditions rather than sleeping.

**5. Gap map.** Two axes.

*Journey coverage*: approved journeys × `critique` verdicts × existing coverage →
**covered / weak / missing / misleading**.

*Requirements coverage*: each requirement →
**covered / weak / untested / contradicted / unobservable**.

Combined priority order: **contradicted > misleading > untested > missing > weak**.
`contradicted` leads because a normative document disagreeing with the code is either a live
defect or a specification nobody maintained, and both are worth someone's afternoon.
`misleading` still outranks absence: a test that passes while the journey is broken is worse
than no test. `unobservable` — the requirement is real but not checkable at the chosen
boundary — is stated honestly rather than dropped, because it is a finding about the
boundary.

**6. Risks and assumptions.** Every `topology` and `state` assumption that was inferred but
not executed, listed as something the build phase must confirm on first run. Plus flakiness
risks and rough cost. Plus:

```
doc_code_conflicts[{requirement_id, doc_claim, code_evidence, authority,
                    verdict: likely_stale_doc | likely_code_defect | undetermined}]
```

Consistent with the read-only stance, synthesis reports the conflict and both readings; it
does not adjudicate. Only conflicts that touch a scenario are reported — this is not a
documentation audit.

**7. Emission.** Markdown block, then an offer to save to a user-named path.

**8. Conflict disposition.** If `doc_code_conflicts[]` is non-empty, offer — never assume —
one of:

- **Create tracking issues.** One per conflict, or one grouped issue, using a capability
  that already exists in the session: the `github:create-issue` skill, an issue-tracking
  MCP, or `gh`. The same rule as document retrieval applies — **no new issue-creation
  mechanism is built.** If no capability is available, say so and fall back to the next
  option.
- **Save a findings document.** A markdown file at a user-named path listing each conflict,
  its document anchor, its code evidence, and both readings.
- **Neither.** The conflicts remain in the emitted plan.

This exists so an inconsistency discovered in passing is not forgotten the moment the
session ends. It does not widen the auditing scope: it acts only on conflicts synthesis
already surfaced.

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
provenance                  # journey | requirement | both
requirement_ids[]           # traceability back to profile:docs requirements
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
instead of losing it. `requirement_ids[]` is what lets a reader ask "why does this test
exist" and get an answer with a document anchor attached.

For a scenario with `provenance: requirement`, `journey_id` is null.

## Testing

Three layers, all runnable without an LLM.

**`tests/test_profile_inventory.py`** — synthetic mini-repos under
`tests/fixtures/profile_inventory/`: Python + pytest, Go + compose, TypeScript monorepo, and
a deliberately unrecognizable stack. Asserts language and manifest classification,
`test_files[].kind` signals, and that the unrecognizable stack produces a populated
`unclassified[]` with `coverage_confidence: low` rather than a confident wrong answer.

Documentation fixtures extend the same set: a MkDocs site, an ADR tree, a Sphinx project,
and a repo with no documentation at all. Asserts that `docs[]` and `docs_sites[]` populate
correctly, that `doc_type_guess` is `unknown` rather than wrong for an untypable file, and
that the documentation-free repo yields empty arrays rather than guesses.

**`tests/test_itest_contracts.py`** — every `references/contracts/*.schema.json` in both
plugins is valid JSON Schema, and committed example documents validate against them. This
gives the cross-plugin seam teeth: if `profile:stack`'s or `profile:docs`'s output shape
drifts from what `itest` expects, a test fails rather than a workflow.

**`tests/test_plugin_structure.py`** — new, and useful beyond these two plugins. Every
`SKILL.md` has `name` and `description` frontmatter; every `${CLAUDE_PLUGIN_ROOT}`-relative
path referenced in a skill body exists; every plugin directory has a `marketplace.json`
entry.

**What these tests do not cover, stated plainly:** synthesis behavior. Conflict detection,
gap-map ordering, boundary selection, and requirement-to-journey mapping are model
judgments and are not exercised by the non-LLM suite. Only the census and the contract
shapes are.

## Repo integration

Two `.claude-plugin/marketplace.json` entries and two README sections, matching existing
house style.

## Out of scope

- The build skill that implements scenarios (seam specified, skill deferred)
- Executing anything during discovery — no container boots, no test runs, no health checks
- Building any documentation retrieval mechanism; only existing capabilities are used
- Building any issue-creation mechanism; only existing capabilities are used
- Comprehensive documentation accuracy auditing — only conflicts touching a scenario are
  reported
- Writing or repairing documentation
- Persisting the plan by convention; saving is offered, never assumed
- Unit test design, performance testing, and security testing
```