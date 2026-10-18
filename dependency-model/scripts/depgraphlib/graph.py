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

import contextlib

from depgraphlib.ids import assign_ids, slug


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


def dedupe_components(components):
    """The topology's components with repeated names collapsed to the first,
    so the graph and ids.json agree on one node per name."""
    seen, unique = set(), []
    for c in components or []:
        if c["name"] not in seen:
            seen.add(c["name"])
            unique.append(c)
    return unique


def component_nodes(components):
    """Graph nodes for the topology contract's first-party components. They
    are not dependencies, so they never enter the inventory; category
    `component`, lifecycle `run` (the component is the running thing)."""
    components = dedupe_components(components)
    ids = assign_ids([c["name"] for c in components], "component")
    return [{"id": ids[c["name"]], "name": c["name"],
             "category": "component", "lifecycle": "run"} for c in components]


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


def _category_and_rest(id_):
    category, _, rest = id_.partition(":")
    return category, rest


def _resolver(nodes):
    """Map a written target id to a node id. In order: exact match; canonical
    match; `service:<x>` to `component:<x>` (the system's own listener is not
    a service: categories.md, worked adjudications); the re-slugged id part
    against every node's re-slugged id part; the re-slugged id part against
    every node's slugged name. The first step that finds any candidate
    decides: exactly one resolves, several leave the link unresolved. The
    re-slug and name steps look only at nodes in the target's category. A
    target whose id part cannot be slugged is left unresolved."""
    known_ids = {n["id"] for n in nodes}
    by_canonical = {}
    by_reslug = {}
    by_name = {}
    for n in nodes:
        by_canonical.setdefault(canonical_id(n["id"]), []).append(n["id"])
        category, rest = _category_and_rest(n["id"])
        for index, text in ((by_reslug, rest), (by_name, n["name"])):
            with contextlib.suppress(ValueError):
                index.setdefault((category, slug(text)), []).append(n["id"])

    def resolve(target):
        if target in known_ids:
            return target
        steps = [by_canonical.get(canonical_id(target), [])]
        if target.startswith("service:"):
            component = "component:" + target[len("service:"):]
            steps.append([component] if component in known_ids
                         else by_canonical.get(canonical_id(component), []))
        category, rest = _category_and_rest(target)
        try:
            key = (category, slug(rest))
        except ValueError:
            key = None
        if key is not None:
            steps += [by_reslug.get(key, []), by_name.get(key, [])]
        for candidates in steps:
            if candidates:
                return candidates[0] if len(set(candidates)) == 1 else None
        return None
    return resolve


def _build_edges(merged, nodes):
    resolve = _resolver(nodes)
    component_ids = {n["id"] for n in nodes if n["category"] == "component"}
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
            if category != "service":
                continue
            for use in d.get("details", {}).get("used_by") or []:
                if not isinstance(use, dict):
                    raise InvalidDependencyError(
                        f"used_by entry of {source!r} is not an object: {use!r}")
                target = _require(use, "component_id", category)
                node = resolve(target)
                if node in component_ids:
                    edges.add((node, source, "depends_on", "run"))
                else:
                    unresolved.add((source, target, "used_by"))
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
    edges, unresolved = _build_edges(merged, nodes)
    adjacency = _depends_on_adjacency(edges)
    cycles = _find_cycles({n["id"] for n in nodes}, adjacency)
    return {"nodes": nodes, "edges": edges, "cycles": cycles}, unresolved


def build_graph(merged, components=None):
    """Return {"nodes": [...], "edges": [...], "cycles": [...]} from a merged inventory."""
    return link_graph(merged, components)[0]
