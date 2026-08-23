# dependency-model Layer 2 (Synthesis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two skills that join layer 1's six discovery contracts into one `synthesis` contract — merged inventory, typed dependency graph, per-service health definitions — and render it as a Mermaid report; plus the `lifecycle` amendment layer 1 needs to support it.

**Architecture:** `synthesize` gathers the six envelopes, hands the mechanical half to `depgraph.py` (key-union merge, typed edges, cycle detection, Mermaid emission), and applies LLM judgment only to health conditions. `report` renders the resulting contract. A separate layer-1 script, `pkglifecycle.py`, derives build-vs-run for packages because syft cannot.

**Tech Stack:** Python 3.11+ stdlib only (`tomllib` for TOML), `uv run --script` with `python3` fallback, `unittest`/`pytest`, `ruff`, Mermaid via `mmdc` (optional).

**Spec:** `docs/superpowers/specs/2026-08-22-dependency-synthesis-design.md`

## Global Constraints

- **No version numbers move.** `contract_version` stays `1.0.0`; `plugin.json` stays `0.1.0`. Versions advance only when the user declares the feature productionized. Do not propose or make a bump.
- **`lifecycle` has exactly two values: `build` and `run`.** No `both`, ever. The build environment is a strict superset of the runtime environment — a runtime dependency is present at build *because* it is a runtime dependency.
- **Health is filtered by failability, not by lifecycle or category.** A dependency enters a health definition iff a condition can be *stated* about it with evidence. Bundled libraries produce none and self-exclude; a dynamically loaded package produces a `presence` condition citing its loading site.
- **No `healthy`/`degraded`/`unhealthy` enum in any schema.** The taxonomy lives in prose in `references/definitions.md` only.
- **`null` means "no declaration was found"** — never "confirmed absent", never "not needed".
- **No criticality, ranking, scores, or blast radius** on dependencies or edges. `required_for` records *which* function needs a dependency, never how much it matters.
- **Read-only and static.** Nothing is executed against the target system, nothing measured. Every bound is a declared one.
- **`depgraphlib` and `pkglifecycle.py` are stdlib-only.** Both run under bare `python3`; scripts declare `dependencies = []`.
- **Skills invoke skills by name**, never by path. No skill mentions `profile/scripts/`.
- Repo checks that must pass before every commit:

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
REPO="$(pwd)" bash scripts/verify-marketplace.sh
```

### Verified facts you can rely on (measured, not assumed)

- **syft cannot distinguish dev from runtime.** Python/uv reports `pyyaml` (runtime) and `pytest`/`ruff` (dev) from `/uv.lock` with identical `metadataType` and metadata keys. npm **silently drops** `devDependencies` from the catalogue entirely. Measured with syft 1.51.0 on 2026-08-22.
- **syft edge direction:** in `artifactRelationships`, `{parent: A, child: B, type: "dependency-of"}` means **A is a dependency of B**. To walk from a root to what it pulls in, follow edges where `child` is the current node and take `parent`. Confirmed: `pytest` appears as `child` on 5 edges (its own deps) and as `parent` on none.
- **Mermaid label escaping:** a raw `"` in a quoted label **breaks parsing**; `#quot;` is the working escape. `#`, `<`, `>`, and `;` are all fine unescaped. Opaque node ids (`n0`, `n1`, …) with the real name in a quoted label renders correctly for `@babel/core`, `github.com/sony/gobreaker`, `x[1]`, and `a b (c)`. Verified with `mmdc`.
- `tomllib` is stdlib from Python 3.11, so TOML parsing costs no dependency.

### Existing tests that WILL break — each has a task that fixes it

- `tests/test_dependency_model_contracts.py:57-60` asserts an exact list of schema filenames. Adding `synthesis.schema.json` breaks it (Task 5).
- `tests/test_dependency_model_coupling.py:13,23` asserts the skill directory listing equals exactly the six categories. Adding `report` and `synthesize` breaks it (Task 11).
- The coupling tests iterate **all** skills for per-category assertions ("names its own `<category>.schema.json`"). `report` and `synthesize` have no per-category contract, so those tests must be split into category-scoped and all-skill-scoped groups (Task 11).
- `scripts/verify-marketplace.sh:57` lists the plugin's skills; it becomes `config,network,package,platform,report,security,service,synthesize` (Task 11).

---

### Task 1: `pkglifecycle.py` — derive build-vs-run for packages

syft cannot answer this (see verified facts). This script reads the declaring manifest to classify roots, then propagates to transitives over syft's `dependency-of` edges.

**Files:**
- Create: `dependency-model/scripts/pkglifecycle.py`
- Test: `tests/test_pkglifecycle.py`

**Interfaces:**
- Produces: `classify_roots(root: Path) -> dict[str, str]` — maps lowercased package name to `"build"` or `"run"`, from every manifest found. Unknown ecosystems contribute nothing.
- Produces: `propagate(roots: dict[str,str], artifacts: list[dict], relationships: list[dict]) -> dict[str,str]` — maps syft artifact **id** to `"build"` or `"run"`.
- Produces: `unresolved_ecosystems(root: Path) -> list[str]` — ecosystems present but unparseable, for the assumption each skill records.
- Produces: CLI `uv run --script pkglifecycle.py <repo> --syft-json <file>` → JSON `{"lifecycle": {artifact_id: "build"|"run"}, "unresolved": [...]}`.
- Consumed by: Task 3 (the `package` skill invokes it).

- [ ] **Step 1: Write the failing test**

Create `tests/test_pkglifecycle.py`:

```python
# tests/test_pkglifecycle.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pkglifecycle
from repobuilder import build_repo

PYPROJECT = """\
[project]
name = "x"
dependencies = ["pyyaml>=6.0", "requests"]

[project.optional-dependencies]
extra = ["rich"]

[dependency-groups]
dev = ["pytest>=8.0", "ruff>=0.12"]
"""

PACKAGE_JSON = """\
{"name": "x", "version": "1.0.0",
 "dependencies": {"left-pad": "1.3.0"},
 "devDependencies": {"is-odd": "3.0.1"}}
"""

CARGO = """\
[package]
name = "x"

[dependencies]
serde = "1"

[dev-dependencies]
criterion = "0.5"
"""

GO_MOD = """\
module example.com/x

go 1.23

require github.com/jackc/pgx/v5 v5.5.0
"""


class TestClassifyRoots(unittest.TestCase):
    def test_pyproject_splits_project_from_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": PYPROJECT})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["pyyaml"], "run")
            self.assertEqual(roots["requests"], "run")
            self.assertEqual(roots["pytest"], "build")
            self.assertEqual(roots["ruff"], "build")

    def test_optional_dependencies_are_run(self):
        """An extra ships when selected; it is not a dev tool."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": PYPROJECT})
            self.assertEqual(pkglifecycle.classify_roots(Path(root))["rich"], "run")

    def test_package_json_splits_dependencies_from_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"package.json": PACKAGE_JSON})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["left-pad"], "run")
            self.assertEqual(roots["is-odd"], "build")

    def test_cargo_splits_dependencies_from_dev(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"Cargo.toml": CARGO})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["serde"], "run")
            self.assertEqual(roots["criterion"], "build")

    def test_go_mod_has_no_dev_concept_so_all_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": GO_MOD})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["github.com/jackc/pgx/v5"], "run")

    def test_version_specifiers_are_stripped_from_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": PYPROJECT})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertIn("pyyaml", roots)
            self.assertNotIn("pyyaml>=6.0", roots)

    def test_malformed_manifest_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": "[project\nbroken"})
            self.assertEqual(pkglifecycle.classify_roots(Path(root)), {})


class TestPropagate(unittest.TestCase):
    """Edge direction is load-bearing: {parent: A, child: B} means A is a
    dependency of B. Inverting it inverts every classification silently."""

    ARTIFACTS = [
        {"id": "a1", "name": "pytest"},
        {"id": "a2", "name": "pluggy"},
        {"id": "a3", "name": "pyyaml"},
        {"id": "a4", "name": "shared"},
    ]
    # pluggy is a dependency of pytest; shared is a dependency of pyyaml
    RELS = [
        {"parent": "a2", "child": "a1", "type": "dependency-of"},
        {"parent": "a4", "child": "a3", "type": "dependency-of"},
    ]

    def test_transitive_of_a_build_root_is_build(self):
        out = pkglifecycle.propagate({"pytest": "build", "pyyaml": "run"},
                                     self.ARTIFACTS, self.RELS)
        self.assertEqual(out["a2"], "build")

    def test_transitive_of_a_run_root_is_run(self):
        out = pkglifecycle.propagate({"pytest": "build", "pyyaml": "run"},
                                     self.ARTIFACTS, self.RELS)
        self.assertEqual(out["a4"], "run")

    def test_run_wins_when_reachable_from_both(self):
        """A package pulled in by both a dev tool and the app ships."""
        rels = self.RELS + [{"parent": "a2", "child": "a3", "type": "dependency-of"}]
        out = pkglifecycle.propagate({"pytest": "build", "pyyaml": "run"},
                                     self.ARTIFACTS, rels)
        self.assertEqual(out["a2"], "run")

    def test_roots_keep_their_own_classification(self):
        out = pkglifecycle.propagate({"pytest": "build", "pyyaml": "run"},
                                     self.ARTIFACTS, self.RELS)
        self.assertEqual(out["a1"], "build")
        self.assertEqual(out["a3"], "run")

    def test_unreachable_artifact_defaults_to_run(self):
        """A package syft found that no manifest declares is, absent evidence,
        installed. Guessing build would understate the runtime surface."""
        arts = self.ARTIFACTS + [{"id": "a9", "name": "mystery"}]
        out = pkglifecycle.propagate({"pytest": "build"}, arts, self.RELS)
        self.assertEqual(out["a9"], "run")

    def test_non_dependency_of_relationships_are_ignored(self):
        rels = [{"parent": "a2", "child": "a1", "type": "contains"}]
        out = pkglifecycle.propagate({"pytest": "build"}, self.ARTIFACTS, rels)
        self.assertEqual(out["a2"], "run")

    def test_a_cycle_terminates(self):
        rels = [{"parent": "a1", "child": "a2", "type": "dependency-of"},
                {"parent": "a2", "child": "a1", "type": "dependency-of"}]
        out = pkglifecycle.propagate({"pytest": "build"}, self.ARTIFACTS, rels)
        self.assertEqual(out["a1"], "build")


class TestCli(unittest.TestCase):
    def test_emits_lifecycle_and_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": PYPROJECT})
            syft = Path(tmp) / "syft.json"
            syft.write_text(json.dumps({
                "artifacts": [{"id": "a1", "name": "pytest"},
                              {"id": "a3", "name": "pyyaml"}],
                "artifactRelationships": [],
            }), encoding="utf-8")
            rc = pkglifecycle.main([str(root), "--syft-json", str(syft)])
            self.assertEqual(rc, 0)

    def test_returns_2_when_syft_json_is_unreadable(self):
        self.assertEqual(pkglifecycle.main(["/tmp", "--syft-json", "/no/such"]), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_pkglifecycle.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'pkglifecycle'`.

- [ ] **Step 3: Implement `pkglifecycle.py`**

Create `dependency-model/scripts/pkglifecycle.py`:

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Derive build-vs-run lifecycle for packages that syft cannot classify.

syft does not distinguish dev from runtime dependencies, and it fails
differently per ecosystem: Python/uv reports both from one lockfile with
identical metadata, while npm silently drops devDependencies entirely.

So classify declared roots from the manifest, then propagate to transitives
over syft's dependency-of edges.

Usage:
    uv run --script pkglifecycle.py <repo> --syft-json <file>
    python3 pkglifecycle.py <repo> --syft-json <file>   # fallback; no deps

Exit codes:
    0  emitted
    2  repo path or syft JSON unusable
"""

import argparse
import json
import re
import sys
import tomllib
from collections import deque
from pathlib import Path

BUILD, RUN = "build", "run"

# Strip everything from the first specifier character on: "pyyaml>=6.0" -> "pyyaml",
# "requests[socks]" -> "requests". Names themselves never contain these.
_SPECIFIER = re.compile(r"[<>=!~\[\s;].*$")


def _name(raw):
    return _SPECIFIER.sub("", str(raw)).strip().lower()


def _load_toml(path):
    try:
        with open(path, "rb") as handle:
            return tomllib.load(handle)
    except (OSError, ValueError):
        return None


def _pyproject(path, out):
    data = _load_toml(path)
    if not data:
        return
    project = data.get("project") or {}
    for dep in project.get("dependencies") or []:
        out[_name(dep)] = RUN
    # An extra ships when selected; it is not a dev tool.
    for deps in (project.get("optional-dependencies") or {}).values():
        for dep in deps:
            out.setdefault(_name(dep), RUN)
    for deps in (data.get("dependency-groups") or {}).values():
        for dep in deps:
            out.setdefault(_name(dep), BUILD)


def _package_json(path, out):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for dep in (data.get("dependencies") or {}):
        out[_name(dep)] = RUN
    for dep in (data.get("devDependencies") or {}):
        out.setdefault(_name(dep), BUILD)


def _cargo(path, out):
    data = _load_toml(path)
    if not data:
        return
    for dep in (data.get("dependencies") or {}):
        out[_name(dep)] = RUN
    for dep in (data.get("dev-dependencies") or {}):
        out.setdefault(_name(dep), BUILD)


_GO_REQUIRE = re.compile(r"^\s*(?:require\s+)?([a-z0-9][\w.\-/]*\.[\w.\-/]+)\s+v\S+",
                         re.IGNORECASE)


def _go_mod(path, out):
    # Go has no dev-dependency concept: everything required is a run dependency.
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        match = _GO_REQUIRE.match(line)
        if match:
            out[_name(match.group(1))] = RUN


MANIFESTS = {
    "pyproject.toml": _pyproject,
    "package.json": _package_json,
    "Cargo.toml": _cargo,
    "go.mod": _go_mod,
}

# Ecosystems we can detect but not classify. Their presence becomes an
# assumption rather than a silent gap.
UNPARSEABLE = {
    "Gemfile": "ruby", "composer.json": "php", "pom.xml": "java",
    "build.gradle": "java", "build.gradle.kts": "java",
}

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "vendor", "dist",
             "build", "target", "site-packages", "__pycache__"}


def _walk(root):
    for path in Path(root).rglob("*"):
        if path.is_file() and not any(p in SKIP_DIRS for p in path.parts):
            yield path


def classify_roots(root):
    """Return {lowercased package name: build|run} from every manifest found."""
    out = {}
    for path in sorted(_walk(root)):
        handler = MANIFESTS.get(path.name)
        if handler:
            handler(path, out)
    return out


def unresolved_ecosystems(root):
    """Ecosystems present but not classifiable, for an assumption record."""
    found = {UNPARSEABLE[p.name] for p in _walk(root) if p.name in UNPARSEABLE}
    return sorted(found)


def propagate(roots, artifacts, relationships):
    """Map syft artifact id to build|run.

    A dependency-of edge {parent: A, child: B} means A is a dependency of B, so
    walking outward from a root follows edges where child is the current node.
    run wins over build: a package pulled in by both a dev tool and the app ships.
    """
    by_id = {a["id"]: str(a.get("name", "")).lower() for a in artifacts}
    children_of = {}
    for rel in relationships:
        if rel.get("type") != "dependency-of":
            continue
        children_of.setdefault(rel["child"], []).append(rel["parent"])

    out = {}
    for lifecycle in (BUILD, RUN):  # run second so it overwrites build
        seeds = [i for i, name in by_id.items() if roots.get(name) == lifecycle]
        seen, queue = set(seeds), deque(seeds)
        while queue:
            node = queue.popleft()
            out[node] = lifecycle
            for nxt in children_of.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)

    for artifact_id in by_id:
        out.setdefault(artifact_id, RUN)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pkglifecycle.py",
        description="Derive build-vs-run lifecycle for syft-catalogued packages.")
    parser.add_argument("path", help="repo root")
    parser.add_argument("--syft-json", required=True, help="syft-json output file")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": f"not a directory: {args.path}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2
    try:
        syft = json.loads(Path(args.syft_json).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        json.dump({"error": f"cannot read syft json: {exc}"}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    lifecycle = propagate(classify_roots(root),
                          syft.get("artifacts") or [],
                          syft.get("artifactRelationships") or [])
    indent = args.indent if args.indent > 0 else None
    print(json.dumps({"lifecycle": lifecycle,
                      "unresolved": unresolved_ecosystems(root)},
                     indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable: `chmod +x dependency-model/scripts/pkglifecycle.py`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_pkglifecycle.py -q`
Expected: PASS.

- [ ] **Step 5: Verify against this repo end to end**

```bash
syft scan dir:. -o syft-json --quiet --exclude '**/.venv' --exclude '**/node_modules' --exclude '**/site-packages' > /tmp/s.json
uv run --script dependency-model/scripts/pkglifecycle.py . --syft-json /tmp/s.json | python3 -c "
import json,sys
d=json.load(sys.stdin)['lifecycle']
from collections import Counter
print(Counter(d.values()))
"
```
Expected: both `build` and `run` present. This repo declares `pyyaml` as a run root and `pytest`/`ruff` as build roots, so a result with zero `build` entries means the manifest classification silently failed — investigate rather than accepting it.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run pytest -q
git add dependency-model/scripts/pkglifecycle.py tests/test_pkglifecycle.py
git commit -m "feat(dependency-model): derive package build-vs-run lifecycle (#49)"
```

---

### Task 2: `lifecycle` on the layer-1 contract

**Files:**
- Modify: `dependency-model/references/contracts/dependency-core.schema.json`
- Modify: all six `dependency-model/references/contracts/examples/*.example.json`
- Modify: `tests/test_dependency_model_contracts.py`

**Interfaces:**
- Produces: `lifecycle` as a required property of every dependency, enum `["build", "run"]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dependency_model_contracts.py`:

```python
class TestLifecycle(unittest.TestCase):
    """Two values only. The build environment is a strict superset of the
    runtime environment, so a runtime dependency is present at build BECAUSE
    it is a runtime dependency -- `both` would record the containment twice."""

    def test_core_requires_lifecycle_with_exactly_two_values(self):
        core = load(CONTRACTS / "dependency-core.schema.json")
        self.assertIn("lifecycle", core["required"])
        self.assertEqual(core["properties"]["lifecycle"]["enum"], ["build", "run"])

    def test_no_schema_admits_a_both_value(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            with self.subTest(schema=path.name):
                self.assertNotIn('"both"', path.read_text(encoding="utf-8"))

    def test_every_example_dependency_declares_lifecycle(self):
        for category in CATEGORIES:
            instance = load(EXAMPLES / f"{category}.example.json")
            for dep in instance["categories"][category]["dependencies"]:
                with self.subTest(category=category, dep=dep["id"]):
                    self.assertIn(dep["lifecycle"], ("build", "run"))

    def test_package_example_is_build_and_service_example_is_run(self):
        pkg = load(EXAMPLES / "package.example.json")
        self.assertEqual(
            pkg["categories"]["package"]["dependencies"][0]["lifecycle"], "build")
        svc = load(EXAMPLES / "service.example.json")
        self.assertEqual(
            svc["categories"]["service"]["dependencies"][0]["lifecycle"], "run")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: FAIL — `lifecycle` is not in `required`.

- [ ] **Step 3: Add the field to the core schema**

In `dependency-core.schema.json`, add `"lifecycle"` to `required`, and add this property alongside `id`/`name`:

```json
"lifecycle": {
  "enum": ["build", "run"],
  "description": "Which environment must contain this dependency. run: shipped in the runtime artifact (npm dependencies). build: needed only to build and test, absent at runtime (npm devDependencies). The build environment is a strict superset of the runtime one, so there is no third value. This does NOT determine health: most libraries are run and still contribute no health condition, because they cannot fail while the process is up."
}
```

- [ ] **Step 4: Add `lifecycle` to all six examples**

`package.example.json` → `"lifecycle": "build"` (the example is a locked build-time dependency). The other five → `"lifecycle": "run"`. Every dependency object in every example needs it; the existing example-validates-against-schema test is what catches a miss.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: PASS, including the pre-existing example-validation tests.

- [ ] **Step 6: Commit**

```bash
uv run ruff check . && uv run pytest -q
git add dependency-model/references/contracts tests/test_dependency_model_contracts.py
git commit -m "feat(dependency-model): add lifecycle to the dependency core (#49)"
```

---

### Task 3: The six skills set `lifecycle`

**Files:**
- Modify: `dependency-model/skills/package/SKILL.md`
- Modify: `dependency-model/skills/{service,network,config,security,platform}/SKILL.md`

**Interfaces:**
- Consumes: `pkglifecycle.py`'s CLI from Task 1; the `lifecycle` field from Task 2.

- [ ] **Step 1: Update the `package` skill**

Add a procedure step, after the syft run and before emitting dependencies:

> Run `pkglifecycle.py` against the same syft JSON to derive `lifecycle`:
>
> ```
> uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/pkglifecycle.py <path> --syft-json <file>
> ```
>
> Use `python3` in place of `uv run --script` if `uv` is unavailable. Set each dependency's `lifecycle` from the returned map, keyed by syft artifact id.
>
> **syft cannot answer this itself** — it reports Python dev and runtime dependencies from one lockfile with identical metadata, and drops npm `devDependencies` from the catalogue entirely. Do not try to infer it from the artifact's `type` or `locations`.
>
> For every entry in the returned `unresolved` list, record one assumption naming the ecosystem and that its packages defaulted to `run`.

- [ ] **Step 2: Update the other five skills**

Each gains one procedure line stating the constant it sets:

- `service`, `network`, `config`, `security`: "Set `lifecycle` to `run` on every dependency — these are needed while the service runs."
- `platform`: "Set `lifecycle` to `run` on every platform entry, whatever `details.kind` is — a CPU, memory, disk, or GPU limit, a cloud service, an architecture, an OS, or a `runtime-version` floor all constrain the environment the system runs in, not merely where it was built."

Each of the six also states, in its Rules: "`lifecycle` has two values and never a third. It records which environment must contain the dependency, and it does **not** determine health."

- [ ] **Step 3: Verify the structural tests still pass**

Run: `uv run pytest tests/test_plugin_structure.py tests/test_dependency_model_coupling.py -q`
Expected: PASS. Keep every verbatim string intact and on one line — `legitimate finding` in particular has been broken by a line wrap twice in this plugin's history.

- [ ] **Step 4: Commit**

```bash
uv run ruff check . && uv run pytest -q
git add dependency-model/skills
git commit -m "feat(dependency-model): six skills set lifecycle (#49)"
```

---

### Task 4: `references/definitions.md`

**Files:**
- Create: `dependency-model/references/definitions.md`
- Test: `tests/test_dependency_model_references.py` (extend)

**Interfaces:**
- Produces: a reference every layer-2 skill points at.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dependency_model_references.py`:

```python
class TestDefinitions(unittest.TestCase):
    def test_definitions_exists(self):
        self.assertTrue((REFERENCES / "definitions.md").exists())

    def test_states_the_two_senses_and_the_superset_relation(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        self.assertIn("build", text)
        self.assertIn("run", text)
        self.assertIn("superset", text)
        self.assertIn("devdependencies", text)

    def test_states_the_failability_test_for_health(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        self.assertIn("fail independently while the process is up", text)

    def test_carries_the_taxonomy_as_prose_and_marks_it_undefined(self):
        text = (REFERENCES / "definitions.md").read_text(encoding="utf-8").lower()
        for word in ("healthy", "degraded", "unhealthy"):
            self.assertIn(word, text)
        self.assertIn("not yet technically defined", text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_references.py -q`
Expected: FAIL — the file does not exist.

- [ ] **Step 3: Write `definitions.md`**

It must contain:

- **The two senses of "dependency".** `build` = needed only to build and test, absent from the deployed artifact (npm `devDependencies`, `[dependency-groups] dev`, `[dev-dependencies]`). `run` = needed while the service runs, and therefore also present at build (npm `dependencies`).
- **The superset relation, with its reasoning**: the build environment is a strict **superset** of the runtime environment, because the runtime dependencies must be present at build in order to run the app for debugging. The reverse does not hold. `npm ci --omit=dev` is the operator that drops the difference. This is why there is no `both` — a runtime dependency is present at build *because* it is a runtime dependency, so `both` would record the containment twice.
- **The health definition**: the service in production has all of its environment and service dependencies met, and all metric-sensitive ones within acceptable bounds.
- **The failability test**, verbatim as the phrase the test greps: a dependency enters a health definition iff it **can fail independently while the process is up**. With the worked table — services, credentials, resource limits, remote config, and dynamically loaded packages can; a bundled library cannot, because it is in the artifact or the deploy failed.
- **Why lifecycle is not the health filter**: most libraries are `run` under npm semantics and still contribute nothing to health.
- **The taxonomy as prose**, explicitly marked "not yet technically defined": *healthy* = all conditions hold; *unhealthy* = a `presence` condition fails for something critical functionality needs; *degraded* = anything between — a dependency reporting degraded itself, one outside its bounds, or one unavailable that only a secondary function needs.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_model_references.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run pytest -q
git add dependency-model/references/definitions.md tests/test_dependency_model_references.py
git commit -m "docs(dependency-model): define dependency senses and health (#49)"
```

---

### Task 5: The `synthesis` contract

**Files:**
- Create: `dependency-model/references/contracts/synthesis.schema.json`
- Create: `dependency-model/references/contracts/examples/synthesis.example.json`
- Modify: `tests/test_dependency_model_contracts.py`

**Interfaces:**
- Produces: the contract `synthesize` emits and `report`, #50, and #51 consume.

Shape:

```json
{
  "contract_version": "1.0.0",
  "target": "/abs/path",
  "inventory": { "categories": { "service": { "status": "discovered", "dependencies": [] } } },
  "graph": {
    "nodes": [{ "id": "service:postgres-primary", "name": "postgres", "category": "service", "lifecycle": "run" }],
    "edges": [{ "from": "package:pgx-v5-5.5.0", "to": "package:puddle-v2-2.2.1", "kind": "depends_on", "lifecycle": "build" }],
    "cycles": [["package:a-1.0.0", "package:b-2.0.0"]]
  },
  "health": [
    {
      "service_id": "service:postgres-primary",
      "conditions": [
        {
          "kind": "presence",
          "subject_id": "network:postgres-5432",
          "expectation": null,
          "required_for": ["component:api"],
          "evidence": ["docker-compose.yml:12"]
        },
        {
          "kind": "bound",
          "subject_id": "service:postgres-primary",
          "expectation": { "value": "5s", "evidence": ["internal/db/pool.go:44"] },
          "required_for": ["component:api"],
          "evidence": ["internal/db/pool.go:44"]
        }
      ]
    }
  ],
  "assumptions": [{ "claim": "...", "why_unconfirmed": "..." }]
}
```

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dependency_model_contracts.py`, and **update the existing exact-list test** at line ~57 to include `synthesis.schema.json`:

```python
class TestSynthesisContract(unittest.TestCase):
    def test_schema_and_example_exist_and_validate(self):
        schema = load(CONTRACTS / "synthesis.schema.json")
        instance = load(EXAMPLES / "synthesis.example.json")
        self.assertEqual(validate(instance, schema, base_dir=CONTRACTS), [])

    def test_requires_the_four_parts(self):
        schema = load(CONTRACTS / "synthesis.schema.json")
        for field in ("contract_version", "target", "inventory", "graph", "health",
                      "assumptions"):
            self.assertIn(field, schema["required"])

    def test_edge_kinds_are_exactly_two(self):
        schema = load(CONTRACTS / "synthesis.schema.json")
        edge = schema["properties"]["graph"]["properties"]["edges"]["items"]
        self.assertEqual(edge["properties"]["kind"]["enum"],
                         ["depends_on", "relates_to"])

    def test_condition_kinds_are_the_three_documented(self):
        schema = load(CONTRACTS / "synthesis.schema.json")
        cond = (schema["properties"]["health"]["items"]
                ["properties"]["conditions"]["items"])
        self.assertEqual(cond["properties"]["kind"]["enum"],
                         ["presence", "bound", "upstream_health"])

    def test_expectation_accepts_null(self):
        """null means no declaration was found -- never 'no bound needed'."""
        schema = load(CONTRACTS / "synthesis.schema.json")
        cond = (schema["properties"]["health"]["items"]
                ["properties"]["conditions"]["items"])
        self.assertIn("null", cond["properties"]["expectation"]["type"])

    def test_example_carries_a_null_expectation_and_a_declared_one(self):
        instance = load(EXAMPLES / "synthesis.example.json")
        expectations = [c["expectation"]
                        for h in instance["health"] for c in h["conditions"]]
        self.assertIn(None, expectations)
        self.assertTrue(any(e is not None for e in expectations))


class TestNoStateVocabulary(unittest.TestCase):
    """D9: states that are not encoded cannot be encoded wrongly. Defining
    `degraded` later must cost nothing in this schema."""

    def test_no_schema_declares_a_health_state_enum(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            text = path.read_text(encoding="utf-8")
            for state in ('"healthy"', '"degraded"', '"unhealthy"'):
                with self.subTest(schema=path.name, state=state):
                    self.assertNotIn(state, text)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: FAIL — `synthesis.schema.json` missing, and the exact-list test fails until updated.

- [ ] **Step 3: Write the schema and example**

Follow `discovery.schema.json`'s house style: two-space indent, `$schema` first, then `title`, `type`, `required`, `properties`. `inventory.categories` `$ref`s the six category schemas exactly as the discovery envelope does. Add `"additionalProperties": false` to `graph`, each edge, each node, and each condition — consistent with what layer 1 carries.

The example must populate: at least two nodes and one edge of **each** kind, one cycle, one health entry with both a `null` and a declared `expectation`, and one assumption.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_dependency_model_contracts.py -q`
Expected: PASS. If the no-state-vocabulary test fires, a description used one of the three words — reword it, do not weaken the test.

- [ ] **Step 5: Commit**

```bash
uv run ruff check . && uv run pytest -q
git add dependency-model/references/contracts tests/test_dependency_model_contracts.py
git commit -m "feat(dependency-model): the synthesis contract (#49)"
```

---

### Task 6: `depgraph.py` — merge and CLI

**Files:**
- Create: `dependency-model/scripts/depgraph.py`
- Create: `dependency-model/scripts/depgraphlib/__init__.py`
- Create: `dependency-model/scripts/depgraphlib/merge.py`
- Test: `tests/test_depgraph_merge.py`

**Interfaces:**
- Produces: `depgraphlib.VERSION = "1.0.0"`.
- Produces: `merge_envelopes(envelopes: list[dict]) -> dict` — returns `{"categories": {...}}`, a key union.
- Produces: CLI `uv run --script depgraph.py <envelope.json> [...] [--indent N]` → the graph document on stdout; exit `2` when any input is unreadable.
- Consumed by: Tasks 7 and 8, which add edges/cycles and Mermaid to the same document.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depgraph_merge.py`:

```python
# tests/test_depgraph_merge.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.merge import merge_envelopes


def env(category, deps, status="discovered"):
    return {"contract_version": "1.0.0", "target": "/r",
            "categories": {category: {"status": status, "dependencies": deps,
                                      "assumptions": []}}}


class TestMergeEnvelopes(unittest.TestCase):
    def test_key_union_across_categories(self):
        out = merge_envelopes([env("service", []), env("network", [])])
        self.assertEqual(sorted(out["categories"]), ["network", "service"])

    def test_dependencies_survive_the_merge(self):
        dep = {"id": "service:pg", "name": "postgres", "lifecycle": "run"}
        out = merge_envelopes([env("service", [dep])])
        self.assertEqual(out["categories"]["service"]["dependencies"], [dep])

    def test_failed_status_propagates_and_never_flattens_to_empty(self):
        """A failed scan and an empty result are different findings. Flattening
        would have the report state as fact that a system has no network
        dependencies when the scan simply broke."""
        out = merge_envelopes([env("network", [], status="failed")])
        self.assertEqual(out["categories"]["network"]["status"], "failed")

    def test_empty_discovered_stays_discovered(self):
        out = merge_envelopes([env("service", [], status="discovered")])
        self.assertEqual(out["categories"]["service"]["status"], "discovered")

    def test_a_later_envelope_does_not_clobber_an_earlier_category(self):
        a = env("service", [{"id": "service:a", "name": "a", "lifecycle": "run"}])
        b = env("service", [{"id": "service:b", "name": "b", "lifecycle": "run"}])
        out = merge_envelopes([a, b])
        ids = [d["id"] for d in out["categories"]["service"]["dependencies"]]
        self.assertEqual(sorted(ids), ["service:a", "service:b"])

    def test_duplicate_ids_are_collapsed_once(self):
        dep = {"id": "service:a", "name": "a", "lifecycle": "run"}
        out = merge_envelopes([env("service", [dep]), env("service", [dep])])
        self.assertEqual(len(out["categories"]["service"]["dependencies"]), 1)

    def test_output_is_deterministic(self):
        envs = [env("network", []), env("service", [])]
        import json
        self.assertEqual(json.dumps(merge_envelopes(envs), sort_keys=True),
                         json.dumps(merge_envelopes(envs), sort_keys=True))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_depgraph_merge.py -q`
Expected: `ModuleNotFoundError: No module named 'depgraphlib'`.

- [ ] **Step 3: Implement `depgraphlib/__init__.py` and `merge.py`**

```python
# depgraphlib/__init__.py
"""Deterministic synthesis over dependency-model discovery envelopes.

Stdlib only: depgraph.py declares no dependencies so it runs under bare
python3 as well as `uv run --script`.
"""

VERSION = "1.0.0"
```

```python
# depgraphlib/merge.py
"""Key-union merge of the six discovery envelopes.

Each discovery skill emits a full envelope with exactly one category
populated, so merging is a key union rather than a transform.
"""


def merge_envelopes(envelopes):
    """Return {"categories": {...}} from any number of discovery envelopes.

    status is never flattened: a failed scan and an empty result are different
    findings, and collapsing them would let a report state as fact that a
    system has no dependencies of a kind when the scan simply broke.
    """
    categories = {}
    for envelope in envelopes:
        for name, block in (envelope.get("categories") or {}).items():
            target = categories.setdefault(
                name, {"status": block.get("status", "discovered"),
                       "dependencies": [], "assumptions": []})
            if block.get("status") == "failed":
                target["status"] = "failed"
            seen = {d["id"] for d in target["dependencies"] if "id" in d}
            for dep in block.get("dependencies") or []:
                if dep.get("id") not in seen:
                    target["dependencies"].append(dep)
                    seen.add(dep.get("id"))
            target["assumptions"].extend(block.get("assumptions") or [])
    for block in categories.values():
        block["dependencies"].sort(key=lambda d: d.get("id", ""))
    return {"categories": categories}
```

- [ ] **Step 4: Implement the CLI**

`dependency-model/scripts/depgraph.py`, mirroring `depscan.py`'s header exactly (`#!/usr/bin/env -S uv run --script`, the `/// script` block with `dependencies = []`, a docstring naming the `python3` fallback and exit codes). It reads one or more envelope JSON files as positional arguments, calls `merge_envelopes`, and prints the document with `sort_keys=True`. Exit `2` when any input is unreadable.

`chmod +x dependency-model/scripts/depgraph.py`

- [ ] **Step 5: Run the tests and commit**

```bash
uv run pytest tests/test_depgraph_merge.py -q
uv run ruff check . && uv run pytest -q
git add dependency-model/scripts tests/test_depgraph_merge.py
git commit -m "feat(dependency-model): depgraph envelope merge and CLI (#49)"
```

Also add `depgraphlib` to `known-first-party` in `pyproject.toml`'s `[tool.ruff.lint.isort]` (it currently lists `inventorylib` and `depscanlib`), and `dependency-model/scripts` is already in ty's `extra-paths`.

---

### Task 7: `depgraph.py` — typed edges and cycles

**Files:**
- Create: `dependency-model/scripts/depgraphlib/graph.py`
- Modify: `dependency-model/scripts/depgraph.py`
- Test: `tests/test_depgraph_graph.py`

**Interfaces:**
- Produces: `build_graph(merged: dict) -> dict` returning `{"nodes": [...], "edges": [...], "cycles": [...]}`.
- Node: `{"id", "name", "category", "lifecycle"}`. Edge: `{"from", "to", "kind", "lifecycle"}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depgraph_graph.py`:

```python
# tests/test_depgraph_graph.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.graph import build_graph


def dep(id_, name, lifecycle="run", related=None, depends=None):
    d = {"id": id_, "name": name, "lifecycle": lifecycle,
         "evidence": [], "related_ids": related or [], "details": {}}
    if depends is not None:
        d["details"]["depends_on"] = depends
    return d


def merged(**cats):
    return {"categories": {k: {"status": "discovered", "dependencies": v,
                               "assumptions": []} for k, v in cats.items()}}


class TestNodes(unittest.TestCase):
    def test_one_node_per_dependency_carrying_category_and_lifecycle(self):
        g = build_graph(merged(service=[dep("service:pg", "postgres")]))
        self.assertEqual(g["nodes"], [{"id": "service:pg", "name": "postgres",
                                       "category": "service", "lifecycle": "run"}])

    def test_nodes_are_sorted_by_id(self):
        g = build_graph(merged(service=[dep("service:b", "b"), dep("service:a", "a")]))
        self.assertEqual([n["id"] for n in g["nodes"]], ["service:a", "service:b"])


class TestEdges(unittest.TestCase):
    def test_depends_on_edges_come_from_package_details(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build")]))
        self.assertEqual(g["edges"], [{"from": "package:a-1", "to": "package:b-2",
                                       "kind": "depends_on", "lifecycle": "build"}])

    def test_relates_to_edges_come_from_related_ids(self):
        g = build_graph(merged(
            service=[dep("service:pg", "postgres", related=["network:pg-5432"])],
            network=[dep("network:pg-5432", "postgres:5432")]))
        self.assertEqual(g["edges"], [{"from": "service:pg", "to": "network:pg-5432",
                                       "kind": "relates_to", "lifecycle": "run"}])

    def test_the_two_edge_kinds_are_not_conflated(self):
        """A consumer asking what must be reachable at runtime filters to run
        edges; one asking what we build against filters to build."""
        g = build_graph(merged(
            package=[dep("package:a-1", "a", "build", depends=["package:b-2"]),
                     dep("package:b-2", "b", "build")],
            service=[dep("service:pg", "pg", related=["network:x"])],
            network=[dep("network:x", "x")]))
        kinds = {e["kind"] for e in g["edges"]}
        self.assertEqual(kinds, {"depends_on", "relates_to"})

    def test_an_edge_to_an_unknown_id_is_dropped_not_dangling(self):
        g = build_graph(merged(service=[dep("service:a", "a", related=["service:ghost"])]))
        self.assertEqual(g["edges"], [])

    def test_edges_are_sorted_and_deduplicated(self):
        g = build_graph(merged(service=[
            dep("service:a", "a", related=["service:b", "service:b"]),
            dep("service:b", "b")]))
        self.assertEqual(len(g["edges"]), 1)


class TestCycles(unittest.TestCase):
    def test_a_two_node_cycle_is_reported(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build", depends=["package:a-1"])]))
        self.assertEqual(len(g["cycles"]), 1)
        self.assertEqual(sorted(g["cycles"][0]), ["package:a-1", "package:b-2"])

    def test_an_acyclic_graph_reports_none(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:b-2"]),
            dep("package:b-2", "b", "build")]))
        self.assertEqual(g["cycles"], [])

    def test_a_self_loop_is_a_cycle(self):
        g = build_graph(merged(package=[
            dep("package:a-1", "a", "build", depends=["package:a-1"])]))
        self.assertEqual(g["cycles"], [["package:a-1"]])

    def test_cycles_are_deterministic(self):
        m = merged(package=[dep("package:a-1", "a", "build", depends=["package:b-2"]),
                            dep("package:b-2", "b", "build", depends=["package:a-1"])])
        self.assertEqual(build_graph(m)["cycles"], build_graph(m)["cycles"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_depgraph_graph.py -q`
Expected: `ModuleNotFoundError: No module named 'depgraphlib.graph'`.

- [ ] **Step 3: Implement `graph.py`**

Nodes: one per dependency, carrying `id`, `name`, `category`, `lifecycle`, sorted by `id`.

Edges: `depends_on` from `details.depends_on[]` (lifecycle taken from the source node); `relates_to` from `related_ids[]`. **Drop any edge whose target id is not a known node** — a dangling edge in a graph #49 says is the deliverable is worse than a missing one. Deduplicate, then sort by `(from, to, kind)`.

Cycles: iterative depth-first search over the `depends_on` edges only (not the combined edge set — `related_ids` links are routinely symmetric, so walking them too would report a 2-cycle for every service↔network association and drown any real finding), using an explicit stack (not recursion — a deep package graph would blow Python's recursion limit). Emit each cycle once, with its member ids in a deterministic rotation (rotate so the lexicographically smallest id is first) so two runs agree.

- [ ] **Step 4: Wire into the CLI, run tests, commit**

```bash
uv run pytest tests/test_depgraph_graph.py tests/test_depgraph_merge.py -q
uv run ruff check . && uv run pytest -q
git add dependency-model/scripts tests/test_depgraph_graph.py
git commit -m "feat(dependency-model): typed dependency edges and cycle detection (#49)"
```

---

### Task 8: `depgraph.py` — Mermaid emission and the node cap

**Files:**
- Create: `dependency-model/scripts/depgraphlib/mermaid.py`
- Modify: `dependency-model/scripts/depgraph.py`
- Test: `tests/test_depgraph_mermaid.py`

**Interfaces:**
- Produces: `to_mermaid(graph: dict, cap: int = 60) -> dict` returning `{"mermaid": str|None, "degraded": bool, "reason": str|None, "node_count": int}`.

**The escaping rule is verified, not guessed.** A raw `"` inside a quoted Mermaid label breaks parsing; `#quot;` is the working escape. `#`, `<`, `>`, and `;` are fine unescaped. Node ids must be opaque (`n0`, `n1`, …) with the real name in the label, because real package names (`@babel/core`, `github.com/sony/gobreaker`, `x[1]`) are not valid Mermaid identifiers.

- [ ] **Step 1: Write the failing test**

Create `tests/test_depgraph_mermaid.py`:

```python
# tests/test_depgraph_mermaid.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dependency-model" / "scripts"))

from depgraphlib.mermaid import to_mermaid


def graph(names, edges=None):
    return {"nodes": [{"id": f"package:{n}", "name": n, "category": "package",
                       "lifecycle": "build"} for n in names],
            "edges": edges or [], "cycles": []}


class TestMermaid(unittest.TestCase):
    def test_emits_a_flowchart_with_opaque_ids_and_labelled_nodes(self):
        out = to_mermaid(graph(["left-pad"]))
        self.assertTrue(out["mermaid"].startswith("flowchart LR"))
        self.assertIn('["left-pad"]', out["mermaid"])
        self.assertFalse(out["degraded"])

    def test_names_that_are_not_valid_mermaid_ids_still_work(self):
        """Verified against mmdc: opaque ids plus quoted labels render for all
        of these; using the name as the id does not."""
        for name in ("@babel/core", "github.com/sony/gobreaker", "x[1]", "a b (c)"):
            with self.subTest(name=name):
                out = to_mermaid(graph([name]))
                self.assertIn(f'["{name}"]', out["mermaid"])

    def test_a_double_quote_in_a_name_is_escaped(self):
        """A raw quote breaks Mermaid parsing; #quot; is the working escape."""
        out = to_mermaid(graph(['has"quote']))
        self.assertNotIn('has"quote', out["mermaid"])
        self.assertIn("has#quot;quote", out["mermaid"])

    def test_hash_and_angle_brackets_are_left_alone(self):
        out = to_mermaid(graph(["has#hash", "has<tag>"]))
        self.assertIn('["has#hash"]', out["mermaid"])
        self.assertIn('["has<tag>"]', out["mermaid"])

    def test_edges_are_emitted_between_the_opaque_ids(self):
        g = graph(["a", "b"], edges=[{"from": "package:a", "to": "package:b",
                                      "kind": "depends_on", "lifecycle": "build"}])
        out = to_mermaid(g)
        self.assertRegex(out["mermaid"], r"n\d+ --> n\d+")

    def test_an_edge_to_a_node_not_in_the_graph_is_skipped(self):
        g = graph(["a"], edges=[{"from": "package:a", "to": "package:ghost",
                                 "kind": "depends_on", "lifecycle": "build"}])
        self.assertNotIn("-->", to_mermaid(g)["mermaid"])

    def test_output_is_deterministic(self):
        g = graph(["b", "a"])
        self.assertEqual(to_mermaid(g)["mermaid"], to_mermaid(g)["mermaid"])


class TestNodeCap(unittest.TestCase):
    def test_above_the_cap_it_degrades_and_says_so(self):
        """Silent truncation would read as 'this is the whole graph'."""
        out = to_mermaid(graph([f"p{i}" for i in range(70)]), cap=60)
        self.assertTrue(out["degraded"])
        self.assertIsNone(out["mermaid"])
        self.assertIn("60", out["reason"])
        self.assertEqual(out["node_count"], 70)

    def test_at_the_cap_it_does_not_degrade(self):
        out = to_mermaid(graph([f"p{i}" for i in range(60)]), cap=60)
        self.assertFalse(out["degraded"])
        self.assertIsNotNone(out["mermaid"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_depgraph_mermaid.py -q`
Expected: `ModuleNotFoundError: No module named 'depgraphlib.mermaid'`.

- [ ] **Step 3: Implement `mermaid.py`**

```python
"""Emit Mermaid flowchart source from a dependency graph.

Node ids are opaque (n0, n1, ...) with the real name in a quoted label: real
package names like @babel/core, github.com/sony/gobreaker and x[1] are not
valid Mermaid identifiers, but they render correctly as labels.

Escaping is verified against mmdc: a raw double quote inside a quoted label
breaks parsing, and #quot; is the escape that works. #, <, > and ; are fine.
"""

CAP_DEFAULT = 60


def _label(name):
    return str(name).replace('"', "#quot;")


def to_mermaid(graph, cap=CAP_DEFAULT):
    nodes = sorted(graph.get("nodes") or [], key=lambda n: n["id"])
    count = len(nodes)
    if count > cap:
        return {"mermaid": None, "degraded": True, "node_count": count,
                "reason": f"{count} nodes exceeds the {cap}-node Mermaid cap; "
                          f"a rendered graph this size is unreadable"}

    index = {node["id"]: f"n{i}" for i, node in enumerate(nodes)}
    lines = ["flowchart LR"]
    lines += [f'  {index[n["id"]]}["{_label(n["name"])}"]' for n in nodes]
    for edge in sorted(graph.get("edges") or [],
                       key=lambda e: (e["from"], e["to"], e["kind"])):
        if edge["from"] in index and edge["to"] in index:
            arrow = "-->" if edge["kind"] == "depends_on" else "-.->"
            lines.append(f'  {index[edge["from"]]} {arrow} {index[edge["to"]]}')
    return {"mermaid": "\n".join(lines) + "\n", "degraded": False,
            "node_count": count, "reason": None}
```

- [ ] **Step 4: Verify the emitted Mermaid actually renders**

Do not trust the unit tests alone — they check strings, not validity:

```bash
uv run python -c "
import sys; sys.path.insert(0,'dependency-model/scripts')
from depgraphlib.mermaid import to_mermaid
g = {'nodes':[{'id':f'p:{n}','name':n,'category':'package','lifecycle':'build'}
              for n in ['@babel/core','github.com/sony/gobreaker','x[1]','has\"quote']],
     'edges':[{'from':'p:@babel/core','to':'p:x[1]','kind':'depends_on','lifecycle':'build'}],
     'cycles':[]}
open('/tmp/g.mmd','w').write(to_mermaid(g)['mermaid'])
"
npx -y -p @mermaid-js/mermaid-cli mmdc -i /tmp/g.mmd -o /tmp/g.svg
```
Expected: `mmdc` exits 0 and writes a non-empty SVG. If it fails, the escaping is wrong — fix it rather than adjusting the unit test.

- [ ] **Step 5: Wire into the CLI, run tests, commit**

```bash
uv run pytest tests/test_depgraph_mermaid.py -q
uv run ruff check . && uv run pytest -q
git add dependency-model/scripts tests/test_depgraph_mermaid.py
git commit -m "feat(dependency-model): mermaid emission with a stated node cap (#49)"
```

---

### Task 9: The `synthesize` skill

**Files:**
- Create: `dependency-model/skills/synthesize/SKILL.md`

**Interfaces:**
- Consumes: the six discovery skills by name; `depgraph.py`; `synthesis.schema.json`.
- Produces: `/dependency-model:synthesize`.

Frontmatter `description` must end with `Emits the dependency-model:synthesis contract.` and carry `Read-only.`. No `version:` field. Never write "subagent". Reference bundled files as `${CLAUDE_PLUGIN_ROOT}/path` in backticks, never as a markdown link.

- [ ] **Step 1: Write the skill**

Sections, in this order:

- Statement of what it emits, and the read-only sentence.
- Pointers: `${CLAUDE_PLUGIN_ROOT}/references/contracts/synthesis.schema.json`, `.../examples/synthesis.example.json`, `${CLAUDE_PLUGIN_ROOT}/references/definitions.md`, `${CLAUDE_PLUGIN_ROOT}/scripts/depgraph.py`.
- `## Usage` — `/dependency-model:synthesize [path]`, plus the bootstrap: invoke the six discovery skills **by name** if not handed their envelopes.
- `## Procedure`:
  1. Gather the six envelopes, invoking each skill by name if needed. Save each to a file.
  2. Run `depgraph.py` over them for the merged inventory, typed edges, cycles, and Mermaid.
  3. For each service, derive `conditions[]`. **Which dependencies contribute a condition is decided by the failability test in `definitions.md`, not by `lifecycle` and not by category**: a dependency enters iff a condition can be *stated* about it with evidence. A bundled library produces none. A dynamically loaded package produces a `presence` condition citing its loading site.
  4. `kind` is `presence` when the condition is that the dependency is reachable; `bound` when a declared metric bound applies; `upstream_health` when the requirement is that another service is itself healthy.
  5. `expectation` carries the declared value with its `file:line`, or is `null` when no declaration was found. **`null` never means "no bound needed."**
  6. `required_for[]` records which functions or components need this — a component name, an entry point, a consuming file. Empty when nothing static connects it. Never a criticality rating.
  7. Carry every category's `status` through unchanged. A `failed` category stays `failed`.
  8. Emit the contract, then a short prose summary.
- `## Rules`: read-only; `null` means no declaration was found, never confirmed absent; an empty `health` list is a legitimate finding for a system with no services, and a failed category is different from an empty one; no criticality, ranking, or blast radius; invoke skills by name, never by path.

- [ ] **Step 2: Verify structural tests pass, then commit**

```bash
uv run pytest tests/test_plugin_structure.py -q
uv run ruff check . && uv run pytest -q
git add dependency-model/skills/synthesize
git commit -m "feat(dependency-model): the synthesize skill (#49)"
```

---

### Task 10: The `report` skill

**Files:**
- Create: `dependency-model/skills/report/SKILL.md`

**Interfaces:**
- Consumes: the `synthesis` contract; `synthesize` by name.
- Produces: `/dependency-model:report`, writing `docs/dependencies.md`.

- [ ] **Step 1: Write the skill**

Same structural rules as Task 9. Sections:

- What it produces and the read-only sentence (it writes one document; it executes nothing against the target).
- Pointers to the synthesis schema, its example, and `definitions.md`.
- `## Usage` — `/dependency-model:report [path]`; bootstrap by invoking `synthesize` **by name** if not handed a contract.
- `## Procedure`:
  1. Obtain the contract.
  2. Write `docs/dependencies.md`: an inventory summary by category (including any category whose `status` is `failed`, stated as failed rather than omitted), the health definitions, the Mermaid graph in a ` ```mermaid ` fence, the cycles, and the assumptions.
  3. **If the graph degraded past the node cap**, say so explicitly with the node count and the reason, and do not emit a partial fence. Silent truncation reads as "this is the whole graph."
  4. If `mmdc` is available, verify the fence renders before writing; if it is not, say in the report that the graph was not render-verified. This mirrors the rule `CLAUDE.md` imposes on `docs/ARCHITECTURE.md`.
  5. Publish an Artifact only when asked.
- `## Rules`: never state an empty category as "no dependencies" when its status is `failed`; no criticality or ranking; the report is a rendering — it adds no facts the contract does not carry.

- [ ] **Step 2: Verify and commit**

```bash
uv run pytest tests/test_plugin_structure.py -q
uv run ruff check . && uv run pytest -q
git add dependency-model/skills/report
git commit -m "feat(dependency-model): the report skill (#49)"
```

---

### Task 11: Registration and coupling-test restructure

**Files:**
- Modify: `scripts/verify-marketplace.sh` (PLUGINS and SCRIPTS arrays)
- Modify: `tests/test_dependency_model_coupling.py`
- Modify: `README.md`
- Modify: `dependency-model/requirements.json`
- Regenerate: Codex manifests

- [ ] **Step 1: Restructure the coupling test**

It currently asserts the skill listing equals exactly the six categories, and applies per-category assertions ("names its own `<category>.schema.json`") to every skill. Split it:

```python
CATEGORIES = ["config", "network", "package", "platform", "security", "service"]
LAYER2 = ["report", "synthesize"]
ALL_SKILLS = sorted(CATEGORIES + LAYER2)
```

- Category-scoped tests (own schema, own example, `--exclude`/`270` for package, the security credential rule) iterate `CATEGORIES`.
- Shared-discipline tests (read-only, `no declaration was found` + `confirmed absent`, no `profile/scripts` path coupling, `${CLAUDE_PLUGIN_ROOT}` refs resolve, no banned promises on any line) iterate **all** skills.
- The directory-listing test asserts `ALL_SKILLS`.
- Add: both layer-2 skills name `synthesis.schema.json`; `report` names `synthesize`; `synthesize` names `depgraph.py`.

- [ ] **Step 2: Add the two decision-pinning tests the spec requires**

These pin instructions rather than runtime behaviour — the skills are prose an LLM
executes, so there is no output to unit-test. That limit is real and worth a comment in
the test file: it proves the rule is *written*, not that it was *followed*.

```python
class TestLifecycleInstructions(unittest.TestCase):
    """Spec pin: an unenforced classification is how two skills come to
    disagree about the same entry."""

    RUN_CONSTANT = ["service", "network", "config", "security"]

    def test_the_four_constant_categories_say_run(self):
        for category in self.RUN_CONSTANT:
            text = body(PLUGIN / "skills" / category / "SKILL.md")
            with self.subTest(skill=category):
                self.assertRegex(text, r"`lifecycle`[^\n]*`run`")

    def test_platform_states_the_split_by_details_kind(self):
        text = body(PLUGIN / "skills" / "platform" / "SKILL.md")
        self.assertIn("details.kind", text)
        for kind in ("cpu", "memory", "disk", "gpu", "cloud-service",
                     "arch", "os", "runtime-version"):
            with self.subTest(kind=kind):
                self.assertIn(kind, text)

    def test_package_defers_to_pkglifecycle_and_says_syft_cannot(self):
        text = body(PLUGIN / "skills" / "package" / "SKILL.md")
        self.assertIn("pkglifecycle.py", text)
        self.assertIn("syft cannot", text.lower())

    def test_no_skill_mentions_a_third_lifecycle_value(self):
        for skill in ALL_SKILLS:
            text = body(PLUGIN / "skills" / skill / "SKILL.md")
            with self.subTest(skill=skill):
                self.assertNotIn("`both`", text)


class TestFailabilityRuleIsStated(unittest.TestCase):
    """Spec pin, both ends: a bundled library must not enter health, a
    dynamically loaded package must. These are the two cases a category
    filter would have got wrong in opposite directions."""

    def test_synthesize_states_the_failability_test_not_a_category_filter(self):
        text = body(PLUGIN / "skills" / "synthesize" / "SKILL.md").lower()
        self.assertIn("fail independently while the process is up", text)
        self.assertIn("not by `lifecycle`", text)

    def test_synthesize_names_both_ends_explicitly(self):
        text = body(PLUGIN / "skills" / "synthesize" / "SKILL.md").lower()
        self.assertIn("bundled", text)
        self.assertIn("dynamically loaded", text)
        self.assertIn("loading site", text)
```

- [ ] **Step 3: Update the derived artifacts**

- `scripts/verify-marketplace.sh` PLUGINS: `"dependency-model:development:config,network,package,platform,report,security,service,synthesize"` — skills in the order `ls dependency-model/skills/` gives, which is alphabetical.
- `scripts/verify-marketplace.sh` SCRIPTS: add `dependency-model/scripts/depgraph.py` and `dependency-model/scripts/pkglifecycle.py`.
- `README.md`: add `synthesize` and `report` bullets to the `### dependency-model` section. The plugin count does not change — this adds skills, not a plugin.
- `dependency-model/requirements.json`: add `mmdc` as **optional** (`"required": false`, probe `["npx", "--version"]`, why: the report skill verifies its generated Mermaid renders when it is available). Allowed tool keys are exactly `name`, `required`, `why`, `probe`, `version_pattern`, `min_version`, `install`; `probe` must be an argv array.
- Regenerate: `uv run scripts/gen_codex_manifests.py` and commit what it writes. Never hand-edit the Codex manifests.

- [ ] **Step 4: Run every check and commit**

```bash
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
REPO="$(pwd)" bash scripts/verify-marketplace.sh
git add scripts/verify-marketplace.sh tests/test_dependency_model_coupling.py README.md dependency-model .agents
git commit -m "feat(dependency-model): register the synthesis skills (#49)"
```

Expected: `verify-marketplace.sh` PASS 40 or higher with FAIL 0, naming all eight skills.

---

### Task 12: Architecture documentation

**Files:**
- Modify: `docs/ARCHITECTURE.md`

- [ ] **Step 1: Extend the graph**

Add `x_synth["synthesize"]` and `x_report["report"]` to the `depmodel` subgraph, with edges from all six discovery skills into `x_synth`, and `x_synth -- "synthesis" --> x_report`. Add the catalog rows for both skills.

- [ ] **Step 2: Re-render — do not eyeball it**

```bash
python3 -c "
import re, pathlib
t = pathlib.Path('docs/ARCHITECTURE.md').read_text(encoding='utf-8')
print(re.search(r'\`\`\`mermaid\n(.*?)\`\`\`', t, re.S).group(1), end='')
" > /tmp/arch.mmd
npx -y -p @mermaid-js/mermaid-cli mmdc -i /tmp/arch.mmd -o /tmp/arch.svg
```
Expected: exit 0. A syntax error here ships a broken graph to `main`. If `npx` is unavailable, say so in the report rather than claiming the render passed.

- [ ] **Step 3: Run every check and commit**

```bash
uv run ruff check . && uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
REPO="$(pwd)" bash scripts/verify-marketplace.sh
git add docs/ARCHITECTURE.md
git commit -m "docs(architecture): map the synthesis skills into the graph (#49)"
```

---

## Notes for the executor

**Deliberately not built** — do not add these back:

- **Journey exposure** — its own issue, #54. `required_for[]` is the slot it fills; until then that field carries whatever static evidence shows.
- **Any runtime evaluation of health.** This layer defines conditions; it never evaluates them.
- **A `healthy`/`degraded`/`unhealthy` enum in any schema.** Prose only, in `definitions.md`. A test enforces the absence.
- **Criticality, ranking, or blast radius** — layer 3, #50.
- **Any version bump** — until the user declares the feature productionized.

**If a test will not go green**, prefer suspecting this plan over suspecting the codebase. In layer 1's execution, nine of ten fix rounds corrected a defect in the plan text rather than in the implementation. The verified facts block at the top of this plan was measured rather than assumed for exactly that reason — but the prose task descriptions have not been executed, and they are the likeliest place for a mistake to remain.
