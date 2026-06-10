#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Resolve a repo's GitHub Project (v2) and cache its metadata locally.

Builds/refreshes `.local/project-cache.json` (ids, fields, milestones, labels,
issue types) for projects named or discovered for a repo, and records the
resolved project title back into `.local/projects.json`.

Usage:
    update_project_cache.py update [--name NAME] [--dir DIR]
                                   [--select-title TITLE | --select-number N]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOCAL_DIR = ".local"
CONFIG_FILENAME = "projects.json"
CACHE_FILENAME = "project-cache.json"
LEGACY_CONFIG_FILENAME = ".local-projects.json"


def build_cache_entry(project, fields, milestones, labels, issue_types, now_iso):
    """Assemble one project's cache entry."""
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


def parse_milestones(data):
    """Map `gh api repos/{o}/{r}/milestones` output to ordered {title, number, id}."""
    return [{"title": m.get("title"), "number": m.get("number"), "id": m.get("node_id")}
            for m in (data or []) if m.get("title")]


def parse_labels(data):
    """Map `gh api repos/{o}/{r}/labels` output to a list of label names."""
    return [lbl.get("name") for lbl in (data or []) if lbl.get("name")]


def parse_issue_types(data):
    """Best-effort: accept a list of {name} or a {issue_types|data: [...]} wrapper."""
    if isinstance(data, dict):
        data = data.get("issue_types") or data.get("data") or []
    return [t.get("name") for t in (data or [])
            if isinstance(t, dict) and t.get("name")]


FIELD_TYPE_MAP = {
    "ProjectV2SingleSelectField": "single_select",
    "ProjectV2IterationField": "iteration",
    "ProjectV2Field": "field",
}


def parse_fields(data):
    """Convert `gh project field-list --format json` output to the cache fields map."""
    fields = {}
    for f in (data or {}).get("fields", []) or []:
        name = f.get("name")
        if not name:
            continue
        ftype = FIELD_TYPE_MAP.get(f.get("type"), "field")
        entry = {"id": f.get("id"), "type": ftype}
        if f.get("options"):
            entry["options"] = [{"name": o.get("name"), "id": o.get("id")}
                                for o in f["options"]]
        elif ftype == "iteration":
            iters = (f.get("configuration") or {}).get("iterations") or []
            if iters:
                entry["options"] = [{"name": it.get("title"), "id": it.get("id")}
                                    for it in iters]
        fields[name] = entry
    return fields


def _find_by_title(linked, title):
    for p in linked:
        if (p.get("title") or "").lower() == title.lower():
            return p
    return None


def select_project(linked, named_title=None, selected_title=None, selected_number=None):
    """Decide which project to use.

    Returns (status, payload):
      ("resolved", project_dict)
      ("needs_selection", [candidate_dicts])
      ("none", None)
    """
    if selected_number is not None:
        for p in linked:
            if p.get("number") == selected_number:
                return ("resolved", p)
        return ("none", None)
    if selected_title:
        p = _find_by_title(linked, selected_title)
        return ("resolved", p) if p else ("none", None)
    if named_title:  # "" marker is falsy -> skipped -> discovery
        p = _find_by_title(linked, named_title)
        if p:
            return ("resolved", p)
        # named project no longer linked: fall through to discovery
    if len(linked) == 1:
        return ("resolved", linked[0])
    if len(linked) > 1:
        return ("needs_selection", linked)
    return ("none", None)


def parse_linked_projects(data):
    """Extract a list of {number, id, title, owner} from a repository.projectsV2 query."""
    repo = (data or {}).get("data", {}).get("repository") or {}
    nodes = (repo.get("projectsV2") or {}).get("nodes") or []
    out = []
    for n in nodes:
        if not n:
            continue
        out.append({
            "number": n.get("number"),
            "id": n.get("id"),
            "title": n.get("title"),
            "owner": (n.get("owner") or {}).get("login"),
        })
    return out


def parse_git_remote(url):
    """Parse a git remote URL into (owner, repo); (None, None) if unparseable."""
    if not url:
        return (None, None)
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    m = re.search(r"[:/]([^/:]+)/([^/:]+)$", url)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))


def get_entry(config, name):
    """Return the first entry in config["projects"] with the given name, or None."""
    for e in (config or {}).get("projects", []):
        if e.get("name") == name:
            return e
    return None


def set_project_title(config, name, title):
    """Set github.project for `name`, creating the entry if needed. Returns config."""
    e = get_entry(config, name)
    if e is None:
        e = {"name": name, "github": {}}
        config.setdefault("projects", []).append(e)
    e.setdefault("github", {})["project"] = title
    return config


def migrate_entry(entry):
    """Drop a legacy issues_project ID block; keep owner/repo/project title."""
    gh = dict(entry.get("github", {}))
    gh.pop("issues_project", None)
    out = dict(entry)
    out["github"] = gh
    return out


def ensure_gitignore_text(text, entry=".local/"):
    """Return gitignore text with `entry` present (idempotent)."""
    target = entry.rstrip("/")
    for line in text.splitlines():
        if line.strip().rstrip("/") == target:
            return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + entry + "\n"


def write_json(path, data):
    """Write JSON atomically, creating parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def find_config(start_dir):
    """Walk up from start_dir. Return (Path, is_legacy) or (None, False)."""
    d = Path(start_dir).absolute()
    for parent in [d, *d.parents]:
        new = parent / LOCAL_DIR / CONFIG_FILENAME
        if new.exists():
            return (new, False)
        legacy = parent / LEGACY_CONFIG_FILENAME
        if legacy.exists():
            return (legacy, True)
    return (None, False)


def update_cache(cache_path, name, entry):
    """Merge one project's entry into the cache file, preserving other keys."""
    cache_path = Path(cache_path)
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    cache[name] = entry
    write_json(cache_path, cache)
    return cache


class GhError(RuntimeError):
    """Raised when a gh CLI call fails."""


PROJECTS_QUERY = """
query($owner:String!, $repo:String!) {
  repository(owner:$owner, name:$repo) {
    projectsV2(first:50) {
      nodes {
        number title id
        owner { ... on User { login } ... on Organization { login } }
      }
    }
  }
}
"""


def run_gh(args):
    """Run a gh command; return stdout. Raise GhError on failure."""
    try:
        result = subprocess.run(["gh"] + args, capture_output=True, text=True, check=True)
        return result.stdout
    except FileNotFoundError:
        print("Error: 'gh' CLI not found. Install it from https://cli.github.com/",
              file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        raise GhError(e.stderr.strip()) from e


def run_gh_json(args):
    """Run a gh command and parse stdout as JSON."""
    return json.loads(run_gh(args))


def run_gh_graphql(query, variables):
    """Run a GraphQL query via `gh api graphql` with -F field=value variables."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F", f"{k}={v}"]
    return run_gh_json(args)


def git_remote_url():
    """Return the origin remote URL, or '' if unavailable."""
    try:
        result = subprocess.run(["git", "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def discover_linked_projects(owner, repo):
    """Return linked Projects v2 for a repo as a list of {number,id,title,owner}."""
    data = run_gh_graphql(PROJECTS_QUERY, {"owner": owner, "repo": repo})
    return parse_linked_projects(data)


def enumerate_project(owner, repo, project, now_iso):
    """Gather all metadata for the chosen project and assemble a cache entry."""
    field_data = run_gh_json([
        "project", "field-list", str(project["number"]),
        "--owner", project["owner"], "--format", "json",
    ])
    fields = parse_fields(field_data)

    milestones = parse_milestones(run_gh_json([
        "api", f"repos/{owner}/{repo}/milestones?state=all&per_page=100",
    ]))
    labels = parse_labels(run_gh_json([
        "api", f"repos/{owner}/{repo}/labels?per_page=100",
    ]))
    try:
        issue_types = parse_issue_types(run_gh_json([
            "api", f"repos/{owner}/{repo}/issue-types",
        ]))
    except GhError:
        issue_types = []  # issue types not enabled / endpoint unavailable

    return build_cache_entry(project, fields, milestones, labels, issue_types, now_iso)
