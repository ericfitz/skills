"""GitHub issue-tracker adapter: dependency-related issues."""
import json
import shutil
import subprocess

from .. import contracts as c


def parse_issues(json_text: str) -> c.Context:
    """Parse issues from gh issue list JSON output.

    Args:
        json_text: JSON array from gh issue list --json number,title,labels,url

    Returns:
        Context with issues list
    """
    data = json.loads(json_text or "[]")
    issues = [
        {
            "id": f"#{i['number']}",
            "title": i.get("title", ""),
            "url": i.get("url", ""),
            "labels": [label.get("name", "") for label in i.get("labels", [])],
        }
        for i in data
    ]
    return c.Context(issues=issues)


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def handle(verb, argv):
    """Main entry point for GitHub issue-tracker operations.

    Args:
        verb: Operation verb (issues)
        argv: Arguments for the verb

    Returns:
        Context with issues list
    """
    if verb == "issues":
        # Return empty Context if gh is not installed (graceful degradation)
        if shutil.which("gh") is None:
            return c.Context()
        r = _run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                "dependencies",
                "--state",
                "open",
                "--json",
                "number,title,labels,url",
                "--limit",
                "20",
            ]
        )
        return parse_issues(r.stdout if r.returncode == 0 else "[]")

    raise ValueError(f"github tracker: unknown verb {verb}")
