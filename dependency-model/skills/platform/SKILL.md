---
name: platform
description: Enumerate the OS and cloud resources a system declares a need for — CPU, memory, disk, GPU, architecture, runtime versions, and managed cloud services. Every figure is a declared one; nothing is measured. Read-only. Use when sizing an environment or planning capacity review. Emits the dependency-model:discovery contract.
---

# platform

Enumerate the OS and cloud resources a system declares a need for. Emits the
`discovery` contract with the `platform` category populated.

**This skill never executes the project.** It reads the shared scan output and
the repository's own files; nothing is built, started, or queried at runtime.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/platform.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/platform.example.json`
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:platform [path]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`. Never invoke
another plugin's script by path.

If the shared scan has not already been run for this repository, run it once
and save the JSON to `/tmp/depscan.json` (see
`references/running-discovery.md`):

    uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <path> > /tmp/depscan.json

Use `python3` in place of `uv run --script` if `uv` is unavailable. If another of
the six discovery skills already produced this output for the same target, read
`/tmp/depscan.json` rather than scanning again.

## Procedure

1. Read `findings.resource_limits` — each record carries `kind`
   (`cpu`/`memory`/`disk`/`gpu`/`arch`/`runtime-version`), the declared figure
   as `raw`, `file:line`, and the `source` it came from
   (`dockerfile`/`compose`/`kubernetes`). Set `details.kind` and
   `details.source` directly from those two fields, and the record's `file:line`
   goes straight into `evidence`.
2. Set `id` to `platform:<slug>` and `name` to a short label for the figure
   (e.g. `api memory limit`).
3. Read `files.iac` for managed cloud services the system provisions, and
   `files.ci` for runner and image declarations. For each, set `details.kind`
   to `cloud-service`, and `details.source` to `iac` or `ci` as appropriate.
4. Read language manifests for declared runtime version floors; set
   `details.kind` to `runtime-version` and `details.source` to `manifest`.
5. Set `details.declared_value` to the figure **exactly as the repository
   writes it** — `512Mi`, not `512 MiB`, not `536870912`. For a `cloud-service`
   entry this figure is not a number: write the resource type together with
   whatever sizing or tier the repository declares for it — e.g.
   `aws_db_instance (db.t3.micro)`, `google_storage_bucket (STANDARD)` — never
   just the bare resource type with nothing after it, and never a class or tier
   you infer rather than one the repository states.
6. Set `details.component` to the container or service the figure applies to,
   `null` when it is repository-wide.
7. `resilience` on a platform entry: all four facts `null`, `on_path` from the
   stage the figure applies to.
8. If the scan's `coverage.skipped` is non-empty, record one assumption per
   skipped language, naming the language and what went unscanned.
9. Set `lifecycle` from `details.kind`: `cpu`, `memory`, `disk`, `gpu`, and
   `cloud-service` are `run`; `arch`, `os`, and `runtime-version` are `build`.
10. Emit the full envelope, then a short prose summary: figure count by `kind`,
    and which components carry no declared limit at all.

## Rules

- Read-only. Nothing is installed, built, started, or queried at runtime.
- Latency and bandwidth come only from declared timeouts and documented SLOs.
  There is nothing to measure from here, and a figure measured on a developer's
  machine would be a confidently wrong figure.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
