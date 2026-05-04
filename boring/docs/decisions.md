# Design Decisions Log

Short notes on choices made during development. Date-ordered. Add to the top when making new decisions.

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
