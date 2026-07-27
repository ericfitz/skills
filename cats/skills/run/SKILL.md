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

**Exit code 2** means a library error, not a fuzzing outcome — a missing
config, a failed preflight check (spec not found, `cats` not on PATH,
invalid rules file, server not reachable), or a failed `seed`/`pre_run` hook.
Report the tool's message **verbatim** and stop. Do not guess at a fix, do
not retry, do not edit the user's hook to paper over the failure — the
message already says what's wrong and (for config issues) points at
`/cats:init`.

**Any other exit code** means the campaign ran to completion (CATS itself
exits nonzero on some fuzzing outcomes even though the run succeeded and
produced results). Report the summary the agent returned, then point the
user at `/cats:analyze` to triage the true positives it found.
