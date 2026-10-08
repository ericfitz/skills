"""Repo file listing: git-aware, with a filesystem fallback."""

import subprocess
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "vendor", "dist", "build", "target", "out", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next",
    ".gradle", "site-packages", ".idea",
}


def _skipped(rel):
    return any(part in SKIP_DIRS for part in Path(rel).parts)


def _git_files(root):
    """Return git's view of the repo, or None if root is not a usable git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _walk_files(root):
    found = []
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _skipped(rel):
            found.append(rel)
    return found


def walk_repo(root):
    """Return (sorted repo-relative POSIX paths, method) where method is git|walk."""
    root = Path(root)
    files = _git_files(root)
    if files is None:
        return sorted(_walk_files(root)), "walk"
    return sorted(f for f in files if not _skipped(f)), "git"
