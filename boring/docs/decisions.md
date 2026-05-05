# Design Decisions Log

Short notes on choices made during development. Date-ordered. Add to the top when making new decisions.

---

## 2026-05-04 — PDF support

### pypdf, no OCR, no PDF heading detection

Library: **pypdf** (MIT, pure-Python, no native deps). Considered
pdfminer.six (more layout-aware, slower), pymupdf (best quality but
AGPL — incompatible with downstream repackaging), and pdfplumber
(table-oriented, we don't need tables). pypdf is good enough for the
typical business-PDF corpus we'd label for calibration; we can swap if
extraction quality becomes a corpus problem.

**Image-only / scanned PDFs hard-fail** with a clear ValueError. OCR is a
v2 decision — adding tesseract or ocrmypdf would be significant scope
creep for a niche of input documents.

**No heading extraction from PDFs.** PDF has no reliable heading model
and pypdf doesn't expose font sizes well. Heuristic detection (short
lines surrounded by blank lines, all-caps lines) was considered and
rejected as too noisy. Consequence: D1.4 (signposting) yields "no
boundaries to evaluate" on most PDFs — a known false negative we accept
in exchange for not misleading the other Direction-axis checks with
wrong heading detection.

### page_number in the Locator schema

The `Locator` dataclass gains an optional `page_number` field
(1-indexed) and `page_number_end` (only emitted when a span crosses a
page). Populated for PDF source only; omitted from the JSON output for
all other formats. This is a backwards-compatible minor-version bump
per the schema versioning policy.

The page-number lookup uses a side table on `Document.page_boundaries`
— a list of `(char_start, char_end, page_number)` tuples built during
parse. `Document.page_number_for_offset(offset)` does the lookup; the
locator helpers call it automatically. No check code needs to know
about pages.

### Page join with `\n\n`

PDF pages are joined with `\n\n` so paragraph segmentation works
naturally across page breaks (a paragraph that wraps from page 1 to
page 2 is still one paragraph). This does mean the last paragraph of
one page and first of the next sometimes get merged when a writer
deliberately splits them at page breaks — but in business PDFs the
page break is usually a layout decision, not a paragraph-boundary
decision, so this is the right default.

---

## 2026-05-04 — Direction-axis checks (D1.1, D1.4, D1.6)

### D1.1 buried thesis: claim detection is conservative

A sentence is "claim-shaped" if it (a) opens with a strong claim phrase
("we recommend", "this document concludes", "TL;DR"), (b) has a "we"
subject + a claim verb (recommend / propose / find / argue / ...), or
(c) has an obligation modal (must / should / ought to) with a real
(non-expletive) subject. Expletive-subject sentences ("It is critical
that...") are deliberately *not* counted — they're meta-commentary that
D1.6 already flags.

Trade-off: high precision, low recall. A writer can make a strong claim
with phrasing none of these patterns catch (e.g., "Database X is the
right choice"). The LLM phase is the right place for residual judgment;
the mechanical check just answers "is there an obvious BLUF?" which is
the question BLUF doctrine actually cares about.

A summary/recommendation/TL;DR heading near the top of the document
(within the first ~10% by char) softens the score by one level: the
document is structurally signaling its claim location even when
sentence-level patterns don't match.

### D1.4 signposting: only top-level boundaries are evaluated

Section transitions matter most at the level-1 (top-level) heading
boundaries. Sub-heading boundaries (`##`, `###`) often don't need an
explicit transition because they live inside a flow that's already
established. We evaluate only level-1 boundaries; if a doc has none, we
fall back to all headings.

Roadmap detection is a phrase lookup ("this document covers", "the
following sections", "we begin by", ...) plus a regex hint for
enumeration ("first ... then ... finally ..."). Whether a roadmap is
*required* is genre-dependent (per `checks_required.roadmap` in the
calibration profile).

### D1.6 topic-position drift: continuity is a soft proxy

Subject-continuity scoring is unavoidably rough — a sentence's subject
"links back" to the prior sentence if it's a pronoun, or its lemma
appears among the prior sentence's content lemmas. This misses synonyms
and paraphrases; it over-counts incidental lemma overlap. The threshold
on the average score (`warn_mean_continuity_below = 0.40`) is the
calibration item most in need of corpus tuning.

Expletive-subject detection is reliable: spaCy's `expl` dep tag plus a
custom rule for "It is X" / "It was Y" with a copular head verb covers
the cases that matter.

---

## 2026-05-04 — Texture-axis checks (D3.3, D3.4, D3.5)

### D3.4 filters out heading-only paragraphs

The markdown parser segments `# Background` lines into their own
"paragraphs" with word count 1. Counting them in the paragraph-length
distribution distorts the CV. D3.4 filters them via a regex
(`^\s*#{1,6}\s+...`) before computing stats. Other checks may want
to do the same — there's no shared `body_paragraphs` helper yet
because only D3.4 needs it so far.

### D3.5 uses lemmas for MATTR

MATTR is computed over content-word *lemmas* (NOUN/PROPN/VERB/ADJ/ADV)
rather than surface forms. Reason: "system / systems" should count as
one type, not two — the writer hasn't varied vocabulary by inflecting
the same word.

---

## 2026-05-04 — Mechanical checks expansion

### proselint integration: keep our own lists for hedging and weasel words

We integrate proselint (v0.16) for D2.1 padding/wordiness because it bundles
the long tail of Garner/Strunk/Pinker/Norris phrase lists we don't want to
re-curate. But we **disable proselint's `hedging` and `weasel_words` checks**
in our wrapper because:

- Our `HEDGE_WORDS` / `HEDGE_PHRASES` (D2.7) detect *stacked* hedges in a
  single sentence — the actually-actionable signal — which proselint can't
  do because it operates at phrase granularity, not sentence granularity.
- Our `VAGUE_QUANTIFIERS` / `VAGUE_INTENSIFIERS` / `VAGUE_MODIFIERS` (D4.4)
  are categorized so the measurement breakdown is meaningful; proselint's
  `weasel_words` returns flat hits.
- Otherwise the same span would get flagged by two checks, confusing the
  downstream LLM phase.

D2.1 also carries a small `SUPPLEMENTAL_WORDY` list for high-frequency
business-writing phrases proselint misses ("due to the fact that", "in
order to", "with regard to", etc.). Supplemental hits that overlap a
proselint hit are dropped (proselint's message is richer).

### proselint 0.16 has off-by-one spans

In v0.16 the spans returned by `LintFile.lint()` are shifted +1 on both
ends — `(span.start - 1, span.end - 1)` is what indexes the input. Our
wrapper compensates so callers get spans that index the original text
directly. If we upgrade proselint past 0.16 this needs re-verifying.

### proselint 0.16 also requires manual registry population

Importing `proselint.checks` in 0.16 only *builds* the check tuple; the
singleton `CheckRegistry()` is left empty until the CLI runs. Our wrapper
calls `CheckRegistry().register_many(__register__)` once on first use.

---

## 2026-05-04 — v0.1.0 scaffold

### Taxonomy: four axes (Direction / Density / Texture / Surprise)

Grounded in Westgate & Wilson's MAC model of boredom (Psychological Review 2018) plus craft traditions (Gopen-Swan, Williams, Provost, Minto). Direction = MAC meaning component. Density and Texture = MAC attentional component (over- and under-stimulation poles). Surprise is cross-cutting.

23 sub-dimensions total. 18 are mechanically computable (with varying confidence); 5 are LLM-only.

### Calibration in a separate TOML file

Reasons:
- Thresholds will change as we gather corpus data; we want one-file edits.
- Genre profiles (executive_brief, architecture_doc, etc.) belong with thresholds, not with code.
- TOML beats JSON because it allows comments, and the comments document *why* a threshold is what it is.
- Python's stdlib `tomllib` (3.11+) parses it natively.

Genre profiles are deltas on `[default]`, listing only what differs. This keeps the file readable.

### Locators: composite, with hashes

Every span finding carries char offsets, line/col, sentence and paragraph indices, section path, SHA-256 of the span text, a preview, and small context windows. The hash is the integrity check for re-runs after document edits — mismatch = stale finding.

For .docx, char/line refer to extracted normalized text, not the .docx archive. `paragraph_index` and `text_preview` are the primary navigation aids.

### Schema: grouped by sub-dimension

Each sub-dimension owns its block in `findings`. Each block has three tiers: `summary` (the score), `measurements` (raw numbers), `flags` (span-level findings). Different checks emit different combinations.

Light support for incremental re-runs: hashes and timestamps present, but no formal diff machinery. A future tool can compute diffs externally.

### Three-tier confidence per check

- *measurement*: facts (numbers, distributions) — always present
- *flag*: a candidate span for LLM review — present where applicable
- *score*: severity against thresholds (pass/warn/severe) — present for checks with thresholds

Reporting caps in `[reporting]` block of calibration: 25 flags per check, 200 total. Severity-then-position selection.

### Extensibility: check registry

Each check is a class registered into a module-level dict at import time. The pipeline iterates the registry in code-sorted order. Adding a new check = drop a file, register, import. No edits anywhere else.

### Input formats: markdown, plaintext, docx

PDF deferred — the offset/locator complexity isn't worth it in v1.

### Readability: report but don't score

textstat is wired in for Flesch, FK grade, Gunning Fog, SMOG, Dale-Chall, ARI. Document-level plus per-longest-paragraph (variance is more interesting than the mean for spotting overload pockets). These are descriptive only and not used in any check's scoring.

### Versioning policy

`schema_version` follows semver. Adding sub-dimensions or fields = minor bump. Removing or renaming = major bump. Consumers iterate dicts, never assume positional structure.

### What's deliberately *not* in the schema

- Recommendations (later phase)
- Prioritization (later phase)
- Natural-language summary (synthesis phase)
- LLM judgments (separate schema, to be designed)
- Diff against prior runs (computable externally from hashes)
