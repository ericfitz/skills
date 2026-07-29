# profile/scripts/inventorylib/manifests.py
"""Detect dependency manifests and resolve the package manager in use."""

from pathlib import PurePosixPath

# filename -> (ecosystem, default package manager or None if a lockfile decides)
MANIFESTS = {
    "pyproject.toml": ("python", None),
    "requirements.txt": ("python", "pip"),
    "setup.py": ("python", "pip"),
    "Pipfile": ("python", "pipenv"),
    "go.mod": ("go", "go"),
    "package.json": ("node", None),
    "Cargo.toml": ("rust", "cargo"),
    "Gemfile": ("ruby", "bundler"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("kotlin", "gradle"),
    "composer.json": ("php", "composer"),
    "mix.exs": ("elixir", "mix"),
    "Package.swift": ("swift", "spm"),
    "pubspec.yaml": ("dart", "pub"),
}

# filename -> (ecosystem, package manager)
LOCKFILE_PM = {
    "uv.lock": ("python", "uv"),
    "poetry.lock": ("python", "poetry"),
    "pdm.lock": ("python", "pdm"),
    "Pipfile.lock": ("python", "pipenv"),
    "package-lock.json": ("node", "npm"),
    "yarn.lock": ("node", "yarn"),
    "pnpm-lock.yaml": ("node", "pnpm"),
    "bun.lockb": ("node", "bun"),
}


def detect_manifests(paths):
    """Return manifest records, resolving package manager from sibling lockfiles.

    A lockfile resolves a manifest only when it sits in the same directory AND
    belongs to the same ecosystem. Without the ecosystem check, a Go module
    beside a package-lock.json reports as npm-managed — a confident wrong
    answer, which is precisely what this module must never produce.

    Two lockfiles of the same ecosystem in one directory (npm and yarn, say)
    resolve alphabetically. That tie-break is arbitrary but deterministic, and
    a test pins it so it cannot drift silently.
    """
    locks_by_dir = {}
    for path in paths:
        parsed = PurePosixPath(path)
        entry = LOCKFILE_PM.get(parsed.name)
        if entry:
            locks_by_dir.setdefault(parsed.parent.as_posix(), set()).add(entry)

    found = []
    for path in sorted(paths):
        parsed = PurePosixPath(path)
        entry = MANIFESTS.get(parsed.name)
        if not entry:
            continue
        ecosystem, default_manager = entry
        siblings = sorted(
            manager
            for lock_ecosystem, manager in locks_by_dir.get(parsed.parent.as_posix(), set())
            if lock_ecosystem == ecosystem
        )
        found.append({
            "path": path,
            "ecosystem": ecosystem,
            "package_manager": siblings[0] if siblings else default_manager,
        })
    return found
