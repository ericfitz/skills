# Resilience signatures reference

What `depscan.py` matches in source to populate `findings.resilience_calls`, and
how each of the six skills correlates those matches to the dependencies they
belong to. This document is the spec for `depscanlib/source.py`'s
`RESILIENCE_PATTERNS` table — keep the two in step; a pattern added to one without
the other is a coverage gap in one direction or a stale claim in the other.

Per D9 in the design spec, source-literal matching covers three ecosystems: Go,
TypeScript/JavaScript, and Python. Every other ecosystem still gets full
file-based coverage (compose, k8s, IaC, CI, `.env`) — only this source-literal
layer is bounded to these three.

## Go

| Pattern | `kind` |
|---|---|
| `context.WithTimeout` | `timeout` |
| `context.WithDeadline` | `deadline` |
| A `Timeout:` struct field (e.g. `http.Client{Timeout: ...}`) | `timeout` |
| `backoff.*` (e.g. `backoff.Retry`, `cenkalti/backoff`) | `retry` |
| `retry.*` (e.g. `avast/retry-go`) | `retry` |
| `gobreaker` (`sony/gobreaker`) | `circuit-breaker` |

## Python

| Pattern | `kind` |
|---|---|
| `timeout=` keyword argument (e.g. `requests.get(url, timeout=5)`, `httpx.Client(timeout=...)`) | `timeout` |
| `@retry` decorator | `retry` |
| `tenacity` (import or `Retrying(...)` construction) | `retry` |
| `pybreaker` (`CircuitBreaker(...)`) | `circuit-breaker` |

## TypeScript / JavaScript

| Pattern | `kind` |
|---|---|
| `AbortSignal.timeout(...)` | `timeout` |
| A `timeout:` option (e.g. in an axios or fetch-wrapper config object) | `timeout` |
| `p-retry` (import or `pRetry(...)` call) | `retry` |
| `opossum` (circuit breaker construction) | `circuit-breaker` |

## Multi-line constructs are a silent miss

`source.py`'s pattern matching is line-based: every pattern above is matched
against one line of source at a time, never across a line boundary. A
construct split across lines — `const {\n  A,\n  B,\n} = process.env` for an
env-var destructure, or a multi-line `context.WithTimeout(\n  ctx,\n  5*time.Second,\n)`
call — matches nothing on any single line and so yields no
`resilience_calls` or `env_refs` entry at all, with no `coverage.skipped`
signal to say so. A downstream skill cannot distinguish this from the
construct genuinely being absent; treat it as one more reason a `null` fact
is a candidate gap, never a confirmed one.

## Mapping a scanner `kind` to a contract fact

`RESILIENCE_PATTERNS` emits four `kind`s: `timeout`, `deadline`, `retry`,
`circuit-breaker`. `dependency-core.schema.json`'s `resilience` object has
four facts: `timeout`, `retry`, `fallback`, `health_check`. `deadline` and
`circuit-breaker` have no fact of the same name, so a skill correlating a
match must map explicitly rather than guess:

| scanner `kind` | contract fact |
|---|---|
| `timeout` | `timeout` |
| `deadline` | `timeout` |
| `retry` | `retry` |
| `circuit-breaker` | `fallback`, with `description` naming the library (e.g. `"circuit breaker: sony/gobreaker"`) |

Nothing populates `health_check` from `resilience_calls` — that fact is
filled from file-based evidence (a compose/k8s health-check declaration), not
a source-literal pattern.

## Correlating a call to a dependency

`resilience_calls` is emitted once, cross-cutting, by the shared scan — it is not
pre-assigned to any dependency. Each skill does its own correlation against its
own dependencies:

A `resilience_calls` record belongs to a dependency when it sits in a file that
also carries that dependency's client construction (the line that builds the
client, connection, or channel for it) or its config key (the line that reads the
env var, config value, or flag naming it). When both are true, record the
`file:line` of the resilience call itself as the resilience evidence — not the
client-construction line, and not the config-read line; those are separate
evidence entries the skill already has reason to record elsewhere.

A call with no dependency it plausibly belongs to (no client construction, no
config key, in the same file) is not correlated to anything — it is not evidence
for any single dependency's `resilience` block, though it is still present in the
raw scan output for a human or a later layer to inspect.

## `null` means unconfirmed, not absent

**`null` means no declaration was found in the repository — never that the
behaviour is confirmed absent.** This is the single most load-bearing sentence in
this document, because it determines what a downstream layer is allowed to
conclude from an empty `resilience` field.

A `null` under `timeout`, `retry`, `fallback`, or `health_check` states only that
this discovery pass, scanning only these three ecosystems' source literals plus
the file-based evidence common to all languages, found no matching declaration.
It does not state that no timeout exists — a timeout set in a language outside
D9's scope, or expressed as a pattern this table doesn't yet recognize, or
configured entirely outside source code (an infrastructure-level proxy timeout,
for instance) would also read as `null` here.

A downstream layer reads a `null` on a request-path dependency as a *candidate*
gap worth investigating — never a confirmed one. Layer 1 must not decide that for
it; deciding "no timeout is declared" versus "no timeout was found" is exactly the
judgment call D1 in the design spec reserves for layer 3.

## The D9 boundary

A repository whose primary language falls outside Go, TypeScript/JavaScript, and
Python still gets full file-based coverage — compose, k8s, IaC, CI, `.env`, and
the `package` category's syft-driven coverage of roughly thirty ecosystems all
apply regardless of language. Only `resilience_calls` and `env_refs` extraction
from source literals is bounded to these three.

When a repository's primary language is outside this set, each affected skill
records an assumption naming the language and what went unscanned, drawn from the
scan's `coverage.skipped` field — so the gap is visible in the contract rather
than silently read as "no resilience declared."
