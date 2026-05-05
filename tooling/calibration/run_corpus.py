"""Run the analyzer over every document in the calibration corpus and
emit a flat CSV of (filename, label, genre, code, score, metric_value,
flag_count) rows for downstream separability analysis.

Usage (from the repo root, where the .venv lives next to boring/):
    uv --project boring run python ../tooling/calibration/run_corpus.py

Outputs:
    boring/calibration/results.csv

Skips files that fail to parse (e.g., image-only PDFs); logs them to
stderr and continues. Each successful document contributes one row per
sub-dimension.
"""

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# This script lives at  <repo>/tooling/calibration/run_corpus.py
# The skill (and analyzer) live at  <repo>/boring/
_TOOLING_DIR = Path(__file__).resolve().parent.parent
_REPO_ROOT = _TOOLING_DIR.parent
_SKILL_DIR = _REPO_ROOT / "boring"
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from analyzer.pipeline import run_analysis  # noqa: E402  # ty:ignore[unresolved-import]

CALIBRATION_DIR = _SKILL_DIR / "calibration"
CALIBRATION_TOML = _SKILL_DIR / "calibration.toml"
RESULTS_CSV = CALIBRATION_DIR / "results.csv"

# Default genre for every doc in the corpus. The corpus is predominantly
# academic security papers + threat reports + standards; technical_report
# is the closest existing profile. We can re-stratify later.
DEFAULT_GENRE = "technical_report"

# Per-file genre overrides — for documents whose nature is materially
# different from the default. Keep this small; if a category grows we
# should add a real genre profile to calibration.toml instead.
GENRE_OVERRIDES: dict[str, str] = {
    # All standards / compliance documents are deliberately verbose; they
    # match technical_report better than any current profile, but if we
    # add a `standards_doc` profile in the future this is where it goes.
}


@dataclass
class CorpusItem:
    label: str  # "boring" | "not-boring"
    genre: str
    path: Path


def discover_corpus() -> list[CorpusItem]:
    """Walk calibration/boring and calibration/not-boring (and their
    subdirectories) and return every PDF / TXT / MD / DOCX file."""
    items: list[CorpusItem] = []
    for label_dir, label in [
        (CALIBRATION_DIR / "boring", "boring"),
        (CALIBRATION_DIR / "not-boring", "not-boring"),
    ]:
        if not label_dir.is_dir():
            continue
        for path in sorted(label_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in (".pdf", ".txt", ".md", ".markdown", ".docx"):
                continue
            genre = GENRE_OVERRIDES.get(path.name, DEFAULT_GENRE)
            items.append(CorpusItem(label=label, genre=genre, path=path))
    return items


def main() -> int:
    items = discover_corpus()
    if not items:
        print("No documents found under calibration/{boring,not-boring}/", file=sys.stderr)
        return 1
    print(f"Found {len(items)} documents.", file=sys.stderr)

    rows: list[dict[str, object]] = []
    for i, item in enumerate(items, start=1):
        rel = item.path.relative_to(CALIBRATION_DIR)
        t0 = time.monotonic()
        try:
            result = run_analysis(
                document_path=item.path,
                calibration_path=CALIBRATION_TOML,
                declared_genre=item.genre,
                genre_source="user_declared",
            )
        except (ValueError, OSError, RuntimeError, KeyError, MemoryError) as exc:
            # ValueError: bad PDF, scanned PDF, doc too large for spaCy.
            # OSError / KeyError / RuntimeError: parser / dependency edge cases.
            # MemoryError: pathological huge document.
            # We log and continue so a single bad doc doesn't abort the corpus run.
            print(
                f"  [{i}/{len(items)}] FAIL  {rel}  ({type(exc).__name__}: {exc})",
                file=sys.stderr,
            )
            continue
        elapsed = time.monotonic() - t0
        wc = result["document"]["word_count"]
        sc = result["document"]["sentence_count"]
        print(f"  [{i}/{len(items)}] OK    {rel}  ({wc} words, {sc} sents, {elapsed:.1f}s)", file=sys.stderr)

        for code, finding in result["findings"].items():
            summary = finding.get("summary") or {}
            rows.append(
                {
                    "filename": str(rel),
                    "label": item.label,
                    "genre": item.genre,
                    "word_count": wc,
                    "sentence_count": sc,
                    "code": code,
                    "name": finding["name"],
                    "axis": finding["axis"],
                    "checked": finding["checked"],
                    "score": summary.get("score"),
                    "metric_name": summary.get("metric_name"),
                    "metric_value": summary.get("metric_value"),
                    "threshold_warn": summary.get("threshold_warn"),
                    "threshold_severe": summary.get("threshold_severe"),
                    "flag_count": len(finding.get("flags", [])),
                }
            )

    if not rows:
        print("No results to write — every document failed.", file=sys.stderr)
        return 2

    fieldnames = list(rows[0].keys())
    with RESULTS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    file_count = len({r["filename"] for r in rows})
    print(
        f"\nWrote {len(rows)} rows for {file_count} documents -> {RESULTS_CSV}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
