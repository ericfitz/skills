"""Assemble the shared evidence index the six discovery skills read."""

from pathlib import Path

from depscanlib import VERSION
from depscanlib.files import classify_files
from depscanlib.source import scan_source
from depscanlib.walk import EXCLUDE_DIRS, walk_repo

EMPTY_FINDINGS = ("env_refs", "url_literals", "host_port_literals",
                  "secret_shaped_keys", "resource_limits", "resilience_calls")


def build_coverage(paths, skipped):
    """Return files_scanned / skipped / confidence for the scan.

    confidence is about what the scan could see, not about what it found:
    an empty repo is low, an unscanned language is partial, everything else
    is high.
    """
    if not paths:
        return {"files_scanned": 0, "skipped": skipped, "confidence": "low"}
    confidence = "partial" if skipped else "high"
    return {"files_scanned": len(paths), "skipped": skipped,
            "confidence": confidence}


def build_scan(root):
    """Walk root and return the complete evidence index."""
    root = Path(root)
    paths, method = walk_repo(root)
    files = classify_files(root, paths)
    findings = {key: [] for key in EMPTY_FINDINGS}
    source_findings, skipped = scan_source(root, paths)
    findings.update(source_findings)

    return {
        "scan_version": VERSION,
        "target": str(root.resolve()),
        "listing_method": method,
        "exclusions": sorted(EXCLUDE_DIRS),
        "files": files,
        "findings": findings,
        "coverage": build_coverage(paths, skipped),
    }
