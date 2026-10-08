# D4.2 — No vivid imagery or analogy

**Axis**: Surprise. **Mechanical-analyzer support**: none (deferred to LLM).

## What this dimension measures

Vivid imagery / analogy = the writer reaching outside the document's
abstract domain to give the reader a concrete picture. Examples:

- "The system currently behaves like a phone tree from 1996" (analogy)
- "The control plane sits above the data plane like a thermostat above
  a furnace" (imagery)
- "Imagine the cache as a coat-check at a busy restaurant — the
  attendant has to find your coat fast, but only the coats actually
  belonging to current diners" (extended analogy)

Concrete numbers and named entities (which mechanical D4.1 catches)
are *not* what this dimension measures — this is specifically about
pictures, comparisons, and analogies that make new material familiar.

This is a Surprise-axis dimension: a well-placed analogy creates a
small dopaminergic re-hook (the reader's brain lights up when an
unexpected familiar pattern fits the new material). The dimension's
absence doesn't make a document wrong, but it makes it feel
relentlessly abstract.

## What to look for

- Analogies to systems / experiences the reader already knows
  (especially from outside the document's technical domain)
- Metaphors that reframe the technical content
- Comparisons that make the unfamiliar familiar
- Worked thought experiments ("imagine you're holding 100 keys and
  someone asks you for the one tagged 'apartment'")
- Physical or sensory grounding for abstract concepts

## Scoring

- **pass** — At least one well-placed vivid analogy or image in a
  topic that benefits from it. Or the document is in a genre where
  imagery is correctly absent (specs, formal proofs, runbooks).
- **warn** — Pure abstraction throughout, in a topic that should
  have been grounded. The document is comprehensible but
  consistently asks the reader to hold abstract concepts without
  giving them anywhere to land.
- **severe** — Long abstract document with zero attempt to ground
  the material. The reader has to do all the work of building mental
  models from first principles.

## Genre adjustments

- **Specifications / formal proofs / regulatory standards**: should
  be austere. Analogies in this genre tend to introduce ambiguity.
  Score `pass` with `high` confidence and note that the genre rules
  this dimension out.
- **Runbooks / operational procedures**: same — should be austere.
  Score `pass` with `high` confidence.
- **API reference docs**: light imagery is fine but not required.
  Score `pass` unless the prose strains under abstraction in a way
  that grounding would relieve.
- **Tutorials**: imagery is highly valued. Apply strictly.
- **Architecture decision records / RFCs**: at least one grounding
  analogy is usually warranted. Apply normally.
- **Technical reports**: analogies are valued in the framing (intro
  + conclusion); the methods section can be austere. Judge mostly
  from the framing sections.
- **Executive briefs**: analogies are highly valued — non-technical
  readers depend on them. Apply strictly.
- **Finding writeups**: at least one analogy in the impact / context
  section is usually warranted.

## How much imagery is enough?

A document with even *one* well-placed vivid analogy in a topic that
benefits from it scores `pass`. This dimension does not reward density
of imagery — overuse can be its own problem (the document feels
folksy or unserious). One memorable analogy in a 3000-word document
is plenty.

## Common evidence patterns

- **Pass**: "Think of the rate limiter as a bouncer at a club: it's
  not deciding who's a good guest, just whether the room is at
  capacity right now." — one analogy, clearly placed at the moment
  of introducing rate limiting
- **Warn**: a 3000-word architecture doc with no analogies, no
  metaphors, no grounding — just nested abstractions described in
  terms of their components
- **Severe**: a 10,000-word academic paper proceeding through pure
  formalism with no concrete picture offered for any of the central
  abstractions

## What the mechanical layer cannot tell you

The mechanical analyzer detects example markers (D4.1: "for example",
"such as", "consider", "imagine"). These can *coincide* with vivid
imagery but they aren't the same thing — "consider the case where X"
introduces an example, not an analogy. Vivid imagery is specifically
about reaching outside the domain to bring something familiar in.
Judge from substance, not marker presence.
