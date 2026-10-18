#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the shared id list for a profile:topology contract.

Read-only apart from the optional ids.json: this reads the topology contract
and derives `component:<slug>` and `service:<slug>` ids with the same function
depgraph.py uses, so every script and skill agrees on them.

Usage:
    uv run --script idmap.py TOPOLOGY.json [--write]

Without --write the document is printed. With --write it is written to
ids.json beside TOPOLOGY.json (temp file + os.replace) and the absolute path
is printed.

Exit codes:
    0  the document was printed or written
    2  nothing written: the topology is unreadable or not a JSON object, a
       list entry lacks a string `name`, a name cannot be slugged, or two
       names collide even after the fallback
"""

import argparse
import json
import os
import sys
import tempfile

from depgraphlib.ids import assign_ids

SERVICE_SOURCES = ("real_dependencies", "external_third_parties")


def _fail(message):
    json.dump({"error": message}, sys.stderr)
    sys.stderr.write("\n")
    return 2


def _names(topology, key):
    entries = topology.get(key)
    if entries is None:
        return []
    if not isinstance(entries, list):
        raise ValueError(f"{key} must be a list, got {type(entries).__name__}")
    names = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"{key}[{i}] is not an object")
        if not isinstance(entry.get("name"), str):
            raise ValueError(f"{key}[{i}] has no string `name`")
        names.append(entry["name"])
    return names


def build_document(topology):
    component_names = _names(topology, "components")
    component_ids = assign_ids(component_names, "component")
    component_parts = {cid.partition(":")[2] for cid in component_ids.values()}

    sources = {}
    for key in SERVICE_SOURCES:
        for name in _names(topology, key):
            sources.setdefault(name, key)
    service_ids = assign_ids(list(sources), "service")

    services, skipped = [], []
    for name, sid in service_ids.items():
        if sid.partition(":")[2] in component_parts:
            skipped.append({"name": name, "reason":
                            f"matches component:{sid.partition(':')[2]}; "
                            "the system's own listener, not a service"})
        else:
            services.append({"id": sid, "name": name, "source": sources[name]})
    return {
        "components": sorted(({"id": cid, "name": n} for n, cid in component_ids.items()),
                             key=lambda e: e["id"]),
        "services": sorted(services, key=lambda e: e["id"]),
        "skipped": sorted(skipped, key=lambda e: e["name"]),
    }


def write_atomic(path, text):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".ids-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="idmap.py",
        description="Write the shared component/service id list for a topology contract.")
    parser.add_argument("topology", metavar="TOPOLOGY.json",
                        help="profile:topology contract")
    parser.add_argument("--write", action="store_true",
                        help="write ids.json beside the topology file and print its path")
    args = parser.parse_args(argv)

    try:
        with open(args.topology, encoding="utf-8") as f:
            topology = json.load(f)
    except (OSError, ValueError) as exc:
        return _fail(f"unreadable input: {args.topology}: {exc}")
    if not isinstance(topology, dict):
        return _fail(f"{args.topology}: top level must be a JSON object")

    try:
        document = build_document(topology)
    except (ValueError, TypeError) as exc:
        return _fail(f"ids: {exc}")

    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if not args.write:
        sys.stdout.write(text)
        return 0
    out = os.path.join(os.path.dirname(os.path.abspath(args.topology)), "ids.json")
    try:
        write_atomic(out, text)
    except OSError as exc:
        return _fail(f"cannot write {out}: {exc}")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
