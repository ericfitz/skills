---
name: api-workflows
description: Shortcut that produces an Arazzo workflow spec — init when no OpenAPI spec is recorded in .local/openapi/config.yaml, then arazzo. Chains existing skills only.
argument-hint: "[journeys-doc-path]"
disable-model-invocation: true
---

# api-workflows

Produce an Arazzo workflow spec in one command: record the OpenAPI spec if
needed, then generate the workflows.

## Steps

1. Invoke `test-api-workflows:init`, only if `.local/openapi/config.yaml` is
   missing or has no `openapi_spec`. Otherwise say that this step was
   skipped.
2. Invoke `test-api-workflows:arazzo` with `[journeys-doc-path]`. Its own
   preflight offers apply.

## Usage

    /test-api-workflows:api-workflows [journeys-doc-path]

The bare form `/api-workflows` also works in Claude Code when no other command has
that name; Codex uses the namespaced form only.

## Rules

- Invoke every skill by name, never by script path. Each chained skill keeps
  its own confirmation gates; answer none of them for the user.
- Stop at the first step that fails or that the user declines. Report
  `Stopped at step N (<skill>): <reason>` and list what completed.
- This shortcut adds no behavior of its own: it sequences the skills above.
