# D1.2 — Missing stakes

**Axis**: Direction. **Mechanical-analyzer support**: none (deferred to LLM).

## What this dimension measures

Stakes = the reader's answer to "why does this matter, and what happens
if we get it wrong?". A document with stakes makes the cost of inaction
or the cost of a wrong choice concrete and felt. A document without
stakes describes a topic without giving the reader a reason to care.

This is a Direction-axis failure: when stakes are absent, the reader
loses the meaning component (MAC model). Even prose that's structurally
clean and rhythmically alive will get put down if the reader can't
locate why finishing it is valuable.

## What to look for

- A stated problem with consequences (cost, risk, opportunity, impact)
- An audience signal — who has skin in the game
- Whether the early portion (~first 15%) establishes "why now" / "why this"
- Whether the recommendation, if any, ties back to stakes
- Whether stakes are *concrete* ("a $4M write-down", "two outages last
  quarter", "the auth team blocks here every sprint") or *abstract*
  ("strategic alignment", "operational efficiency")

## Scoring

- **pass** — Stakes are stated clearly in the first ~15% of the
  document. Concrete consequences, specific audience, "why now" cue
  present. The reader knows from early on what's at risk.
- **warn** — Stakes are present but vague, buried, or generic. The
  reader can infer them but the document doesn't make them visible.
  ("This is important for our growth strategy" without saying what
  growth depends on or what slows it down.)
- **severe** — No stakes stated. The document proceeds as a
  description of a topic with no acknowledged cost of getting it
  wrong. The reader has to supply their own motivation.

## Genre adjustments

- **Status updates**: stakes are usually implicit in the recipient
  relationship. Score `pass` unless the update describes a *change* in
  status that isn't explained.
- **Reference docs / specs / runbooks**: stakes are inappropriate;
  these are pure information transfer. Score `pass` with `high`
  confidence and note in the rationale.
- **Architecture decision records / RFCs**: should explicitly state
  what's at stake in the decision. Apply the rubric strictly.
- **Executive briefs**: stakes are non-negotiable. The first paragraph
  should answer "why is this in front of me?". Apply strictly.
- **Finding writeups** (security, audit, quality): stakes should
  appear in the "Impact" section if the format is templated, or
  early in the body if not. Severity is justified when impact is
  understated or omitted.

## Common evidence patterns

- **Pass**: "Last quarter we shipped 14% of planned features because
  the build pipeline blocks for 40 minutes per merge. This proposal
  cuts that to under 5 minutes."
- **Warn**: "Improving build performance is important for developer
  productivity." (true but generic — the reader supplies the stakes)
- **Severe**: "This document describes the architecture of the new
  CI/CD pipeline." (no problem stated, no cost cited, no audience cue)

## What the mechanical layer cannot tell you

The mechanical analyzer flags expletive subjects ("It is important to
note that...") via D1.6 and detects throat-clearing openers via D2.8.
Both of those *can* coincide with weak-stakes prose, but neither
measures stakes directly. A document with zero expletives can still
have no stakes; a document riddled with expletives can still have
sharp stakes once you get past the throat-clearing. Judge stakes from
the substance, not the surface signals.
