"""Per-run output directories and --ref snapshots.

A run dir is keyed on the repo and the commit (or the working tree), so two
sessions scanning two branches of one repo never overwrite each other's
output, and one commit always maps to the same dir.

A --ref snapshot is `git archive` of that commit: only files committed there,
so git-ignored trees, other branches' nested worktrees, build output, and
uncommitted edits cannot leak into the scan. `git archive` writes nothing to
the repo, which `git worktree add` would.
"""

import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class RefError(Exception):
    """The ref cannot be resolved to a commit in the target repo."""


@dataclass
class Run:
    run_dir: Path
    scan_root: Path
    ref: dict | None
    refused: list[str] = field(default_factory=list)


def _resolve_commit(root, ref):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet",
             f"{ref}^{{commit}}"],
            capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RefError(f"cannot run git: {exc}") from exc
    if proc.returncode != 0:
        raise RefError(f"not a commit in {root}: {ref}")
    return proc.stdout.strip()


def _inside_only(refused):
    """tarfile's "data" filter, but skip rather than abort on a refused member.

    The data filter refuses exactly what walk.is_unsafe_link does: absolute
    links and links resolving outside the destination (committed ones are
    real, measured on tmi). Each is left out, never followed, and recorded.
    """
    def keep(member, path):
        try:
            return tarfile.data_filter(member, path)
        except tarfile.FilterError:
            refused.append(member.name)
            return None
    return keep


def _extract(root, commit, dest):
    """Extract `git archive <commit>` into dest atomically (temp dir, rename).

    Returns the members refused as unsafe links.
    """
    refused = []
    staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix="snapshot-"))
    proc = subprocess.Popen(["git", "-C", str(root), "archive", commit],
                            stdout=subprocess.PIPE)
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            tar.extractall(staging, filter=_inside_only(refused))
        if proc.wait(timeout=300) != 0:
            raise RefError(f"git archive failed for {commit}")
        # Recorded before the rename: a snapshot dir must never exist without it.
        (dest.parent / "refused.json").write_text(json.dumps(sorted(refused)))
        staging.rename(dest)
        return sorted(refused)
    except BaseException:
        proc.kill()
        proc.wait()
        shutil.rmtree(staging, ignore_errors=True)
        raise


def prepare(root, ref, tmp_base=None):
    """Return the Run for scanning root at ref (None = the working tree)."""
    root = Path(root).resolve()
    commit = _resolve_commit(root, ref) if ref else None
    key = hashlib.sha256(f"{root}\0{commit or 'worktree'}".encode()).hexdigest()[:12]
    run_dir = Path(tmp_base or tempfile.gettempdir()).resolve() / f"dependency-model-{key}"
    run_dir.mkdir(parents=True, exist_ok=True)
    if commit is None:
        return Run(run_dir, root, None)
    snapshot = run_dir / "snapshot"
    if snapshot.is_dir():
        refused = json.loads((run_dir / "refused.json").read_text())
    else:
        refused = _extract(root, commit, snapshot)
    return Run(run_dir, snapshot, {"name": ref, "commit": commit}, refused)
