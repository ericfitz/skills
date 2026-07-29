"""Build synthetic repo trees in a temp directory for inventory tests."""

import subprocess
from pathlib import Path


def build_repo(base, files):
    """Create files under base. Keys are repo-relative POSIX paths, values file text.

    Returns base as a Path.
    """
    base = Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def git_init(base):
    """Initialize a git repo at base and stage nothing. Returns base."""
    base = Path(base)
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    return base
