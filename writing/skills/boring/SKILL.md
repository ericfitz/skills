---
name: boring
description: Evaluate technical business writing for "boringness" across 20 sub-dimensions on four axes (Direction, Density, Texture, Surprise). Combines a mechanical analyzer (15 sub-dimensions, deterministic, runs as a Python script) with five LLM-judged sub-dimensions that require semantic judgment. Use when the user asks to review a document for engagement, clarity, or "is this boring", or for prose-mechanics issues in technical writing.
---

# boring — writing-evaluation skill

This skill evaluates technical business writing — executive briefs,
RFCs, status updates, finding writeups, architecture docs, proposals,
technical reports — across a 20-sub-dimension taxonomy on four axes:

- **Direction** — does the reader know where this is going and why?
- **Density** — is the information rate well-calibrated?
- **Texture** — is the prose rhythmically alive?
- **Surprise** — does the reader ever encounter the unexpected?

The taxonomy is grounded in the MAC model of boredom (Westgate &
Wilson, 2018) plus the craft tradition (Gopen-Swan, Williams, Provost,
Minto). Full theoretical grounding lives in the development repo
(`writing/skills/boring/top-docs/research-report.md`) and is not shipped with the skill.

## When to invoke

Invoke when the user asks any of:

- "Review this document"
- "Is this boring / engaging / hard to read / dry?"
- "Evaluate this writing for X" (where X is on the four-axis taxonomy)
- "Check this RFC / brief / report / proposal"
- "What's wrong with this writing?"

Skip when the user asks for:

- Spell-check / grammar correction (use a grammar tool)
- Style-guide enforcement (e.g., AP, Chicago) (use a style-guide linter)
- Copy editing or rewriting (this skill diagnoses; it doesn't rewrite)
- Single-sentence questions ("is this passive voice?") — too small
  for the full pipeline

## Workflow

The skill has two phases. **You run the mechanical phase as a script;
you do the LLM phase yourself in this conversation.**

### Phase 1 — Run the mechanical analyzer

The analyzer is a Python script. It produces deterministic, locator-
rich JSON for 15 sub-dimensions plus document metadata (readability,
structure, paragraph/sentence stats). It also lists the 5 sub-
dimensions deferred to you (Phase 2).

#### Where is the skill installed?

Throughout this section, `<SKILL_DIR>` means the directory containing
this `SKILL.md` (e.g., `~/.claude/skills/boring/`,
`/path/to/cloned/repo/boring/`, etc.). All paths in the commands
below resolve from that directory, not from the user's current working
directory.

#### One-time setup

The analyzer needs a Python virtual environment with `spacy`,
`proselint`, `textstat`, `python-docx`, `pypdf`, and the
`en_core_web_sm` spaCy model. All dependencies are declared in
`pyproject.toml`, so a single `uv sync` from `<SKILL_DIR>` builds the
environment and installs everything; subsequent runs are a no-op.

#### Setup decision tree

Run these checks in order on every invocation. Each one tells you
exactly what to do at the relevant fork.

**Check 1 — Is `uv` installed?**

```sh
uv --version
```

- **Exit 0** → `uv` is installed; continue to Check 2.
- **`command not found`** → STOP. `uv` is a hard prerequisite and the
  skill cannot install it for the user (it's a system-level tool).
  Tell the user: *"This skill needs `uv` to manage its Python
  environment, but `uv` doesn't appear to be installed on this system.
  Please install it from <https://docs.astral.sh/uv/getting-started/installation/>
  (one-line installer for macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`),
  then re-run the skill."* Do not proceed.

**Check 2 — Is the venv built and current?**

```sh
cd <SKILL_DIR>
uv sync
```

- **Exit 0** → venv is built or refreshed; continue to Check 3.
- **Network error** (PyPI or `github.com` unreachable, "Connection
  reset", "Failed to fetch") → STOP. Tell the user: *"Setup needs to
  download Python packages from PyPI and the spaCy model from GitHub,
  but the network request failed: [paste the error]. Please check
  your internet connection (or proxy / firewall settings) and re-run
  the skill."* Do not retry blindly.
- **`uv` version too old** ("unrecognized option", "unknown command")
  → STOP. Tell the user: *"This skill requires a recent version of
  `uv`. Please update with `uv self update` and re-run."*
- **Other error** → STOP. Capture the full error and tell the user:
  *"Setup failed with an error I don't recognize: [paste]. Please
  share this with whoever maintains the skill, or try removing the
  venv (`rm -rf <SKILL_DIR>/.venv`) and re-running."*

**Check 3 — Verify the venv actually works.**

```sh
cd <SKILL_DIR>
uv run python -c "from analyzer.pipeline import run_analysis; import en_core_web_sm; print('analyzer + spaCy model: ok')"
```

- **Prints `analyzer + spaCy model: ok`** → setup is good. Proceed to
  the analysis step.
- **`ModuleNotFoundError: No module named 'analyzer'`** → the editable
  install of the local package didn't take. Recover with:
  `cd <SKILL_DIR> && rm -rf .venv && uv sync` and re-run the
  verification. If it still fails after a clean rebuild, tell the
  user the same way you'd report an unknown error in Check 2.
- **`OSError: [E050] Can't find model 'en_core_web_sm'`** → rare,
  because `uv run` re-installs missing declared dependencies on the
  fly. If you do see it, the model URL in `pyproject.toml` may be
  stale relative to the spaCy version actually installed (e.g., a
  manual `pip install spacy` upgraded spaCy past what the model
  supports). Recovery: clean rebuild (`rm -rf .venv && uv sync`).
  If that still fails, tell the user the model pin needs a refresh
  and stop.
- **Any other import error** → capture the full traceback and tell
  the user the venv is broken in a way you don't recognize, and
  suggest the clean-rebuild recipe as a first step.

**Once Check 3 passes**, the environment is good for the rest of the
session. Don't re-run the checks for follow-up document analyses
within the same session — `uv sync` is fast (~10 ms when current)
but the verification call spins up Python, which is unnecessary
overhead.

#### Run on the target document

```sh
cd <SKILL_DIR>
uv run python -m analyzer <absolute-path-to-document> \
    --genre <genre> \
    --output <absolute-path-to-output.json>
```

**Always use absolute paths** for the document and output — `cd
<SKILL_DIR>` changes your working directory, so document paths
relative to where the user invoked you will resolve incorrectly.

**Always use `uv run`** — running `python -m analyzer` directly will
fail to find the package because the analyzer lives under
`scripts/analyzer/` and is only on `sys.path` via the editable
install that `uv run` activates.

Genres recognized: `executive_brief`, `architecture_doc`,
`technical_report`, `finding_writeup`, `proposal`, `rfc`,
`status_update`. If the user didn't declare a genre, infer it from the
document's structure and content; if you're not confident, ask the
user.

Input formats accepted: `.md`, `.markdown`, `.txt`, `.docx`, `.pdf`.
Image-only / scanned PDFs are rejected with a clear error (no OCR).

The output is JSON conforming to `docs/schema-mechanical.md`. The
fields you care about for Phase 2:

- `findings` — 15 mechanical findings, keyed by code
- `deferred_to_llm` — 5 deferred sub-dimensions (D1.2, D1.5, D2.5,
  D4.2, D4.3) — these are your Phase 2 work
- `document` — text metadata you'll echo into the LLM output
- `structure`, `readability` — supporting context for your judgments

### Phase 2 — Apply the five judge rubrics

For each of the five deferred sub-dimensions, apply the corresponding
rubric and produce a structured judgment. The rubrics live at:

| Code | Name | Rubric |
|---|---|---|
| D1.2 | Missing stakes | `rubrics/D1_2_missing_stakes.md` |
| D1.5 | Flat tension | `rubrics/D1_5_flat_tension.md` |
| D2.5 | Obvious claims | `rubrics/D2_5_obvious_claims.md` |
| D4.2 | No vivid imagery or analogy | `rubrics/D4_2_no_vivid_imagery.md` |
| D4.3 | No counterintuitive claims | `rubrics/D4_3_no_counterintuitive_claims.md` |

Read each rubric in full before judging — they include genre
adjustments, evidence patterns, and what the mechanical layer cannot
tell you. Judge the document **as it is, for its declared genre, in
front of a reader who knows the topic but is busy.**

For each judgment produce:

1. **Score** — `pass`, `warn`, or `severe` (matching the mechanical
   layer's three-tier scheme; see `docs/schema-llm.md`)
2. **Rationale** — one or two sentences. Direct, specific, no
   lecturing.
3. **Evidence** — two to four short evidence quotes from the document,
   each with a one-line comment on what the quote shows. **Quotes must
   be verbatim substrings of the document — never paraphrase or
   summarize.** Use ellipsis for elision; the surviving fragments
   must still be verbatim.
4. **Confidence** — `low`, `medium`, or `high`. Use `low` when the
   document is too short or off-genre to judge reliably, or when the
   signals are mixed. Use `high` only when the evidence is unambiguous.

Use the mechanical findings as supporting context — they tell you
what the prose-mechanics surface looks like — but make your own
judgment on the dimension you're asked about. The rubrics are
explicit about what the mechanical layer cannot tell you.

### Phase 3 — Emit the merged output

Combine the mechanical JSON and your LLM judgments into a single
merged JSON conforming to `docs/schema-merged.md`. The merged shape
has one `findings` block keyed by sub-dimension code, with each entry
tagged `source: mechanical | llm`.

The merged output also carries an `axis_summary` block aggregating
per-axis scores using the rule:

- `severe` if any sub-dimension on this axis scored `severe` (and is
  not a genre-gated pass)
- `warn` if no severes but at least one warn
- `pass` if all pass

Save the merged output to a path the user can read (default
`<document>.boring.json` next to the original document, unless the
user specifies otherwise).

### Phase 4 — Present findings to the user

After producing the merged JSON, summarize for the user. Lead with
the four axis verdicts; then enumerate the most important sub-
dimensions to address. Apply this priority ordering (derived from
the MAC model; see the development repo's research report for full
detail):

1. Direction failures first — fix these and the document becomes
   worth reading even if other problems remain.
2. Top one or two Density failures — usually the highest-impact
   sub-dimensions for technical writers (often nominalization or
   padding).
3. One Texture observation — usually sentence-length monotony or
   opener monotony.
4. One Surprise prompt — usually "where is the most interesting /
   counterintuitive finding, and is it given enough prominence?"

For each item present: (a) the score and one-sentence rationale,
(b) the locator information from the mechanical phase or evidence
quote from the LLM phase, (c) a short concrete prompt for the writer
to address it. **Do not generate rewrites unless the user explicitly
asks** — this skill diagnoses; rewriting is a separate ask the user
should make deliberately.

## Important constraints

- **Don't lecture.** The output should be diagnostic and specific,
  not a writing-craft mini-essay attached to every finding.
- **Don't rewrite unless asked.** Diagnosis only by default.
- **Don't penalize useful absence of narrative.** A reference doc, an
  API spec, or a runbook should *not* have cognitive tension or
  surprise. Apply the genre adjustments in each rubric.
- **Don't mistake dense for boring.** Technical content is sometimes
  legitimately dense for its audience. The mechanical layer gives you
  signals; you decide whether the density is unmotivated (fog) or
  motivated (high information rate for an expert reader).
- **Quotes are verbatim.** When the schema says "verbatim substring,"
  it means verbatim. The downstream consumer can grep for the quote
  text to locate evidence in the source. Paraphrasing breaks that.

## Files in this skill

```
boring/
├── SKILL.md                    ← this file
├── calibration.toml            ← thresholds (uncalibrated as of v0.1)
├── docs/
│   ├── schema-mechanical.md    ← Phase 1 output schema
│   ├── schema-llm.md           ← Phase 2 output schema
│   └── schema-merged.md        ← Phase 3 output schema
├── rubrics/
│   ├── D1_2_missing_stakes.md
│   ├── D1_5_flat_tension.md
│   ├── D2_5_obvious_claims.md
│   ├── D4_2_no_vivid_imagery.md
│   └── D4_3_no_counterintuitive_claims.md
├── scripts/
│   └── analyzer/               ← the Python analyzer package
├── pyproject.toml              ← Python deps (spacy, proselint, textstat, ...)
└── uv.lock
```
