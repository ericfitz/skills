"""Python ecosystem adapter (uv / pip)."""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .. import contracts as c
from .. import projects as proj
from ..categorize import classify_bump
from ..gitfiles import changed_files

try:
    import tomllib
except ImportError:  # Python 3.10: declared() falls back to scanning the text
    tomllib = None


def _uv_projects(root: Path) -> list:
    """One project per tracked uv.lock, root first. Without git the root lock alone."""
    try:
        r = _run(["git", "-C", str(root), "ls-files", "--", "*uv.lock"])
        listed = r.stdout.splitlines() if r.returncode == 0 else []
    except OSError:
        listed = []
    dirs = {proj.parent_of(f) for f in listed if f.rsplit("/", 1)[-1] == "uv.lock" and (root / f).exists()}
    if (root / "uv.lock").exists() or not dirs:
        dirs.add(proj.ROOT)
    return [{"dir": d, "members": [d]} for d in sorted(dirs, key=lambda d: (d != proj.ROOT, d))]


def detect(root: Path) -> dict:
    """Detect Python package manager: uv if available and uv.lock/pyproject.toml exist, else pip."""
    root = Path(root)
    has_uv = shutil.which("uv") is not None
    if has_uv and ((root / "uv.lock").exists() or (root / "pyproject.toml").exists()):
        return {"present": True, "ecosystem": "python", "packageManager": "uv", "projects": _uv_projects(root)}
    if (root / "requirements.txt").exists() or (root / "setup.py").exists() or (root / "pyproject.toml").exists():
        return {"present": True, "ecosystem": "python", "packageManager": "pip", "projects": proj.DEFAULT}
    return {"present": False, "ecosystem": "python"}


def parse_outdated(json_text: str) -> list:
    """Parse pip list --outdated --format json output."""
    data = json.loads(json_text or "[]")
    recs = []
    for info in data:
        name = info["name"]
        cur = info.get("version", "")
        lat = info.get("latest_version", "")
        recs.append(
            c.UpdateRecord(
                name=name,
                current=cur,
                latest=lat,
                wanted=lat,
                bump=classify_bump(cur, lat),
                kind="direct",
                location="pyproject.toml",
                ecosystem="python",
            )
        )
    return recs


_TREE_LINE = re.compile(r"^((?:\u2502   |    )*)(?:\u251c\u2500\u2500 |\u2514\u2500\u2500 )(\S+) v(\S+)(.*)$")
_LATEST = re.compile(r"\(latest: v?([^)\s]+)\)")


def parse_tree_outdated(text: str, location: str = "uv.lock") -> list:
    """Parse `uv tree --outdated --frozen --all-groups` into UpdateRecords.

    Depth 1 is a direct dependency, deeper is transitive. uv prints `(latest: ...)` only
    on a package's first appearance and marks later subtrees `(*)`, so the first line seen
    need not be the shallowest: the depth is the minimum over every appearance, the
    `latest` comes from whichever appearance carries it. The project itself (depth 0) and
    the `(*)` legend are not dependencies. Packages are keyed by name and version.
    """
    depth, latest = {}, {}
    for line in text.splitlines():
        m = _TREE_LINE.match(line)
        if not m:
            continue
        name = re.sub(r"\[.*\]$", "", m.group(2))  # `httpx[socks]` -> `httpx`
        key = (name, m.group(3))
        d = len(m.group(1)) // 4 + 1
        depth[key] = min(d, depth.get(key, d))
        lm = _LATEST.search(m.group(4))
        if lm:
            latest[key] = lm.group(1)
    return [
        c.UpdateRecord(
            name=n,
            current=v,
            latest=lat,
            wanted=lat,
            bump=classify_bump(v, lat),
            kind="direct" if depth[(n, v)] == 1 else "transitive",
            location=location,
            ecosystem="python",
        )
        for (n, v), lat in latest.items()
    ]


def parse_audit(json_text: str) -> list:
    """Parse pip-audit --format json output."""
    data = json.loads(json_text or "{}")
    advs = []
    for dep in data.get("dependencies", []):
        for v in dep.get("vulns", []):
            fixes = v.get("fix_versions", [])
            advs.append(
                c.Advisory(
                    package=dep.get("name", ""),
                    ecosystem="python",
                    severity="",
                    current=dep.get("version", ""),
                    fixed=fixes[0] if fixes else "",
                    ids=[v.get("id", "")],
                    summary=v.get("description", ""),
                    source="pip-audit",
                )
            )
    return advs


def _audit_uv(root: Path, project: str = proj.ROOT) -> list:
    """Audit one project's LOCKFILE rather than the installed environment.

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
        # Every extra and group: a package reached only through an optional extra is
        # still pinned in uv.lock and still ships to whoever installs that extra.
        exported = _run(
            [
                "uv",
                "export",
                "--frozen",
                "--project",
                str(root / project),
                "--all-extras",
                "--all-groups",
                "--format",
                "pylock.toml",
                "-o",
                str(pylock),
            ]
        )
        if exported.returncode != 0:
            return []  # no lockfile, or stale under --frozen: report nothing found
        out = _run(
            [
                "uv",
                "tool",
                "run",
                "pip-audit",
                "--locked",
                str(pylock.parent),
                "--format",
                "json",
                "--progress-spinner",
                "off",
            ]
        )
        advs = _parse_audit_lenient(out.stdout)
        for a in advs:
            a.location = proj.join(project, "uv.lock")
        return advs


def _outdated_uv(root: Path, project: str) -> list:
    """Outdated packages of one project, read from its lockfile, not any environment.

    `uv tree --outdated --frozen` answers from uv.lock plus the index, so it needs no venv
    for the project, cannot be fooled by the PEP 723 ephemeral environment `uv run bump.py`
    runs in (#28) or by a venv that drifted from the lock (#37), and shows how deep each
    package sits (#57). The text format is parsed because `--format json` is still marked
    experimental by uv 0.13. A failure warns and yields nothing for this project only.
    """
    r = _run(["uv", "tree", "--outdated", "--frozen", "--all-groups", "--project", str(root / project)])
    if r.returncode != 0:
        print(
            f"warning: `uv tree --outdated` failed in {project}; no records for it: "
            f"{(r.stderr or r.stdout).strip()[-300:]}",
            file=sys.stderr,
        )
        return []
    return parse_tree_outdated(r.stdout, proj.join(project, "uv.lock"))


def _parse_audit_lenient(text: str) -> list:
    """pip-audit exits non-zero when it finds something, so returncode says nothing about
    whether stdout is JSON. Offline or missing, it prints a banner instead -- degrade to
    'nothing found' the way every other optional-tool path here does."""
    try:
        return parse_audit(text)
    except ValueError:
        return []


def _run(args, env=None, cwd=None):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True, env=env, cwd=cwd)


def _run_shell(cmd, cwd=None):
    """ONLY for trusted config/default strings (no per-run data interpolated)."""
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=cwd)


def _requirement_names(data: dict):
    """Normalized package name of every requirement a pyproject declares: dependencies,
    extras, dependency groups and the legacy uv dev-dependencies."""
    reqs = list(data.get("project", {}).get("dependencies", []))
    for extra in data.get("project", {}).get("optional-dependencies", {}).values():
        reqs += extra
    for group in data.get("dependency-groups", {}).values():
        reqs += [r for r in group if isinstance(r, str)]  # skip {include-group = ...}
    reqs += data.get("tool", {}).get("uv", {}).get("dev-dependencies", [])
    for r in reqs:
        m = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", r)
        if m:
            yield re.sub(r"[-_.]+", "-", m.group(1)).lower()


def declared(pyproject: Path, tool: str) -> bool:
    """Does this pyproject name `tool`: as a requirement anywhere, or a [tool.<tool>] table?"""
    try:
        text = pyproject.read_text()
    except OSError:
        return False
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            return False
        return tool in data.get("tool", {}) or tool in set(_requirement_names(data))
    return bool(
        re.search(rf"(?m)^\s*\[tool\.{tool}[.\]]", text)
        or re.search(rf"(?m)^[^#\n]*[\"']{tool}\s*[\[<>=!~;@\"' ]", text)
    )


def _known_project(root: Path, project: str, mgr: str) -> None:
    """Reject a --project that is not one this adapter reports from `detect`."""
    known = [p["dir"] for p in (detect(root).get("projects") or proj.DEFAULT)]
    if mgr != "uv":
        known = [proj.ROOT]
    if project not in known:
        raise ValueError(f"python: unknown project {project!r}; known: {', '.join(known)}")


def handle(verb, argv):
    """Handle bump operations for Python ecosystem."""
    root = Path(".")
    det = detect(root)
    mgr = det.get("packageManager", "pip")
    if verb == "detect":
        return det
    if verb == "cache-clear":
        _run(["uv", "cache", "clean"] if mgr == "uv" else ["pip", "cache", "purge"])
        return {"warnings": []}
    if verb == "outdated":
        if mgr == "uv":
            return [r for p in det["projects"] for r in _outdated_uv(root, p["dir"])]
        out = _run(["pip", "list", "--outdated", "--format", "json"])
        return parse_outdated(out.stdout)
    if verb == "audit":
        probe = "uv" if mgr == "uv" else "pip-audit"
        if shutil.which(probe) is None:
            return []
        if mgr == "uv":
            return [a for p in det["projects"] for a in _audit_uv(root, p["dir"])]
        out = _run(["pip-audit", "--format", "json"])
        return parse_audit(out.stdout)
    if verb in ("apply", "validate"):
        project, argv = proj.split_project(argv)
        _known_project(root, project, mgr)
    if verb == "apply":
        where = str(root / project)
        if mgr == "uv":
            flags = []
            for a in argv:  # a e.g. "requests==2.31.0"
                flags += ["--upgrade-package", a.split("==")[0]]
            steps = [["uv", "lock", "--project", where, *flags], ["uv", "sync", "--project", where]]
            candidates = [proj.join(project, "pyproject.toml"), proj.join(project, "uv.lock")]
        else:
            steps = [["pip", "install", *argv]]
            candidates = ["requirements.txt"]
        for cmd in steps:
            r = _run(cmd)
            if r.returncode != 0:
                return {
                    "applied": [],
                    "filesModified": [],
                    "error": f"{' '.join(cmd)}: " + (r.stdout + r.stderr)[-4000:],
                }
        modified = changed_files(candidates, cwd=root)
        # For uv the lockfile is the evidence: `uv lock --upgrade-package X` is a no-op
        # when uv.lock already holds the target, and echoing the spec back as applied
        # would let a commit message claim a bump that never happened (#37). pip never
        # edits requirements.txt, so an empty diff carries no signal there.
        applied = [] if mgr == "uv" and not modified else argv
        return {"applied": applied, "filesModified": modified}
    if verb == "validate":
        results = {}
        cwd = root / project
        for step, tool, cmd in (
            ("test", "pytest", "uv run pytest" if mgr == "uv" else "pytest"),
            ("lint", "ruff", "uv run ruff check ." if mgr == "uv" else "ruff check ."),
        ):
            if mgr == "uv" and not declared(cwd / "pyproject.toml", tool):
                results[step] = "skipped"
                results[step + "_output"] = f"no {tool} declared in {proj.join(project, 'pyproject.toml')}"
                continue
            r = _run_shell(cmd, cwd=cwd)  # trusted default/config strings
            results[step] = "pass" if r.returncode == 0 else "fail"
            results[step + "_output"] = (r.stdout + r.stderr)[-4000:]
        return results
    raise ValueError(f"python: unknown verb {verb}")
