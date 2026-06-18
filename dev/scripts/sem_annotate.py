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
