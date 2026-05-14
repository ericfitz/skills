# boring/tools/

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
skill's thresholds in `boring/src/calibration.toml` against a
hand-labeled corpus.

The corpus itself lives at `boring/calibration/{boring,not-boring}/`
(gitignored — typically third-party / copyrighted source documents
that don't belong in a public repo). Each script writes its outputs
back into `boring/calibration/` (also gitignored).

### Workflow

Run from the repo root:

```sh
# 1. Run the analyzer over every doc in the corpus.
#    Writes boring/calibration/results.csv (one row per doc × sub-dimension).
uv --project boring/src run python boring/tools/run_corpus.py

# 2. (Optional) Re-run a single doc that failed or whose result changed.
#    Replaces that doc's rows in results.csv in place.
uv --project boring/src run python boring/tools/run_one.py boring/calibration/boring/some_doc.pdf

# 3. Compute per-check separability + threshold recommendations.
#    Writes boring/calibration/recommendations.md.
uv --project boring/src run python boring/tools/analyze_results.py
```

The recommendations are advisory — review and apply selectively to
`boring/src/calibration.toml`. See `boring/docs/calibration-findings-2026-05-04.md`
for an example of a calibration run and its writeup.

## Why outside the shipped skill

The skill is self-contained: someone consuming it from `dist/`
shouldn't have to think about how the thresholds were derived, just
that they're there. Calibration tooling, manifest-tracking utilities,
and ground-truth corpora are dev-side concerns and live here so the
skill stays clean.
