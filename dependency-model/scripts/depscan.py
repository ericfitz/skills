#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Emit a deterministic JSON evidence index of a repository's dependencies.

Read-only: this walks and reads files. It resolves no names, opens no
sockets, boots no containers, and runs no build.

Usage:
    uv run --script depscan.py [PATH] [--json] [--indent N]
    python3 depscan.py [PATH] [--json] [--indent N]   # fallback; no deps

Exit codes:
    0  index emitted (possibly partial; see coverage.confidence)
    2  PATH is not a usable directory
"""

import argparse
import json
import sys
from pathlib import Path

from depscanlib.report import build_scan


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="depscan.py",
        description="Emit a deterministic JSON dependency-evidence index.")
    parser.add_argument("path", nargs="?", default=".",
                        help="repo root to scan (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON (default; accepted for explicitness)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": f"not a directory: {args.path}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(build_scan(root), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
