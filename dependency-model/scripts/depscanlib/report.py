"""Assemble the shared evidence index the six discovery skills read."""

from pathlib import Path

from depscanlib import VERSION
from depscanlib.files import classify_files
from depscanlib.k8s import scan_k8s
from depscanlib.literals import scan_literals
from depscanlib.pathclass import classify_path, tag_paths
from depscanlib.resources import scan_resources
from depscanlib.source import scan_source
from depscanlib.walk import EXCLUDE_DIRS, git_ignored, walk_repo_and_links

EMPTY_FINDINGS = ("env_refs", "url_literals", "host_port_literals",
                  "secret_shaped_keys", "resource_limits", "resilience_calls",
                  "k8s_network", "secret_refs")


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


def build_scan(root, target=None, ref=None, run_dir=None, refused=()):
    """Walk root and return the complete evidence index.

    root is what is scanned; target is the repo it stands for (they differ
    for a --ref snapshot, whose evidence paths are still repo-relative).
    refused is the unsafe links a snapshot declined to extract.
    """
    root = Path(root)
    paths, method, unsafe = walk_repo_and_links(root)
    ignored = git_ignored(root)
    files = classify_files(root, paths)
    findings = {key: [] for key in EMPTY_FINDINGS}
    source_findings, skipped = scan_source(root, paths)
    findings.update(source_findings)
    findings.update(scan_literals(root, paths))
    findings["resource_limits"] = scan_resources(root, paths, files)
    findings.update(scan_k8s(root, files["k8s"]))
    for records in findings.values():
        tag_paths(root, records)

    return {
        "scan_version": VERSION,
        "target": str(Path(target or root).resolve()),
        "scan_root": str(root.resolve()),
        "ref": ref,
        "run_dir": str(run_dir) if run_dir else None,
        "listing_method": method,
        "exclusions": sorted(EXCLUDE_DIRS),
        "ignored": ignored,
        "unsafe_links": sorted(set(unsafe) | set(refused)),
        "syft_excludes": ([f"**/{name}" for name in sorted(EXCLUDE_DIRS)]
                          + [f"./{path}" for path in ignored]),
        "files": files,
        "file_classes": {p: classify_path(root, p)
                         for group in files.values() for p in group},
        "findings": findings,
        "coverage": build_coverage(paths, skipped),
    }
