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
