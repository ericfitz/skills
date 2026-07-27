---
name: run
version: 0.1.0
description: Run a CATS fuzzing campaign against this repo's configured server and spec. Use when asked to fuzz the API, run CATS, or start a security fuzzing campaign.
---

# cats:run

Dispatches the bundled `cats-run` subagent (`${CLAUDE_PLUGIN_ROOT}/agents/cats-run.md`)
to execute one full fuzzing campaign, then reports its summary.

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
blackbox mode, skip-seed, skip-parse); the agent only forwards flags it's
explicitly given, so be specific.

## On completion

**Don't key off exit code 2 alone** — `run` exits with CATS's own exit code
verbatim on a completed campaign, and CATS is free to use 2 for its own
reasons. Use what actually printed to tell the two apart:

- **A library error** (missing config, a failed preflight check — spec not
  found, `cats` not on PATH, invalid rules file, server not reachable — or a
  failed `seed`/`pre_run` hook) prints a single message to **stderr** and
  prints **no run summary at all** (no `run_id:`/`db:`/"Results by type"
  block). Report that message **verbatim** and stop. Do not guess at a fix,
  do not retry, do not edit the user's hook to paper over the failure — the
  message already says what's wrong and (for config issues) points at
  `/cats:init`.
- **A completed campaign** always prints the full run summary first,
  regardless of what exit code CATS itself returns. If the agent's report
  includes run_id/db/counts, the campaign ran to completion — report that
  summary, then point the user at `/cats:analyze` to triage the true
  positives it found.
