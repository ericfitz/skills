"""Language-agnostic literal extraction over every readable text file.

secret_shaped_keys records key NAMES and locations only. It never captures a
value, in any form, from any file. A discovery contract carrying a credential
is a leak, and the cheapest place to make that impossible is here, where the
value would first be read.
"""

import re

from depscanlib.walk import read_text

TEXT_SUFFIXES_SKIPPED = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".so", ".dylib", ".dll", ".exe",
    ".class", ".jar", ".wasm", ".bin", ".db", ".sqlite", ".sqlite3",
}

URL_RE = re.compile(r'\b([a-z][a-z0-9+.\-]{1,15})://([^\s"\'`<>,)\]}]+)')

# host:port, not image:tag and not a clock. The port must be 2-5 digits and
# the whole match must not be followed by another colon-separated token.
HOST_PORT_RE = re.compile(
    r'(?<![\w.:/@-])'
    r'((?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z][a-z0-9\-]*(?:\.[a-z0-9\-]+)*))'
    r':(\d{2,5})(?![\w.:])',
    re.IGNORECASE)

# A port is a port. 16 is an image tag, 30 is half past the hour.
MIN_PORT = 80
MAX_PORT = 65535

# The leading prefix is OPTIONAL: a key is very often the bare keyword
# (`password:`, `PRIVATE_KEY =`), and a mandatory prefix would match
# STRIPE_API_KEY while silently missing API_KEY. "AUTH" is deliberately not in
# the list -- it fires on `authors = [...]` in every pyproject.toml, and
# AUTH_TOKEN is already caught by TOKEN.
SECRET_NAME_RE = re.compile(
    r'\b((?:[A-Za-z][A-Za-z0-9_]*?)?'
    r'(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_]?KEY|APIKEY|CREDENTIAL|'
    r'PRIVATE[_]?KEY|ACCESS[_]?KEY|CLIENT[_]?SECRET)'
    r'[A-Za-z0-9_]*)\b'
    r'(?=\s*[:=])',
    re.IGNORECASE)

SCHEMA_KEYS = ('"$schema"', "'$schema'", "$schema:")


def _is_text(path):
    dot = path.rfind(".")
    return dot < 0 or path[dot:].lower() not in TEXT_SUFFIXES_SKIPPED


def _url_host(rest):
    authority = rest.split("/", 1)[0]
    authority = authority.rsplit("@", 1)[-1]
    return authority.split(":", 1)[0]


def _strip_trailing(value):
    return value.rstrip('.,;:"\'`)]}>')


def scan_literals(root, paths):
    """Return URL, host:port, and secret-shaped-key findings across the repo."""
    urls, host_ports, secret_keys = [], [], []

    for path in sorted(paths):
        if not _is_text(path):
            continue
        text = read_text(root, path)
        if not text:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if not any(marker in line for marker in SCHEMA_KEYS):
                for match in URL_RE.finditer(line):
                    value = _strip_trailing(match.group(0))
                    urls.append({"value": value, "scheme": match.group(1),
                                 "host": _url_host(match.group(2)),
                                 "file": path, "line": number})
            for match in HOST_PORT_RE.finditer(line):
                port = int(match.group(2))
                if MIN_PORT <= port <= MAX_PORT:
                    host_ports.append({"host": match.group(1), "port": port,
                                       "file": path, "line": number})
            for match in SECRET_NAME_RE.finditer(line):
                secret_keys.append({"name": match.group(1), "file": path,
                                    "line": number})

    return {"url_literals": urls, "host_port_literals": host_ports,
            "secret_shaped_keys": secret_keys}
