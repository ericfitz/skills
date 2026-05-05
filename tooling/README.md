# tooling/

Development tooling that lives outside the distributed skills. Not
shipped, not invoked at skill runtime — used during skill development
and calibration.

## calibration/

Scripts for tuning the boring skill's thresholds in
`boring/calibration.toml` against a hand-labeled corpus.

The corpus itself lives at `boring/calibration/{boring,not-boring}/`
(gitignored — typically third-party / copyrighted source documents
that don't belong in a public repo). Each script writes its outputs
back into `boring/calibration/` (also gitignored).

### Workflow

```sh
# 1. Run the analyzer over every doc in the corpus.
#    Writes boring/calibration/results.csv (one row per doc × sub-dimension).
uv --project boring run python tooling/calibration/run_corpus.py

# 2. (Optional) Re-run a single doc that failed or whose result changed.
#    Replaces that doc's rows in results.csv in place.
uv --project boring run python tooling/calibration/run_one.py boring/some_doc.pdf

# 3. Compute per-check separability + threshold recommendations.
#    Writes boring/calibration/recommendations.md.
uv --project boring run python tooling/calibration/analyze_results.py
```

The recommendations are advisory — review and apply selectively to
`boring/calibration.toml`. See `boring/docs/calibration-findings-2026-05-04.md`
for an example of a calibration run and its writeup.

## Why outside the skill

The skill is self-contained: someone consuming it shouldn't have to
think about how the thresholds were derived, just that they're there.
Calibration tooling, manifest-tracking utilities, and ground-truth
corpora are dev-side concerns and live here so the skill stays clean.
