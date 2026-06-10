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
