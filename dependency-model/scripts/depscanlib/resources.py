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


# A resource figure is a number with an optional unit/suffix (`500m`, `2Gi`,
# `1.5`, `4G`, `0.5`). YAML booleans and prose (`true`, `default`) under a
# `storage:`/`memory:`-style key are not quantities.
QUANTITY_RE = re.compile(r'^\d+(?:\.\d+)?\s*[A-Za-z]{0,3}$')


def _is_quantity(raw):
    return bool(QUANTITY_RE.match(raw.strip()))


def _record(kind, raw, path, line, source, bound=None, component=None):
    """bound is "request" or "limit" (None when the file doesn't say)."""
    rec = {"kind": kind, "raw": raw.strip(), "file": path, "line": line,
           "source": source}
    if bound:
        rec["bound"] = bound
    if component:
        rec["component"] = component
    return rec


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


SECTION_RE = re.compile(r'^(\s*)(requests|limits|reservations):\s*(?:\{(.*)\})?' + _COMMENT_TAIL)
FLOW_PAIR_RE = re.compile(r'([\w.\-/]+):\s*["\']?([^"\',}]+)')
BOUNDS = {"requests": "request", "reservations": "request", "limits": "limit"}
K8S_KEY_KINDS = {"cpu": "cpu", "memory": "memory", "storage": "disk",
                 "ephemeral-storage": "disk"}
IMAGE_RE = re.compile(r'^(\s*)image:')
LIST_NAME_RE = re.compile(r'^(\s*)-\s+name:\s*["\']?([^"\'\s#]+)')
SERVICE_RE = re.compile(r'^  ([\w][\w.\-]*):\s*(?:#.*)?$')


def _flow_kind(key):
    return K8S_KEY_KINDS.get(key) or ("gpu" if key.lower().endswith("gpu") else None)


def _scan_kubernetes(root, path, out):
    lines = read_text(root, path).splitlines()
    section = None      # (indent, bound) of the enclosing requests:/limits: block
    component = None
    for number, line in enumerate(lines, start=1):
        if line.startswith("---"):
            section = component = None
        indent = len(line) - len(line.lstrip())
        if section and line.strip() and indent <= section[0]:
            section = None
        if IMAGE_RE.match(line):
            # the container's `- name:` sits just above, at the item level
            for prev in reversed(lines[max(0, number - 12):number - 1]):
                m = LIST_NAME_RE.match(prev)
                if m and len(m.group(1)) + 2 == indent:
                    component = m.group(2)
                    break
        m = SECTION_RE.match(line)
        if m:
            bound = BOUNDS[m.group(2)]
            if m.group(3) is not None:
                for key, value in FLOW_PAIR_RE.findall(m.group(3)):
                    kind = _flow_kind(key)
                    if kind and _is_quantity(value):
                        out.append(_record(kind, value, path, number,
                                           "kubernetes", bound, component))
            else:
                section = (indent, bound)
            continue
        for pattern, kind in ((K8S_GPU_RE, "gpu"), (K8S_CPU_RE, "cpu"),
                              (K8S_MEMORY_RE, "memory"), (K8S_STORAGE_RE, "disk")):
            match = pattern.match(line)
            if match:
                if _is_quantity(match.group(1)):
                    out.append(_record(kind, match.group(1), path, number,
                                       "kubernetes", section and section[1],
                                       component))
                break


def _scan_compose(root, path, out):
    section = service = None
    for number, line in enumerate(read_text(root, path).splitlines(), start=1):
        m = SERVICE_RE.match(line)
        if m:
            service = m.group(1)
        indent = len(line) - len(line.lstrip())
        if section and line.strip() and indent <= section[0]:
            section = None
        m = SECTION_RE.match(line)
        if m:
            section = (indent, BOUNDS[m.group(2)])
            continue
        for pattern, kind in COMPOSE_RES_RES:
            match = pattern.match(line)
            if match:
                if _is_quantity(match.group(1)):
                    bound = ("request" if "reservation" in line.split(":")[0]
                             else "limit" if "mem_limit" in line else
                             section and section[1])
                    out.append(_record(kind, match.group(1), path, number,
                                       "compose", bound or None, service))
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
