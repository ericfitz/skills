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
# the whole match must not be followed by another colon-separated token. A
# port immediately followed by '@' is not a port at all -- it is a numeric
# password in a schemeless `user:pass@host` credential.
HOST_PORT_RE = re.compile(
    r'(?<![\w.:/@-])'
    r'((?:\d{1,3}(?:\.\d{1,3}){3})|(?:[a-z][a-z0-9\-]*(?:\.[a-z0-9\-]+)*))'
    r':(\d{2,5})(?![\w.:@])',
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


def _looks_like_partial_userinfo(head):
    """True if `head` (the text up to the first '/') looks like a truncated
    `user:password` rather than a complete `host[:port]`.

    A real `host:port` authority has an all-digit tail after the last ':'.
    A `user:password` fragment usually does not -- that difference is what
    lets `_split_authority` tell an ordinary `host:port/path` apart from a
    password that itself contains an unencoded '/'.
    """
    if ":" not in head:
        return False
    return not head.rsplit(":", 1)[-1].isdigit()


def _split_authority(rest):
    """Split a URL's `scheme://` remainder into (userinfo, hostport, tail).

    The authority normally ends at the first '/'. A raw, unencoded password
    can itself contain '/' (`user:pa/ss@host/path`), which would otherwise
    truncate the authority before the real '@'. Look past the first '/' for
    a later '@' only when what precedes it looks like a partial
    `user:password` (see `_looks_like_partial_userinfo`) rather than a
    complete `host:port` -- an ordinary path segment with '@' in it (a
    social-style `/@handle`) or an explicit `host:port/path@thing` is left
    alone, since neither is a credential.

    Returns `(None, hostport, tail)` when no userinfo is present.
    """
    head, slash, after_slash = rest.partition("/")
    if "@" not in head and slash and _looks_like_partial_userinfo(head):
        next_head, next_slash, next_tail = after_slash.partition("/")
        if "@" in next_head:
            head, slash, after_slash = head + slash + next_head, next_slash, next_tail
    if "@" in head:
        userinfo, _, hostport = head.rpartition("@")
        return userinfo, hostport, slash + after_slash
    return None, head, slash + after_slash


def _url_host(rest):
    _, hostport, _ = _split_authority(rest)
    return hostport.split(":", 1)[0]


def _redact_userinfo(rest):
    """Blank out a URL's userinfo (`user:pass@`) before it is emitted.

    Scheme, host, port, and path are the signal a discovery skill wants; the
    userinfo component is, by definition, a credential. Keep the fact that
    one was present -- that a connection string carries inline credentials
    is itself worth recording -- without reproducing it.
    """
    userinfo, hostport, tail = _split_authority(rest)
    if userinfo is None:
        return rest
    return "***@" + hostport + tail


# Query-string / fragment `name=value` pairs, delimited by '&'. Applied only
# to the text from the first '?' or '#' onward -- the path is never touched.
_QUERY_KV_RE = re.compile(r'([^&=?#]+)=([^&#]*)')


def _redact_secret_params(text):
    """Blank out the value of any query-string or fragment parameter whose
    name is secret-shaped (per SECRET_NAME_RE).

    JDBC and OAuth-style URLs carry credentials as `?password=...` or
    `#access_token=...` rather than in userinfo -- the same leak, through a
    different URL component. The parameter name and the path, and any
    non-secret parameter, are left untouched: query shape is legitimate
    evidence, only the secret value is not.
    """
    start = next((i for i, ch in enumerate(text) if ch in "?#"), None)
    if start is None:
        return text

    def redact(match):
        name = match.group(1)
        if SECRET_NAME_RE.search(name + "="):
            return f"{name}=***"
        return match.group(0)

    return text[:start] + _QUERY_KV_RE.sub(redact, text[start:])


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
                    scheme, rest = match.group(1), match.group(2)
                    redacted = _redact_secret_params(_redact_userinfo(rest))
                    value = _strip_trailing(f"{scheme}://{redacted}")
                    urls.append({"value": value, "scheme": scheme,
                                 "host": _url_host(rest),
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
