# D1.5 — Flat tension

**Axis**: Direction. **Mechanical-analyzer support**: none (deferred to LLM).

## What this dimension measures

Cognitive tension = the reader's sense that the document is building
toward something — a finding, a resolution, a payoff. A document with
tension has a problem-solution arc: difficulties acknowledged and then
overcome; alternatives considered and rejected; sub-questions raised
and answered. A flat document presents conclusions without the
difficulties they overcame and proceeds in a single descriptive
register throughout.

This is the Boyd/Blackburn/Pennebaker "narrative arc" finding scaled
down to the document level. Even non-fiction texts (NYT articles, TED
talks, Supreme Court arguments) follow staging → plot progression →
cognitive tension. Engaging non-fiction has these. Boring non-fiction
often has staging but flatlines on the rest.

## What to look for

- Acknowledgment of difficulty / failure / surprise during the work
  ("we initially tried X but it failed because...")
- Alternatives discussed and rejected (versus a single path presented
  as the only option)
- Sub-question structure — does each section earn its existence by
  resolving something?
- Whether the document has narrative shape (setup → complication →
  resolution) at any scale, or proceeds as flat exposition
- Whether the writer is willing to surface "the hard part" — the
  judgment call, the tradeoff that doesn't have a clean answer, the
  thing that nearly didn't work

## Scoring

- **pass** — Tension is built and resolved at least once. The
  document acknowledges difficulty; alternatives are discussed; there
  is a "hard part" the writer is willing to make visible.
- **warn** — Tension is present in places but flatlines for long
  stretches. The document mentions difficulty in passing but never
  develops it. Alternatives appear as a perfunctory "we considered X,
  Y, Z and chose Z" without explaining why X and Y didn't work.
- **severe** — Pure flat exposition. Conclusions are stated without
  the difficulties they overcame. No alternatives discussed. No
  sub-questions raised. The document reads as if every choice was
  obvious from the start.

## Genre adjustments

- **Status updates**: should be tensionless. Score `pass` with `high`
  confidence and note in the rationale.
- **Reference docs / specs / runbooks**: should be tensionless. Score
  `pass` with `high` confidence.
- **Tutorials**: light tension is good ("a common mistake is X, here's
  why"); strong tension is unnecessary. Score `pass` for any
  documented gotchas; `warn` only if the tutorial is so smooth it
  ignores known confusions.
- **Technical reports**: tension expected. The whole point is to
  document the investigation; if it reads as if the investigators
  knew the answer from the start, that's `warn` or `severe`.
- **Architecture decision records / RFCs**: tension expected. The
  whole point is the alternatives-and-tradeoffs analysis. A record
  that just announces the decision without the rejected paths is
  `warn` or `severe`.
- **Finding writeups**: moderate tension expected. The investigative
  arc (what we looked for → what surprised us → what it means)
  should be visible.
- **Proposals**: tension expected. A proposal that pretends every
  difficulty was anticipated and resolved is suspicious; readers want
  to see the tradeoffs.

## Common evidence patterns

- **Pass**: "Our first attempt batched the writes, which broke under
  high concurrency — the second writer would silently overwrite the
  first's pending update. The fix wasn't to add locking (we tried —
  the contention was worse) but to model writes as an append-only log
  with a periodic compaction."
- **Warn**: "We considered alternatives A, B, and C, and chose C."
  (perfunctory; no friction visible)
- **Severe**: "The system uses approach C. Approach C handles X by
  Y. Approach C also handles Z by W." (flat description, no
  alternatives, no acknowledgment that any choice was made)

## What the mechanical layer cannot tell you

Tension is structural and semantic. The mechanical analyzer measures
prose mechanics (passive voice, sentence-length variation, etc.) —
none of which correlate well with whether the document has narrative
shape. A flatlining document can be sentence-by-sentence well-crafted;
a high-tension document can have rough mechanics.
