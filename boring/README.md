# boring — writing-evaluation skill

A skill that evaluates technical business writing — executive briefs,
RFCs, status updates, finding writeups, architecture docs, proposals,
technical reports — for "boringness" across a 20-sub-dimension
taxonomy on four axes: **Direction**, **Density**, **Texture**, and
**Surprise**. Grounded in the MAC model of boredom (Westgate & Wilson,
2018) plus the craft tradition (Gopen-Swan, Williams, Provost, Minto).

**Skill entry point**: `src/SKILL.md`. Invoke from a Codex or Claude Code
session.

## Download
Clone the repository or download the skill as a zip file from [`releases`](https://github.com/ericfitz/skills/releases).

## Install

The shipped artifact is a versioned zip in `dist/`. Build it with:

```sh
boring/tools/build.sh
# → boring/dist/boring-<version>.zip
```

To install into a Claude Code skills directory:

```sh
# 1. Copy the zip into your skills dir (user-global shown; project-
#    local would be <repo>/.claude/skills/ instead).
cp boring/dist/boring-<version>.zip ~/.claude/skills/

# 2. Unzip — produces ~/.claude/skills/boring/
cd ~/.claude/skills && unzip boring-<version>.zip && rm boring-<version>.zip

# 3. Build the analyzer's Python venv. Requires `uv`
#    (https://docs.astral.sh/uv/). Takes ~30s the first time.
cd boring && uv sync
```

To install into a Codex skills directory:

```sh
# 1. Copy the zip into your skills dir (user-global shown; project-
#    local would be <repo>/.codex/skills/ instead).
cp boring/dist/boring-<version>.zip ~/.codex/skills/

# 2. Unzip — produces ~/.codex/skills/boring/
cd ~/.codex/skills && unzip boring-<version>.zip && rm boring-<version>.zip

# 3. Build the analyzer's Python venv. Requires `uv`
#    (https://docs.astral.sh/uv/). Takes ~30s the first time.
cd boring && uv sync
```
In either case, step 3 is technically optional — SKILL.md's setup decision tree runs
`uv sync` on first invocation if the venv is missing — but doing it
eagerly fails fast if `uv` isn't installed or the network is down,
instead of discovering that mid-conversation.

## Status

**v0.1.0 — full pipeline complete.** 15 mechanical sub-dimensions run
as a Python script (deterministic, locator-rich JSON output);
5 LLM-judged sub-dimensions are handled by the host LLM via the
rubrics in `src/rubrics/`. Calibration thresholds are intuitive
defaults, not yet tuned against a labeled corpus of business writing —
see `docs/calibration-findings-2026-05-04.md` for the first
calibration attempt and why it punted on threshold updates.

**Next steps** The skill is undergoing calibration against a hand-labeled
corpus of business writing, which will cause an update in the values
in configuration.toml that optimize against writing style at the author's
employer.  The skill runs fine and produces useful output now with
intuitive weights, or you can assemble your own internal corpous
of "boring" and "not-boring" documents for your organization and perform
your own calibration vs. that corpus.  Note that "not-boring" does
not mean the same thing as "interesting"; the latter concept is
heavily weighted in the subject's perceived interest in the subject
matter vs. the writing style.

## Repository layout

This directory is split into the shipped skill and the dev-side
tooling around it:

```
boring/
├── README.md                   ← this file
├── src/                        ← the skill (everything that ships)
│   ├── SKILL.md                ← entry point: invocation, workflow, rubrics index
│   ├── calibration.toml        ← thresholds + per-genre profiles
│   ├── pyproject.toml          ← Python deps for the analyzer
│   ├── uv.lock
│   ├── docs/
│   │   ├── schema-mechanical.md    ← Phase 1 (analyzer) output schema
│   │   ├── schema-llm.md           ← Phase 2 (LLM judgment) output schema
│   │   └── schema-merged.md        ← Phase 3 (merged) output schema
│   ├── rubrics/                ← Phase 2 judge rubrics (read by the host LLM)
│   │   ├── D1_2_missing_stakes.md
│   │   ├── D1_5_flat_tension.md
│   │   ├── D2_5_obvious_claims.md
│   │   ├── D4_2_no_vivid_imagery.md
│   │   └── D4_3_no_counterintuitive_claims.md
│   └── scripts/
│       └── analyzer/           ← the Python analyzer package
│           ├── __main__.py     ← CLI entry point
│           ├── pipeline.py     ← orchestrator
│           ├── document.py     ← parsing (md / txt / docx / pdf), spaCy caching
│           ├── locator.py      ← composite-locator construction
│           ├── config.py       ← calibration loading + genre overrides
│           ├── checks/         ← one file per check, registered into the pipeline
│           └── common/
│               ├── proselint_wrap.py    ← cached proselint pass + span-offset fix
│               ├── readability.py
│               └── word_lists.py        ← curated phrase tables
├── docs/                       ← dev-side reference (not shipped)
│   ├── research-report.md      ← MAC + craft-tradition grounding, taxonomy
│   ├── decisions.md            ← design decisions log
│   └── calibration-findings-2026-05-04.md
├── samples/                    ← smoke-test fixtures (not shipped)
│   ├── input.md
│   └── output.json
├── tools/                      ← calibration scripts (not shipped)
│   ├── run_corpus.py           ← runs the analyzer over a labeled corpus
│   ├── run_one.py              ← re-runs a single doc, patches results.csv
│   └── analyze_results.py      ← per-check separability + threshold recs
├── calibration/                ← gitignored corpus + per-run outputs
│   ├── boring                  ← corpus of curated documents that are hand-labeled as "boring"
│   ├── not-boring              ← corpus of curated documents that are hand-labeled as "not-boring"
└── dist/                       ← gitignored build output (copy of src/)
```

To produce a distributable skill, copy `src/` into `dist/boring/`.
Everything outside `src/` is dev-side and intentionally not shipped.

## Quickstart

```sh
# from boring/src/ — uv handles the venv + deps (model is bundled
# via pyproject.toml, no separate spaCy install needed)
cd src
uv sync

# run the mechanical analyzer against the bundled sample
uv run python -m analyzer ../samples/input.md --genre executive_brief --output /tmp/result.json
```

If your IDE (VS Code, ty, Pylance) reports spurious "unresolved import"
errors for `spacy`, `proselint`, `textstat`, `docx`, or `pypdf`, point
the IDE's Python interpreter at `boring/src/.venv/bin/python`. The
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

1. Create a new module in `src/scripts/analyzer/checks/` (e.g.
   `d2_6_idea_overload.py`).
2. Define a class with class-level `code`, `name`, `axis` and a
   `run(doc, config)` method returning a `Finding`.
3. Call `register_check(YourCheck())` at the bottom of the file.
4. Add the import to `src/scripts/analyzer/checks/__init__.py`.
5. Add the corresponding threshold block to `src/calibration.toml`.

The pipeline picks it up automatically.

## See also

- `src/SKILL.md` — the invocation contract
- `docs/research-report.md` — taxonomy and theoretical grounding
- `src/docs/schema-mechanical.md` / `src/docs/schema-llm.md` /
  `src/docs/schema-merged.md` — output schemas (shipped with the skill)
- `docs/decisions.md` — design decisions log
- `src/calibration.toml` — every threshold, with rationale comments
