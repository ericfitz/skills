---
name: synthesize
description: Gather the six dependency-model discovery contracts for a repository, merge them into one graph, and derive which dependencies carry a failure-relevant health condition. Read-only. Use when a system's dependency inventory and health picture need to be assembled from the six discovery skills' output. Emits the dependency-model:synthesis contract.
---

# synthesize

Gather the six discovery envelopes for a repository, merge them into one
inventory and graph, and derive the health view: which dependencies carry a
condition that can be stated with evidence. Emits the `synthesis` contract.

**This skill executes nothing against the target system.** It reads the six
discovery envelopes and `depgraph.py`'s output; nothing is resolved, probed,
or run against the target.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/synthesis.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/synthesis.example.json`
Definitions: `${CLAUDE_PLUGIN_ROOT}/references/definitions.md`
Merge script: `${CLAUDE_PLUGIN_ROOT}/scripts/depgraph.py`

## Usage

    /dependency-model:synthesize [path]

Standalone invocation: if you were not handed the six discovery envelopes,
invoke `profile:topology` first, then `depscan.py` once, then the six
discovery skills **by name** — `/dependency-model:service`,
`/dependency-model:package`, `/dependency-model:config`,
`/dependency-model:security`, `/dependency-model:platform`,
`/dependency-model:network` — in any order. Never invoke another plugin's
script by path, and never reach into a discovery skill's internals; invoke
each skill by name and take its envelope.

## Procedure

1. Gather the six envelopes. For each discovery skill whose output you were
   not already handed, invoke it by name and save its emitted envelope JSON
   to a file. A skill that reports `status: "failed"` for its category still
   produces a file — save it as emitted, do not skip it or retry the scan.

2. Run `depgraph.py` over the saved envelope files:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depgraph.py ENVELOPE.json [ENVELOPE.json ...]

   This returns `{"inventory": {...}, "graph": {...}, "mermaid": {...}}`: the
   merged inventory (key union across categories), the typed-edge graph with
   `depends_on` and `relates_to` edges and any cycles found, and a Mermaid
   rendering. Take `inventory` and `graph` unchanged into the contract.
   `mermaid` is a working-document extra the report skill consumes — it is
   deliberately not in the contract, so do not carry it forward.

3. For each service-shaped dependency in the merged inventory, derive its
   `conditions[]`. Which dependencies contribute a condition is decided by
   the failability test in `definitions.md` — not by `lifecycle` and not by
   category: a dependency enters a health definition iff it can fail
   independently while the process is up, and a condition can be stated
   about it with evidence. That set includes a service, a credential, a
   resource limit, remote configuration, a network path, and a dynamically
   loaded package. A bundled library produces no such condition and
   self-excludes. A dynamically loaded package — a reflectively resolved
   JDBC driver, an `importlib` plugin, a `dlopen`ed `.so` — produces a
   `presence` condition citing the `file:line` of its loading site **when
   one appears in the evidence this skill can read**. Nothing in layer 1
   today records that a package is dynamically loaded, or where; when no
   loading site appears, the package contributes no condition and an
   assumption is recorded naming the gap.

4. Assign `kind` per condition: `presence` when the condition is that the
   subject must exist or resolve (a network path reaching, a dynamically
   loaded package loading, a config key being set); `bound` when a declared
   metric limit applies (a timeout, a retry count, a pool size); `upstream_health`
   when the requirement is that another service's own health entry is itself
   healthy.

5. Set `expectation` to the declared value with its `file:line` evidence when
   one was found in the inventory's `resilience` facts, or `null` when none
   was found. **`null` means no declaration was found — it never means no
   bound is needed.** Whether an unbounded request-path dependency is a real
   gap is a judgment for a later layer, not this contract.

6. Fill `required_for[]` with the ids of functions or components that static
   evidence connects to this condition — a component name, an entry point, a
   consuming file. Leave it empty when nothing static connects it. It records
   which callers need the condition met, never how important any of them are.

7. Carry every category's `status` through unchanged from the merged
   inventory. A `failed` category stays `failed` — never flattened to an
   empty list, because that would assert absence where a scan merely broke.

8. Emit the contract: `contract_version`, `target`, the `inventory` and
   `graph` from step 2 unchanged, the `health` array from steps 3-7, and
   `assumptions` carried and merged from the six envelopes plus any you added
   while deriving conditions. Follow with a short prose summary: service
   count, condition count by `kind`, and any category whose status is
   `failed`.

## Rules

- Read-only. Nothing is resolved, probed, or run at runtime.
- `null` in `expectation` means no declaration was found — never that a bound
  is confirmed absent or unnecessary.
- An empty `health` list is a legitimate finding for a system with no
  service-shaped dependencies. A `failed` category is a different finding
  from an empty one and must never be collapsed into it.
- No criticality, ranking, or blast radius judgment. `required_for[]` records
  which callers need a condition met, not how important any of them are — that
  judgment belongs to a later layer.
- Invoke the six discovery skills, and `profile:topology`, by name — never by
  reaching into another plugin's directory by path.
