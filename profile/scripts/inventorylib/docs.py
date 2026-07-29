"""Documentation census: what docs exist, roughly what kind, and how stale.

Classifies by path tokens only. It never reads document content and never
guesses outside the fixed vocabulary — an untypable doc is 'unknown', which is
the signal that tells profile:docs to read it rather than trust the label.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

DOC_TYPES = (
    "prd", "requirements", "spec", "design", "architecture", "adr",
    "runbook", "api_reference", "user_guide", "tutorial", "readme",
    "changelog", "unknown",
)

DOC_EXTS = {".md", ".rst", ".adoc", ".txt"}

DOC_DIRS = {
    "docs", "doc", "documentation", "adr", "adrs", "decisions",
    "rfc", "rfcs", "spec", "specs", "design", "wiki", "notes",
}

DOC_NAMES = {
    "README.md", "README.rst", "README.txt",
    "CONTRIBUTING.md", "ARCHITECTURE.md", "CHANGELOG.md", "CHANGELOG.rst",
}

STEM_TYPES = {
    "readme": "readme",
    "changelog": "changelog",
    "changes": "changelog",
    "history": "changelog",
}

# ordered: the first token that matches wins
TOKEN_TYPES = (
    ({"prd", "prds"}, "prd"),
    ({"requirement", "requirements", "acceptance"}, "requirements"),
    ({"adr", "adrs", "decision", "decisions"}, "adr"),
    ({"rfc", "rfcs", "spec", "specs", "specification"}, "spec"),
    ({"architecture", "architectural"}, "architecture"),
    ({"design"}, "design"),
    ({"runbook", "runbooks", "playbook"}, "runbook"),
    ({"api", "reference"}, "api_reference"),
    ({"tutorial", "tutorials", "quickstart"}, "tutorial"),
    ({"guide", "guides", "howto", "contributing"}, "user_guide"),
)

DOC_SITE_FILES = {
    "mkdocs.yml": "mkdocs",
    "mkdocs.yaml": "mkdocs",
    "docusaurus.config.js": "docusaurus",
    "docusaurus.config.ts": "docusaurus",
    "book.toml": "mdbook",
    "antora.yml": "antora",
}

# Sphinx's conf.py is only a doc site when it sits inside a doc directory;
# 'conf.py' is far too common a filename to trust on its own.
SPHINX_CONF = "conf.py"

_TOKENS = re.compile(r"[^a-z0-9]+")


def _tokens(path):
    return {token for token in _TOKENS.split(path.lower()) if token}


def guess_doc_type(path):
    """Return one of DOC_TYPES for path, based on its tokens. Never guesses wildly."""
    parsed = PurePosixPath(path)
    stem_type = STEM_TYPES.get(parsed.stem.lower())
    if stem_type:
        return stem_type
    tokens = _tokens(path)
    if {"getting", "started"} <= tokens or {"get", "started"} <= tokens:
        return "tutorial"
    for names, doc_type in TOKEN_TYPES:
        if tokens & names:
            return doc_type
    return "unknown"


def _is_doc(path):
    parsed = PurePosixPath(path)
    if parsed.name in DOC_NAMES:
        return True
    if parsed.suffix.lower() not in DOC_EXTS:
        return False
    return any(part.lower() in DOC_DIRS for part in parsed.parts[:-1])


def _git_last_modified(root, path):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI", "--", path],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _size(root, path):
    try:
        return (Path(root) / path).stat().st_size
    except OSError:
        return None


def _doc_sites(paths):
    sites = []
    for path in sorted(paths):
        parsed = PurePosixPath(path)
        generator = DOC_SITE_FILES.get(parsed.name)
        if generator is None and parsed.name == SPHINX_CONF:
            if any(part.lower() in DOC_DIRS for part in parsed.parts[:-1]):
                generator = "sphinx"
        if generator:
            sites.append({"path": path, "generator": generator})
    return sites


def detect_docs(root, paths, max_git_lookups=500):
    """Return {'docs': [...], 'docs_sites': [...]}, both sorted by path.

    Git lookups are capped: beyond max_git_lookups, last_modified is None. A
    thousand-page docs site should not turn the census into a thousand
    subprocess calls.
    """
    root = Path(root)
    docs = []
    lookups = 0
    for path in sorted(p for p in paths if _is_doc(p)):
        if lookups < max_git_lookups:
            last_modified = _git_last_modified(root, path)
            lookups += 1
        else:
            last_modified = None
        docs.append({
            "path": path,
            "doc_type_guess": guess_doc_type(path),
            "size": _size(root, path),
            "last_modified": last_modified,
        })
    return {"docs": docs, "docs_sites": _doc_sites(paths)}
