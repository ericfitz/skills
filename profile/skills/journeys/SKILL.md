---
name: journeys
description: Identify the key workflows users actually perform with a system, mined from documentation evidence, routes, CLI commands, and UI entry points, ranked by business criticality with dependency edges between them. Use when profiling an unfamiliar project for test design, documentation, or product understanding. Emits the profile:journeys contract.
---

# journeys

Mine a repository for the workflows its users actually perform, and emit the
`journeys` contract as **ranked candidates for a human to confirm**.

This phase proposes. It does not decide. The caller runs the confirmation gate.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/journey-sources.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/journeys.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/journeys.example.json`

## Usage

    /profile:journeys [path]

## Input

You are normally handed a `profile:stack` contract and a `profile:docs` contract.
The `docs` contract's `journey_evidence[]` is your strongest source: it is what the
project's own documentation says people do with the system, already extracted with
anchors. Its `glossary[]` gives you the project's vocabulary — name candidates in it.

**Standalone invocation:** if you were not handed them, invoke `profile:stack`, then
`profile:docs`, and use their output.

## Procedure

1. Start from the `docs` contract's `journey_evidence[]`, then work down the remaining
   priority order in `references/journey-sources.md`. Record every source you used in
   `sources_read`, including `corpus_id` references from the `docs` contract. Do not
   re-read documents `profile:docs` already read.
2. Draft candidates. Each needs an actor, an intention, and an observable outcome.
   Apply the "What is not a journey" filter.
3. Attach `evidence` as `file:line` references to every candidate. A candidate with
   no evidence does not ship.
4. Rank by the criticality rubric, then assign `rank` as a dense ordering from 1.
5. Add `depends_on` edges per "Finding dependency edges". These matter downstream:
   consumers use them to order work and to establish prerequisite state.
6. Estimate `surface_coverage` — what fraction of the public entry points these
   candidates touch. An honest low number is useful information.
7. Emit at most 12 candidates, then a short prose summary naming the ones you were
   least certain about.

## Rules

- Prefer what the documentation says users do over what the code makes possible.
- Do not report anything about existing tests or test coverage. That is a consumer's
  concern, not this phase's.
- If the repository has no usable documentation, say so in the summary and rank
  purely from the public surface — and say that too.
