"""Go ecosystem adapter."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from .. import projects as proj
from ..categorize import classify_bump, parse_semver
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
        recs.append(
            c.UpdateRecord(
                name=name,
                current=cur,
                latest=lat,
                wanted=lat,
                bump=classify_bump(cur, lat),
                kind=required[name] if required else "direct",
                location="go.mod",
                ecosystem="go",
            )
        )
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
            out.add(s[len("replace ") :].split("=>")[0].strip().split()[0])
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
            advs.append(
                c.Advisory(
                    package=pkg,
                    ecosystem="go",
                    severity=severity,
                    current="",
                    fixed="",
                    ids=[osv["id"]],
                    summary=osv.get("summary", ""),
                    source="govulncheck",
                )
            )
    return advs


def parse_list_stream(json_text: str) -> dict:
    """Parse `go list -m -e -json` over several args: concatenated JSON objects.
    Returns {"path@version": GoMod file path}; a record with an error or without a
    GoMod file is left out, so the caller treats it as unknown."""
    out = {}
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
        if (
            isinstance(obj, dict)
            and obj.get("Path")
            and obj.get("Version")
            and obj.get("GoMod")
            and not obj.get("Error")
        ):
            out[f"{obj['Path']}@{obj['Version']}"] = obj["GoMod"]
    return out


def module_line(gomod_text: str) -> str:
    """The module path a go.mod declares, or "" when it has no readable module line."""
    for line in gomod_text.splitlines():
        s = line.split("//")[0].strip()
        if s.startswith("module") and s[6:7] in (" ", "\t", "("):
            toks = s[6:].strip().strip("()").strip().split()
            return toks[0].strip('"`') if toks else ""
    return ""


def last_version_with_path(current: str, latest: str, candidates: list, declared: dict, path: str) -> str:
    """Highest release above `current` (below `latest`) whose go.mod still declares
    `path`; "" when none does. `declared` maps a version to its declared module path."""
    cur, lat = parse_semver(current), parse_semver(latest)
    keep = [v for v in candidates if "-" not in v and cur < parse_semver(v) < lat and declared.get(v) == path]
    return max(keep, key=parse_semver, default="")


def _declared_paths(specs: list) -> dict:
    """{spec: declared module path} from the cached .mod of each `path@version`.
    One batched `go list` (field-limited, so no source zip is fetched); specs it
    cannot resolve are absent."""
    if not specs:
        return {}
    r = _run(["go", "list", "-m", "-e", "-json=Path,Version,GoMod,Error", *specs])
    out = {}
    for spec, gomod in parse_list_stream(r.stdout).items():
        try:
            declared = module_line(Path(gomod).read_text())
        except OSError:
            continue
        if declared:
            out[spec] = declared
    return out


def _versions(name: str) -> list:
    r = _run(["go", "list", "-m", "-versions", name])
    toks = r.stdout.split()
    return toks[1:] if r.returncode == 0 and toks[:1] == [name] else []


def detect_renames(recs: list) -> None:
    """Mark records whose latest version declares a different module path (meta.renamedTo)
    and the last version still under the old path (meta.lastVersionWithPath).
    Any lookup failure leaves the record unchanged."""
    todo = [r for r in recs if r.bump != c.BUMP_NONE]
    declared = _declared_paths([f"{r.name}@{r.latest}" for r in todo])
    for r in todo:
        new = declared.get(f"{r.name}@{r.latest}")
        if not new or new == r.name:
            continue
        cands = [
            v
            for v in _versions(r.name)
            if "-" not in v and parse_semver(r.current) < parse_semver(v) < parse_semver(r.latest)
        ]
        got = _declared_paths([f"{r.name}@{v}" for v in cands])
        r.meta["renamedTo"] = new
        r.meta["lastVersionWithPath"] = last_version_with_path(
            r.current, r.latest, cands, {v: got.get(f"{r.name}@{v}") for v in cands}, r.name
        )


_RENAMED = re.compile(r"module declares its path as:\s*(\S+)\s+but was required as:\s*(\S+)")


def parse_renamed(output: str) -> list:
    """[{"required": Y, "declared": X}] from go's `module declares its path as: X
    but was required as: Y` errors."""
    return [{"required": m.group(2), "declared": m.group(1)} for m in _RENAMED.finditer(output)]


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
        out = {"present": present, "ecosystem": "go", "packageManager": "", "workspace": (root / "go.work").exists()}
        if present:
            members = [os.path.relpath(m.parent, root).replace(os.sep, "/") for m in _workspace_gomods(root)]
            out["projects"] = proj.merge([{"dir": proj.ROOT, "members": [proj.ROOT, *members]}])
        return out
    if verb in ("apply", "validate"):
        project, argv = proj.split_project(argv)
        proj.require_root(project, "go")
    if verb == "cache-clear":
        return {"warnings": []}  # go refreshes via `go list`; no aggressive clean
    if verb == "outdated":
        out = _run(["go", "list", "-m", "-u", "all"])
        required = {}
        for gomod in _workspace_gomods(root):
            required.update(required_modules(gomod.read_text()))
        recs = parse_outdated(out.stdout, required)
        detect_renames(recs)
        return recs
    if verb == "audit":
        if shutil.which("govulncheck") is None:
            return []
        out = _run(["govulncheck", "-json", "./..."])
        return parse_vuln(out.stdout)
    if verb == "apply":
        steps = [["go", "get", spec] for spec in argv]  # spec e.g. "github.com/foo/bar@v1.2.3"
        steps.append(["go", "mod", "tidy"])
        if (root / "go.work").exists():
            steps.append(["go", "work", "sync"])
        for cmd in steps:
            r = _run(cmd)
            if r.returncode != 0:
                text = (r.stdout + r.stderr)[-4000:]
                res = {"applied": [], "filesModified": [], "error": f"{' '.join(cmd)}: " + text}
                if renamed := parse_renamed(text):
                    res["renamed"] = renamed
                return res
        return {"applied": argv, "filesModified": changed_files(["go.mod", "go.sum"], cwd=root)}
    if verb == "validate":
        results = {}
        for step, cmd in (("build", "go build ./..."), ("test", "go test ./..."), ("lint", "go vet ./...")):
            r = _run_shell(cmd)  # trusted config/default strings
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"go: unknown verb {verb}")
