"""Run the analyzer over every document in a labeled corpus and
emit a flat CSV of (filename, label, genre, code, score, metric_value,
flag_count) rows for downstream separability analysis.

The corpus is a directory outside this repository containing
`boring/` and `not-boring/` subdirectories.

Usage (from the skill directory):
    uv run python tools/run_corpus.py --corpus <corpus-dir>

Outputs:
    <corpus-dir>/results.csv

Skips files that fail to parse (e.g., image-only PDFs); logs them to
stderr and continues. Each successful document contributes one row per
sub-dimension.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# This script lives at  <skill>/tools/run_corpus.py; the analyzer package
# lives at  <skill>/scripts/analyzer/  and the thresholds at  <skill>/calibration.toml.
_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from analyzer.pipeline import run_analysis  # noqa: E402  # ty:ignore[unresolved-import]

CALIBRATION_TOML = _SKILL_DIR / "calibration.toml"
LABELS = ("boring", "not-boring")

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


def discover_corpus(corpus_dir: Path) -> list[CorpusItem]:
    """Walk <corpus>/boring and <corpus>/not-boring (and their
    subdirectories) and return every PDF / TXT / MD / DOCX file."""
    items: list[CorpusItem] = []
    for label in LABELS:
        label_dir = corpus_dir / label
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus", type=Path, required=True, help="labeled corpus directory (outside the repo)"
    )
    args = parser.parse_args(argv)
    corpus_dir: Path = args.corpus.resolve()
    if not corpus_dir.is_dir():
        print(f"Corpus directory not found: {corpus_dir}", file=sys.stderr)
        return 2
    results_csv = corpus_dir / "results.csv"

    items = discover_corpus(corpus_dir)
    if not items:
        print(f"No documents found under {corpus_dir}/{{boring,not-boring}}/", file=sys.stderr)
        return 1
    print(f"Found {len(items)} documents.", file=sys.stderr)

    rows: list[dict[str, object]] = []
    for i, item in enumerate(items, start=1):
        rel = item.path.relative_to(corpus_dir)
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
    with results_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    file_count = len({r["filename"] for r in rows})
    print(
        f"\nWrote {len(rows)} rows for {file_count} documents -> {results_csv}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
