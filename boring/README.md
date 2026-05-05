# boring — writing-evaluation skill

A skill that evaluates technical business writing — executive briefs,
RFCs, status updates, finding writeups, architecture docs, proposals,
technical reports — for "boringness" across a 20-sub-dimension
taxonomy on four axes: **Direction**, **Density**, **Texture**, and
**Surprise**. Grounded in the MAC model of boredom (Westgate & Wilson,
2018) plus the craft tradition (Gopen-Swan, Williams, Provost, Minto).

**Skill entry point**: `SKILL.md`. Invoke from a Claude Code or
Anthropic-Console session.

## Status

**v0.1.0 — full pipeline complete.** 15 mechanical sub-dimensions run
as a Python script (deterministic, locator-rich JSON output);
5 LLM-judged sub-dimensions are handled by the host LLM via the
rubrics in `rubrics/`. Calibration thresholds are intuitive defaults,
not yet tuned against a labeled corpus of business writing — see
`docs/calibration-findings-2026-05-04.md` for the first calibration
attempt and why it punted on threshold updates.

## Structure

```
boring/
├── SKILL.md                    ← entry point: invocation, workflow, rubrics index
├── README.md                   ← this file (project overview)
├── calibration.toml            ← thresholds + per-genre profiles
├── pyproject.toml              ← Python deps for the analyzer
├── docs/
│   ├── research-report.md      ← MAC + craft-tradition grounding, taxonomy
│   ├── schema-mechanical.md    ← Phase 1 (analyzer) output schema
│   ├── schema-llm.md           ← Phase 2 (LLM judgment) output schema
│   ├── schema-merged.md        ← Phase 3 (merged) output schema
│   ├── decisions.md            ← design decisions log
│   └── calibration-findings-2026-05-04.md
├── rubrics/                    ← Phase 2 judge rubrics (read by the host LLM)
│   ├── D1_2_missing_stakes.md
│   ├── D1_5_flat_tension.md
│   ├── D2_5_obvious_claims.md
│   ├── D4_2_no_vivid_imagery.md
│   └── D4_3_no_counterintuitive_claims.md
├── samples/
│   ├── input.md                ← deliberately bad sample for testing
│   └── output.json             ← Phase 1 output for the sample
└── scripts/
    └── analyzer/               ← the Python analyzer package
        ├── __main__.py         ← CLI entry point
        ├── pipeline.py         ← orchestrator
        ├── document.py         ← parsing (md / txt / docx / pdf), spaCy caching
        ├── locator.py          ← composite-locator construction
        ├── config.py           ← calibration loading + genre overrides
        ├── checks/             ← one file per check, registered into the pipeline
        └── common/
            ├── proselint_wrap.py    ← cached proselint pass + span-offset fix
            ├── readability.py
            └── word_lists.py        ← curated phrase tables
```

The `tooling/` directory at the repo root (outside the skill) holds
calibration scripts used during development:

```
tooling/
└── calibration/
    ├── run_corpus.py           ← runs the analyzer over a labeled corpus
    ├── run_one.py              ← re-runs a single doc, patches results.csv
    └── analyze_results.py      ← per-check separability + threshold recs
```

These are **not part of the skill** — they're for tuning
`calibration.toml` against a hand-labeled corpus. Don't ship them as
part of the skill distribution.

## Quickstart

```sh
# from the boring/ directory — uv handles the venv + deps
uv sync
uv pip install https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl  # one-time

# run the mechanical analyzer
uv run python -m analyzer samples/input.md --genre executive_brief --output result.json
```

If your IDE (VS Code, ty, Pylance) reports spurious "unresolved import"
errors for `spacy`, `proselint`, `textstat`, `docx`, or `pypdf`, point
the IDE's Python interpreter at `./.venv/bin/python`. The
`pyproject.toml` already configures `tool.ty.environment`,
`tool.pyright`, and `tool.ruff` for that path; some IDEs also need an
explicit interpreter selection.

Genres recognized: `executive_brief`, `architecture_doc`,
`technical_report`, `finding_writeup`, `proposal`, `rfc`,
`status_update`. Omit `--genre` to use default thresholds.

Input formats: `.md` / `.markdown`, `.txt`, `.docx`, `.pdf`. PDFs use
`pypdf` for text extraction and carry `page_number` on every locator.
Image-only / scanned PDFs are rejected with a clear error (OCR is not
supported).

## What the analyzer covers

15 mechanical sub-dimensions across the four axes:

**Direction**: D1.1 buried thesis, D1.4 no signposting, D1.6 topic-
position drift.

**Density**: D2.1 padding/wordiness, D2.2 nominalization fog,
D2.3 passive overhang, D2.4 subject-verb separation, D2.7 hedging
clutter, D2.8 throat-clearing.

**Texture**: D3.1 sentence-length monotony, D3.3 opener monotony,
D3.4 paragraph monotony, D3.5 vocabulary flatness.

**Surprise**: D4.1 no concrete examples, D4.4 no specificity.

The 5 sub-dimensions deferred to the host LLM (handled in Phase 2 of
the skill workflow): D1.2 missing stakes, D1.5 flat tension,
D2.5 obvious claims, D4.2 no vivid imagery, D4.3 no counterintuitive
claims. Their rubrics live in `rubrics/`.

## Adding a new mechanical check

1. Create a new module in `scripts/analyzer/checks/` (e.g.
   `d2_6_idea_overload.py`).
2. Define a class with class-level `code`, `name`, `axis` and a
   `run(doc, config)` method returning a `Finding`.
3. Call `register_check(YourCheck())` at the bottom of the file.
4. Add the import to `scripts/analyzer/checks/__init__.py`.
5. Add the corresponding threshold block to `calibration.toml`.

The pipeline picks it up automatically.

## See also

- `SKILL.md` — the invocation contract
- `docs/research-report.md` — taxonomy and theoretical grounding
- `docs/schema-mechanical.md` / `docs/schema-llm.md` /
  `docs/schema-merged.md` — output schemas
- `docs/decisions.md` — design decisions log
- `calibration.toml` — every threshold, with rationale comments
