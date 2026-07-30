"""Build synthetic repo trees in a temp directory for inventory tests."""

import os
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


def git_commit_all(base, message="init"):
    """Commit everything under base. Requires git_init to have run. Returns base."""
    base = Path(base)
    env = {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", message],
                   check=True, env=env)
    return base
