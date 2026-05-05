# Merged-output schema (v0.1.0)

This is the final structured output the skill produces, combining the
mechanical analysis (`schema-mechanical.md`) and the LLM evaluation
(`schema-llm.md`) into a single artifact for downstream consumers.

The merged output has a single `findings` block keyed by sub-dimension
code, where each entry has a uniform shape regardless of whether the
finding came from the mechanical analyzer or the LLM phase. A small
`source` field tells the consumer where the finding came from.

## Top-level structure

```json
{
  "schema_version": "0.1.0",
  "phase": "merged",
  "meta": { ... },
  "document": { ... },
  "calibration": { ... },
  "readability": { ... },
  "structure": { ... },
  "findings": {
    "D1.1": { "source": "mechanical", ... },
    "D1.2": { "source": "llm",        ... },
    "D1.4": { "source": "mechanical", ... },
    "D1.5": { "source": "llm",        ... },
    "D1.6": { "source": "mechanical", ... },
    "D2.1": { "source": "mechanical", ... },
    "D2.2": { "source": "mechanical", ... },
    "D2.3": { "source": "mechanical", ... },
    "D2.4": { "source": "mechanical", ... },
    "D2.5": { "source": "llm",        ... },
    "D2.7": { "source": "mechanical", ... },
    "D2.8": { "source": "mechanical", ... },
    "D3.1": { "source": "mechanical", ... },
    "D3.3": { "source": "mechanical", ... },
    "D3.4": { "source": "mechanical", ... },
    "D3.5": { "source": "mechanical", ... },
    "D4.1": { "source": "mechanical", ... },
    "D4.2": { "source": "llm",        ... },
    "D4.3": { "source": "llm",        ... },
    "D4.4": { "source": "mechanical", ... }
  },
  "axis_summary": {
    "direction": { "score": "severe", "contributing_codes": ["D1.1", "D1.4"] },
    "density":   { "score": "warn",   "contributing_codes": ["D2.7", "D2.8"] },
    "texture":   { "score": "warn",   "contributing_codes": ["D3.3"] },
    "surprise":  { "score": "severe", "contributing_codes": ["D4.4"] }
  }
}
```

20 sub-dimensions total: 15 mechanical + 5 LLM. The 5 deferred entries
that appeared in the mechanical output's `deferred_to_llm` block are
removed at the merge step (they're now resolved by the LLM phase) so
the consumer sees one consistent block.

## `meta`, `document`, `calibration`, `readability`, `structure`

All copied verbatim from the mechanical output.

## `findings` entries

Uniform shape regardless of source:

```json
{
  "source": "mechanical | llm",
  "code": "D1.1",
  "name": "Buried thesis",
  "axis": "direction",
  "score": "pass | warn | severe",
  "rationale": "...",

  // Mechanical-only fields:
  "metric_name": "position_of_first_claim_pct",
  "metric_value": 0.7977,
  "threshold_warn": 0.05,
  "threshold_severe": 0.15,
  "measurements": { ... },
  "flags": [ ... ],

  // LLM-only fields:
  "evidence": [ { "quote": "...", "comment": "..." }, ... ],
  "confidence": "low | medium | high"
}
```

Mechanical findings keep their full `summary` / `measurements` / `flags`
detail (lifted into the top level of the entry). LLM findings keep
their `evidence` and `confidence` fields.

## `axis_summary`

Aggregates per-axis scores. The aggregation rule:

- **severe** — any sub-dimension on this axis scored `severe` (and is
  not a genre-gated `pass`)
- **warn** — no severes, but at least one sub-dimension scored `warn`
- **pass** — all sub-dimensions scored `pass`

`contributing_codes` lists the sub-dimensions whose score determined
the axis verdict (i.e., the severes if the axis is severe, the warns
if the axis is warn). LLM `pass`-with-`high`-confidence entries that
are genre-gated do *not* appear in `contributing_codes`.

## Why merge

The mechanical analyzer runs as a script and emits JSON; the LLM
phase produces JSON in the host LLM's response. Without a merge step,
downstream consumers (synthesis, presentation) would have to read two
different schemas and reconcile them. The merged schema is the single
contract those consumers depend on.

## Versioning

`schema_version` follows semver. Same policy as the mechanical and LLM
schemas. The merger should refuse to combine outputs whose
`schema_version` major numbers differ from its own.
