"""GitHub code-host adapter: Dependabot alerts, dependency PRs, PR lifecycle."""
import json
import shutil
import subprocess

from .. import contracts as c


def parse_alerts(json_text: str) -> list:
    """Parse Dependabot alerts from GitHub API response.

    Args:
        json_text: JSON array from repos/{owner}/{repo}/dependabot/alerts

    Returns:
        List of Advisory objects
    """
    data = json.loads(json_text or "[]")
    advs = []
    for a in data:
        if a.get("state") != "open":
            continue
        sa = a.get("security_advisory", {})
        dep = a.get("dependency", {}).get("package", {})
        # first_patched_version can be JSON null (no fix released yet); `or {}`
        # guards against None.get(...) when the key is present but null.
        fixed = (a.get("security_vulnerability", {}).get("first_patched_version") or {}).get("identifier", "")
        advs.append(c.Advisory(package=dep.get("name", ""), ecosystem=dep.get("ecosystem", ""),
                               severity=sa.get("severity", "").upper(), current="", fixed=fixed,
                               ids=[], summary=sa.get("summary", ""), source="dependabot"))
    return advs


def parse_prs(json_text: str) -> c.Context:
    """Parse dependency PRs from gh pr list output.

    Args:
        json_text: JSON array from gh pr list --json number,title,headRefName,url

    Returns:
        Context with pullRequests list
    """
    data = json.loads(json_text or "[]")
    prs = [{"id": f"#{p['number']}", "title": p.get("title", ""),
            "head": p.get("headRefName", ""), "url": p.get("url", "")} for p in data]
    return c.Context(pullRequests=prs)


def open_pr_cmd(branch, title, body):
    """Return an argv list for creating a pull request.

    Title and body are passed as separate args, never shell-interpolated,
    so a PR title containing shell metacharacters cannot inject.

    Args:
        branch: Target branch for PR (head ref)
        title: PR title
        body: PR body

    Returns:
        List form argv for subprocess
    """
    return ["gh", "pr", "create", "--base", "main", "--head", branch,
            "--title", title, "--body", body]


def merge_cmd(number):
    """Return an argv list for merging a pull request.

    Args:
        number: PR number

    Returns:
        List form argv for subprocess
    """
    return ["gh", "pr", "merge", str(number), "--squash", "--delete-branch"]


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def handle(verb, argv):
    """Main entry point for GitHub codehost operations.

    Args:
        verb: Operation verb (detect, alerts, prs, open-pr, pr-status, merge-pr)
        argv: Arguments for the verb

    Returns:
        Operation-specific result
    """
    if verb == "detect":
        r = _run(["git", "remote", "get-url", "origin"])
        return {"present": "github.com" in r.stdout}

    if verb == "alerts":
        # Return empty list if gh is not installed (graceful degradation)
        if shutil.which("gh") is None:
            return []
        # gh substitutes {owner}/{repo} from the current repo automatically.
        r = _run(["gh", "api", "repos/{owner}/{repo}/dependabot/alerts"])
        if r.returncode != 0:
            return []
        return parse_alerts(r.stdout)

    if verb == "prs":
        # Return empty Context if gh is not installed (graceful degradation)
        if shutil.which("gh") is None:
            return c.Context()
        r = _run(["gh", "pr", "list", "--label", "dependencies",
                  "--json", "number,title,headRefName,url", "--limit", "20"])
        return parse_prs(r.stdout if r.returncode == 0 else "[]")

    if verb == "open-pr":
        # Check if gh is installed for write operations
        if shutil.which("gh") is None:
            return {"ok": False, "output": "gh not installed"}
        branch, title, body = argv[0], argv[1], argv[2]
        r = _run(open_pr_cmd(branch, title, body))
        # `gh pr create` prints the PR URL to stdout and the failure reason to stderr,
        # so on failure stdout is empty by construction. Append stderr only then: the
        # skill scrapes the URL out of `output` on success and gh may still emit
        # unrelated warnings on stderr in that case (#36).
        ok = r.returncode == 0
        return {"output": (r.stdout if ok else r.stdout + r.stderr).strip(), "ok": ok}

    if verb == "pr-status":
        # Check if gh is installed for read operations
        if shutil.which("gh") is None:
            return {"error": "gh not installed"}
        number = argv[0]
        r = _run(["gh", "pr", "view", str(number), "--json",
                  "state,mergeable,mergeStateStatus,reviewDecision"])
        return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr.strip()}

    if verb == "merge-pr":
        # Check if gh is installed for write operations
        if shutil.which("gh") is None:
            return {"ok": False, "output": "gh not installed"}
        r = _run(merge_cmd(argv[0]))
        return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}

    raise ValueError(f"github codehost: unknown verb {verb}")
