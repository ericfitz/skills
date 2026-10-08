"""Kubernetes networking objects and secret references, read line by line.

Text, not a YAML parse (depscanlib is stdlib-only). Only what a flat layout
of a manifest shows: Service/Ingress/NetworkPolicy objects with their ports,
container ports, and `secretKeyRef` name/key with the env var that uses it.
ponytail: indentation heuristics; a manifest generated as one JSON-ish line
or a helm template with `{{ }}` control flow is read best-effort.
"""

import re

from depscanlib.walk import read_text

NETWORK_KINDS = {"Service", "Ingress", "NetworkPolicy"}
KIND_RE = re.compile(r'^kind:\s*["\']?(\w+)')
NAME_RE = re.compile(r'^(\s*)(?:-\s+)?name:\s*["\']?([^"\'\s#]+)')
PORT_RE = re.compile(r'^\s*-?\s*(?:port|targetPort|containerPort|number):\s*["\']?(\w+)')
HOST_RE = re.compile(r'^\s*-?\s*host:\s*["\']?([^"\'\s#]+)')
SECRET_REF_RE = re.compile(r'^(\s*)secretKeyRef:\s*(.*)$')
FLOW_FIELD_RE = re.compile(r'\b(name|key):\s*["\']?([^"\',}\s]+)')
CONTAINER_PORT_RE = re.compile(r'^\s*-?\s*containerPort:\s*(\d+)')


def split_docs(lines):
    """Yield (first_line_number, lines) per YAML document."""
    start, cur = 1, []
    for number, line in enumerate(lines, start=1):
        if line.startswith("---"):
            yield start, cur
            start, cur = number + 1, []
        else:
            cur.append(line)
    yield start, cur


def doc_kind_and_name(doc):
    kind = name = None
    in_meta = False
    for line in doc:
        match = KIND_RE.match(line)
        if match and kind is None:
            kind = match.group(1)
        if line.startswith("metadata:"):
            in_meta = True
        elif in_meta and line and not line[0].isspace():
            in_meta = False
        elif in_meta and name is None:
            m = NAME_RE.match(line)
            if m and len(m.group(1)) == 2:
                name = m.group(2)
    return kind, name


def _walk_back_name(doc, index, indent):
    """Nearest preceding `- name: X` list item indented less than `indent`."""
    for i in range(index - 1, -1, -1):
        m = NAME_RE.match(doc[i])
        if m and doc[i].lstrip().startswith("- ") and len(m.group(1)) < indent:
            return m.group(2)
    return None


def container_name(doc, index):
    """Container `- name:` that owns line `index` (closest one above it that
    is followed by an `image:` line at the same list-item level)."""
    for i in range(index, -1, -1):
        m = NAME_RE.match(doc[i])
        if m and doc[i].lstrip().startswith("- "):
            indent = len(m.group(1)) + 2
            for nxt in doc[i + 1:i + 8]:
                if re.match(rf'^ {{{indent}}}image:', nxt):
                    return m.group(2)
    return None


def _secret_ref(doc, index, match, path, base):
    indent, rest = len(match.group(1)), match.group(2)
    fields = dict(FLOW_FIELD_RE.findall(rest)) if rest.startswith("{") else {}
    if not rest:
        for nxt in doc[index + 1:index + 6]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            fields.update(FLOW_FIELD_RE.findall(nxt))
    if "name" not in fields:
        return None
    return {"env": _walk_back_name(doc, index, indent), "secret": fields["name"],
            "key": fields.get("key"), "file": path, "line": base + index}


def scan_k8s(root, paths):
    """Return {"k8s_network": [...], "secret_refs": [...]} for manifest paths."""
    network, secrets = [], []
    for path in sorted(paths):
        for base, doc in split_docs(read_text(root, path).splitlines()):
            kind, name = doc_kind_and_name(doc)
            if kind is None or kind == "CustomResourceDefinition":
                continue
            if kind in NETWORK_KINDS:
                ports, hosts = [], []
                for line in doc:
                    m = PORT_RE.match(line)
                    if m and m.group(1) not in ports:
                        ports.append(m.group(1))
                    m = HOST_RE.match(line)
                    if m and kind == "Ingress" and m.group(1) not in hosts:
                        hosts.append(m.group(1))
                first = next((i for i, ln in enumerate(doc) if KIND_RE.match(ln)), 0)
                rec = {"kind": kind, "name": name, "ports": ports,
                       "file": path, "line": base + first}
                if hosts:
                    rec["hosts"] = hosts
                network.append(rec)
            for i, line in enumerate(doc):
                m = CONTAINER_PORT_RE.match(line)
                if m:
                    network.append({"kind": "containerPort",
                                    "name": container_name(doc, i) or name,
                                    "ports": [m.group(1)], "file": path,
                                    "line": base + i})
                m = SECRET_REF_RE.match(line)
                if m:
                    rec = _secret_ref(doc, i, m, path, base)
                    if rec:
                        secrets.append(rec)
    return {"k8s_network": network, "secret_refs": secrets}
