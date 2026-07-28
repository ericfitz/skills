"""Orchestration helpers: pure functions the CLI/skill call to combine adapter output.

These functions spawn no subprocesses; they only merge already-gathered data
(config exclusions/holds from disk + inputs passed in) and run the categorizer.
"""
from . import categorize, config
from . import contracts as c


def categorize_payload(payload: dict, root=".") -> c.Categories:
    """Categorize a gathered payload of updates + advisories.

    payload keys:
      updates:        [UpdateRecord dicts]         (required, may be empty)
      advisories:     [Advisory dicts]             (required, may be empty)
      exclude:        [glob pattern, ...]          (optional; pinned names, etc.)
      holds:          {name: reason}               (optional)
      replaceTargets: [name, ...]                  (optional; Go replace targets)

    Disk exclusions/holds (CLAUDE.md '## Bump Exclusions' + .bump-config.json,
    via config.merged_exclusions) are merged with anything passed in.
    """
    updates = c.load_records(payload.get("updates", []))
    advisories = c.load_advisories(payload.get("advisories", []))
    disk_excl, disk_holds = config.merged_exclusions(root)
    exclude = list(disk_excl) + list(payload.get("exclude", []))
    holds = {**disk_holds, **payload.get("holds", {})}
    replace_targets = set(payload.get("replaceTargets", []))
    return categorize.categorize(updates, advisories, exclude, holds, replace_targets)
