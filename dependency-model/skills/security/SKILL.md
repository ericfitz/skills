---
name: security
description: Enumerate the secrets and permissions a system requires — what each credential is named, where it is read, and which policies grant what. Records names and locations only, never values. Read-only. Use when auditing a system's credential surface or planning least-privilege review. Emits the dependency-model:discovery contract.
---

# security

Enumerate the secrets and permissions a system requires. Emits the `discovery`
contract with the `security` category populated.

**This skill never executes the project.** It reads the shared scan output and
the repository's own files; nothing is built, started, or queried at runtime.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/security.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/security.example.json`
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py discovery <file.json>` (exit 0 = valid) before returning it.
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:security [path] [--ref <branch>]

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
Put any scratch file (scripts, drafts, intermediates) in `<run_dir>/work/security/`, never
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

1. Read `findings.secret_refs` (Kubernetes `secretKeyRef`: `env`, `secret`, `key`,
   `file:line`; names only) alongside `findings.secret_shaped_keys` — the scanner records key names and
   locations and deliberately never captures a value; the `file:line` of each
   record goes straight into `evidence`. Filter on `path_class` (see
   `references/running-discovery.md`): `test`, `docs`, `vendored` and
   `generated` hits are rarely real credentials.
2. Read IAM, RBAC, and policy files under `files.iac` and `files.k8s` for
   grants, roles, and scopes.
3. Read auth middleware and client construction for the credentials they
   consume.
4. Set `id` to `security:<slug>` and `name` to the credential's literal name
   (the env var, secret, or role name — e.g. `POSTGRES_PASSWORD`).
5. Set `details.kind` from the enumerated set, `details.provider` from where the
   credential lives (`kubernetes`, `vault`, `aws-secrets-manager`, `env`, `file`,
   `unknown`), `details.scope` from what it authorises, and
   `details.granted_to[]` from the principals a policy names.
6. Set `details.rotation_declared` true only when the repository declares a
   rotation mechanism.
7. `resilience` on a security entry: all four facts `null`, `on_path` from where
   the credential is read.
8. If the scan's `coverage.skipped` is non-empty, record one assumption per
   skipped language, naming the language and what went unscanned.
9. Set `lifecycle` per `references/definitions.md`: `run` for a credential the
   deployed service reads (Kubernetes `secretKeyRef`, runtime env, mounted
   secret); `build` for one needed only to build or test. A secret referenced
   only from CI workflows (`.github/workflows/`, e.g. `secrets.X`) is `build`:
   name it, set `provider` `unknown` unless the workflow names one, and cite the
   workflow `file:line`. If a workflow injects it into a deployed artifact or
   deploys with it, record that in `scope`; if the same name is also read at
   runtime, that is a separate `run` entry (see next step).
   Test-only credentials (`path_class` `test`) are `build`.
10. Environments and repeats. The schema has no environment field. When a
    credential exists only in one environment (dev compose, staging overlay,
    prod manifest), say so in `scope` and record the evidence path. When one env
    var or secret name is read in several places or environments, emit one entry
    per distinct role (different `lifecycle`, provider, or environment) with
    distinct ids (`security:<slug>-<context>`, e.g. `security:postgres-password-ci`);
    do not merge them, and do not split one credential across identical entries.
11. Optional credentials. There is no `optional` field. Treat a credential as
    optional only on declared evidence (`optional: true` on a `secretKeyRef`,
    a guarded or defaulted read); say so in `scope` and add an assumption when
    the reading code was not checked. Otherwise treat it as required and record
    nothing about it.
12. Emit the full envelope, then a short prose summary: credential count by
    `kind`, and how many declare a rotation mechanism.

## The credential rule

This skill records that a secret exists, what it is called, and where it is
read. It does not record what it is.

- **Never read a secret's value.** Not from a `.env` file, not from a
  Kubernetes manifest's `data:` or `stringData:` block, not from a committed
  config file, not from a fixture.
- **Never open a file under `~/.keys/`.** Not to check its format, not to
  confirm it exists.
- The `security` sub-schema declares no field a value could be written into,
  and a test enforces that. If you find yourself wanting one, the answer is an
  assumption, not a new field.
- A value that appears in the repository by accident is a finding about the
  repository — record the key and its location, add an assumption saying a
  literal-looking value is committed there, and do not reproduce it.

## Rules

- Read-only. Nothing is installed, built, started, or queried at runtime.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third: `build` (build/test only, including CI-only secrets) or `run`. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
