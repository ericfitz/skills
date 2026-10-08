#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Emit a deterministic JSON evidence index of a repository's dependencies.

Read-only: this walks and reads files. It resolves no names, opens no
sockets, boots no containers, and runs no build.

Usage:
    uv run --script depscan.py [PATH] [--ref REF] [--write] [--indent N]
    python3 depscan.py [PATH] [--ref REF] [--write] [--indent N]   # fallback; no deps

--ref scans a `git archive` snapshot of REF instead of the working tree.
--write saves the index as depscan.json in the per-run output dir (keyed on
PATH and the commit) and prints that dir instead of the index.

Exit codes:
    0  index emitted (possibly partial; see coverage.confidence)
    2  PATH is not a usable directory, or REF is not a commit in it
"""

import argparse
import json
import sys
from pathlib import Path

from depscanlib.report import build_scan
from depscanlib.run import RefError, prepare


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="depscan.py",
        description="Emit a deterministic JSON dependency-evidence index.")
    parser.add_argument("path", nargs="?", default=".",
                        help="repo root to scan (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON (default; accepted for explicitness)")
    parser.add_argument("--ref", help="scan a snapshot of this git ref")
    parser.add_argument("--write", action="store_true",
                        help="save depscan.json in the run dir; print the dir")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": f"not a directory: {args.path}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    try:
        run = prepare(root, args.ref)
    except RefError as exc:
        json.dump({"error": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    text = json.dumps(build_scan(run.scan_root, target=root, ref=run.ref,
                                 run_dir=run.run_dir, refused=run.refused),
                      indent=indent, sort_keys=True)
    if args.write:
        (run.run_dir / "depscan.json").write_text(text + "\n", encoding="utf-8")
        print(run.run_dir)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
