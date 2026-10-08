# tools/

Development tooling for the boring skill. Not shipped with the skill,
not invoked at skill runtime — used during skill development,
calibration, and packaging.

## Build script

`build.sh` produces a distributable zip:

```sh
boring/tools/build.sh
# → boring/dist/boring/             (staged tree, kept for inspection)
# → boring/dist/boring-<version>.zip (artifact for distribution)
```

Version is read from `boring/src/pyproject.toml`. The zip wraps a
top-level `boring/` directory so `unzip` produces a single drop-in
folder. Excludes `.venv`, `__pycache__`, `*.egg-info`, `.envrc`,
`.ruff_cache`, and `.DS_Store`.

## Calibration scripts

`run_corpus.py`, `run_one.py`, and `analyze_results.py` tune the
skill's thresholds in `calibration.toml` against a hand-labeled corpus.

The corpus is a directory kept **outside this repository** (its
documents are third-party and must never be committed). It holds
`boring/` and `not-boring/` subdirectories; each script takes its path
as `--corpus` and writes its outputs (`results.csv`,
`recommendations.md`) into that same directory.

### Workflow

Run from the skill directory:

```sh
# 1. Run the analyzer over every doc in the corpus.
#    Writes <corpus-dir>/results.csv (one row per doc × sub-dimension).
uv run python tools/run_corpus.py --corpus <corpus-dir>

# 2. (Optional) Re-run a single doc that failed or whose result changed.
#    Replaces that doc's rows in results.csv in place.
uv run python tools/run_one.py --corpus <corpus-dir> boring/some_doc.pdf

# 3. Compute per-check separability + threshold recommendations.
#    Writes <corpus-dir>/recommendations.md.
uv run python tools/analyze_results.py --corpus <corpus-dir>
```

The recommendations are advisory — review and apply selectively to
`calibration.toml`.

## Why outside the shipped skill

The skill is self-contained: someone consuming it from `dist/`
shouldn't have to think about how the thresholds were derived, just
that they're there. Calibration tooling, manifest-tracking utilities,
and ground-truth corpora are dev-side concerns and live here so the
skill stays clean.
