#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Derive the synthesis contract's health[] from depgraph.py's output.

Read-only and deterministic: the same depgraph document always yields
byte-identical output. The rules are in depgraphlib/health.py; synthesize's
SKILL.md says which fields the skill may refine afterwards.

Usage:
    uv run --script health.py DEPGRAPH_OUT.json [--indent N]
    python3 health.py DEPGRAPH_OUT.json [--indent N]   # fallback; no deps

Exit codes:
    0  {"health": [...], "unattached": [...]} emitted
    2  the input was unreadable, or is not a depgraph.py document
       (missing `inventory` or `graph`, or a malformed entry)
"""

import argparse
import json
import sys

from depgraphlib.health import derive_health


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="health.py",
        description="Derive health[] from depgraph.py output.")
    parser.add_argument("document", metavar="DEPGRAPH_OUT.json",
                        help="depgraph.py output (or a synthesis document)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    try:
        with open(args.document, encoding="utf-8") as f:
            result = derive_health(json.load(f))
    except (OSError, json.JSONDecodeError) as exc:
        json.dump({"error": f"unreadable document: {args.document}: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    except (KeyError, TypeError, AttributeError) as exc:
        json.dump({"error": f"not a depgraph.py document: {exc!r}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(result, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
