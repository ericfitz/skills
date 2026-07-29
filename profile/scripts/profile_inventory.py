#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Emit a deterministic JSON inventory of a repository.

Usage:
    uv run --script profile_inventory.py [PATH] [--json] [--indent N]
    python3 profile_inventory.py [PATH] [--json] [--indent N]   # fallback; no deps

Exit codes:
    0  inventory emitted (possibly partial; see coverage_confidence)
    2  PATH is not a usable directory
"""

import argparse
import json
import sys
from pathlib import Path

from inventorylib.report import build_inventory


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="profile_inventory.py",
        description="Emit a deterministic JSON inventory of a repository.")
    parser.add_argument("path", nargs="?", default=".",
                        help="repo root to inventory (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON (default; accepted for explicitness)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": "not a directory: %s" % args.path}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(build_inventory(root), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
