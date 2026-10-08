"""Which candidate files actually changed, according to git."""
import subprocess


def changed_files(candidates, cwd="."):
    """Subset of candidates (order preserved) that git reports modified or untracked.

    apply's contract promises the files it changed; a hardcoded list lies whenever the
    underlying command no-ops or fails. When git itself is unavailable (not a repo, no
    binary) degrade to the candidates unchanged -- the old behavior beats crashing.
    """
    try:
        prefix = subprocess.run(["git", "rev-parse", "--show-prefix"],
                                cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()
        r = subprocess.run(["git", "status", "--porcelain", "--", *candidates],
                           cwd=cwd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return list(candidates)
    # porcelain paths are repo-root-relative; strip cwd's prefix so they compare against
    # the (cwd-relative) candidates as given.
    dirty = set()
    for line in r.stdout.splitlines():
        if len(line) <= 3:
            continue
        path = line[3:].strip().strip('"')
        if prefix and path.startswith(prefix):
            path = path[len(prefix):]
        dirty.add(path)
    return [c for c in candidates if c in dirty]
