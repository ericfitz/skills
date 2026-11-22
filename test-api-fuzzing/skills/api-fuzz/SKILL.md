---
name: api-fuzz
description: Shortcut that runs a whole CATS API fuzzing pass — init when .local/cats/config.yaml is missing, then run, report and analyze. Chains existing skills only.
argument-hint: "[flags passed through to run, e.g. --identity NAME --path PATTERN]"
disable-model-invocation: true
---

# api-fuzz

Run a whole CATS API fuzzing pass in one command: configure if needed, fuzz,
query the results, and triage the findings.

## Steps

1. Invoke `test-api-fuzzing:init`, only if `.local/cats/config.yaml` is
   missing. Otherwise say that this step was skipped.
2. Invoke `test-api-fuzzing:run` with all of the user's flags, unchanged. Wait
   for the campaign to finish. A failed validity gate is a failed step.
3. Invoke `test-api-fuzzing:report` against the latest database.
4. Invoke `test-api-fuzzing:analyze` against the latest database.

## Usage

    /test-api-fuzzing:api-fuzz [flags passed through to run]

The bare form `/api-fuzz` also works in Claude Code when no other command has
that name; Codex uses the namespaced form only.

## Rules

- Invoke every skill by name, never by script path. Each chained skill keeps
  its own confirmation gates; answer none of them for the user.
- Stop at the first step that fails or that the user declines. Report
  `Stopped at step N (<skill>): <reason>` and list what completed.
- This shortcut adds no behavior of its own: it sequences the skills above.
