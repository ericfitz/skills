"""Agnostic categorizer: semver comparison + glob exclusion, no provider knowledge."""

import re
from dataclasses import asdict
from pathlib import PurePosixPath

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


_SEVERITY_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


def _nested(location: str) -> bool:
    """A manifest in a subdirectory belongs to a separate project, which the ecosystem
    adapters (rooted at the project directory) neither list nor apply to."""
    return PurePosixPath(location or ".").parent != PurePosixPath(".")


def _merge(advs) -> c.Advisory:
    """One advisory per package: the highest fixed version, the first known current
    version, the highest severity, and every id in first-seen order."""
    ids = []
    for a in advs:
        ids += [i for i in a.ids if i and i not in ids]
    fixes = [a.fixed for a in advs if a.fixed]
    return c.Advisory(
        package=advs[0].package,
        ecosystem=next((a.ecosystem for a in advs if a.ecosystem), ""),
        severity=max((a.severity for a in advs), key=lambda s: _SEVERITY_RANK.get(s.upper(), 0)),
        current=next((a.current for a in advs if a.current), ""),
        fixed=max(fixes, key=parse_semver) if fixes else "",
        ids=ids,
        summary=next((a.summary for a in advs if a.summary), ""),
        source=", ".join(dict.fromkeys(a.source for a in advs if a.source)),
        location=next((a.location for a in advs if a.location), ""),
    )


def _place_advisory(out, adv, nested, exclude, holds):
    """Bucket an advisory no update record matched. It becomes a `transitive` record
    (current from the advisory, latest = its fix) so that it is applied or planned
    like any other update instead of disappearing."""
    known = bool(adv.current and adv.fixed)
    bump = classify_bump(adv.current, adv.fixed) if known else (c.BUMP_NONE if adv.current else c.BUMP_UNKNOWN)
    rec = c.UpdateRecord(
        name=adv.package,
        current=adv.current,
        latest=adv.fixed,
        wanted=adv.fixed,
        bump=bump,
        kind="transitive",
        location=adv.location,
        ecosystem=adv.ecosystem,
    )
    if nested:
        out.needsPlan.append(_item(rec, f"advisory in {adv.location}, a separate project this run does not cover", adv))
    elif not adv.fixed:
        out.needsPlan.append(_item(rec, "security advisory with no fixed version", adv))
    elif not adv.current:
        out.needsPlan.append(_item(rec, f"current version unknown; fixed in {adv.fixed}", adv))
    elif bump == c.BUMP_NONE:
        out.skipped.append(_item(rec, f"advisory already fixed ({adv.current} >= {adv.fixed})", adv))
    elif excl := _excluded(rec, exclude, holds):
        out.needsPlan.append(_item(rec, excl, adv))
    elif bump == c.BUMP_MAJOR:
        out.needsPlan.append(_item(rec, f"Major security fix ({adv.current} -> {adv.fixed})", adv))
    else:
        sev = adv.ids[0] if adv.ids else adv.severity
        out.securityFixes.append(_item(rec, f"transitive security fix ({sev})", adv))


def categorize(updates, advisories, exclude, holds, replace_targets) -> c.Categories:
    groups = {}
    for a in advisories:
        groups.setdefault((a.package, a.location if _nested(a.location) else ""), []).append(a)
    merged = {key: _merge(advs) for key, advs in groups.items()}
    adv_index = {pkg: a for (pkg, nested), a in merged.items() if not nested}
    out = c.Categories()
    for rec in updates:
        adv = adv_index.get(rec.name)
        if rec.name in replace_targets or rec.bump == c.BUMP_NONE:
            out.skipped.append(_item(rec, "replace directive" if rec.name in replace_targets else "up to date", adv))
            continue
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
    recorded = {rec.name for rec in updates}
    for (pkg, nested), adv in sorted(merged.items()):
        if nested or pkg not in recorded:
            _place_advisory(out, adv, bool(nested), exclude, holds)
    return out
