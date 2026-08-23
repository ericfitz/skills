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
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:security [path]

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

1. Read `findings.secret_shaped_keys` — the scanner records key names and
   locations and deliberately never captures a value; the `file:line` of each
   record goes straight into `evidence`.
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
9. Set `lifecycle` to `run` on every dependency — these are needed while the service runs.
10. Emit the full envelope, then a short prose summary: credential count by
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
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
