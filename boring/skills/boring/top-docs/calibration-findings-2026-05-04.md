# Calibration findings — 2026-05-04 (first run)

First labeled-corpus calibration run for the mechanical analysis layer.
The headline result: **the corpus and the checks are not measuring the
same thing**, so we are *not* updating `calibration.toml` from this run.
Recording the findings here so the next round of calibration starts from
a clear baseline rather than re-discovering them.

## What we ran

- **Corpus**: 30 documents in `calibration/{boring,not-boring}/` (20
  labeled boring, 10 labeled not-boring), drawn from infosec literature
  — academic papers, threat reports, NIST/PCI/CC standards, plus 11
  additional academic papers in `boring/additional/`.
- **Tooling**:
  - `calibration/run_corpus.py` — runs the analyzer over every doc with
    `genre=technical_report` (the closest existing profile), writes
    `calibration/results.csv` (one row per doc × sub-dimension)
  - `calibration/run_one.py` — re-runs a single doc and patches its
    rows in place (used to re-process NIST 800-53 after raising
    `nlp.max_length`)
  - `calibration/analyze_results.py` — per-check separability analysis
    (AUC by Mann-Whitney U, Youden's J best-threshold), writes
    `calibration/recommendations.md`
- **Outputs** (gitignored along with the corpus): `calibration/results.csv`,
  `calibration/recommendations.md`

## Headline numbers

AUC = `P(boring metric ranks worse than not-boring)`. 0.5 = chance; ≥
0.65 = useful; ≥ 0.80 = strong.

| Code | Name | AUC | Verdict |
|---|---|---|---|
| D3.5 | Vocabulary flatness | 0.70 | useful |
| D2.2 | Nominalization fog | 0.68 | useful |
| D2.4 | Subject-verb separation | 0.64 | weak |
| D4.1 | No concrete examples | 0.60 | weak |
| D3.3 | Opener monotony | 0.59 | weak |
| D2.3 | Passive overhang | 0.55 | low signal |
| D2.1 | Padding / wordiness | 0.53 | low signal |
| D1.4 | No signposting | 0.50 | low signal |
| D1.6 | Topic-position drift | 0.49 | low signal |
| D2.8 | Throat-clearing | 0.48 | low signal |
| D3.4 | Paragraph monotony | 0.40 | low signal |
| D4.4 | No specificity | 0.34 | inverted |
| D1.1 | Buried thesis | 0.31 | inverted |
| D2.7 | Hedging clutter | 0.24 | inverted |
| D3.1 | Sentence-length monotony | 0.17 | inverted |

Three observations stand out:

1. **Only 2 of 15 checks separate the classes at AUC ≥ 0.65.** D3.5
   vocabulary flatness and D2.2 nominalization fog are the survivors.
2. **Four checks are inverted** (D3.1, D2.7, D1.1, D4.4 — AUC < 0.5):
   the boring-labeled documents score *better* than the not-boring ones
   on those metrics.
3. **The remaining 9 checks cluster around AUC 0.5** — no usable signal
   in this corpus.

## Why this happened

The corpus is **not the corpus the checks were designed for.** The
checks target *technical business writing* — executive briefs, RFCs,
status updates, finding writeups, architecture docs, proposals. The
corpus is *infosec literature*: cryptography papers, threat reports,
formal standards.

That mismatch produces predictable inversions:

- **D1.1 buried thesis (AUC 0.31)** — the "boring" papers in this
  corpus are mostly standards (NIST, PCI, FIPS, CC) which are *required*
  to announce their scope and applicability up front, so they front-load
  claim-shaped sentences. The "not-boring" papers are narrative threat
  reports and exploit walkthroughs that genuinely build to a punchline
  (e.g., Trusting Trust holds the reveal until the end). The check is
  measuring the right thing; the corpus rewards the opposite.
- **D2.7 hedging clutter (AUC 0.24)** — standards documents say "shall"
  and "must" without hedging because that's the regulatory register.
  Threat reports hedge appropriately ("the malware appears to...", "we
  assess with high confidence that..."). On business writing this
  inversion would not appear.
- **D1.1 / D4.4 / D3.1 inversions** all share that pattern: standards
  writing follows a prose-mechanics discipline that scores well on
  surface metrics, while engaging narrative writing legitimately
  violates those metrics in service of pacing.

## What we believe instead

We have a small, mostly negative result. What it does and does not
support:

- **Does not support**: changing any threshold in `calibration.toml`.
  The corpus does not represent the genres the thresholds describe.
- **Does support**: D3.5 (vocabulary flatness) and D2.2 (nominalization
  fog) probably are genuinely genre-independent signals — they showed
  modest separability even on the wrong corpus.
- **Suggests**: D1.1 (buried thesis) detection might be too narrow.
  Standards docs match our claim patterns ("we recommend", "this
  document specifies") at the very top, while papers with strong
  narrative arcs delay until the conclusion. Both are valid prose
  strategies; flagging "early claim" as universally good is wrong. A
  follow-up worth investigating: weight the position by genre profile
  more aggressively, or fold "presence of summary-section heading"
  into the score more heavily.

## What we need next

A corpus of **business technical writing** — executive briefs, RFCs,
status updates, finding writeups, architecture docs, proposals — with
labels at the per-dimension level (Direction good/bad, Density
good/bad, Texture good/bad, Surprise good/bad). Realistically this
corpus does not exist publicly; it has to be assembled internally
(documents from real engineering / leadership writing inside an
organization) with hand labels from people who know the genre.

Until that corpus exists, the thresholds in `calibration.toml` should
remain marked `intuitive_defaults_uncalibrated` (status field in the
TOML's `[meta]` block).

## Files preserved

- `calibration/run_corpus.py`, `calibration/run_one.py`,
  `calibration/analyze_results.py` — the calibration tooling, in the
  repo
- `calibration/results.csv`, `calibration/recommendations.md` — the
  outputs of this run, gitignored along with the corpus
- The corpus itself — gitignored under `boring/calibration/`
