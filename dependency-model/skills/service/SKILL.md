---
name: service
description: Identify the out-of-project services a system needs — databases, caches, queues, object stores, search engines, and APIs — with the timeout, retry, fallback, and health-check declarations that bear on how each one fails. Read-only. Use when mapping a system's runtime dependencies or planning failure testing. Emits the dependency-model:discovery contract.
---

# service

Identify the out-of-project services a system depends on — databases, caches,
queues, object stores, search engines, and APIs — along with the resilience
declarations that bear on how each one fails. Emits the `discovery` contract
with the `service` category populated.

**This skill never executes anything.** Nothing resolves a name, opens a
socket, or boots a container; every entry comes from reading files.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/service.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/service.example.json`
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Resilience signatures: `${CLAUDE_PLUGIN_ROOT}/references/resilience-signatures.md`

## Usage

    /dependency-model:service [path]

Standalone invocation: if you were not handed a `profile:topology` contract,
invoke `profile:topology` first and use its output as `seeded_by`.

If the shared scan has not already been run for this repository, run it once
and save the JSON to `/tmp/depscan.json` (see
`references/running-discovery.md`):

    uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <path> > /tmp/depscan.json

Use `python3` in place of `uv run --script` if `uv` is unavailable. If another of
the six discovery skills already produced this output for the same target, read
`/tmp/depscan.json` rather than scanning again.

## Procedure

1. Read the index from `/tmp/depscan.json`.

2. Seed from the `topology` contract's `real_dependencies` and
   `external_third_parties`. These are coarse by design — refine them, do not
   simply copy them.
3. Read every file under the index's `files.compose`, `files.k8s`, and
   `files.iac` for service declarations: images, chart dependencies, managed-
   service resources.
4. Read `findings.url_literals` and `findings.host_port_literals` for services
   the config files do not declare, and the manifests from the `package`
   category for client libraries that imply one. **Filter out registry and
   lockfile URLs before reading `url_literals`.** A package-download URL
   (`files.pythonhosted.org`, `registry.npmjs.org`, a Go module proxy, and
   the like) inside `uv.lock`, `package-lock.json`, `go.sum`, or a similar
   lockfile is a build-time artifact source, not a service the running
   system depends on — it belongs to `package`, not here.
5. For each service identified, set `id` to `service:<slug>` — a stable slug
   built from the service's name and role (e.g. `service:postgres-primary`,
   `service:stripe-api`) — and `name` to the service's plain name (e.g.
   `postgres`, `stripe`). Set `evidence` to the `file:line` locations that
   show this service exists: the compose/k8s/iac declaration line, the
   url/host-port literal's line, or the client-construction line — the
   schema requires `id`, `name`, and `evidence`, and none of them is implied
   by anything else you set.
6. Assign `details.kind` from the enumerated set, and `details.managed_by`
   from how it is brought up.
7. Fill `details.config_keys[]` from `findings.env_refs` whose name plainly
   points at this service, and link each to its `config:` id in
   `related_ids`.
8. Fill `resilience` per `resilience-signatures.md`: correlate
   `findings.resilience_calls` in the files that construct this service's
   client, record the call's `file:line` as evidence, and set every fact you
   cannot find to `null`. The scanner's `kind` does not name-match the
   contract's facts one-to-one: a `deadline` match fills `timeout`, and a
   `circuit-breaker` match fills `fallback` (with `description` naming the
   library) — see the mapping table in `resilience-signatures.md`.
9. Set `resilience.on_path` from where the client is constructed — startup
   wiring, a request handler, a background worker, or a build step. Leave it
   empty when the repository does not say.
10. Link `related_ids` to the `network:` entry for the host and port this
    service is reached on. Both categories record it; `categories.md` has
    the rule.
11. If the index's `coverage.skipped` is non-empty, record one assumption per
    skipped language naming it and what went unscanned.
12. Set `lifecycle` to `run` on every dependency — these are needed while the service runs.
13. Emit the full envelope, then a short prose summary.

## Rules

- Read-only; an unconfirmable claim becomes an assumption, never a probe.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a pure library or CLI. A scan that could not complete is `failed`.
- `service` records the thing depended on; `network` records the path used to
  reach it. Both categories record the same `postgres:5432` and link through
  `related_ids`.
- When a URL embeds what is plainly a credential in its path (a webhook
  token, a signed URL segment), record the URL with that segment replaced by
  `***`, and hand the fact that a credential is embedded in this URL to the
  `security` category.
- No criticality, no blast radius, no monitoring-gap judgment, no test
  strategy. This layer reports facts.
- Never invoke `profile`'s scripts by path; invoke `profile:topology` by name.
