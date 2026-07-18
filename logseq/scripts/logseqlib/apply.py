# logseq/scripts/logseqlib/apply.py
"""Safe multi-file changeset application: diff, backup, git guard, atomic writes."""
import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ApplyError(Exception):
    pass


@dataclass
class Change:
    path: Path
    new_content: str | None  # None = delete


def _relpath(graph: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(graph.resolve()))
    except ValueError:
        raise ApplyError(f"path outside graph: {path}") from None


def diff_changeset(graph: Path, changes: list) -> str:
    chunks = []
    for ch in changes:
        rel = _relpath(graph, ch.path)
        old = ch.path.read_text() if ch.path.is_file() else ""
        new = ch.new_content if ch.new_content is not None else ""
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}")
        chunks.append("".join(diff))
    return "\n".join(c for c in chunks if c)


def backup(graph: Path, changes: list, now_stamp: str):
    bdir = graph / "logseq" / ".backups" / now_stamp
    backed_any = False
    for ch in changes:
        rel = _relpath(graph, ch.path)
        if ch.path.is_file():
            dest = bdir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ch.path, dest)
            backed_any = True
    return bdir if backed_any else None


def git_is_dirty(graph: Path):
    if not (graph / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "-C", str(graph), "status", "--porcelain"],
                           capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(r.stdout.strip())


def apply_changeset(graph: Path, changes: list, now_stamp: str,
                    dry_run: bool = False, force: bool = False) -> dict:
    rels = [_relpath(graph, ch.path) for ch in changes]  # validates all paths
    diff = diff_changeset(graph, changes)
    if dry_run:
        return {"dry_run": True, "diff": diff, "files": rels}
    if git_is_dirty(graph) and not force:
        raise ApplyError("graph git tree is dirty; commit/stash or pass force")
    bdir = backup(graph, changes, now_stamp)
    for ch in changes:
        if ch.new_content is None:
            if ch.path.is_file():
                ch.path.unlink()
            continue
        ch.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = ch.path.with_suffix(ch.path.suffix + ".tmp")
        tmp.write_text(ch.new_content)
        os.replace(tmp, ch.path)
    return {"applied": rels, "backup": str(bdir) if bdir else None,
            "diff": diff}
