"""Node ecosystem adapter (pnpm / npm)."""
import json
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump


def detect(root: Path) -> dict:
    root = Path(root)
    if not (root / "package.json").exists():
        return {"present": False, "ecosystem": "node"}
    mgr = "pnpm" if (root / "pnpm-lock.yaml").exists() else ("npm" if (root / "package-lock.json").exists() else "npm")
    return {"present": True, "ecosystem": "node", "packageManager": mgr}


def parse_outdated(json_text: str, manager: str) -> list:
    data = json.loads(json_text or "{}")
    recs = []
    for name, info in data.items():
        cur = info.get("current", "")
        lat = info.get("latest", "")
        wanted = info.get("wanted", lat)
        kind = "direct"
        recs.append(c.UpdateRecord(name=name, current=cur, latest=lat, wanted=wanted,
                                   bump=classify_bump(cur, lat), kind=kind,
                                   location="package.json", ecosystem="node",
                                   meta={"dependencyType": info.get("dependencyType", "")}))
    return recs


def parse_audit(json_text: str, manager: str) -> list:
    data = json.loads(json_text or "{}")
    advs = []
    if isinstance(data.get("advisories"), dict):   # pnpm / npm-v6 bulk shape
        for adv in data["advisories"].values():
            if not isinstance(adv, dict) or "severity" not in adv:
                continue
            patched = adv.get("patched_versions", "") or ""
            fixed = patched.lstrip("><= ").strip() if patched and patched != "<0.0.0" else ""
            findings = adv.get("findings") or []
            current = findings[0].get("version", "") if findings and isinstance(findings[0], dict) else ""
            advs.append(c.Advisory(package=adv.get("module_name", ""), ecosystem="node",
                                   severity=str(adv.get("severity", "")).upper(),
                                   current=current, fixed=fixed,
                                   ids=list(adv.get("cves") or []),
                                   summary=adv.get("vulnerable_versions", ""), source="audit"))
        return advs
    # npm v7+ shape
    vulns = data.get("vulnerabilities", {})
    for name, v in vulns.items():
        if not isinstance(v, dict) or "severity" not in v:
            continue
        fix = v.get("fixAvailable")
        fixed = fix.get("version", "") if isinstance(fix, dict) else ""
        ids = []
        for via in v.get("via", []):
            if isinstance(via, dict) and via.get("url"):
                ids.append(via["url"])
        advs.append(c.Advisory(package=name, ecosystem="node",
                               severity=v.get("severity", "").upper(),
                               current="", fixed=fixed, ids=ids,
                               summary=v.get("range", ""), source="audit"))
    return advs


def _pkg_name(spec: str) -> str:
    """Strip the version from a spec, preserving a leading scope '@'. 'eslint@9.1' -> 'eslint',
    '@angular/core@20' -> '@angular/core'."""
    if spec.startswith("@"):
        return "@" + spec[1:].split("@")[0]
    return spec.split("@")[0]


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def _run_shell(cmd):
    """ONLY for trusted config/default strings that need shell operators (e.g. 'a || b')."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def handle(verb, argv):
    root = Path(".")
    mgr = detect(root).get("packageManager", "npm")
    if verb == "detect":
        return detect(root)
    if verb == "cache-clear":
        # registry metadata can be stale in either cache -- always clear both, each
        # guarded so a missing binary is skipped rather than fatal.
        if shutil.which("pnpm"):
            _run(["pnpm", "store", "prune"])
        if shutil.which("npm"):
            _run(["npm", "cache", "clean", "--force"])
        return {"warnings": []}
    if verb == "outdated":
        if shutil.which(mgr) is None:
            return []
        cmd = ["pnpm", "outdated", "--format", "json"] if mgr == "pnpm" else ["npm", "outdated", "--json"]
        out = _run(cmd)
        return parse_outdated(out.stdout, mgr)
    if verb == "audit":
        if shutil.which(mgr) is None:
            return []
        out = _run(["pnpm", "audit", "--json"] if mgr == "pnpm" else ["npm", "audit", "--json"])
        return parse_audit(out.stdout, mgr)
    if verb == "apply":
        names = [_pkg_name(a) for a in argv]
        _run([mgr, "update", *names])
        _run([mgr, "install"])
        lock = "pnpm-lock.yaml" if mgr == "pnpm" else "package-lock.json"
        return {"applied": argv, "filesModified": ["package.json", lock]}
    if verb == "validate":
        results = {}
        cmds = (("build", f"{mgr} run build"), ("test", f"{mgr} test"),
                ("lint", f"{mgr} run lint:all || {mgr} run lint"))
        for step, cmd in cmds:
            r = _run_shell(cmd)          # trusted: mgr is 'pnpm'|'npm', not user data
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"node: unknown verb {verb}")
