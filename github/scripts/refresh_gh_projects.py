#!/usr/bin/env python3
"""Best-effort session-start refresher for `.local/gh-projects.json`.

Re-resolves each cached GitHub Project's fields, milestones, labels, and
issue types via `gh` so the `github:create-issue` / `github:backlog` skills
never operate on a stale cache. Refresh-only: it never creates `.local/` or
the cache file, and it never reads or writes `.local/repos.json` (that
registry belongs to `~/Scripts/provision-repo-config.py`, the sole creator).

This is intended to run from a SessionStart hook, so every failure path is
silent and the process always exits 0 — a failed refresh must never block or
break session start. Pass --verbose to see what happened when running by
hand; the hook invocation does not pass it.

Stdlib only: no PEP 723 dependencies, no uv. `gh` does all the API work.

Usage:
    refresh_gh_projects.py [--verbose] [--cwd PATH]
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

LOCAL_DIR = ".local"
CACHE_FILENAME = "gh-projects.json"

GH_TIMEOUT = 5          # seconds, per subprocess call (git or gh)
SOFT_BUDGET_SECONDS = 15.0  # total wall-clock budget across all entries

_REMOTE_RE = re.compile(r"[:/]([^/:]+)/([^/:]+)$")

_FIELD_TYPE_MAP = {
    "ProjectV2SingleSelectField": "single_select",
    "ProjectV2IterationField": "iteration",
    "ProjectV2Field": "field",
}


class GhError(RuntimeError):
    """Raised when a `gh` invocation exits non-zero."""


class RefreshError(RuntimeError):
    """Raised when a cached entry cannot be re-resolved."""


# --- gh/git plumbing --------------------------------------------------------

def _run(argv: list[str], cwd: Path | None = None, timeout: int = GH_TIMEOUT) -> str:
    """Run a subprocess; return stdout. Raises on non-zero exit, missing
    binary, or timeout — callers decide what "best effort" means."""
    result = subprocess.run(
        argv, shell=False, capture_output=True, text=True,
        timeout=timeout, cwd=str(cwd) if cwd else None,
    )
    if result.returncode != 0:
        raise GhError((result.stderr or "").strip())
    return result.stdout


def _run_gh_json(argv: list[str]) -> object:
    return json.loads(_run(["gh", *argv]))


def _parse_git_remote(url: str) -> tuple[str | None, str | None]:
    """Parse a git remote URL into (owner, repo); (None, None) if unparseable."""
    url = (url or "").strip()
    if not url:
        return (None, None)
    if url.endswith(".git"):
        url = url[:-4]
    m = _REMOTE_RE.search(url)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))


def _git_toplevel(start: Path) -> Path | None:
    try:
        out = _run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    except Exception:
        return None
    out = out.strip()
    return Path(out) if out else None


def _repo_owner_repo(root: Path) -> tuple[str | None, str | None]:
    try:
        out = _run(["git", "remote", "get-url", "origin"], cwd=root)
    except Exception:
        return (None, None)
    return _parse_git_remote(out)


# --- provisioning-shape parsing (mirrors provision-repo-config.py) --------

def _parse_fields(data: dict) -> dict:
    fields = {}
    for f in (data or {}).get("fields", []) or []:
        name = f.get("name")
        if not name:
            continue
        ftype = _FIELD_TYPE_MAP.get(f.get("type"), "field")
        entry = {"id": f.get("id"), "type": ftype}
        if f.get("options"):
            entry["options"] = [{"name": o.get("name"), "id": o.get("id")} for o in f["options"]]
        elif ftype == "iteration":
            iters = (f.get("configuration") or {}).get("iterations") or []
            if iters:
                entry["options"] = [{"name": it.get("title"), "id": it.get("id")} for it in iters]
        fields[name] = entry
    return fields


def _parse_milestones(data: list) -> list:
    return [{"title": m.get("title"), "number": m.get("number"), "id": m.get("node_id")}
            for m in (data or []) if m.get("title")]


def _parse_labels(data: list) -> list:
    return [lbl.get("name") for lbl in (data or []) if lbl.get("name")]


def _parse_issue_types(data) -> list:
    if isinstance(data, dict):
        data = data.get("issue_types") or data.get("data") or []
    return [t.get("name") for t in (data or []) if isinstance(t, dict) and t.get("name")]


def _build_cache_entry(project: dict, fields: dict, milestones: list,
                       labels: list, issue_types: list, now_iso: str) -> dict:
    return {
        "cached_at": now_iso,
        "project": {
            "number": project.get("number"),
            "owner": project.get("owner"),
            "id": project.get("id"),
            "title": project.get("title"),
        },
        "fields": fields,
        "milestones": milestones,
        "labels": labels,
        "issue_types": issue_types,
    }


def _refresh_entry(entry: dict, owner: str | None, repo: str | None, now_iso: str) -> dict:
    project = entry.get("project") or {}
    number = project.get("number")
    powner = project.get("owner")
    if number is None or not powner:
        raise RefreshError("cached entry has no project number/owner")
    if not owner or not repo:
        raise RefreshError("could not resolve repo owner/repo from git remote")

    field_data = _run_gh_json(["project", "field-list", str(number),
                               "--owner", powner, "--format", "json"])
    fields = _parse_fields(field_data)
    milestones = _parse_milestones(
        _run_gh_json(["api", f"repos/{owner}/{repo}/milestones?state=all&per_page=100"]))
    labels = _parse_labels(
        _run_gh_json(["api", f"repos/{owner}/{repo}/labels?per_page=100"]))
    try:
        issue_types = _parse_issue_types(
            _run_gh_json(["api", f"repos/{owner}/{repo}/issue-types"]))
    except GhError:
        # a non-zero exit (404/disabled endpoint) means "not enabled here";
        # timeouts/missing-binary/bad-JSON are real failures and must
        # propagate so the caller preserves the whole cached entry instead.
        issue_types = []

    return _build_cache_entry(project, fields, milestones, labels, issue_types, now_iso)


# --- cache comparison + atomic write ---------------------------------------

def _strip_cached_at(cache: dict) -> dict:
    out = {}
    for name, entry in cache.items():
        if isinstance(entry, dict):
            out[name] = {k: v for k, v in entry.items() if k != "cached_at"}
        else:
            out[name] = entry
    return out


def _atomic_write(path: Path, data: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        os.replace(tmp_name, str(path))
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


# --- orchestration -----------------------------------------------------------

def _do_refresh(cwd: Path, verbose: bool) -> int:
    root = _git_toplevel(cwd)
    if root is None:
        if verbose:
            print(f"{cwd}: not inside a git repo; nothing to refresh", file=sys.stderr)
        return 0

    cache_path = root / LOCAL_DIR / CACHE_FILENAME
    if not cache_path.exists():
        if verbose:
            print(f"{cache_path}: no cache; nothing to refresh", file=sys.stderr)
        return 0

    try:
        original_cache = json.loads(cache_path.read_text())
    except Exception as exc:
        if verbose:
            print(f"{cache_path}: unparseable, leaving alone ({exc})", file=sys.stderr)
        return 0
    if not isinstance(original_cache, dict):
        if verbose:
            print(f"{cache_path}: not a JSON object, leaving alone", file=sys.stderr)
        return 0

    owner, repo = _repo_owner_repo(root)
    now_iso = datetime.now(timezone.utc).isoformat()  # noqa: UP017 -- bare python3, not py311+
    start = time.monotonic()
    over_budget = False
    new_cache: dict = {}

    for name, entry in original_cache.items():
        if not isinstance(entry, dict):
            new_cache[name] = entry
            continue
        if over_budget or (time.monotonic() - start) > SOFT_BUDGET_SECONDS:
            over_budget = True
            new_cache[name] = entry
            if verbose:
                print(f"{name}: soft time budget exceeded, keeping cached value", file=sys.stderr)
            continue
        try:
            new_cache[name] = _refresh_entry(entry, owner, repo, now_iso)
            if verbose:
                print(f"{name}: refreshed", file=sys.stderr)
        except Exception as exc:
            new_cache[name] = entry
            if verbose:
                print(f"{name}: refresh failed, keeping cached value ({exc})", file=sys.stderr)

    if _strip_cached_at(new_cache) == _strip_cached_at(original_cache):
        if verbose:
            print(f"{cache_path}: no content changes, leaving file untouched", file=sys.stderr)
        return 0

    try:
        _atomic_write(cache_path, new_cache)
        if verbose:
            print(f"{cache_path}: rewritten", file=sys.stderr)
    except Exception as exc:
        if verbose:
            print(f"{cache_path}: failed to write ({exc})", file=sys.stderr)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Best-effort refresh of .local/gh-projects.json.")
    parser.add_argument("--verbose", action="store_true",
                        help="print what was refreshed/skipped and why")
    parser.add_argument("--cwd", default=None,
                        help="directory to resolve the repo from (default: current directory)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    cwd = Path(args.cwd) if args.cwd else Path.cwd()
    try:
        return _do_refresh(cwd, args.verbose)
    except Exception as exc:
        # Belt-and-braces: _do_refresh already swallows its own failures, but
        # a session-start hook must never propagate an exception either way.
        if args.verbose:
            print(f"unexpected error: {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
