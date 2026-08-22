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
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:config [path]

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

1. Read `findings.env_refs` — each is a `{name, file, line}` triple; that is your
   primary evidence and the `file:line` goes straight into `evidence`.
2. Read every file under `files.env` for declared keys and their presence, and
   every config loader in the repository for keys the literal scan missed.
3. Set `id` to `config:<key-slug>` and `name` to the key's literal name (e.g.
   `DATABASE_URL`), and set `details.key` to that same literal name — the
   schema requires `details.key` and it is not implied by anything else you
   set.
4. Set `details.mechanism` from where the key is read: `env`, `file`, `flag`,
   `remote`, `constant`, or `unknown`.
5. Set `details.required` from whether the code fails without it — a lookup with
   no default is required, a `.get(name, default)` is not. Set it `null` when the
   repository does not say.
6. Record `details.default` only when the repository declares one literally.
7. Fill `details.consumed_by[]` from the files the key is read in.
8. Set `details.validated` true only when the repository declares a parse or
   validation step for the key.
9. Link `related_ids` to the `service:` or `network:` entry the key points at.
10. `resilience` on a config entry: all four facts `null`, `on_path` from where the
    key is read.
11. If the scan's `coverage.skipped` is non-empty, record one assumption per
    skipped language, naming the language and what went unscanned.
12. Emit the full envelope, then a short prose summary: key count, how many are
    required, and how many carry no declared default.

## Rules

- Read-only. Nothing is installed, built, started, or queried at runtime.
- Record a key's name, its location, and its declared default — never a value
  read from a `.env` file that is not a committed placeholder. If a `.env` file
  carries a real-looking value, record the key and add an assumption; do not
  copy the value.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
