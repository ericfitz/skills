"""Extract declared resource figures from Dockerfiles, compose, and k8s.

Every figure here is a declared one. Per D3 nothing is measured, so a value
this module cannot find in a file simply is not reported.

Text and regex, not a YAML parse: depscanlib is stdlib-only so depscan.py
runs under bare python3 with no dependencies.
"""

import re
from pathlib import PurePosixPath

from depscanlib.walk import read_text

# A trailing `# ...` comment is ordinary on a hand-maintained resource line
# (`memory: 2Gi  # raised after OOM`); every pattern below tolerates one so a
# comment doesn't silently drop the whole line.
_COMMENT_TAIL = r'\s*(?:#.*)?$'

DOCKERFILE_NAMES = {"Dockerfile", "Containerfile"}


def _is_dockerfile_name(name):
    """True for Dockerfile/Containerfile and common variant conventions.

    Covers exact names, `Dockerfile.dev`-style suffixes, and
    `backend.dockerfile`-style extensions, case-insensitively for the
    variant forms.
    """
    if name in DOCKERFILE_NAMES:
        return True
    lower = name.lower()
    return (lower.startswith("dockerfile.") or lower.startswith("containerfile.") or
            lower.endswith(".dockerfile"))


K8S_CPU_RE = re.compile(r'^\s*cpu:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL)
K8S_MEMORY_RE = re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL)
K8S_GPU_RE = re.compile(r'^\s*[\w.\-/]*gpu:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL,
                        re.IGNORECASE)
K8S_STORAGE_RE = re.compile(r'^\s*(?:ephemeral-)?storage:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL)

COMPOSE_RES_RES = (
    (re.compile(r'^\s*mem_limit:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "memory"),
    (re.compile(r'^\s*mem_reservation:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "memory"),
    (re.compile(r'^\s*memory:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "memory"),
    (re.compile(r'^\s*cpus:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "cpu"),
    (re.compile(r'^\s*cpu_shares:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "cpu"),
    (re.compile(r'^\s*shm_size:\s*["\']?([^"\'\n#]+?)["\']?' + _COMMENT_TAIL), "memory"),
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
        if _is_dockerfile_name(PurePosixPath(path).name):
            _scan_dockerfile(root, path, out)
    return sorted(out, key=lambda r: (r["file"], r["line"], r["kind"]))
