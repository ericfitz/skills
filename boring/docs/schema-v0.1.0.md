# Boring-Writing Skill — Mechanical Analysis Output Schema (v1)

This document specifies the JSON output produced by the mechanical analysis script. The schema is the contract between the script and downstream phases (LLM evaluation, synthesis, recommendations, presentation).

## Design principles

1. **Grouped by sub-dimension.** Top-level findings are keyed by sub-dimension code (D1.1, D2.3, etc.) so each check has its own bucket with summary metrics and individual findings.
2. **Composite locators on every span finding.** Multiple redundant fields enable navigation, verification, and stale detection.
3. **Light diff support.** Document digest, run timestamp, and per-finding text hashes are present so a future tool could diff runs, but no formal incremental machinery is built.
4. **Active thresholds echoed into output.** Whatever calibration values the script used are recorded, so the report is reproducible and self-documenting.
5. **Three confidence tiers per check.** Each sub-dimension can produce *measurements* (facts), *flags* (candidate spans for LLM review), and *scores* (summary judgments against thresholds).

## Top-level structure

```json
{
  "schema_version": "0.1.0",
  "meta": { ... },
  "document": { ... },
  "calibration": { ... },
  "readability": { ... },
  "structure": { ... },
  "findings": {
    "D1.1": { ... },
    "D1.4": { ... },
    "D1.6": { ... },
    "D2.1": { ... },
    "D2.2": { ... },
    "D2.3": { ... },
    "D2.4": { ... },
    "D2.7": { ... },
    "D2.8": { ... },
    "D3.1": { ... },
    "D3.3": { ... },
    "D3.4": { ... },
    "D3.5": { ... },
    "D4.4": { ... }
  },
  "deferred_to_llm": [ ... ]
}
```

## `meta` — run metadata

Identifies this run for traceability and future diffing.

```json
{
  "run_id": "uuid-v4-string",
  "run_timestamp_utc": "2026-05-04T18:23:11Z",
  "skill_version": "0.1.0",
  "script_version": "0.1.0",
  "spacy_model": "en_core_web_sm-3.8.0",
  "spacy_version": "3.8.2",
  "proselint_version": "0.14.0",
  "textstat_version": "0.7.4",
  "python_version": "3.11.7"
}
```

The `spacy_model` field is critical — sentence segmentation can vary across model versions, which affects `sentence_index` values. Pin the model in the calibration file and record what was actually used here.

## `document` — what was analyzed

```json
{
  "source_path": "/path/to/input.md",
  "source_format": "markdown | plaintext | docx",
  "source_bytes": 48201,
  "source_sha256": "sha256:9f1c...",
  "extracted_text_sha256": "sha256:b2e4...",
  "char_count": 47892,
  "line_count": 612,
  "paragraph_count": 84,
  "sentence_count": 412,
  "word_count": 9847,
  "declared_genre": "executive_brief | architecture_doc | technical_report | finding_writeup | proposal | rfc | status_update | other | null",
  "genre_source": "user_declared | llm_inferred | default"
}
```

Two hashes: `source_sha256` is the raw input file (lets us detect if the file changed at all); `extracted_text_sha256` is the normalized text the script actually analyzed (for .docx this differs; for markdown/plaintext usually the same modulo line endings).

`declared_genre` is what the skill prompt determines from the LLM's classification or user declaration before invoking the script. The script uses it to select the calibration profile.

## `calibration` — what thresholds were active

Echoes the resolved (post-override) calibration so every threshold cited in the report can be traced back.

```json
{
  "calibration_file_sha256": "sha256:1a2b...",
  "genre_profile_applied": "executive_brief",
  "active_thresholds": {
    "density.subject_verb_gap.warn_token_distance": 7,
    "density.subject_verb_gap.severe_token_distance": 12,
    "density.passive_rate.warn_ratio": 0.15,
    "density.passive_rate.severe_ratio": 0.30,
    "...": "..."
  }
}
```

## `readability` — descriptive only, never used for scoring

```json
{
  "document": {
    "flesch_reading_ease": 38.2,
    "flesch_kincaid_grade": 14.1,
    "gunning_fog": 16.3,
    "smog_index": 14.0,
    "dale_chall": 9.8,
    "automated_readability_index": 14.5
  },
  "longest_paragraphs": [
    {
      "paragraph_index": 12,
      "word_count": 287,
      "flesch_reading_ease": 24.1,
      "flesch_kincaid_grade": 19.2,
      "locator": { ... }
    }
  ]
}
```

Per-paragraph scores are computed for, say, the top 10 longest paragraphs — variance across the document is more interesting than the document-level mean.

## `structure` — document-shape summary

Document-wide measurements that are useful context for many findings, not specific to one check.

```json
{
  "headings": [
    {
      "level": 1,
      "text": "Recommendation",
      "locator": { ... },
      "shape": "claim | nominal | mixed",
      "child_paragraph_indices": [3, 4, 5, 6]
    }
  ],
  "paragraph_lengths_words": [42, 58, 31, ...],
  "sentence_lengths_words": [18, 22, 14, ...],
  "sentence_lengths_stats": {
    "mean": 21.3,
    "median": 20.0,
    "stdev": 7.4,
    "coefficient_of_variation": 0.35,
    "p10": 12,
    "p90": 32
  },
  "first_claim_position": {
    "found": true,
    "sentence_index": 14,
    "char_offset": 1823,
    "claim_type": "recommendation | finding | thesis",
    "locator": { ... }
  }
}
```

`headings.shape` classifies headings as **claim** ("Why we should adopt X"), **nominal** ("Architecture"), or **mixed** ("Architecture: Adopting X"). High nominal-heading ratio is a signal for D1.3 (no forward motion).

`first_claim_position` is computed by detecting first-person plural recommendation patterns ("we recommend / we propose / we conclude / we find"), modal-of-obligation patterns ("must / should"), and explicit thesis markers near the start. Where this falls in the document is a primary signal for D1.1 (buried thesis).

## `findings` — per-sub-dimension results

Each entry has the same shape:

```json
{
  "code": "D2.3",
  "name": "Passive overhang",
  "axis": "density",
  "checked": true,
  "summary": {
    "metric_name": "passive_sentence_ratio",
    "metric_value": 0.41,
    "threshold_warn": 0.25,
    "threshold_severe": 0.40,
    "score": "severe | warn | pass",
    "rationale": "41% of sentences use passive voice; threshold for severe is 40%."
  },
  "measurements": {
    "passive_sentence_count": 169,
    "total_sentence_count": 412,
    "passive_sentence_ratio": 0.41,
    "agentless_passive_count": 142
  },
  "flags": [
    {
      "flag_id": "D2.3-001",
      "severity": "warn | severe | info",
      "message": "Passive voice with omitted agent",
      "locator": { ... },
      "evidence": {
        "passive_aux": "was",
        "passive_verb": "performed",
        "agent_present": false
      }
    }
  ],
  "notes": []
}
```

Three tiers visible:
- `summary` — the document-level score for this check
- `measurements` — the raw numbers behind the score
- `flags` — individual span-level findings the LLM should review

Some checks produce only summary + measurements (e.g., D3.1 sentence-length monotony — there's nothing to flag at span level). Some produce only flags (e.g., D2.8 throat-clearing — every match is a flag, no meaningful aggregate score). Most produce both.

`checked: false` is used when the check is gated off by the genre profile (e.g., D1.5 flat tension is not checked for a runbook).

## Locator schema

The composite locator. Every span finding carries one.

```json
{
  "scope": "span | section | paragraph | document",

  "char_start": 12453,
  "char_end": 12491,

  "line_start": 47,
  "line_col_start": 12,
  "line_end": 47,
  "line_col_end": 50,

  "sentence_index_start": 142,
  "sentence_index_end": 142,
  "paragraph_index": 38,
  "section_path": ["3. Recommendation", "3.2 Cost analysis"],

  "text_sha256": "sha256:a3f1...8b2c",
  "text_preview": "An analysis of the results was performed by the team",
  "context_before": "...prior to deployment. ",
  "context_after": " across all three regions."
}
```

Behavior across source formats:

- **Markdown / plaintext**: all fields populated. `char_start/end` and `line_start/end` are into the source file directly.
- **docx**: `char_start/end` and `line_start/end` are into the *extracted normalized text*, not the .docx archive. `paragraph_index` is the primary navigation aid for the writer. `text_preview` lets them search for the span in Word.
- **pdf**: `char_start/end` and `line_start/end` are into the *extracted normalized text* (page text joined with `\n\n`). `page_number` (1-indexed) is the primary navigation aid; `page_number_end` is emitted only when the span crosses a page. Headings are not extracted from PDFs (PDF has no reliable heading model), so `section_path` is always empty.

PDF-specific locator fields:

- `page_number`: 1-indexed page where the span starts. Emitted only for PDF source.
- `page_number_end`: 1-indexed page where the span ends. Emitted only when the span crosses pages (different from `page_number`).

`scope` distinguishes:
- `"span"` — a specific token range; all locator fields populated.
- `"paragraph"` — entire paragraph; `char_start/end` and `paragraph_index` populated, no sub-paragraph fields.
- `"section"` — entire section; `section_path` populated, char range covers all section content.
- `"document"` — whole-document finding; only `text_sha256` of the whole extracted text and basic metadata.

`text_sha256` is the SHA-256 of the exact bytes in the span. On re-run, downstream code can verify a finding still applies by re-hashing at the (possibly shifted) offsets. Mismatch = stale, the LLM phase should re-evaluate rather than blindly accept.

## `deferred_to_llm` — sub-dimensions the script does not check

```json
[
  {
    "code": "D1.2",
    "name": "Missing stakes",
    "axis": "direction",
    "reason": "semantic_judgment_required",
    "hints": {
      "stakes_words_in_intro": ["risk", "cost"],
      "stakes_words_in_conclusion": []
    }
  },
  {
    "code": "D1.5",
    "name": "Flat tension",
    "axis": "direction",
    "reason": "semantic_judgment_required",
    "hints": {
      "problem_word_density_per_paragraph": [0.0, 0.02, 0.0, ...],
      "contrast_marker_count": 3
    }
  }
]
```

These are the four LLM-only sub-dimensions from our earlier evaluation: **D1.2 missing stakes, D1.5 flat tension, D4.2 no vivid imagery, D4.3 no counterintuitive claims**, plus **D2.5 obvious claims** which we deferred to v2.

The `hints` field carries any cheap signals the script can compute that *might* help the LLM — but the LLM is doing the actual judgment. Hints are optional and explicitly described as suggestive, not authoritative.

## Per-sub-dimension specifics

What each `findings.D*.*` entry contains specifically. Listed in v1-priority order.

### D2.3 Passive overhang
- **Summary metric**: `passive_sentence_ratio`
- **Measurements**: passive sentence count, agentless passive count, total sentence count
- **Flags**: every passive sentence with locator, severity by whether agent is omitted

### D2.4 Subject-verb separation
- **Summary metric**: `mean_subject_verb_gap`, `max_subject_verb_gap`, `pct_sentences_over_warn_threshold`
- **Measurements**: per-sentence S-V gap distribution
- **Flags**: every sentence above warn threshold, severity at severe threshold

### D2.7 Hedging clutter
- **Summary metric**: `hedges_per_100_sentences`, `stacked_hedge_sentences_count`
- **Measurements**: total hedge count, breakdown by hedge type
- **Flags**: sentences with stacked hedges (≥2)

### D2.8 Throat-clearing
- **Summary metric**: `throat_clearing_phrase_count`
- **Measurements**: counts by category (sentence-opener vs paragraph-opener vs mid-sentence)
- **Flags**: every match with locator and matched phrase

### D2.1 Padding / wordiness
- **Summary metric**: `wordy_phrase_count_per_1000_words`
- **Measurements**: counts from proselint by check_path, plus our own counts
- **Flags**: every wordy-phrase match

### D2.2 Nominalization fog
- **Summary metric**: `nominalizations_per_sentence`, `light_verb_nominalization_count`
- **Measurements**: nominalization suffix breakdown, "to be" main-verb ratio
- **Flags**: every light-verb + nominalization construction (highest-precision pattern)

### D3.1 Sentence-length monotony
- **Summary metric**: `coefficient_of_variation`, `longest_similar_length_run`
- **Measurements**: full sentence-length distribution stats, runs of consecutive sentences within ±20% of each other
- **Flags**: locators for the longest similar-length runs

### D3.3 Opener monotony
- **Summary metric**: `first_token_entropy`, `longest_same_opener_run`
- **Measurements**: opener distribution (first token, first POS, first 2-grams)
- **Flags**: locators for the longest same-opener runs

### D3.4 Paragraph monotony
- **Summary metric**: `paragraph_length_coefficient_of_variation`
- **Measurements**: paragraph length distribution, longest run of similar-length paragraphs
- **Flags**: none typically; this is an aggregate finding

### D3.5 Vocabulary flatness
- **Summary metric**: `mattr` (moving-average type-token ratio), `verb_diversity_ratio`
- **Measurements**: most-repeated content lemmas, most-repeated verb lemmas
- **Flags**: top 10 over-used verbs/nouns with their counts (no spans — this is a document property)

### D4.4 No specificity
- **Summary metric**: `vague_quantifier_density_per_1000_words`
- **Measurements**: counts of vague quantifier instances by category
- **Flags**: every vague-quantifier match

### D1.6 Topic-position drift
- **Summary metric**: `expletive_subject_ratio`, `mean_subject_continuity_score`
- **Measurements**: per-sentence subject lemmas, expletive-subject count, paragraph-level subject-continuity scores
- **Flags**: sentences with expletive subjects ("It is...", "There are..."); paragraphs with low subject continuity

### D1.4 No signposting
- **Summary metric**: `transition_marker_density_at_section_boundaries`
- **Measurements**: roadmap detection in intro (yes/no, with locator if found), transition marker counts at section boundaries
- **Flags**: section boundaries lacking transitions

### D1.1 Buried thesis
- **Summary metric**: `position_of_first_claim_pct` (where in document, by char offset, the first claim-shaped sentence appears)
- **Measurements**: positions of all detected claim-shaped sentences (recommendations, findings, theses); presence of summary section near top
- **Flags**: first claim location, with assessment of whether it's "buried" given genre profile

### D1.3 No forward motion (low priority — can be deferred to v1.5)
- **Summary metric**: `nominal_heading_ratio`, `descriptive_to_claim_sentence_ratio`
- **Measurements**: heading shape distribution, paragraph-final sentence type distribution
- **Flags**: paragraphs ending without a clear "so what"

## Example: minimal but complete output

A truncated example showing a real document with two findings:

```json
{
  "schema_version": "0.1.0",
  "meta": {
    "run_id": "01HXYZ...",
    "run_timestamp_utc": "2026-05-04T18:23:11Z",
    "skill_version": "0.1.0",
    "script_version": "0.1.0",
    "spacy_model": "en_core_web_sm-3.8.0",
    "spacy_version": "3.8.2",
    "proselint_version": "0.14.0",
    "textstat_version": "0.7.4",
    "python_version": "3.11.7"
  },
  "document": {
    "source_path": "/tmp/proposal.md",
    "source_format": "markdown",
    "source_bytes": 4821,
    "source_sha256": "sha256:9f1c...",
    "extracted_text_sha256": "sha256:9f1c...",
    "char_count": 4821,
    "line_count": 78,
    "paragraph_count": 12,
    "sentence_count": 47,
    "word_count": 982,
    "declared_genre": "executive_brief",
    "genre_source": "llm_inferred"
  },
  "calibration": {
    "calibration_file_sha256": "sha256:1a2b...",
    "genre_profile_applied": "executive_brief",
    "active_thresholds": {
      "density.passive_rate.warn_ratio": 0.15,
      "density.passive_rate.severe_ratio": 0.30,
      "density.subject_verb_gap.warn_token_distance": 7,
      "texture.sentence_length.warn_max_run": 6
    }
  },
  "readability": {
    "document": {
      "flesch_reading_ease": 38.2,
      "flesch_kincaid_grade": 14.1,
      "gunning_fog": 16.3,
      "smog_index": 14.0,
      "dale_chall": 9.8
    },
    "longest_paragraphs": []
  },
  "structure": {
    "headings": [
      {
        "level": 1,
        "text": "Background",
        "shape": "nominal",
        "locator": {
          "scope": "span",
          "char_start": 0,
          "char_end": 13,
          "line_start": 1,
          "line_col_start": 1,
          "line_end": 1,
          "line_col_end": 13,
          "sentence_index_start": 0,
          "sentence_index_end": 0,
          "paragraph_index": 0,
          "section_path": ["Background"],
          "text_sha256": "sha256:c4d5...",
          "text_preview": "# Background",
          "context_before": "",
          "context_after": "\n\nIn recent years"
        },
        "child_paragraph_indices": [1, 2, 3]
      }
    ],
    "sentence_lengths_stats": {
      "mean": 24.8,
      "median": 23.0,
      "stdev": 6.1,
      "coefficient_of_variation": 0.246,
      "p10": 18,
      "p90": 33
    },
    "first_claim_position": {
      "found": true,
      "sentence_index": 38,
      "char_offset": 3892,
      "claim_type": "recommendation",
      "locator": { "...": "..." }
    }
  },
  "findings": {
    "D2.3": {
      "code": "D2.3",
      "name": "Passive overhang",
      "axis": "density",
      "checked": true,
      "summary": {
        "metric_name": "passive_sentence_ratio",
        "metric_value": 0.32,
        "threshold_warn": 0.15,
        "threshold_severe": 0.30,
        "score": "severe",
        "rationale": "32% of sentences use passive voice; threshold for severe in executive_brief profile is 30%."
      },
      "measurements": {
        "passive_sentence_count": 15,
        "agentless_passive_count": 12,
        "total_sentence_count": 47,
        "passive_sentence_ratio": 0.32
      },
      "flags": [
        {
          "flag_id": "D2.3-001",
          "severity": "warn",
          "message": "Agentless passive",
          "locator": {
            "scope": "span",
            "char_start": 412,
            "char_end": 478,
            "line_start": 8,
            "line_col_start": 1,
            "line_end": 8,
            "line_col_end": 67,
            "sentence_index_start": 4,
            "sentence_index_end": 4,
            "paragraph_index": 1,
            "section_path": ["Background"],
            "text_sha256": "sha256:7a8b...",
            "text_preview": "An analysis of the costs was performed prior to the decision.",
            "context_before": "...considered the alternatives. ",
            "context_after": " The results indicated..."
          },
          "evidence": {
            "passive_aux": "was",
            "passive_verb": "performed",
            "agent_present": false
          }
        }
      ],
      "notes": []
    },
    "D3.1": {
      "code": "D3.1",
      "name": "Sentence-length monotony",
      "axis": "texture",
      "checked": true,
      "summary": {
        "metric_name": "coefficient_of_variation",
        "metric_value": 0.246,
        "threshold_warn": 0.35,
        "threshold_severe": 0.20,
        "score": "warn",
        "rationale": "Sentence-length variation is below the warning threshold (CV 0.246 < 0.35). The longest run of similar-length sentences is 9 (warn at 6)."
      },
      "measurements": {
        "coefficient_of_variation": 0.246,
        "longest_similar_length_run": 9,
        "similar_length_runs_above_threshold": 3
      },
      "flags": [
        {
          "flag_id": "D3.1-001",
          "severity": "warn",
          "message": "Run of 9 sentences within ±20% of each other in length",
          "locator": {
            "scope": "span",
            "char_start": 1245,
            "char_end": 1893,
            "line_start": 22,
            "line_col_start": 1,
            "line_end": 28,
            "line_col_end": 89,
            "sentence_index_start": 18,
            "sentence_index_end": 26,
            "paragraph_index": 5,
            "section_path": ["Analysis"],
            "text_sha256": "sha256:e9f0...",
            "text_preview": "The system processes records in batches. The batches are sized to optimize throughput. The throughput depends on the available resources...",
            "context_before": "",
            "context_after": ""
          },
          "evidence": {
            "sentence_lengths_in_run": [22, 19, 21, 20, 23, 22, 21, 19, 20]
          }
        }
      ],
      "notes": []
    }
  },
  "deferred_to_llm": [
    {
      "code": "D1.2",
      "name": "Missing stakes",
      "axis": "direction",
      "reason": "semantic_judgment_required",
      "hints": {
        "stakes_words_in_intro": [],
        "stakes_words_in_conclusion": ["risk"]
      }
    }
  ]
}
```

## Versioning policy

- `schema_version` follows semver. Backward-compatible additions = minor version bump. Breaking changes = major version bump.
- Downstream phases (LLM evaluator, synthesizer) read `schema_version` first and refuse to process incompatible versions.
- New sub-dimensions added later are minor-version bumps as long as `findings` remains a dict (consumers should iterate over keys, not assume which keys exist).
- New fields *within* a finding entry are minor-version bumps; consumers should ignore unknown fields.

## What's deliberately NOT in the schema

- **Recommendations** — recommendations are generated by a later phase from this output; they're not part of the script's output.
- **Prioritization** — the script reports raw findings; downstream phases prioritize.
- **Natural-language summary text** — only structured data here. The synthesis phase generates prose.
- **Diff against a prior run** — even though we have hashes for it, there's no `prior_run_id` or `changes` field. A future tool can compute diffs externally if needed.
- **LLM judgments** — only mechanical and rule-based output. The LLM-evaluation phase produces its own structured output (separate schema, to be designed) which the synthesis phase merges with this one.
