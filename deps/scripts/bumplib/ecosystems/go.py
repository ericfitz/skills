"""Go ecosystem adapter."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump
from ..gitfiles import changed_files

_OUTDATED = re.compile(r"^(\S+)\s+(\S+)\s+\[(\S+)\]")


def parse_outdated(text: str, required: dict | None = None) -> list:
    """Parse `go list -m -u all`. With `required` (see required_modules), keep only
    modules go.mod itself requires: `all` also lists the whole build graph, and
    `go get` on a graph-only module adds it to go.mod as a new indirect require."""
    recs = []
    for line in text.splitlines():
        m = _OUTDATED.match(line.strip())
        if not m:
            continue
        name, cur, lat = m.group(1), m.group(2), m.group(3)
        if required is not None and name not in required:
            continue
        recs.append(c.UpdateRecord(name=name, current=cur, latest=lat, wanted=lat,
                                   bump=classify_bump(cur, lat),
                                   kind=required[name] if required else "direct",
                                   location="go.mod", ecosystem="go"))
    return recs


def required_modules(gomod_text: str) -> dict:
    """{module path: "direct" | "indirect"} for every require entry in go.mod."""
    out, in_block = {}, False
    for line in gomod_text.splitlines():
        s = line.strip()
        if s.startswith("require ("):
            in_block = True
            continue
        if in_block and s == ")":
            in_block = False
            continue
        if not (in_block or s.startswith("require ")):
            continue
        toks = s.split("//")[0].split()
        if toks and toks[0] == "require":
            toks = toks[1:]
        if len(toks) >= 2 and toks[1].startswith("v"):
            out[toks[0]] = "indirect" if "// indirect" in s else "direct"
    return out


def _workspace_gomods(root: Path) -> list:
    """go.mod files to read: the root one plus each go.work `use` dir, if any."""
    mods, in_use = [root / "go.mod"], False
    work = root / "go.work"
    for line in work.read_text().splitlines() if work.exists() else []:
        s = line.strip()
        if s.startswith("use ("):
            in_use = True
        elif in_use and s == ")":
            in_use = False
        elif s.startswith("use "):
            mods.append(root / s[4:].strip() / "go.mod")
        elif in_use and s and not s.startswith("//"):
            mods.append(root / s / "go.mod")
    return [m for m in mods if m.exists()]


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
        required = {}
        for gomod in _workspace_gomods(root):
            required.update(required_modules(gomod.read_text()))
        return parse_outdated(out.stdout, required)
    if verb == "audit":
        if shutil.which("govulncheck") is None:
            return []
        out = _run(["govulncheck", "-json", "./..."])
        return parse_vuln(out.stdout)
    if verb == "apply":
        steps = [["go", "get", spec] for spec in argv]   # spec e.g. "github.com/foo/bar@v1.2.3"
        steps.append(["go", "mod", "tidy"])
        if (root / "go.work").exists():
            steps.append(["go", "work", "sync"])
        for cmd in steps:
            r = _run(cmd)
            if r.returncode != 0:
                return {"applied": [], "filesModified": [],
                        "error": f"{' '.join(cmd)}: " + (r.stdout + r.stderr)[-4000:]}
        return {"applied": argv, "filesModified": changed_files(["go.mod", "go.sum"], cwd=root)}
    if verb == "validate":
        results = {}
        for step, cmd in (("build", "go build ./..."), ("test", "go test ./..."), ("lint", "go vet ./...")):
            r = _run_shell(cmd)         # trusted config/default strings
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"go: unknown verb {verb}")
