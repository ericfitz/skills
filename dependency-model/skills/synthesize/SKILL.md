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
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py synthesis <file.json>` (exit 0 = valid) before returning it.
Definitions: `${CLAUDE_PLUGIN_ROOT}/references/definitions.md`
Merge script: `${CLAUDE_PLUGIN_ROOT}/scripts/depgraph.py`
Health script: `${CLAUDE_PLUGIN_ROOT}/scripts/health.py`

## Usage

    /dependency-model:synthesize [path] [--ref <branch>]

Standalone invocation: if you were not handed the six discovery envelopes,
run `depscan.py` once first (it prints the run dir; the scan gives
`scan_root`), then invoke `profile:topology` (which invokes `profile:stack`)
on `scan_root` — with `--ref` that is the snapshot, not the live tree — and
save their contracts to `<run_dir>/stack.json` and `<run_dir>/topology.json`,
then invoke the six discovery skills **by name** — `/dependency-model:service`,
`/dependency-model:package`, `/dependency-model:config`,
`/dependency-model:security`, `/dependency-model:platform`,
`/dependency-model:network` — in any order. Never invoke another plugin's
script by path, and never reach into a discovery skill's internals; invoke
each skill by name and take its envelope.

## Procedure

1. Gather the six envelopes. For each discovery skill whose output you were
   not already handed, invoke it by name, passing the same `--ref` to each,
   and save its emitted envelope JSON to `<run_dir>/<category>.json` in the
   run dir the shared scan printed. A skill that reports `status: "failed"` for its category still
   produces a file — save it as emitted, do not skip it or retry the scan.

2. Run `depgraph.py` over the saved envelope files, passing the topology
   contract so the system's own components become graph nodes:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depgraph.py ENVELOPE.json [ENVELOPE.json ...] --topology <run_dir>/topology.json

   This returns `{"inventory": {...}, "components": [...], "graph": {...},
   "mermaid": {...}, "unresolved": [...]}`: the
   merged inventory (key union across categories), the topology's
   `components[]` with a `component:<slug>` id added (first-party, so they
   are graph nodes and health anchors but never inventory entries), the
   typed-edge graph with `depends_on` and `relates_to` edges and any cycles
   found, and a Mermaid
   rendering. If it exits 2 because the envelopes disagree on `target` or
   `ref`, they came from different repos or branches: re-run discovery for
   one of them instead of merging. Take `inventory`, `components` and `graph` unchanged into the contract.
   `mermaid` is a working-document extra the report skill consumes — it is
   deliberately not in the contract, so do not carry it forward.

   **Reconcile `unresolved` before going on.** Each entry is a link
   (`from`, `to`, `kind`) whose target matched no node; depgraph.py also
   counts them on stderr. The discovery skills ran in parallel and guessed
   each other's ids, so most are the same thing under a different slug
   (`service:postgres` written, `service:postgres-primary` discovered). A
   link written as `service:<x>` for a first-party component already
   resolves to `component:<x>` when that component node exists. For
   each entry:
   - If exactly one node in the target's category is plainly the same
     real-world thing, rewrite that id in the `from` entry of the saved
     envelope in `<run_dir>` (never in the repo). A link that names one of
     the system's own components under another slug is rewritten to that
     component's `component:<slug>` id the same way.
   - Otherwise leave it and record an assumption naming both ids and why
     no node matched. Never invent a node to satisfy a link.
   Re-run depgraph.py over the rewritten envelopes and take its output. An
   `unresolved` list that is still non-empty is fine once every remaining
   entry has its assumption; `unresolved` itself is not carried into the
   contract.

3. Run `health.py` over depgraph.py's final output:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/health.py DEPGRAPH_OUT.json

   It returns `{"health": [...], "unattached": [...]}`, sorted, so two runs
   over the same envelopes give identical `health[]`. It applies the
   failability test in `definitions.md` as far as the envelopes record it —
   not by `lifecycle` and not by category: a dependency contributes a
   condition iff it can fail independently while the process is up;
   category, `details.kind`, and lifecycle are only how the envelopes tell it
   that. One health entry per anchor — a `run` service, or a first-party
   component that anything links to — keyed by `service_id` (the field keeps
   its name for a `component:` id). A service's conditions come from its own
   `resilience` and from every node a `relates_to` edge (either
   direction) or its own `depends_on` edge links it to; a component has no
   `resilience`, so its conditions are only its links. Network paths reached
   from an anchor through other network paths only (an ingress fronting a
   listener) count as linked:
   - `kind`: `presence` when the subject must exist or resolve (a network
     path, a credential, a config key being set, a managed cloud service);
     `bound` when a declared metric limit applies (the service's timeout —
     always emitted — and retry when declared, a platform cpu/memory/disk/gpu
     limit); `upstream_health` when the subject is another service whose own
     health entry must hold.
   - `expectation`: the declared value with its `file:line` evidence — from
     the `resilience` timeout or retry, or a resource limit's
     `declared_value` — or `null` when none was found. **`null` means no
     declaration was found — it never means no bound is needed.** Whether an
     unbounded request-path dependency is a real gap is a judgment for a
     later layer, not this contract.
   - Never a condition: packages — a bundled library self-excludes, and
     layer 1 records no loading site for a dynamically loaded one —
     `build` dependencies, and platform runtime versions, OS, and arch.
   - `unattached` lists failable dependencies no anchor links to (remote
     config, unlinked network paths, credentials, resource limits). The
     contract keys health on an anchor id, so they have no entry.

4. Take the script's `health[]` as the base. **Never change or drop** a
   condition's `kind`, `subject_id`, `expectation`, or `evidence`, and never
   drop a condition or entry. You may only:
   - Fill `required_for[]` (the script leaves it empty) with the ids of
     components or functions that static evidence connects to the condition
     — a `component:<slug>` id from `components[]`, an entry point, a
     consuming file. Leave it empty
     when nothing static connects it. It records which callers need the
     condition met, never how important any of them are.
   - Add a `presence` condition for a dynamically loaded package — a
     reflectively resolved JDBC driver, an `importlib` plugin, a `dlopen`ed
     `.so` — citing the `file:line` of its loading site, **only when one
     appears in the evidence this skill can read**. Nothing in layer 1 today
     records one; when none appears, record an assumption naming the gap.
   - Record one assumption naming the `unattached` ids (or their count by
     category) and that they carry no health entry because no discovery
     skill linked them to a service or a component.

5. Carry every category's `status` through unchanged from the merged
   inventory. A `failed` category stays `failed` — never flattened to an
   empty list, because that would assert absence where a scan merely broke.

6. Emit the contract: `contract_version`, `target`, `ref` (from the
   envelopes; omit it for a working-tree run), the `inventory`, `components`
   and `graph` from step 2 unchanged, the `health` array from steps 3-4, and
   top-level `assumptions` holding only the cross-cutting ones: those you
   added while deriving conditions plus any an envelope carries at its top
   level. Per-category assumptions live at
   `inventory.categories.<cat>.assumptions` (most of them do); they stay
   there, unchanged and not copied up, and `report` reads both locations.
   Follow with a short prose summary: service and component
   count, condition count by `kind`, and any category whose status is
   `failed`.

## Rules

- Read-only. Nothing is resolved, probed, or run at runtime.
- `null` in `expectation` means no declaration was found — never that a bound
  is confirmed absent or unnecessary.
- An empty `health` list is a legitimate finding for a system with no
  service-shaped dependencies and nothing linked to its components. A `failed` category is a different finding
  from an empty one and must never be collapsed into it.
- No criticality, ranking, or blast radius judgment. `required_for[]` records
  which callers need a condition met, not how important any of them are — that
  judgment belongs to a later layer.
- Invoke the six discovery skills, and `profile:topology`, by name — never by
  reaching into another plugin's directory by path.
