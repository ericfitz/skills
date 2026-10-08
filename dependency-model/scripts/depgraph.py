#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Merge dependency-model discovery envelopes into a single graph document.

Read-only: this reads envelope JSON files and merges them in memory. It
resolves no names, opens no sockets, boots no containers, and runs no build.

Usage:
    uv run --script depgraph.py ENVELOPE.json [...] [--topology topology.json] [--indent N]
    python3 depgraph.py ENVELOPE.json [...] [--indent N]   # fallback; no deps

--topology adds one `component:<slug>` graph node per first-party component
in the profile:topology contract, so links to the system's own components
resolve and health can key on them. The inventory is unchanged.

Exit codes:
    0  graph document emitted. Links (`related_ids`, `depends_on`) whose
       target matches no node are listed in the document's `unresolved`
       and counted on stderr; they are not an error.
    2  an input envelope or the topology file was unreadable (missing or
       invalid JSON), the envelopes came from different targets or refs, or a
       dependency entry is missing a required field (id, name, or lifecycle)
       or is otherwise malformed (e.g. a bare string instead of an object,
       or a category value that isn't a dict)
"""

import argparse
import json
import sys

from depgraphlib.graph import InvalidDependencyError, link_graph, slug
from depgraphlib.merge import MixedProvenanceError, merge_envelopes
from depgraphlib.mermaid import to_mermaid


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="depgraph.py",
        description="Merge dependency-model discovery envelopes into a graph document.")
    parser.add_argument("envelopes", nargs="+", metavar="ENVELOPE.json",
                        help="discovery envelope JSON files to merge")
    parser.add_argument("--topology", metavar="topology.json",
                        help="profile:topology contract; its components[] become "
                             "component:<slug> nodes")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    loaded = []
    for path in args.envelopes + ([args.topology] if args.topology else []):
        try:
            with open(path, encoding="utf-8") as f:
                loaded.append(json.load(f))
        except (OSError, json.JSONDecodeError) as exc:
            json.dump({"error": f"unreadable input: {path}: {exc}"}, sys.stderr)
            sys.stderr.write("\n")
            return 2
    topology = loaded.pop() if args.topology else {}

    try:
        components = [{"id": f"component:{slug(c['name'])}", "name": c["name"],
                       "role": c.get("role"), "evidence": list(c.get("evidence") or [])}
                      for c in topology.get("components") or []]
        merged = merge_envelopes(loaded)
        graph, unresolved = link_graph(merged, components)
    except MixedProvenanceError as exc:
        json.dump({"error": str(exc)}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    except (InvalidDependencyError, TypeError, AttributeError, KeyError) as exc:
        # Envelopes are produced by LLM agents; a malformed shape (a bare
        # string where a dependency object belongs, a null details object, a
        # category value that isn't a dict) is the realistic failure mode.
        # Some of these crash in merge_envelopes before build_graph's own
        # InvalidDependencyError ever gets a chance to fire, so both calls
        # share this one handler.
        json.dump({"error": f"invalid dependency: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    if unresolved:
        sys.stderr.write(f"depgraph.py: {len(unresolved)} link(s) match no node; "
                         "see `unresolved` in the output\n")
    document = {"inventory": merged, "components": components, "graph": graph,
                "mermaid": to_mermaid(graph), "unresolved": unresolved}

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(document, indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
