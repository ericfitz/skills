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
