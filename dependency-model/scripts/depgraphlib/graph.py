"""Typed edges and cycle detection over a merged discovery inventory.

Turns the merged `{"categories": {...}}` document into a graph document:
one node per discovered dependency plus one per first-party component from
the topology contract, one edge per relationship between them, and the cycles
found in the depends_on graph. An edge whose target is not a
node is never dropped silently: it is listed under `unresolved` for the
caller to reconcile. That cycle list is not an
exhaustive enumeration of every simple cycle in the graph — see
`_find_cycles` for why.
"""


class InvalidDependencyError(ValueError):
    """A dependency entry in the merged inventory is missing a field
    (`id`, `name`, or `lifecycle`) the graph requires."""


def _require(d, field, category):
    try:
        return d[field]
    except KeyError as exc:
        raise InvalidDependencyError(
            f"dependency in category {category!r} is missing required "
            f"field {field!r}: {d!r}") from exc


def slug(name):
    """The id slug rule from references/categories.md (Ids): lowercase; `_`,
    spaces and `/` become `-`; `.` stays."""
    return name.lower().replace("_", "-").replace(" ", "-").replace("/", "-")


def component_nodes(components):
    """Graph nodes for the topology contract's first-party components. They
    are not dependencies, so they never enter the inventory; category
    `component`, lifecycle `run` (the component is the running thing)."""
    return [{"id": f"component:{slug(c['name'])}", "name": c["name"],
             "category": "component", "lifecycle": "run"} for c in components or []]


def _build_nodes(merged, components=None):
    nodes = component_nodes(components)
    for category, block in merged.get("categories", {}).items():
        for d in block.get("dependencies") or []:
            nodes.append({"id": _require(d, "id", category),
                          "name": _require(d, "name", category),
                          "category": category,
                          "lifecycle": _require(d, "lifecycle", category)})
    nodes.sort(key=lambda n: n["id"])
    return nodes


def canonical_id(id_):
    """The id-matching form: `config:TMI_NATS_URL` and `config:tmi-nats-url`
    are the same id written by two skills that slugged a key differently."""
    return id_.lower().replace("_", "-")


def _resolver(known_ids):
    """Map a written target id to a node id: exact match first, then a
    canonical match when exactly one node has that canonical form, then
    `service:<x>` to `component:<x>`: the system's own listener is not a
    service (categories.md, worked adjudications), so a skill that wrote
    `service:tmiserver` meant the first-party component."""
    by_canonical = {}
    for i in known_ids:
        by_canonical.setdefault(canonical_id(i), []).append(i)

    def resolve(target, _retry=True):
        if target in known_ids:
            return target
        matches = by_canonical.get(canonical_id(target), [])
        if len(matches) == 1:
            return matches[0]
        if _retry and target.startswith("service:"):
            return resolve("component:" + target[len("service:"):], _retry=False)
        return None
    return resolve


def _build_edges(merged, known_ids):
    resolve = _resolver(known_ids)
    edges, unresolved = set(), set()
    for category, block in merged.get("categories", {}).items():
        for d in block.get("dependencies") or []:
            source = _require(d, "id", category)
            lifecycle = _require(d, "lifecycle", category)
            links = [(t, "depends_on") for t in d.get("details", {}).get("depends_on") or []]
            links += [(t, "relates_to") for t in d.get("related_ids") or []]
            for target, kind in links:
                node = resolve(target)
                if node is None:
                    unresolved.add((source, target, kind))
                else:
                    edges.add((source, node, kind, lifecycle))
    return ([{"from": f, "to": t, "kind": k, "lifecycle": lc}
             for f, t, k, lc in sorted(edges, key=lambda e: (e[0], e[1], e[2]))],
            [{"from": f, "to": t, "kind": k} for f, t, k in sorted(unresolved)])


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

    Not an exhaustive enumeration of every simple cycle: a global-visited
    DFS back-edge walk reports one representative cycle per exploration, not
    every simple cycle through a node. Complete enumeration would need
    Tarjan SCC + Johnson's algorithm; the cycles reported here are real, but
    the list is not guaranteed complete.
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

    cycles.sort(key=tuple)
    return cycles


def link_graph(merged, components=None):
    """Return (graph, unresolved) from a merged inventory and, optionally, the
    topology contract's `components[]`.

    `graph` is {"nodes", "edges", "cycles"}, the synthesis contract's shape.
    `unresolved` lists {"from", "to", "kind"} links whose target matched no
    node; it is not part of the contract, and synthesize reconciles it.
    """
    nodes = _build_nodes(merged, components)
    known_ids = {n["id"] for n in nodes}
    edges, unresolved = _build_edges(merged, known_ids)
    adjacency = _depends_on_adjacency(edges)
    cycles = _find_cycles(known_ids, adjacency)
    return {"nodes": nodes, "edges": edges, "cycles": cycles}, unresolved


def build_graph(merged, components=None):
    """Return {"nodes": [...], "edges": [...], "cycles": [...]} from a merged inventory."""
    return link_graph(merged, components)[0]
