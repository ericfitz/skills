# Journey sources

Reference for `profile:journeys`: where evidence of real user workflows comes from,
strongest first, how to rank a candidate's `business_criticality`, how to draw
`depends_on` edges between candidates, and what does not qualify as a journey at all.

## Source priority

Mine sources in this order. A candidate backed by a source near the top of this list
needs less corroboration than one backed only by a source near the bottom.

1. **The `docs` contract's `journey_evidence[]`.** Someone wrote down what users do
   with this system — nothing beats that. Each item already carries an `actor` and
   an `entry_point_hint` where the text gave them, and `source_refs` anchored into the
   corpus `profile:docs` read. Cite those `corpus_id` references directly in your own
   `sources_read`, and name candidates using the `glossary[]` vocabulary rather than
   inventing new terms for the same concept.
2. **OpenAPI or GraphQL schemas.** An operation with a summary or description is a
   named workflow with its actor and outcome mostly written for you.
3. **HTTP route registration.** A router table or controller mapping tells you every
   entry point that exists, even the ones no document mentions.
4. **CLI subcommand definitions.** A subcommand with its own help text is a workflow
   its authors thought worth naming.
5. **UI route definitions.** A client-side router or page-registration table shows
   what a human is meant to navigate to and do there.
6. **The e2e entries of the inventory's file census.** A named end-to-end scenario
   file is evidence that someone once cared enough about a workflow to script it
   start to finish; the file's name is often the clearest available label for the
   journey it exercises. Use it to name and locate candidates, never to report on it
   as a phase in its own right — that reporting belongs to a later consumer, not to
   this phase.
7. **Issue and milestone titles.** What a project spends its planning effort on is
   weak but real evidence of what its workflows are.
8. **Commit message themes.** The weakest source: a recurring theme across commits
   suggests an area of the system that matters, but rarely names an actor or an
   outcome on its own.

**The documentary record is read by `profile:docs`, not here.** If you were handed a
`docs` contract, work from its `journey_evidence[]` and `glossary[]` rather than
re-reading the PRDs, READMEs, or wiki pages it already read. Re-reading the same
prose wastes the run and produces a second, slightly different reading of a document
this plugin already settled once.

## Ranking rubric

Assign `business_criticality` using these four values, in this order of decreasing
weight:

| value | when it applies |
|---|---|
| `critical` | the workflow is the product's reason to exist, or it is the revenue path — the thing that would make the product pointless or unpaid if it broke |
| `high` | the workflow is named in the README or documentation as a primary flow, even if it is not the revenue path |
| `medium` | the workflow is a supported flow reachable from the public surface, with no particular documentation or business emphasis calling it out |
| `low` | the workflow is administrative, diagnostic, or rarely used — an operator task, a settings change, a maintenance action |

When a candidate could plausibly sit at two levels, prefer the lower one and say why
in `rationale`. An inflated ranking is a worse error than a modest one: it misdirects
whatever a consumer does with `rank` next.

## Finding dependency edges

A candidate depends on another (`depends_on`) when any of these hold:

- **Its entry point requires an identifier that only another journey can produce** —
  a cancel-order journey needs an order id, and only a create-order journey produces
  one.
- **Documentation describes it as a follow-on step** — a guide that walks through
  journey A and then says "once you have done that, you can B" is stating the edge
  directly.
- **Its handler reads an entity another journey creates** — the code path behind the
  entry point loads a record whose only writer is another candidate's entry point.

Do not invent an edge from mere topical proximity (two journeys that both touch
"orders" are not automatically dependent). An edge without one of the three
justifications above does not ship.

## What is not a journey

These do not qualify as candidates, however prominent they are in the code:

- **A single endpoint with no user-visible outcome** — an endpoint that returns data
  but changes nothing and completes no task on its own is a building block, not a
  workflow.
- **A health check.** Nobody's intention is served by it; it exists for the system,
  not for a user.
- **An internal cron task with no actor.** A scheduled job that no one triggers and
  no one is waiting on has no actor to name.
- **A pure function.** Correct in isolation or not, it has no entry point a user
  reaches and no outcome a user observes.
- **A configuration knob.** Setting a value is not itself a workflow; the workflow is
  whatever the setting later changes the behavior of.

## Closing rule

"A journey has an actor, an intention, and an observable outcome. If you cannot name
all three, it is not a journey."
