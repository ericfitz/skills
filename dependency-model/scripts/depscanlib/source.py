"""Source-literal extraction for Go, TypeScript/JavaScript, and Python.

Per D9 these three ecosystems are the whole scope: per-language literal
matching does not generalise the way manifest detection does. Every other
language's source files are counted and reported in coverage.skipped so the
gap lands in the contract instead of vanishing.
"""

import re
from collections import Counter

from depscanlib.walk import read_text

SOURCE_LANGUAGES = {
    ".go": "go",
    ".ts": "ts", ".tsx": "ts",
    ".js": "js", ".jsx": "js", ".mjs": "js", ".cjs": "js",
    ".py": "python", ".pyi": "python",
}

# Languages we can name but deliberately do not scan. Anything not listed
# here and not in SOURCE_LANGUAGES is not source, so it is not "skipped".
OTHER_LANGUAGES = {
    ".rs": "rust", ".java": "java", ".kt": "kotlin", ".rb": "ruby",
    ".php": "php", ".cs": "csharp", ".swift": "swift", ".scala": "scala",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".dart": "dart",
    ".pl": "perl", ".lua": "lua", ".r": "r", ".m": "objc",
}

SKIP_REASON = "source-literal scanning covers go, js, python, and ts only"

# raw text captured by the end-of-line resilience patterns is attacker/bundle
# controlled (a minified vendor file's single line can run tens of KB) — cap
# it so one match can't blow up the findings payload.
RAW_MAX_LEN = 200

_IDENT = r"[A-Za-z_][A-Za-z0-9_]*"


def _extract_single(match):
    return [match.group(1)]


def _extract_destructured(match):
    """Pull every bound name out of a `{ A, B: renamed, C = default }` group.

    The env var name is what's destructured *from* process.env, i.e. the
    left side of a `:` rename or `=` default — not the local binding.
    """
    names = []
    for part in match.group(1).split(","):
        name = re.split(r"[:=]", part, maxsplit=1)[0].strip()
        if re.fullmatch(_IDENT, name):
            names.append(name)
    return names


ENV_PATTERNS = {
    "go": [
        (re.compile(r'os\.(?:Getenv|LookupEnv)\(\s*"([A-Za-z_][A-Za-z0-9_]*)"'),
         _extract_single),
    ],
    "python": [
        (re.compile(r'(?:os\.)?\benviron\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
         _extract_single),
        (re.compile(r'(?:os\.)?\benviron\.get\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
         _extract_single),
        (re.compile(r'os\.getenv\(\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
         _extract_single),
    ],
    "js": [
        (re.compile(r'process\.env\.([A-Za-z_][A-Za-z0-9_]*)'), _extract_single),
        (re.compile(r'process\.env\?\.([A-Za-z_][A-Za-z0-9_]*)'), _extract_single),
        (re.compile(r'process\.env\[\s*["\']([A-Za-z_][A-Za-z0-9_]*)["\']'),
         _extract_single),
        (re.compile(r'\{\s*([^{}]+)\}\s*=\s*process\.env\b'), _extract_destructured),
    ],
}
ENV_PATTERNS["ts"] = ENV_PATTERNS["js"]

# (compiled pattern, kind). Documented for humans in
# references/resilience-signatures.md — keep the two in step.
RESILIENCE_PATTERNS = {
    "go": [
        (re.compile(r'context\.WithTimeout\([^)]*\)'), "timeout"),
        (re.compile(r'context\.WithDeadline\([^)]*\)'), "deadline"),
        (re.compile(r'\bTimeout:\s*[^,\n}]+'), "timeout"),
        (re.compile(r'\b(?:backoff|retry)\.[A-Za-z]+\([^)]*\)'), "retry"),
        (re.compile(r'\bgobreaker\b[^\n]*'), "circuit-breaker"),
    ],
    "python": [
        (re.compile(r'\btimeout\s*=(?!=)\s*[^,)\n]+'), "timeout"),
        (re.compile(r'@retry\b[^\n]*'), "retry"),
        (re.compile(r'\btenacity\b[^\n]*'), "retry"),
        (re.compile(r'\bpybreaker\b[^\n]*'), "circuit-breaker"),
    ],
    "js": [
        (re.compile(r'AbortSignal\.timeout\([^)]*\)'), "timeout"),
        (re.compile(r'\btimeout\s*:\s*[^,\n}]+'), "timeout"),
        (re.compile(r'\bp-retry\b[^\n]*'), "retry"),
        (re.compile(r'\bopossum\b[^\n]*'), "circuit-breaker"),
    ],
}
RESILIENCE_PATTERNS["ts"] = RESILIENCE_PATTERNS["js"]


def _suffix(path):
    dot = path.rfind(".")
    return path[dot:].lower() if dot > 0 else ""


def _scan_file(root, path, language, env_out, resilience_out):
    text = read_text(root, path)
    if not text:
        return
    for number, line in enumerate(text.splitlines(), start=1):
        for pattern, extractor in ENV_PATTERNS.get(language, []):
            for match in pattern.finditer(line):
                for name in extractor(match):
                    env_out.append({"name": name, "file": path, "line": number})
        for pattern, kind in RESILIENCE_PATTERNS.get(language, []):
            for match in pattern.finditer(line):
                raw = match.group(0).strip()[:RAW_MAX_LEN]
                resilience_out.append({"kind": kind, "raw": raw,
                                       "file": path, "line": number,
                                       "language": language})


def scan_source(root, paths):
    """Return ({"env_refs": [...], "resilience_calls": [...]}, skipped).

    skipped carries one record per out-of-scope language actually present,
    so each skill can turn it into a named assumption.
    """
    env_refs, resilience_calls = [], []
    unscanned = Counter()

    for path in sorted(paths):
        suffix = _suffix(path)
        language = SOURCE_LANGUAGES.get(suffix)
        if language:
            _scan_file(root, path, language, env_refs, resilience_calls)
        elif suffix in OTHER_LANGUAGES:
            unscanned[OTHER_LANGUAGES[suffix]] += 1

    skipped = [{"reason": SKIP_REASON, "language": language, "count": count}
               for language, count in sorted(unscanned.items())]
    return {"env_refs": env_refs, "resilience_calls": resilience_calls}, skipped
