---
name: run
version: 0.1.0
description: Run a CATS fuzzing campaign against this repo's configured server and spec. Use when asked to fuzz the API, run CATS, or start a security fuzzing campaign.
---

# cats:run

Dispatches the bundled `cats-run` subagent (`${CLAUDE_PLUGIN_ROOT}/agents/cats-run.md`)
to execute one full fuzzing campaign, then reports its summary.

**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), do the worker's job inline: read
`${CLAUDE_PLUGIN_ROOT}/agents/cats-run.md` and execute the campaign yourself,
following it exactly. Same output contract (the compact summary).

## Before dispatching

If `.local/cats/config.yaml` is missing, `cats_tool.py` exits 2 with
"No .local/cats/config.yaml found. Run /cats:init to create one." — check for
the file yourself first, and if it's missing, point the user at `/cats:init`
instead of dispatching the agent.

## Dispatch

Run the `cats-run` agent **in the background** — a real campaign runs the
full CATS fuzzer against every configured path and typically takes
**30-40 minutes**. Tell the user this up front so they aren't left wondering
why nothing has returned yet.

Pass through any flags the user asked for (identity, path filter, rate limit,
blackbox mode, skip-seed, skip-parse, allow-port-forward, no-prune); the
agent only forwards flags it's explicitly given, so be specific.

## Server path check

Before ever touching the network, `checks()` inspects the process table for a
`kubectl port-forward` bound to the configured `server:`'s local port
(loopback URLs only). A userspace forward silently drops requests under load
(observed ~46% loss as connection-error codes 953/999 in a real campaign
against this repo), and those errors get absorbed by the `CONNECTION_ERROR_999`
false-positive rule — so the run *looks* clean while most of the API was
never actually reached. If a forward is detected and not explicitly allowed,
`run` fails this check before fuzzing starts, naming the forward's command
line and the fix: point `server:` at a directly reachable endpoint (e.g. a
NodePort), or pass `--allow-port-forward` / set `allow_port_forward: true` in
`config.yaml` if the forward is genuinely fine for this repo.

## On completion

**Don't key off exit code 2 alone** — `run` exits with CATS's own exit code
verbatim on a completed campaign, and CATS is free to use 2 for its own
reasons. Exit code **3** is different: it means the campaign ran to
completion but is **invalid** (see "Validity gate" below), not that CATS
itself failed. Use what actually printed to tell these apart:

- **A library error** (missing config, a failed preflight check — spec not
  found, `cats` not on PATH, invalid rules file, server not reachable, a
  disallowed kubectl port-forward — or a failed `seed`/`pre_run` hook) prints
  a single message to **stderr** and prints **no run summary at all** (no
  `run_id:`/`db:`/"Results by type" block). Report that message **verbatim**
  and stop. Do not guess at a fix, do not retry, do not edit the user's hook
  to paper over the failure — the message already says what's wrong and (for
  config issues) points at `/cats:init`.
- **A completed campaign** always prints the full run summary first,
  regardless of what exit code CATS itself returns. If the agent's report
  includes run_id/db/counts, the campaign ran to completion — report that
  summary, then point the user at `/cats:analyze` to triage the true
  positives it found (unless the run is invalid — see below).

## Validity gates

A campaign can run to completion and still be worthless. There are three ways
that happens, and `run` checks for all of them after every completed campaign:

| gate | config key (default) | what it means |
|---|---|---|
| **transport** | `max_connection_error_pct` (1.0%) | tests failing with a connection error (CATS pseudo-codes 953/999) — the requests never reached the API |
| **credential** | `max_unauthenticated_pct` (5.0%) | tests getting a **non-false-positive** 401 — the campaign lost its bearer token partway through and the rest of the run only exercised the unauthenticated path |
| **fixture** | `cats.fixtures` (unset = gate off) | a seeded fixture the campaign depends on no longer exists at the end of the run — the campaign DELETEd its own test data, so every later test nested under that fixture ran against a 404 |

The fixture gate is not a percentage. One dead anchor silently invalidates
every path beneath it, so a single death fails the run.

### The pattern behind all three: the campaign sabotaging itself

Every one of these gates exists because a campaign destroyed its own ability to
keep testing, **while still reporting as complete**. That is the failure mode to
be suspicious of, and it generalizes past these three. When triaging any
surprising result, ask whether the fuzzer did something to the system that
invalidated the rest of its own run:

- **Revoking its own credential.** A self-logout endpoint blacklists the very
  bearer token the campaign authenticates with. Everything after that point is
  a 401 against an unauthenticated path.
- **Deleting its own fixtures.** DELETE on `/things/{id}` where `{id}` came from
  refData consumes the seeded fixture, and because CATS walks paths in lexical
  order the anchor is usually fuzzed *before* everything nested under it.
- **Mutating its own identity.** A successful PATCH/DELETE against the fuzzing
  user's own account has the same effect as a logout. Point destructive
  user/admin routes at a dedicated throwaway account, never the identity in use.
- **Exhausting a shared budget.** Rate limits, quotas, and lockout counters
  consumed early make later tests fail for reasons that have nothing to do with
  the endpoint under test.
- **Poisoning shared state.** A fuzzer that writes an invalid value into a
  config or cache other endpoints read will make those endpoints fail
  independently of their own correctness.

The tell is always the same shape: **findings that cluster by *when* the test
ran rather than by *what* it tested.** If failures start at some test number and
never stop, suspect self-sabotage before believing the findings. Check the
result distribution by test number before concluding anything about the API.

The fixes follow a pattern too — take the destructive operation off the
resource the rest of the campaign depends on:

- give the anchor path its own **throwaway decoy** id, so a successful DELETE
  consumes the decoy while the fixture nested paths need survives;
- or put the endpoint in `cats.skip_paths` and fuzz it in its own short run,
  where destroying something at the end costs nothing.

Some 401s are expected (`BypassAuthentication` and the header-mangling
fuzzers provoke them deliberately), which is why the credential gate counts
only 401s that survived false-positive classification, and why it is a
threshold rather than zero.

If either threshold is exceeded the run is **contaminated**: its per-rule and
per-path conclusions are meaningless. `run` prints both counts/percentages,
then a `RUN INVALID` block to stderr naming every gate that failed, and exits
**3** — `latest.db` is **not** updated to point at this run, so a later
`/cats:analyze` (which defaults to `--db latest`) can't accidentally analyze
it. Report the invalid run with the cause the tool printed rather than
treating it as a normal completed run.

The usual cause of a credential failure is fuzzing an endpoint that revokes
the caller's own token — a self-logout endpoint will happily blacklist the
very bearer token the campaign is authenticating with. Put those in
`cats.skip_paths` (rendered as CATS's `--skipPaths`) and fuzz them on their
own instead:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py run --path /me/logout
```

An explicit `--path` wins over `skip_paths`, precisely so a skipped path can
still be tested — at the end of its own short campaign, losing the token
costs nothing.

## Retention

Each run's database (`cats-results-<run_id>.db`) is roughly 1.4 GB, and
nothing removed them automatically before this — a results directory could
grow without bound. After a **successful, valid** run (same gate as the
`latest.db` update above: parsed, classified, and not contaminated), `run`
prunes old run databases down to the `keep_runs` most recent
(`config.yaml`'s `keep_runs`, default 5), always keeping whichever one
`latest.db` points at. Each pruned database takes its raw report artifacts
(`report-<run_id>/` and `report-<run_id>.*`) with it; a surviving run keeps
its own. A failed, skipped-parse, or contaminated run never
prunes — only a run that was itself trustworthy is allowed to delete history.

If anything was pruned, the summary includes a line like:

```
Pruned 3 old run database(s), reclaimed 4.2 GB (keep_runs: 5)
```

No line is printed if pruning is enabled but nothing was old enough to
remove. Pass `--no-prune` to skip pruning for a single invocation without
changing `keep_runs`. To prune outside of a run (e.g. to reclaim space
between campaigns), use `uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py
prune [--keep N] [--dry-run]` directly.
