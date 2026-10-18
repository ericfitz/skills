"""Emit Mermaid flowchart source from a dependency graph.

Node ids are opaque (n0, n1, ...) with the real name in a quoted label: real
package names like @babel/core, github.com/sony/gobreaker and x[1] are not
valid Mermaid identifiers, but they render correctly as labels.

First-party components (category `component`) use the [[subroutine]] shape
so the system's own parts stand out from what they depend on.

Escaping is verified against mmdc: a raw double quote inside a quoted label
breaks parsing, and #quot; is the escape that works. #, <, > and ; are fine.
"""

CAP_DEFAULT = 60


def _label(name):
    return str(name).replace('"', "#quot;")


KEPT_CATEGORIES = ("component", "service")


def _render(entries, edges):
    """entries: [(key, label, shape_is_component)] in output order."""
    index = {key: f"n{i}" for i, (key, _, _) in enumerate(entries)}
    lines = ["flowchart LR"]
    for key, label, is_component in entries:
        open_, close = ('[["', '"]]') if is_component else ('["', '"]')
        lines.append(f"  {index[key]}{open_}{_label(label)}{close}")
    for src, dst, kind in sorted(edges):
        if src in index and dst in index:
            arrow = "-->" if kind == "depends_on" else "-.->"
            lines.append(f"  {index[src]} {arrow} {index[dst]}")
    return "\n".join(lines) + "\n"


def _result(mermaid, count, reason, view, collapsed, degraded):
    return {"mermaid": mermaid, "degraded": degraded, "node_count": count,
            "reason": reason, "view": view, "collapsed": collapsed}


def to_mermaid(graph, cap=CAP_DEFAULT):
    nodes = sorted(graph.get("nodes") or [], key=lambda n: n["id"])
    count = len(nodes)
    edges = {(e["from"], e["to"], e["kind"]) for e in graph.get("edges") or []}
    if count <= cap:
        entries = [(n["id"], n["name"], n["category"] == "component") for n in nodes]
        return _result(_render(entries, edges), count, None, "full", {}, False)

    kept = [n for n in nodes if n["category"] in KEPT_CATEGORIES]
    rolled = {}
    target = {n["id"]: n["id"] for n in kept}
    for n in nodes:
        if n["category"] not in KEPT_CATEGORIES:
            rolled[n["category"]] = rolled.get(n["category"], 0) + 1
            target[n["id"]] = f"rollup:{n['category']}"
    size = len(kept) + len(rolled)
    if size > cap:
        return _result(None, count,
                       f"{count} nodes exceeds the {cap}-node Mermaid cap, and the "
                       f"collapsed view still has {size} nodes; a rendered graph "
                       f"this size is unreadable", None, {}, True)

    entries = [(n["id"], n["name"], n["category"] == "component") for n in kept]
    entries += [(f"rollup:{cat}", f"{cat} ({rolled[cat]})", False) for cat in sorted(rolled)]
    mapped = {(target[a], target[b], kind) for a, b, kind in edges
              if a in target and b in target and target[a] != target[b]}
    reason = (f"{count} nodes exceeds the {cap}-node Mermaid cap; showing a collapsed "
              f"view of {size} nodes with the other categories rolled up")
    return _result(_render(entries, mapped), count, reason, "collapsed", rolled, False)
