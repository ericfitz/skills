"""Assemble the full repo inventory."""

from pathlib import Path

from inventorylib import VERSION
from inventorylib.docs import detect_docs
from inventorylib.infra import detect_infra
from inventorylib.languages import classify_languages
from inventorylib.manifests import detect_manifests
from inventorylib.testfiles import classify_test_files, test_dirs
from inventorylib.walk import walk_repo

UNCLASSIFIED_LIMIT = 200
DOCS_LIMIT = 200
HIGH_CONFIDENCE_MAX_UNCLASSIFIED_SHARE = 0.05


def coverage_confidence(languages, manifests, unclassified, total_files):
    """Return high|partial|low for how much of the repo was understood."""
    if not languages or not manifests:
        return "low"
    share = len(unclassified) / total_files if total_files else 0.0
    if share <= HIGH_CONFIDENCE_MAX_UNCLASSIFIED_SHARE:
        return "high"
    return "partial"


def build_inventory(root):
    """Walk root and return the complete inventory object."""
    root = Path(root)
    paths, method = walk_repo(root)
    languages, unclassified = classify_languages(paths)
    manifests = detect_manifests(paths)
    tests = classify_test_files(root, paths)
    infra = detect_infra(root, paths)
    docs = detect_docs(root, paths)

    # A path the infra census recognized is not unclassified, whatever the
    # language census thinks: .tf/.tfvars/.bicep carry no language, but the
    # inventory understands them. Without this subtraction the same file is
    # reported as recognized IaC AND unknown, and confidence degrades for a
    # repo the census fully understood — a self-contradictory inventory.
    known = {
        record["path"]
        for section in (infra["ci"], infra["containers"], infra["iac"],
                        infra["test_config"], infra["entrypoints"])
        for record in section
    }
    unclassified = [p for p in unclassified if p not in known]

    return {
        "inventory_version": VERSION,
        "root": str(root.resolve()),
        "listing_method": method,
        "languages": languages,
        "manifests": manifests,
        "test_files": tests,
        "test_dirs": test_dirs(tests),
        "test_config": infra["test_config"],
        "ci": infra["ci"],
        "containers": infra["containers"],
        "iac": infra["iac"],
        "entrypoints": infra["entrypoints"],
        "docs": docs["docs"][:DOCS_LIMIT],
        "docs_total": len(docs["docs"]),
        "docs_sites": docs["docs_sites"],
        "unclassified": sorted(unclassified)[:UNCLASSIFIED_LIMIT],
        "unclassified_total": len(unclassified),
        "coverage_confidence": coverage_confidence(
            languages, manifests, unclassified, len(paths)),
    }
