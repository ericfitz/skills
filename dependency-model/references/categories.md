# Category reference

What belongs in each of the six `dependency-model` categories, what does not, and
how to adjudicate a dependency that a naive reading would place in more than one.
Each skill reads only its own section before classifying evidence from
`depscan.py`'s output.

## The six categories

| Category | Question it answers | Belongs | Does not belong |
|---|---|---|---|
| `package` | What libraries does this ship with, and at what versions? | Anything `syft` resolves from a manifest or lockfile: direct and transitive dependencies, their version constraints, and their resolution state (declared / locked / installed). | A service the code calls over the network — that is `service`, even when the caller happens to also import an SDK package for it (the SDK entry is `package`; the endpoint it talks to is `service`). |
| `service` | What out-of-project services does it need — databases, queues, caches, APIs? | The thing depended on: a Postgres instance, a Redis cache, a third-party payment API, an internal service reached over HTTP or gRPC. Recorded from `topology.real_dependencies`/`external_third_parties` as seed evidence, compose/k8s/IaC service declarations, and client-library construction. | The hostname or port used to reach the service — that fact belongs to `network`, linked back through `related_ids`. A library that only runs in-process (no network call, no socket) is `package`, not `service`. |
| `config` | What configuration must be supplied for it to run? | Environment variables, `.env` entries, config-file keys, CLI flags, and the mechanism and default for each, as read by `env_refs` and the config-loader evidence in the scan index. | The value a config key resolves to when that value is itself a dependency fact — a `DATABASE_URL` config key is `config`; the hostname it names once parsed is `network`, linked. A secret's value or the key that only ever holds a value-shaped secret — see `security`. |
| `security` | What secrets and permissions does it require? | Names and locations of secrets, credentials, and permissions the code reads or requests: an env var read as an API key, a Kubernetes `Secret` reference, an IAM policy statement, an RBAC role binding. Never the secret's value. | The config key that reads a secret's *location* (which secret manager, which key name) — that is `config`, linked to the `security` entry for the secret itself. A plain (non-secret) config value stays entirely in `config`. |
| `platform` | What OS and cloud resources does it declare a need for? | CPU/memory/disk/GPU requests, target architecture, OS, language runtime version, and named cloud resources (a queue, a bucket, a managed database) as declared in Dockerfile, compose, k8s, IaC, or CI resource blocks. | A cloud resource's *reachability path* — a bucket's declared size is `platform`; the network egress needed to reach it is `network`. The resource's role as a dependency the application calls is `service`, linked. |
| `network` | What names, hosts, and ports must resolve and connect? | The path used to reach something: hostnames, IPs, ports, DNS records, egress rules, proxy and ingress configuration, and the `direction` (inbound/outbound) each implies. | The identity or purpose of what's on the other end of that path — a listening port that a Postgres container exposes is `network` (the path); the fact that the system depends on Postgres for storage is `service` (the thing). Both get recorded, linked. |

## The service/network adjudication rule

`service` and `network` overlap by design, not by accident: both will see the same
`postgres:5432`. The rule that separates them:

**`service` records the thing depended on; `network` records the path used to reach it.**

Both categories record the fact — this is not a case where one skill defers to the
other — and the two entries link through `related_ids`, so a `service:postgres-primary`
entry carries `"related_ids": ["network:postgres-5432"]` and vice versa. A
dependency legitimately appears in more than one category only when each category
records a genuinely different fact about it. If two entries would say the same
thing in two places, that is a duplicate, not a cross-category link — collapse it
to one entry and drop the second.

## Worked adjudications

These are the cases where the naive reading gets it wrong. Each resolves the same
way: ask which fact — identity of the thing, or the path to reach it, or the
config that names it, or the credential that guards it — a given piece of evidence
actually states, then place it there.

- **A hostname inside a connection string** (`postgres://user:pass@db.internal:5432/app`).
  Both `service` and `network` record it. `service` gets the database itself —
  what it is, what talks to it, what resilience is declared around the call.
  `network` gets the name that must resolve — `db.internal`, port `5432` — as a
  `hostname`/`port` entry. They link.

- **An API base URL** (`https://api.stripe.com/v1/charges`). `service` records it
  when the system calls it — the third-party API is the dependency. `network`
  records the egress it implies — the host `api.stripe.com` that must resolve and
  the outbound connection it requires. Both entries carry the same `file:line`
  evidence for the literal; they differ only in what fact each is asserting about
  it.

- **A container port a service listens on** (`ports: ["8080:8080"]` in a compose
  file for the app's own container). `network` only, `direction: inbound`. This
  is not a `service` entry — the application isn't depending on itself, it is
  declaring where it can be reached. Only ports the code depends on *reaching
  outward* on another component populate `service`.

- **A config key naming an endpoint** (`API_BASE_URL` read via `os.getenv`).
  `config` records the key: its name, where it's read, whether it has a default.
  `network` records the value once resolved — the hostname or URL the key names —
  as its own entry. The two link through `related_ids` so a reader can go from
  "this is configurable" to "this is what it resolves to" without re-parsing the
  key.

- **A Kubernetes `Secret` holding a database password** (a `Secret` named
  `db-credentials`, mounted as an env var `DB_PASSWORD` that the app reads).
  `security` records the secret reference — its name, that it's a Kubernetes
  `Secret`, where it's granted to the pod — never the value, which discovery never
  reads. `config` records the key that reads it (`DB_PASSWORD`, the env var name
  and the `file:line` of the read call) — again never the value. The two entries
  link; the fact that the value is secret lives only in `security`.

## Never a duplicate

The test for whether a dependency belongs in two categories is not "does this
evidence touch two categories" but "does each category state a fact the other
does not." A `postgres:5432` literal touching both `service` and `network` passes
that test — one states identity, the other states path. A config key that merely
repeats a hostname already fully captured under `network`, with nothing new to
say about the mechanism by which it's supplied, does not — record it once, in
whichever category actually owns the fact, and reference it by `related_ids` from
the other rather than re-stating it.
