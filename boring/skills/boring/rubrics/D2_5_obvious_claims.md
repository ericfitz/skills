# D2.5 — Obvious claims

**Axis**: Density. **Mechanical-analyzer support**: none (deferred to LLM).

## What this dimension measures

Obvious claims are sentences that assert what the reader already knows
or has just inferred from the prior sentence. Each obvious claim is a
small failure of information density: it costs the reader attention but
delivers no new information. Pervasive obvious claims produce the
"why am I reading this?" feeling — the document is technically correct
but not informative.

This is the Density-axis understimulation pole in MAC terms. The reader
isn't overwhelmed; they're under-fed. Every sentence tells them
something they could have predicted from the previous sentence (or
from knowing the topic at all).

## What to look for

- Sentences that restate the previous sentence with different words
- Definitions of terms the audience clearly knows for its declared
  genre (defining "API" in a doc for engineers, defining "TLS" in a
  doc for security professionals)
- Statements of facts so general they apply to any document in the
  field ("Security is important." "Performance matters at scale.")
- Closing sentences that summarize what was just said one paragraph
  ago — not a section summary, a redundant restatement
- "Throat-clearing" intros that announce the obvious ("This document
  is about X" — when X is the title)
- Conjunctive paragraphs where every sentence adds the same idea in a
  slightly different shape, instead of advancing the argument

## Scoring

- **pass** — Information density is healthy. Most sentences advance
  the argument or contribute new specifics. The occasional definition
  or transition is fine.
- **warn** — Noticeable filler. Multiple sentences could be deleted
  with no information loss. Some sections have an "every sentence
  says the same thing" feel.
- **severe** — Pervasive. Whole paragraphs (especially intros and
  conclusions) are filler. The document could be reduced by 30%+
  with no information loss. Definitions of terms the audience knows;
  general truisms; restatements of headings.

## Genre adjustments

- **Tutorials / explainers for novice audiences**: defining basic
  terms is appropriate. Score `pass` even if a more expert audience
  would find them obvious.
- **Status updates**: should be high-density. Apply strictly.
- **Reference docs / specs**: definitions are part of the content.
  Score `pass` for definitions, but `warn` for editorializing
  ("Note that this is important...") or restatement.
- **Executive briefs**: should be high-density. Apply strictly.
- **Finding writeups**: should be high-density (executives skim them).
  Apply strictly.

## Density of obvious claims matters more than absolute count

Two or three obvious sentences in a long document are unimportant. An
opening section made entirely of "as everyone knows..." filler is
severe. If the document is short and dense (good), score `pass` with
high confidence even if there's one fluffy sentence somewhere.

## Common evidence patterns

- **Pass**: every sentence either makes a claim, supplies evidence,
  acknowledges a difficulty, or signposts structure
- **Warn**: "It is important to consider security in modern systems.
  Security plays a key role in any deployment. Without security,
  systems may be vulnerable." (three sentences, one idea, no specifics)
- **Severe**: an entire intro section that defines the field, asserts
  the field is important, names well-known categories of work in the
  field, and concludes with "This paper presents work in this field"
  — no actual content yet

## What the mechanical layer cannot tell you

The mechanical analyzer flags throat-clearing phrases (D2.8) and
hedging clutter (D2.7), both of which often *coincide* with obvious
claims, but neither measures the underlying signal. A sentence can be
free of throat-clearing phrases and still be substantively obvious
("Performance is important."). Conversely, a sentence with throat-
clearing can still deliver real information once you mentally strip
the prefix. Judge from the informational delta of each sentence.
