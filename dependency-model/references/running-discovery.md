# Running discovery

The sequence for producing a complete `dependency-model` picture of a repository:
one seed contract, one scan, six independent skills reading the same scan
output, then `synthesize` and `report` to merge that output into a graph and
health view and render it. This page covers the six-skill layer; see
`skills/synthesize/SKILL.md` and `skills/report/SKILL.md` for the two steps
after it.

## The sequence

1. **Invoke `profile:topology`** to get the seed contract. It supplies
   `real_dependencies` and `external_third_parties` as starting evidence for the
   `service` category, and establishes the repo's deployment shape that several
   categories' evidence should be read against.
2. **Run `depscan.py` once** against the target repository. Every one of the six
   skills reads this same output; the scan is not re-run per skill.
3. **Run the six skills — in any order, or concurrently** — each reading the same
   scan output and emitting its own envelope with exactly one category populated.
   No skill depends on another skill's output; only on the shared scan and the
   seed contract from step 1.

## Commands

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> [--ref <branch>] --write
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> [--ref <branch>] --write   # fallback, no deps
```

Use the `uv run --script` form when `uv` is available — it resolves the script's
declared dependencies automatically. The `python3` fallback runs the same script
with only the standard library, for environments where `uv` isn't installed;
`depscan.py` is written to support both invocation paths without a code change
between them.

`--write` saves the scan as `depscan.json` in the **run dir** and prints that
dir. Every file this run produces (the scan, `syft.json`, and each skill's
envelope as `<category>.json`) goes in the same run dir. It sits under the
system temp dir and is named from a hash of the repo path and the commit (or
"working tree"), so two sessions analysing two branches of one repo on the
same machine never overwrite each other's output.

Skills run concurrently in that one run dir, so each writes its scratch files
(helper scripts, drafts, intermediates) to its own `<run_dir>/work/<skill>/`
and nothing else. `<run_dir>` itself holds only the envelopes and shared
inputs: `depscan.json`, `syft.json` (written by `package`, read-only for
everyone else), `snapshot/`.

## Filtering findings by path class

Every record in `findings.*` carries `path_class`: `first-party`, `test`,
`docs`, `vendored`, or `generated`. `file_classes` maps each path in `files.*`
(so `files.k8s`) to the same classes. The scanner tags and never drops: each
skill decides what to keep. Evidence for a running system normally comes from
`first-party` records; `test`, `docs`, `vendored` and `generated` ones are
context at most, and cite them only when nothing first-party backs the claim.
A URL literal's URL is in `value` (with `scheme`, `host`), not `url`.

## What depscan does not extract

Look by hand (`rg` the snapshot) for these; do not assume absence:

- Config keys built from a prefix at runtime (`os.Getenv(envPrefix + "ENABLED")`)
  and `SettingDef.EnvVar`-style tables. Only literal `os.Getenv`/`environ`/
  `process.env` names and Go `env:`/`envconfig:` struct tags are in `env_refs`.
- Pod specs embedded in Terraform (`kubernetes_*` resources) and Terraform
  security-group rules; `files.iac` lists the files.
- Kubernetes RBAC and cloud IAM, and `envFrom` secret refs (only
  `secretKeyRef` is in `secret_refs`).
- Tracked directories named like an excluded one (`vendor`, `build`, `dist`,
  `target`): `syft_excludes` skips them by name, so before trusting a
  package inventory, `git ls-files <dir>` any such directory that exists and
  record what it holds as an assumption.

## Symlinks

Only relative symlinks that stay inside the repo are followed. An absolute
link, or a relative one that resolves outside the repo, is treated as
hostile: `depscan.py` lists it in `unsafe_links[]` and never reads through
it, a `--ref` snapshot refuses to extract it, and every skill is told not to
open it. syft already follows neither kind (verified with syft 1.52.0).

## Choosing what to scan: working tree or `--ref`

Without `--ref`, the scan covers the working tree, uncommitted edits included.
Git-ignored paths are listed in the scan's `ignored[]` and passed on to syft as
excludes, so nested worktrees of other branches, build output, and provider
caches do not reach the package inventory.

With `--ref <branch>`, `depscan.py` extracts a `git archive` snapshot of that
commit into `<run_dir>/snapshot` and scans that instead: only the files
committed on that branch, whatever is checked out. It writes nothing to the
repo. Every skill then reads evidence from the scan's `scan_root` (the
snapshot) rather than the repo path; evidence paths stay repo-relative, so
`file:line` citations hold against that branch. The scan's `ref` (`name` and
resolved `commit`) is copied into every envelope, and `depgraph.py` refuses to
merge envelopes whose `target` or `ref` disagree: a merge across two branches
would describe a system that exists on neither.

## The six skills

Each names its own category and consumes the scan output at `<run_dir>/depscan.json` plus its own contract and reference documents. Run
any or all of the following, in any order:

- `/dependency-model:package`
- `/dependency-model:service`
- `/dependency-model:config`
- `/dependency-model:security`
- `/dependency-model:platform`
- `/dependency-model:network`

## Why there is no orchestrator here

This layer deliberately ships no seventh skill that runs the other six and
merges their output. That is by design (D8 in the design spec), not an
oversight: layer 2's report skill already has to gather all six contracts before
it can render anything, which makes it the orchestrator whether or not layer 1
also builds one. Building an orchestrator in this layer would mean building the
same gathering logic twice — once here, once again in layer 2 — for no benefit,
since nothing in layer 1 itself needs the six results merged.

A caller who wants all six today invokes them directly, in the sequence above;
a caller who wants a rendered report waits for layer 2's report skill, which
performs that invocation and the merge described next as part of producing its
output.

## How the six envelopes merge

Each skill emits a full envelope — `contract_version`, `target`, `seeded_by`,
and a `categories` object — with exactly one key populated under `categories`
(per D6 in the design spec). Merging six such envelopes into one complete
picture is a **key union under `categories`**: take the single populated key
from each envelope and union them into one `categories` object. No conflict
resolution is needed because no two skills ever populate the same key, and no
transform is needed because every skill's single-category output is already
valid against the shared envelope schema on its own. `scripts/depgraph.py`
implements exactly this union, plus the typed-edge graph and cycle detection
built on top of it; `synthesize` invokes it rather than re-deriving the merge
in prose.

## `exclusions[]` is the single source of truth

`depscan.py`'s output carries an `exclusions[]` list — a fixed set, not a
configurable one: `EXCLUDE_DIRS` in `walk.py` is the sole source, and
`depscan.py` takes no `--exclude` flag or other config input to extend it.
See `walk.py` for the current membership; this document does not restate it,
so it cannot go stale against the code. This fixed list is the single source
of truth for both tools that need to skip the same noise:

- The `package` skill reads `exclusions[]` and rewrites each bare directory
  name to a `**/<name>` glob before passing it to `syft --exclude` — see
  `skills/package/SKILL.md` step 2 for the exact form and why the bare and
  root-anchored forms don't work.
- The five file-scanning skills inherit the same list by reading it from the
  scan index — they don't re-derive their own exclusion rules.

Without it, `syft scan dir:` reports a nested virtualenv or `node_modules` tree
as part of the project's own dependency set — verified against this repository,
where an unscoped `syft scan dir:.` reported 270 packages against the 2 direct
dependencies plus one optional extra that `pyproject.toml` actually declares,
with 188 coming from a nested `writing/skills/boring/.venv/` and 7 from the
repo's own `.venv/`. Reading
`exclusions[]` from the shared index, rather than each tool maintaining its own
list, is what keeps that from happening independently in six places.
