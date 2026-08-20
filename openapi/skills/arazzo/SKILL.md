---
name: arazzo
description: Generate an Arazzo workflow spec (arazzo.yaml) from the confirmed customer-journeys doc, mapping each journey's steps onto real operations in the project's OpenAPI spec. Use when asked to create an Arazzo spec, generate API workflow descriptions, or turn journeys into executable workflow definitions.
---

# arazzo

Turn the confirmed journeys doc into an Arazzo 1.0 workflow description bound
to the project's OpenAPI spec.

Authoring reference: `${CLAUDE_PLUGIN_ROOT}/references/arazzo-authoring.md`

## Usage

    /openapi:arazzo [journeys-doc-path]

The journeys doc defaults to `docs/journeys.md` — the file `itest:design`
writes after its human gate.

## Preflight

Two inputs are required. When one is missing, offer to produce it now rather
than bailing out:

- **`.local/openapi/config.yaml` missing** → offer to run `/openapi:init` in
  this session. Stop only if the user declines or cancels init.
- **Journeys doc missing** (default `docs/journeys.md`, or the path given as
  an argument) → offer to run `/itest:design`, noting that it is a long,
  human-gated discovery workflow. Stop only if the user declines.

Read the journeys contract from the doc's fenced JSON block. If the block is
absent, fall back to the prose sections and say that you did.

Read the OpenAPI spec named by `openapi_spec` and enumerate its operations
(operationId, method + path, summary, declared response codes).

## Mapping

One Arazzo workflow per confirmed journey, following the authoring reference:

- `workflowId` from the journey `id`, sanitized to `[A-Za-z0-9_\-]+`.
- `summary`/`description` from the journey name and narrative.
- Workflow-level `dependsOn` from the journey's `depends_on` edges.
- Steps: decompose the narrative into concrete calls and bind each to a real
  operation — `operationId` preferred, `operationPath` when the spec declares
  no ids. Chain obvious data flow with `$steps.<stepId>.outputs.<name>`
  (created ids, tokens, cursors). Default `successCriteria` is a
  `$statusCode` check against the 2xx code the spec declares for that
  operation.
- A journey that is **not API-shaped** (a CLI or UI actor with no operation
  to bind) is flagged and skipped, never force-mapped.

## Human gate

Before writing anything, present the full mapping as a table — journey →
proposed steps → operations — with unmapped steps and skipped journeys called
out explicitly. The user approves, edits, or drops entries. Nothing is
emitted until they respond.

## Emission

- Write to the `arazzo_spec` path from the config (default `arazzo.yaml` at
  the repo root, the spec's recommended entry-document name).
- Document header: `arazzo: 1.0.1`. `info` from the repo's name and version;
  `sourceDescriptions` pointing at the OpenAPI spec by relative path with
  `type: openapi`.
- If the target file already exists, summarize what would change and ask
  before overwriting.
- If a committed `apis.yaml` exists at the repo root without an Arazzo entry,
  offer to add one.

## Validation

After emission, validate the document with `redocly`, `spectral`, or `vacuum`
if one is on PATH, and report its findings. Otherwise run a structural
self-check — every referenced `operationId` resolves against the OpenAPI
spec, every `dependsOn` names an emitted workflow, every referenced step
output exists — and state explicitly that no external validator ran.

## Rules

- Never invent operations: a step that cannot bind to the OpenAPI spec is
  surfaced at the gate, not fabricated.
- Journeys the user removed or dropped at the gate stay out of the document.
- Never invoke another plugin's scripts by path; `/openapi:init` and
  `/itest:design` are invoked as skills.
