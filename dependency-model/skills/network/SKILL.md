---
name: network
description: Enumerate the names, hosts, and ports a system must resolve and connect to — inbound listeners, outbound endpoints, DNS, proxies, and ingress. Nothing is resolved or probed. Read-only. Use when mapping a system's network surface or planning egress policy. Emits the dependency-model:discovery contract.
---

# network

Enumerate the names, hosts, and ports a system must resolve and connect to.
Emits the `discovery` contract with the `network` category populated.

**This skill never executes the project.** It reads the shared scan output and
the repository's own files; nothing is resolved, connected to, or probed.

Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/network.schema.json`
Envelope: `${CLAUDE_PLUGIN_ROOT}/references/contracts/discovery.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/network.example.json`
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:network [path]

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

1. Read `findings.host_port_literals` and `findings.url_literals` — both carry
   `file:line`, which goes straight into `evidence`. **Filter out registry and
   lockfile URLs before doing anything else with `url_literals`.** A
   package-download URL (`files.pythonhosted.org`, `registry.npmjs.org`, a Go
   module proxy, and the like) inside `uv.lock`, `package-lock.json`, `go.sum`,
   or a similar lockfile is a build-time artifact source, not a network path the
   running system reaches — it belongs to `package`, not here. Measured on this
   repository, 2035 of 2339 `url_literals` entries were exactly this:
   package-download URLs from `uv.lock` files. Recording them here would drown
   the real network surface in noise.
2. Read `files.compose` and `files.k8s` for published ports, services, and
   ingress; `files.iac` for security groups, egress rules, and DNS records; and
   proxy configuration wherever it lives.
3. Set `id` to `network:<slug>` and `name` to the literal being recorded (e.g.
   `postgres:5432`).
4. Set `details.kind` and `details.direction` from what the declaration is: a
   published container port is `port` / `inbound`; a connection string host is
   `hostname` / `outbound`; an ingress host is `ingress` / `inbound`.
5. Set `details.value` to the literal as written, and
   `details.resolution_mechanism` to how the name is expected to resolve
   (compose service name, kubernetes DNS, public DNS, hosts file,
   environment-supplied), `null` when the repository does not say.
6. Link `related_ids` to the `service:` entry this path reaches and the
   `config:` key that supplies it.
7. `resilience` on a network entry: correlate `findings.resilience_calls` in the
   same file where the endpoint is used, exactly as `service` does.
8. If the scan's `coverage.skipped` is non-empty, record one assumption per
   skipped language, naming the language and what went unscanned.
9. Set `lifecycle` to `run` on every dependency — these are needed while the service runs.
10. Emit the full envelope, then a short prose summary: entry count by
    `direction`, and how many carry no declared resolution mechanism.

## Rules

- Read-only. Nothing is resolved and nothing is probed. A hostname that
  resolves on your workstation may not resolve where the system runs; a port
  that answers here proves nothing there. Record what is declared.
- `network` records the path used to reach a dependency; `service` records the
  thing itself. Both record the same `postgres:5432` and link through
  `related_ids`.
- Ignore registry and lockfile URLs — they name where a package is downloaded
  from, not a network path the running system reaches. See step 1.
- When a URL embeds what is plainly a credential in its path (a webhook
  token, a signed URL segment), record the URL with that segment replaced by
  `***`, and hand the fact that a credential is embedded in this URL to the
  `security` category.
- `null` in `resilience` means no declaration was found — never that the
  behaviour is confirmed absent.
- `lifecycle` has two values and never a third. It records which environment
  must contain the dependency, and it does **not** determine health.
- An empty `dependencies` list with `status: "discovered"` is a legitimate finding
  for a project this category does not apply to. A scan that could not complete
  is `failed`.
- No criticality, no blast radius, no monitoring-gap judgment, no test strategy.
  This layer reports facts.
