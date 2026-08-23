#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Merge dependency-model discovery envelopes into a single graph document.

Read-only: this reads envelope JSON files and merges them in memory. It
resolves no names, opens no sockets, boots no containers, and runs no build.

Usage:
    uv run --script depgraph.py ENVELOPE.json [...] [--indent N]
    python3 depgraph.py ENVELOPE.json [...] [--indent N]   # fallback; no deps

Exit codes:
    0  graph document emitted
    2  an input envelope was unreadable (missing or invalid JSON), or a
       dependency entry is missing a required field (id, name, or lifecycle)
       or is otherwise malformed (e.g. a bare string instead of an object,
       or a category value that isn't a dict)
"""

import argparse
import json
import sys

from depgraphlib.graph import InvalidDependencyError, build_graph
from depgraphlib.merge import merge_envelopes
from depgraphlib.mermaid import to_mermaid


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="depgraph.py",
        description="Merge dependency-model discovery envelopes into a graph document.")
    parser.add_argument("envelopes", nargs="+", metavar="ENVELOPE.json",
                        help="discovery envelope JSON files to merge")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    loaded = []
    for path in args.envelopes:
        try:
            with open(path, encoding="utf-8") as f:
                loaded.append(json.load(f))
        except (OSError, json.JSONDecodeError) as exc:
            json.dump({"error": f"unreadable envelope: {path}: {exc}"}, sys.stderr)
            sys.stderr.write("\n")
            return 2

    try:
        merged = merge_envelopes(loaded)
        graph = build_graph(merged)
    except (InvalidDependencyError, TypeError, AttributeError) as exc:
        # Envelopes are produced by LLM agents; a malformed shape (a bare
        # string where a dependency object belongs, a null details object, a
        # category value that isn't a dict) is the realistic failure mode.
        # Some of these crash in merge_envelopes before build_graph's own
        # InvalidDependencyError ever gets a chance to fire, so both calls
        # share this one handler.
        json.dump({"error": f"invalid dependency: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    document = {"inventory": merged, "graph": graph, "mermaid": to_mermaid(graph)}

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(document, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
