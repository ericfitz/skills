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
       or a category value that isn't a dict), or a topology component id
       cannot be built (the topology is not an object, a component lacks a
       string `name`, a name slugs to empty, or two names collide)
"""

import json
import sys

from depgraphlib.graph import InvalidDependencyError, dedupe_components, link_graph, role_conflicts
from depgraphlib.ids import assign_ids
from depgraphlib.merge import MixedProvenanceError, merge_envelopes
from depgraphlib.mermaid import to_mermaid
from jsonargs import JsonErrorParser


def main(argv=None):
    parser = JsonErrorParser(
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
        topo_components = dedupe_components(topology.get("components"))
        conflicts = role_conflicts(topology.get("components"))
        ids = assign_ids([c["name"] for c in topo_components], "component")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        json.dump({"error": f"component ids: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    try:
        components = [{"id": ids[c["name"]], "name": c["name"],
                       "role": c.get("role"), "evidence": list(c.get("evidence") or [])}
                      for c in topo_components]
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
    for name, roles in sorted(conflicts.items()):
        sys.stderr.write(f"depgraph.py: component {name!r} is listed with roles "
                         f"{', '.join(map(repr, roles))}; kept {roles[0]!r}\n")
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
