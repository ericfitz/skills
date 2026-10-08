"""Run the analyzer over a single corpus document and merge its rows into
<corpus-dir>/results.csv (replacing any existing rows for that filename).

Usage (from the skill directory):
    uv run python tools/run_one.py --corpus <corpus-dir> \\
        <path_relative_to_corpus> [--genre GENRE]

Example:
    uv run python tools/run_one.py --corpus <corpus-dir> boring/some_doc.pdf
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

_SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from analyzer.pipeline import run_analysis  # noqa: E402  # ty:ignore[unresolved-import]

CALIBRATION_TOML = _SKILL_DIR / "calibration.toml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--corpus", type=Path, required=True, help="labeled corpus directory (outside the repo)"
    )
    parser.add_argument("document", help="document path relative to the corpus directory")
    parser.add_argument("--genre", default="technical_report")
    args = parser.parse_args(argv)
    corpus_dir: Path = args.corpus.resolve()
    if not corpus_dir.is_dir():
        print(f"Corpus directory not found: {corpus_dir}", file=sys.stderr)
        return 2
    results_csv = corpus_dir / "results.csv"
    rel = args.document
    genre = args.genre
    path = (corpus_dir / rel).resolve()
    if not path.is_relative_to(corpus_dir):
        print(f"Document must be inside the corpus directory: {rel}", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 2

    # Infer label from the top-level directory under the corpus.
    parts = Path(rel).parts
    label = parts[0]
    if label not in ("boring", "not-boring"):
        print(f"First path component must be 'boring' or 'not-boring' (got {label!r})", file=sys.stderr)
        return 2

    print(f"Running analyzer on {rel} (genre={genre}) ...", file=sys.stderr)
    t0 = time.monotonic()
    result = run_analysis(
        document_path=path,
        calibration_path=CALIBRATION_TOML,
        declared_genre=genre,
        genre_source="user_declared",
    )
    elapsed = time.monotonic() - t0
    wc = result["document"]["word_count"]
    sc = result["document"]["sentence_count"]
    print(f"  done ({wc} words, {sc} sents, {elapsed:.1f}s)", file=sys.stderr)

    new_rows: list[dict[str, object]] = []
    for code, finding in result["findings"].items():
        summary = finding.get("summary") or {}
        new_rows.append(
            {
                "filename": rel,
                "label": label,
                "genre": genre,
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

    # Read existing results and drop any rows for this filename, then append.
    existing: list[dict[str, str]] = []
    fieldnames: list[str] | None = None
    if results_csv.is_file():
        with results_csv.open() as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else None
            for row in reader:
                if row.get("filename") != rel:
                    existing.append(row)
    if fieldnames is None:
        fieldnames = list(new_rows[0].keys())

    combined = existing + new_rows
    with results_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in combined:
            writer.writerow(row)
    print(
        f"Wrote {len(new_rows)} rows for {rel} into {results_csv} "
        f"({len(combined)} total rows now).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
