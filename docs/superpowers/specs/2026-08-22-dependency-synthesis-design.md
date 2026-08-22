# dependency-model — synthesis: report, dependency graph, service health

Design spec for [#49](https://github.com/ericfitz/skills/issues/49), layer 2 of
[#46](https://github.com/ericfitz/skills/issues/46).

Date: 2026-08-22

## Problem

Layer 1 ([#48](https://github.com/ericfitz/skills/issues/48)) discovers a system's
dependencies as six category contracts, each a flat list of facts with `file:line`
evidence. Nothing joins them.

The joins are where the value is. A `service` entry and a `network` entry describe
the same Postgres from two sides and link through `related_ids`; syft's
`depends_on` edges form a real package graph; and neither is any use to a human
until something renders it. Layers 3 and 4 need the joined form too — a monitoring
gap analysis and a chaos plan both reason over a graph, not six lists.

This layer produces that join once, as a contract, and renders it.

## Scope

Two new skills in the existing `dependency-model` plugin, plus an amendment to
layer 1's contract:

| Skill | Produces |
|---|---|
| `synthesize` | the `synthesis` contract — merged inventory, typed dependency graph, per-service health definitions |
| `report` | `docs/dependencies.md` with a Mermaid graph; an Artifact on request |

### D1 — Journey exposure is split out of this issue

#49 as filed bundled journey exposure with the three synthesis deliverables. It is
different in kind: it needs a second input (confirmed journeys), a reachability
engine (`graphify`/`sem`), and it carries the only acceptance criterion phrased as
a verification rather than a build — "verify `graphify path` can reliably connect a
journey entry point to a package's import sites."

If that verification comes back negative, the report, graph, and health definitions
are unaffected. Welded together, a negative result blocks four deliverables instead
of one. So journey exposure gets its own issue and its own brainstorm → spec → plan
cycle.

The synthesis contract still reserves the slot it will fill: `required_for[]` on
each health condition (D8). Until the exposure work lands, that field carries
whatever static evidence shows.

## Decisions

### D2 — Health is defined over run-time dependencies only

"Dependency" is overloaded in this project, and the two senses were never
distinguished in layer 1:

- **build-time** — packages and modules the system is built against
- **run-time** — services, network paths, configuration, and credentials the system
  needs while running

**Healthy means: all run-time dependencies are met, and all metric-sensitive
run-time dependencies are within acceptable bounds.** Build-time dependencies are
not part of health.

`references/definitions.md` states this, because the ambiguity lives in layer 1's
six categories rather than in this layer.

### D3 — `lifecycle` is added to the layer-1 contract, and no version moves

The build/run split is a fact about a dependency, so it belongs on the dependency,
not in one consumer that re-derives it. `dependency-core.schema.json` gains a
required `lifecycle` enum — `build`, `run`, `both` — set by each layer-1 skill from
evidence it already reads:

| Category | `lifecycle` |
|---|---|
| `package` | `build` |
| `service`, `network`, `config`, `security` | `run` |
| `platform` | per `details.kind`: `cpu`/`memory`/`disk`/`gpu`/`cloud-service` → `run`; `arch`/`os`/`runtime-version` → `build` |

`platform` is the only category needing a rule rather than a constant. A test pins
the mapping: an unenforced classification is how two skills come to disagree about
the same entry.

`both` is for a genuine straddler — a package also loaded at runtime by a plugin
host. Each SKILL.md states that it is used only with evidence, never as a hedge; a
three-value enum with a vague middle invites shrugging into it.

Making the field required invalidates all six shipped category examples, which
carry no `lifecycle`. All six are updated in the same change, and the existing
contract test — which validates every example against its schema — is what catches
any that are missed.

**No version number moves.** `contract_version` stays `1.0.0`. Versions in this
marketplace advance when the user declares a feature productionized, not when a
schema changes. This plugin is unfinished; the contract is amended in place.

### D4 — The contract is the interface; the report is a rendering

`synthesize` emits the contract; `report` renders it. #50 and #51 read the
contract, humans read the report. This matches how every other plugin here hands
data across, and keeps presentation out of the dependency path of two downstream
issues.

### D5 — Two skills, not one and not three

One skill would orchestrate, merge, derive, and render — four jobs, against a
plugin whose layer-1 discipline is one skill, one job.

Three skills (`graph`, `health`, `report`) over-decomposes: `graph` and `health`
are transforms over contracts someone else already gathered, so as standalone
skills each needs six envelopes handed in. Layer 1's six skills each had their own
evidence to read; these do not.

Two splits on the line D4 already draws: data and presentation.

### D6 — The deterministic half goes in a script

`scripts/depgraph.py` plus `depgraphlib/`, mirroring `depscan.py`: merge the six
envelopes by key union, resolve edges, detect cycles, emit Mermaid, apply the node
cap. All mechanical, all unit-testable against fixture envelopes, and no reason for
two runs on the same input to differ.

What needs judgment — reading a service's evidence and stating what must hold for
it to be healthy — stays with the LLM in `synthesize`.

Stdlib-only, `uv run --script` with a documented `python3` fallback, as `depscan.py`
is.

### D7 — Health is a uniform `conditions[]`, not `requires[]` plus `bounds[]`

Two special-cased lists quietly encode a binary: presence is met or not, bounds are
within or not, and a consumer ANDs them. Real systems have a middle — a dependency
online but reporting degraded, a dependency online but outside its bounds, a
dependency unavailable that only a secondary function needs.

So the contract emits conditions, uniformly:

```json
{
  "kind": "presence | bound | upstream_health",
  "subject_id": "service:postgres-primary",
  "expectation": { "value": "5s", "evidence": ["internal/db/pool.go:44"] },
  "required_for": ["journey:checkout"],
  "evidence": ["docker-compose.yml:12"]
}
```

The `required_for` value above is illustrative of the eventual shape. Journey ids
only become available once the split-out exposure work (D1) lands; until then the
field carries whatever static evidence shows — a component name, an entry point, a
consuming file — or an empty list when nothing static connects the dependency to a
named function.

`presence` — the dependency is reachable. `bound` — it is within a declared bound.
`upstream_health` — it is itself healthy, which composes because services have
health entries and the graph links them.

Adding a fourth condition kind later is an enum addition, not a reshape.

`expectation: null` means **no declaration was found** — never "no bound is
needed." This is layer 1's discipline one level up: layer 3 decides whether an
unbounded request-path dependency is a real gap, and layer 2 must not have
pre-judged it.

### D8 — Each condition carries `required_for[]`

Without it every unmet condition looks identical and any failure reads as total. A
dependency needed only by a secondary function is exactly the case that must be
distinguishable.

It stays factual: `required_for` records *which* functions or code paths need this
dependency, not how important they are. Journey importance already lives on the
journey (`business_criticality` in the `profile:journeys` contract), so layer 3
joins the two.

This is the slot the split-out journey-exposure work (D1) fills.

### D9 — No state vocabulary appears in this layer's schema

There is no `healthy | degraded | unhealthy` enum anywhere in what `synthesize`
emits. States that are not encoded cannot be encoded wrongly, and defining
`degraded` later becomes a new mapping over conditions that already exist, in a
consumer not yet written.

The taxonomy is written down in `references/definitions.md` as stated intent, and
marked as not yet technically defined so a reader knows the omission is deliberate:

- **healthy** — all conditions hold
- **unhealthy** — a `presence` condition fails for something critical functionality
  needs
- **degraded** — anything in between: a dependency reporting degraded itself, one
  outside its bounds, or one unavailable that only a secondary function needs

A test asserts the schema carries no such enum, so D9 is executable rather than
aspirational.

### D10 — Mermaid in a repo document, with a stated cap; Artifact on request

The report is `docs/dependencies.md` with the graph as a ` ```mermaid ` fence:
text-diffable as #49 requires, reviewable in a PR, and renders natively on GitHub.
`report` can additionally publish an Artifact when asked, for a graph worth panning
around or sharing.

Mermaid degrades badly at scale, so `depgraph.py` applies a node cap — 60 to start,
tunable in implementation — above which it emits a summary and a pointer instead of
an unreadable fence, and the report states that it degraded and why. Silent
truncation would read as "this is the whole graph."

## Architecture

### Layout

```
dependency-model/
  scripts/depgraph.py                    merge, edges, cycles, mermaid
  scripts/depgraphlib/                   testable modules
  references/contracts/
    synthesis.schema.json                the layer-2 contract
    examples/synthesis.example.json
    dependency-core.schema.json          AMENDED: + lifecycle
  references/definitions.md              dependency senses, health, the taxonomy
  skills/synthesize/SKILL.md
  skills/report/SKILL.md
```

### Data flow

```
profile:topology ─┐
                  ├─→ six discovery skills ─→ six envelopes
                  ▼
          /dependency-model:synthesize
                  │  1. gather the six (invoke by name if not handed them)
                  │  2. depgraph.py → merge, edges, cycles, mermaid
                  │  3. LLM        → health conditions, required_for, assumptions
                  ▼
            synthesis contract ──→ #50, #51
                  ▼
          /dependency-model:report → docs/dependencies.md (+ Artifact)
```

Standalone invocation follows layer 1's pattern: `report` invokes `synthesize` if
not handed a contract; `synthesize` invokes the six discovery skills if not handed
envelopes. By name, never by path.

### The synthesis contract

Four parts:

**`inventory`** — the six discovery envelopes merged. Because each layer-1 skill
emits a full envelope with exactly one category populated, this is a key union
rather than a transform.

**`graph`** — nodes and typed edges:

- `depends_on`, from `package.details.depends_on[]` — syft's `dependency-of` edges,
  package to package, `lifecycle: build`
- `relates_to`, from `related_ids[]` — cross-category links, `lifecycle: run`

Keeping the two kinds distinct is what makes the graph answerable in both senses of
"dependency": a consumer asking what must be reachable at runtime filters to `run`
edges; one asking what the system is built against filters to `build`.

Plus `cycles[]` — a cycle is a fact and deterministic to detect.

**`health`** — one entry per run-time service, holding `conditions[]` per D7.

**`assumptions[]`** — same shape as layer 1's.

### Error propagation

A layer-1 category with `status: "failed"` propagates into the synthesis contract as
failed. It must never flatten to an empty list: the report would then state as fact
that a system has no network dependencies when the scan simply broke. Layer 1 spent
a rule on the empty-versus-failed distinction, and a merge is exactly where it gets
lost.

## Rules

**Read-only.** Nothing is executed against the target system, and nothing is
measured. Every bound in a health condition is a declared one.

**No criticality, no ranking, no scores on dependencies or edges.** Layer 3 judges.
`required_for` records which function needs a dependency, never how much it matters.

**`null` means no declaration was found**, never "confirmed absent" and never "not
needed."

**Skills invoke skills by name**, never by path.

## Testing

| Test | Asserts |
|---|---|
| `tests/test_depgraph_*.py` | `depgraphlib` against fixture envelopes: key-union merge, both edge kinds, cycle detection, Mermaid emission, node-cap degradation |
| `tests/test_dependency_model_contracts.py` (extended) | the synthesis schema and its example; `conditions[]` accepts all three kinds and a `null` expectation |
| `tests/test_dependency_model_coupling.py` (extended) | the two new skills state the `null` discipline, name their own contract, and reach into no other plugin by path |

Four tests exist specifically to pin decisions from this design, because each
guards a choice that would otherwise erode silently:

1. The synthesis schema contains no `healthy`/`degraded`/`unhealthy` enum (D9).
2. The `lifecycle` mapping is pinned per category, including `platform`'s split by
   `details.kind` (D3).
3. A `status: "failed"` category propagates as failed through the merge.
4. `expectation: null` is legal and documented as "no declaration found" (D7).

## Definition of done

The plugin-registration checklist in `CLAUDE.md` applies in full — this adds skills
to an existing plugin, so the `PLUGINS` array skills list becomes
`config,network,package,platform,report,security,service,synthesize`, `SCRIPTS`
gains `depgraph.py`, Codex manifests regenerate, and the README section and
`docs/ARCHITECTURE.md` graph and catalog gain both skills.

Specific to #49:

1. Both skills implemented, `synthesize` emitting a valid contract
2. Layer 1 amended with `lifecycle`, all six skills setting it, mapping pinned
3. `references/definitions.md` written
4. `requirements.json` declares `mmdc` optional — when present, `report` verifies
   its generated Mermaid renders, the same discipline `CLAUDE.md` imposes on
   `docs/ARCHITECTURE.md`; when absent, the report says so rather than shipping a
   possibly-broken fence
5. All four CI checks green

## Out of scope

Deferred by explicit decision:

- **Journey exposure** — its own issue (D1)
- **Any runtime evaluation of health.** This layer defines conditions; it never
  evaluates them
- **The degraded/unhealthy state vocabulary in schema** — prose only (D9)
- **Criticality, ranking, or blast radius** — layer 3
- **Any version bump** — until the user declares the feature productionized (D3)
