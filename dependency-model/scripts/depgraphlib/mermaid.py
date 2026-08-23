"""Emit Mermaid flowchart source from a dependency graph.

Node ids are opaque (n0, n1, ...) with the real name in a quoted label: real
package names like @babel/core, github.com/sony/gobreaker and x[1] are not
valid Mermaid identifiers, but they render correctly as labels.

Escaping is verified against mmdc: a raw double quote inside a quoted label
breaks parsing, and #quot; is the escape that works. #, <, > and ; are fine.
"""

CAP_DEFAULT = 60


def _label(name):
    return str(name).replace('"', "#quot;")


def to_mermaid(graph, cap=CAP_DEFAULT):
    nodes = sorted(graph.get("nodes") or [], key=lambda n: n["id"])
    count = len(nodes)
    if count > cap:
        return {"mermaid": None, "degraded": True, "node_count": count,
                "reason": f"{count} nodes exceeds the {cap}-node Mermaid cap; "
                          f"a rendered graph this size is unreadable"}

    index = {node["id"]: f"n{i}" for i, node in enumerate(nodes)}
    lines = ["flowchart LR"]
    lines += [f'  {index[n["id"]]}["{_label(n["name"])}"]' for n in nodes]
    for edge in sorted(graph.get("edges") or [],
                       key=lambda e: (e["from"], e["to"], e["kind"])):
        if edge["from"] in index and edge["to"] in index:
            arrow = "-->" if edge["kind"] == "depends_on" else "-.->"
            lines.append(f'  {index[edge["from"]]} {arrow} {index[edge["to"]]}')
    return {"mermaid": "\n".join(lines) + "\n", "degraded": False,
            "node_count": count, "reason": None}
