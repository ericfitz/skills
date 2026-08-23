---
name: report
description: Render the dependency-model synthesis contract into a human-readable document — an inventory summary by category, the health definitions, the Mermaid dependency graph, cycles, and assumptions. Read-only. Use when a system's dependency and health picture needs to be handed to a reader rather than a downstream contract consumer. Writes docs/dependencies.md.
---

# report

Render the `synthesis` contract into `docs/dependencies.md`: a human-readable
document covering the inventory, the health definitions, the dependency
graph, its cycles, and the assumptions behind all of it.

**This skill writes one document and executes nothing against the target.**
It reads the `synthesis` contract; nothing is built, started, resolved, or
queried at runtime.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/synthesis.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/synthesis.example.json`
Definitions: `${CLAUDE_PLUGIN_ROOT}/references/definitions.md`
Mermaid renderer: `${CLAUDE_PLUGIN_ROOT}/scripts/depgraphlib/mermaid.py`

## Usage

    /dependency-model:report [path]

Bootstrap: if you were not handed a `synthesis` contract, invoke `synthesize`
by name and take the contract it emits. `synthesize` in turn invokes
`profile:topology` and the six discovery skills by name to build one — never
invoke any of them yourself, and never invoke another plugin's script by
path.

## Procedure

1. Obtain the contract. Take the `synthesis` contract you were handed, or
   invoke `synthesize` by name and take the contract it emits.

2. Write `docs/dependencies.md` with these sections, in order:
   - **Inventory summary**, one subsection per category present in
     `inventory.categories`. For a category whose `status` is `discovered`,
     list its dependencies — name, lifecycle, evidence — or state plainly
     that the list is empty. For a category whose `status` is
     `not-applicable`, say the category does not apply to this project. For
     a category whose `status` is `failed`, state that the scan for that
     category failed and why, if the contract's assumptions say why — never
     describe a failed category's empty list as "no dependencies"; a failed
     scan and an empty result are different findings, and this document is
     the last place a reader can still tell them apart.
   - **Health definitions**: reproduce the taxonomy from `definitions.md`
     (healthy, unhealthy, degraded — stated as prose intent, not yet
     technically defined), then list each `health[]` entry's `service_id`
     and its `conditions[]`: `kind`, `subject_id`, `expectation` (or, when
     `expectation` is `null`, state plainly that no declaration was found —
     never that a bound is confirmed absent), `required_for`, and
     `evidence`.
   - **Dependency graph**: see step 3.
   - **Cycles**: list each cycle detected in `graph.cycles`, or state there
     are none. `graph.cycles` is not an exhaustive enumeration of every
     simple cycle in the graph — say so, rather than presenting the list as
     complete.
   - **Assumptions**: list every `assumptions[]` entry — `claim` and
     `why_unconfirmed`.

3. Render the Mermaid graph from the contract's own `graph.nodes` and
   `graph.edges` — they already carry everything the diagram needs. Do not
   re-scan the target or re-invoke any discovery skill to produce it. Reuse
   `to_mermaid`, the same renderer `depgraph.py` calls, applied to `graph`
   from the contract:

       PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/scripts python3 -c "
       import json
       from depgraphlib.mermaid import to_mermaid
       contract = json.load(open('CONTRACT.json'))
       print(json.dumps(to_mermaid(contract['graph'])))
       "

   This returns `{"mermaid": ..., "degraded": ..., "node_count": ...,
   "reason": ...}`. When `degraded` is `false`, embed `mermaid` in a
   ` ```mermaid ` fence. **When `degraded` is `true`, do not emit a fence at
   all** — a truncated or absent diagram rendered as if complete would read
   as "this is the whole graph." Instead, state in prose, in the graph
   section, that the graph exceeded the node cap, the `node_count`, and the
   `reason` given.

4. If `mmdc` can be run — `npx -y -p @mermaid-js/mermaid-cli mmdc -i
   fence.mmd -o /tmp/dependencies-graph.svg` on the fence's source — verify
   the fence renders before writing the document. If `mmdc` cannot be run
   (no network, `npx` unavailable), say so plainly in the graph section: the
   diagram was not render-verified.

5. Publish the document as an Artifact only when asked to; do not publish
   one by default.

6. Emit a short prose summary: category count by status, health entry
   count, cycle count, and whether the graph was render-verified.

## Rules

- Read-only. Nothing is built, started, resolved, or queried at runtime;
  this skill writes one document and reads the contract it renders.
- `null` in `expectation` means no declaration was found — never that a
  bound is confirmed absent.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding.
  A category whose `status` is `failed` is a different finding and must be
  stated as failed, never rendered as if it were an empty discovered list.
- The report is a rendering. It adds no facts the contract does not carry —
  no criticality, ranking, or blast radius judgment, and no health state
  beyond what `health[]` already states.
- Never invoke another plugin's script by path; obtain the contract from
  `synthesize` by name.
