"""CLI entry point.

Usage:
    python -m analyzer <document_path> --calibration <calibration.toml> [--genre <name>] [--output <path>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import run_analysis


def _default_calibration_path() -> Path:
    """Find calibration.toml by walking up from this file.

    Layout supported:
      - src/analyzer/__main__.py + repo-root/calibration.toml
      - analyzer/__main__.py + analyzer/../calibration.toml (flat layout)
    First match wins; otherwise return a placeholder that argparse will
    expose as the default and which load_config will then fail on with
    a clear message.
    """
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / "calibration.toml"
        if candidate.is_file():
            return candidate
    return here.parent / "calibration.toml"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="analyzer", description="Mechanical analysis for boring-writing detection.")
    p.add_argument("document", type=Path, help="Path to the document to analyze.")
    p.add_argument(
        "--calibration",
        type=Path,
        default=_default_calibration_path(),
        help="Path to calibration.toml (default: search upwards from the package).",
    )
    p.add_argument(
        "--genre",
        type=str,
        default=None,
        help="Declared genre (e.g. executive_brief, architecture_doc, finding_writeup, ...).",
    )
    p.add_argument(
        "--genre-source",
        type=str,
        default="default",
        choices=["user_declared", "llm_inferred", "default"],
        help="How the genre was determined.",
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON output to this path instead of stdout.",
    )
    args = p.parse_args(argv)

    result = run_analysis(
        document_path=args.document,
        calibration_path=args.calibration,
        declared_genre=args.genre,
        genre_source=args.genre_source,
    )

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
