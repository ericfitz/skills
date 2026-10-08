"""Mechanical health derivation over depgraph.py's output.

Implements the failability test in references/definitions.md as far as the
layer-1 envelopes record it. The test itself is "can this fail independently
while the process is up"; the envelopes answer it only through category,
`details.kind`, `details.mechanism`, and lifecycle, so those fields are the
approximation used here -- not the rule. It diverges from the real test
exactly where layer 1 records nothing: a dynamically loaded package has no
loading-site field, so every package is treated as bundled and the skill
records that gap.

Judgment stays in the skill: `required_for` is always empty here.
"""

KIND_RANK = {"presence": 0, "bound": 1, "upstream_health": 2}
RESOURCE_LIMITS = frozenset({"cpu", "memory", "disk", "gpu"})
FIXED_PLATFORM = frozenset({"runtime-version", "os", "arch"})


def is_anchor(node):
    """A node that gets a health entry: a `run` service, or a first-party
    component from the topology contract (#83)."""
    if node["category"] == "component":
        return True
    return node["category"] == "service" and node["lifecycle"] == "run"


def _kind_for(dep, category):
    """The condition kind a dependency contributes to an anchor, or None when
    it cannot fail while the process is up (a bundled package, a build-only
    dependency, a runtime version baked into the image)."""
    if category == "package" or dep.get("lifecycle") == "build":
        return None
    if category == "service":
        return "upstream_health"
    if category == "platform":
        kind = (dep.get("details") or {}).get("kind")
        if kind in RESOURCE_LIMITS:
            return "bound"
        if kind in FIXED_PLATFORM:
            return None
    return "presence"


def _stands_alone(dep, category):
    """Failable with no service link: an env/file/flag config key is read at
    startup and cannot change under a running process; remote config can."""
    if _kind_for(dep, category) is None:
        return False
    if category == "config":
        return (dep.get("details") or {}).get("mechanism") == "remote"
    return True


def _declared(value, evidence):
    return {"value": value, "evidence": list(evidence or [])}


def _neighbor_condition(dep, category):
    kind = _kind_for(dep, category)
    if kind is None:
        return None
    evidence = list(dep.get("evidence") or [])
    expectation = None
    if kind == "bound":
        declared = (dep.get("details") or {}).get("declared_value")
        if declared:
            expectation = _declared(declared, evidence)
    return {"kind": kind, "subject_id": dep["id"], "expectation": expectation,
            "required_for": [], "evidence": evidence}


def _own_bounds(dep):
    """timeout is always a bound (null expectation = no declaration found);
    retry only when declared."""
    res = dep.get("resilience") or {}
    conditions = []
    timeout, retry = res.get("timeout"), res.get("retry")
    if timeout:
        conditions.append({"kind": "bound", "subject_id": dep["id"],
                           "expectation": _declared(f"timeout: {timeout.get('value')}",
                                                    timeout.get("evidence")),
                           "required_for": [], "evidence": list(timeout.get("evidence") or [])})
    else:
        conditions.append({"kind": "bound", "subject_id": dep["id"], "expectation": None,
                           "required_for": [], "evidence": list(dep.get("evidence") or [])})
    if retry:
        conditions.append({"kind": "bound", "subject_id": dep["id"],
                           "expectation": _declared(f"retry: {retry.get('description')}",
                                                    retry.get("evidence")),
                           "required_for": [], "evidence": list(retry.get("evidence") or [])})
    return conditions


def _sort_key(c):
    return (KIND_RANK[c["kind"]], c["subject_id"],
            (c["expectation"] or {}).get("value") or "")


def derive_health(document):
    """Return {"health": [...], "unattached": [...]} from depgraph.py output.

    `unattached` lists failable dependencies linked to no anchor: the contract
    keys health on an anchor id, so they have no entry to go in.

    An anchor's neighbours are the nodes its edges reach directly, plus the
    network paths reached from those through other network paths only: an
    ingress that fronts a listener is still the path to the component behind
    it. A component has no inventory entry, so it carries no own bounds and
    gets no entry when nothing links to it.
    """
    deps, category_of = {}, {}
    for category, block in document["inventory"]["categories"].items():
        for d in block.get("dependencies") or []:
            deps[d["id"]] = d
            category_of[d["id"]] = category
    nodes = {n["id"]: n for n in document["graph"]["nodes"]}
    anchors = {i for i, n in nodes.items() if is_anchor(n)}

    adjacent = {}
    for e in document["graph"]["edges"]:
        pairs = [(e["from"], e["to"])]
        if e["kind"] == "relates_to":
            pairs.append((e["to"], e["from"]))
        for a, b in pairs:
            if b != a and b in deps:
                adjacent.setdefault(a, set()).add(b)

    # ponytail: walks through every network node; a shared hub (one egress rule
    # many hosts relate to) would attach them all. Stop at details.direction
    # != "inbound", or at high-degree nodes, if that shows up in a real run.
    neighbors = {}
    for anchor in anchors:
        reached = set(adjacent.get(anchor, ()))
        frontier = [n for n in reached if category_of[n] == "network"]
        while frontier:
            for n in adjacent.get(frontier.pop(), ()):
                if n != anchor and n not in reached and category_of[n] == "network":
                    reached.add(n)
                    frontier.append(n)
        neighbors[anchor] = reached

    health, linked = [], set()
    for anchor in sorted(anchors):
        conditions = _own_bounds(deps[anchor]) if anchor in deps else []
        for n in neighbors[anchor]:
            c = _neighbor_condition(deps[n], category_of[n])
            if c:
                conditions.append(c)
                linked.add(n)
        unique = {}
        for c in conditions:
            unique.setdefault(_sort_key(c), c)
        if unique:
            health.append({"service_id": anchor,
                           "conditions": [unique[k] for k in sorted(unique)]})

    unattached = sorted(i for i, d in deps.items()
                        if i not in anchors and i not in linked
                        and _stands_alone(d, category_of[i]))
    return {"health": health, "unattached": unattached}
