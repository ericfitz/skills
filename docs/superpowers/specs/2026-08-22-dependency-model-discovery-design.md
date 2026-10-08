# dependency-model — dependency discovery skills and contract schemas

Design spec for [#48](https://github.com/ericfitz/skills/issues/48), layer 1 of
[#46](https://github.com/ericfitz/skills/issues/46).

Date: 2026-08-22

## Problem

A system's dependencies are scattered across manifests, lockfiles, compose files,
IaC, CI config, and source literals. Nothing in this marketplace enumerates them.
`profile:topology` reports a coarse `real_dependencies` list as a side effect of
determining deployment shape, but it is not an inventory and was never meant to be
one.

Layers 2–4 of #46 need that inventory: a dependency report and graph (#49), a
monitoring and resilience gap analysis (#50), and a chaos test plan (#51). All
three read the same facts. This layer produces them once, as versioned contracts.

## Scope

A new plugin, `dependency-model`, with six read-only discovery skills — one per
dependency category named in #46:

| Category | Question it answers |
|---|---|
| package | What libraries does this ship with, and at what versions? |
| service | What out-of-project services does it need — databases, queues, caches, APIs? |
| config | What configuration must be supplied for it to run? |
| security | What secrets and permissions does it require? |
| platform | What OS and cloud resources does it declare a need for? |
| network | What names, hosts, and ports must resolve and connect? |

Layers 2–4 are out of scope here, but their contract is designed here (#48 AC 3).

## Decisions

Each of these settled a real fork. They are recorded with their rationale because
the rationale is what makes them reviewable later.

### D1 — Contracts carry failure-relevant facts, not judgments

Each dependency records observable facts that bear on how it fails: whether a
timeout, retry, fallback, or health check is declared, and whether it sits on a
startup path or a request path. These are facts with `file:line` evidence, in the
same discipline as everything else.

They are not criticality ratings. Layer 3 judges criticality; layer 1 hands it the
evidence so it need not re-read every file to do so.

### D2 — Shared envelope, six referenced sub-schemas

One `discovery.schema.json` envelope with categories keyed by name, and six
category sub-schemas it `$ref`s. Consumers get one entry point; each category
stays independently editable.

Keying categories by name — rather than discriminating a single array by a
`category` field — means the schema needs no `oneOf` and no `if`/`then`, and it
gives the emission model in D6 for free.

### D3 — Static discovery only; nothing is ever executed

No name resolution, no port probing, no latency measurement, no container boot.

The rationale is not caution, it is correctness: these skills run on a developer's
machine or in CI, never inside the environment the code actually runs in. A
latency measured from a laptop is not the system's latency, and a hostname that
resolves on a workstation may not resolve in production. An observed value would
be a confidently wrong value.

So every claim is what the code and config **declare**. Anything that cannot be
confirmed from the repository goes in `assumptions[]` and stays there.

### D4 — Six skills, one per category

One skill : one sub-schema : one category, matching every other plugin here. Each
is small, independently invocable, and parallelizes cleanly as subagents.

The cost of this choice is that several categories read overlapping evidence — the
same compose file feeds service, config, platform, and network. D5 pays that cost
down.

### D5 — One shared scan script, then LLM judgment per category

A bundled deterministic script makes a single pass over the repository and emits a
raw evidence index. All six skills read the index instead of re-walking the tree.

The script extracts and locates; it does not classify. Classification, correlation,
and resilience-fact assembly are the LLM's work in each skill.

### D6 — Each skill emits a full envelope with one category populated

A single skill's output is therefore already valid against the top-level schema,
and layer 2's merge is a key union rather than a transform.

### D7 — syft is required for the package category

`syft scan dir:` covers roughly thirty ecosystems and emits `artifactRelationships`
including `dependency-of` edges — a real dependency graph, which #49 needs anyway.
Writing and maintaining per-ecosystem lockfile parsers to re-derive that would be
poor use of effort.

It is declared **required** in `requirements.json`. `/env:check` discovers sidecar
declarations automatically, so no change to the `env` plugin is needed.

Two consequences, both verified against this repository on 2026-08-22 with syft
1.51.0:

- **No line numbers.** `locations[].path` is file-level. Package evidence is
  therefore a file path, not `file:line`. The other five categories keep `file:line`.
- **Declared and installed are conflated.** An unscoped `syft scan dir:.` of this
  repository reported 270 packages where `pyproject.toml` declares 2 direct
  dependencies plus one optional extra; 188 came from a nested
  `writing/skills/boring/.venv/` and 7 from `.venv/`. Exclusions are mandatory, and
  `resolution` (declared / locked / installed) is a required field.

### D8 — Deferred to layer 2: orchestration

Layer 1 ships six invocable skills and a documented sequence. #49's report skill
becomes the orchestrator, since it must gather all six contracts to render anything.
Building an orchestrator now would mean building it twice.

The sequence — invoke `profile:topology`, run `depscan.py` once, then the six skills
in any order or in parallel — is documented in `references/running-discovery.md` and
summarized in the plugin's `README.md` section.

### D9 — Source-literal patterns cover Go, TypeScript/JavaScript, and Python

`depscan.py` extracts `resilience_calls` and `env_refs` from source for those three
ecosystems only. They are the three `dev:*` and `deps:bump` already commit to, and
per-ecosystem literal matching does not generalize the way manifest detection does.

This bounds only source-literal matching. Every ecosystem still gets full coverage
of the file-based evidence — compose, k8s, IaC, CI, `.env` — and the package
category covers roughly thirty ecosystems through syft regardless.

When a repository's primary language falls outside the three, each affected skill
records an assumption naming the language and what went unscanned, so the gap is
visible in the contract rather than silently absent.

## Architecture

### Layout

```
dependency-model/
  .claude-plugin/plugin.json          v0.1.0
  .codex-plugin/plugin.json           generated by scripts/gen_codex_manifests.py
  requirements.json                   syft: required
  scripts/depscan.py                  shared evidence scan
  scripts/depscanlib/                 testable extractor modules
  references/contracts/
    discovery.schema.json             envelope
    package.schema.json
    service.schema.json
    config.schema.json
    security.schema.json
    platform.schema.json
    network.schema.json
    examples/<category>.example.json  one worked example each
  references/
    categories.md                     what belongs in which category, and the
                                      service/network overlap rule
    resilience-signatures.md          Go/TS/JS/Python timeout/retry/breaker patterns
    running-discovery.md              the documented sequence (D8)
  skills/{package,service,config,security,platform,network}/SKILL.md
```

### Position in the marketplace

`profile:topology` → contract → each of the six skills. Same dependency direction
as `itest` → `profile`. `profile` is not modified (#48 AC 4).

Coarse overlap between `topology.real_dependencies` and this plugin's `service`
category is accepted refinement-tier redundancy, exactly as `stack` → `topology`
overlaps today.

### Contract

Envelope:

```json
{
  "contract_version": "1.0.0",
  "target": "/abs/path/to/repo",
  "seeded_by": {"contract": "profile:topology", "contract_version": "1.0.0"},
  "categories": {
    "service": {
      "status": "discovered",
      "dependencies": [],
      "assumptions": [{"claim": "...", "why_unconfirmed": "..."}]
    }
  }
}
```

`status` is one of `discovered`, `not-applicable`, or `failed`, so an empty
`dependencies` list is never ambiguous. An empty `service` list is a legitimate
finding for a pure library; a failed scan is not the same thing.

Shared core, identical across all six sub-schemas:

```json
{
  "id": "service:postgres-primary",
  "name": "postgres",
  "evidence": ["docker-compose.yml:12", "internal/db/pool.go:41"],
  "related_ids": ["network:postgres-5432"],
  "resilience": {
    "timeout":      {"value": "5s", "evidence": ["internal/db/pool.go:44"]},
    "retry":        null,
    "fallback":     null,
    "health_check": {"description": "pg_isready", "evidence": ["docker-compose.yml:19"]},
    "on_path":      ["startup", "request"]
  },
  "details": {}
}
```

`id` is `<category>:<slug>` and stable across runs, so layer 2 can key a graph on it.

**`null` in `resilience` means no declaration was found — never "confirmed
absent."** The distinction is load-bearing: layer 3 reads a null on a request-path
dependency as a *candidate* monitoring gap, and layer 1 must not have already
decided it is a real one. Stated in each schema description and in every SKILL.md.

`related_ids[]` links a dependency to its counterpart in another category. It gives
#49's graph its cross-category edges directly instead of making it re-infer them by
string-matching hostnames.

### `details` per category

| Skill | Primary evidence | `details` fields |
|---|---|---|
| package | syft, with `--exclude` from the scan index | `ecosystem`, `package_manager`, `purl`, `version`, `version_constraint`, `pinned`, `resolution`, `direct`, `depends_on[]` |
| service | `topology.real_dependencies` and `external_third_parties` as seed; compose, k8s, IaC; `url_literals`; client-library imports | `kind`, `protocol`, `client_library`, `managed_by`, `config_keys[]` |
| config | `env_refs`, `.env` files, config loaders, declared defaults | `mechanism`, `key`, `required`, `default`, `consumed_by[]`, `validated` |
| security | `secret_shaped_keys`, IAM and RBAC policy files, auth middleware | `kind`, `provider`, `scope`, `granted_to`, `rotation_declared` |
| platform | Dockerfile, compose, k8s, IaC, CI resource declarations | `kind`, `declared_value`, `source`, `component` |
| network | `host_port_literals`, DNS, egress, proxy, ingress config | `kind`, `value`, `direction`, `protocol`, `resolution_mechanism` |

`service.kind` is one of database, cache, queue, object-store, search, api.
`platform.kind` is one of cpu, memory, disk, gpu, arch, os, runtime-version,
cloud-service. `network.kind` is one of hostname, ip, port, dns, egress, proxy,
ingress. Full enumerations live in the sub-schemas.

Latency and bandwidth under `platform` come only from declared timeouts and
documented SLOs. Per D3 there is nothing to measure.

### Scan script

`scripts/depscan.py`, run via `uv run --script` with a documented `python3`
fallback, mirroring `profile/scripts/profile_inventory.py`.

```json
{
  "scan_version": "1.0.0",
  "target": "/abs/path",
  "exclusions": [".venv", "node_modules", "vendor", "dist", "site-packages", ".git"],
  "files": {"compose": [], "k8s": [], "iac": [], "env": [], "ci": []},
  "findings": {
    "env_refs":           [{"name": "DATABASE_URL", "file": "internal/db/pool.go", "line": 41}],
    "url_literals":       [],
    "host_port_literals": [],
    "secret_shaped_keys": [],
    "resource_limits":    [],
    "resilience_calls":   [{"kind": "timeout", "raw": "5*time.Second", "file": "internal/db/pool.go", "line": 44}]
  },
  "coverage": {"files_scanned": 812, "skipped": [], "confidence": "high"}
}
```

`resilience_calls` is cross-cutting by design: the scanner finds every timeout,
retry, and circuit-breaker literal once, and each skill correlates the ones that
belong to its own dependencies. That is what makes D1 affordable across six skills.

`exclusions[]` is the single source of truth for both tools. The `package` skill
reads it from the index and passes each entry as a `syft --exclude`. Without it,
syft reports a nested virtualenv as the project's dependency set (D7), and the five
file-scanning skills pick up the same noise independently.

Exit codes follow `profile_inventory.py`: `0` on success including partial coverage,
`2` when the target path is unusable.

## Rules

These are constraints on the skills, stated in each SKILL.md.

**Read-only.** Nothing is executed, nothing is modified. Per D3, an unconfirmable
claim becomes an assumption rather than a probe.

**Evidence or assumption, never a guess.** Every factual claim carries `file:line`
(file-level for package, per D7). Everything inferred goes in `assumptions[]` with
why it is unconfirmed.

**The security skill records names and locations, never values.** It reports that
`STRIPE_API_KEY` is read at `billing.go:12` and sourced from a Kubernetes secret. It
does not read the secret's contents, and it does not open files under `~/.keys/`. A
discovery skill that writes credentials into a contract JSON is a credential leak,
so the sub-schema permits no value-shaped field and a test enforces it.

**service and network overlap by design.** Both will see the same `postgres:5432`.
`service` records the thing depended on; `network` records the path used to reach
it. They link through `related_ids[]`. `references/categories.md` carries the
adjudication rule for ambiguous cases.

**No test strategy, no remediation, no criticality.** This layer reports facts.
Layers 2–4 decide what they mean.

**Skills call each other by name, never by path.** No skill reaches into
`profile/scripts/`. Standalone invocation bootstraps its own `topology` contract by
invoking `profile:topology`.

## Testing

| Test file | Precedent | Asserts |
|---|---|---|
| `tests/test_depscan_*.py` | `test_profile_walk.py`, `test_profile_manifests.py` | `depscanlib` extractors against `repobuilder` fixtures |
| `tests/test_dependency_model_contracts.py` | `test_profile_contracts.py` | every example validates against its sub-schema and the envelope |
| `tests/test_dependency_model_coupling.py` | `test_itest_coupling.py` | the six skills never reference `profile/scripts/` by path; each names its own contract and example |
| `tests/test_schema_check_refs.py` | new | local-file `$ref` resolution |

One case is called out because it enforces the credential rule: the `security`
example must contain no value-shaped field. A schema that permits one is a single
careless run away from writing a secret to disk.

### Change required to a shared test helper

`tests/schema_check.py` supports only `type`, `properties`, `required`, `items`, and
`enum`. It cannot resolve `$ref`, which D2 depends on.

It gains local-file `$ref` resolution: an optional `base_dir` argument and a resolve
step, roughly thirty lines with its own test. The alternative — duplicating the
shared core into six files — reintroduces exactly the drift D2 exists to prevent.
This is a contained improvement to a helper this work already uses.

## Definition of done

The plugin-registration checklist in `CLAUDE.md` applies in full. Specific to #48:

1. All six skills implemented, each emitting a valid envelope
2. `docs/ARCHITECTURE.md` — replace the dashed `planned — issue 46` subgraph with
   the real six-skill subgraph and its `topology` edge, add the catalog rows, and
   re-render the Mermaid with `mmdc` rather than eyeballing it
3. `requirements.json` declares syft as required
4. All four CI checks green

## Out of scope

Deferred by explicit decision, not oversight:

- The orchestrator — layer 2's report skill (D8)
- Vulnerability data — grype and trivy are adjacent but #46 does not scope CVEs
- Criticality, blast radius, and monitoring-gap judgment — layer 3 (D1)
- Every form of live probing — resolution, reachability, measurement (D3)
- `graphify`/`sem` journey-exposure reachability — folded into layer 2's design
  per the #46 decomposition
