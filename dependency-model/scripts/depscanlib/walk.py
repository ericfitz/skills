"""Repo file listing: git-aware, with a filesystem fallback.

Deliberately duplicates profile's walk rather than importing inventorylib:
plugins install independently, so a cross-plugin Python import would break
at install time.
"""

import subprocess
from pathlib import Path

# The single source of truth for what neither this scanner nor syft looks at.
# Unscoped, syft catalogues an installed tree as though it were the project's
# dependency set — 270 packages against 2 declared ones, measured on this repo.
EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "vendor", "dist", "build", "target", "out", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next",
    ".gradle", "site-packages", ".idea", ".terraform", "Pods",
}


def _excluded(rel):
    return any(part in EXCLUDE_DIRS for part in Path(rel).parts)


def _git_files(root):
    """Return git's view of the repo, or None if root is not a usable git repo.

    Uses -z (NUL-separated, unquoted paths) rather than the newline-delimited
    default: with core.quotepath's default of true, git C-quotes non-ASCII
    filenames in plain output ("caf\\303\\251.yaml" as literal characters),
    which turns into a path that does not exist on disk. -z also survives
    filenames containing newlines, which `-c core.quotepath=false` alone
    would not.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    # -z output is NUL-terminated, not NUL-separated: split() leaves one
    # trailing empty string to drop.
    return [f for f in proc.stdout.split("\0") if f]


def _walk_files(root):
    found = []
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _excluded(rel):
            found.append(rel)
    return found


def walk_repo(root):
    """Return (sorted repo-relative POSIX paths, method) where method is git|walk."""
    root = Path(root)
    files = _git_files(root)
    if files is None:
        return sorted(_walk_files(root)), "walk"
    return sorted(f for f in files if not _excluded(f)), "git"


def read_text(root, rel, limit=None):
    """Read a repo-relative file as text, or return '' if it cannot be read."""
    try:
        text = (Path(root) / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[:limit] if limit else text
