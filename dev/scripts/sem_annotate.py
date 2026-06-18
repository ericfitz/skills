"""sem-annotate: generate and refresh SEM@<sha> intent markers on code entities."""
import re
import os

COMMENT_BY_EXT = {
    ".go": "//", ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//",
    ".py": "#",
}

# Matches a SEM marker line: indent, comment prefix, short/full hex sha, description.
SEM_MARKER_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>//|#)\s*SEM@(?P<sha>[0-9a-fA-F]{4,40}):\s?(?P<desc>.*)$"
)


def comment_prefix(path):
    """Return the line-comment prefix for a file path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    return COMMENT_BY_EXT.get(ext.lower())


def parse_markers(text):
    """Return {0-based line index: {'sha', 'desc'}} for every SEM marker line."""
    out = {}
    for i, line in enumerate(text.splitlines()):
        m = SEM_MARKER_RE.match(line)
        if m:
            out[i] = {"sha": m.group("sha"), "desc": m.group("desc")}
    return out


def find_marker_above(lines, start_line):
    """Return the SEM marker dict on the line directly above 1-based start_line, or None."""
    above_idx = start_line - 2  # line above the entity, 0-based
    if above_idx < 0 or above_idx >= len(lines):
        return None
    m = SEM_MARKER_RE.match(lines[above_idx])
    if not m:
        return None
    return {"sha": m.group("sha"), "desc": m.group("desc")}


def build_marker(prefix, indent, sha, desc):
    """Build a SEM marker line with the given prefix, indentation, SHA, and description."""
    return f"{indent}{prefix} SEM@{sha}: {desc}"


def apply_marker(lines, start_line, prefix, sha, desc):
    """Insert or replace the SEM marker directly above 1-based start_line.

    Indentation is copied from the entity definition line. Returns a NEW list.
    """
    lines = list(lines)
    idx = start_line - 1                       # entity line, 0-based
    entity_line = lines[idx] if 0 <= idx < len(lines) else ""
    indent = entity_line[: len(entity_line) - len(entity_line.lstrip())]
    marker = build_marker(prefix, indent, sha, desc)
    above = idx - 1
    if above >= 0 and SEM_MARKER_RE.match(lines[above]):
        lines[above] = marker
    else:
        lines.insert(idx, marker)
    return lines


def classify(existing_sha, blame_commit, logic_changed):
    """Classify entity status: missing (no marker) / fresh (sha current or change cosmetic) / stale (logic changed).

    SHA comparison is prefix-based: blame_commit.startswith(existing_sha).
    """
    if not existing_sha:
        return "missing"
    if blame_commit.startswith(existing_sha):
        return "fresh"
    return "stale" if logic_changed else "fresh"
