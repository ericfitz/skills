#!/usr/bin/env python3
"""Locate OpenAPI and Arazzo spec documents in a repository.

Searches only *.yaml/*.yml/*.json files for markers that strongly indicate a
real spec document — via ripgrep when available (which honors .gitignore in a
git repo), else a directory walk with a fixed exclude list. Each candidate is
verified: structural parse first (rules out grep false positives), then an
external validator (vacuum, redocly, spectral) when one is on PATH and
supports the document kind. Prints JSON findings to stdout; an empty result
is data, not an error.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

GLOBS = ("*.yaml", "*.yml", "*.json")
EXCLUDE_DIRS = {".git", "node_modules", "vendor", ".venv", "venv",
                "dist", "build", "target"}

# kind -> regexes a real spec's version line would match (line-anchored for
# YAML, key-quoted for JSON). Content-level checks happen in verify().
MARKERS = {
    "openapi": [r'^\s*openapi:\s*["\']?3', r'"openapi"\s*:\s*"3',
                r'^\s*swagger:\s*["\']?2\.0', r'"swagger"\s*:\s*"2\.0"'],
    "arazzo": [r'^\s*arazzo:\s*["\']?1', r'"arazzo"\s*:\s*"1'],
}

# name, kinds it can judge, argv builder. First installed match wins.
VALIDATORS = (
    ("vacuum", ("openapi",), lambda p: ["vacuum", "lint", str(p)]),
    ("redocly", ("openapi", "arazzo"), lambda p: ["redocly", "lint", str(p)]),
    ("spectral", ("openapi",), lambda p: ["spectral", "lint", str(p)]),
)


def _rg_candidates(root, kind):
    cmd = ["rg", "-l", "--no-messages"]
    for g in GLOBS:
        cmd += ["-g", g]
    for d in EXCLUDE_DIRS:
        cmd += ["-g", f"!**/{d}/**"]
    for pattern in MARKERS[kind]:
        cmd += ["-e", pattern]
    proc = subprocess.run([*cmd, str(root)], capture_output=True, text=True)
    # rg exits 1 on "no matches", which is not an error here.
    return sorted(Path(line) for line in proc.stdout.splitlines()
                  if line.strip())


def _walk_candidates(root, kind):
    regexes = [re.compile(p, re.M) for p in MARKERS[kind]]
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not any(path.match(g) for g in GLOBS):
            continue
        if EXCLUDE_DIRS.intersection(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(r.search(text) for r in regexes):
            found.append(path)
    return found


def find_candidate_files(root, kind):
    root = Path(root)
    if shutil.which("rg"):
        return _rg_candidates(root, kind)
    return _walk_candidates(root, kind)


def _structural(doc, kind):
    """Return (marker, ok, detail)."""
    if not isinstance(doc, dict):
        return "unknown", False, "document is not a mapping"
    if kind == "openapi":
        version = doc.get("openapi") or doc.get("swagger")
        label = ("swagger" if "swagger" in doc and "openapi" not in doc
                 else "openapi")
        if not version:
            return "unknown", False, "no openapi/swagger version field"
        marker = f"{label}-{version}"
        if "info" not in doc:
            return marker, False, "missing top-level info"
        if not any(k in doc for k in ("paths", "webhooks", "components")):
            return marker, False, "missing paths/webhooks/components"
        return marker, True, "structural checks passed"
    version = doc.get("arazzo")
    if not version:
        return "unknown", False, "no arazzo version field"
    marker = f"arazzo-{version}"
    if "info" not in doc:
        return marker, False, "missing top-level info"
    if "workflows" not in doc:
        return marker, False, "missing workflows"
    return marker, True, "structural checks passed"


def _external_validator(path, kind):
    for name, kinds, build in VALIDATORS:
        if kind in kinds and shutil.which(name):
            try:
                proc = subprocess.run(build(path), capture_output=True,
                                      text=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError) as exc:
                return name, None, f"{name} failed to run: {exc}"
            detail = (proc.stdout + proc.stderr).strip().splitlines()
            return name, proc.returncode == 0, (detail[0] if detail else "")
    return None, None, ""


def verify(path, root, kind):
    entry = {"path": str(Path(path).resolve().relative_to(
                 Path(root).resolve())),
             "marker": "unknown", "valid": False,
             "validator": "structural", "detail": ""}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        doc = (json.loads(text) if str(path).endswith(".json")
               else yaml.safe_load(text))
    except (ValueError, yaml.YAMLError) as exc:
        entry["detail"] = f"parse error: {exc}".splitlines()[0]
        return entry
    marker, ok, detail = _structural(doc, kind)
    entry.update(marker=marker, valid=ok, detail=detail)
    if ok:
        name, verdict, vdetail = _external_validator(path, kind)
        if verdict is not None:
            entry.update(validator=name, valid=verdict,
                         detail=vdetail or detail)
    return entry


def discover(root):
    root = Path(root)
    result = {}
    for kind in ("openapi", "arazzo"):
        entries = [verify(p, root, kind)
                   for p in find_candidate_files(root, kind)]
        entries.sort(key=lambda e: (not e["valid"],
                                    len(Path(e["path"]).parts), e["path"]))
        result[kind] = entries
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".",
                        help="repository root to search (default: .)")
    args = parser.parse_args(argv)
    print(json.dumps(discover(Path(args.root)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
