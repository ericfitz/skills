#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Derive build-vs-run lifecycle for packages that syft cannot classify.

syft does not distinguish dev from runtime dependencies, and it fails
differently per ecosystem: Python/uv reports both from one lockfile with
identical metadata, while npm silently drops devDependencies entirely.

So classify declared roots from the manifest, then propagate to transitives
over syft's dependency-of edges.

Usage:
    uv run --script pkglifecycle.py <repo> --syft-json <file>
    python3 pkglifecycle.py <repo> --syft-json <file>   # fallback; no deps

Exit codes:
    0  emitted
    2  repo path or syft JSON unusable
"""

import argparse
import json
import re
import sys
import tomllib
from collections import deque
from pathlib import Path

BUILD, RUN = "build", "run"

# Strip everything from the first specifier character on: "pyyaml>=6.0" -> "pyyaml",
# "requests[socks]" -> "requests". Names themselves never contain these.
_SPECIFIER = re.compile(r"[<>=!~\[\s;].*$")


def _name(raw):
    return _SPECIFIER.sub("", str(raw)).strip().lower()


def _load_toml(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return None


def _pyproject(path, out):
    data = _load_toml(path)
    if not data:
        return
    project = data.get("project") or {}
    for dep in project.get("dependencies") or []:
        out[_name(dep)] = RUN
    # An extra ships when selected; it is not a dev tool.
    for deps in (project.get("optional-dependencies") or {}).values():
        for dep in deps:
            out.setdefault(_name(dep), RUN)
    for deps in (data.get("dependency-groups") or {}).values():
        for dep in deps:
            out.setdefault(_name(dep), BUILD)


def _package_json(path, out):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for dep in (data.get("dependencies") or {}):
        out[_name(dep)] = RUN
    for dep in (data.get("devDependencies") or {}):
        out.setdefault(_name(dep), BUILD)


def _cargo(path, out):
    data = _load_toml(path)
    if not data:
        return
    for dep in (data.get("dependencies") or {}):
        out[_name(dep)] = RUN
    for dep in (data.get("dev-dependencies") or {}):
        out.setdefault(_name(dep), BUILD)


_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([a-z0-9][\w.\-/]*\.[\w.\-/]+)\s+v\S+",
                         re.IGNORECASE)


def _go_mod(path, out):
    # Go has no dev-dependency concept: everything required is a run dependency.
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        match = _GO_REQUIRE.match(line)
        if match:
            out[_name(match.group(1))] = RUN


MANIFESTS = {
    "pyproject.toml": _pyproject,
    "package.json": _package_json,
    "Cargo.toml": _cargo,
    "go.mod": _go_mod,
}

# Ecosystems we can detect but not classify. Their presence becomes an
# assumption rather than a silent gap.
UNPARSEABLE = {
    "Gemfile": "ruby", "composer.json": "php", "pom.xml": "java",
    "build.gradle": "java", "build.gradle.kts": "java",
}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist",
             "build", "target", "site-packages", "__pycache__"}


def _walk(root):
    for path in Path(root).rglob("*"):
        if path.is_file() and not any(p in SKIP_DIRS for p in path.parts):
            yield path


def classify_roots(root):
    """Return {lowercased package name: build|run} from every manifest found."""
    out = {}
    for path in sorted(_walk(root)):
        handler = MANIFESTS.get(path.name)
        if handler:
            handler(path, out)
    return out


def unresolved_ecosystems(root):
    """Ecosystems present but not classifiable, for an assumption record."""
    found = {UNPARSEABLE[p.name] for p in _walk(root) if p.name in UNPARSEABLE}
    return sorted(found)


def propagate(roots, artifacts, relationships):
    """Map syft artifact id to build|run.

    A dependency-of edge {parent: A, child: B} means A is a dependency of B, so
    walking outward from a root follows edges where child is the current node.
    run wins over build: a package pulled in by both a dev tool and the app ships.
    """
    by_id = {a["id"]: str(a.get("name", "")).lower() for a in artifacts}
    children_of = {}
    for rel in relationships:
        if rel.get("type") != "dependency-of":
            continue
        children_of.setdefault(rel["child"], []).append(rel["parent"])

    out = {}
    for lifecycle in (BUILD, RUN):  # run second so it overwrites build
        seeds = [i for i, name in by_id.items() if roots.get(name) == lifecycle]
        seen, queue = set(seeds), deque(seeds)
        while queue:
            node = queue.popleft()
            out[node] = lifecycle
            for nxt in children_of.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

    for artifact_id in by_id:
        out.setdefault(artifact_id, RUN)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pkglifecycle.py",
        description="Derive build-vs-run lifecycle for syft-catalogued packages.")
    parser.add_argument("path", help="repo root")
    parser.add_argument("--syft-json", required=True, help="syft-json output file")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": f"not a directory: {args.path}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    try:
        syft = json.loads(Path(args.syft_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        json.dump({"error": f"cannot read syft json: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    lifecycle = propagate(classify_roots(root),
                          syft.get("artifacts") or [],
                          syft.get("artifactRelationships") or [])
    indent = args.indent if args.indent > 0 else None
    print(json.dumps({"lifecycle": lifecycle,
                      "unresolved": unresolved_ecosystems(root)},
                     indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
