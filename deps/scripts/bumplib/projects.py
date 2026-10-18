"""Projects: the independently locked units a repository holds.

A project is `{"dir": <repo-relative POSIX dir, "." for the root>, "members": [<dirs whose
manifests belong to it>]}`. Ecosystem `detect` verbs report them, the categorizer keys on
them, and `apply`/`validate` take `--project DIR` to act on one.
"""

import posixpath

ROOT = "."
DEFAULT = [{"dir": ROOT, "members": [ROOT]}]


def norm(path: str) -> str:
    """Repo-relative POSIX form of a directory: "" and "./" are the root."""
    p = posixpath.normpath((path or ROOT).replace("\\", "/"))
    return p


def join(directory: str, name: str) -> str:
    """Repo-relative path of `name` inside `directory` ("." contributes no prefix)."""
    d = norm(directory)
    return name if d == ROOT else f"{d}/{name}"


def parent_of(location: str) -> str:
    return norm(posixpath.dirname((location or "").replace("\\", "/")) or ROOT)


def split_project(argv):
    """Pull `--project DIR` out of a verb's argv. Returns (dir, remaining argv).

    The default is the root. A flag with no value, or a repeated flag, is an error:
    guessing which project was meant would apply a bump to the wrong lockfile."""
    rest, project, i = [], None, 0
    argv = list(argv)
    while i < len(argv):
        if argv[i] == "--project":
            if project is not None:
                raise ValueError("--project given more than once")
            if i + 1 >= len(argv):
                raise ValueError("--project needs a directory")
            project = norm(argv[i + 1])
            i += 2
            continue
        rest.append(argv[i])
        i += 1
    return (ROOT if project is None else project), rest


def require_root(project: str, ecosystem: str) -> None:
    """Go and Node act on one project, the root: reject anything else."""
    if project != ROOT:
        raise ValueError(f"{ecosystem}: --project must be '.', got {project!r}")


def validate_projects(projects) -> list:
    """Check a `projects` list's shape and normalize its dirs; reject anything else."""
    if not isinstance(projects, list):
        raise ValueError("projects must be a list")
    out = []
    for p in projects:
        if not (
            isinstance(p, dict)
            and isinstance(p.get("dir"), str)
            and isinstance(p.get("members"), list)
            and all(isinstance(m, str) for m in p["members"])
        ):
            raise ValueError(f"project must be {{dir: str, members: [str]}}, got {p!r}")
        out.append({"dir": norm(p["dir"]), "members": [norm(m) for m in p["members"]]})
    return out


def merge(projects) -> list:
    """Merge projects sharing a `dir` (union of members, first-seen order)."""
    by_dir = {}
    for p in validate_projects(projects):
        members = by_dir.setdefault(p["dir"], [])
        for m in p["members"]:
            if m not in members:
                members.append(m)
    return [{"dir": d, "members": m} for d, m in by_dir.items()]


def resolve(location: str, projects):
    """The project dir owning `location`, or None when its directory belongs to none.

    A project owns its own dir before any other project's `members` claim it."""
    parent = parent_of(location)
    for p in projects:
        if p["dir"] == parent:
            return p["dir"]
    for p in projects:
        if parent in p["members"]:
            return p["dir"]
    return None
