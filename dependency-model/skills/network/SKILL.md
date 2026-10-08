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
Validate the output with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/validate.py discovery <file.json>` (exit 0 = valid) before returning it.
Categories: `${CLAUDE_PLUGIN_ROOT}/references/categories.md`
Sequence: `${CLAUDE_PLUGIN_ROOT}/references/running-discovery.md`

## Usage

    /dependency-model:network [path] [--ref <branch>]

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
Put any scratch file (scripts, drafts, intermediates) in `<run_dir>/work/network/`, never
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

1. Read `findings.host_port_literals` and `findings.url_literals` (the URL is
   in `value`) — both carry `file:line`, which goes straight into `evidence`,
   and `path_class`: keep `first-party`, see `references/running-discovery.md`. **Filter out registry and
   lockfile URLs before doing anything else with `url_literals`.** A
   package-download URL (`files.pythonhosted.org`, `registry.npmjs.org`, a Go
   module proxy, and the like) inside `uv.lock`, `package-lock.json`, `go.sum`,
   or a similar lockfile is a build-time artifact source, not a network path the
   running system reaches — it belongs to `package`, not here. Measured on this
   repository, 2035 of 2339 `url_literals` entries were exactly this:
   package-download URLs from `uv.lock` files. Recording them here would drown
   the real network surface in noise.
2. Read `findings.k8s_network` (Service/Ingress/NetworkPolicy objects and
   containerPorts: `kind`, `name`, `ports`, `file:line`), and `files.compose` and `files.k8s` for published ports, services, and
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
   `config:` key that supplies it. Build each id by the rule in `categories.md` ("Ids").
7. `resilience` on a network entry: correlate `findings.resilience_calls` in the
   same file where the endpoint is used, exactly as `service` does. Each of
   `timeout`, `retry`, `fallback`, `health_check` is `null` or an object with
   `evidence[]` and `value` (`timeout`) or `description` (the others), e.g.
   `"timeout": {"value": "5s", "evidence": ["client.go:42"]}`; see
   `resilience-signatures.md` for the `kind` mapping.
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
- Dev-only endpoints (OAuth stubs, Tilt or local registries, ports that only a
  Makefile or dev compose file opens) are not recorded: `lifecycle` here is
  `run`, and these never ship in the runtime artifact. Note their exclusion in
  one assumption, naming the files.
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
