"""Typed edges and cycle detection over a merged discovery inventory.

Turns the merged `{"categories": {...}}` document into a graph document:
one node per discovered dependency, one edge per relationship between them,
and the cycles found in the depends_on graph.
"""


def _build_nodes(merged):
    nodes = []
    for category, block in merged.get("categories", {}).items():
        for d in block.get("dependencies") or []:
            nodes.append({"id": d["id"], "name": d["name"],
                          "category": category, "lifecycle": d["lifecycle"]})
    nodes.sort(key=lambda n: n["id"])
    return nodes


def _build_edges(merged, known_ids):
    edges = set()
    for block in merged.get("categories", {}).values():
        for d in block.get("dependencies") or []:
            source = d["id"]
            lifecycle = d["lifecycle"]
            for target in d.get("details", {}).get("depends_on") or []:
                if target in known_ids:
                    edges.add((source, target, "depends_on", lifecycle))
            for target in d.get("related_ids") or []:
                if target in known_ids:
                    edges.add((source, target, "relates_to", lifecycle))
    return [{"from": f, "to": t, "kind": k, "lifecycle": lc}
            for f, t, k, lc in sorted(edges, key=lambda e: (e[0], e[1], e[2]))]


def _depends_on_adjacency(edges):
    adjacency = {}
    for e in edges:
        if e["kind"] == "depends_on":
            adjacency.setdefault(e["from"], []).append(e["to"])
    for targets in adjacency.values():
        targets.sort()
    return adjacency


def _rotate_to_smallest(cycle):
    start = cycle.index(min(cycle))
    return cycle[start:] + cycle[:start]


def _find_cycles(node_ids, adjacency):
    """Iterative depth-first search for cycles in the depends_on graph.

    Uses an explicit stack rather than recursion: a real package graph is
    deep enough to blow Python's recursion limit.
    """
    cycles = []
    seen_cycles = set()
    global_visited = set()

    for start in sorted(node_ids):
        if start in global_visited:
            continue
        # Each stack frame: (node, iterator index into adjacency[node]).
        path = [start]
        path_set = {start}
        index_stack = [0]
        global_visited.add(start)

        while path:
            node = path[-1]
            neighbors = adjacency.get(node, [])
            idx = index_stack[-1]
            if idx < len(neighbors):
                index_stack[-1] += 1
                neighbor = neighbors[idx]
                if neighbor in path_set:
                    cycle_start = path.index(neighbor)
                    cycle = _rotate_to_smallest(path[cycle_start:])
                    key = tuple(cycle)
                    if key not in seen_cycles:
                        seen_cycles.add(key)
                        cycles.append(cycle)
                elif neighbor not in global_visited:
                    global_visited.add(neighbor)
                    path.append(neighbor)
                    path_set.add(neighbor)
                    index_stack.append(0)
            else:
                path.pop()
                index_stack.pop()
                path_set.discard(node)

    cycles.sort(key=lambda c: c[0])
    return cycles


def build_graph(merged):
    """Return {"nodes": [...], "edges": [...], "cycles": [...]} from a merged inventory."""
    nodes = _build_nodes(merged)
    known_ids = {n["id"] for n in nodes}
    edges = _build_edges(merged, known_ids)
    adjacency = _depends_on_adjacency(edges)
    cycles = _find_cycles(known_ids, adjacency)
    return {"nodes": nodes, "edges": edges, "cycles": cycles}
