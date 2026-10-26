#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Render saved profile contracts as one offline HTML report."""

import argparse
import os
import sys
import tempfile
import webbrowser
from pathlib import Path

from reportlib.inputs import ReportInputError, load_profile
from reportlib.render import render_report


def _destination(output: Path, input_paths: list[Path]) -> Path:
    """Resolve caller paths and reject unsafe destinations without changing files."""
    output = output.expanduser()
    if output.suffix.lower() not in {".html", ".htm"}:
        raise ReportInputError(f"{output}: output must have an .html or .htm suffix")
    resolved = output.resolve()
    if not resolved.parent.is_dir():
        raise ReportInputError(f"{output}: output parent directory must already exist")
    if resolved.exists() and not resolved.is_file():
        raise ReportInputError(f"{output}: output must be a regular file")
    for path in input_paths:
        source = path.expanduser().resolve()
        if resolved == source or (resolved.exists() and source.exists() and resolved.samefile(source)):
            raise ReportInputError(f"{output}: output collides with input {path}")
    return resolved


def write_report(output: Path, html: str, input_paths: list[Path]) -> None:
    """Atomically replace the requested report, preserving inputs and old output."""
    output = _destination(output, input_paths)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(html)
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact_dir", type=Path, help="directory containing the four saved profile contracts")
    parser.add_argument(
        "--support", type=Path, action="append", default=[], help="explicit JSON, text or Markdown file"
    )
    parser.add_argument("--out", type=Path, help="HTML destination (default: <artifact_dir>/profile-report.html)")
    parser.add_argument("--title", help="report title")
    parser.add_argument("--open", action="store_true", help="request the default browser after successful generation")
    args = parser.parse_args(argv)
    try:
        artifact_dir = args.artifact_dir.expanduser()
        support = [path.expanduser() for path in args.support]
        inputs = [artifact_dir / f"{name}.json" for name in ("stack", "docs", "journeys", "topology")]
        inputs.extend(support)
        output = _destination(args.out if args.out is not None else artifact_dir / "profile-report.html", inputs)
        bundle = load_profile(artifact_dir, support)
        html = render_report(bundle, args.title)
        write_report(output, html, inputs)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Report saved: {output}")
    if not args.open:
        print("Browser: not requested")
    else:
        try:
            opened = webbrowser.open(output.as_uri())
        except Exception as exc:
            print(f"Warning: report saved, but browser opening failed: {exc}", file=sys.stderr)
        else:
            if opened:
                print("Browser: opening requested successfully")
            else:
                print("Warning: report saved, but browser opening was unavailable or declined", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
