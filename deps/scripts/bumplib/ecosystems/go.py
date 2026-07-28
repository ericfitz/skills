"""Go ecosystem adapter."""
import json
import re
import shutil
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
    out, in_block = set(), False
    for line in gomod_text.splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        if s.startswith("replace ("):
            in_block = True
            continue
        if in_block:
            if s == ")":
                in_block = False
            elif "=>" in s:
                out.add(s.split("=>")[0].strip().split()[0])
            continue
        if s.startswith("replace ") and "=>" in s:
            out.add(s[len("replace "):].split("=>")[0].strip().split()[0])
    return out


def pinned_names(gomod_text: str) -> set:
    out = set()
    for line in gomod_text.splitlines():
        if "// pinned:" not in line:
            continue
        toks = line.split("//")[0].strip().split()
        if not toks:
            continue
        name = toks[1] if toks[0] == "require" and len(toks) > 1 else toks[0]
        out.add(name)
    return out


def parse_vuln(json_text: str) -> list:
    """Parse govulncheck -json output: a stream of concatenated JSON objects.
    Emit one Advisory per OSV record (dedup by id)."""
    advs, seen = [], set()
    dec = json.JSONDecoder()
    idx, n = 0, len(json_text)
    while idx < n:
        while idx < n and json_text[idx].isspace():
            idx += 1
        if idx >= n:
            break
        try:
            obj, end = dec.raw_decode(json_text, idx)
        except ValueError:
            break
        idx = end
        osv = obj.get("osv") if isinstance(obj, dict) else None
        if isinstance(osv, dict) and osv.get("id") and osv["id"] not in seen:
            seen.add(osv["id"])
            affected = osv.get("affected") or [{}]
            pkg = affected[0].get("package", {}).get("name", "") if affected else ""
            severity = osv.get("database_specific", {}).get("severity", "")
            advs.append(c.Advisory(package=pkg, ecosystem="go", severity=severity,
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
        if shutil.which("govulncheck") is None:
            return []
        out = _run(["govulncheck", "-json", "./..."])
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
