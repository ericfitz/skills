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


def ensure_gitignore_file(gitignore_path):
    """Ensure `.local/` is ignored in the given .gitignore file."""
    path = Path(gitignore_path)
    text = path.read_text() if path.exists() else ""
    new_text = ensure_gitignore_text(text)
    if new_text != text:
        path.write_text(new_text)


def process_entry(entry, selection, now_iso, config, config_path, cache_path, gitignore_path):
    """Resolve one entry's project and update cache/config. Returns a result dict."""
    name = entry.get("name")
    gh = entry.get("github", {})
    owner, repo = gh.get("owner"), gh.get("repo")
    if not owner or not repo:
        o2, r2 = parse_git_remote(git_remote_url())
        owner = owner or o2
        repo = repo or r2
    if not owner or not repo:
        return {"name": name, "status": "error",
                "message": "no owner/repo in config and none derivable from git remote"}

    linked = discover_linked_projects(owner, repo)
    status, payload = select_project(
        linked,
        named_title=gh.get("project"),
        selected_title=selection.get("title"),
        selected_number=selection.get("number"),
    )

    if status == "needs_selection":
        return {"name": name, "status": "needs_selection",
                "candidates": [{"number": p["number"], "title": p["title"]}
                               for p in payload]}
    if status == "none":
        set_project_title(config, name, "")
        write_json(config_path, config)
        return {"name": name, "status": "none"}

    project = payload
    cache_entry = enumerate_project(owner, repo, project, now_iso)
    update_cache(cache_path, name, cache_entry)
    set_project_title(config, name, project["title"])
    write_json(config_path, config)
    ensure_gitignore_file(gitignore_path)
    return {"name": name, "status": "resolved", "title": project["title"]}


def _load_or_init_config(start_dir):
    """Return (config_dict, config_path). Migrate a legacy file if found.

    If no config exists, initialize one under <start_dir>/.local/projects.json with a
    single entry named after the repo (from git remote, else the directory name).
    """
    start_dir = Path(start_dir).absolute()
    path, is_legacy = find_config(start_dir)
    if path is None:
        owner, repo = parse_git_remote(git_remote_url())
        name = repo or start_dir.name
        config = {"projects": [{"name": name, "github": {}}]}
        if owner and repo:
            config["projects"][0]["github"] = {"owner": owner, "repo": repo}
        new_path = start_dir / LOCAL_DIR / CONFIG_FILENAME
        return config, new_path
    config = json.loads(path.read_text())
    config["projects"] = [migrate_entry(e) for e in config.get("projects", [])]
    if is_legacy:
        # Move into .local/projects.json beside the legacy file's directory.
        new_path = path.parent / LOCAL_DIR / CONFIG_FILENAME
        return config, new_path
    return config, path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Resolve a repo's GitHub Project and cache its metadata.")
    parser.add_argument("command", choices=["update"])
    parser.add_argument("--name", help="Only process the entry with this name.")
    parser.add_argument("--dir", default=".", help="Directory to resolve config from.")
    parser.add_argument("--select-title", help="Force-select a project by title.")
    parser.add_argument("--select-number", type=int, help="Force-select a project by number.")
    args = parser.parse_args(argv)

    config, config_path = _load_or_init_config(args.dir)
    cache_path = config_path.parent / CACHE_FILENAME
    # config_path is <repo-root>/.local/projects.json, so .parent.parent is repo root.
    gitignore_path = config_path.parent.parent / ".gitignore"
    now_iso = datetime.now(timezone.utc).isoformat()

    selection = {}
    if args.select_title:
        selection["title"] = args.select_title
    if args.select_number is not None:
        selection["number"] = args.select_number

    entries = config.get("projects", [])
    if args.name:
        entries = [e for e in entries if e.get("name") == args.name]
        if not entries:
            print(json.dumps({"results": [
                {"name": args.name, "status": "error", "message": "entry not found"}]}))
            return 1

    results = []
    for e in entries:
        try:
            results.append(process_entry(e, selection, now_iso, config,
                                         config_path, cache_path, gitignore_path))
        except GhError as exc:
            results.append({"name": e.get("name"), "status": "error",
                            "message": str(exc)})
    print(json.dumps({"results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
