"""sem_scope: shared repo-local scope file (.local/sem-scope.json) for the sem tools.

When a tool is invoked with no explicit path argument it consults this file for default
include/exclude globs. Explicit path arguments always fully override the file.
"""
import json
import os
import re

SCOPE_REL = os.path.join(".local", "sem-scope.json")

_REGEX_CACHE = {}


def load_scope(cwd=None):
    """Return the parsed .local/sem-scope.json dict, or None if the file is absent.

    Raises on malformed JSON or wrong value types (never silently falls back).
    """
    base = cwd if cwd is not None else os.getcwd()
    path = os.path.join(base, SCOPE_REL)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{SCOPE_REL}: expected a JSON object")
    for key in ("include", "exclude"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"{SCOPE_REL}: '{key}' must be a list of strings")
    return data


def _compile(pattern):
    """Compile a glob pattern to a regex over POSIX relative paths (cached)."""
    rx = _REGEX_CACHE.get(pattern)
    if rx is not None:
        return rx
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        rx = re.compile(re.escape(prefix) + r"(?:/.*)?\Z", re.S)
    else:
        i, n = 0, len(pattern)
        out = []
        while i < n:
            c = pattern[i]
            if c == "*":
                j = i
                while j < n and pattern[j] == "*":
                    j += 1
                if j - i >= 2:  # '**'
                    if pattern[j:j + 1] == "/":
                        out.append("(?:.*/)?")
                        j += 1
                    else:
                        out.append(".*")
                    i = j
                    continue
                out.append("[^/]*")
                i += 1
            elif c == "?":
                out.append("[^/]")
                i += 1
            else:
                out.append(re.escape(c))
                i += 1
        rx = re.compile("".join(out) + r"\Z", re.S)
    _REGEX_CACHE[pattern] = rx
    return rx


def glob_match(relpath, pattern):
    """True if POSIX-style relpath matches glob pattern.

    '**' crosses path separators; '*' and '?' do not; a trailing '/' is a directory prefix.
    """
    relpath = relpath.replace("\\", "/")
    return _compile(pattern).match(relpath) is not None


def is_excluded(relpath, scope):
    """True if relpath matches any pattern in scope['exclude']."""
    if not scope:
        return False
    for pat in scope.get("exclude") or []:
        if glob_match(relpath, pat):
            return True
    return False


def include_paths(scope):
    """Entity-discovery paths from scope['include'], defaulting to ['.'] when empty.

    Note: this default ('.') suits sem-annotate, which must pass a path to `sem entities`.
    dedupe treats an empty include as 'whole repo' and reads scope['include'] directly.
    """
    inc = (scope or {}).get("include") or []
    return list(inc) if inc else ["."]
