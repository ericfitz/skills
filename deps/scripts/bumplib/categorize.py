"""Agnostic categorizer: semver comparison + glob exclusion, no provider knowledge."""
import re
from dataclasses import asdict

from . import contracts as c

_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")
# Fallbacks for releases that carry fewer than three components. PyPI is full of them
# (packaging 26.2, attrs 25.3), and against the three-group pattern alone they matched
# nothing and parsed as (0, 0, 0) -- so `26.2 -> 26.3` compared equal and was reported
# as "none", i.e. silently dropped as already up to date. Tried widest-first, so any
# string that already parsed keeps parsing exactly as it did.
_SEMVER2 = re.compile(r"(\d+)\.(\d+)")
_SEMVER1 = re.compile(r"(\d+)")


def parse_semver(v: str):
    """Return (major, minor, patch). Strips leading 'v', trailing pre-release/build.

    Missing trailing components read as 0, so '26.2' is (26, 2, 0) -- the same value a
    PEP 440 or semver reading gives it. Anything with no digits at all stays (0, 0, 0).
    """
    s = v or ""
    m = _SEMVER.search(s)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = _SEMVER2.search(s)
    if m:
        return (int(m.group(1)), int(m.group(2)), 0)
    m = _SEMVER1.search(s)
    if m:
        return (int(m.group(1)), 0, 0)
    return (0, 0, 0)


def classify_bump(current: str, latest: str) -> str:
    cur, lat = parse_semver(current), parse_semver(latest)
    if lat == cur or lat < cur:
        return c.BUMP_NONE
    if lat[0] > cur[0]:
        return c.BUMP_MAJOR
    if lat[1] > cur[1]:
        return c.BUMP_MINOR
    return c.BUMP_PATCH


def glob_match(name: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def _excluded(rec, exclude, holds):
    if rec.pinned:
        return "pinned"
    for pat in exclude:
        if glob_match(rec.name, pat):
            return f"Excluded ({pat})"
    if rec.name in holds:
        return f"Hold: {holds[rec.name]}"
    return None


def _item(rec, reason, advisory=None):
    d = asdict(rec)
    d["reason"] = reason
    d["advisory"] = asdict(advisory) if advisory else None
    return d


def categorize(updates, advisories, exclude, holds, replace_targets) -> c.Categories:
    adv_index = {a.package: a for a in advisories}
    out = c.Categories()
    for rec in updates:
        if rec.name in replace_targets or rec.bump == c.BUMP_NONE:
            out.skipped.append(_item(rec, "replace directive" if rec.name in replace_targets else "up to date"))
            continue
        adv = adv_index.get(rec.name)
        excl = _excluded(rec, exclude, holds)
        if rec.bump == c.BUMP_MAJOR:
            reason = "Major security fix" if adv else f"Major ({rec.current} -> {rec.latest})"
            out.needsPlan.append(_item(rec, reason, adv))
        elif excl:
            out.needsPlan.append(_item(rec, excl, adv))
        elif adv:
            sev = adv.ids[0] if adv.ids else adv.severity
            out.securityFixes.append(_item(rec, f"security fix ({sev})", adv))
        else:
            out.safe.append(_item(rec, f"{rec.bump} update"))
    return out
