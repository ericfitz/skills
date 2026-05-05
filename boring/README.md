# boring — Boring-Writing Detection Skill

A skill for evaluating technical business writing for "boringness" and proposing targeted improvements. Built around a four-axis taxonomy (Direction, Density, Texture, Surprise) grounded in psychology of boredom, psycholinguistics, and the technical-writing craft tradition.

## Status

**v0.1.0 — full mechanical layer complete.** All 15 mechanical checks across the four axes (Direction / Density / Texture / Surprise) are implemented, each registered into the pipeline and smoke-tested on the sample. Five LLM-only sub-dimensions are declared as deferred. The next phases — LLM evaluation, synthesis, and presentation — are not yet implemented.

## Repository layout

```
boring/
├── README.md                  # this file
├── calibration.toml           # all thresholds + per-genre profiles (edit to recalibrate)
├── pyproject.toml             # package metadata; install with `pip install -e .`
├── docs/
│   ├── research-report.md     # the research, taxonomy, and rubric sketch
│   ├── schema-v0.1.0.md       # mechanical-analyzer JSON output schema
│   └── decisions.md           # running log of design decisions
├── src/
│   └── analyzer/              # the Python package: mechanical-analysis script
│       ├── __main__.py        # CLI entry point
│       ├── pipeline.py        # orchestrator
│       ├── document.py        # parsing (md/txt/docx), spaCy caching
│       ├── locator.py         # composite-locator construction
│       ├── config.py          # calibration loading + genre overrides
│       ├── checks/            # one file per check, registered into the pipeline
│       │   ├── base.py
│       │   ├── d1_1_buried_thesis.py
│       │   ├── d1_4_signposting.py
│       │   ├── d1_6_topic_drift.py
│       │   ├── d2_1_padding.py
│       │   ├── d2_2_nominalization.py
│       │   ├── d2_3_passive.py
│       │   ├── d2_4_sv_gap.py
│       │   ├── d2_7_hedging.py
│       │   ├── d2_8_throat_clearing.py
│       │   ├── d3_1_sentence_length.py
│       │   ├── d3_3_opener_monotony.py
│       │   ├── d3_4_paragraph_monotony.py
│       │   ├── d3_5_vocabulary_flatness.py
│       │   ├── d4_1_concrete_examples.py
│       │   ├── d4_4_specificity.py
│       │   └── _deferred_decls.py
│       └── common/
│           ├── proselint_wrap.py    # cached proselint pass + span-offset fix
│           ├── readability.py
│           └── word_lists.py        # curated hedge/throat-clearing/vague-quantifier/transition lists
└── samples/
    ├── input.md               # a deliberately bad test document
    └── output.json            # what the analyzer produced for it
```

## Quickstart

```sh
# from the boring/ directory — uv handles venv + deps
uv sync
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl  # one-time
uv run python -m analyzer samples/input.md --genre executive_brief --output result.json
```

If your IDE (VS Code, ty, Pylance) reports spurious "unresolved import" errors
for `spacy`, `proselint`, `textstat`, or `docx`, point the IDE's Python
interpreter at `./.venv/bin/python`. The `pyproject.toml` already configures
`tool.ty.environment`, `tool.pyright`, and `tool.ruff` for that path; some
IDEs also need an explicit interpreter selection.

Genres recognized: `executive_brief`, `architecture_doc`, `technical_report`, `finding_writeup`, `proposal`, `rfc`, `status_update`. Omit `--genre` to use default thresholds.

Input formats: `.md` / `.markdown`, `.txt`, `.docx`, `.pdf`. PDFs use `pypdf` for text extraction and carry `page_number` on every locator. Image-only / scanned PDFs are rejected with a clear error (OCR is not supported).

## What's implemented

All 15 mechanical checks are working end-to-end:

**Direction axis**

- **D1.1** Buried thesis  *(first claim-shaped sentence position; summary-heading near top)*
- **D1.4** No signposting  *(transition markers at section boundaries; roadmap detection)*
- **D1.6** Topic-position drift  *(expletive subjects; per-paragraph subject continuity)*

**Density axis**

- **D2.1** Padding / wordiness  *(proselint + supplemental phrase list)*
- **D2.2** Nominalization fog  *(suffix density + light-verb + nominalization patterns)*
- **D2.3** Passive overhang
- **D2.4** Subject-verb separation
- **D2.7** Hedging clutter  *(stacked-hedge sentence detection)*
- **D2.8** Throat-clearing  *(paragraph/sentence-opener detection)*

**Texture axis**

- **D3.1** Sentence-length monotony
- **D3.3** Opener monotony  *(same-token runs, same-POS runs, first-token entropy)*
- **D3.4** Paragraph monotony  *(length CV, similar-length runs, wall-of-text detection)*
- **D3.5** Vocabulary flatness  *(MATTR + verb diversity + top-verb share)*

**Surprise axis**

- **D4.1** No concrete examples  *(per-paragraph entity / number / example-marker signals)*
- **D4.4** No specificity  *(vague quantifiers, intensifiers, modifiers)*

**LLM-only sub-dimensions** (declared as deferred, to be implemented in a later phase):

- **D1.2** Missing stakes, **D1.5** Flat tension, **D2.5** Obvious claims, **D4.2** No vivid imagery, **D4.3** No counterintuitive claims

Each follows the same registry pattern — see `docs/schema-v0.1.0.md` for design and `src/analyzer/checks/d2_3_passive.py` for a reference implementation.

## Adding a new check

1. Create a new module in `src/analyzer/checks/` (e.g. `d2_8_throat_clearing.py`).
2. Define a class with class-level `code`, `name`, `axis` and a `run(doc, config)` method returning a `Finding`.
3. Call `register_check(YourCheck())` at the bottom of the file.
4. Add `from . import d2_8_throat_clearing  # noqa` to `src/analyzer/checks/__init__.py`.
5. Add the corresponding threshold block to `calibration.toml`.

The pipeline picks it up automatically.

## See also

- `docs/research-report.md` — the original research, full taxonomy, and rubric sketch
- `docs/schema-v0.1.0.md` — full JSON output schema with examples
- `docs/decisions.md` — design decisions log
- `calibration.toml` — every threshold, with rationale comments
