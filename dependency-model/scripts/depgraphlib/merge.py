"""Key-union merge of the six discovery envelopes.

Each discovery skill emits a full envelope with exactly one category
populated, so merging is a key union rather than a transform.
"""


def merge_envelopes(envelopes):
    """Return {"categories": {...}} from any number of discovery envelopes.

    status is never flattened: a failed scan and an empty result are different
    findings, and collapsing them would let a report state as fact that a
    system has no dependencies of a kind when the scan simply broke.
    """
    categories = {}
    for envelope in envelopes:
        for name, block in (envelope.get("categories") or {}).items():
            target = categories.setdefault(
                name, {"status": block.get("status", "discovered"),
                       "dependencies": [], "assumptions": []})
            if block.get("status") == "failed":
                target["status"] = "failed"
            seen = {d["id"] for d in target["dependencies"] if "id" in d}
            for dep in block.get("dependencies") or []:
                if dep.get("id") not in seen:
                    target["dependencies"].append(dep)
                    seen.add(dep.get("id"))
            target["assumptions"].extend(block.get("assumptions") or [])
    for block in categories.values():
        block["dependencies"].sort(key=lambda d: d.get("id", ""))
    return {"categories": categories}
