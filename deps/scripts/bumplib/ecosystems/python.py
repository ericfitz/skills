"""Python ecosystem adapter (uv / pip)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump
from ..gitfiles import changed_files


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


def _project_python(root: Path):
    """Absolute path to the project virtualenv's interpreter, or None if there isn't one.

    bump.py declares PEP 723 inline metadata, so `uv run bump.py` runs it in an isolated
    ephemeral environment and exports that environment in VIRTUAL_ENV. Anything asking uv
    "what is installed?" then answers for the ephemeral env -- which holds nothing -- so
    every uv project looked fully up to date. Naming the interpreter explicitly is what
    pins the question back to the project; it also wins over an inherited VIRTUAL_ENV.

    UV_PROJECT_ENVIRONMENT is uv's documented override for projects whose environment is
    not `.venv`. A relative value resolves against the project root, as uv resolves it.
    """
    env_dir = os.environ.get("UV_PROJECT_ENVIRONMENT") or ".venv"
    base = Path(env_dir)
    if not base.is_absolute():
        base = Path(root) / env_dir
    for rel in ("bin/python", "Scripts/python.exe"):
        exe = base / rel
        if exe.exists():
            return exe
    return None


def _audit_uv(root: Path) -> list:
    """Audit the LOCKFILE rather than the installed environment.

    pip-audit's default source asks pip to enumerate installed distributions, and in a
    uv-created venv pip enumerates nothing: measured in this repo, `pip list` returned []
    where 33 dist-info directories sat on disk and importlib.metadata found all 33. Having
    scanned an empty set, pip-audit reports "No known vulnerabilities found" and exits 0 --
    a security check whose silent pass is indistinguishable from a real one.

    Exporting uv.lock to PEP 751 pylock.toml and auditing that file takes pip out of the
    path entirely; against this repo's pre-fix lock it scanned 58 packages and caught the
    nltk advisories the environment mode missed. The export goes to a temp directory and
    is discarded: uv has no notion of pylock.toml as an input -- given one in place of
    uv.lock it silently re-resolves from pyproject.toml -- so a copy left in the project
    could be mistaken for a lockfile while pinning nothing.
    """
    with tempfile.TemporaryDirectory() as tmp:
        pylock = Path(tmp) / "pylock.toml"
        exported = _run(["uv", "export", "--frozen", "--project", str(root),
                         "--format", "pylock.toml", "-o", str(pylock)])
        if exported.returncode != 0:
            return []       # no lockfile, or stale under --frozen: report nothing found
        out = _run(["uv", "tool", "run", "pip-audit", "--locked", str(pylock.parent),
                    "--format", "json", "--progress-spinner", "off"])
        return _parse_audit_lenient(out.stdout)


def _parse_audit_lenient(text: str) -> list:
    """pip-audit exits non-zero when it finds something, so returncode says nothing about
    whether stdout is JSON. Offline or missing, it prints a banner instead -- degrade to
    'nothing found' the way every other optional-tool path here does."""
    try:
        return parse_audit(text)
    except ValueError:
        return []


def _run(args, env=None):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True, env=env)


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
        if mgr == "uv":
            venv = _project_python(root)
            # Fresh clone / rm -rf .venv: there is a lockfile to honor but no
            # environment to inspect. Create it -- `uv sync` runs later in the
            # flow anyway -- rather than silently querying the ephemeral env (#28).
            if venv is None and (root / "uv.lock").exists() and _run(["uv", "sync"]).returncode == 0:
                venv = _project_python(root)
            cmd = ["uv", "pip", "list", "--outdated", "--format", "json"]
            env = None
            if venv:
                cmd += ["--python", str(venv)]
            else:
                # Without an explicit interpreter uv answers for VIRTUAL_ENV, which under
                # `uv run bump.py` is the empty PEP 723 ephemeral env -- strip it so
                # discovery can never resolve there, and say so.
                print("warning: no project environment found; outdated results may be "
                      "incomplete (run `uv sync`)", file=sys.stderr)
                env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
            out = _run(cmd, env=env)
        else:
            out = _run(["pip", "list", "--outdated", "--format", "json"])
        return parse_outdated(out.stdout)
    if verb == "audit":
        probe = "uv" if mgr == "uv" else "pip-audit"
        if shutil.which(probe) is None:
            return []
        if mgr == "uv":
            return _audit_uv(root)
        out = _run(["pip-audit", "--format", "json"])
        return parse_audit(out.stdout)
    if verb == "apply":
        if mgr == "uv":
            flags = []
            for a in argv:              # a e.g. "requests==2.31.0"
                flags += ["--upgrade-package", a.split("==")[0]]
            steps = [["uv", "lock", *flags], ["uv", "sync"]]
            candidates = ["pyproject.toml", "uv.lock"]
        else:
            steps = [["pip", "install", *argv]]
            candidates = ["requirements.txt"]
        for cmd in steps:
            r = _run(cmd)
            if r.returncode != 0:
                return {"applied": [], "filesModified": [],
                        "error": f"{' '.join(cmd)}: " + (r.stdout + r.stderr)[-4000:]}
        return {"applied": argv, "filesModified": changed_files(candidates, cwd=root)}
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
