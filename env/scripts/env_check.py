#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""env_check.py: read-only environment checker for skills marketplace plugins.

Discovers each plugin's sidecar `requirements.json` (see
`env/references/requirements.schema.json`), probes for what it declares, and
reports what is missing, why it matters, and how to fix it. Strictly
read-only: no install path lives here (that is the skill layer's `--fix`).
See docs/superpowers/specs/2026-07-26-env-check-design.md for the full design.

Usage:
    env_check.py [check] [--plugin NAME] [--root PATH] [--json]
    env_check.py probe <plugin> <name> [--root PATH]

Exit codes:
    0  all hard requirements met
    1  at least one hard requirement missing (or a probed item failed)
    2  usage or discovery error
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from pathlib import Path


class DiscoveryError(Exception):
    """Raised when the checker cannot find or read its own declaration."""


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _first_line(text: str, limit: int = 200) -> str:
    """First non-empty, trimmed line of `text`. Used to turn multi-line probe
    output (which may include token-like content on later lines) into a
    single safe-to-print summary."""
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:limit]
    return ""


_PLATFORM_KEYS = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}


def _install_hint(install: dict | None) -> str:
    """Resolve the `remedy` string shown in a report for an `install` object.

    This is display guidance for a human reading the report, not a command
    the checker runs -- `env_check.py` is read-only. It picks the key for the
    detected host platform (`platform.system()`: Darwin -> macos, Linux ->
    linux, Windows -> windows) and falls through to `docs` when the host has
    no key of its own, or when `install` has no `docs` either, `""`.

    The skill layer's `--fix` does its own platform detection and reads the
    same `install` object directly (see env/skills/check/SKILL.md Step 3) --
    it never runs the string this function returns."""
    if not install:
        return ""
    key = _PLATFORM_KEYS.get(platform.system())
    if key and install.get(key):
        return install[key]
    return install.get("docs", "")


def _finding(plugin: str, section: str, name: str, why: str, remedy: str, detail: str) -> dict:
    return {"plugin": plugin, "section": section, "name": name,
            "why": why, "remedy": remedy, "detail": detail}


def _broken_finding(plugin: str, path: Path, exc: Exception) -> dict:
    """A distinct finding for a sibling requirements.json that exists but
    fails to parse -- never a crash, never misfiled as merely 'undeclared'."""
    return _finding(
        plugin, "declaration", "requirements.json",
        "env_check.py must be able to parse this file to check the plugin",
        "fix the plugin's requirements.json (or reinstall this version of the plugin)",
        f"failed to parse {path}: {exc}")


# ---------------------------------------------------------------------------
# version comparison
# ---------------------------------------------------------------------------

def _parse_version(s: str) -> tuple[int, ...] | None:
    """Parse a dot-separated run of integers, e.g. '2.41.1' -> (2, 41, 1).
    Anything else (missing, non-numeric segments) is unparseable -> None."""
    s = s.strip()
    if not s:
        return None
    parts = s.split(".")
    nums: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        nums.append(int(part))
    return tuple(nums)


def _version_key(s: str) -> tuple[int, ...]:
    """Sort key for a version-looking directory name; unparseable sorts lowest
    so a genuinely-versioned sibling always wins the "highest version" pick."""
    parsed = _parse_version(s)
    return parsed if parsed is not None else (-1,)


def compare_versions(found: str, minimum: str) -> bool | None:
    """True if `found` >= `minimum`, False if lower, None if either string is
    unparseable -- an unparseable version is unknown, not a failure."""
    f = _parse_version(found)
    m = _parse_version(minimum)
    if f is None or m is None:
        return None
    length = max(len(f), len(m))
    f_padded = f + (0,) * (length - len(f))
    m_padded = m + (0,) * (length - len(m))
    return f_padded >= m_padded


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

def _self_dir(root: Path | None) -> Path:
    """The env plugin's own directory: either <repo>/env (source layout) or
    .../cache/<marketplace>/env/<version> (installed layout). Defaults to this
    script's own location; --root overrides it for tests and standalone use."""
    return root if root is not None else Path(__file__).resolve().parents[1]


def _layout_info(self_dir: Path) -> tuple[str, str, Path]:
    """Detect flat-vs-cache layout from self_dir's own declaration.

    If self_dir is literally named after the plugin ("env"), this is the flat
    source layout and siblings live at self_dir.parent/*/requirements.json.
    Otherwise self_dir's name is presumed to be a version directory (the
    installed-cache layout, CLAUDE_PLUGIN_ROOT = .../env/<version>/) and
    siblings live two levels up, at */*/requirements.json.

    Returns (layout, plugin_name, glob_root).
    """
    self_declaration = self_dir / "requirements.json"
    if not self_declaration.is_file():
        raise DiscoveryError(f"self declaration not found: {self_declaration}")
    try:
        self_data = _load_json(self_declaration)
    except (OSError, json.JSONDecodeError) as exc:
        raise DiscoveryError(f"failed to read {self_declaration}: {exc}") from exc

    plugin_name = self_data.get("plugin")
    if not plugin_name:
        raise DiscoveryError(f"{self_declaration} is missing a 'plugin' field")

    if self_dir.name == plugin_name:
        return "flat", plugin_name, self_dir.parent
    return "cache", plugin_name, self_dir.parent.parent


def _discover_all(
    root: Path | None,
) -> tuple[dict[str, tuple[str | None, Path]], list[dict], str, str, Path, Path]:
    """Single filesystem pass shared by discover(), _discover_broken(), and
    discover_undeclared(), so all three agree on layout and on which sibling
    requirements.json files actually parse.

    Both layouts key by directory name, never by the declaration's own
    `plugin` field -- the schema already pins plugin == dirname for every
    committed declaration (see tests/test_env_declarations.py), and keying by
    directory name means a declaration that disagrees with its own directory
    can't silently show up as both declared (under the field's name) and
    undeclared (under the dirname).

    Returns (found, broken, layout, plugin_name, self_dir, glob_root). `found`
    holds every sibling requirements.json that parses as JSON; `broken` holds
    a 'broken declaration' finding (see _broken_finding) for every sibling
    that exists but doesn't parse -- kept separate so a corrupt file
    elsewhere in the cache can never crash the checker (a broken declaration
    is exactly what this tool exists to diagnose) and never gets misfiled as
    merely "undeclared" (see discover_undeclared).
    """
    self_dir = _self_dir(root)
    layout, plugin_name, glob_root = _layout_info(self_dir)

    found: dict[str, tuple[str | None, Path]] = {}
    broken: list[dict] = []

    if layout == "flat":
        for path in sorted(glob_root.glob("*/requirements.json")):
            name = path.parent.name
            try:
                _load_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                broken.append(_broken_finding(name, path, exc))
                continue
            found[name] = (None, path)
    else:
        by_plugin: dict[str, list[tuple[tuple[int, ...], str, Path]]] = {}
        for path in sorted(glob_root.glob("*/*/requirements.json")):
            version_str = path.parent.name
            plugin_dir_name = path.parent.parent.name
            try:
                _load_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                broken.append(_broken_finding(plugin_dir_name, path, exc))
                continue
            by_plugin.setdefault(plugin_dir_name, []).append(
                (_version_key(version_str), version_str, path))
        for name, versions in by_plugin.items():
            versions.sort(key=lambda t: t[0])
            best_version, best_path = versions[-1][1], versions[-1][2]
            found[name] = (best_version, best_path)

    return found, broken, layout, plugin_name, self_dir, glob_root


def discover(root: Path | None = None) -> dict[str, tuple[str | None, Path]]:
    """Find every discoverable plugin's requirements.json.

    Returns {plugin_name: (version_or_None, path_to_requirements_json)}.
    version is only meaningful in the cache layout (the version directory
    name); the flat layout has no version concept, so it is always None.
    A sibling whose requirements.json exists but fails to parse is excluded
    here -- see _discover_broken -- rather than crashing or being counted as
    present-and-valid.

    If discovery finds no siblings -- standalone install, or an unrecognized
    layout -- this degrades to reporting on self only, honestly, rather than
    guessing.
    """
    found, _broken, layout, plugin_name, self_dir, _glob_root = _discover_all(root)
    if len(found) <= 1:
        version = self_dir.name if layout == "cache" else None
        return {plugin_name: (version, self_dir / "requirements.json")}
    return found


def _discover_broken(root: Path | None = None) -> list[dict]:
    """'Broken declaration' findings for siblings whose requirements.json
    exists but fails to parse, in either layout. Degraded discovery (no real
    siblings found) reports none, matching discover_undeclared."""
    found, broken, _layout, _plugin_name, _self_dir, _glob_root = _discover_all(root)
    if len(found) <= 1:
        return []
    return broken


def discover_undeclared(root: Path | None = None) -> list[str]:
    """Plugin directories (identified by .claude-plugin/plugin.json) that have
    no requirements.json at all. Neutral, not a failure -- see issue #21. A
    plugin whose requirements.json exists but fails to parse is reported by
    _discover_broken instead, never here.

    Degraded discovery (no siblings visible) reports an empty list rather
    than claiming visibility it doesn't have."""
    found, broken, layout, _plugin_name, _self_dir, glob_root = _discover_all(root)
    if len(found) <= 1:
        return []

    if layout == "flat":
        candidates = {p.parents[1].name for p in glob_root.glob("*/.claude-plugin/plugin.json")}
    else:
        candidates = {p.parents[2].name for p in glob_root.glob("*/*/.claude-plugin/plugin.json")}
    broken_names = {f["plugin"] for f in broken}
    return sorted(candidates - set(found) - broken_names)


# ---------------------------------------------------------------------------
# probing
# ---------------------------------------------------------------------------

def run_probe(argv: list[str]) -> tuple[int, str]:
    """Execute a declared probe argv with shell=False (never a shell string,
    never metacharacter expansion) and return (exit_code, combined output).

    A missing executable is reported as exit 127 (the shell convention for
    "command not found") and a timeout as 124, rather than propagating the
    underlying exception -- callers get one uniform (code, output) result."""
    try:
        result = subprocess.run(argv, shell=False, capture_output=True, timeout=30, text=True)
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, "probe timed out after 30s"
    return result.returncode, (result.stdout or "") + (result.stderr or "")


# ---------------------------------------------------------------------------
# per-item evaluation
# ---------------------------------------------------------------------------

def evaluate_tool(plugin: str, tool: dict) -> tuple[str, dict | None]:
    """Returns (status, finding); status is 'ok', 'missing', or 'degraded'.
    finding is None when status is 'ok'."""
    code, output = run_probe(tool["probe"])
    required = tool["required"]
    remedy = _install_hint(tool.get("install"))

    if code != 0:
        status = "missing" if required else "degraded"
        return status, _finding(plugin, "tool", tool["name"], tool["why"], remedy,
                                 f"probe exited {code}")

    version_pattern = tool.get("version_pattern")
    min_version = tool.get("min_version")
    if version_pattern and min_version:
        match = re.search(version_pattern, output)
        if match:
            found_version = match.group(1)
            satisfied = compare_versions(found_version, min_version)
            # satisfied is False -> genuinely too old. True or None (unparseable,
            # i.e. unknown) both fall through to "ok" -- an unknown comparison
            # is not a failure.
            if satisfied is False:
                status = "missing" if required else "degraded"
                return status, _finding(
                    plugin, "tool", tool["name"], tool["why"], remedy,
                    f"found {found_version}, need >= {min_version}")
        # No match at all -- the probe's output didn't contain a recognizable
        # version string. Presence is already confirmed (exit 0); treat the
        # version as unknown rather than failing on it.
    return "ok", None


def evaluate_config(plugin: str, entry: dict, *, repo_root: Path, home: Path) -> tuple[str, dict | None]:
    scope_root = repo_root if entry["scope"] == "repo" else home
    target = scope_root / entry["path"]
    if target.exists():
        return "ok", None
    status = "missing" if entry["required"] else "degraded"
    return status, _finding(plugin, "config", entry["path"], entry["why"], entry["remedy"],
                             f"not found: {target}")


def evaluate_auth(plugin: str, entry: dict) -> tuple[str, dict | None]:
    """Auth entries carry no `required` field in the schema -- a failed auth
    probe always degrades a capability, never drives the hard exit code."""
    code, output = run_probe(entry["probe"])
    if code == 0:
        return "ok", None
    return "degraded", _finding(plugin, "auth", entry["name"], entry["why"], entry["remedy"],
                                 f"status {code}: {_first_line(output)}")


# ---------------------------------------------------------------------------
# report assembly
# ---------------------------------------------------------------------------

def _bucket(status: str, finding: dict | None, missing: list[dict], degraded: list[dict]) -> int:
    """Files `finding` into the right list per `status`; returns 1 if the item
    was ok (for the caller's running ok_count), else 0."""
    if status == "missing":
        missing.append(finding)
        return 0
    if status == "degraded":
        degraded.append(finding)
        return 0
    return 1


def build_report(root: Path | None = None, plugin_filter: str | None = None, *,
                  repo_root: Path | None = None, home: Path | None = None) -> dict:
    declarations = discover(root)
    degraded_discovery = len(declarations) <= 1
    undeclared = [] if degraded_discovery else discover_undeclared(root)
    # A sibling requirements.json that exists but fails to parse -- surfaced
    # as its own findings (folded into `degraded`, since a malformed
    # declaration carries no `required` signal of its own) rather than
    # crashing build_report or being misfiled as "undeclared".
    broken = [] if degraded_discovery else _discover_broken(root)

    plugins_report = {
        name: {"version": version, "path": str(path)}
        for name, (version, path) in sorted(declarations.items())
    }

    if plugin_filter is not None and plugin_filter not in declarations:
        return {
            "plugins": plugins_report,
            "degraded_discovery": degraded_discovery,
            "missing": [],
            "degraded": list(broken),
            "undeclared": undeclared,
            "ok_count": 0,
            "exit_code": 2,
            "error": f"unknown plugin: {plugin_filter}",
        }

    repo_root = Path.cwd() if repo_root is None else repo_root
    home = Path.home() if home is None else home
    names = [plugin_filter] if plugin_filter else sorted(declarations)

    missing: list[dict] = []
    degraded: list[dict] = list(broken)
    ok_count = 0

    for name in names:
        _version, path = declarations[name]
        try:
            data = _load_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            # Defense in depth: discover() already excludes unparseable
            # siblings from `declarations`, so this should be unreachable in
            # practice -- but a broken declaration must never traceback
            # regardless of how it got past discovery (e.g. edited on disk
            # between the discover() call above and this read).
            degraded.append(_broken_finding(name, path, exc))
            continue

        for tool in data.get("tools", []):
            status, finding = evaluate_tool(name, tool)
            ok_count += _bucket(status, finding, missing, degraded)

        for cfg in data.get("config", []):
            status, finding = evaluate_config(name, cfg, repo_root=repo_root, home=home)
            ok_count += _bucket(status, finding, missing, degraded)

        for auth in data.get("auth", []):
            status, finding = evaluate_auth(name, auth)
            ok_count += _bucket(status, finding, missing, degraded)

    return {
        "plugins": plugins_report,
        "degraded_discovery": degraded_discovery,
        "missing": missing,
        "degraded": degraded,
        "undeclared": undeclared,
        "ok_count": ok_count,
        "exit_code": 1 if missing else 0,
    }


def _print_human(report: dict) -> None:
    if report.get("error"):
        print(report["error"], file=sys.stderr)
        return

    if report["degraded_discovery"]:
        print("(degraded discovery: no sibling plugins found; reporting on self only)")

    print("Plugins:")
    for name, info in sorted(report["plugins"].items()):
        version = f" v{info['version']}" if info["version"] else ""
        print(f"  {name}{version}")

    if report["missing"]:
        print("\nMissing (hard):")
        for f in report["missing"]:
            print(f"  [{f['plugin']}] {f['name']}: {f['detail']} -- {f['why']}")
            if f["remedy"]:
                print(f"    remedy: {f['remedy']}")

    if report["degraded"]:
        print("\nDegraded (optional):")
        for f in report["degraded"]:
            print(f"  [{f['plugin']}] {f['name']}: {f['detail']} -- {f['why']}")
            if f["remedy"]:
                print(f"    remedy: {f['remedy']}")

    if report["undeclared"]:
        count = len(report["undeclared"])
        noun = "plugin has" if count == 1 else "plugins have"
        print(f"\nWARNING: {count} {noun} no requirements.json -- "
              f"their needs are unchecked (see issue #21): {', '.join(report['undeclared'])}")

    print(f"\nOK: {report['ok_count']} requirement(s) met")


# ---------------------------------------------------------------------------
# probe subcommand
# ---------------------------------------------------------------------------

def cmd_probe(plugin_name: str, probe_name: str, root: Path | None) -> int:
    """Re-run a single declared probe by (plugin, name). Only ever runs a
    probe found in a discovered declaration -- an unknown plugin or probe
    name is a usage error (exit 2), never a fallback to running anything else."""
    try:
        declarations = discover(root)
    except DiscoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if plugin_name not in declarations:
        print(f"unknown plugin: {plugin_name}", file=sys.stderr)
        return 2

    _version, path = declarations[plugin_name]
    try:
        data = _load_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"failed to read {path}: {exc}", file=sys.stderr)
        return 2

    entry = None
    kind = None
    for tool in data.get("tools", []):
        if tool.get("name") == probe_name:
            entry, kind = tool, "tool"
            break
    if entry is None:
        for auth in data.get("auth", []):
            if auth.get("name") == probe_name:
                entry, kind = auth, "auth"
                break
    if entry is None:
        print(f"unknown probe: {plugin_name}/{probe_name}", file=sys.stderr)
        return 2

    code, output = run_probe(entry["probe"])
    if kind == "auth":
        print(f"exit {code}: {_first_line(output)}")
    else:
        print(f"exit {code}")
        text = output.strip()
        if text:
            print(text)
    return 0 if code == 0 else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="env_check.py check")
    parser.add_argument("--plugin", help="restrict evaluation to a single plugin")
    parser.add_argument("--root", type=Path, help="override discovery root (for testing)")
    parser.add_argument("--json", action="store_true", help="emit the JSON report")
    args = parser.parse_args(argv)

    try:
        report = build_report(root=args.root, plugin_filter=args.plugin)
    except DiscoveryError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)
    return report["exit_code"]


def _main_probe(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="env_check.py probe")
    parser.add_argument("plugin")
    parser.add_argument("name")
    parser.add_argument("--root", type=Path, help="override discovery root (for testing)")
    args = parser.parse_args(argv)
    return cmd_probe(args.plugin, args.name, args.root)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    if argv and argv[0] == "probe":
        return _main_probe(argv[1:])
    if argv and argv[0] == "check":
        argv = argv[1:]
    return _main_check(argv)


if __name__ == "__main__":
    sys.exit(main())
