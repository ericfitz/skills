"""Run the analyzer over a single document and append its rows to
boring/calibration/results.csv (replacing any existing rows for that filename).

Usage (from the repo root):
    uv --project boring/src run python boring/tools/run_one.py \\
        <relative_path_under_calibration> [genre]

Example:
    uv --project boring/src run python boring/tools/run_one.py \\
        boring/03_nist_sp_800-53_rev5_2020.pdf
"""

from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

_BORING_DIR = Path(__file__).resolve().parent.parent
_SRC_DIR = _BORING_DIR / "src"
sys.path.insert(0, str(_SRC_DIR / "scripts"))

from analyzer.pipeline import run_analysis  # noqa: E402  # ty:ignore[unresolved-import]

CALIBRATION_DIR = _BORING_DIR / "calibration"
CALIBRATION_TOML = _SRC_DIR / "calibration.toml"
RESULTS_CSV = CALIBRATION_DIR / "results.csv"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    rel = argv[1]
    genre = argv[2] if len(argv) > 2 else "technical_report"
    path = CALIBRATION_DIR / rel
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 2

    # Infer label from top-level directory under calibration/.
    parts = Path(rel).parts
    if not parts:
        print("Path must be inside calibration/", file=sys.stderr)
        return 2
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
    if RESULTS_CSV.is_file():
        with RESULTS_CSV.open() as f:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else None
            for row in reader:
                if row.get("filename") != rel:
                    existing.append(row)
    if fieldnames is None:
        fieldnames = list(new_rows[0].keys())

    combined = existing + new_rows
    with RESULTS_CSV.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in combined:
            writer.writerow(row)
    print(
        f"Wrote {len(new_rows)} rows for {rel} into {RESULTS_CSV} "
        f"({len(combined)} total rows now).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
