"""Agnostic categorizer: semver comparison + glob exclusion, no provider knowledge."""

import re
from dataclasses import asdict

from . import contracts as c
from . import projects as proj

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


def _item(rec, reason, advisory=None, project=proj.ROOT):
    d = asdict(rec)
    d["reason"] = reason
    d["project"] = project
    d["advisory"] = asdict(advisory) if advisory else None
    return d


_SEVERITY_RANK = {"LOW": 1, "MODERATE": 2, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}


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


def _place_advisory(out, adv, project, covered, exclude, holds):
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
    if not covered:
        out.needsPlan.append(
            _item(rec, f"advisory in {adv.location}, a separate project this run does not cover", adv, project)
        )
    elif not adv.fixed:
        out.needsPlan.append(_item(rec, "security advisory with no fixed version", adv, project))
    elif not adv.current:
        out.needsPlan.append(_item(rec, f"current version unknown; fixed in {adv.fixed}", adv, project))
    elif bump == c.BUMP_NONE:
        out.skipped.append(_item(rec, f"advisory already fixed ({adv.current} >= {adv.fixed})", adv, project))
    elif excl := _excluded(rec, exclude, holds):
        out.needsPlan.append(_item(rec, excl, adv, project))
    elif bump == c.BUMP_MAJOR:
        out.needsPlan.append(_item(rec, f"Major security fix ({adv.current} -> {adv.fixed})", adv, project))
    else:
        sev = adv.ids[0] if adv.ids else adv.severity
        out.securityFixes.append(_item(rec, f"transitive security fix ({sev})", adv, project))


def categorize(updates, advisories, exclude, holds, replace_targets, projects=None) -> c.Categories:
    """Bucket updates and advisories. A package is matched per project: two projects
    locking the same package at different versions each get their own advisory.

    `projects` (see projects.py) defaults to one root project, which treats every
    manifest in a subdirectory as a separate project this run does not cover."""
    projects = projects or proj.DEFAULT
    groups = {}
    for a in advisories:
        owner = proj.resolve(a.location, projects)
        # An uncovered location keeps its own group, apart from other locations.
        key = (a.package, proj.parent_of(a.location), a.location) if owner is None else (a.package, owner, "")
        groups.setdefault(key, []).append(a)
    merged = {key: _merge(advs) for key, advs in groups.items()}
    adv_index = {(pkg, project): a for (pkg, project, loc), a in merged.items() if not loc}
    out = c.Categories()
    recorded = set()
    for rec in updates:
        # An adapter only emits records for projects it covers, so a record outside
        # every member keeps its own directory as its project.
        project = proj.resolve(rec.location, projects) or proj.parent_of(rec.location)
        recorded.add((rec.name, project))
        adv = adv_index.get((rec.name, project))
        if rec.name in replace_targets or rec.bump == c.BUMP_NONE:
            out.skipped.append(
                _item(rec, "replace directive" if rec.name in replace_targets else "up to date", adv, project)
            )
            continue
        excl = _excluded(rec, exclude, holds)
        if renamed := rec.meta.get("renamedTo"):
            last = rec.meta.get("lastVersionWithPath") or ""
            tail = f"{last} is the last version under the old path" if last else "no newer version keeps the old path"
            out.needsPlan.append(_item(rec, f"Renamed ({rec.name} -> {renamed} at {rec.latest}); {tail}", adv, project))
        elif rec.bump == c.BUMP_MAJOR:
            reason = "Major security fix" if adv else f"Major ({rec.current} -> {rec.latest})"
            out.needsPlan.append(_item(rec, reason, adv, project))
        elif excl:
            out.needsPlan.append(_item(rec, excl, adv, project))
        elif adv:
            sev = adv.ids[0] if adv.ids else adv.severity
            out.securityFixes.append(_item(rec, f"security fix ({sev})", adv, project))
        else:
            out.safe.append(_item(rec, f"{rec.bump} update", project=project))
    for (pkg, project, loc), adv in sorted(merged.items()):
        if loc or (pkg, project) not in recorded:
            _place_advisory(out, adv, project, not loc, exclude, holds)
    return out
