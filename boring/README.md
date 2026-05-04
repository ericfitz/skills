# boring — Boring-Writing Detection Skill

A skill for evaluating technical business writing for "boringness" and proposing targeted improvements. Built around a four-axis taxonomy (Direction, Density, Texture, Surprise) grounded in psychology of boredom, psycholinguistics, and the technical-writing craft tradition.

## Status

**v0.1.0 scaffold + first wave of density checks.** The mechanical-analysis layer is built end-to-end. Six mechanical checks are implemented, demonstrating every pattern we'll need: span-emitting, aggregate-only, multi-factor severity, proselint integration, and curated-phrase detection. Nine more mechanical checks plus the LLM-evaluation, synthesis, and presentation phases are still to come.

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
│       │   ├── d2_1_padding.py
│       │   ├── d2_3_passive.py
│       │   ├── d2_4_sv_gap.py
│       │   ├── d2_7_hedging.py
│       │   ├── d2_8_throat_clearing.py
│       │   ├── d3_1_sentence_length.py
│       │   └── _deferred_decls.py
│       └── common/
│           ├── proselint_wrap.py    # cached proselint pass + span-offset fix
│           ├── readability.py
│           └── word_lists.py        # curated hedge/throat-clearing/vague-quantifier lists
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

## What's implemented

Mechanical checks (working end-to-end):

- **D2.1** Padding / wordiness  *(proselint + supplemental phrase list)*
- **D2.3** Passive overhang
- **D2.4** Subject-verb separation
- **D2.7** Hedging clutter  *(stacked-hedge sentence detection)*
- **D2.8** Throat-clearing  *(paragraph/sentence-opener detection)*
- **D3.1** Sentence-length monotony

LLM-only sub-dimensions (declared as deferred, to be implemented in a later phase):

- **D1.2** Missing stakes, **D1.5** Flat tension, **D2.5** Obvious claims, **D4.2** No vivid imagery, **D4.3** No counterintuitive claims

Mechanical checks designed but not yet implemented:

- **D1.1** Buried thesis, **D1.4** No signposting, **D1.6** Topic-position drift
- **D2.2** Nominalization
- **D3.3** Opener monotony, **D3.4** Paragraph monotony, **D3.5** Vocabulary flatness
- **D4.1** No concrete examples, **D4.4** No specificity

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
