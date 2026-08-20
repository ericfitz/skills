# openapi Plugin (init + arazzo) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New `openapi` plugin with `init` (spec discovery + `.local/openapi/config.yaml` bootstrap) and `arazzo` (journeys doc → Arazzo 1.0.1 workflow spec) skills, closing #44 and #43.

**Architecture:** Two prose skills plus one Python discovery script. `find_specs.py` locates and verifies OpenAPI/Arazzo candidates (rg or a walk fallback over yaml/json only; structural parse always, external validator when present). Skills are prose-driven with human gates; guard tests pin their load-bearing sentences, unit tests pin the script.

**Tech Stack:** Python 3 (uv, PyYAML, unittest, ruff), ripgrep, Claude plugin conventions of this repo.

**Spec:** `docs/superpowers/specs/2026-08-20-openapi-arazzo-plugin-design.md`

## Global Constraints

- Emitted Arazzo version: `arazzo: 1.0.1`; default output filename `arazzo.yaml` at repo root.
- Pointer file: `.local/openapi/config.yaml` with keys `openapi_spec`, `arazzo_spec` (paths relative to repo root).
- Discovery reads only `*.yaml`, `*.yml`, `*.json` files; strong markers only.
- No coupling to the cats plugin: `.local/cats/config.yaml` may be read as a hint; cats scripts are never invoked.
- Plugin version `0.1.0`, marketplace category `development`.
- All skill frontmatter: `name` matches directory, no `version:` field.
- Validators (`vacuum`, `redocly`, `spectral`) and `rg` are optional in `requirements.json`; `uv` is required.
- Repo checks that must pass at every commit: `uv run python -m pytest tests/ -q` and `uv run ruff check .`.

---

### Task 1: find_specs.py discovery script (TDD)

**Files:**
- Create: `openapi/scripts/find_specs.py`
- Test: `tests/test_openapi_findspecs.py`

**Interfaces:**
- Produces: CLI `uv run python openapi/scripts/find_specs.py [root]` → JSON on stdout:
  `{"openapi": [{"path", "marker", "valid", "validator", "detail"}], "arazzo": [...]}`, exit 0 even when empty.
- Produces (for tests): module functions `find_candidate_files(root: Path, kind: str) -> list[Path]`, `verify(path: Path, root: Path, kind: str) -> dict`, `discover(root: Path) -> dict`, `main(argv) -> int`.

- [ ] **Step 1: Write the failing tests** — `tests/test_openapi_findspecs.py`:

```python
# tests/test_openapi_findspecs.py
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "openapi" / "scripts"))

import find_specs  # noqa: E402

MINIMAL_OPENAPI_YAML = """openapi: 3.1.0
info:
  title: t
  version: "1"
paths: {}
"""

MINIMAL_ARAZZO_YAML = """arazzo: 1.0.1
info:
  title: t
  version: "1"
sourceDescriptions:
  - name: api
    url: openapi.yaml
    type: openapi
workflows:
  - workflowId: w1
    steps:
      - stepId: s1
        operationId: op1
"""


class TempTree(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p


class TestCandidateSearch(TempTree):
    def test_finds_yaml_openapi3(self):
        self.write("api/openapi.yaml", MINIMAL_OPENAPI_YAML)
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([p.name for p in found], ["openapi.yaml"])

    def test_finds_json_openapi3(self):
        self.write("spec.json", json.dumps(
            {"openapi": "3.0.3", "info": {"title": "t", "version": "1"},
             "paths": {}}))
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([p.name for p in found], ["spec.json"])

    def test_finds_arazzo_yaml(self):
        self.write("arazzo.yaml", MINIMAL_ARAZZO_YAML)
        found = find_specs.find_candidate_files(self.root, "arazzo")
        self.assertEqual([p.name for p in found], ["arazzo.yaml"])

    def test_ignores_non_yaml_json_files(self):
        self.write("README.md", "openapi: 3.1.0\n")
        self.assertEqual(find_specs.find_candidate_files(self.root, "openapi"), [])

    def test_excluded_dirs_are_skipped(self):
        self.write("node_modules/dep/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.assertEqual(find_specs.find_candidate_files(self.root, "openapi"), [])

    @unittest.skipUnless(shutil.which("rg"), "rg not installed")
    def test_gitignored_files_skipped_with_rg(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        self.write(".gitignore", "generated/\n")
        self.write("generated/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        found = find_specs.find_candidate_files(self.root, "openapi")
        self.assertEqual([str(p.relative_to(self.root)) for p in found],
                         ["openapi.yaml"])


class TestVerify(TempTree):
    def _no_validators(self):
        # Hide vacuum/redocly/spectral so the structural branch runs.
        return patch.object(find_specs.shutil, "which", lambda name: None)

    def test_structural_accepts_minimal_openapi(self):
        p = self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertTrue(entry["valid"])
        self.assertEqual(entry["validator"], "structural")
        self.assertEqual(entry["marker"], "openapi-3.1.0")
        self.assertEqual(entry["path"], "openapi.yaml")

    def test_structural_accepts_minimal_arazzo(self):
        p = self.write("arazzo.yaml", MINIMAL_ARAZZO_YAML)
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "arazzo")
        self.assertTrue(entry["valid"])
        self.assertEqual(entry["marker"], "arazzo-1.0.1")

    def test_structural_rejects_marker_without_structure(self):
        # e.g. a dependency pin that matched the grep marker
        p = self.write("deps.json", json.dumps({"openapi": "3.1.0"}))
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertFalse(entry["valid"])
        self.assertEqual(entry["validator"], "structural")

    def test_unparseable_candidate_is_invalid_not_fatal(self):
        p = self.write("bad.yaml", "openapi: 3.1.0\n\t: {broken")
        with self._no_validators():
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertFalse(entry["valid"])
        self.assertIn("parse", entry["detail"])

    def test_external_validator_verdict_wins(self):
        p = self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        bindir = self.root / "bin"
        bindir.mkdir()
        stub = bindir / "vacuum"
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
        with patch.dict(os.environ, {"PATH": str(bindir)}):
            entry = find_specs.verify(p, self.root, "openapi")
        self.assertEqual(entry["validator"], "vacuum")
        self.assertFalse(entry["valid"])


class TestDiscoverAndMain(TempTree):
    def test_ordering_valid_first_then_shallow(self):
        self.write("deep/nested/openapi.yaml", MINIMAL_OPENAPI_YAML)
        self.write("openapi.json", json.dumps({"openapi": "3.0.0"}))  # invalid
        self.write("openapi.yaml", MINIMAL_OPENAPI_YAML)
        with patch.object(find_specs.shutil, "which", lambda name: None):
            result = find_specs.discover(self.root)
        paths = [e["path"] for e in result["openapi"]]
        self.assertEqual(paths, ["openapi.yaml", str(Path("deep/nested/openapi.yaml")),
                                 "openapi.json"])

    def test_empty_tree_exits_zero_with_empty_lists(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "openapi" / "scripts" / "find_specs.py"),
             str(self.root)],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)
        self.assertEqual(data, {"openapi": [], "arazzo": []})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests, verify they fail** — `uv run python -m pytest tests/test_openapi_findspecs.py -q` → collection error: `ModuleNotFoundError: find_specs`.

- [ ] **Step 3: Implement** — `openapi/scripts/find_specs.py`:

```python
#!/usr/bin/env python3
"""Locate OpenAPI and Arazzo spec documents in a repository.

Searches only *.yaml/*.yml/*.json files for markers that strongly indicate a
real spec document — via ripgrep when available (which honors .gitignore in a
git repo), else a directory walk with a fixed exclude list. Each candidate is
verified: structural parse first (rules out grep false positives), then an
external validator (vacuum, redocly, spectral) when one is on PATH and
supports the document kind. Prints JSON findings to stdout; an empty result
is data, not an error.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

GLOBS = ("*.yaml", "*.yml", "*.json")
EXCLUDE_DIRS = {".git", "node_modules", "vendor", ".venv", "venv",
                "dist", "build", "target"}

# kind -> regexes a real spec's version line would match (line-anchored for
# YAML, key-quoted for JSON). Content-level check happens in verify().
MARKERS = {
    "openapi": [r'^\s*openapi:\s*["\']?3', r'"openapi"\s*:\s*"3',
                r'^\s*swagger:\s*["\']?2\.0', r'"swagger"\s*:\s*"2\.0"'],
    "arazzo": [r'^\s*arazzo:\s*["\']?1', r'"arazzo"\s*:\s*"1'],
}

# name, kinds it can judge, argv builder. First installed match wins.
VALIDATORS = (
    ("vacuum", ("openapi",), lambda p: ["vacuum", "lint", str(p)]),
    ("redocly", ("openapi", "arazzo"), lambda p: ["redocly", "lint", str(p)]),
    ("spectral", ("openapi",), lambda p: ["spectral", "lint", str(p)]),
)


def _rg_candidates(root, kind):
    cmd = ["rg", "-l", "--no-messages"]
    for g in GLOBS:
        cmd += ["-g", g]
    for d in EXCLUDE_DIRS:
        cmd += ["-g", f"!**/{d}/**"]
    for pattern in MARKERS[kind]:
        cmd += ["-e", pattern]
    proc = subprocess.run(cmd + [str(root)], capture_output=True, text=True)
    # rg exits 1 on "no matches", which is not an error here.
    return [Path(line) for line in proc.stdout.splitlines() if line.strip()]


def _walk_candidates(root, kind):
    regexes = [re.compile(p, re.M) for p in MARKERS[kind]]
    found = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not any(path.match(g) for g in GLOBS):
            continue
        if EXCLUDE_DIRS.intersection(path.relative_to(root).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(r.search(text) for r in regexes):
            found.append(path)
    return found


def find_candidate_files(root, kind):
    root = Path(root)
    if shutil.which("rg"):
        return _rg_candidates(root, kind)
    return _walk_candidates(root, kind)


def _structural(doc, kind):
    """Return (marker, ok, detail)."""
    if not isinstance(doc, dict):
        return "unknown", False, "document is not a mapping"
    if kind == "openapi":
        version = doc.get("openapi") or doc.get("swagger")
        label = ("swagger" if "swagger" in doc and "openapi" not in doc
                 else "openapi")
        if not version:
            return "unknown", False, "no openapi/swagger version field"
        marker = f"{label}-{version}"
        if "info" not in doc:
            return marker, False, "missing top-level info"
        if not any(k in doc for k in ("paths", "webhooks", "components")):
            return marker, False, "missing paths/webhooks/components"
        return marker, True, "structural checks passed"
    version = doc.get("arazzo")
    if not version:
        return "unknown", False, "no arazzo version field"
    marker = f"arazzo-{version}"
    if "info" not in doc:
        return marker, False, "missing top-level info"
    if "workflows" not in doc:
        return marker, False, "missing workflows"
    return marker, True, "structural checks passed"


def _external_validator(path, kind):
    for name, kinds, build in VALIDATORS:
        if kind in kinds and shutil.which(name):
            try:
                proc = subprocess.run(build(path), capture_output=True,
                                      text=True, timeout=60)
            except (subprocess.TimeoutExpired, OSError) as exc:
                return name, None, f"{name} failed to run: {exc}"
            detail = (proc.stdout + proc.stderr).strip().splitlines()
            return name, proc.returncode == 0, (detail[0] if detail else "")
    return None, None, ""


def verify(path, root, kind):
    entry = {"path": str(Path(path).resolve().relative_to(Path(root).resolve())),
             "marker": "unknown", "valid": False,
             "validator": "structural", "detail": ""}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        doc = (json.loads(text) if str(path).endswith(".json")
               else yaml.safe_load(text))
    except (ValueError, yaml.YAMLError) as exc:
        entry["detail"] = f"parse error: {exc}".splitlines()[0]
        return entry
    marker, ok, detail = _structural(doc, kind)
    entry.update(marker=marker, valid=ok, detail=detail)
    if ok:
        name, verdict, vdetail = _external_validator(path, kind)
        if verdict is not None:
            entry.update(validator=name, valid=verdict,
                         detail=vdetail or detail)
    return entry


def discover(root):
    root = Path(root)
    result = {}
    for kind in ("openapi", "arazzo"):
        entries = [verify(p, root, kind)
                   for p in find_candidate_files(root, kind)]
        entries.sort(key=lambda e: (not e["valid"],
                                    len(Path(e["path"]).parts), e["path"]))
        result[kind] = entries
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".",
                        help="repository root to search (default: .)")
    args = parser.parse_args(argv)
    print(json.dumps(discover(Path(args.root)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify green** — `uv run python -m pytest tests/test_openapi_findspecs.py -q` → all pass. Then `uv run ruff check .`.

- [ ] **Step 5: Commit** — `git add openapi/scripts/find_specs.py tests/test_openapi_findspecs.py && git commit -m "feat(openapi): spec discovery script with structural + external verification (#44)"`

---

### Task 2: openapi:init skill (guard tests first)

**Files:**
- Create: `openapi/skills/init/SKILL.md`
- Test: `tests/test_openapi_coupling.py` (new file, init guards only)

**Interfaces:**
- Consumes: `${CLAUDE_PLUGIN_ROOT}/scripts/find_specs.py` from Task 1.
- Produces: `.local/openapi/config.yaml` contract (`openapi_spec`, `arazzo_spec`) that Task 3's skill reads.

- [ ] **Step 1: Write failing guard tests** — `tests/test_openapi_coupling.py`:

```python
# tests/test_openapi_coupling.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
INIT = REPO / "openapi" / "skills" / "init" / "SKILL.md"
ARAZZO = REPO / "openapi" / "skills" / "arazzo" / "SKILL.md"


class TestInitSkill(unittest.TestCase):
    def test_init_documents_the_pointer_file_and_idempotence(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".local/openapi/config.yaml", text)
        self.assertIn("openapi_spec", text)
        self.assertIn("arazzo_spec", text)
        # exists -> print and stop
        self.assertIn("already exists", text)

    def test_init_runs_the_discovery_script_and_offers_three_choices(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/find_specs.py", text)
        lower = text.lower()
        self.assertIn("accept", lower)
        self.assertIn("type a path", lower)
        self.assertIn("cancel", lower)

    def test_init_never_finishes_without_a_verified_spec(self):
        lower = INIT.read_text(encoding="utf-8").lower()
        self.assertIn("never finish without", lower)

    def test_init_handles_gitignore_and_offers_apis_yaml(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".gitignore", text)
        self.assertIn("apis.yaml", text)

    def test_init_reads_cats_config_as_hint_only(self):
        text = INIT.read_text(encoding="utf-8")
        self.assertIn(".local/cats/config.yaml", text)
        self.assertNotIn("cats_tool.py", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run, verify failure** — FileNotFoundError on `INIT.read_text` (skill missing).

- [ ] **Step 3: Write** `openapi/skills/init/SKILL.md` (full content in spec §"Skill: openapi:init"; frontmatter `name: init`, description covering triggers "set up openapi config", "locate the project's OpenAPI spec", "when .local/openapi/config.yaml is missing"). Must contain, verbatim where quoted by tests: the config example, "already exists" idempotence sentence, the `uv run python ${CLAUDE_PLUGIN_ROOT}/scripts/find_specs.py [path]` invocation, the accept / type a path / cancel menu, "Never finish without an existing, verified OpenAPI spec file", the `.gitignore` ensure step, the cats-config hint sentence, and the `apis.yaml` offer with this template:

```yaml
name: <project name>
type: Index
apis:
  - name: <project name> API
    properties:
      - type: OpenAPI
        url: <openapi_spec path>
      - type: Arazzo
        url: <arazzo_spec path>
```

- [ ] **Step 4: Run tests green** — `uv run python -m pytest tests/test_openapi_coupling.py -q` (arazzo class not yet present; only init tests exist at this point).

- [ ] **Step 5: Commit** — `git add openapi/skills/init/SKILL.md tests/test_openapi_coupling.py && git commit -m "feat(openapi): init skill bootstraps .local/openapi/config.yaml (#44)"`

---

### Task 3: openapi:arazzo skill + authoring reference (guard tests first)

**Files:**
- Create: `openapi/skills/arazzo/SKILL.md`, `openapi/references/arazzo-authoring.md`
- Modify: `tests/test_openapi_coupling.py` (add arazzo guards)

**Interfaces:**
- Consumes: `.local/openapi/config.yaml` (Task 2), `docs/journeys.md` (itest:design, shipped in #45).
- Produces: `arazzo.yaml` (Arazzo 1.0.1) in target repos.

- [ ] **Step 1: Add failing guard tests** to `tests/test_openapi_coupling.py`:

```python
class TestArazzoSkill(unittest.TestCase):
    def test_arazzo_preflight_offers_to_run_init_and_itest_design(self):
        text = ARAZZO.read_text(encoding="utf-8")
        self.assertIn("/openapi:init", text)
        self.assertIn("/itest:design", text)
        self.assertIn("offer", text.lower())

    def test_arazzo_reads_the_journeys_doc_itest_emits(self):
        # Cross-plugin consistency: same well-known path itest:design writes.
        arazzo = ARAZZO.read_text(encoding="utf-8")
        itest = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8")
        self.assertIn("docs/journeys.md", arazzo)
        self.assertIn("docs/journeys.md", itest)

    def test_arazzo_documents_gate_version_and_overwrite_protection(self):
        text = ARAZZO.read_text(encoding="utf-8")
        lower = text.lower()
        self.assertIn("gate", lower)
        self.assertIn("arazzo: 1.0.1", text)
        self.assertIn("arazzo.yaml", text)
        self.assertIn("overwrit", lower)

    def test_arazzo_flags_non_api_journeys_instead_of_forcing(self):
        lower = ARAZZO.read_text(encoding="utf-8").lower()
        self.assertIn("not api-shaped", lower)

    def test_arazzo_reports_when_no_external_validator_ran(self):
        lower = ARAZZO.read_text(encoding="utf-8").lower()
        self.assertIn("no external validator", lower)

    def test_arazzo_references_resolve_inside_the_plugin(self):
        import re
        for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)",
                              ARAZZO.read_text(encoding="utf-8")):
            self.assertNotIn("..", ref)
            self.assertTrue((REPO / "openapi" / ref.lstrip("/")).exists())
```

- [ ] **Step 2: Run, verify failure** (ARAZZO missing).

- [ ] **Step 3: Write the skill and reference.** `arazzo/SKILL.md` implements spec §"Skill: openapi:arazzo" — preflight offers (`/openapi:init` when config missing, `/itest:design` when journeys doc missing, stop only on decline/cancel), contract-block parse with prose fallback, mapping rules (workflowId from journey id sanitized to `[A-Za-z0-9_\-]+`; `dependsOn` from `depends_on`; steps bound to `operationId`/`operationPath`; `$steps.<id>.outputs.*` chaining; declared-2xx `successCriteria`; journeys that are not API-shaped are flagged and skipped, never force-mapped), the human gate table, emission (`arazzo: 1.0.1` header, configured path default `arazzo.yaml`, sourceDescriptions by relative path, ask-before-overwrite with change summary), post-emission validation (redocly/spectral/vacuum if present, else structural self-check and state explicitly that "no external validator" ran), and the apis.yaml update offer. Reference `${CLAUDE_PLUGIN_ROOT}/references/arazzo-authoring.md`.

  `references/arazzo-authoring.md` is a one-page Arazzo 1.0 cheat sheet: document skeleton (`arazzo`, `info`, `sourceDescriptions[{name,url,type: openapi}]`, `workflows`), workflow fields (`workflowId`, `summary`, `description`, `inputs`, `dependsOn`, `steps`, `outputs`), step fields (`stepId`, `operationId` or `operationPath`, `parameters[{name,in,value}]`, `requestBody{contentType,payload}`, `successCriteria[{condition}]`, `outputs`), runtime expressions (`$statusCode`, `$response.body#/ptr`, `$steps.<id>.outputs.<name>`, `$inputs.<name>`, `$sourceDescriptions.<name>.url`), plus the mapping doctrine restated with one worked journey→workflow example.

- [ ] **Step 4: Run green** — `uv run python -m pytest tests/test_openapi_coupling.py -q`.

- [ ] **Step 5: Commit** — `git add openapi/skills/arazzo openapi/references tests/test_openapi_coupling.py && git commit -m "feat(openapi): arazzo skill maps confirmed journeys onto the OpenAPI spec (#44)"`

---

### Task 4: Plugin wiring — manifests, requirements, marketplace, codex

**Files:**
- Create: `openapi/.claude-plugin/plugin.json`, `openapi/requirements.json`
- Modify: `.claude-plugin/marketplace.json` (add openapi entry, category `development`)
- Generated: `openapi/.codex-plugin/plugin.json`, `.agents/plugins/marketplace.json` via `uv run python scripts/gen_codex_manifests.py`

**Interfaces:**
- Consumes: skills from Tasks 2–3 (codex generation requires `skills/` to exist).
- Produces: registered plugin `openapi` v0.1.0 discoverable by the generic structure/env/codex suites.

- [ ] **Step 1: RED via the generic suites** — create `openapi/.claude-plugin/plugin.json`:

```json
{
  "name": "openapi",
  "version": "0.1.0",
  "description": "OpenAPI workflow toolkit: locate and record the project's OpenAPI and Arazzo specs (init), and generate an Arazzo 1.0 workflow spec from the confirmed customer-journeys doc mapped onto real operations (arazzo). Prose-driven with human gates; validators used when installed.",
  "author": { "name": "efitz" }
}
```

  Run `uv run python -m pytest tests/test_plugin_structure.py tests/test_codex_manifests.py -q` → FAIL (unregistered in marketplace, codex manifest missing).

- [ ] **Step 2: GREEN** — add the marketplace entry (same description) to `.claude-plugin/marketplace.json`; write `openapi/requirements.json`:

```json
{
  "requirements_version": "1.0.0",
  "plugin": "openapi",
  "tools": [
    {
      "name": "uv",
      "required": true,
      "why": "init runs scripts/find_specs.py via `uv run`",
      "probe": ["uv", "--version"],
      "install": { "macos": "brew install uv", "docs": "https://docs.astral.sh/uv/getting-started/installation/" }
    },
    {
      "name": "rg",
      "required": false,
      "why": "spec discovery prefers ripgrep (honors .gitignore); a built-in walk fallback covers its absence",
      "probe": ["rg", "--version"],
      "install": { "macos": "brew install ripgrep", "docs": "https://github.com/BurntSushi/ripgrep" }
    },
    {
      "name": "vacuum",
      "required": false,
      "why": "preferred external validator for OpenAPI candidates and emitted specs",
      "probe": ["vacuum", "version"],
      "install": { "macos": "brew install daveshanley/vacuum/vacuum", "docs": "https://quobix.com/vacuum/" }
    },
    {
      "name": "redocly",
      "required": false,
      "why": "validator for OpenAPI and Arazzo documents when vacuum is absent",
      "probe": ["redocly", "--version"],
      "install": { "macos": "npm i -g @redocly/cli", "docs": "https://redocly.com/docs/cli/" }
    },
    {
      "name": "spectral",
      "required": false,
      "why": "fallback OpenAPI linter",
      "probe": ["spectral", "--version"],
      "install": { "macos": "npm i -g @stoplight/spectral-cli", "docs": "https://github.com/stoplightio/spectral" }
    }
  ],
  "config": [
    {
      "path": ".local/openapi/config.yaml",
      "scope": "repo",
      "required": false,
      "why": "arazzo reads openapi_spec/arazzo_spec paths from it; init creates it and offers to run when missing",
      "remedy": "run /openapi:init in the target repo"
    }
  ]
}
```

  Then `uv run python scripts/gen_codex_manifests.py`.

- [ ] **Step 3: Full suite + lint green** — `uv run python -m pytest tests/ -q && uv run ruff check .`

- [ ] **Step 4: Commit** — `git add openapi/.claude-plugin openapi/.codex-plugin openapi/requirements.json .claude-plugin/marketplace.json .agents/plugins/marketplace.json && git commit -m "feat(openapi): register openapi plugin v0.1.0 (#43, #44)"`

---

### Task 5: Integrate and close issues

**Files:** none new.

- [ ] **Step 1:** Full verification once more on the final tree: `uv run python -m pytest tests/ -q && uv run ruff check .`
- [ ] **Step 2:** Squash-or-keep per session flow: work is on a feature branch `feat/44-openapi-plugin`; merge to `main` (this session's established pattern), push.
- [ ] **Step 3:** `gh issue comment 43` recording the decision (standalone openapi plugin; CATS stays in its own plugin) and `gh issue close 43`. #44 closes via `Closes #44` in the final commit if merged to main pushed; otherwise close explicitly with a comment naming the commit.
