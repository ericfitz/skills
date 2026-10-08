---
name: config
description: Enumerate the configuration a system must be supplied with to run — environment variables, config files, flags, and remote config — with what reads each key, whether it is required, and what default it declares. Read-only. Use when documenting deployment requirements or planning test environments. Emits the dependency-model:discovery contract.
---

# config

Enumerate the configuration a system must be supplied with to run. Emits the
`discovery` contract with the `config` category populated.

**This skill never executes the project.** It reads the shared scan output and
the repository's own files; nothing is built, started, or queried at runtime.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/config.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/config.example.json`
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py discovery <file.json>` (exit 0 = valid) before returning it.
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:config [path] [--ref <branch>]

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
Put any scratch file (scripts, drafts, intermediates) in `<run_dir>/work/config/`, never
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

1. Read `findings.env_refs` — each is a `{name, file, line}` triple; that is your
   primary evidence and the `file:line` goes straight into `evidence`. Skip `path_class: test` records
   (see `references/running-discovery.md`). Go struct-tag keys (`env:"X"`) carry `mechanism`.
2. Read every file under `files.env` for declared keys and their presence, and
   every config loader in the repository for keys the literal scan missed.
   The scan sees only literal names, so prefer a committed generated config
   reference (e.g. `config-reference.md`) as the main key source when one exists,
   and cite it as evidence. Also cover keys the scan cannot see, or record each
   gap as an assumption: DB-backed settings (a `system_settings` table or
   `SettingDef`-style registry: `mechanism` `remote`), dotted YAML-only keys
   (`file`), and dynamic-prefix patterns such as `TMI_SECRET_<KEY>` (one entry
   for the pattern, or an assumption if the concrete keys are unknowable).
   Drop `_test.go` and test-harness keys (`TEST_DB_*`) even where `path_class`
   did not tag them.
3. Set `id` to `config:<key-slug>` and `name` to the key's literal name (e.g.
   `DATABASE_URL`), and set `details.key` to that same literal name — the
   schema requires `details.key` and it is not implied by anything else you
   set.
4. Set `details.mechanism` from where the key is read: `env`, `file`, `flag`,
   `remote`, `constant`, or `unknown`.
5. Set `details.required` from whether the code fails without it — a lookup with
   no default is required, a `.get(name, default)` is not. Set it `null` when the
   repository does not say. `required` is boolean or null, so a key needed by
   only some components (e.g. workers) is `true` with those files in
   `consumed_by[]` and an assumption naming who needs it.
6. Record `details.default` only when the repository declares one literally.
7. Fill `details.consumed_by[]` from the files the key is read in.
8. Set `details.validated` true only when the repository declares a parse or
   validation step for the key.
9. Link `related_ids` to the `service:` or `network:` entry the key points at. Build each id by the rule in `categories.md` ("Ids").
10. `resilience` on a config entry: all four facts `null`, `on_path` from where the
    key is read.
11. If the scan's `coverage.skipped` is non-empty, record one assumption per
    skipped language, naming the language and what went unscanned.
12. Set `lifecycle` to `run` on every dependency — these are needed while the service runs.
13. Emit the full envelope, then a short prose summary: key count, how many are
    required, and how many carry no declared default.

## Rules

- Read-only. Nothing is installed, built, started, or queried at runtime.
- Record a key's name, its location, and its declared default — never a value
  read from a `.env` file that is not a committed placeholder. If a `.env` file
  carries a real-looking value, record the key and add an assumption; do not
  copy the value.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
