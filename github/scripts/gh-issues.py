#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Fetch GitHub issues with Projects v2 fields (status, priority) as JSON.

Usage:
    gh-issues.py [--repo OWNER/REPO] [--branch BRANCH] [--milestone M]
                 [--assignee A] [--status S] [--project P]
"""

import argparse
import json
import re
import subprocess
import sys


def run_gh(args: list[str]) -> str:
    """Run a gh CLI command and return stdout. Exit on failure."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout
    except FileNotFoundError:
        print("Error: 'gh' CLI not found. Install it from https://cli.github.com/", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        print(f"Error running 'gh {' '.join(args)}':\n{e.stderr.strip()}", file=sys.stderr)
        sys.exit(1)


def get_git_context() -> dict:
    """Extract repo and branch from git context. Returns None values on failure."""
    context = {"repo": None, "branch": None}
    try:
        subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return context

    # Get branch
    try:
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        context["branch"] = result.stdout.strip() or None
    except subprocess.CalledProcessError:
        pass

    # Get repo via gh
    try:
        output = run_gh(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
        context["repo"] = output.strip() or None
    except SystemExit:
        # run_gh calls sys.exit on failure -- catch it here since repo detection is best-effort
        pass

    return context


def fetch_issues(repo: str, milestone: str | None, assignee: str | None) -> list[dict]:
    """Fetch open issues from the repo using gh issue list."""
    gh_args = [
        "issue", "list",
        "--repo", repo,
        "--state", "open",
        "--json", "number,title,milestone,assignees,state,body,labels,comments",
        "--limit", "200",
    ]
    if milestone:
        gh_args.extend(["--milestone", milestone])
    if assignee:
        gh_args.extend(["--assignee", assignee])

    output = run_gh(gh_args)
    return json.loads(output)


def find_project(owner: str, repo: str, project_arg: str | None) -> int | None:
    """Find the GitHub Project number. Returns None if no project found."""
    if project_arg:
        # If numeric, use directly as project number
        if project_arg.isdigit():
            return int(project_arg)
        # Otherwise, search by title
        output = run_gh(["project", "list", "--owner", owner, "--format", "json"])
        projects = json.loads(output).get("projects", [])
        for proj in projects:
            if proj["title"].lower() == project_arg.lower():
                return proj["number"]
        print(f"Warning: no project found matching '{project_arg}'", file=sys.stderr)
        return None

    # Auto-detect: find a project that contains items from this repo
    output = run_gh(["project", "list", "--owner", owner, "--format", "json"])
    projects = json.loads(output).get("projects", [])

    repo_name = repo.split("/")[-1]
    for proj in projects:
        items_output = run_gh([
            "project", "item-list", str(proj["number"]),
            "--owner", owner,
            "--format", "json",
            "--limit", "50",
        ])
        items = json.loads(items_output).get("items", [])
        for item in items:
            item_repo = item.get("content", {}).get("repository", "")
            if item_repo == repo or item_repo.endswith(f"/{repo_name}"):
                return proj["number"]

    return None


def fetch_project_items(project_number: int, owner: str) -> list[dict]:
    """Fetch all items from a GitHub Project."""
    output = run_gh([
        "project", "item-list", str(project_number),
        "--owner", owner,
        "--format", "json",
        "--limit", "500",
    ])
    return json.loads(output).get("items", [])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch GitHub issues with Projects v2 fields as JSON."
    )
    parser.add_argument("--repo", help="GitHub repo in owner/repo format")
    parser.add_argument("--branch", help="Git branch name (for semver extraction)")
    parser.add_argument("--milestone", help="Filter by milestone title")
    parser.add_argument("--assignee", help="Filter by assignee login")
    parser.add_argument("--status", help="Filter by GitHub Projects status (case-insensitive)")
    parser.add_argument("--project", help="GitHub Project number or title (skips auto-detection)")
    return parser.parse_args()


def main():
    args = parse_args()
    git_ctx = get_git_context()

    # Resolve repo
    repo = args.repo or git_ctx["repo"]
    if not repo:
        print("Error: --repo is required when not in a git repo with a GitHub remote.", file=sys.stderr)
        sys.exit(1)

    # Resolve milestone: explicit --milestone wins, otherwise extract semver from branch
    milestone = args.milestone
    if not milestone:
        branch = args.branch or git_ctx["branch"]
        if branch:
            match = re.search(r"(\d+\.\d+(?:\.\d+)?)", branch)
            if match:
                milestone = match.group(1)

    owner = repo.split("/")[0]

    # Fetch issues
    issues = fetch_issues(repo, milestone, args.assignee)

    # Find project and fetch project items
    project_number = find_project(owner, repo, args.project)
    project_items = []
    if project_number:
        project_items = fetch_project_items(project_number, owner)
    elif not args.project:
        print("Warning: no GitHub Project found for this repo. Status and priority will be null.", file=sys.stderr)

    # Build lookup: issue_number -> {status, priority}
    project_lookup = {}
    repo_name = repo.split("/")[-1]
    for item in project_items:
        content = item.get("content", {})
        if content.get("type") != "Issue":
            continue
        item_repo = content.get("repository", "")
        # repository field is "owner/repo" format
        if item_repo == repo or item_repo.endswith(f"/{repo_name}"):
            project_lookup[content["number"]] = {
                "status": item.get("status"),
                "priority": item.get("priority"),
            }

    # Flatten and join
    results = []
    for issue in issues:
        milestone_title = None
        if issue.get("milestone"):
            milestone_title = issue["milestone"].get("title")

        assignee_login = None
        if issue.get("assignees"):
            assignee_login = issue["assignees"][0].get("login")

        proj_data = project_lookup.get(issue["number"], {})
        status = proj_data.get("status")
        priority = proj_data.get("priority")

        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        comments = [
            {"author": c.get("author", {}).get("login"), "body": c.get("body")}
            for c in issue.get("comments", [])
        ]

        results.append({
            "number": issue["number"],
            "title": issue["title"],
            "milestone": milestone_title,
            "assignee": assignee_login,
            "status": status,
            "priority": priority,
            "labels": labels,
            "body": issue.get("body", ""),
            "comments": comments,
        })

    # Apply client-side status filter
    if args.status:
        results = [r for r in results if r["status"] and r["status"].lower() == args.status.lower()]

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
