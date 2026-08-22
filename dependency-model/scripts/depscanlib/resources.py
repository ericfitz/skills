"""Extract declared resource figures from Dockerfiles, compose, and k8s.

Every figure here is a declared one. Per D3 nothing is measured, so a value
this module cannot find in a file simply is not reported.

Text and regex, not a YAML parse: depscanlib is stdlib-only so depscan.py
runs under bare python3 with no dependencies.
"""

import re
from pathlib import PurePosixPath

from depscanlib.walk import read_text

DOCKERFILE_NAMES = {"Dockerfile", "Containerfile"}

K8S_CPU_RE = re.compile(r'^\s*cpu:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
K8S_MEMORY_RE = re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?\s*$')
K8S_GPU_RE = re.compile(r'^\s*[\w.\-/]*gpu:\s*["\']?([^"\'\n#]+?)["\']?\s*$',
                        re.IGNORECASE)
K8S_STORAGE_RE = re.compile(r'^\s*(?:ephemeral-)?storage:\s*["\']?([^"\'\n#]+?)["\']?\s*$')

COMPOSE_RES_RES = (
    (re.compile(r'^\s*mem_limit:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*mem_reservation:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
    (re.compile(r'^\s*cpus:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "cpu"),
    (re.compile(r'^\s*cpu_shares:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "cpu"),
    (re.compile(r'^\s*shm_size:\s*["\']?([^"\'\n#]+?)["\']?\s*$'), "memory"),
)

FROM_RE = re.compile(
    r'^\s*FROM\s+(?:--platform=(?P<platform>\S+)\s+)?(?P<image>\S+)',
    re.IGNORECASE)


def _record(kind, raw, path, line, source):
    return {"kind": kind, "raw": raw.strip(), "file": path, "line": line,
            "source": source}


def _scan_dockerfile(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        match = FROM_RE.match(line)
        if not match:
            continue
        if match.group("platform"):
            out.append(_record("arch", match.group("platform"), path, number,
                               "dockerfile"))
        out.append(_record("runtime-version", match.group("image"), path, number,
                           "dockerfile"))


def _scan_kubernetes(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        for pattern, kind in ((K8S_GPU_RE, "gpu"), (K8S_CPU_RE, "cpu"),
                              (K8S_MEMORY_RE, "memory"), (K8S_STORAGE_RE, "disk")):
            match = pattern.match(line)
            if match:
                out.append(_record(kind, match.group(1), path, number,
                                   "kubernetes"))
                break


def _scan_compose(root, path, out):
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        for pattern, kind in COMPOSE_RES_RES:
            match = pattern.match(line)
            if match:
                out.append(_record(kind, match.group(1), path, number, "compose"))
                break


def scan_resources(root, paths, files):
    """Return declared resource figures, sorted by file then line.

    files is classify_files()'s result: only files it recognised as compose or
    kubernetes are read that way, so an ordinary config.yaml with a `cpu:` key
    is never mistaken for a manifest.
    """
    out = []
    for path in sorted(files.get("k8s", [])):
        _scan_kubernetes(root, path, out)
    for path in sorted(files.get("compose", [])):
        _scan_compose(root, path, out)
    for path in sorted(paths):
        if PurePosixPath(path).name in DOCKERFILE_NAMES:
            _scan_dockerfile(root, path, out)
    return sorted(out, key=lambda r: (r["file"], r["line"], r["kind"]))
