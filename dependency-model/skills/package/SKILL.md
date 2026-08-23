---
name: package
description: Inventory the libraries a project ships with and at what versions — every ecosystem syft catalogues, with declared/locked/installed resolution and the dependency edges between them. Read-only. Use when auditing dependencies, planning an upgrade, or building a dependency graph. Emits the dependency-model:discovery contract.
---

# package

Inventory what a project ships with. Emits the `discovery` contract with the
`package` category populated.

**This skill never executes the project.** `syft` reads files; nothing is built,
installed, resolved over the network, or run.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/package.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/package.example.json`
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:package [path]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`. Never invoke
another plugin's script by path.

`syft` is required. If it is not on PATH, emit the envelope with
`status: "failed"`, an assumption saying so, and stop — do not substitute a
hand-rolled lockfile parse.

If the shared scan has not already been run for this repository, run it once
and save the JSON to `/tmp/depscan.json` (see
`references/running-discovery.md`):

    uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <path> > /tmp/depscan.json

Use `python3` in place of `uv run --script` if `uv` is unavailable. If another of
the six discovery skills already produced this output for the same target, read
`/tmp/depscan.json` rather than scanning again.

## Procedure

1. Read `exclusions[]` from `/tmp/depscan.json` — this skill needs nothing
   else from the shared scan; `package`'s own evidence comes from syft.

2. Run syft with every entry from the scan's `exclusions[]` passed as
   `--exclude`. `exclusions[]` holds bare directory names (`node_modules`,
   `.venv`); syft's own exclusion syntax only matches a glob, so each bare
   name must be rewritten to a `**/<name>` glob, quoted, before it is passed:

       syft scan dir:<path> -o syft-json --quiet --exclude '**/node_modules' --exclude '**/.venv' ... > /tmp/syft.json

   Do not pass the bare name (`--exclude '.venv'`) or a root-anchored path
   (`--exclude './.venv'`): the bare form makes syft error out with no valid
   JSON output, and the root-anchored form only matches at the scan root, so
   a nested `sub/.venv` or `sub/node_modules` is not excluded at all — the
   installed-tree contamination this step exists to prevent.

   **The exclusions are not optional.** Unscoped, syft catalogues installed
   trees as though they were the project's dependency set: measured on this
   marketplace, an unscoped `syft scan dir:.` reported 270 packages against 2
   declared direct dependencies, 188 of them from a nested virtualenv — and
   only the `**/<name>` glob form actually removes that contamination; the
   root-anchored form leaves it in.

3. Run `pkglifecycle.py` against the same syft JSON to derive `lifecycle`:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/pkglifecycle.py <path> --syft-json /tmp/syft.json

   Use `python3` in place of `uv run --script` if `uv` is unavailable. Set
   each dependency's `lifecycle` from the returned map, keyed by syft
   artifact id.

   **syft cannot answer this itself** — it reports Python dev and runtime
   dependencies from one lockfile with identical metadata, and drops npm
   `devDependencies` from the catalogue entirely. Do not try to infer it from
   the artifact's `type` or `locations`.

   For every entry in the returned `unresolved` list, record one assumption
   naming the ecosystem and that its packages defaulted to `run`.

4. For each syft artifact, emit one dependency:
   - `id` is `package:<name>-<full-version-slug>`, e.g. `package:pgx-v5-5.5.0` —
     the full resolved version, not just the major, so the same package
     pinned at two versions in two lockfiles gets two distinct ids instead
     of colliding. Stable across runs.
   - `name`, `details.version`, `details.purl`, `details.ecosystem` come
     straight from the artifact.
   - `lifecycle` comes from the `pkglifecycle.py` map built in step 3 — never
     inferred from syft's own fields.
   - `evidence` is `locations[].path` — **a bare file path, no line number.**
     syft reports file-level locations only; do not invent a line.
   - `details.resolution` is your judgment from the location it was catalogued
     at: `declared` for a manifest, `locked` for a lockfile, `installed` for an
     installed tree. syft conflates the three; you must not.
   - `details.direct` is true when the package is named in a manifest the
     project owns, false when it is only reachable through another package,
     null when you cannot tell.
   - `details.pinned` is true when the version is exact, false for a range.
5. Read syft's `artifactRelationships` and fill `details.depends_on[]` from the
   `dependency-of` edges, mapping syft artifact ids to your `package:` ids.
   Ignore `contains` and `evident-by`.
6. Set `resilience` on every package entry: all four facts `null` and
   `on_path: ["build"]`. A library declaration carries no timeout or retry of
   its own; the code that calls it does, and that belongs to `service`.
7. Link `related_ids` to `service` entries where a package is unmistakably a
   client for a discovered service, and say so in an assumption if the link is
   an inference rather than a fact.
8. Emit the full envelope, then a short prose summary: package count by
   ecosystem, how many are direct, and how many are pinned.

## Rules

- Read-only. Nothing is installed, built, or resolved over the network.
- Evidence for this category is a **file path**, not `file:line`. Every other
  category carries `file:line`.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- If syft returns zero artifacts for a repository that plainly has manifests,
  that is a `failed` status with an assumption, not a `discovered` empty list.
- An empty list with `status: "discovered"` is a legitimate finding for a
  project with no third-party dependencies.
- Do not report vulnerabilities, licences as findings, or upgrade advice. This
  layer reports what is there.
