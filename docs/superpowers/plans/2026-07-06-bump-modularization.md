# Bump Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the 964-line `deps:bump` monolith into a thin orchestrator skill plus config-selected Python adapters (ecosystem / code host / issue tracker) that speak a common JSON contract, with an agnostic mechanical core, preserving today's exact GitHub + Go/Python/Node behavior.

**Architecture:** All deterministic logic moves into a `bumplib` Python package under `deps/scripts/`, driven by one PEP-723 CLI entrypoint `bump.py <axis> <name> <verb>`. Three axes (ecosystem, codeHost, issueTracker) are selected from `.bump-config.json` and resolved to adapter modules; every adapter reads/writes normalized contract JSON. A fixed core (`contracts`, `config`, `categorize`, `dispatch`) never varies by provider. The `SKILL.md` becomes a thin orchestrator that shells out to `bump.py` and holds only git flow, changelog research, the human plan, and the report.

**Tech Stack:** Python 3.10+ (stdlib only: `dataclasses`, `json`, `argparse`, `subprocess`, `re`, `pathlib`, `importlib`), `unittest` for tests, `ruff` for lint, `uv run` for invocation, `gh` CLI for GitHub.

## Global Constraints

- **Python 3.10+**, standard library only — no third-party runtime dependencies (matches existing `deps`/`github`/`dev` scripts). Copy the PEP-723 header block verbatim from `github/scripts/gh-issues.py` (`# /// script` … `requires-python = ">=3.10"`).
- **Tests use `unittest`** (pytest is NOT installed). Every test file: `import sys`; `sys.dont_write_bytecode = True`; `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))`; ends with `if __name__ == "__main__": unittest.main()`. Tests live in top-level `tests/`, named `tests/test_bump_<component>.py`.
- **Run a single test file:** `python3 -m unittest tests.test_bump_<component> -v`. **Run all bump tests:** `python3 -m unittest discover -s tests -p "test_bump_*.py" -v`.
- **Lint before every commit:** `ruff check deps/scripts tests` — must pass clean.
- **Behavior preservation:** the authoritative reference for every command string and categorization rule is the current `deps/skills/bump/SKILL.md` (kept in git history at commit `0f22bb5`). Where a task says "exact command from Phase N", copy it verbatim from that file — do not invent alternatives.
- **Contract stability:** the JSON shapes in Task 1 are the interface every adapter and the categorizer must honor. Never add a required field to a contract without updating `contracts.py` and its tests.
- **Adapter output rule:** every adapter verb prints exactly one JSON value to stdout and nothing else; warnings/diagnostics go to stderr and to a `warnings: [...]` field in the JSON, never to stdout.
- **Subprocess safety:** invoke tools with `subprocess.run(list, capture_output=True, text=True)` — **no `shell=True`** — for any command that interpolates per-run data (package specs, versions, branch names, PR titles/bodies). A `shell=True` helper is permitted *only* for fixed, trusted config/default command strings that need shell operators (e.g. `pnpm run lint:all || pnpm run lint`) and must never receive interpolated per-run data. Name the two helpers `_run(args)` and `_run_shell(cmd)` so the distinction is visible at every call site.

---

## File Structure

**Create:**
- `deps/scripts/bump.py` — PEP-723 CLI entrypoint; `sys.path` bootstrap; dispatch.
- `deps/scripts/bumplib/__init__.py` — package marker; exports version.
- `deps/scripts/bumplib/contracts.py` — dataclasses + JSON (de)serialization for update records, advisories, context, categories.
- `deps/scripts/bumplib/config.py` — load/merge exclusions; adapter selection; command overrides.
- `deps/scripts/bumplib/categorize.py` — agnostic semver + glob categorizer.
- `deps/scripts/bumplib/dispatch.py` — axis+name → module resolution; verb invocation; `none` fallbacks; output validation.
- `deps/scripts/bumplib/ecosystems/__init__.py`, `go.py`, `python.py`, `node.py`.
- `deps/scripts/bumplib/codehosts/__init__.py`, `github.py`.
- `deps/scripts/bumplib/trackers/__init__.py`, `github.py`.
- `deps/skills/bump/reference/contracts.md` — authoritative contract doc.
- `deps/skills/bump/reference/adding-adapters.md` — extension guide.
- `tests/test_bump_contracts.py`, `test_bump_config.py`, `test_bump_categorize.py`, `test_bump_dispatch.py`, `test_bump_eco_go.py`, `test_bump_eco_node.py`, `test_bump_eco_python.py`, `test_bump_codehost_github.py`, `test_bump_tracker_github.py`.
- `tests/fixtures/bump/` — recorded tool outputs (`go_list.txt`, `pnpm_outdated.json`, `npm_audit.json`, `pip_audit.json`, `dependabot_alerts.json`, etc.).

**Modify:**
- `deps/skills/bump/SKILL.md` — replace phase bodies with thin orchestration that calls `bump.py`.
- `deps/.claude-plugin/plugin.json` — bump version to `2.0.0`.

**Responsibility boundaries:** each adapter module owns exactly one provider on one axis. Pure parse/classify functions are separated from subprocess calls so they can be unit-tested against fixtures without invoking real tools.

---

## Task 1: Contracts module

**Files:**
- Create: `deps/scripts/bumplib/__init__.py`, `deps/scripts/bumplib/contracts.py`
- Test: `tests/test_bump_contracts.py`

**Interfaces:**
- Produces: dataclasses `UpdateRecord(name, current, latest, wanted, bump, kind, location, pinned=False, ecosystem="", meta=None)`, `Advisory(package, ecosystem, severity, current, fixed, ids=None, summary="", source="")`, `Context(issues=None, pullRequests=None)`, `Categories(securityFixes=None, safe=None, needsPlan=None, skipped=None)`. Constants `BUMP_MAJOR="major"`, `BUMP_MINOR="minor"`, `BUMP_PATCH="patch"`, `BUMP_NONE="none"`. Functions `dump(obj) -> str` (JSON string, dataclasses → dicts, stable key order), `load_records(s) -> list[UpdateRecord]`, `load_advisories(s) -> list[Advisory]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_contracts.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import contracts as c


class TestContracts(unittest.TestCase):
    def test_update_record_defaults(self):
        r = c.UpdateRecord(name="eslint", current="9.38.0", latest="9.39.2",
                           wanted="9.39.2", bump=c.BUMP_MINOR, kind="direct",
                           location="package.json")
        self.assertFalse(r.pinned)
        self.assertEqual(r.meta, {})
        self.assertEqual(r.ecosystem, "")

    def test_dump_is_stable_json(self):
        r = c.UpdateRecord(name="a", current="1.0.0", latest="1.0.1",
                           wanted="1.0.1", bump=c.BUMP_PATCH, kind="direct",
                           location="go.mod")
        parsed = json.loads(c.dump(r))
        self.assertEqual(parsed["name"], "a")
        self.assertEqual(parsed["bump"], "patch")
        self.assertEqual(parsed["pinned"], False)

    def test_dump_list_roundtrips_records(self):
        recs = [c.UpdateRecord(name="a", current="1.0.0", latest="2.0.0",
                               wanted="1.0.0", bump=c.BUMP_MAJOR, kind="direct",
                               location="go.mod")]
        back = c.load_records(c.dump(recs))
        self.assertEqual(back[0].name, "a")
        self.assertEqual(back[0].bump, "major")

    def test_load_advisories(self):
        s = c.dump([c.Advisory(package="qs", ecosystem="node", severity="HIGH",
                               current="6.14.1", fixed="6.14.2", ids=["CVE-1"],
                               source="audit")])
        adv = c.load_advisories(s)
        self.assertEqual(adv[0].ids, ["CVE-1"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_bump_contracts -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'bumplib'`.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/__init__.py
__version__ = "2.0.0"
```

```python
# deps/scripts/bumplib/contracts.py
"""Common JSON contract for bump adapters: normalized dataclasses + (de)serialization.

Every adapter verb emits one of these shapes; the categorizer and orchestrator
consume them without knowing which provider produced the data.
"""
import json
from dataclasses import dataclass, field, is_dataclass, asdict

BUMP_MAJOR = "major"
BUMP_MINOR = "minor"
BUMP_PATCH = "patch"
BUMP_NONE = "none"


@dataclass
class UpdateRecord:
    name: str
    current: str
    latest: str
    wanted: str
    bump: str
    kind: str
    location: str
    pinned: bool = False
    ecosystem: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class Advisory:
    package: str
    ecosystem: str
    severity: str
    current: str
    fixed: str
    ids: list = field(default_factory=list)
    summary: str = ""
    source: str = ""


@dataclass
class Context:
    issues: list = field(default_factory=list)
    pullRequests: list = field(default_factory=list)


@dataclass
class Categories:
    securityFixes: list = field(default_factory=list)
    safe: list = field(default_factory=list)
    needsPlan: list = field(default_factory=list)
    skipped: list = field(default_factory=list)


def _plain(obj):
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, list):
        return [_plain(x) for x in obj]
    return obj


def dump(obj) -> str:
    return json.dumps(_plain(obj), sort_keys=True, indent=2)


def load_records(s) -> list:
    data = json.loads(s) if isinstance(s, str) else s
    return [UpdateRecord(**d) for d in data]


def load_advisories(s) -> list:
    data = json.loads(s) if isinstance(s, str) else s
    return [Advisory(**d) for d in data]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_contracts -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/__init__.py deps/scripts/bumplib/contracts.py tests/test_bump_contracts.py
git commit -m "feat(bump): add common JSON contract dataclasses"
```

---

## Task 2: Categorizer (agnostic semver + glob)

**Files:**
- Create: `deps/scripts/bumplib/categorize.py`
- Test: `tests/test_bump_categorize.py`

**Interfaces:**
- Consumes: `contracts.UpdateRecord`, `contracts.Advisory`.
- Produces: `parse_semver(v) -> tuple[int,int,int]`; `classify_bump(current, latest) -> str` (one of `major`/`minor`/`patch`/`none`); `glob_match(name, pattern) -> bool` (exact match, or prefix glob where a trailing `*` matches any suffix); `categorize(updates: list[UpdateRecord], advisories: list[Advisory], exclude: list[str], holds: dict[str,str], replace_targets: set[str]) -> contracts.Categories`. Each categorized item is a dict `{...record fields..., "reason": str, "advisory": {...}|None}`.

**Category rules (verbatim from SKILL.md Phase 5):**
- **Skipped:** package in `replace_targets`, OR `classify_bump == "none"`.
- **Security fix:** an advisory exists for the package AND bump ∈ {patch, minor} AND not excluded. (reason: `"security fix (<CVE/severity>)"`.)
- **Needs plan:** bump == major (reason `"Major (<cur> -> <lat>)"`, or `"Major security fix"` if an advisory exists); OR excluded/pinned/held (reason names the source: `"pinned"`, `"Excluded (<pattern>)"`, or `"Hold: <text>"`).
- **Safe:** bump ∈ {patch, minor}, not excluded, no hold, no major. (reason `"<bump> update"`.)
- Exclusion applies if `record.pinned` is True, OR any `exclude` pattern matches via `glob_match`, OR the name is a key in `holds`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_categorize.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import contracts as c
from bumplib import categorize as cat


def rec(name, current, latest, **kw):
    bump = cat.classify_bump(current, latest)
    return c.UpdateRecord(name=name, current=current, latest=latest,
                          wanted=kw.get("wanted", latest), bump=bump,
                          kind=kw.get("kind", "direct"),
                          location=kw.get("location", "manifest"),
                          pinned=kw.get("pinned", False))


class TestSemver(unittest.TestCase):
    def test_parse_strips_leading_v(self):
        self.assertEqual(cat.parse_semver("v1.2.3"), (1, 2, 3))

    def test_parse_trims_prerelease(self):
        self.assertEqual(cat.parse_semver("2.0.0-rc.1"), (2, 0, 0))

    def test_classify(self):
        self.assertEqual(cat.classify_bump("1.2.3", "2.0.0"), "major")
        self.assertEqual(cat.classify_bump("1.2.3", "1.5.0"), "minor")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.5"), "patch")
        self.assertEqual(cat.classify_bump("1.2.3", "1.2.3"), "none")


class TestGlob(unittest.TestCase):
    def test_exact_and_prefix(self):
        self.assertTrue(cat.glob_match("zone.js", "zone.js"))
        self.assertFalse(cat.glob_match("zone.jsx", "zone.js"))
        self.assertTrue(cat.glob_match("@angular/core", "@angular/*"))
        self.assertTrue(cat.glob_match("@antv/x6-plugin", "@antv/x6*"))
        self.assertFalse(cat.glob_match("@antv/y", "@antv/x6*"))


class TestCategorize(unittest.TestCase):
    def test_safe_minor(self):
        out = cat.categorize([rec("eslint", "9.38.0", "9.39.2")], [], [], {}, set())
        self.assertEqual(len(out.safe), 1)
        self.assertEqual(out.safe[0]["reason"], "minor update")

    def test_security_patch(self):
        adv = [c.Advisory(package="qs", ecosystem="node", severity="HIGH",
                          current="6.14.1", fixed="6.14.2", ids=["CVE-1"])]
        out = cat.categorize([rec("qs", "6.14.1", "6.14.2")], adv, [], {}, set())
        self.assertEqual(len(out.securityFixes), 1)

    def test_major_needs_plan(self):
        out = cat.categorize([rec("typescript", "5.8.0", "6.0.0")], [], [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major", out.needsPlan[0]["reason"])

    def test_excluded_needs_plan(self):
        out = cat.categorize([rec("@angular/core", "20.2.0", "20.3.0")], [],
                             ["@angular/*"], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Excluded", out.needsPlan[0]["reason"])

    def test_pinned_needs_plan(self):
        out = cat.categorize([rec("requests", "2.28.0", "2.29.0", pinned=True)], [],
                             [], {}, set())
        self.assertEqual(out.needsPlan[0]["reason"], "pinned")

    def test_hold_needs_plan(self):
        out = cat.categorize([rec("@antv/x6", "2.19.2", "2.20.0")], [], [],
                             {"@antv/x6": "v3 breaking"}, set())
        self.assertIn("Hold", out.needsPlan[0]["reason"])

    def test_replace_target_skipped(self):
        out = cat.categorize([rec("local/mod", "1.0.0", "1.1.0")], [], [], {},
                             {"local/mod"})
        self.assertEqual(len(out.skipped), 1)

    def test_uptodate_skipped(self):
        out = cat.categorize([rec("a", "1.0.0", "1.0.0")], [], [], {}, set())
        self.assertEqual(len(out.skipped), 1)

    def test_major_security_goes_to_plan(self):
        adv = [c.Advisory(package="pgx", ecosystem="go", severity="HIGH",
                          current="4.18.3", fixed="5.0.0", ids=["CVE-9"])]
        out = cat.categorize([rec("pgx", "4.18.3", "5.8.0")], adv, [], {}, set())
        self.assertEqual(len(out.needsPlan), 1)
        self.assertIn("Major security", out.needsPlan[0]["reason"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_bump_categorize -v`
Expected: FAIL — `No module named 'bumplib.categorize'`.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/categorize.py
"""Agnostic categorizer: semver comparison + glob exclusion, no provider knowledge."""
import re
from dataclasses import asdict

from . import contracts as c

_SEMVER = re.compile(r"(\d+)\.(\d+)\.(\d+)")


def parse_semver(v: str):
    """Return (major, minor, patch). Strips leading 'v', trailing pre-release/build."""
    m = _SEMVER.search(v or "")
    if not m:
        return (0, 0, 0)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def classify_bump(current: str, latest: str) -> str:
    cur, lat = parse_semver(current), parse_semver(latest)
    if lat == cur or lat < cur:
        return c.BUMP_NONE
    if lat[0] > cur[0]:
        return c.BUMP_MAJOR
    if lat[1] > cur[1]:
        return c.BUMP_MINOR
    return c.BUMP_PATCH


def glob_match(name: str, pattern: str) -> bool:
    if pattern.endswith("*"):
        return name.startswith(pattern[:-1])
    return name == pattern


def _excluded(rec, exclude, holds):
    if rec.pinned:
        return "pinned"
    for pat in exclude:
        if glob_match(rec.name, pat):
            return f"Excluded ({pat})"
    if rec.name in holds:
        return f"Hold: {holds[rec.name]}"
    return None


def _item(rec, reason, advisory=None):
    d = asdict(rec)
    d["reason"] = reason
    d["advisory"] = asdict(advisory) if advisory else None
    return d


def categorize(updates, advisories, exclude, holds, replace_targets) -> c.Categories:
    adv_index = {a.package: a for a in advisories}
    out = c.Categories()
    for rec in updates:
        if rec.name in replace_targets or rec.bump == c.BUMP_NONE:
            out.skipped.append(_item(rec, "replace directive" if rec.name in replace_targets else "up to date"))
            continue
        adv = adv_index.get(rec.name)
        excl = _excluded(rec, exclude, holds)
        if rec.bump == c.BUMP_MAJOR:
            reason = "Major security fix" if adv else f"Major ({rec.current} -> {rec.latest})"
            out.needsPlan.append(_item(rec, reason, adv))
        elif excl:
            out.needsPlan.append(_item(rec, excl, adv))
        elif adv:
            sev = adv.ids[0] if adv.ids else adv.severity
            out.securityFixes.append(_item(rec, f"security fix ({sev})", adv))
        else:
            out.safe.append(_item(rec, f"{rec.bump} update"))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_categorize -v`
Expected: PASS (all tests).

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/categorize.py tests/test_bump_categorize.py
git commit -m "feat(bump): add agnostic semver + glob categorizer"
```

---

## Task 3: Config loading and merge

**Files:**
- Create: `deps/scripts/bumplib/config.py`
- Test: `tests/test_bump_config.py`

**Interfaces:**
- Produces: `parse_claude_exclusions(text) -> list[str]` (bullets under a `## Bump Exclusions` heading); `load_config(root: Path) -> dict` (reads `.bump-config.json` if present, else `{}`); `merged_exclusions(root: Path) -> tuple[list[str], dict[str,str]]` returning `(exclude_patterns, holds)` from CLAUDE.md + `.bump-config.json`; `resolve_adapter(axis: str, config: dict, remote_url: str|None) -> str` (returns configured value, else auto-detects `"github"` when `remote_url` contains `github.com` and axis ∈ {codeHost, issueTracker}, else `"none"`); `ecosystem_commands(config: dict, eco: str) -> dict` (config overrides merged over built-in defaults with keys `cacheClear, build, test, lint`).

**Defaults (`DEFAULT_COMMANDS`), copied from SKILL.md Phase 3/8:** provide per-ecosystem-and-manager defaults, e.g. `("node","pnpm") -> {"cacheClear": "pnpm store prune && npm cache clean --force", "build": "pnpm run build", "test": "pnpm test", "lint": "pnpm run lint:all"}`; `("go", "") -> {"cacheClear": "", "build": "go build ./...", "test": "go test ./...", "lint": "go vet ./..."}`; `("python","uv") -> {"cacheClear": "uv cache clean", "build": "", "test": "uv run pytest", "lint": "uv run ruff check ."}`. (Fill the full table from the SKILL.md Phase 3 and Phase 8 command lists — every ecosystem/manager pair that appears there.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_config.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import config as cfg


class TestClaudeExclusions(unittest.TestCase):
    def test_parses_bullets_under_heading(self):
        text = ("# Project\n\n## Bump Exclusions\n"
                "- @angular/*\n- zone.js\n\n## Other\n- not-this\n")
        self.assertEqual(cfg.parse_claude_exclusions(text), ["@angular/*", "zone.js"])

    def test_no_heading_returns_empty(self):
        self.assertEqual(cfg.parse_claude_exclusions("# X\n- a\n"), [])


class TestMerge(unittest.TestCase):
    def _root(self, td, claude=None, bump_cfg=None):
        root = Path(td)
        if claude is not None:
            (root / "CLAUDE.md").write_text(claude)
        if bump_cfg is not None:
            (root / ".bump-config.json").write_text(json.dumps(bump_cfg))
        return root

    def test_merges_both_sources(self):
        with tempfile.TemporaryDirectory() as td:
            root = self._root(td, claude="## Bump Exclusions\n- a/*\n",
                              bump_cfg={"exclude": ["b"], "hold": {"c": "later"}})
            excl, holds = cfg.merged_exclusions(root)
            self.assertIn("a/*", excl)
            self.assertIn("b", excl)
            self.assertEqual(holds["c"], "later")


class TestResolveAdapter(unittest.TestCase):
    def test_explicit_wins(self):
        self.assertEqual(cfg.resolve_adapter("issueTracker", {"issueTracker": "jira"}, None), "jira")

    def test_autodetect_github(self):
        self.assertEqual(cfg.resolve_adapter("codeHost", {}, "git@github.com:o/r.git"), "github")

    def test_none_when_not_github(self):
        self.assertEqual(cfg.resolve_adapter("codeHost", {}, "git@gitlab.com:o/r.git"), "none")


class TestEcosystemCommands(unittest.TestCase):
    def test_override_beats_default(self):
        merged = cfg.ecosystem_commands({"ecosystems": {"node": {"test": "custom"}}}, "node", "pnpm")
        self.assertEqual(merged["test"], "custom")
        self.assertEqual(merged["build"], "pnpm run build")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_bump_config -v`
Expected: FAIL — `No module named 'bumplib.config'`.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/config.py
"""Load and merge bump configuration: exclusions, adapter selection, command overrides."""
import json
from pathlib import Path

DEFAULT_COMMANDS = {
    ("go", ""): {"cacheClear": "", "build": "go build ./...", "test": "go test ./...", "lint": "go vet ./..."},
    ("python", "uv"): {"cacheClear": "uv cache clean", "build": "", "test": "uv run pytest", "lint": "uv run ruff check ."},
    ("python", "pip"): {"cacheClear": "pip cache purge", "build": "", "test": "pytest", "lint": "ruff check ."},
    ("node", "pnpm"): {"cacheClear": "pnpm store prune && npm cache clean --force", "build": "pnpm run build", "test": "pnpm test", "lint": "pnpm run lint:all"},
    ("node", "npm"): {"cacheClear": "npm cache clean --force", "build": "npm run build", "test": "npm test", "lint": "npm run lint"},
}


def parse_claude_exclusions(text: str) -> list:
    out, in_section = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_section = s.lower() == "## bump exclusions"
            continue
        if in_section and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def load_config(root: Path) -> dict:
    p = Path(root) / ".bump-config.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def merged_exclusions(root: Path):
    root = Path(root)
    exclude, holds = [], {}
    claude = root / "CLAUDE.md"
    if not claude.exists():
        claude = root / ".claude" / "CLAUDE.md"
    if claude.exists():
        exclude += parse_claude_exclusions(claude.read_text())
    cfg = load_config(root)
    exclude += list(cfg.get("exclude", []))
    holds.update(cfg.get("hold", {}))
    # de-dupe, preserve order
    seen, uniq = set(), []
    for p in exclude:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq, holds


def resolve_adapter(axis: str, config: dict, remote_url) -> str:
    if config.get(axis):
        return config[axis]
    if axis in ("codeHost", "issueTracker") and remote_url and "github.com" in remote_url:
        return "github"
    if axis == "ecosystem":
        return ""  # ecosystem is detected, not configured
    return "none"


def ecosystem_commands(config: dict, eco: str, manager: str = "") -> dict:
    base = dict(DEFAULT_COMMANDS.get((eco, manager), {}))
    override = (config.get("ecosystems", {}) or {}).get(eco, {}) or {}
    base.update({k: v for k, v in override.items() if k in ("cacheClear", "build", "test", "lint")})
    return base
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_config -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/config.py tests/test_bump_config.py
git commit -m "feat(bump): add config load/merge and adapter selection"
```

---

## Task 4: Dispatch + CLI entrypoint

**Files:**
- Create: `deps/scripts/bumplib/dispatch.py`, `deps/scripts/bump.py`, `deps/scripts/bumplib/ecosystems/__init__.py`, `deps/scripts/bumplib/codehosts/__init__.py`, `deps/scripts/bumplib/trackers/__init__.py`
- Test: `tests/test_bump_dispatch.py`

**Interfaces:**
- Consumes: `contracts`.
- Produces: `AXES = {"ecosystem": "ecosystems", "codeHost": "codehosts", "issueTracker": "trackers"}`; `NONE_RESULTS: dict[str, object]` mapping each verb to its empty contract JSON-able value (e.g. `"outdated" -> []`, `"audit" -> []`, `"issues"/"prs" -> {"issues": [], "pullRequests": []}` via `Context`, `"alerts" -> []`); `run(axis, name, verb, argv) -> object` which, when `name == "none"`, returns `NONE_RESULTS[verb]`, else imports `bumplib.<package>.<name>` and calls its `handle(verb, argv) -> object`; each adapter module exposes `handle(verb: str, argv: list[str]) -> object`.
- The `bump.py` CLI: `bump.py <axis> <name> <verb> [args...]`, prints `contracts.dump(run(...))` to stdout.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_dispatch.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "deps" / "scripts"))

from bumplib import dispatch


class TestDispatch(unittest.TestCase):
    def test_none_outdated_is_empty_list(self):
        self.assertEqual(dispatch.run("ecosystem", "none", "outdated", []), [])

    def test_none_issues_is_empty_context(self):
        out = dispatch.run("issueTracker", "none", "issues", [])
        self.assertEqual(out.issues, [])
        self.assertEqual(out.pullRequests, [])

    def test_unknown_adapter_raises(self):
        with self.assertRaises(ModuleNotFoundError):
            dispatch.run("ecosystem", "nosuch", "outdated", [])

    def test_real_adapter_handle_called(self):
        # go adapter exists after Task 5; here assert routing to a stub package attr
        self.assertIn("ecosystem", dispatch.AXES)
        self.assertEqual(dispatch.AXES["codeHost"], "codehosts")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_bump_dispatch -v`
Expected: FAIL — `No module named 'bumplib.dispatch'`.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/ecosystems/__init__.py
# deps/scripts/bumplib/codehosts/__init__.py
# deps/scripts/bumplib/trackers/__init__.py
# (all three are empty package markers)
```

```python
# deps/scripts/bumplib/dispatch.py
"""Resolve axis+name to an adapter module and invoke a verb; handle the 'none' provider."""
import importlib

from . import contracts as c

AXES = {"ecosystem": "ecosystems", "codeHost": "codehosts", "issueTracker": "trackers"}

NONE_RESULTS = {
    "detect": {"present": False},
    "outdated": [],
    "audit": [],
    "alerts": [],
    "prs": c.Context(),
    "issues": c.Context(),
}


def run(axis, name, verb, argv):
    if axis not in AXES:
        raise ValueError(f"unknown axis: {axis}")
    if name == "none":
        if verb not in NONE_RESULTS:
            raise ValueError(f"'none' adapter has no verb '{verb}' on axis {axis}")
        return NONE_RESULTS[verb]
    mod = importlib.import_module(f"bumplib.{AXES[axis]}.{name}")
    return mod.handle(verb, argv)
```

```python
# deps/scripts/bump.py
# /// script
# requires-python = ">=3.10"
# ///
"""bump: unified CLI over bump adapters. Usage: bump.py <axis> <name> <verb> [args...]"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bumplib import contracts, dispatch  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print("usage: bump.py <axis> <name> <verb> [args...]", file=sys.stderr)
        return 2
    axis, name, verb, rest = argv[0], argv[1], argv[2], argv[3:]
    result = dispatch.run(axis, name, verb, rest)
    print(contracts.dump(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_dispatch -v`
Expected: PASS. Also run `python3 deps/scripts/bump.py issueTracker none issues` → prints `{"issues": [], "pullRequests": []}`.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bump.py deps/scripts/bumplib/dispatch.py deps/scripts/bumplib/ecosystems/__init__.py deps/scripts/bumplib/codehosts/__init__.py deps/scripts/bumplib/trackers/__init__.py tests/test_bump_dispatch.py
git commit -m "feat(bump): add dispatch router and CLI entrypoint"
```

---

## Task 5: Go ecosystem adapter

**Files:**
- Create: `deps/scripts/bumplib/ecosystems/go.py`
- Test: `tests/test_bump_eco_go.py`, `tests/fixtures/bump/go_list.txt`, `tests/fixtures/bump/govulncheck.json`

**Interfaces:**
- Consumes: `contracts`, `categorize.classify_bump`.
- Produces: `handle(verb, argv)`; pure functions `parse_outdated(text) -> list[UpdateRecord]` (parses `go list -m -u all` lines of form `module vCUR [vLATEST]`; lines without `[...]` are up-to-date and omitted); `parse_vuln(json_text) -> list[Advisory]` (parses `govulncheck -json` OSV records); `replace_targets(gomod_text) -> set[str]` (module paths on `replace` lines); `pinned_names(gomod_text) -> set[str]` (require lines with `// pinned:` comment).
- Verbs: `detect`, `cache-clear`, `outdated`, `audit`, `apply`, `validate`. Commands verbatim from SKILL.md Phase 4b/7/8: outdated `go list -m -u all`; audit `govulncheck ./...`; apply `go get <pkg>@<ver>` then `go mod tidy` (+ `go work sync` if `go.work`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_eco_go.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.ecosystems import go


class TestGoOutdated(unittest.TestCase):
    def test_parses_bracketed_updates_only(self):
        recs = go.parse_outdated((FIX / "go_list.txt").read_text())
        names = {r.name: r for r in recs}
        self.assertIn("github.com/gin-gonic/gin", names)
        self.assertEqual(names["github.com/gin-gonic/gin"].current, "v1.10.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].latest, "v1.11.0")
        self.assertEqual(names["github.com/gin-gonic/gin"].bump, "minor")
        # up-to-date line must be excluded
        self.assertNotIn("golang.org/x/sys", names)

    def test_replace_and_pinned(self):
        gomod = ("module x\nrequire (\n\tgithub.com/foo/bar v1.2.3 // pinned: compat\n)\n"
                 "replace github.com/foo/bar => ./local\n")
        self.assertIn("github.com/foo/bar", go.replace_targets(gomod))
        self.assertIn("github.com/foo/bar", go.pinned_names(gomod))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create the fixture and run to verify failure**

Create `tests/fixtures/bump/go_list.txt`:
```
github.com/gin-gonic/gin v1.10.0 [v1.11.0]
golang.org/x/crypto v0.46.0 [v0.47.0]
golang.org/x/sys v0.20.0
github.com/jackc/pgx/v4 v4.18.3 [v5.8.0]
```

Run: `python3 -m unittest tests.test_bump_eco_go -v`
Expected: FAIL — `No module named 'bumplib.ecosystems.go'`.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/ecosystems/go.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_eco_go -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/ecosystems/go.py tests/test_bump_eco_go.py tests/fixtures/bump/go_list.txt
git commit -m "feat(bump): add Go ecosystem adapter"
```

---

## Task 6: Node ecosystem adapter

**Files:**
- Create: `deps/scripts/bumplib/ecosystems/node.py`
- Test: `tests/test_bump_eco_node.py`, `tests/fixtures/bump/pnpm_outdated.json`, `tests/fixtures/bump/npm_audit.json`

**Interfaces:**
- Produces: `handle(verb, argv)`; `parse_outdated(json_text, manager) -> list[UpdateRecord]` (pnpm `pnpm outdated --format json` object keyed by package with `current`/`latest`/`wanted`/`dependencyType`; npm `npm outdated --json` similar); `parse_audit(json_text, manager) -> list[Advisory]` (pnpm/npm `audit --json` advisories: severity, module_name, current, patched/fixAvailable, CVE from `via`/`cves`); `detect(root) -> dict` (pnpm if `pnpm-lock.yaml`, npm if `package-lock.json`, prefer pnpm). Commands verbatim from SKILL.md Phase 4d/7/8.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_eco_node.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.ecosystems import node


class TestNode(unittest.TestCase):
    def test_parse_pnpm_outdated(self):
        recs = {r.name: r for r in node.parse_outdated((FIX / "pnpm_outdated.json").read_text(), "pnpm")}
        self.assertEqual(recs["eslint"].current, "9.38.0")
        self.assertEqual(recs["eslint"].latest, "9.39.2")
        self.assertEqual(recs["eslint"].bump, "minor")

    def test_parse_audit(self):
        advs = node.parse_audit((FIX / "npm_audit.json").read_text(), "npm")
        self.assertTrue(any(a.package == "qs" for a in advs))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create fixtures and run to verify failure**

Create `tests/fixtures/bump/pnpm_outdated.json`:
```json
{
  "eslint": { "current": "9.38.0", "latest": "9.39.2", "wanted": "9.39.2", "dependencyType": "devDependencies" },
  "rxjs":   { "current": "7.8.1",  "latest": "7.8.2",  "wanted": "7.8.2",  "dependencyType": "dependencies" }
}
```

Create `tests/fixtures/bump/npm_audit.json`:
```json
{ "vulnerabilities": {
  "qs": { "name": "qs", "severity": "high", "range": "<6.14.2",
          "fixAvailable": { "name": "qs", "version": "6.14.2" },
          "via": [{ "source": 1, "name": "qs", "cwe": [], "cvss": {}, "url": "CVE-1" }] } } }
```

Run: `python3 -m unittest tests.test_bump_eco_node -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/ecosystems/node.py
"""Node ecosystem adapter (pnpm / npm)."""
import json
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
        cur = info.get("current") or (info.get("current", ""))
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
        _run(["pnpm", "store", "prune"] if mgr == "pnpm" else ["npm", "cache", "clean", "--force"])
        return {"warnings": []}
    if verb == "outdated":
        cmd = ["pnpm", "outdated", "--format", "json"] if mgr == "pnpm" else ["npm", "outdated", "--json"]
        out = _run(cmd)
        return parse_outdated(out.stdout, mgr)
    if verb == "audit":
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_eco_node -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/ecosystems/node.py tests/test_bump_eco_node.py tests/fixtures/bump/pnpm_outdated.json tests/fixtures/bump/npm_audit.json
git commit -m "feat(bump): add Node ecosystem adapter"
```

---

## Task 7: Python ecosystem adapter

**Files:**
- Create: `deps/scripts/bumplib/ecosystems/python.py`
- Test: `tests/test_bump_eco_python.py`, `tests/fixtures/bump/pip_outdated.json`, `tests/fixtures/bump/pip_audit.json`

**Interfaces:**
- Produces: `handle(verb, argv)`; `detect(root) -> dict` (uv if `uv` available and (`uv.lock` or `pyproject.toml`), else pip if `requirements.txt`/`setup.py`); `parse_outdated(json_text) -> list[UpdateRecord]` (`pip list --outdated --format json`: `name`, `version`→current, `latest_version`→latest); `parse_audit(json_text) -> list[Advisory]` (`pip-audit --format json`: `dependencies[].vulns[]` with `id`, `fix_versions`). Commands verbatim from SKILL.md Phase 4c/7/8.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_eco_python.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.ecosystems import python as py


class TestPython(unittest.TestCase):
    def test_parse_outdated(self):
        recs = {r.name: r for r in py.parse_outdated((FIX / "pip_outdated.json").read_text())}
        self.assertEqual(recs["requests"].current, "2.28.0")
        self.assertEqual(recs["requests"].latest, "2.31.0")

    def test_parse_audit(self):
        advs = py.parse_audit((FIX / "pip_audit.json").read_text())
        self.assertTrue(any("PYSEC" in (a.ids[0] if a.ids else "") for a in advs))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create fixtures and run to verify failure**

Create `tests/fixtures/bump/pip_outdated.json`:
```json
[ { "name": "requests", "version": "2.28.0", "latest_version": "2.31.0", "latest_filetype": "wheel" } ]
```

Create `tests/fixtures/bump/pip_audit.json`:
```json
{ "dependencies": [
  { "name": "requests", "version": "2.28.0",
    "vulns": [ { "id": "PYSEC-2023-1", "fix_versions": ["2.31.0"], "description": "x" } ] } ] }
```

Run: `python3 -m unittest tests.test_bump_eco_python -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/ecosystems/python.py
"""Python ecosystem adapter (uv / pip)."""
import json
import shutil
import subprocess
from pathlib import Path

from .. import contracts as c
from ..categorize import classify_bump


def detect(root: Path) -> dict:
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
        out = _run(["uv", "run", "pip-audit", "--format", "json"] if mgr == "uv"
                   else ["pip-audit", "--format", "json"])
        if out.returncode == 127:
            return []
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
        return {"applied": argv, "filesModified": ["pyproject.toml", "uv.lock"] if mgr == "uv" else ["requirements.txt"]}
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_eco_python -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/ecosystems/python.py tests/test_bump_eco_python.py tests/fixtures/bump/pip_outdated.json tests/fixtures/bump/pip_audit.json
git commit -m "feat(bump): add Python ecosystem adapter"
```

---

## Task 8: GitHub code-host adapter

**Files:**
- Create: `deps/scripts/bumplib/codehosts/github.py`
- Test: `tests/test_bump_codehost_github.py`, `tests/fixtures/bump/dependabot_alerts.json`, `tests/fixtures/bump/dep_prs.json`

**Interfaces:**
- Produces: `handle(verb, argv)`; `parse_alerts(json_text) -> list[Advisory]` (Dependabot `repos/O/R/dependabot/alerts` array: `security_advisory.summary/severity`, `dependency.package.ecosystem/name`, fixed from `security_vulnerability.first_patched_version.identifier`); `parse_prs(json_text) -> Context` (from `gh pr list ... --json number,title,headRefName`); `open_pr_cmd(branch, title, body) -> str`, `merge_cmd(number) -> str` (command builders). Read commands verbatim from SKILL.md Phase 4a/11.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_codehost_github.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.codehosts import github as gh


class TestGitHubCodeHost(unittest.TestCase):
    def test_parse_alerts(self):
        advs = gh.parse_alerts((FIX / "dependabot_alerts.json").read_text())
        self.assertEqual(advs[0].package, "qs")
        self.assertEqual(advs[0].severity, "HIGH")
        self.assertEqual(advs[0].fixed, "6.14.2")

    def test_parse_prs(self):
        ctx = gh.parse_prs((FIX / "dep_prs.json").read_text())
        self.assertEqual(ctx.pullRequests[0]["id"], "#42")

    def test_merge_cmd(self):
        self.assertEqual(gh.merge_cmd(42),
                         ["gh", "pr", "merge", "42", "--squash", "--delete-branch"])

    def test_open_pr_cmd_passes_title_as_arg(self):
        # title with shell metacharacters must appear as its own list element, unescaped
        cmd = gh.open_pr_cmd("bump-x", "bump; rm -rf /", "body")
        self.assertIn("bump; rm -rf /", cmd)
        self.assertEqual(cmd[0:2], ["gh", "pr"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create fixtures and run to verify failure**

Create `tests/fixtures/bump/dependabot_alerts.json`:
```json
[ { "state": "open",
    "security_advisory": { "summary": "qs DoS", "severity": "high" },
    "security_vulnerability": { "first_patched_version": { "identifier": "6.14.2" } },
    "dependency": { "package": { "ecosystem": "npm", "name": "qs" } } } ]
```

Create `tests/fixtures/bump/dep_prs.json`:
```json
[ { "number": 42, "title": "chore(deps): bump x", "headRefName": "dependabot/npm/x" } ]
```

Run: `python3 -m unittest tests.test_bump_codehost_github -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/codehosts/github.py
"""GitHub code-host adapter: Dependabot alerts, dependency PRs, PR lifecycle."""
import json
import subprocess

from .. import contracts as c


def parse_alerts(json_text: str) -> list:
    data = json.loads(json_text or "[]")
    advs = []
    for a in data:
        if a.get("state") != "open":
            continue
        sa = a.get("security_advisory", {})
        dep = a.get("dependency", {}).get("package", {})
        fixed = a.get("security_vulnerability", {}).get("first_patched_version", {}).get("identifier", "")
        advs.append(c.Advisory(package=dep.get("name", ""), ecosystem=dep.get("ecosystem", ""),
                               severity=sa.get("severity", "").upper(), current="", fixed=fixed,
                               ids=[], summary=sa.get("summary", ""), source="dependabot"))
    return advs


def parse_prs(json_text: str) -> c.Context:
    data = json.loads(json_text or "[]")
    prs = [{"id": f"#{p['number']}", "title": p.get("title", ""),
            "head": p.get("headRefName", ""), "url": p.get("url", "")} for p in data]
    return c.Context(pullRequests=prs)


def open_pr_cmd(branch, title, body):
    """Return an argv list — title/body are passed as separate args, never shell-interpolated,
    so a PR title containing shell metacharacters cannot inject."""
    return ["gh", "pr", "create", "--base", "main", "--head", branch,
            "--title", title, "--body", body]


def merge_cmd(number):
    return ["gh", "pr", "merge", str(number), "--squash", "--delete-branch"]


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def handle(verb, argv):
    if verb == "detect":
        r = _run(["git", "remote", "get-url", "origin"])
        return {"present": "github.com" in r.stdout}
    if verb == "alerts":
        # gh substitutes {owner}/{repo} from the current repo automatically.
        r = _run(["gh", "api", "repos/{owner}/{repo}/dependabot/alerts"])
        if r.returncode != 0:
            return []
        return parse_alerts(r.stdout)
    if verb == "prs":
        r = _run(["gh", "pr", "list", "--label", "dependencies",
                  "--json", "number,title,headRefName,url", "--limit", "20"])
        return parse_prs(r.stdout if r.returncode == 0 else "[]")
    if verb == "open-pr":
        branch, title, body = argv[0], argv[1], argv[2]
        r = _run(open_pr_cmd(branch, title, body))
        return {"output": r.stdout.strip(), "ok": r.returncode == 0}
    if verb == "pr-status":
        number = argv[0]
        r = _run(["gh", "pr", "view", str(number), "--json",
                  "state,mergeable,mergeStateStatus,reviewDecision"])
        return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr.strip()}
    if verb == "merge-pr":
        r = _run(merge_cmd(argv[0]))
        return {"ok": r.returncode == 0, "output": (r.stdout + r.stderr).strip()}
    raise ValueError(f"github codehost: unknown verb {verb}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_codehost_github -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/codehosts/github.py tests/test_bump_codehost_github.py tests/fixtures/bump/dependabot_alerts.json tests/fixtures/bump/dep_prs.json
git commit -m "feat(bump): add GitHub code-host adapter"
```

---

## Task 9: GitHub issue-tracker adapter

**Files:**
- Create: `deps/scripts/bumplib/trackers/github.py`
- Test: `tests/test_bump_tracker_github.py`, `tests/fixtures/bump/dep_issues.json`

**Interfaces:**
- Produces: `handle(verb, argv)`; `parse_issues(json_text) -> Context` (from `gh issue list --label dependencies --json number,title,labels`). Commands verbatim from SKILL.md Phase 4a.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bump_tracker_github.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "deps" / "scripts"))
FIX = BASE / "tests" / "fixtures" / "bump"

from bumplib.trackers import github as tr


class TestGitHubTracker(unittest.TestCase):
    def test_parse_issues(self):
        ctx = tr.parse_issues((FIX / "dep_issues.json").read_text())
        self.assertEqual(ctx.issues[0]["id"], "#7")
        self.assertIn("dependencies", ctx.issues[0]["labels"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Create fixture and run to verify failure**

Create `tests/fixtures/bump/dep_issues.json`:
```json
[ { "number": 7, "title": "Upgrade pgx to v5", "labels": [ { "name": "dependencies" } ] } ]
```

Run: `python3 -m unittest tests.test_bump_tracker_github -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

```python
# deps/scripts/bumplib/trackers/github.py
"""GitHub issue-tracker adapter: dependency-related issues."""
import json
import subprocess

from .. import contracts as c


def parse_issues(json_text: str) -> c.Context:
    data = json.loads(json_text or "[]")
    issues = [{"id": f"#{i['number']}", "title": i.get("title", ""),
               "url": i.get("url", ""),
               "labels": [l.get("name", "") for l in i.get("labels", [])]} for i in data]
    return c.Context(issues=issues)


def _run(args):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True)


def handle(verb, argv):
    if verb == "issues":
        r = _run(["gh", "issue", "list", "--label", "dependencies", "--state", "open",
                  "--json", "number,title,labels,url", "--limit", "20"])
        return parse_issues(r.stdout if r.returncode == 0 else "[]")
    raise ValueError(f"github tracker: unknown verb {verb}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_bump_tracker_github -v`
Expected: PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check deps/scripts tests
git add deps/scripts/bumplib/trackers/github.py tests/test_bump_tracker_github.py tests/fixtures/bump/dep_issues.json
git commit -m "feat(bump): add GitHub issue-tracker adapter"
```

---

## Task 10: Reference docs (contract + adding adapters)

**Files:**
- Create: `deps/skills/bump/reference/contracts.md`, `deps/skills/bump/reference/adding-adapters.md`

**Interfaces:** none (documentation). Content is authoritative for the JSON shapes in Task 1 and the verb tables in Tasks 5–9.

- [ ] **Step 1: Write `contracts.md`**

Document each shape with a field table and one example JSON payload, copied from the dataclasses in `contracts.py`: `UpdateRecord`, `Advisory`, `Context`, `Categories`. State the adapter output rule (one JSON value on stdout; warnings to stderr + `warnings` field). List the verb → output-shape mapping for each axis:

```
ecosystem:  detect→{present,ecosystem,packageManager,workspace?}  cache-clear→{warnings}
            outdated→[UpdateRecord]  audit→[Advisory]  apply→{applied,filesModified}  validate→{build,test,lint,*_output}
codeHost:   detect→{present}  alerts→[Advisory]  prs→Context  open-pr→{ok,output}  pr-status→{state,mergeable,...}  merge-pr→{ok,output}
issueTracker: issues→Context  advisories→[Advisory] (optional)
```

- [ ] **Step 2: Write `adding-adapters.md`**

Step-by-step: (1) pick the axis package (`ecosystems`/`codehosts`/`trackers`); (2) create `<name>.py` exposing `handle(verb, argv)`; (3) implement the verbs for that axis (table above); (4) emit only contract shapes; (5) select it via `.bump-config.json` (`codeHost`/`issueTracker`) — ecosystems are auto-detected via their `detect` verb; (6) add `tests/test_bump_<axis>_<name>.py` with a recorded fixture and pure parse-function tests. **Subprocess safety (required):** shell out with `subprocess.run(list, ...)` and no `shell=True` for anything interpolating package specs, versions, branch names, or PR text; reserve a `_run_shell` helper strictly for fixed trusted config strings needing shell operators. Include a minimal skeleton:

```python
from .. import contracts as c

def handle(verb, argv):
    if verb == "issues":
        return c.Context(issues=[])
    raise ValueError(f"<name>: unknown verb {verb}")
```

- [ ] **Step 3: Commit**

```bash
git add deps/skills/bump/reference/contracts.md deps/skills/bump/reference/adding-adapters.md
git commit -m "docs(bump): add contract and adding-adapters reference"
```

---

## Task 11: Rewrite SKILL.md as thin orchestrator + bump plugin version

**Files:**
- Modify: `deps/skills/bump/SKILL.md`, `deps/.claude-plugin/plugin.json`

**Interfaces:** the SKILL orchestrates by calling `uv run deps/scripts/bump.py <axis> <name> <verb>` (resolve the script path relative to the plugin) and the `bumplib` core. It keeps the git-generic and judgment phases; it delegates all provider mechanics to adapters.

- [ ] **Step 1: Rewrite the SKILL.md body**

Keep the frontmatter `name`/`description` (update `version: 2.0.0`). Replace the phase bodies so each phase calls the CLI instead of embedding commands. The orchestration flow (preserving MODE=pr/direct, bisect, PR monitoring, plan, report from the current skill):

1. **Detect ecosystems:** for each of `go|python|node`, run `bump.py ecosystem <eco> detect`; keep those with `present: true` (honor an explicit ecosystem arg).
2. **Resolve axes:** read `.bump-config.json`; via `config.resolve_adapter`, determine `codeHost` and `issueTracker` (auto-detect GitHub from `git remote get-url origin`).
3. **Branch management (git-generic, unchanged):** MODE=pr on `main`+GitHub code-host, else MODE=direct; stash/checkout logic exactly as current Phase 1.
4. **Cache refresh:** `bump.py ecosystem <eco> cache-clear` per ecosystem.
5. **Gather:** per ecosystem `outdated` + `audit`; once, `codeHost alerts` + `codeHost prs` + `issueTracker issues`. Merge all advisories (ecosystem audit ∪ Dependabot).
6. **Categorize:** load `merged_exclusions`, Go `replace_targets`/`pinned_names`, then call `categorize.categorize(...)` (invoke via a small `bump.py ... ` categorize path or import in the orchestrator's Python step). Display the four categories as the current Phase 6 tables.
7. **Changelog research (judgment, unchanged):** GitHub releases only, for needs-plan majors.
8. **Apply + validate + bisect:** apply safe/security via `ecosystem apply`; run `ecosystem validate`; on failure, run the current Phase 9 bisect loop calling `apply` one-at-a-time + `validate`.
9. **Commit (git-generic, unchanged).**
10. **PR flow (MODE=pr):** `codeHost open-pr`, poll `codeHost pr-status` until ready (current Phase 11 readiness rules), `codeHost merge-pr`; conservative-on-failure exactly as current.
11. **Plan (judgment, unchanged)** and **report (unchanged).**

Each phase body references the exact CLI call and points to `reference/contracts.md` for output shapes. Preserve every error-handling rule from the current SKILL.md "Error Handling" section (missing tool, non-GitHub, SSH-key push failure, gh missing, not-mergeable PR).

- [ ] **Step 2: Bump plugin version**

Edit `deps/.claude-plugin/plugin.json`: set `"version": "2.0.0"`.

- [ ] **Step 3: Verify the skill invokes real scripts**

Run the read-only path end to end against this repo (which has no managed manifests, so expect clean "nothing detected"):
```bash
python3 deps/scripts/bump.py ecosystem go detect
python3 deps/scripts/bump.py issueTracker none issues
```
Expected: valid JSON, no traceback.

- [ ] **Step 4: Commit**

```bash
git add deps/skills/bump/SKILL.md deps/.claude-plugin/plugin.json
git commit -m "refactor(bump): thin orchestrator over bumplib adapters (v2.0.0)"
```

---

## Task 12: Full suite green + integration smoke

**Files:** none created; verification only.

- [ ] **Step 1: Run the entire bump test suite**

Run: `python3 -m unittest discover -s tests -p "test_bump_*.py" -v`
Expected: all tests PASS.

- [ ] **Step 2: Lint the whole surface**

Run: `ruff check deps/scripts tests`
Expected: clean (exit 0).

- [ ] **Step 3: Smoke-test the CLI dispatch for every axis**

```bash
python3 deps/scripts/bump.py ecosystem python detect
python3 deps/scripts/bump.py codeHost none alerts
python3 deps/scripts/bump.py issueTracker none issues
```
Expected: each prints valid JSON matching the documented shape; no tracebacks.

- [ ] **Step 4: Final commit (if any doc/version touch-ups)**

```bash
git add -A deps/ tests/
git commit -m "test(bump): full adapter suite green + CLI smoke" || echo "nothing to commit"
```

---

## Self-Review

**1. Spec coverage:**
- Three axes + config selection → Tasks 3, 4, 5–9. ✓
- Common JSON contract → Task 1 + Task 10 doc. ✓
- Agnostic categorizer as code → Task 2. ✓
- Config file (selection + overrides), defaults preserve zero-config → Task 3. ✓
- `none` fallbacks → Task 4 (`NONE_RESULTS`). ✓
- Advisories from two sources (ecosystem audit + Dependabot) merged → Task 11 step 5. ✓
- Behavior preservation (phase→component map) → Task 11. ✓
- Shared `bumplib` package + `sys.path` bootstrap → Tasks 1/4. ✓
- Reference/adding-adapters seam docs → Task 10. ✓
- Testing strategy (fixtures, categorizer tables, config merge, contract conformance) → Tasks 1–9, 12. ✓
- Error-handling posture preserved → Task 11 step 1 + adapters return-empty-on-missing-tool (Tasks 5–9). ✓

**2. Placeholder scan:** No "TBD/TODO/handle edge cases". Task 3's `DEFAULT_COMMANDS` explicitly instructs copying the full table from SKILL.md Phase 3/8 with the exact keys shown — that is a concrete, bounded action, not a placeholder.

**3. Type consistency:** `handle(verb, argv)` is the uniform adapter entry across Tasks 4–9. `UpdateRecord`/`Advisory`/`Context`/`Categories` field names are identical across Task 1 definition and all consumers. `classify_bump`/`glob_match`/`categorize` signatures match between Task 2 definition and Task 11 usage. `resolve_adapter`/`merged_exclusions`/`ecosystem_commands` match between Task 3 and Task 11.
