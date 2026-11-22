"""Explicit per-origin lists for the `discover` plugin's skills and contract schemas.

`discover` merges two former plugins. Tests iterate these lists, never a directory
glob, so a schema or skill added without declaring its origin fails a test.
"""

import re
from collections.abc import Iterable
from pathlib import Path

PROFILE_SKILLS: tuple[str, ...] = ("docs", "journeys", "project-report", "stack", "topology")
DEPENDENCY_SKILLS: tuple[str, ...] = (
    "config",
    "dependency-report",
    "network",
    "package",
    "platform",
    "security",
    "service",
    "synthesize",
)
# User-invoked shortcuts that chain skills of one origin; they belong to neither list.
SHORTCUT_SKILLS: tuple[str, ...] = ("dependency-model", "project-profile")
PROFILE_SCHEMAS = ("docs", "journeys", "stack", "topology")
DEPENDENCY_SCHEMAS = (
    "config",
    "dependency-core",
    "discovery",
    "network",
    "package",
    "platform",
    "security",
    "service",
    "synthesis",
)

_SUFFIX = ".schema.json"


def schema_paths(contracts_dir: Path, names: Iterable[str]) -> list[Path]:
    """Paths of the named schemas, in the given order (existence is not checked)."""
    return [Path(contracts_dir) / f"{name}{_SUFFIX}" for name in names]


def schema_drift(contracts_dir: Path, listed: Iterable[str]) -> tuple[list[str], list[str]]:
    """(unlisted, missing): schemas present but not listed, and listed but absent; each sorted."""
    present = {p.name[: -len(_SUFFIX)] for p in Path(contracts_dir).glob(f"*{_SUFFIX}")}
    listed = set(listed)
    return sorted(present - listed), sorted(listed - present)


def skill_drift(skills_dir: Path, listed: Iterable[str]) -> tuple[list[str], list[str]]:
    """(unlisted, missing): skill dirs present but not listed, and listed but absent; each sorted."""
    present = {p.name for p in Path(skills_dir).iterdir() if p.is_dir()}
    listed = set(listed)
    return sorted(present - listed), sorted(listed - present)


_DEPENDENCY_SKILL_REF = re.compile(
    r"discover:(" + "|".join(re.escape(n) for n in DEPENDENCY_SKILLS) + r")(?![A-Za-z0-9_-])"
)


def dependency_skill_refs(text: str) -> list[str]:
    """Sorted `discover:<dependency skill>` tokens in text; a profile skill must have none (one-way direction)."""
    return sorted({f"discover:{m}" for m in _DEPENDENCY_SKILL_REF.findall(text)})
