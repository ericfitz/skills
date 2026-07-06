"""Go ecosystem adapter."""
import re
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump

_OUTDATED = re.compile(r"^(\S+)\s+(\S+)\s+\[(\S+)\]")


def parse_outdated(text: str) -> list:
    recs = []
    for line in text.splitlines():
        m = _OUTDATED.match(line.strip())
        if not m:
            continue
        name, cur, lat = m.group(1), m.group(2), m.group(3)
        recs.append(c.UpdateRecord(name=name, current=cur, latest=lat, wanted=lat,
                                   bump=classify_bump(cur, lat), kind="direct",
                                   location="go.mod", ecosystem="go"))
    return recs


def replace_targets(gomod_text: str) -> set:
    out = set()
    for line in gomod_text.splitlines():
        s = line.strip()
        if s.startswith("replace "):
            body = s[len("replace "):].split("=>")[0].strip()
            out.add(body.split()[0])
    return out


def pinned_names(gomod_text: str) -> set:
    out = set()
    for line in gomod_text.splitlines():
        if "// pinned:" in line:
            out.add(line.strip().split()[0])
    return out


def parse_vuln(json_text: str) -> list:
    import json
    advs = []
    for line in json_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        osv = obj.get("osv") or obj.get("finding")
        if isinstance(osv, dict) and osv.get("id"):
            advs.append(c.Advisory(package=osv.get("affected", [{}])[0].get("package", {}).get("name", ""),
                                   ecosystem="go", severity=osv.get("database_specific", {}).get("severity", ""),
                                   current="", fixed="", ids=[osv["id"]],
                                   summary=osv.get("summary", ""), source="govulncheck"))
    return advs


def _run(args):
    """Safe: args is a list, no shell — metacharacters in package specs cannot inject."""
    return subprocess.run(args, capture_output=True, text=True)


def _run_shell(cmd):
    """ONLY for trusted, config-sourced command strings that may use shell operators
    (e.g. 'go vet ./...'). Never pass per-run/user data here — use _run(list) for that.
    Same trust level as a Makefile target the project already runs."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def handle(verb, argv):
    root = Path(".")
    if verb == "detect":
        present = (root / "go.mod").exists()
        return {"present": present, "ecosystem": "go", "packageManager": "",
                "workspace": (root / "go.work").exists()}
    if verb == "cache-clear":
        return {"warnings": []}  # go refreshes via `go list`; no aggressive clean
    if verb == "outdated":
        out = _run(["go", "list", "-m", "-u", "all"])
        return parse_outdated(out.stdout)
    if verb == "audit":
        out = _run(["govulncheck", "-json", "./..."])
        if "not found" in out.stderr or out.returncode == 127:
            return []
        return parse_vuln(out.stdout)
    if verb == "apply":
        for spec in argv:               # spec e.g. "github.com/foo/bar@v1.2.3"
            _run(["go", "get", spec])
        _run(["go", "mod", "tidy"])
        if (root / "go.work").exists():
            _run(["go", "work", "sync"])
        return {"applied": argv, "filesModified": ["go.mod", "go.sum"]}
    if verb == "validate":
        results = {}
        for step, cmd in (("build", "go build ./..."), ("test", "go test ./..."), ("lint", "go vet ./...")):
            r = _run_shell(cmd)         # trusted config/default strings
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"go: unknown verb {verb}")
