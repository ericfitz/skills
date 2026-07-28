"""Python ecosystem adapter (uv / pip)."""
import json
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump


def detect(root: Path) -> dict:
    """Detect Python package manager: uv if available and uv.lock/pyproject.toml exist, else pip."""
    root = Path(root)
    has_uv = shutil.which("uv") is not None
    if has_uv and ((root / "uv.lock").exists() or (root / "pyproject.toml").exists()):
        return {"present": True, "ecosystem": "python", "packageManager": "uv"}
    if (root / "requirements.txt").exists() or (root / "setup.py").exists():
        return {"present": True, "ecosystem": "python", "packageManager": "pip"}
    if (root / "pyproject.toml").exists():
        return {"present": True, "ecosystem": "python", "packageManager": "pip"}
    return {"present": False, "ecosystem": "python"}


def parse_outdated(json_text: str) -> list:
    """Parse pip list --outdated --format json output."""
    data = json.loads(json_text or "[]")
    recs = []
    for info in data:
        name = info["name"]
        cur = info.get("version", "")
        lat = info.get("latest_version", "")
        recs.append(c.UpdateRecord(name=name, current=cur, latest=lat, wanted=lat,
                                   bump=classify_bump(cur, lat), kind="direct",
                                   location="pyproject.toml", ecosystem="python"))
    return recs


def parse_audit(json_text: str) -> list:
    """Parse pip-audit --format json output."""
    data = json.loads(json_text or "{}")
    advs = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            fixes = v.get("fix_versions", [])
            advs.append(c.Advisory(package=dep.get("name", ""), ecosystem="python",
                                   severity="", current=dep.get("version", ""),
                                   fixed=fixes[0] if fixes else "", ids=[v.get("id", "")],
                                   summary=v.get("description", ""), source="pip-audit"))
    return advs


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def _run_shell(cmd):
    """ONLY for trusted config/default strings (no per-run data interpolated)."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def handle(verb, argv):
    """Handle bump operations for Python ecosystem."""
    root = Path(".")
    mgr = detect(root).get("packageManager", "pip")
    if verb == "detect":
        return detect(root)
    if verb == "cache-clear":
        _run(["uv", "cache", "clean"] if mgr == "uv" else ["pip", "cache", "purge"])
        return {"warnings": []}
    if verb == "outdated":
        cmd = (["uv", "pip", "list", "--outdated", "--format", "json"] if mgr == "uv"
               else ["pip", "list", "--outdated", "--format", "json"])
        out = _run(cmd)
        return parse_outdated(out.stdout)
    if verb == "audit":
        probe = "uv" if mgr == "uv" else "pip-audit"
        if shutil.which(probe) is None:
            return []
        out = _run(["uv", "run", "pip-audit", "--format", "json"] if mgr == "uv"
                   else ["pip-audit", "--format", "json"])
        return parse_audit(out.stdout)
    if verb == "apply":
        if mgr == "uv":
            flags = []
            for a in argv:              # a e.g. "requests==2.31.0"
                flags += ["--upgrade-package", a.split("==")[0]]
            _run(["uv", "lock", *flags])
            _run(["uv", "sync"])
        else:
            _run(["pip", "install", *argv])
        modified = ["pyproject.toml", "uv.lock"] if mgr == "uv" else ["requirements.txt"]
        return {"applied": argv, "filesModified": modified}
    if verb == "validate":
        results = {}
        cmds = (("test", "uv run pytest" if mgr == "uv" else "pytest"),
                ("lint", "uv run ruff check ." if mgr == "uv" else "ruff check ."))
        for step, cmd in cmds:
            r = _run_shell(cmd)          # trusted default/config strings
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"python: unknown verb {verb}")
