# LLM-evaluation output schema (v0.1.0)

This is the structured output the host LLM produces during the
LLM-evaluation phase of the skill, after running the mechanical
analyzer (whose output is `schema-mechanical.md`) and applying the
five judge rubrics in `rubrics/`.

## Top-level structure

```json
{
  "schema_version": "0.1.0",
  "phase": "llm_evaluation",
  "document": {
    "source_path": "/path/to/input.md",
    "source_sha256": "sha256:9f1c...",
    "extracted_text_sha256": "sha256:b2e4...",
    "declared_genre": "executive_brief",
    "word_count": 982
  },
  "llm_findings": {
    "D1.2": { ... },
    "D1.5": { ... },
    "D2.5": { ... },
    "D4.2": { ... },
    "D4.3": { ... }
  }
}
```

The `document` block echoes the corresponding fields from the
mechanical output so a downstream consumer can verify both phases ran
on the same document.

## `llm_findings` entries

Each entry has the same shape:

```json
{
  "code": "D1.2",
  "name": "Missing stakes",
  "axis": "direction",
  "score": "pass | warn | severe",
  "rationale": "1-2 sentences explaining the judgment",
  "evidence": [
    { "quote": "verbatim substring of the document", "comment": "what this shows" },
    { "quote": "...", "comment": "..." }
  ],
  "confidence": "low | medium | high"
}
```

### Field semantics

- **`code`** — sub-dimension code from the taxonomy (`D1.2`, `D1.5`,
  `D2.5`, `D4.2`, `D4.3`). Exactly these five — no others.
- **`name`** — human-readable name, must match the rubric file's
  title.
- **`axis`** — one of `direction`, `density`, `surprise`. (None of the
  five are `texture`-axis.)
- **`score`** — one of three values, matching the mechanical layer's
  three-tier scheme:
  - `pass` — no real problem; the document does this aspect well or
    the dimension is not relevant to its genre/purpose
  - `warn` — noticeable weakness; would benefit from revision
  - `severe` — pervasive or critical failure
- **`rationale`** — one or two sentences explaining the judgment.
  Direct, specific, no lecturing.
- **`evidence`** — two to four short evidence quotes from the
  document, each with a one-line comment. **Quotes must be verbatim
  substrings of the document — never paraphrased or summarized.** If a
  quote is too long to include in full, use an ellipsis (`...`) for
  the elision; the surviving fragments must still be verbatim. The
  downstream consumer can grep for the quote text to locate the
  evidence in the source document.
- **`confidence`** — `low`, `medium`, or `high`. Use `low` when the
  document is too short or off-genre to judge reliably, or when the
  signals are mixed. Use `high` only when the evidence is unambiguous.

## Genre-gating

If a sub-dimension is not applicable to the document's declared genre
(e.g., D1.5 flat tension on a runbook, D4.3 counterintuitive claims
on a spec), the rubric instructs the LLM to score it `pass` with
`confidence: high` and explain in the rationale that the genre rules
this dimension out. The synthesis phase treats genre-gated `pass`
entries differently from substantive `pass` entries (it doesn't
celebrate them as wins; it acknowledges they were ruled out).

## Versioning

`schema_version` follows semver. Backward-compatible additions = minor
version bump. Breaking changes = major version bump. The synthesis
phase reads `schema_version` first and refuses to process incompatible
versions.
