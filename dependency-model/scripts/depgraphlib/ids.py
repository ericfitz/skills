"""The id slug rule from references/categories.md (Ids) and id assignment.

One function builds every slug, so ids written by different scripts agree.
"""
import re

_GROUP = re.compile(r"\([^()]*\)")


class IdCollisionError(ValueError):
    """Two different names produce the same id even after the fallback."""


def _squash(s):
    return re.sub(r"[^a-z0-9.]+", "-", s).strip("-")


def slug_keep_groups(name):
    """The slug rule without step 2: parenthesized groups stay, as `-` runs."""
    return _squash(name.lower())


def slug(name):
    """Lowercase; drop balanced `(...)` groups; every run of characters other
    than `a-z`, `0-9` and `.` becomes one `-`; trim `-`. A name that slugs to
    empty falls back to `slug_keep_groups`; if that is empty too, ValueError."""
    s = name.lower()
    prev = None
    while prev != s:
        prev, s = s, _GROUP.sub(" ", s)
    result = _squash(s) or slug_keep_groups(name)
    if not result:
        raise ValueError(f"cannot derive an id slug from {name!r}")
    return result


def assign_ids(names, prefix):
    """Map each distinct name to `<prefix>:<slug>`. Names whose slugs collide
    fall back to `slug_keep_groups`; a collision that remains raises
    IdCollisionError naming both names."""
    for n in names:
        if not isinstance(n, str):
            raise TypeError(f"name must be a string, got {n!r}")
    distinct = list(dict.fromkeys(names))
    slugs = {n: slug(n) for n in distinct}
    counts = {}
    for s in slugs.values():
        counts[s] = counts.get(s, 0) + 1
    ids = {n: (slugs[n] if counts[slugs[n]] == 1 else slug_keep_groups(n))
           for n in distinct}
    owner = {}
    for n in distinct:
        if ids[n] in owner:
            raise IdCollisionError(
                f"names {owner[ids[n]]!r} and {n!r} both produce id "
                f"{prefix}:{ids[n]}")
        owner[ids[n]] = n
    return {n: f"{prefix}:{ids[n]}" for n in distinct}
