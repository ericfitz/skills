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
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py discovery <file.json>` (exit 0 = valid) before returning it.
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:package [path] [--ref <branch>]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`. Never invoke
another plugin's script by path.

`syft` is required. If it is not on PATH, emit the envelope with
`status: "failed"`, an assumption saying so, and stop — do not substitute a
hand-rolled lockfile parse.

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
Put any scratch file (scripts, drafts, intermediates) in `<run_dir>/work/package/`, never
in `<run_dir>` itself, which is for envelopes and shared inputs; other skills run
concurrently and would overwrite it.

Read evidence files from the scan's `scan_root`, not from `<path>`: with
`--ref` they differ, and `scan_root` is the snapshot of that branch. Copy the
scan's `target` and `ref` into the envelope unchanged. The envelope
carries `ref` (the scan's `ref` object, or null for the working tree) and
`scan: null`, since this category reads syft, not the shared scan.

Follow a symlink only if it is relative and stays inside the repo. The scan
lists every other link in `unsafe_links[]` and never reads through them; do
not open those paths either, and do not follow any other link that is
absolute or leaves the repo. In a repo under analysis such a link is treated
as hostile: it would pull whatever it points at, a key file or `/etc`, into
the evidence.

## Procedure

1. Read `scan_root` and `syft_excludes[]` from `<run_dir>/depscan.json` —
   this skill needs nothing else from the shared scan; `package`'s own
   evidence comes from syft.

2. Run syft on `scan_root` with every entry of `syft_excludes[]` passed as
   its own quoted `--exclude`, exactly as written:

       syft scan dir:<scan_root> -o syft-json --quiet --exclude '**/node_modules' --exclude './.claude/worktrees' ... > <run_dir>/syft.json

   `depscan.py` has already put each entry in the only form syft honours:
   `**/<name>` for the fixed exclusion names, so a nested `sub/.venv` is
   caught too, and `./<path>` for every git-ignored path in the target. Do
   not rewrite, drop, or de-duplicate them.

   **The exclusions are not optional.** syft neither knows which trees are
   installed nor honours `.gitignore`, so unscoped it catalogues them as
   though they were the project's dependency set. Measured on this
   marketplace, an unscoped `syft scan dir:.` reported 270 packages against 2
   declared direct dependencies, 188 of them from a nested virtualenv. On a
   larger Go and TypeScript repo, the fixed names alone left 3,261 packages,
   and the `./<path>` entries cut that to 792: the other three quarters came
   from git-ignored nested worktrees and compiled binaries, with no tracked
   file lost.

3. Run `pkglifecycle.py` on the same `scan_root` and syft JSON to derive
   `lifecycle`:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/pkglifecycle.py <scan_root> --syft-json <run_dir>/syft.json

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
     null when you cannot tell. syft has no direct flag, so read the
     manifests in `scan_root` (never run a package manager), one per
     ecosystem, and do it for every manifest the repo has, including nested
     modules and workspaces: Go `go.mod` `require` lines without
     `// indirect`; npm/pnpm/yarn every `package.json` (workspace packages
     included) `dependencies` and `devDependencies`; Python
     `pyproject.toml` / `requirements*.txt` names (normalise `-`/`_`/case);
     Cargo `[dependencies]`; Maven/Gradle declared coordinates. A package
     found in no manifest of its ecosystem is `false`; an ecosystem you did
     not parse is `null`.
   - `details.pinned` is true when the version is exact, false for a range.
   - `github-action` artifacts: `ecosystem` `github-actions`, `resolution`
     `declared` (a `uses:` ref in a workflow file), `pinned` true only when
     the ref is a 40-hex commit SHA (a tag or branch is `false`), `direct`
     true. Their `locations` may be plain strings rather than objects; take
     the string as the path. Their purl may be empty.
   - `terraform` artifacts (providers and modules): `ecosystem` `terraform`,
     `resolution` `locked` when the version comes from
     `.terraform.lock.hcl`, else `declared`; `pinned` true for an exact
     version and false for a constraint (`~>`, `>=`); `direct` true for a
     provider or module named in a `.tf` file. The purl may be empty; leave
     it empty rather than inventing one.
   - **Merge duplicates.** syft emits one artifact per manifest, so a
     repo with several `go.mod` files yields the same package many times
     (tmi: 779 artifacts, 538 distinct ids). The id is the merge key: emit one
     dependency per id, with `evidence` the union of every occurrence's
     paths, `lifecycle` `run` if any occurrence is `run`, `direct` true if
     any occurrence is true, `depends_on` the union, and `resolution` the
     strongest seen (`installed` over `locked` over `declared`). Merge only
     identical ids: the same package at two versions stays two entries.
5. Read syft's `artifactRelationships` and fill `details.depends_on[]` from the
   `dependency-of` edges, mapping syft artifact ids to your `package:` ids.
   Ignore `contains` and `evident-by`.
6. Set `resilience` on every package entry: all four facts `null` and
   `on_path: ["build"]`. A library declaration carries no timeout or retry of
   its own; the code that calls it does, and that belongs to `service`.
7. Link `related_ids` to `service` entries where a package is unmistakably a
   client for a discovered service, and say so in an assumption if the link is
   an inference rather than a fact. Build each id by the rule in `categories.md` ("Ids").
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
