"""Node ecosystem adapter (pnpm / npm)."""
import json
import re
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump
from ..gitfiles import changed_files

# Directories that never hold a workspace manifest. node_modules is the one that
# matters -- without it the manifest walk would read every vendored package.json.
_SKIP_DIRS = {"node_modules", "dist", "build", "out", "coverage",
              "venv", "__pycache__", "vendor", "tmp"}

_DEP_FIELDS = (("dependencies", "prod"), ("devDependencies", "dev"),
               ("optionalDependencies", "optional"), ("peerDependencies", "peer"))


def detect(root: Path) -> dict:
    root = Path(root)
    if not (root / "package.json").exists():
        return {"present": False, "ecosystem": "node"}
    mgr = "pnpm" if (root / "pnpm-lock.yaml").exists() else "npm"
    return {"present": True, "ecosystem": "node", "packageManager": mgr}


def _manifests(root: Path, max_depth: int = 4):
    """Yield each non-vendored package.json under root, root's own first.

    A bounded walk rather than expanding the `workspaces` globs or pnpm-workspace.yaml:
    one code path serves both managers, it needs no YAML parser (bumplib is stdlib-only),
    and it copes with layouts those manifests do not describe.
    """
    root = Path(root)
    if (root / "package.json").exists():
        yield root / "package.json"
    stack = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        if depth >= max_depth:
            continue
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.name in _SKIP_DIRS or e.name.startswith("."):
                continue
            if not e.is_dir() or e.is_symlink():
                continue
            if (e / "package.json").exists():
                yield e / "package.json"
            stack.append((e, depth + 1))


def dep_index(root: Path) -> dict:
    """Map every DECLARED dependency name to where and how it is declared.

    Values carry `location` (manifest path relative to root), `type` (prod/dev/optional/
    peer), `range` (the declared specifier), and the workspace's directory and package
    name. A name absent from this map is transitive. First declaration wins, and the root
    manifest is visited first, so a root-level pin outranks a workspace one.
    """
    root = Path(root)
    index = {}
    for man in _manifests(root):
        try:
            pj = json.loads(man.read_text())
        except (OSError, ValueError):
            continue          # an unreadable manifest must not sink the whole run
        if not isinstance(pj, dict):
            continue
        rel_dir = man.parent.relative_to(root).as_posix()
        is_root = rel_dir == "."
        for field, dtype in _DEP_FIELDS:
            for name, rng in (pj.get(field) or {}).items():
                if name in index:
                    continue
                index[name] = {
                    "location": man.relative_to(root).as_posix(),
                    "type": dtype,
                    "range": rng if isinstance(rng, str) else "",
                    "workspaceDir": "" if is_root else rel_dir,
                    "workspaceName": "" if is_root else str(pj.get("name") or ""),
                }
    return index


def parse_outdated(json_text: str, manager: str, declared: dict | None = None) -> list:
    """Build UpdateRecords from `npm outdated --json` / `pnpm outdated --format json`.

    npm maps a name to EITHER a single entry OR a LIST of entries -- one per dependent,
    which is routine in a workspaces monorepo. Both shapes are normalized here; assuming
    the dict shape is what used to raise AttributeError.

    `declared` is a dep_index() map. With it, a package missing from the index is reported
    as transitive and a declared one gets its real manifest path. Without it every record
    keeps the old direct/package.json assumption, so pure parse tests stay meaningful.
    """
    data = json.loads(json_text or "{}")
    recs, seen = [], set()
    for name, info in data.items():
        for entry in (info if isinstance(info, list) else [info]):
            if not isinstance(entry, dict):
                continue
            cur = entry.get("current", "") or ""
            lat = entry.get("latest", "") or ""
            wanted = entry.get("wanted", lat) or lat
            key = (name, cur, lat)
            if key in seen:
                continue          # several dependents agreeing is still one update
            seen.add(key)
            decl = (declared or {}).get(name)
            recs.append(c.UpdateRecord(
                name=name, current=cur, latest=lat, wanted=wanted,
                bump=classify_bump(cur, lat),
                kind="direct" if (decl or declared is None) else "transitive",
                location=(decl or {}).get("location") or "package.json",
                ecosystem="node",
                meta={"dependencyType": entry.get("dependencyType", "") or (decl or {}).get("type", ""),
                      "declaredRange": (decl or {}).get("range", ""),
                      "dependent": entry.get("dependent", "")}))
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


def split_spec(spec: str) -> tuple:
    """'eslint@9.1.0' -> ('eslint', '9.1.0'); '@angular/core@20.0.0' -> ('@angular/core',
    '20.0.0'). A bare name yields an empty version."""
    scoped = spec.startswith("@")
    name, sep, version = (spec[1:] if scoped else spec).partition("@")
    return ("@" if scoped else "") + name, version if sep else ""


def _pkg_name(spec: str) -> str:
    """Strip the version from a spec, preserving a leading scope '@'."""
    return split_spec(spec)[0]


_VER_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)")


def _version(v: str):
    m = _VER_RE.match(v or "")
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def _bounds(rng: str):
    """[lower, upper) for the caret/tilde/exact forms manifests overwhelmingly use.

    None for anything else -- unions, comparator sets, wildcards, dist-tags, urls, and the
    workspace:/file:/npm: protocols. Callers treat None as 'cannot prove', which keeps an
    unrecognized range on the conservative path instead of guessing at its meaning.
    """
    r = (rng or "").strip()
    if not r or r[0] in "^~":
        op, r = (r[:1], r[1:].strip()) if r else ("", "")
    else:
        op = ""
    if not r or any(ch in r for ch in " |<>=,-+"):
        return None
    lo = _version(r)
    if lo is None or _VER_RE.match(r).end() != len(r):   # 1.x, 1.2.3-beta.1, ...
        return None
    major, minor, patch = lo
    if op == "^":
        # ^0.x and ^0.0.x only widen within the leading non-zero, per npm's caret rules.
        hi = (major + 1, 0, 0) if major else (0, minor + 1, 0) if minor else (0, 0, patch + 1)
    elif op == "~":
        hi = (major, minor + 1, 0)
    else:
        hi = (major, minor, patch + 1)          # exact pin
    return lo, hi


def satisfies(version: str, rng: str):
    """True/False when the range form is understood, None when it is not."""
    bounds, ver = _bounds(rng), _version(version)
    if bounds is None or ver is None:
        return None
    return bounds[0] <= ver < bounds[1]


def _widen(rng: str, version: str) -> str:
    """Preserve the declared operator while moving it up: '^0.184.0' + '0.185.1' -> '^0.185.1'."""
    op = rng[0] if rng[:1] in ("^", "~") else ""
    return f"{op}{version}"


def _install_cmd(mgr: str, name: str, version: str, decl: dict, root: Path) -> list:
    """Command that moves a declared dependency PAST its current range, rewriting the manifest.

    npm targets a workspace by directory (`-w <dir>`); pnpm targets one by package name
    (`--filter <name>`) because pnpm's own `-w` means 'the workspace root', not 'a workspace'.
    An empty workspaceName only means 'root manifest' -- whether that root IS a workspace
    root is decided by pnpm-workspace.yaml (pnpm ignores package.json's `workspaces`), and
    `-w` outside a workspace is an error, not a no-op.
    """
    spec = f"{name}@{_widen(decl.get('range', ''), version)}"
    flag = {"dev": "-D", "optional": "-O", "peer": "--save-peer"}.get(decl.get("type", ""))
    if mgr == "pnpm":
        cmd = ["pnpm", "add"]
        if decl.get("workspaceName"):
            cmd += ["--filter", decl["workspaceName"]]
        elif (root / "pnpm-workspace.yaml").exists():
            cmd += ["-w"]
    else:
        cmd = ["npm", "install"]
        if decl.get("workspaceDir"):
            cmd += ["-w", decl["workspaceDir"]]
    return cmd + ([flag] if flag else []) + [spec]


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
        return parse_outdated(out.stdout, mgr, dep_index(root))
    if verb == "audit":
        if shutil.which(mgr) is None:
            return []
        out = _run(["pnpm", "audit", "--json"] if mgr == "pnpm" else ["npm", "audit", "--json"])
        return parse_audit(out.stdout, mgr)
    if verb == "apply":
        declared = dep_index(root)
        lock = "pnpm-lock.yaml" if mgr == "pnpm" else "package-lock.json"
        modified, update_names = {lock}, []

        def _checked(cmd):
            r = _run(cmd)
            if r.returncode != 0:
                return {"applied": [], "filesModified": [],
                        "error": f"{' '.join(cmd)}: " + (r.stdout + r.stderr)[-4000:]}
            return None

        for spec in argv:
            name, version = split_spec(spec)
            decl = declared.get(name)
            if decl:
                modified.add(decl["location"])
            # Rewrite a manifest only for a declared dependency whose target is PROVABLY
            # outside its range -- `update` alone can never cross that boundary, which is
            # why an out-of-range spec used to be silently dropped. Bare names, transitive
            # packages and unrecognized range forms all stay on `update`, which touches
            # only the lockfile.
            if version and decl and satisfies(version, decl.get("range", "")) is False:
                err = _checked(_install_cmd(mgr, name, version, decl, root))
                if err:
                    return err
            else:
                update_names.append(name)
        if update_names:
            err = _checked([mgr, "update", *update_names])
            if err:
                return err
        err = _checked([mgr, "install"])
        if err:
            return err
        return {"applied": list(argv), "filesModified": changed_files(sorted(modified), cwd=root)}
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
