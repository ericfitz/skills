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
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py discovery <file.json>` (exit 0 = valid) before returning it.
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:platform [path] [--ref <branch>]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`. Never invoke
another plugin's script by path.

If you were not handed a run dir by another of the six discovery skills, run
the shared scan once (see `references/running-discovery.md`); pass `--ref`
only when asked to analyse a branch other than the working tree:

    uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <path> [--ref <branch>] --write

It prints the run dir, a per-repo, per-commit directory that holds
`depscan.json` and everything else this run writes, so two sessions on two
branches never overwrite each other. Use `python3` in place of
`uv run --script` if `uv` is unavailable. If another discovery skill already
produced a run dir for the same target and ref, read `<run_dir>/depscan.json`
rather than scanning again.
Put any scratch file (scripts, drafts, intermediates) in `<run_dir>/work/platform/`, never
in `<run_dir>` itself, which is for envelopes and shared inputs; other skills run
concurrently and would overwrite it.

Read evidence files from the scan's `scan_root`, not from `<path>`: with
`--ref` they differ, and `scan_root` is the snapshot of that branch. Copy the
scan's `target` and `ref` into the envelope unchanged.

Follow a symlink only if it is relative and stays inside the repo. The scan
lists every other link in `unsafe_links[]` and never reads through them; do
not open those paths either, and do not follow any other link that is
absolute or leaves the repo. In a repo under analysis such a link is treated
as hostile: it would pull whatever it points at, a key file or `/etc`, into
the evidence.

## Procedure

1. Read `findings.resource_limits` — each record carries `kind`
   (`cpu`/`memory`/`disk`/`gpu`/`arch`/`runtime-version`), the declared figure
   as `raw`, `file:line`, and the `source` it came from
   (`dockerfile`/`compose`/`kubernetes`). Set `details.kind` and
   `details.source` directly from those two fields, and the record's `file:line`
   goes straight into `evidence`. `bound` (`request`/`limit`) and `component`
   (container or service) are set where the file shows them; use them in `name`.
   A declaration carrying both cpu and memory (`cpu: 2, memory: 4Gi`) is two
   entries, one `cpu` and one `memory`, each with its own `declared_value` —
   there is no combined kind, and never put two figures in one `declared_value`.
2. Set `id` to `platform:<slug>` and `name` to a short label for the figure
   (e.g. `api memory limit`).
3. Read `files.iac` for managed cloud services the system provisions, and
   `files.ci` for runner and image declarations. For each, set `details.kind`
   to `cloud-service`, and `details.source` to `iac` or `ci` as appropriate.
4. Read language manifests for declared runtime version floors — `go.mod`'s
   `go` directive, `package.json` `engines`, `requires-python` in
   `pyproject.toml`, `rust-version` in `Cargo.toml`, `.tool-versions` — and set
   `details.kind` to `runtime-version` and `details.source` to `manifest`.
   A base image tagged `:latest` is also a `runtime-version`: record the tag as
   declared (`node:latest`) and add an assumption that it is unpinned, so the
   version it resolves to is unknown.
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
9. Set `lifecycle` to `run` on every platform entry, whatever `details.kind`
   is — a CPU, memory, disk, or GPU limit, a cloud service, an architecture,
   an OS, or a `runtime-version` floor all constrain the environment the
   system runs in, not merely where it was built. **One owner-decided
   exception (2026-09-28):** a fact about the CI/build environment itself —
   a `runs-on: ubuntu-latest` runner OS, a CI job's `container:` image, a CI
   `runtime-version` such as `setup-go`'s `go-version` — is `lifecycle: build`.
   Test: does the fact describe where the code is built and tested, not where
   it runs? A Dockerfile `FROM` of the shipped image, compose, k8s, IaC, and
   manifest floors describe the runtime and stay `run`.
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
