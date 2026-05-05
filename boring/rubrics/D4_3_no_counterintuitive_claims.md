# D4.3 — No counterintuitive claims

**Axis**: Surprise. **Mechanical-analyzer support**: none (deferred to LLM).

## What this dimension measures

A counterintuitive claim is a sentence that pushes against the reader's
default belief or expectation:

- "Surprisingly, X."
- "We expected Y but found Z."
- "Conventional wisdom says A; in practice it's B."
- "This is the opposite of what most teams do, and here's why."

Counterintuitive claims are dopaminergic: they hook attention and make
the reader want to know how the document gets there. A document
without counterintuitive claims may still be useful, but it will feel
predictable — every sentence confirms what the reader could have
inferred. Engagement degrades quickly even when the prose mechanics
are clean.

This is a Surprise-axis dimension: surprise is a major neural hook
(N400 prediction-error response). A document that confirms expectations
sentence by sentence offers no such hooks.

## What to look for

- Surprise markers: "surprisingly", "unexpectedly", "we were wrong",
  "contrary to", "instead of", "we expected ... but"
- Findings explicitly contrasted with default assumptions
- Recommendations explicitly contrasted with industry norms or prior
  approaches
- Sub-claims acknowledged as initially counterintuitive
- Author admitting their own initial expectation was wrong
- Claims framed as "you'd think X — but actually Y"

## Scoring

- **pass** — One or more substantive counterintuitive claims.
  The document explicitly engages with what a reader might have
  expected and corrects it.
- **warn** — Confirms expectations throughout. No friction with
  default beliefs. The reader could have written the document
  themselves from the title.
- **severe** — Reads as a list of conventional positions defended
  with conventional reasoning. Every claim aligns with industry
  defaults; nothing the reader didn't already assume.

## Genre adjustments

- **Reference docs / specs / standards / runbooks**: should *not*
  contain counterintuitive claims — they describe what is, not what
  was discovered. Score `pass` with `high` confidence and note the
  genre rules this dimension out.
- **Tutorials**: light counterintuitivity is great ("a common
  mistake is X — here's why it doesn't work"); strong
  counterintuitivity is unnecessary. Score `pass` for any "common
  mistake" or "you might think X but" content.
- **Status updates**: counterintuitive claims appropriate when
  reporting unexpected progress or unexpected obstacles. Apply
  normally; absence is `warn` not `severe`.
- **Technical reports**: counterintuitive claims expected (the whole
  point is "what we found"). Apply strictly. A report that confirms
  every prior assumption is suspicious — either the work was unneeded
  or the writer is hiding the surprises.
- **Architecture decision records / RFCs**: at least one
  counterintuitive element is usually warranted (otherwise the
  decision was obvious and didn't need a record). Apply strictly.
- **Finding writeups**: counterintuitive claims expected (a finding
  that confirms what everyone already believed is rarely worth
  writing up). Apply strictly.
- **Proposals**: counterintuitive claims valued — they justify why
  the proposal is needed. Apply normally.
- **Executive briefs**: counterintuitive claims highly valued —
  executives don't need confirmation of what they already think.
  Apply strictly.

## Common evidence patterns

- **Pass**: "We initially planned to add a cache layer between the
  service and the database, expecting most of our latency to come from
  database round-trips. Profiling showed the opposite — the database
  was responding in 2ms; the latency was in our serializer. Adding a
  cache wouldn't have moved the needle."
- **Pass**: "The standard advice is to denormalize for read-heavy
  workloads. We tried this and it made things worse — the
  denormalization cost dominated because our reads are bursty, not
  steady."
- **Warn**: "We chose Postgres because it's the standard relational
  database, with strong tooling support and a large ecosystem." (no
  friction with defaults)
- **Severe**: a finding writeup that catalogs known issues with
  known fixes — no insight about why they're underaddressed, no
  finding the team didn't already suspect, no surprise

## What the mechanical layer cannot tell you

Counterintuitive claims have no reliable surface signature. The
markers above ("surprisingly", "we expected") often appear, but their
presence doesn't guarantee a real counterintuitive claim, and good
counterintuitive claims sometimes appear without explicit markers.
Judge from substance: ask yourself "if I read the title, could I have
written this content from defaults?". If yes, the counterintuitive
content is missing.
