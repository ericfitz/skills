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

LOCKFILE_PM = {
    "uv.lock": "uv",
    "poetry.lock": "poetry",
    "pdm.lock": "pdm",
    "Pipfile.lock": "pipenv",
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
    "bun.lockb": "bun",
}


def detect_manifests(paths):
    """Return manifest records, resolving package manager from sibling lockfiles."""
    locks_by_dir = {}
    for path in paths:
        parsed = PurePosixPath(path)
        manager = LOCKFILE_PM.get(parsed.name)
        if manager:
            locks_by_dir.setdefault(parsed.parent.as_posix(), set()).add(manager)

    found = []
    for path in sorted(paths):
        parsed = PurePosixPath(path)
        entry = MANIFESTS.get(parsed.name)
        if not entry:
            continue
        ecosystem, default_manager = entry
        siblings = sorted(locks_by_dir.get(parsed.parent.as_posix(), set()))
        found.append({
            "path": path,
            "ecosystem": ecosystem,
            "package_manager": siblings[0] if siblings else default_manager,
        })
    return found
