# `profile` Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `profile` plugin that answers general questions about any codebase — what it is built with, what its documentation says it is supposed to do, how it deploys, and what users do with it — backed by a deterministic inventory script.

**Architecture:** A dependency-free Python package (`inventorylib`) does the mechanical repo census and emits JSON; four skills (`stack`, `docs`, `topology`, `journeys`) interpret that census with model reasoning guided by reference files. Each skill emits a versioned JSON contract, which is the only thing downstream consumers (including the `itest` plugin) are allowed to depend on.

**Tech Stack:** Python 3.13 stdlib only. `unittest` for tests. Markdown skills. No third-party runtime or test dependencies.

**Spec:** `docs/superpowers/specs/2026-07-26-integration-test-design-design.md`

## Global Constraints

- **Python: stdlib only.** No third-party imports in shipped code or tests. `jsonschema` is NOT installed; contract tests use the hand-rolled checker built in Task 8.
- **Test style:** `unittest.TestCase` classes, matching `tests/test_dedupe.py`. Every test module starts with `sys.dont_write_bytecode = True` and a `sys.path.insert` pointing at `profile/scripts`.
- **Test command:** `python3 -m unittest discover -s tests -t .` from the repo root. Single module: `python3 -m unittest tests.<module> -v`.
- **Lint command:** `ruff check profile/ tests/test_profile_*.py tests/repobuilder.py tests/schema_check.py tests/test_plugin_structure.py` — scoped to files this plan creates. Whole-directory linting fails on pre-existing errors (13 in `tests/`, 8 in `dev/` and `logseq/`) that are out of scope. Do not fix those here.
- **Script invocation is `uv run --script`, never bare `uv run`.** Skills invoke `uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/profile_inventory.py <path>`. The `--script` flag is load-bearing, not stylistic: this tool runs against arbitrary user repos, and bare `uv run` resolves project context from the current directory — verified failing outright inside a repo whose `pyproject.toml` has an unresolvable dependency, which is common with private indexes and unpublished packages. `--script` treats the file as a PEP 723 script and ignores the surrounding project entirely. Measured warm overhead is lower than the system `python3` (0.02–0.06s vs 0.21s).
- **Every script carries a PEP 723 header** declaring `requires-python`, and `dependencies` when it has any. Today it has none, so `python3 <script>` remains a documented fallback that works. When a dependency is eventually added, the header is the only change needed — uv resolves and caches it per-script, isolated, on first run.
- **No `pyproject.toml` for these plugins.** Repo convention is that packaging follows dependencies: `dev` and `logseq` are stdlib-only and ship no manifest; `writing/skills/boring` has a `pyproject.toml` and `uv.lock` because it depends on spacy, textstat, and proselint. `profile` is stdlib-only, and PEP 723 covers the single-script case without a manifest. A `pyproject.toml` here would describe a build nothing runs, and would make `profile_inventory.py` report this repo as a two-package monorepo while `dev` and `logseq` stay invisible. Reach for one only if a plugin grows a multi-module package with shared third-party dependencies.
- **Repo has no pytest and no CI.** Do not add either.
- **Branch:** create `feat/profile-plugin` before Task 1. Do not commit to `main`.
- **Paths in JSON output are always repo-relative POSIX strings**, sorted, never absolute — except the top-level `root` key.
- **The script classifies what it recognizes and explicitly lists what it does not.** No silent guessing. This is the property the model fallback depends on.
- **No testing vocabulary in `docs`, `topology`, or `journeys` outputs.** Binding, per the spec's extraction discipline: `topology` emits `standup_notes`, never test-boundary options; `journeys` emits no test-coverage hints; `docs` emits requirements, never test ideas.
- **`profile:docs` never builds a document retrieval mechanism.** Binding, per the spec. It reads in-repo files with Read/Glob/Grep, reaches user-named external sources only through a capability already present in the session (WebFetch, an MCP the user names, a local path), and records anything it cannot reach in `unavailable_sources[]` with a concrete remedy. No scraping, no guessed URLs, no new plumbing.
- **`profile:docs` never emits journey candidates.** It emits `journey_evidence[]`. Candidate formation and ranking belong to `profile:journeys` alone — one owner per artifact.

## File Structure

```
ruff.toml                             # NEW: repo-wide lint config (Task 1)

profile/
  .claude-plugin/plugin.json          # plugin manifest
  scripts/
    profile_inventory.py              # CLI entry point, arg parsing, exit codes
    inventorylib/
      __init__.py                     # version constant only
      walk.py                         # git-aware file listing + skip rules
      languages.py                    # extension -> language, unrecognized census
      manifests.py                    # manifest/lockfile -> ecosystem, package manager
      testfiles.py                    # test-file census + kind classification signals
      infra.py                        # CI, containers, IaC, test config, entrypoints
      docs.py                         # documentation census: doc_type guess, size, mtime, doc sites
      report.py                       # assembly, unclassified, coverage_confidence
  references/
    ecosystems.md                     # manifest/lockfile signatures for model fallback
    deployment-shapes.md              # deployment signatures -> shape + testability
    doc-sources.md                    # source tiers, doc_type vocabulary, ranking, remedies
    journey-sources.md                # where journeys hide, how to rank
    contracts/stack.schema.json
    contracts/docs.schema.json
    contracts/topology.schema.json
    contracts/journeys.schema.json
    contracts/examples/stack.example.json
    contracts/examples/docs.example.json
    contracts/examples/topology.example.json
    contracts/examples/journeys.example.json
  skills/
    stack/SKILL.md
    docs/SKILL.md
    topology/SKILL.md
    journeys/SKILL.md

tests/
  schema_check.py                     # dependency-free JSON Schema subset validator (test helper)
  repobuilder.py                      # builds synthetic repo trees in temp dirs (test helper)
  test_profile_walk.py
  test_profile_languages.py
  test_profile_manifests.py
  test_profile_testfiles.py
  test_profile_infra.py
  test_profile_docs.py
  test_profile_report.py
  test_profile_cli.py
  test_profile_contracts.py
  test_plugin_structure.py
```

**Why `docs.py` is its own module rather than more of `infra.py`:** the documentation
census needs `git log` for last-modified times, a filename-and-path type guess, and
docs-site config parsing. That is a different job from "is this file a Dockerfile", and
`infra.py` is already the widest module in the package.

**Deliberate refinement of the spec:** the spec proposed committed fixture repos under `tests/fixtures/profile_inventory/`. This plan builds synthetic repos in temp directories instead (`tests/repobuilder.py`). Committing a tree containing `go.mod`, `package.json`, and `pyproject.toml` into this repo would confuse repo-level tooling and the plugin's own inventory script when run on itself. The test coverage is identical; the fixtures are declarative dicts inside the test modules.

---

### Task 1: Repo file listing

**Files:**
- Create: `ruff.toml` (repo root)
- Create: `profile/scripts/inventorylib/__init__.py`
- Create: `profile/scripts/inventorylib/walk.py`
- Create: `tests/repobuilder.py`
- Test: `tests/test_profile_walk.py`

**Interfaces:**
- Consumes: nothing
- Produces: `walk_repo(root: Path) -> tuple[list[str], str]` returning sorted repo-relative POSIX paths and the listing method (`"git"` or `"walk"`). `SKIP_DIRS: set[str]`. Test helper `build_repo(base: Path, files: dict[str, str]) -> Path`.

- [ ] **Step 1: Write the test helper**

```python
# tests/repobuilder.py
"""Build synthetic repo trees in a temp directory for inventory tests."""

import subprocess
from pathlib import Path


def build_repo(base, files):
    """Create files under base. Keys are repo-relative POSIX paths, values file text.

    Returns base as a Path.
    """
    base = Path(base)
    for rel, text in files.items():
        path = base / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return base


def git_init(base):
    """Initialize a git repo at base and stage nothing. Returns base."""
    base = Path(base)
    subprocess.run(["git", "init", "-q", str(base)], check=True)
    return base
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_profile_walk.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.walk import SKIP_DIRS, walk_repo
from repobuilder import build_repo, git_init


class TestWalkRepo(unittest.TestCase):
    def test_lists_files_relative_and_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "b.py": "x = 1\n",
                "a.py": "y = 2\n",
                "pkg/c.py": "z = 3\n",
            })
            files, method = walk_repo(root)
            self.assertEqual(files, ["a.py", "b.py", "pkg/c.py"])
            self.assertEqual(method, "walk")

    def test_skips_noise_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                "app.py": "x = 1\n",
                "node_modules/left-pad/index.js": "//\n",
                ".venv/lib/thing.py": "x = 1\n",
                "dist/bundle.js": "//\n",
            })
            files, _ = walk_repo(root)
            self.assertEqual(files, ["app.py"])

    def test_uses_git_listing_and_honors_gitignore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {
                ".gitignore": "secret.txt\n",
                "app.py": "x = 1\n",
                "secret.txt": "shh\n",
            })
            git_init(root)
            files, method = walk_repo(root)
            self.assertEqual(method, "git")
            self.assertIn("app.py", files)
            self.assertNotIn("secret.txt", files)

    def test_skip_dirs_contains_expected_entries(self):
        self.assertTrue({"node_modules", ".venv", "vendor", "dist"} <= SKIP_DIRS)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_walk -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib'`

- [ ] **Step 4: Write the implementation**

```python
# profile/scripts/inventorylib/__init__.py
"""Deterministic repo inventory for the profile plugin."""

VERSION = "1.0.0"
```

```python
# profile/scripts/inventorylib/walk.py
"""Repo file listing: git-aware, with a filesystem fallback."""

import subprocess
from pathlib import Path

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "vendor", "dist", "build", "target", "out", "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next",
    ".gradle", "site-packages", ".idea",
}


def _skipped(rel):
    return any(part in SKIP_DIRS for part in Path(rel).parts)


def _git_files(root):
    """Return git's view of the repo, or None if root is not a usable git repo."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "--others",
             "--exclude-standard"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return [line for line in proc.stdout.splitlines() if line]


def _walk_files(root):
    found = []
    for path in Path(root).rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if not _skipped(rel):
            found.append(rel)
    return found


def walk_repo(root):
    """Return (sorted repo-relative POSIX paths, method) where method is git|walk."""
    root = Path(root)
    files = _git_files(root)
    if files is None:
        return sorted(_walk_files(root)), "walk"
    return sorted(f for f in files if not _skipped(f)), "git"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_walk -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Add the repo-wide lint config**

This repo has no ruff configuration, so results currently depend on the developer's global ruff settings — running `ruff check` here today surfaces rules (`RUF100`, `UP006`, `SIM115`, `DTZ005`) that are not ruff defaults. Pin it so lint is deterministic for everyone. Create `ruff.toml` at the repo root:

```toml
target-version = "py311"
line-length = 110
exclude = ["**/.venv", "writing/skills/boring/dist"]

[lint]
select = ["E", "F", "I", "BLE"]

[lint.isort]
known-first-party = ["inventorylib"]

[lint.per-file-ignores]
# Test modules must mutate sys.path before importing plugin scripts, which
# are invoked by path and are not installed packages.
"tests/*.py" = ["E402", "I001"]
```

This is config only — no `[project]` table, no build system. It deliberately does not make the repo look like a Python package, and `profile_inventory.py` correctly continues to report this repo as having no manifests.

Verify the per-file-ignores take effect:

Run: `ruff check tests/test_profile_walk.py tests/repobuilder.py`
Expected: `All checks passed!` — in particular no `E402` from the `sys.path.insert` pattern.

- [ ] **Step 7: Lint the new code**

Run: `ruff check profile/ tests/test_profile_walk.py tests/repobuilder.py`
Expected: `All checks passed!`

Do not run `ruff check tests/` — 13 pre-existing errors in other test modules are out of scope for this plan.

- [ ] **Step 8: Commit**

```bash
git add ruff.toml profile/scripts/inventorylib tests/test_profile_walk.py tests/repobuilder.py
git commit -m "feat(profile): git-aware repo file listing for inventory

Adds a root ruff.toml so lint results no longer depend on global config."
```

---

### Task 2: Language classification

**Files:**
- Create: `profile/scripts/inventorylib/languages.py`
- Test: `tests/test_profile_languages.py`

**Interfaces:**
- Consumes: `walk_repo` output (a list of POSIX path strings)
- Produces: `classify_languages(paths: list[str]) -> tuple[list[dict], list[str]]`. First element is language records `{"name": str, "files": int, "share": float}` sorted by file count descending then name ascending. Second element is paths with an unrecognized, non-ignorable extension — the `unclassified` feed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_languages.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))

from inventorylib.languages import classify_languages


class TestClassifyLanguages(unittest.TestCase):
    def test_counts_and_sorts_by_file_count(self):
        langs, _ = classify_languages(["a.py", "b.py", "c.go"])
        self.assertEqual([entry["name"] for entry in langs], ["python", "go"])
        self.assertEqual(langs[0]["files"], 2)
        self.assertEqual(langs[0]["share"], 0.667)

    def test_ties_break_alphabetically(self):
        langs, _ = classify_languages(["a.go", "b.py"])
        self.assertEqual([entry["name"] for entry in langs], ["go", "python"])

    def test_tsx_and_ts_both_count_as_typescript(self):
        langs, _ = classify_languages(["a.ts", "b.tsx"])
        self.assertEqual(len(langs), 1)
        self.assertEqual(langs[0]["files"], 2)

    def test_ignorable_extensions_are_not_unclassified(self):
        _, unknown = classify_languages(["README.md", "data.json", "logo.png"])
        self.assertEqual(unknown, [])

    def test_unrecognized_source_extension_is_reported(self):
        _, unknown = classify_languages(["thing.zig", "other.nim"])
        self.assertEqual(unknown, ["thing.zig", "other.nim"])

    def test_empty_input_is_safe(self):
        langs, unknown = classify_languages([])
        self.assertEqual(langs, [])
        self.assertEqual(unknown, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_languages -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.languages'`

- [ ] **Step 3: Write the implementation**

```python
# profile/scripts/inventorylib/languages.py
"""Map file extensions to languages and report what could not be classified."""

from pathlib import PurePosixPath

EXT_LANGUAGE = {
    ".py": "python", ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".cs": "csharp", ".php": "php", ".swift": "swift", ".scala": "scala",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".sql": "sql", ".lua": "lua",
    ".dart": "dart", ".clj": "clojure", ".hs": "haskell",
}

IGNORABLE_EXTS = {
    ".md", ".rst", ".txt", ".json", ".yml", ".yaml", ".toml", ".ini",
    ".cfg", ".conf", ".lock", ".csv", ".tsv", ".xml", ".html", ".htm",
    ".css", ".scss", ".less", ".svg", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".webp", ".pdf", ".woff", ".woff2", ".ttf", ".eot",
    ".gitignore", ".gitattributes", ".editorconfig", ".env", ".example",
    ".mod", ".sum", ".log", ".zip", ".gz", ".tar",
}


def classify_languages(paths):
    """Return (language records, paths with an unrecognized source extension)."""
    counts = {}
    unknown = []
    for path in paths:
        ext = PurePosixPath(path).suffix.lower()
        language = EXT_LANGUAGE.get(ext)
        if language:
            counts[language] = counts.get(language, 0) + 1
        elif ext and ext not in IGNORABLE_EXTS:
            unknown.append(path)
    total = sum(counts.values())
    languages = [
        {
            "name": name,
            "files": count,
            "share": round(count / total, 3) if total else 0.0,
        }
        for name, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return languages, unknown
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_languages -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check profile/ tests/test_profile_languages.py
git add profile/scripts/inventorylib/languages.py tests/test_profile_languages.py
git commit -m "feat(profile): language classification with unclassified census"
```

---

### Task 3: Manifest and package-manager detection

**Files:**
- Create: `profile/scripts/inventorylib/manifests.py`
- Test: `tests/test_profile_manifests.py`

**Interfaces:**
- Consumes: `walk_repo` output
- Produces: `detect_manifests(paths: list[str]) -> list[dict]` with records `{"path": str, "ecosystem": str, "package_manager": str | None}`, sorted by path. `MANIFESTS: dict[str, tuple[str, str | None]]`, `LOCKFILE_PM: dict[str, tuple[str, str]]`.

**Lockfile scoping rule (binding):** a lockfile resolves a manifest only when it shares
both the manifest's directory **and** its ecosystem. Amended after review found that
unscoped resolution reports `go.mod` beside a `package-lock.json` as npm-managed — a
confident wrong answer, which this module must never produce.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_manifests.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))

from inventorylib.manifests import detect_manifests


class TestDetectManifests(unittest.TestCase):
    def test_detects_go_module(self):
        found = detect_manifests(["go.mod", "main.go"])
        self.assertEqual(found, [
            {"path": "go.mod", "ecosystem": "go", "package_manager": "go"},
        ])

    def test_lockfile_refines_package_manager(self):
        found = detect_manifests(["pyproject.toml", "uv.lock"])
        self.assertEqual(found[0]["package_manager"], "uv")

    def test_manifest_default_used_when_no_lockfile(self):
        found = detect_manifests(["requirements.txt"])
        self.assertEqual(found[0]["package_manager"], "pip")

    def test_pyproject_without_lockfile_has_no_package_manager(self):
        found = detect_manifests(["pyproject.toml"])
        self.assertIsNone(found[0]["package_manager"])

    def test_lockfile_only_applies_within_same_directory(self):
        found = detect_manifests(["api/package.json", "web/pnpm-lock.yaml"])
        self.assertIsNone(found[0]["package_manager"])

    def test_monorepo_reports_each_manifest_sorted(self):
        found = detect_manifests([
            "web/package.json", "web/yarn.lock", "api/go.mod",
        ])
        self.assertEqual([entry["path"] for entry in found],
                         ["api/go.mod", "web/package.json"])
        self.assertEqual(found[1]["package_manager"], "yarn")

    def test_non_manifest_files_ignored(self):
        self.assertEqual(detect_manifests(["src/app.py", "README.md"]), [])

    def test_lockfile_from_another_ecosystem_never_overrides_a_default(self):
        """A Go module beside a package-lock.json is not npm-managed."""
        found = detect_manifests(["go.mod", "package-lock.json"])
        self.assertEqual(found[0]["package_manager"], "go")

    def test_foreign_lockfile_does_not_invent_a_manager(self):
        found = detect_manifests(["pyproject.toml", "yarn.lock"])
        self.assertIsNone(found[0]["package_manager"])

    def test_competing_lockfiles_resolve_alphabetically(self):
        """Arbitrary but deterministic; pinned so it cannot drift silently."""
        found = detect_manifests(["package.json", "package-lock.json", "yarn.lock"])
        self.assertEqual(found[0]["package_manager"], "npm")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_manifests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.manifests'`

- [ ] **Step 3: Write the implementation**

```python
# profile/scripts/inventorylib/manifests.py
"""Detect dependency manifests and resolve the package manager in use."""

from pathlib import PurePosixPath

# filename -> (ecosystem, default package manager or None if a lockfile decides)
MANIFESTS = {
    "pyproject.toml": ("python", None),
    "requirements.txt": ("python", "pip"),
    "setup.py": ("python", "pip"),
    "Pipfile": ("python", "pipenv"),
    "go.mod": ("go", "go"),
    "package.json": ("node", None),
    "Cargo.toml": ("rust", "cargo"),
    "Gemfile": ("ruby", "bundler"),
    "pom.xml": ("java", "maven"),
    "build.gradle": ("java", "gradle"),
    "build.gradle.kts": ("kotlin", "gradle"),
    "composer.json": ("php", "composer"),
    "mix.exs": ("elixir", "mix"),
    "Package.swift": ("swift", "spm"),
    "pubspec.yaml": ("dart", "pub"),
}

# filename -> (ecosystem, package manager)
LOCKFILE_PM = {
    "uv.lock": ("python", "uv"),
    "poetry.lock": ("python", "poetry"),
    "pdm.lock": ("python", "pdm"),
    "Pipfile.lock": ("python", "pipenv"),
    "package-lock.json": ("node", "npm"),
    "yarn.lock": ("node", "yarn"),
    "pnpm-lock.yaml": ("node", "pnpm"),
    "bun.lockb": ("node", "bun"),
}


def detect_manifests(paths):
    """Return manifest records, resolving package manager from sibling lockfiles.

    A lockfile resolves a manifest only when it sits in the same directory AND
    belongs to the same ecosystem. Without the ecosystem check, a Go module
    beside a package-lock.json reports as npm-managed — a confident wrong
    answer, which is precisely what this module must never produce.

    Two lockfiles of the same ecosystem in one directory (npm and yarn, say)
    resolve alphabetically. That tie-break is arbitrary but deterministic, and
    a test pins it so it cannot drift silently.
    """
    locks_by_dir = {}
    for path in paths:
        parsed = PurePosixPath(path)
        entry = LOCKFILE_PM.get(parsed.name)
        if entry:
            locks_by_dir.setdefault(parsed.parent.as_posix(), set()).add(entry)

    found = []
    for path in sorted(paths):
        parsed = PurePosixPath(path)
        entry = MANIFESTS.get(parsed.name)
        if not entry:
            continue
        ecosystem, default_manager = entry
        siblings = sorted(
            manager
            for lock_ecosystem, manager in locks_by_dir.get(parsed.parent.as_posix(), set())
            if lock_ecosystem == ecosystem
        )
        found.append({
            "path": path,
            "ecosystem": ecosystem,
            "package_manager": siblings[0] if siblings else default_manager,
        })
    return found
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_manifests -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check profile/ tests/test_profile_manifests.py
git add profile/scripts/inventorylib/manifests.py tests/test_profile_manifests.py
git commit -m "feat(profile): manifest and package-manager detection"
```

---

### Task 4: Test-file census and kind classification

**Files:**
- Create: `profile/scripts/inventorylib/testfiles.py`
- Test: `tests/test_profile_testfiles.py`

**Interfaces:**
- Consumes: `walk_repo` output plus the repo root (content reads)
- Produces: `classify_test_files(root: Path, paths: list[str], max_bytes: int = 4096) -> list[dict]` with records `{"path": str, "language": str | None, "kind": str, "signals": list[str]}` where `kind` is one of `unit|integration|e2e|unknown`. Also `test_dirs(records: list[dict]) -> list[str]`.

**Kind resolution priority (binding):** any `e2e` signal wins; else any `integration` signal; else a filename-pattern match yields `unit`; else `unknown`. A directory signal alone is never enough to call something a unit test.

**Census admission (binding):** a file enters the census only if its extension maps to a
known language in `EXT_LANGUAGE`. Amended after review: without this guard a directory
signal alone admits non-source files, and `docs/contract/terms.md` and a locale file under
`src/it/` both classify as `integration`. That is the same weakness the priority rule
already forbids for `unit`, and it matters more here — a later consumer reads every
integration file in full. The extension guard is deliberately chosen over trimming `it` and
`contract` from `TEST_DIR_NAMES`, because both are real test conventions (Maven's `src/it/`,
Pact-style contract tests), and over requiring a filename-pattern match, which would lose
Jest's `__tests__/foo.js` where the directory is the only signal.

**Known residual:** the gate excludes non-source files only. A *source* file in an
ambiguously-named directory — `src/it/messages.py` in an i18n project, where `it` is the
Italian locale code rather than Maven's integration-test directory — still classifies as
`integration`. No extension gate can separate those two meanings of `it`; only removing
`it` from `TEST_DIR_NAMES` would, at the cost of missing real Maven integration tests. The
`signals[]` audit trail keeps the call inspectable (`['dir:it']` alone is visibly weak
evidence), and downstream consumers are expected to weigh it. Accepted, not overlooked.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_testfiles.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.testfiles import classify_test_files, test_dirs
from repobuilder import build_repo


def classify(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return classify_test_files(root, sorted(files))


class TestClassifyTestFiles(unittest.TestCase):
    def test_non_test_files_are_excluded(self):
        self.assertEqual(classify({"src/app.py": "x = 1\n"}), [])

    def test_python_name_pattern_is_a_unit_test(self):
        [record] = classify({"tests/test_app.py": "def test_x(): pass\n"})
        self.assertEqual(record["kind"], "unit")
        self.assertEqual(record["language"], "python")
        self.assertIn("name:test_*.py", record["signals"])

    def test_integration_directory_overrides_unit(self):
        [record] = classify({"tests/integration/test_api.py": "def test_x(): pass\n"})
        self.assertEqual(record["kind"], "integration")
        self.assertIn("dir:integration", record["signals"])

    def test_pytest_marker_detected_from_content(self):
        [record] = classify({
            "tests/test_api.py": "import pytest\n\n@pytest.mark.integration\ndef test_x(): pass\n",
        })
        self.assertEqual(record["kind"], "integration")
        self.assertIn("marker:pytest.mark.integration", record["signals"])

    def test_go_build_tag_detected(self):
        [record] = classify({
            "api/client_test.go": "//go:build integration\n\npackage api\n",
        })
        self.assertEqual(record["kind"], "integration")
        self.assertIn("buildtag:integration", record["signals"])
        self.assertEqual(record["language"], "go")

    def test_e2e_beats_integration(self):
        [record] = classify({"tests/e2e/integration/flow.spec.ts": "it('x', () => {})\n"})
        self.assertEqual(record["kind"], "e2e")

    def test_directory_signal_alone_is_unknown(self):
        [record] = classify({"tests/helpers.py": "VALUE = 1\n"})
        self.assertEqual(record["kind"], "unknown")

    def test_markdown_in_a_test_directory_is_not_a_test_file(self):
        """A directory signal alone must not admit a non-source file."""
        self.assertEqual(classify({"docs/contract/terms.md": "# Terms\n"}), [])

    def test_locale_data_in_a_test_named_directory_is_excluded(self):
        """'it' is a Maven test convention and an Italian locale code."""
        self.assertEqual(classify({"src/it/messages.json": "{}\n"}), [])

    def test_signals_are_sorted(self):
        [record] = classify({"tests/integration/test_api.py": "def test_x(): pass\n"})
        self.assertEqual(record["signals"], sorted(record["signals"]))

    def test_unreadable_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"tests/test_a.py": "def test_x(): pass\n"})
            records = classify_test_files(root, ["tests/test_a.py", "tests/test_gone.py"])
            self.assertEqual(len(records), 2)


class TestTestDirs(unittest.TestCase):
    def test_unique_sorted_parent_dirs(self):
        records = [
            {"path": "tests/integration/test_a.py"},
            {"path": "tests/integration/test_b.py"},
            {"path": "tests/test_c.py"},
        ]
        self.assertEqual(test_dirs(records), ["tests", "tests/integration"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_testfiles -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.testfiles'`

- [ ] **Step 3: Write the implementation**

```python
# profile/scripts/inventorylib/testfiles.py
"""Census of test files, with the signals behind each kind guess."""

import fnmatch
from pathlib import Path, PurePosixPath

from inventorylib.languages import EXT_LANGUAGE

TEST_DIR_NAMES = {
    "test", "tests", "spec", "specs", "__tests__", "testing",
    "e2e", "integration", "it", "itest", "functional", "acceptance",
    "contract", "endtoend", "end_to_end",
}

INTEGRATION_DIRS = {"integration", "it", "itest", "functional", "acceptance", "contract"}
E2E_DIRS = {"e2e", "endtoend", "end_to_end"}

# (glob, language)
NAME_PATTERNS = (
    ("test_*.py", "python"), ("*_test.py", "python"),
    ("*_test.go", "go"),
    ("*.test.ts", "typescript"), ("*.test.tsx", "typescript"),
    ("*.spec.ts", "typescript"), ("*.spec.tsx", "typescript"),
    ("*.test.js", "javascript"), ("*.spec.js", "javascript"),
    ("*Test.java", "java"), ("*Tests.java", "java"),
    ("*Tests.cs", "csharp"),
    ("*_spec.rb", "ruby"), ("*_test.rb", "ruby"),
    ("*_test.rs", "rust"),
    ("*_test.exs", "elixir"),
)

# (signal name, kind, substrings that trigger it)
CONTENT_MARKERS = (
    ("marker:pytest.mark.integration", "integration", ("pytest.mark.integration",)),
    ("marker:pytest.mark.e2e", "e2e", ("pytest.mark.e2e",)),
    ("buildtag:integration", "integration",
     ("//go:build integration", "// +build integration")),
    ("buildtag:e2e", "e2e", ("//go:build e2e", "// +build e2e")),
    ("marker:testcontainers", "integration", ("testcontainers",)),
)

_KIND_BY_SIGNAL = {name: kind for name, kind, _ in CONTENT_MARKERS}


def _is_source(path):
    """True when the extension maps to a known language.

    Census admission gate. Without it a directory signal alone admits any
    file: `docs/contract/terms.md` and a locale file under `src/it/` both
    come back as integration tests, and a later consumer reads every
    integration file in full.
    """
    return PurePosixPath(path).suffix.lower() in EXT_LANGUAGE


def _name_signals(path):
    """Return (signals, language) for path, or ([], None) if it is not a test file."""
    parsed = PurePosixPath(path)
    signals = [
        "dir:%s" % part for part in parsed.parts[:-1] if part in TEST_DIR_NAMES
    ]
    language = None
    for pattern, pattern_language in NAME_PATTERNS:
        if fnmatch.fnmatch(parsed.name, pattern):
            signals.append("name:%s" % pattern)
            language = pattern_language
            break
    if not signals:
        return [], None
    return signals, language


def _content_signals(full_path, max_bytes):
    try:
        text = Path(full_path).read_text(encoding="utf-8", errors="replace")[:max_bytes]
    except OSError:
        return []
    return [
        name for name, _, needles in CONTENT_MARKERS
        if any(needle in text for needle in needles)
    ]


def _resolve_kind(signals):
    dirs = {signal.split(":", 1)[1] for signal in signals if signal.startswith("dir:")}
    kinds = {_KIND_BY_SIGNAL[s] for s in signals if s in _KIND_BY_SIGNAL}
    if dirs & E2E_DIRS or "e2e" in kinds:
        return "e2e"
    if dirs & INTEGRATION_DIRS or "integration" in kinds:
        return "integration"
    if any(signal.startswith("name:") for signal in signals):
        return "unit"
    return "unknown"


def classify_test_files(root, paths, max_bytes=4096):
    """Return one record per test file, with the signals behind its kind."""
    root = Path(root)
    records = []
    for path in paths:
        if not _is_source(path):
            continue
        signals, language = _name_signals(path)
        if not signals:
            continue
        signals = signals + _content_signals(root / path, max_bytes)
        records.append({
            "path": path,
            "language": language,
            "kind": _resolve_kind(signals),
            "signals": sorted(set(signals)),
        })
    return records


def test_dirs(records):
    """Return the unique sorted parent directories of test-file records."""
    return sorted({PurePosixPath(r["path"]).parent.as_posix() for r in records})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_testfiles -v`
Expected: PASS, 12 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check profile/ tests/test_profile_testfiles.py
git add profile/scripts/inventorylib/testfiles.py tests/test_profile_testfiles.py
git commit -m "feat(profile): test-file census with kind classification signals"
```

---

### Task 5: Infrastructure and entrypoint detection

**Files:**
- Create: `profile/scripts/inventorylib/infra.py`
- Test: `tests/test_profile_infra.py`

**Interfaces:**
- Consumes: `walk_repo` output plus repo root
- Produces: `detect_infra(root: Path, paths: list[str]) -> dict` with keys `ci`, `containers`, `iac`, `test_config`, `entrypoints` — each a sorted list of records containing at least `path`. Documentation is **not** here; it is Task 5b.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_infra.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.infra import detect_infra
from repobuilder import build_repo


def infra(files):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return detect_infra(root, sorted(files))


class TestDetectInfra(unittest.TestCase):
    def test_github_workflows_are_ci(self):
        found = infra({".github/workflows/test.yml": "on: push\n"})
        self.assertEqual(found["ci"], [{"path": ".github/workflows/test.yml",
                                        "system": "github-actions"}])

    def test_gitlab_ci_detected(self):
        found = infra({".gitlab-ci.yml": "stages: [test]\n"})
        self.assertEqual(found["ci"][0]["system"], "gitlab-ci")

    def test_compose_and_dockerfile_detected(self):
        found = infra({"Dockerfile": "FROM scratch\n",
                       "docker-compose.yml": "services: {}\n"})
        kinds = {entry["kind"] for entry in found["containers"]}
        self.assertEqual(kinds, {"dockerfile", "compose"})

    def test_terraform_detected_by_extension(self):
        found = infra({"infra/main.tf": "resource {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "terraform")

    def test_pytest_ini_is_test_config(self):
        found = infra({"pytest.ini": "[pytest]\n"})
        self.assertEqual(found["test_config"][0]["framework"], "pytest")

    def test_package_json_test_script_becomes_test_config(self):
        found = infra({"package.json": '{"scripts": {"test": "vitest run"}}\n'})
        entry = found["test_config"][0]
        self.assertEqual(entry["path"], "package.json")
        self.assertEqual(entry["command"], "vitest run")
        self.assertEqual(entry["framework"], "vitest")

    def test_malformed_package_json_is_skipped_silently(self):
        found = infra({"package.json": "{not json\n"})
        self.assertEqual(found["test_config"], [])

    def test_entrypoints_detected(self):
        found = infra({"cmd/server/main.go": "package main\n", "manage.py": "x = 1\n"})
        paths = {entry["path"] for entry in found["entrypoints"]}
        self.assertEqual(paths, {"cmd/server/main.go", "manage.py"})

    def test_nested_index_is_a_barrel_not_an_entrypoint(self):
        found = infra({"index.js": "run()\n",
                       "src/components/Button/index.ts": "export * from './Button'\n"})
        paths = {entry["path"] for entry in found["entrypoints"]}
        self.assertEqual(paths, {"index.js"})

    def test_sam_template_detected_by_transform(self):
        found = infra({"template.yaml":
                       "Transform: AWS::Serverless-2016-10-31\nResources: {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "sam")

    def test_plain_cloudformation_is_not_called_sam(self):
        found = infra({"infra/template.yaml":
                       "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}\n"})
        self.assertEqual(found["iac"][0]["kind"], "cloudformation")

    def test_issue_form_template_is_not_iac(self):
        found = infra({".github/ISSUE_TEMPLATE/template.yml":
                       "name: Bug report\nbody: []\n"})
        self.assertEqual(found["iac"], [])

    def test_documentation_is_not_this_modules_job(self):
        """Docs are censused by inventorylib.docs (Task 5b), not here."""
        found = infra({"README.md": "# x\n"})
        self.assertNotIn("docs", found)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_infra -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.infra'`

- [ ] **Step 3: Write the implementation**

```python
# profile/scripts/inventorylib/infra.py
"""Detect CI, container, IaC, test-config, and entrypoint artifacts."""

import json
from pathlib import Path, PurePosixPath

CI_FILES = {
    ".gitlab-ci.yml": "gitlab-ci",
    "azure-pipelines.yml": "azure-pipelines",
    "Jenkinsfile": "jenkins",
    ".travis.yml": "travis",
    "bitbucket-pipelines.yml": "bitbucket",
    ".circleci/config.yml": "circleci",
}

CONTAINER_FILES = {
    "Dockerfile": "dockerfile",
    "Containerfile": "dockerfile",
    "docker-compose.yml": "compose",
    "docker-compose.yaml": "compose",
    "compose.yml": "compose",
    "compose.yaml": "compose",
}

IAC_FILES = {
    "cdk.json": "cdk",
    "serverless.yml": "serverless",
    "Chart.yaml": "helm",
    "kustomization.yaml": "kustomize",
    "Pulumi.yaml": "pulumi",
}

# template.yaml is not in IAC_FILES: the name alone proves nothing. A GitHub
# issue form, a Backstage software template, and a SAM stack all ship as
# template.yaml. The file's own content decides — see _template_kind.
TEMPLATE_NAMES = {"template.yaml", "template.yml"}
SAM_TRANSFORM = "AWS::Serverless-2016-10-31"
CFN_MARKER = "AWSTemplateFormatVersion"

IAC_EXTS = {".tf": "terraform", ".tfvars": "terraform", ".bicep": "bicep"}

TEST_CONFIG_FILES = {
    "pytest.ini": "pytest",
    "tox.ini": "tox",
    "jest.config.js": "jest",
    "jest.config.ts": "jest",
    "vitest.config.ts": "vitest",
    "playwright.config.ts": "playwright",
    "karma.conf.js": "karma",
    "phpunit.xml": "phpunit",
    ".rspec": "rspec",
}

ENTRYPOINT_NAMES = {
    "main.py", "__main__.py", "manage.py", "app.py", "wsgi.py", "asgi.py",
    "main.go", "main.rs", "Program.cs", "main.ts", "server.js",
}

# index.* is an entrypoint only at the repo root, where it is npm's default
# main. Nested index.ts/index.js files are barrel re-exports by convention:
# on a measured Angular repo, 14 of 16 name-based entrypoint hits were
# barrels. Root-only keeps the true positive and drops the flood.
ROOT_ONLY_ENTRYPOINTS = {"index.ts", "index.js"}

# ordered: first substring found in the command wins
TEST_COMMAND_FRAMEWORKS = (
    ("vitest", "vitest"), ("jest", "jest"), ("playwright", "playwright"),
    ("mocha", "mocha"), ("ava", "ava"), ("cypress", "cypress"),
    ("pytest", "pytest"), ("go test", "go-test"),
)


def _framework_from_command(command):
    lowered = command.lower()
    for needle, framework in TEST_COMMAND_FRAMEWORKS:
        if needle in lowered:
            return framework
    return None


def _template_kind(root, path):
    """Classify a template.yaml by content, or return None to stay silent.

    SAM templates carry the serverless Transform; plain CloudFormation
    carries AWSTemplateFormatVersion. Anything else named template.yaml —
    issue forms, Backstage templates — is not IaC and must not be labeled.
    """
    try:
        text = (Path(root) / path).read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    if SAM_TRANSFORM in text:
        return "sam"
    if CFN_MARKER in text:
        return "cloudformation"
    return None


def _package_json_test_config(root, path):
    try:
        data = json.loads((Path(root) / path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return None
    command = scripts.get("test")
    if not isinstance(command, str) or not command.strip():
        return None
    return {
        "path": path,
        "framework": _framework_from_command(command),
        "command": command,
    }


def detect_infra(root, paths):
    """Return infrastructure records grouped by kind, each list sorted by path."""
    ci, containers, iac, test_config, entrypoints = [], [], [], [], []

    for path in sorted(paths):
        parsed = PurePosixPath(path)
        name = parsed.name

        if path.startswith(".github/workflows/"):
            ci.append({"path": path, "system": "github-actions"})
        elif path in CI_FILES:
            ci.append({"path": path, "system": CI_FILES[path]})
        elif name in CI_FILES:
            ci.append({"path": path, "system": CI_FILES[name]})

        if name in CONTAINER_FILES:
            containers.append({"path": path, "kind": CONTAINER_FILES[name]})

        if name in IAC_FILES:
            iac.append({"path": path, "kind": IAC_FILES[name]})
        elif name in TEMPLATE_NAMES:
            kind = _template_kind(root, path)
            if kind:
                iac.append({"path": path, "kind": kind})
        elif parsed.suffix in IAC_EXTS:
            iac.append({"path": path, "kind": IAC_EXTS[parsed.suffix]})

        if name in TEST_CONFIG_FILES:
            test_config.append({
                "path": path,
                "framework": TEST_CONFIG_FILES[name],
                "command": None,
            })
        elif name == "package.json":
            entry = _package_json_test_config(root, path)
            if entry:
                test_config.append(entry)

        if name in ENTRYPOINT_NAMES or (
            name in ROOT_ONLY_ENTRYPOINTS and parsed.parent.as_posix() == "."
        ):
            entrypoints.append({"path": path, "language_hint": parsed.suffix})

    return {
        "ci": ci,
        "containers": containers,
        "iac": iac,
        "test_config": test_config,
        "entrypoints": entrypoints,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_infra -v`
Expected: PASS, 13 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check profile/ tests/test_profile_infra.py
git add profile/scripts/inventorylib/infra.py tests/test_profile_infra.py
git commit -m "feat(profile): CI, container, IaC, test-config, and entrypoint detection"
```

---

### Task 5b: Documentation census

> Inserted after the original plan was written, when documentation analysis was added
> to the spec. Numbered `5b` rather than renumbering Tasks 6–12, because the `itest`
> plan and several steps below reference those numbers by name.

**Files:**
- Create: `profile/scripts/inventorylib/docs.py`
- Modify: `tests/repobuilder.py` (add `git_commit_all`)
- Test: `tests/test_profile_docs.py`

**Interfaces:**
- Consumes: `walk_repo` output plus the repo root
- Produces: `detect_docs(root: Path, paths: list[str], max_git_lookups: int = 500) -> dict`
  with two keys:
  - `docs` — `[{path, doc_type_guess, size, last_modified}]` sorted by path.
    `last_modified` is an ISO-8601 committer date string, or `null` when git has no
    record of the file (uncommitted, or not a git repo).
  - `docs_sites` — `[{path, generator}]` sorted by path.
  Also `DOC_TYPES: tuple[str, ...]`, the fixed vocabulary, and
  `guess_doc_type(path: str) -> str`.

**The vocabulary is fixed and closed** (spec, `profile:docs` section). `doc_type_guess`
is always one of: `prd`, `requirements`, `spec`, `design`, `architecture`, `adr`,
`runbook`, `api_reference`, `user_guide`, `tutorial`, `readme`, `changelog`, `unknown`.
A doc-shaped file that matches nothing is `unknown` — never a confident wrong label.

**Why token matching, not substring matching:** `"api" in "capital"` and
`"adr" in "quadrant"` are both true. Paths are split into alphanumeric tokens and
matched by token membership, so `docs/api/orders.md` types as `api_reference` and
`src/capital.md` does not.

- [ ] **Step 1: Add the commit helper to the test builder**

Append to `tests/repobuilder.py`:

```python
def git_commit_all(base, message="init"):
    """Commit everything under base. Requires git_init to have run. Returns base."""
    base = Path(base)
    env = {
        "GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
        "PATH": os.environ.get("PATH", ""),
    }
    subprocess.run(["git", "-C", str(base), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(base), "commit", "-q", "-m", message],
                   check=True, env=env)
    return base
```

Add `import os` to the module's imports.

The `GIT_CONFIG_GLOBAL=/dev/null` line matters: without it the test inherits the
developer's global git config, including any commit hooks or signing requirements, and
fails on some machines and not others.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_profile_docs.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.docs import DOC_TYPES, detect_docs, guess_doc_type
from repobuilder import build_repo, git_commit_all, git_init


def census(files, **kwargs):
    with tempfile.TemporaryDirectory() as tmp:
        root = build_repo(tmp, files)
        return detect_docs(root, sorted(files), **kwargs)


class TestGuessDocType(unittest.TestCase):
    def test_readme_and_changelog_by_stem(self):
        self.assertEqual(guess_doc_type("README.md"), "readme")
        self.assertEqual(guess_doc_type("CHANGELOG.md"), "changelog")

    def test_type_from_path_tokens(self):
        cases = {
            "docs/prd-billing.md": "prd",
            "docs/requirements/orders.md": "requirements",
            "docs/adr/0004-use-postgres.md": "adr",
            "docs/rfcs/0001-events.md": "spec",
            "docs/architecture.md": "architecture",
            "docs/runbook-oncall.md": "runbook",
            "docs/api/orders.md": "api_reference",
            "docs/getting-started.md": "tutorial",
            "docs/user-guide.md": "user_guide",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(guess_doc_type(path), expected)

    def test_untypable_doc_is_unknown_not_a_wrong_guess(self):
        self.assertEqual(guess_doc_type("docs/notes.md"), "unknown")

    def test_tokens_not_substrings(self):
        """'api' in 'capital' is true; token matching must not be fooled."""
        self.assertEqual(guess_doc_type("docs/capital.md"), "unknown")

    def test_filename_tokens_outrank_directory_tokens(self):
        """docs/design/setup-tutorial.md is a tutorial filed under design/."""
        self.assertEqual(guess_doc_type("docs/design/setup-tutorial.md"), "tutorial")
        self.assertEqual(guess_doc_type("docs/specs/deployment-runbook.md"), "runbook")

    def test_nearest_directory_wins_when_the_filename_says_nothing(self):
        self.assertEqual(guess_doc_type("docs/design/api/orders.md"), "api_reference")

    def test_every_guess_is_in_the_fixed_vocabulary(self):
        for path in ("README.md", "docs/x.md", "docs/adr/1-y.md", "CHANGELOG.md"):
            with self.subTest(path=path):
                self.assertIn(guess_doc_type(path), DOC_TYPES)


class TestDetectDocs(unittest.TestCase):
    def test_collects_named_docs_and_doc_directories(self):
        found = census({
            "README.md": "# x\n",
            "docs/guide.md": "# y\n",
            "specs/auth.md": "# z\n",
            "src/app.py": "x = 1\n",
        })
        self.assertEqual([d["path"] for d in found["docs"]],
                         ["README.md", "docs/guide.md", "specs/auth.md"])

    def test_markdown_beside_code_is_not_documentation(self):
        found = census({"src/notes.md": "# z\n"})
        self.assertEqual(found["docs"], [])

    def test_size_is_recorded(self):
        found = census({"docs/guide.md": "hello\n"})
        self.assertEqual(found["docs"][0]["size"], 6)

    def test_last_modified_is_null_outside_git(self):
        found = census({"docs/guide.md": "# y\n"})
        self.assertIsNone(found["docs"][0]["last_modified"])

    def test_last_modified_comes_from_git_when_committed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"docs/guide.md": "# y\n"})
            git_init(root)
            git_commit_all(root)
            found = detect_docs(root, ["docs/guide.md"])
        stamp = found["docs"][0]["last_modified"]
        self.assertIsInstance(stamp, str)
        self.assertRegex(stamp, r"^\d{4}-\d{2}-\d{2}T")

    def test_git_lookups_are_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            files = {"docs/d%02d.md" % i: "# x\n" for i in range(3)}
            root = build_repo(tmp, files)
            git_init(root)
            git_commit_all(root)
            found = detect_docs(root, sorted(files), max_git_lookups=1)
        stamps = [d["last_modified"] for d in found["docs"]]
        self.assertIsInstance(stamps[0], str)
        self.assertEqual(stamps[1:], [None, None])

    def test_doc_sites_detected(self):
        found = census({"mkdocs.yml": "site_name: x\n",
                        "web/docusaurus.config.js": "module.exports = {}\n"})
        self.assertEqual(
            [(s["path"], s["generator"]) for s in found["docs_sites"]],
            [("mkdocs.yml", "mkdocs"), ("web/docusaurus.config.js", "docusaurus")])

    def test_sphinx_conf_counts_only_inside_a_doc_directory(self):
        found = census({"docs/conf.py": "project = 'x'\n", "src/conf.py": "X = 1\n"})
        self.assertEqual([s["path"] for s in found["docs_sites"]], ["docs/conf.py"])

    def test_no_documentation_yields_empty_lists_not_guesses(self):
        found = census({"src/app.py": "x = 1\n"})
        self.assertEqual(found["docs"], [])
        self.assertEqual(found["docs_sites"], [])

    def test_missing_file_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"docs/a.md": "# a\n"})
            found = detect_docs(root, ["docs/a.md", "docs/gone.md"])
        self.assertEqual([d["size"] for d in found["docs"]], [4, None])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_docs -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.docs'`

- [ ] **Step 4: Write the implementation**

```python
# profile/scripts/inventorylib/docs.py
"""Documentation census: what docs exist, roughly what kind, and how stale.

Classifies by path tokens only. It never reads document content and never
guesses outside the fixed vocabulary — an untypable doc is 'unknown', which is
the signal that tells profile:docs to read it rather than trust the label.
"""

import re
import subprocess
from pathlib import Path, PurePosixPath

DOC_TYPES = (
    "prd", "requirements", "spec", "design", "architecture", "adr",
    "runbook", "api_reference", "user_guide", "tutorial", "readme",
    "changelog", "unknown",
)

DOC_EXTS = {".md", ".rst", ".adoc", ".txt"}

DOC_DIRS = {
    "docs", "doc", "documentation", "adr", "adrs", "decisions",
    "rfc", "rfcs", "spec", "specs", "design", "wiki", "notes",
}

DOC_NAMES = {
    "README.md", "README.rst", "README.txt",
    "CONTRIBUTING.md", "ARCHITECTURE.md", "CHANGELOG.md", "CHANGELOG.rst",
}

STEM_TYPES = {
    "readme": "readme",
    "changelog": "changelog",
    "changes": "changelog",
    "history": "changelog",
}

# ordered: the first token that matches wins
TOKEN_TYPES = (
    ({"prd", "prds"}, "prd"),
    ({"requirement", "requirements", "acceptance"}, "requirements"),
    ({"adr", "adrs", "decision", "decisions"}, "adr"),
    ({"rfc", "rfcs", "spec", "specs", "specification"}, "spec"),
    ({"architecture", "architectural"}, "architecture"),
    ({"design"}, "design"),
    ({"runbook", "runbooks", "playbook"}, "runbook"),
    ({"api", "reference"}, "api_reference"),
    ({"tutorial", "tutorials", "quickstart"}, "tutorial"),
    ({"guide", "guides", "howto", "contributing"}, "user_guide"),
)

DOC_SITE_FILES = {
    "mkdocs.yml": "mkdocs",
    "mkdocs.yaml": "mkdocs",
    "docusaurus.config.js": "docusaurus",
    "docusaurus.config.ts": "docusaurus",
    "book.toml": "mdbook",
    "antora.yml": "antora",
}

# Sphinx's conf.py is only a doc site when it sits inside a doc directory;
# 'conf.py' is far too common a filename to trust on its own.
SPHINX_CONF = "conf.py"

_TOKENS = re.compile(r"[^a-z0-9]+")


def _tokens(path):
    return {token for token in _TOKENS.split(path.lower()) if token}


def _match_tokens(tokens):
    """Return a doc type for one path segment's tokens, or None."""
    if {"getting", "started"} <= tokens or {"get", "started"} <= tokens:
        return "tutorial"
    for names, doc_type in TOKEN_TYPES:
        if tokens & names:
            return doc_type
    return None


def guess_doc_type(path):
    """Return one of DOC_TYPES for path. Nearer path segments outrank farther ones.

    A file's own name is the strongest signal: docs/design/setup-tutorial.md
    is a tutorial that happens to live under design/, not a design doc. When
    the filename says nothing, the nearest ancestor directory that says
    something wins: docs/design/api/orders.md is API reference filed under
    design/. Amended after review found pooled whole-path tokens let an
    ancestor directory confidently override an explicit filename.
    """
    parsed = PurePosixPath(path)
    stem_type = STEM_TYPES.get(parsed.stem.lower())
    if stem_type:
        return stem_type
    for part in reversed(parsed.parts):
        doc_type = _match_tokens(_tokens(part))
        if doc_type:
            return doc_type
    return "unknown"


def _in_doc_dir(path):
    """True when any ancestor directory is a recognized documentation directory."""
    return any(part.lower() in DOC_DIRS for part in PurePosixPath(path).parts[:-1])


def _is_doc(path):
    parsed = PurePosixPath(path)
    if parsed.name in DOC_NAMES:
        return True
    if parsed.suffix.lower() not in DOC_EXTS:
        return False
    return _in_doc_dir(path)


def _git_available(root):
    """One probe so a non-git tree does not pay one doomed subprocess per doc."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def _git_last_modified(root, path):
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%cI", "--", path],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def _size(root, path):
    try:
        return (Path(root) / path).stat().st_size
    except OSError:
        return None


def _doc_sites(paths):
    sites = []
    for path in sorted(paths):
        parsed = PurePosixPath(path)
        generator = DOC_SITE_FILES.get(parsed.name)
        if generator is None and parsed.name == SPHINX_CONF:
            if _in_doc_dir(path):
                generator = "sphinx"
        if generator:
            sites.append({"path": path, "generator": generator})
    return sites


def detect_docs(root, paths, max_git_lookups=500):
    """Return {'docs': [...], 'docs_sites': [...]}, both sorted by path.

    Git lookups are capped: beyond max_git_lookups, last_modified is None. A
    thousand-page docs site should not turn the census into a thousand
    subprocess calls, and a non-git tree pays one probe rather than one
    failed subprocess per document.
    """
    root = Path(root)
    docs = []
    lookups = 0
    use_git = _git_available(root)
    for path in sorted(p for p in paths if _is_doc(p)):
        if use_git and lookups < max_git_lookups:
            last_modified = _git_last_modified(root, path)
            lookups += 1
        else:
            last_modified = None
        docs.append({
            "path": path,
            "doc_type_guess": guess_doc_type(path),
            "size": _size(root, path),
            "last_modified": last_modified,
        })
    return {"docs": docs, "docs_sites": _doc_sites(paths)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_docs -v`
Expected: PASS, 17 tests

- [ ] **Step 6: Lint and commit**

```bash
ruff check profile/ tests/test_profile_docs.py tests/repobuilder.py
git add profile/scripts/inventorylib/docs.py tests/test_profile_docs.py tests/repobuilder.py
git commit -m "feat(profile): documentation census with fixed doc-type vocabulary"
```

---

### Task 6: Inventory assembly and confidence

**Files:**
- Create: `profile/scripts/inventorylib/report.py`
- Test: `tests/test_profile_report.py`

**Interfaces:**
- Consumes: `walk_repo`, `classify_languages`, `detect_manifests`, `classify_test_files`, `test_dirs`, `detect_infra`, `detect_docs`
- Produces: `build_inventory(root: Path) -> dict` (the full inventory object) and `coverage_confidence(languages, manifests, unclassified, total_files) -> str`.

**Confidence rules (binding):** `low` when there are no recognized languages **or** no manifests. Otherwise `high` when unclassified paths are at most 5% of all files, else `partial`. `unclassified` is truncated to 200 entries; when truncation occurs the count is preserved in `unclassified_total`.

**Docs truncation (binding, amended after Task 5b review):** `docs` receives the same
treatment as `unclassified` — truncated to `DOCS_LIMIT = 200` records with the full count
preserved in `docs_total`. Without this, a 3k-page docs site embeds hundreds of KB of
census records verbatim in the `stack` contract handed to every downstream phase. The
census itself stays complete inside `detect_docs`; only the assembled inventory truncates.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_report.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from inventorylib.report import build_inventory, coverage_confidence
from repobuilder import build_repo

PY_REPO = {
    "pyproject.toml": "[project]\nname = 'demo'\n",
    "uv.lock": "version = 1\n",
    "src/app.py": "def run(): pass\n",
    "tests/integration/test_api.py": "def test_x(): pass\n",
    "docker-compose.yml": "services: {}\n",
    "README.md": "# demo\n",
}


def inventory(files):
    with tempfile.TemporaryDirectory() as tmp:
        return build_inventory(build_repo(tmp, files))


class TestCoverageConfidence(unittest.TestCase):
    def test_no_languages_is_low(self):
        self.assertEqual(coverage_confidence([], [{"path": "go.mod"}], [], 3), "low")

    def test_no_manifests_is_low(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [], [], 3), "low")

    def test_mostly_classified_is_high(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}], [], 100),
            "high")

    def test_many_unclassified_is_partial(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}],
                                ["a.zig"] * 20, 100),
            "partial")

    def test_share_of_exactly_five_percent_is_still_high(self):
        """The binding rule says at most 5%; the boundary belongs to high."""
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}],
                                ["a.zig"] * 5, 100),
            "high")

    def test_share_just_above_five_percent_is_partial(self):
        self.assertEqual(
            coverage_confidence([{"name": "python"}], [{"path": "go.mod"}],
                                ["a.zig"] * 6, 100),
            "partial")


class TestBuildInventory(unittest.TestCase):
    def test_has_all_required_keys(self):
        found = inventory(PY_REPO)
        self.assertEqual(set(found), {
            "root", "listing_method", "languages", "manifests", "test_files",
            "test_dirs", "test_config", "ci", "containers", "iac",
            "entrypoints", "docs", "docs_total", "docs_sites", "unclassified",
            "unclassified_total", "coverage_confidence", "inventory_version",
        })

    def test_root_is_absolute_and_paths_are_relative(self):
        found = inventory(PY_REPO)
        self.assertTrue(Path(found["root"]).is_absolute())
        self.assertEqual(found["manifests"][0]["path"], "pyproject.toml")

    def test_python_repo_is_classified_end_to_end(self):
        found = inventory(PY_REPO)
        self.assertEqual(found["languages"][0]["name"], "python")
        self.assertEqual(found["manifests"][0]["package_manager"], "uv")
        self.assertEqual(found["test_files"][0]["kind"], "integration")
        self.assertEqual(found["test_dirs"], ["tests/integration"])
        self.assertEqual(found["containers"][0]["kind"], "compose")
        self.assertEqual(found["coverage_confidence"], "high")

    def test_documentation_census_is_carried_into_the_inventory(self):
        found = inventory(PY_REPO)
        self.assertEqual([d["path"] for d in found["docs"]], ["README.md"])
        self.assertEqual(found["docs"][0]["doc_type_guess"], "readme")
        self.assertEqual(found["docs_total"], 1)
        self.assertEqual(found["docs_sites"], [])

    def test_docs_are_truncated_with_total_preserved(self):
        files = {"docs/d%03d.md" % i: "# x\n" for i in range(250)}
        found = inventory(files)
        self.assertEqual(len(found["docs"]), 200)
        self.assertEqual(found["docs_total"], 250)

    def test_infra_classified_files_are_not_unclassified(self):
        """The inventory must not contradict itself: recognized IaC is not
        unknown, and confidence does not degrade for understood files."""
        found = inventory({
            "pyproject.toml": "[project]\nname = 'demo'\n",
            "uv.lock": "version = 1\n",
            "app.py": "x = 1\n",
            "infra/main.tf": "resource {}\n",
            "infra/vars.tfvars": "v = 1\n",
        })
        self.assertEqual([r["path"] for r in found["iac"]],
                         ["infra/main.tf", "infra/vars.tfvars"])
        self.assertEqual(found["unclassified"], [])
        self.assertEqual(found["coverage_confidence"], "high")

    def test_confidence_is_computed_before_truncation(self):
        """300 unclassified in 4000 files is 7.5% -> partial. Computing from
        the truncated list would floor it at 200/4000 = 5% -> high."""
        files = {"src/f%04d.py" % i: "x = 1\n" for i in range(3699)}
        files.update({"odd/f%03d.zig" % i: "x\n" for i in range(300)})
        files["pyproject.toml"] = "[project]\nname = 'demo'\n"
        found = inventory(files)
        self.assertEqual(found["unclassified_total"], 300)
        self.assertEqual(len(found["unclassified"]), 200)
        self.assertEqual(found["coverage_confidence"], "partial")

    def test_unrecognized_stack_reports_low_confidence_not_a_wrong_answer(self):
        found = inventory({"main.zig": "pub fn main() void {}\n",
                           "build.zig": "pub fn build() void {}\n"})
        self.assertEqual(found["languages"], [])
        self.assertEqual(found["manifests"], [])
        self.assertEqual(found["coverage_confidence"], "low")
        self.assertEqual(sorted(found["unclassified"]), ["build.zig", "main.zig"])

    def test_unclassified_is_truncated_with_total_preserved(self):
        files = {"f%03d.zig" % i: "x\n" for i in range(250)}
        found = inventory(files)
        self.assertEqual(len(found["unclassified"]), 200)
        self.assertEqual(found["unclassified_total"], 250)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_report -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'inventorylib.report'`

- [ ] **Step 3: Write the implementation**

```python
# profile/scripts/inventorylib/report.py
"""Assemble the full repo inventory."""

from pathlib import Path

from inventorylib import VERSION
from inventorylib.docs import detect_docs
from inventorylib.infra import detect_infra
from inventorylib.languages import classify_languages
from inventorylib.manifests import detect_manifests
from inventorylib.testfiles import classify_test_files, test_dirs
from inventorylib.walk import walk_repo

UNCLASSIFIED_LIMIT = 200
DOCS_LIMIT = 200
HIGH_CONFIDENCE_MAX_UNCLASSIFIED_SHARE = 0.05


def coverage_confidence(languages, manifests, unclassified, total_files):
    """Return high|partial|low for how much of the repo was understood."""
    if not languages or not manifests:
        return "low"
    share = len(unclassified) / total_files if total_files else 0.0
    if share <= HIGH_CONFIDENCE_MAX_UNCLASSIFIED_SHARE:
        return "high"
    return "partial"


def build_inventory(root):
    """Walk root and return the complete inventory object."""
    root = Path(root)
    paths, method = walk_repo(root)
    languages, unclassified = classify_languages(paths)
    manifests = detect_manifests(paths)
    tests = classify_test_files(root, paths)
    infra = detect_infra(root, paths)
    docs = detect_docs(root, paths)

    # A path the infra census recognized is not unclassified, whatever the
    # language census thinks: .tf/.tfvars/.bicep carry no language, but the
    # inventory understands them. Without this subtraction the same file is
    # reported as recognized IaC AND unknown, and confidence degrades for a
    # repo the census fully understood — a self-contradictory inventory.
    known = {
        record["path"]
        for section in (infra["ci"], infra["containers"], infra["iac"],
                        infra["test_config"], infra["entrypoints"])
        for record in section
    }
    unclassified = [p for p in unclassified if p not in known]

    return {
        "inventory_version": VERSION,
        "root": str(root.resolve()),
        "listing_method": method,
        "languages": languages,
        "manifests": manifests,
        "test_files": tests,
        "test_dirs": test_dirs(tests),
        "test_config": infra["test_config"],
        "ci": infra["ci"],
        "containers": infra["containers"],
        "iac": infra["iac"],
        "entrypoints": infra["entrypoints"],
        "docs": docs["docs"][:DOCS_LIMIT],
        "docs_total": len(docs["docs"]),
        "docs_sites": docs["docs_sites"],
        "unclassified": sorted(unclassified)[:UNCLASSIFIED_LIMIT],
        "unclassified_total": len(unclassified),
        "coverage_confidence": coverage_confidence(
            languages, manifests, unclassified, len(paths)),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_report -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Lint and commit**

```bash
ruff check profile/ tests/test_profile_report.py
git add profile/scripts/inventorylib/report.py tests/test_profile_report.py
git commit -m "feat(profile): inventory assembly with coverage confidence"
```

---

### Task 7: CLI entry point

**Files:**
- Create: `profile/scripts/profile_inventory.py`
- Test: `tests/test_profile_cli.py`

**Interfaces:**
- Consumes: `build_inventory`
- Produces: `main(argv: list[str] | None = None) -> int`. Exit 0 on success including partial results; exit 2 on an unusable path. JSON goes to stdout; errors go to stderr as JSON.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_cli.py
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "profile" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import profile_inventory
from repobuilder import build_repo


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = profile_inventory.main(argv)
    return code, out.getvalue(), err.getvalue()


class TestCli(unittest.TestCase):
    def test_emits_json_and_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n", "main.go": "package main\n"})
            code, out, _ = run([str(root)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["languages"][0]["name"], "go")

    def test_json_flag_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            code, out, _ = run([str(root), "--json"])
        self.assertEqual(code, 0)
        self.assertIn("coverage_confidence", json.loads(out))

    def test_output_is_deterministic_with_sorted_keys(self):
        """The determinism contract: sorted keys, byte-stable across runs."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            _, first, _ = run([str(root)])
            _, second, _ = run([str(root)])
        self.assertEqual(first, second)
        self.assertEqual(
            first, json.dumps(json.loads(first), indent=2, sort_keys=True) + "\n")

    def test_indent_flag_changes_formatting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"go.mod": "module x\n"})
            _, compact, _ = run([str(root), "--indent", "0"])
            _, pretty, _ = run([str(root), "--indent", "4"])
        self.assertLess(len(compact.splitlines()), len(pretty.splitlines()))

    def test_missing_path_exits_two_with_json_error(self):
        code, out, err = run(["/nonexistent/path/xyz"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("error", json.loads(err))

    def test_file_instead_of_directory_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"a.py": "x = 1\n"})
            code, _, _ = run([str(root / "a.py")])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'profile_inventory'`

- [ ] **Step 3: Write the implementation**

```python
#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Emit a deterministic JSON inventory of a repository.

Usage:
    uv run --script profile_inventory.py [PATH] [--json] [--indent N]
    python3 profile_inventory.py [PATH] [--json] [--indent N]   # fallback; no deps

Exit codes:
    0  inventory emitted (possibly partial; see coverage_confidence)
    2  PATH is not a usable directory
"""

import argparse
import json
import sys
from pathlib import Path

from inventorylib.report import build_inventory


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="profile_inventory.py",
        description="Emit a deterministic JSON inventory of a repository.")
    parser.add_argument("path", nargs="?", default=".",
                        help="repo root to inventory (default: current directory)")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON (default; accepted for explicitness)")
    parser.add_argument("--indent", type=int, default=2,
                        help="JSON indent; 0 for compact output")
    args = parser.parse_args(argv)

    root = Path(args.path)
    if not root.is_dir():
        json.dump({"error": "not a directory: %s" % args.path}, sys.stderr)
        sys.stderr.write("\n")
        return 2

    indent = args.indent if args.indent > 0 else None
    print(json.dumps(build_inventory(root), indent=indent, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_cli -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Verify it runs against this repo**

Run: `uv run --script profile/scripts/profile_inventory.py . --indent 2 | head -30`
Expected: JSON with `"languages"` containing `python`, and `coverage_confidence` present.

- [ ] **Step 6: Lint and commit**

```bash
ruff check profile/ tests/test_profile_cli.py
chmod +x profile/scripts/profile_inventory.py
git add profile/scripts/profile_inventory.py tests/test_profile_cli.py
git commit -m "feat(profile): profile_inventory CLI with exit codes"
```

---

### Task 8: Contract schemas and the dependency-free validator

**Files:**
- Create: `tests/schema_check.py`
- Create: `profile/references/contracts/stack.schema.json`
- Create: `profile/references/contracts/docs.schema.json`
- Create: `profile/references/contracts/topology.schema.json`
- Create: `profile/references/contracts/journeys.schema.json`
- Create: `profile/references/contracts/examples/stack.example.json`
- Create: `profile/references/contracts/examples/docs.example.json`
- Create: `profile/references/contracts/examples/topology.example.json`
- Create: `profile/references/contracts/examples/journeys.example.json`
- Test: `tests/test_profile_contracts.py`

**Interfaces:**
- Consumes: nothing
- Produces: `validate(instance, schema, path="$") -> list[str]` returning human-readable error strings (empty list means valid). Supports the JSON Schema subset actually used here: `type` (object/array/string/number/integer/boolean/null), `properties`, `required`, `items`, `enum`. Unknown keywords are ignored by design.

`jsonschema` is not installed and stdlib-only is a hard constraint, hence the hand-rolled checker.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_profile_contracts.py
import json
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "profile" / "references" / "contracts"


class TestValidator(unittest.TestCase):
    def test_accepts_valid_object(self):
        schema = {"type": "object", "required": ["a"],
                  "properties": {"a": {"type": "string"}}}
        self.assertEqual(validate({"a": "x"}, schema), [])

    def test_reports_missing_required_property(self):
        schema = {"type": "object", "required": ["a"], "properties": {}}
        errors = validate({}, schema)
        self.assertEqual(len(errors), 1)
        self.assertIn("required", errors[0])

    def test_reports_wrong_type_with_path(self):
        schema = {"type": "object", "properties": {"a": {"type": "string"}}}
        errors = validate({"a": 1}, schema)
        self.assertIn("$.a", errors[0])

    def test_validates_array_items(self):
        schema = {"type": "array", "items": {"type": "integer"}}
        self.assertEqual(validate([1, 2], schema), [])
        self.assertEqual(len(validate([1, "x"], schema)), 1)

    def test_enum_enforced(self):
        schema = {"enum": ["a", "b"]}
        self.assertEqual(validate("a", schema), [])
        self.assertEqual(len(validate("c", schema)), 1)

    def test_bool_is_not_an_integer(self):
        self.assertEqual(len(validate(True, {"type": "integer"})), 1)


class TestProfileContracts(unittest.TestCase):
    def test_every_schema_is_valid_json_and_has_required_metadata(self):
        schemas = sorted(CONTRACTS.glob("*.schema.json"))
        self.assertEqual([p.name for p in schemas],
                         ["docs.schema.json", "journeys.schema.json",
                          "stack.schema.json", "topology.schema.json"])
        for path in schemas:
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["type"], "object")
                self.assertIn("contract_version", schema["properties"])
                self.assertIn("contract_version", schema["required"])

    def test_every_schema_has_an_example_that_validates(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            name = path.name.replace(".schema.json", "")
            example_path = CONTRACTS / "examples" / ("%s.example.json" % name)
            with self.subTest(contract=name):
                self.assertTrue(example_path.exists(), "missing example for %s" % name)
                errors = validate(
                    json.loads(example_path.read_text(encoding="utf-8")),
                    json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(errors, [])

    def test_topology_contract_uses_no_testing_vocabulary(self):
        """Extraction discipline: profile phases stay consumer-agnostic."""
        text = (CONTRACTS / "topology.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("boundary", "test", "fixture", "mock"):
            self.assertNotIn(banned, text, "topology contract mentions %r" % banned)

    def test_journeys_contract_uses_no_testing_vocabulary(self):
        text = (CONTRACTS / "journeys.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("test", "coverage_hint", "fixture"):
            self.assertNotIn(banned, text, "journeys contract mentions %r" % banned)

    def test_docs_contract_uses_no_testing_vocabulary(self):
        text = (CONTRACTS / "docs.schema.json").read_text(encoding="utf-8").lower()
        for banned in ("test", "fixture", "mock", "scenario"):
            self.assertNotIn(banned, text, "docs contract mentions %r" % banned)

    def test_docs_contract_emits_evidence_not_journey_candidates(self):
        """Ownership boundary: profile:journeys alone forms and ranks candidates."""
        schema = json.loads((CONTRACTS / "docs.schema.json").read_text(encoding="utf-8"))
        properties = schema["properties"]
        self.assertIn("journey_evidence", properties)
        self.assertNotIn("candidates", properties)

    def test_docs_requirements_do_not_classify_scope(self):
        """Cross-cutting-ness is judged against the journey set, which does not
        exist when docs runs. Deliberately absent; see the spec."""
        schema = json.loads((CONTRACTS / "docs.schema.json").read_text(encoding="utf-8"))
        requirement = schema["properties"]["requirements"]["items"]["properties"]
        self.assertNotIn("scope", requirement)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'schema_check'`

- [ ] **Step 3: Write the validator**

```python
# tests/schema_check.py
"""Minimal JSON Schema subset validator.

Supports type, properties, required, items, and enum — the subset the profile
and itest contracts actually use. Unknown keywords are ignored by design.
Exists because jsonschema is not installed and this repo is stdlib-only.
"""

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


def validate(instance, schema, path="$"):
    """Return a list of error strings; empty means the instance is valid."""
    errors = []

    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        if not any(TYPE_CHECKS[t](instance) for t in types if t in TYPE_CHECKS):
            return ["%s: expected type %s, got %s"
                    % (path, "|".join(types), type(instance).__name__)]

    if "enum" in schema and instance not in schema["enum"]:
        errors.append("%s: %r not in enum %r" % (path, instance, schema["enum"]))

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append("%s: missing required property %r" % (path, name))
        for name, subschema in schema.get("properties", {}).items():
            if name in instance:
                errors.extend(
                    validate(instance[name], subschema, "%s.%s" % (path, name)))

    if isinstance(instance, list) and "items" in schema:
        for index, item in enumerate(instance):
            errors.extend(
                validate(item, schema["items"], "%s[%d]" % (path, index)))

    return errors
```

- [ ] **Step 4: Write the four contract schemas**

`profile/references/contracts/stack.schema.json` — the stack contract carries the inventory forward, which is how `itest` phases get it without ever invoking the script:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "profile:stack contract",
  "type": "object",
  "required": ["contract_version", "primary_language", "languages", "confidence", "inventory"],
  "properties": {
    "contract_version": { "type": "string" },
    "primary_language": { "type": ["string", "null"] },
    "languages": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "files", "share"],
        "properties": {
          "name": { "type": "string" },
          "files": { "type": "integer" },
          "share": { "type": "number" }
        }
      }
    },
    "package_managers": { "type": "array", "items": { "type": "string" } },
    "runtimes": { "type": "array", "items": { "type": "string" } },
    "build_commands": { "type": "array", "items": { "type": "string" } },
    "monorepo": {
      "type": "object",
      "required": ["is"],
      "properties": {
        "is": { "type": "boolean" },
        "packages": { "type": "array", "items": { "type": "string" } }
      }
    },
    "unknowns": { "type": "array", "items": { "type": "string" } },
    "confidence": { "enum": ["high", "partial", "low"] },
    "inventory": { "type": "object" }
  }
}
```

`profile/references/contracts/docs.schema.json` — the documentary record. Note what is
absent as much as what is present: no `candidates`, because journey candidates belong to
`profile:journeys`; no `scope` on a requirement, because cross-cutting-ness is judged
against the journey set, which does not exist yet. Both absences are enforced by tests:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "profile:docs contract",
  "type": "object",
  "required": ["contract_version", "sources_available", "unavailable_sources",
               "corpus", "requirements", "coverage_confidence"],
  "properties": {
    "contract_version": { "type": "string" },
    "sources_available": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["kind", "locator", "capability_used"],
        "properties": {
          "kind": { "enum": ["in-repo", "local-path", "external"] },
          "locator": { "type": "string" },
          "capability_used": { "type": "string" }
        }
      }
    },
    "unavailable_sources": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["locator", "reason", "suggested_remedy"],
        "properties": {
          "locator": { "type": "string" },
          "reason": { "type": "string" },
          "suggested_remedy": { "type": "string" }
        }
      }
    },
    "corpus": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "locator", "doc_type", "title", "authority", "read"],
        "properties": {
          "id": { "type": "string" },
          "locator": { "type": "string" },
          "doc_type": {
            "enum": ["prd", "requirements", "spec", "design", "architecture",
                     "adr", "runbook", "api_reference", "user_guide",
                     "tutorial", "readme", "changelog", "unknown"]
          },
          "title": { "type": "string" },
          "last_modified": { "type": ["string", "null"] },
          "authority": { "enum": ["normative", "descriptive", "historical", "unknown"] },
          "read": { "enum": ["full", "skimmed"] }
        }
      }
    },
    "deferred": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["locator", "doc_type", "rank", "why_deferred"],
        "properties": {
          "locator": { "type": "string" },
          "doc_type": {
            "enum": ["prd", "requirements", "spec", "design", "architecture",
                     "adr", "runbook", "api_reference", "user_guide",
                     "tutorial", "readme", "changelog", "unknown"]
          },
          "rank": { "type": "integer" },
          "why_deferred": { "type": "string" }
        }
      }
    },
    "requirements": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "statement", "modality", "source_refs", "confidence"],
        "properties": {
          "id": { "type": "string" },
          "statement": { "type": "string" },
          "modality": { "enum": ["must", "should", "may"] },
          "actors": { "type": "array", "items": { "type": "string" } },
          "acceptance_criteria": { "type": "array", "items": { "type": "string" } },
          "preconditions_stated": { "type": "array", "items": { "type": "string" } },
          "source_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["corpus_id", "anchor"],
              "properties": {
                "corpus_id": { "type": "string" },
                "anchor": { "type": "string" }
              }
            }
          },
          "staleness": {
            "type": "object",
            "properties": {
              "last_modified": { "type": ["string", "null"] },
              "version_refs": { "type": "array", "items": { "type": "string" } },
              "stated_status": { "type": ["string", "null"] }
            }
          },
          "confidence": { "enum": ["high", "medium", "low"] }
        }
      }
    },
    "journey_evidence": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["narrative", "source_refs"],
        "properties": {
          "narrative": { "type": "string" },
          "actor": { "type": ["string", "null"] },
          "entry_point_hint": { "type": ["string", "null"] },
          "source_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["corpus_id", "anchor"],
              "properties": {
                "corpus_id": { "type": "string" },
                "anchor": { "type": "string" }
              }
            }
          }
        }
      }
    },
    "glossary": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["term", "definition"],
        "properties": {
          "term": { "type": "string" },
          "definition": { "type": "string" },
          "source_refs": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["corpus_id", "anchor"],
              "properties": {
                "corpus_id": { "type": "string" },
                "anchor": { "type": "string" }
              }
            }
          }
        }
      }
    },
    "domain_invariants": { "type": "array", "items": { "type": "string" } },
    "open_questions": { "type": "array", "items": { "type": "string" } },
    "coverage_confidence": { "enum": ["high", "partial", "low"] }
  }
}
```

`profile/references/contracts/topology.schema.json` — note there is no boundary vocabulary anywhere in it, enforced by a test:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "profile:topology contract",
  "type": "object",
  "required": ["contract_version", "shape", "components", "assumptions"],
  "properties": {
    "contract_version": { "type": "string" },
    "shape": {
      "enum": ["monolith", "service-with-dependencies", "multi-service",
               "serverless", "cli", "library", "desktop", "hybrid", "unknown"]
    },
    "components": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "role", "evidence"],
        "properties": {
          "name": { "type": "string" },
          "role": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "real_dependencies": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "kind", "how_started", "evidence"],
        "properties": {
          "name": { "type": "string" },
          "kind": { "type": "string" },
          "how_started": { "type": "string" },
          "config_source": { "type": ["string", "null"] },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "external_third_parties": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "used_for"],
        "properties": {
          "name": { "type": "string" },
          "used_for": { "type": "string" }
        }
      }
    },
    "config_mechanism": { "type": ["string", "null"] },
    "ports_and_endpoints": { "type": "array", "items": { "type": "string" } },
    "startup_sequence": { "type": "array", "items": { "type": "string" } },
    "standup_notes": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["component", "standup_difficulty", "externally_reachable"],
        "properties": {
          "component": { "type": "string" },
          "standup_difficulty": { "enum": ["trivial", "moderate", "hard", "impractical"] },
          "config_needed": { "type": "array", "items": { "type": "string" } },
          "externally_reachable": { "type": "boolean" },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "assumptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim", "why_unconfirmed"],
        "properties": {
          "claim": { "type": "string" },
          "why_unconfirmed": { "type": "string" }
        }
      }
    }
  }
}
```

Note on the property name: the concept the spec calls "testability notes" ships as **`standup_notes`**. The vocabulary test bans the substring `test` from this contract, and that ban is the mechanism enforcing the spec's extraction discipline — a `profile` contract must not name a consumer. The concept is unchanged: how hard is this component to stand up, what config does it need, is it reachable from outside. Use `standup_notes` in the schema, the example, the `topology` SKILL.md (Task 10), and every downstream reference.

`profile/references/contracts/journeys.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "profile:journeys contract",
  "type": "object",
  "required": ["contract_version", "candidates", "sources_read"],
  "properties": {
    "contract_version": { "type": "string" },
    "candidates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "name", "actor", "narrative", "entry_point",
                     "evidence", "business_criticality", "rank", "rationale"],
        "properties": {
          "id": { "type": "string" },
          "name": { "type": "string" },
          "actor": { "type": "string" },
          "narrative": { "type": "string" },
          "entry_point": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" } },
          "business_criticality": { "enum": ["critical", "high", "medium", "low"] },
          "rank": { "type": "integer" },
          "rationale": { "type": "string" },
          "depends_on": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "sources_read": { "type": "array", "items": { "type": "string" } },
    "surface_coverage": { "type": ["string", "null"] }
  }
}
```

- [ ] **Step 5: Write the four examples**

Each example must validate against its schema and must be realistic — these double as the worked examples the SKILL.md files point at. Write them describing a small HTTP service with Postgres.

```json
// profile/references/contracts/examples/stack.example.json
{
  "contract_version": "1.0.0",
  "primary_language": "go",
  "languages": [{ "name": "go", "files": 42, "share": 0.875 }],
  "package_managers": ["go"],
  "runtimes": ["go1.22"],
  "build_commands": ["go build ./..."],
  "monorepo": { "is": false, "packages": [] },
  "unknowns": [],
  "confidence": "high",
  "inventory": {}
}
```

```json
// profile/references/contracts/examples/docs.example.json
{
  "contract_version": "1.0.0",
  "sources_available": [
    { "kind": "in-repo", "locator": "README.md", "capability_used": "Read" },
    { "kind": "in-repo", "locator": "docs/prd-cancellations.md", "capability_used": "Read" },
    { "kind": "external", "locator": "https://wiki.example.com/orders/refund-policy",
      "capability_used": "WebFetch" }
  ],
  "unavailable_sources": [
    {
      "locator": "Confluence space ORDERS",
      "reason": "No Atlassian capability is present in this session.",
      "suggested_remedy": "Enable the Atlassian MCP server, or export the space to markdown under docs/ and run again."
    }
  ],
  "corpus": [
    { "id": "D1", "locator": "docs/prd-cancellations.md", "doc_type": "prd",
      "title": "Order cancellation", "last_modified": "2026-03-11T09:14:02+00:00",
      "authority": "normative", "read": "full" },
    { "id": "D2", "locator": "README.md", "doc_type": "readme",
      "title": "orders service", "last_modified": "2026-07-02T16:40:11+00:00",
      "authority": "descriptive", "read": "full" },
    { "id": "D3", "locator": "docs/adr/0004-server-generated-ids.md", "doc_type": "adr",
      "title": "Server-generated order ids", "last_modified": "2025-11-20T11:02:44+00:00",
      "authority": "historical", "read": "skimmed" }
  ],
  "deferred": [
    { "locator": "docs/api/orders.md", "doc_type": "api_reference", "rank": 14,
      "why_deferred": "below the 25-document read budget; generated reference with no normative language" }
  ],
  "requirements": [
    {
      "id": "R1",
      "statement": "A customer must be able to cancel an order at any time before it ships.",
      "modality": "must",
      "actors": ["authenticated customer"],
      "acceptance_criteria": [
        "the order reports status 'cancelled'",
        "any captured payment is refunded in full"
      ],
      "preconditions_stated": ["the order exists and has not shipped"],
      "source_refs": [{ "corpus_id": "D1", "anchor": "## Cancellation window" }],
      "staleness": {
        "last_modified": "2026-03-11T09:14:02+00:00",
        "version_refs": ["v2 API"],
        "stated_status": "approved"
      },
      "confidence": "high"
    },
    {
      "id": "R2",
      "statement": "Every response must carry the request id in an X-Request-Id header.",
      "modality": "must",
      "actors": [],
      "acceptance_criteria": ["X-Request-Id is present and non-empty on every response"],
      "preconditions_stated": [],
      "source_refs": [{ "corpus_id": "D2", "anchor": "### Observability" }],
      "staleness": {
        "last_modified": "2026-07-02T16:40:11+00:00",
        "version_refs": [],
        "stated_status": null
      },
      "confidence": "medium"
    }
  ],
  "journey_evidence": [
    {
      "narrative": "A signed-in customer cancels an order they placed and is refunded.",
      "actor": "authenticated customer",
      "entry_point_hint": "POST /orders/{id}/cancel",
      "source_refs": [{ "corpus_id": "D1", "anchor": "## Cancellation window" }]
    }
  ],
  "glossary": [
    {
      "term": "settled order",
      "definition": "An order whose payment has been captured and which can no longer be cancelled without a refund.",
      "source_refs": [{ "corpus_id": "D1", "anchor": "## Definitions" }]
    }
  ],
  "domain_invariants": [
    "An order never leaves the 'cancelled' state.",
    "A refund total never exceeds the captured total."
  ],
  "open_questions": [
    "The PRD describes a 24-hour free-cancellation window; no document states what happens at exactly 24 hours."
  ],
  "coverage_confidence": "partial"
}
```

`R2` is deliberately a requirement no single journey owns. It is the worked example of
the cross-cutting case the `itest` gate has to surface.

```json
// profile/references/contracts/examples/topology.example.json
{
  "contract_version": "1.0.0",
  "shape": "service-with-dependencies",
  "components": [
    { "name": "api", "role": "HTTP service", "evidence": ["cmd/api/main.go:1"] }
  ],
  "real_dependencies": [
    {
      "name": "postgres",
      "kind": "database",
      "how_started": "docker-compose service 'db'",
      "config_source": "DATABASE_URL",
      "evidence": ["docker-compose.yml:4"]
    }
  ],
  "external_third_parties": [
    { "name": "stripe", "used_for": "payment capture" }
  ],
  "config_mechanism": "environment variables",
  "ports_and_endpoints": ["api:8080", "db:5432"],
  "startup_sequence": ["db", "migrations", "api"],
  "standup_notes": [
    {
      "component": "api",
      "standup_difficulty": "moderate",
      "config_needed": ["DATABASE_URL"],
      "externally_reachable": true,
      "evidence": ["docker-compose.yml:12"]
    }
  ],
  "assumptions": [
    {
      "claim": "compose stack starts cleanly on a developer machine",
      "why_unconfirmed": "discovery is read-only; nothing was executed"
    }
  ]
}
```

```json
// profile/references/contracts/examples/journeys.example.json
{
  "contract_version": "1.0.0",
  "candidates": [
    {
      "id": "J1",
      "name": "Create an order",
      "actor": "authenticated customer",
      "narrative": "A signed-in customer adds items and places an order, receiving an order id.",
      "entry_point": "POST /orders",
      "evidence": ["README.md:22", "internal/http/routes.go:40"],
      "business_criticality": "critical",
      "rank": 1,
      "rationale": "Named as the primary flow in the README and the only revenue path.",
      "depends_on": []
    },
    {
      "id": "J2",
      "name": "Cancel an order",
      "actor": "authenticated customer",
      "narrative": "A customer cancels an order they placed and the order becomes cancelled.",
      "entry_point": "POST /orders/{id}/cancel",
      "evidence": ["internal/http/routes.go:52"],
      "business_criticality": "high",
      "rank": 2,
      "rationale": "Second most referenced flow in docs; depends on an order existing.",
      "depends_on": ["J1"]
    }
  ],
  "sources_read": ["README.md", "docs/api.md", "internal/http/routes.go"],
  "surface_coverage": "2 of 7 public HTTP routes"
}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: PASS, 13 tests. If the topology vocabulary test fails, apply the `standup_notes` rename from Step 4 rather than weakening the test.

- [ ] **Step 7: Lint and commit**

```bash
ruff check tests/schema_check.py tests/test_profile_contracts.py
git add tests/schema_check.py tests/test_profile_contracts.py profile/references/contracts
git commit -m "feat(profile): phase contracts with dependency-free schema validation"
```

---

### Task 9: `profile:stack` skill and ecosystems reference

**Files:**
- Create: `profile/skills/stack/SKILL.md`
- Create: `profile/references/ecosystems.md`

**Interfaces:**
- Consumes: `profile_inventory.py`, `contracts/stack.schema.json`
- Produces: the `stack` contract, which every other phase depends on. This is the gate phase: it runs the inventory script, corrects it, and passes the inventory forward inside its contract.

- [ ] **Step 1: Write the ecosystems reference**

`profile/references/ecosystems.md` must contain, at minimum:

- A table mapping every key in `MANIFESTS` (Task 3) to its ecosystem, the runtime it implies, and the version file to read for that runtime (`.python-version`, `go.mod` go directive, `.nvmrc`, `rust-toolchain.toml`, `.ruby-version`).
- A table mapping every key in `LOCKFILE_PM` to its package manager and the command that installs dependencies.
- A section **"When the script comes back low-confidence"** listing the fallback reading order: root directory listing, any `Makefile` or `justfile` targets, CI workflow files, `README` build instructions, editor config, then file extensions by frequency. It must also state what the number means, verbatim: *"`coverage_confidence` measures the whole tree, assets included — a repo can be `high` while one niche source directory is opaque. Read `unclassified[]` too, not just the label."*
- A section **"Build command inference"** giving the canonical build command per ecosystem (`go build ./...`, `cargo build`, `npm run build`, `uv build`, `mvn package`, `dotnet build`).
- A closing rule, verbatim: *"If you cannot identify the ecosystem, say so in `unknowns[]` and set `confidence` to `low`. Do not guess a language from a single file."*

- [ ] **Step 2: Write the skill**

```markdown
---
name: stack
version: 1.0.0
description: Identify what a codebase is built with — languages, runtimes, package managers, build commands, and monorepo layout. Use when profiling an unfamiliar project, before test design, dependency work, or onboarding documentation. Emits the profile:stack contract.
---

# stack

Identify the ecosystem of a repository and emit the `stack` contract.

This is the gate phase for `/itest:design`: every other phase's search strategy
depends on knowing the ecosystem, and the inventory this phase produces is passed
forward inside its contract so no downstream phase re-runs the script.

Bundled tool: `${CLAUDE_PLUGIN_ROOT}/scripts/profile_inventory.py`
Reference: `${CLAUDE_PLUGIN_ROOT}/references/ecosystems.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/stack.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/stack.example.json`

## Usage

    /profile:stack [path]     # default: current directory

## Procedure

1. Run the inventory script:

       uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/profile_inventory.py <path>

   `--script` is required: it isolates the run from the target repo's own project
   config, which would otherwise be resolved and can fail on repos with private
   indexes or unpublished dependencies.

   If `uv` is not installed, run the same path under `python3` — this script
   declares no dependencies — and mention the fallback in your summary.

   Exit 2 means the path is unusable — stop and report that.

2. Read `coverage_confidence` and `unclassified`.
   - `high` — trust the census; go to step 4.
   - `partial` or `low` — the script found things it could not classify. Go to step 3.

3. **Fallback reading.** Follow the order in `references/ecosystems.md` under
   "When the script comes back low-confidence". Read the repo yourself. Correct
   or extend the script's findings; never discard them silently.

4. Determine `runtimes` and `build_commands` from the version files and build-command
   tables in `references/ecosystems.md`. Prefer a command actually present in a
   Makefile, justfile, or CI workflow over the ecosystem default.

5. Determine `monorepo`: true when manifests appear in two or more distinct
   directories. List those directories in `monorepo.packages`.

6. Emit the contract. Set `inventory` to the script's full JSON output verbatim.
   Set `confidence` to the script's `coverage_confidence`, downgraded one level if
   your fallback reading contradicted the script.

## Rules

- Everything you could not identify goes in `unknowns[]`. Never guess a language
  from a single file.
- `primary_language` is the language with the largest share, or `null` when no
  language was recognized.
- Emit exactly one JSON object conforming to the contract, then a short prose
  summary. Nothing else.
```

- [ ] **Step 3: Verify the contract example still validates and paths resolve**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add profile/skills/stack profile/references/ecosystems.md
git commit -m "feat(profile): stack skill and ecosystems reference"
```

---

### Task 9b: `profile:docs` skill and doc-sources reference

> Inserted after the original plan was written. Numbered `9b` so Tasks 10–12 keep the
> numbers the `itest` plan and the steps above already reference.

**Files:**
- Create: `profile/skills/docs/SKILL.md`
- Create: `profile/references/doc-sources.md`

**Interfaces:**
- Consumes: the `stack` contract (specifically `inventory.docs` and
  `inventory.docs_sites`), plus any external doc pointers the caller supplies
- Produces: the `docs` contract — the second gate. `journeys`, `topology`,
  `conventions`, and `state` all read from it.

- [ ] **Step 1: Write the doc-sources reference**

`profile/references/doc-sources.md` must contain, at minimum:

**A source-tier table** with three rows, stating for each tier what is in it and which
capability reads it:

| tier | what | how it is read |
|---|---|---|
| in-repo | everything in `inventory.docs`, plus navigation from `inventory.docs_sites` | Read, Glob, Grep |
| user-named external | URLs, wiki pages, tracker documents, local paths outside the repo, all named by the caller | WebFetch for a URL; an MCP server present in this session for the system it belongs to; Read for a local path |
| unreachable | a named source with no matching capability | not read — recorded in `unavailable_sources[]` |

**A binding rule, verbatim:** *"Never build a retrieval mechanism. Use a capability that
already exists in this session, or record the source as unavailable with a remedy. Do not
scrape, do not construct URLs you were not given, and do not install anything."*

**A remedy table** giving the exact wording to put in `suggested_remedy` for each common
case: no MCP for the named system ("Enable the *X* MCP server and run again"); a URL that
fetches but returns a login page ("Export the page to markdown and place it under `docs/`
or give a local path"); a source named too vaguely to locate ("Give a full URL or file
path"); a binary format ("Convert to text and place it in the repo").

**A `doc_type` table** — all thirteen values from `inventorylib/docs.py` `DOC_TYPES`,
each with what it looks like and what it is worth. Note explicitly that the inventory's
`doc_type_guess` is a *path-based guess* and this phase corrects it after reading.

**An `authority` table** — the four values with how to tell them apart: `normative` (the
document states obligations the team agreed to: a spec, an approved PRD, a requirements
document); `descriptive` (explains how things work without binding anyone: most READMEs,
overviews, tutorials); `historical` (superseded, dated, or explicitly marked as such:
most ADRs describing past decisions); `unknown`.

**A ranking section** listing the signals in priority order:
1. `doc_type` — `prd`, `requirements`, `spec` outrank `design`, `architecture`, which
   outrank `adr`, `user_guide`, `readme`, which outrank `api_reference`, `changelog`
2. Normative density — count matches per document with
   `rg -c -i -e '\bMUST\b' -e '\bSHALL\b' -e '\bSHOULD\b' -e 'acceptance criteria' <path>`
3. Recency — `last_modified` from the census; a document untouched for years describing a
   system under active development is likely `historical`
4. Position in a docs-site navigation — a page linked from the top level of `mkdocs.yml`
   or a Docusaurus sidebar outranks an orphan

**A budget section**, verbatim: *"Deep-read at most 25 documents. Everything below the
line goes in `deferred[]` with its rank and why. Always state in your summary how many
documents you read out of how many you found. A cap that is not reported reads as
complete coverage."*

**A closing rule, verbatim:** *"You are extracting what the documents say, not judging
whether it is true. Never read source code to check a requirement. A requirement that
contradicts the code is a finding your caller makes, not one you make."*

- [ ] **Step 2: Write the skill**

```markdown
---
name: docs
version: 1.0.0
description: Read a project's documentary record — PRDs, requirements documents, specifications, design docs, ADRs, wiki pages — and extract the requirements, user-workflow evidence, domain vocabulary, and invariants it states. Use when profiling an unfamiliar project, gathering requirements, or establishing what a system was supposed to do. Emits the profile:docs contract.
---

# docs

Read what this project wrote down about itself, and extract what it says the system is
supposed to do.

This is the second gate phase: `journeys`, `topology`, and other consumers all read from
the record this phase produces, so they read it once and agree about it.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/doc-sources.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/docs.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/docs.example.json`

## Usage

    /profile:docs [path]

## Input

You are normally handed a `profile:stack` contract; use `inventory.docs` and
`inventory.docs_sites` as your in-repo census. You may also be handed external
document pointers — URLs, wiki locations, local paths.

**Standalone invocation:** if you were not handed a `stack` contract, invoke
`profile:stack` first and use its output. If you were not given external pointers and
you are running in a conversation with the user, ask once whether any requirements
documents, PRDs, or specifications live outside the repository, and accept "none".

## Procedure

1. **Resolve sources.** For each in-repo document, the capability is Read. For each
   external pointer, match it to a capability that is already available in this
   session per the source-tier table. Record every resolved source in
   `sources_available[]` with the capability you used.

2. **Record what you cannot reach.** A pointer with no matching capability goes in
   `unavailable_sources[]` with a reason and a `suggested_remedy` drawn from the remedy
   table. Then continue — an unreachable source is a reported gap, never a stop.

3. **Census.** For every candidate, record locator, title, headings, and
   `last_modified`. Correct the inventory's `doc_type_guess`, which is a path-based
   guess made without reading anything.

4. **Rank** by the signals in the reference, in the order given.

5. **Deep-read** down the ranking to the 25-document budget. Each document read becomes
   a `corpus[]` entry with `read: full` or `read: skimmed` and an `authority` value.
   Everything below the line becomes a `deferred[]` entry.

6. **Extract requirements.** A requirement is a statement about what the system must,
   should, or may do. Give each one an id, its `modality`, the actors it names, any
   acceptance criteria stated alongside it, any preconditions the document states, and
   `source_refs` pointing at the document and a heading anchor. A statement with no
   `source_refs` does not ship.

7. **Record `staleness`** per requirement: the document's `last_modified`, any version
   or release identifiers the text names, and any status the document states about
   itself ("draft", "approved", "superseded by X").

8. **Extract `journey_evidence`** — narratives describing what someone does with the
   system, with an actor and an entry-point hint where the text gives one. These are
   evidence for a later phase, not conclusions.

9. **Extract `glossary` and `domain_invariants`** — the project's own terms, and the
   statements that must always hold ("an order never leaves the cancelled state").
   These are the highest-leverage output for anyone writing precise assertions later.

10. **Record `open_questions`** — things the documentation raises but never settles.

11. Set `coverage_confidence`: `high` when you read the normative documents and nothing
    important was unreachable; `partial` when the budget or an unavailable source left a
    real gap; `low` when there is essentially no documentation.

12. Emit the contract, then a short prose summary that states how many documents you
    read out of how many you found, and names anything you could not reach.

## Rules

- **Never build a retrieval mechanism.** Use a capability that already exists in this
  session, or record the source as unavailable with a remedy. Do not scrape, do not
  construct URLs you were not given, and do not install anything.
- **Never read source code to verify a requirement.** You extract what the documents
  say. Whether the code agrees is your caller's finding to make, not yours.
- **Emit `journey_evidence`, never candidates.** Forming and ranking user-workflow
  candidates belongs to `profile:journeys`. Handing it evidence is the job; handing it
  conclusions takes its job away.
- Every requirement, evidence item, and glossary entry carries `source_refs`.
- Do not describe strategy, coverage, boundaries, or fixtures of any kind. This phase
  reports what the documents state; consumers decide what to do with it.
- A repository with no documentation is a legitimate finding: empty arrays and
  `coverage_confidence: low`, said plainly. Do not pad it with inferences from code.
```

- [ ] **Step 3: Verify the contract example still validates and paths resolve**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: PASS, 13 tests

- [ ] **Step 4: Commit**

```bash
git add profile/skills/docs profile/references/doc-sources.md
git commit -m "feat(profile): docs skill and doc-sources reference"
```

---

### Task 10: `profile:topology` skill and deployment-shapes reference

**Files:**
- Create: `profile/skills/topology/SKILL.md`
- Create: `profile/references/deployment-shapes.md`

**Interfaces:**
- Consumes: the `stack` contract (including its embedded `inventory`)
- Produces: the `topology` contract — `shape`, `components`, `real_dependencies`, `external_third_parties`, `config_mechanism`, `ports_and_endpoints`, `startup_sequence`, `standup_notes`, `assumptions`

- [ ] **Step 1: Write the deployment-shapes reference**

`profile/references/deployment-shapes.md` must contain:

- A signature table: for each `shape` enum value in the contract, the artifacts that indicate it (compose file with multiple services → `multi-service`; single Dockerfile plus one manifest → `service-with-dependencies` or `monolith`; `serverless.yml`/`template.yaml`/`cdk.json` → `serverless`; `[project.scripts]` or `cmd/*/main.go` with no server → `cli`; a manifest with no entrypoint → `library`).
- A dependency table: image name or client library → dependency kind and how it is normally started (`postgres`, `mysql`, `redis`, `rabbitmq`, `kafka`, `elasticsearch`, `minio`/S3, `mongodb`).
- A third-party table: SDK or base URL patterns that indicate an external paid service (`stripe`, `twilio`, `sendgrid`, `auth0`, `openai`, AWS SDK clients).
- A section on **config mechanisms**: environment variables, `.env` files, config files, flags, secret managers — and how to tell which one a component actually reads.
- A section on **standup difficulty**, defining the four enum values concretely: `trivial` (single process, no external state), `moderate` (needs containers or a database, all declared), `hard` (needs credentials, cloud resources, or manual steps), `impractical` (needs production data or a third-party account that cannot be stubbed).
- A closing rule, verbatim: *"You are reading, not running. Every claim carries `file:line` evidence. Anything you believe but did not read goes in `assumptions[]` with why it is unconfirmed."*

- [ ] **Step 2: Write the skill**

```markdown
---
name: topology
version: 1.0.0
description: Determine how a system deploys and what it depends on — components, real dependencies, third-party services, configuration, startup order, and how hard each component is to stand up. Read-only. Use when profiling an unfamiliar project for test design, deployment documentation, or onboarding. Emits the profile:topology contract.
---

# topology

Determine the deployment shape of a system by reading its configuration. Emits the
`topology` contract.

**This phase never executes anything.** No container boots, no health checks, no
builds. Every factual claim carries `file:line` evidence; everything inferred but
unconfirmed goes in `assumptions[]`.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/deployment-shapes.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/topology.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/topology.example.json`

## Usage

    /profile:topology [path]

Standalone invocation: if you were not handed a `stack` contract, invoke
`profile:stack` first and use its output. Do not run the inventory script directly.

## Procedure

1. From the `stack` contract's `inventory`, read every path under `containers`,
   `iac`, `ci`, and `entrypoints`. Those files are your primary evidence.
2. Match against the signature table in `references/deployment-shapes.md` to set `shape`.
3. Enumerate `components` — each independently deployable or independently runnable
   unit, with the evidence that shows it exists.
4. Enumerate `real_dependencies` — infrastructure the system genuinely needs (database,
   cache, queue, object store). Record how each is normally started and which config
   key points at it.
5. Enumerate `external_third_parties` — services owned by someone else. These are the
   things a consumer will likely need to substitute.
6. Determine `config_mechanism`, `ports_and_endpoints`, and `startup_sequence`.
7. For each component, write a `standup_notes` entry: difficulty per the definitions in
   the reference, the config it needs, and whether it is reachable from outside the
   process.
8. Emit the contract, then a short prose summary.

## Rules

- Read-only. If you want to know whether something works, you may not find out here —
  record it as an assumption.
- Do not describe test strategy, test boundaries, mocking, or fixtures. This phase
  reports facts about the system; consumers decide what to do with them.
- An empty `real_dependencies` list is a legitimate finding for a library or pure CLI.
```

- [ ] **Step 3: Verify the vocabulary test still passes**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: PASS — in particular `test_topology_contract_uses_no_testing_vocabulary`.

- [ ] **Step 4: Commit**

```bash
git add profile/skills/topology profile/references/deployment-shapes.md
git commit -m "feat(profile): topology skill and deployment-shapes reference"
```

---

### Task 11: `profile:journeys` skill and journey-sources reference

**Files:**
- Create: `profile/skills/journeys/SKILL.md`
- Create: `profile/references/journey-sources.md`

**Interfaces:**
- Consumes: the `stack` contract (including its embedded `inventory`) and the `docs`
  contract (`journey_evidence[]`, `glossary[]`)
- Produces: the `journeys` contract — ranked `candidates[]` with `depends_on` edges, `sources_read`, `surface_coverage`

- [ ] **Step 1: Write the journey-sources reference**

`profile/references/journey-sources.md` must contain:

- A **source-priority list**, strongest evidence first: the `docs` contract's
  `journey_evidence[]` (someone wrote down what users do — nothing beats that); OpenAPI or GraphQL schemas; HTTP route registration; CLI subcommand definitions; UI route definitions; integration or e2e test names already present; issue and milestone titles; commit message themes.
- A note, stated plainly: **the documentary record is read by `profile:docs`, not here.** If you were handed a `docs` contract, work from its evidence and glossary rather than re-reading the same prose. Re-reading it wastes the run and produces a second, slightly different reading of the same document.
- A **ranking rubric** defining the four `business_criticality` values: `critical` (the product's reason to exist, or the revenue path), `high` (named in the README or docs as a primary flow), `medium` (a supported flow reachable from the public surface), `low` (administrative, diagnostic, or rarely used).
- A section **"Finding dependency edges"**: a candidate depends on another when its entry point requires an identifier that only another journey can produce, when documentation describes it as a follow-on step, or when its handler reads an entity another journey creates.
- A section **"What is not a journey"**: a single endpoint with no user-visible outcome, a health check, an internal cron task with no actor, a pure function, a configuration knob.
- A closing rule, verbatim: *"A journey has an actor, an intention, and an observable outcome. If you cannot name all three, it is not a journey."*

- [ ] **Step 2: Write the skill**

```markdown
---
name: journeys
version: 1.0.0
description: Identify the key workflows users actually perform with a system, mined from documentation evidence, routes, CLI commands, and UI entry points, ranked by business criticality with dependency edges between them. Use when profiling an unfamiliar project for test design, documentation, or product understanding. Emits the profile:journeys contract.
---

# journeys

Mine a repository for the workflows its users actually perform, and emit the
`journeys` contract as **ranked candidates for a human to confirm**.

This phase proposes. It does not decide. The caller runs the confirmation gate.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/journey-sources.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/journeys.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/journeys.example.json`

## Usage

    /profile:journeys [path]

## Input

You are normally handed a `profile:stack` contract and a `profile:docs` contract.
The `docs` contract's `journey_evidence[]` is your strongest source: it is what the
project's own documentation says people do with the system, already extracted with
anchors. Its `glossary[]` gives you the project's vocabulary — name candidates in it.

**Standalone invocation:** if you were not handed them, invoke `profile:stack`, then
`profile:docs`, and use their output.

## Procedure

1. Start from the `docs` contract's `journey_evidence[]`, then work down the remaining
   priority order in `references/journey-sources.md`. Record every source you used in
   `sources_read`, including `corpus_id` references from the `docs` contract. Do not
   re-read documents `profile:docs` already read.
2. Draft candidates. Each needs an actor, an intention, and an observable outcome.
   Apply the "What is not a journey" filter.
3. Attach `evidence` as `file:line` references to every candidate. A candidate with
   no evidence does not ship.
4. Rank by the criticality rubric, then assign `rank` as a dense ordering from 1.
5. Add `depends_on` edges per "Finding dependency edges". These matter downstream:
   consumers use them to order work and to establish prerequisite state.
6. Estimate `surface_coverage` — what fraction of the public entry points these
   candidates touch. An honest low number is useful information.
7. Emit at most 12 candidates, then a short prose summary naming the ones you were
   least certain about.

## Rules

- Prefer what the documentation says users do over what the code makes possible.
- Do not report anything about existing tests or test coverage. That is a consumer's
  concern, not this phase's.
- If the repository has no usable documentation, say so in the summary and rank
  purely from the public surface — and say that too.
```

- [ ] **Step 3: Verify contracts still pass**

Run: `python3 -m unittest tests.test_profile_contracts -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add profile/skills/journeys profile/references/journey-sources.md
git commit -m "feat(profile): journeys skill and journey-sources reference"
```

---

### Task 12: Plugin manifest, structural test, and marketplace registration

**Files:**
- Create: `profile/.claude-plugin/plugin.json`
- Create: `tests/test_plugin_structure.py`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: every skill and reference file created in Tasks 9–11
- Produces: an installable plugin, plus a structural test that guards **all** plugins in this repo, not only `profile`

- [ ] **Step 1: Write the failing structural test**

```python
# tests/test_plugin_structure.py
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
PLUGIN_ROOT_REF = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)")


def plugin_dirs():
    return sorted(p.parent for p in REPO.glob("*/.claude-plugin/plugin.json"))


def skill_files():
    return sorted(REPO.glob("*/skills/*/SKILL.md"))


class TestPluginStructure(unittest.TestCase):
    def test_every_plugin_is_registered_in_the_marketplace(self):
        registered = {
            entry["source"].lstrip("./")
            for entry in json.loads(MARKETPLACE.read_text(encoding="utf-8"))["plugins"]
        }
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                self.assertIn(plugin.name, registered)

    def test_every_plugin_manifest_has_name_and_description(self):
        for plugin in plugin_dirs():
            with self.subTest(plugin=plugin.name):
                data = json.loads(
                    (plugin / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
                self.assertEqual(data["name"], plugin.name)
                self.assertTrue(data["description"].strip())

    def test_every_skill_has_name_and_description_frontmatter(self):
        for skill in skill_files():
            with self.subTest(skill=str(skill.relative_to(REPO))):
                text = skill.read_text(encoding="utf-8")
                self.assertTrue(text.startswith("---\n"), "missing frontmatter")
                front = text.split("---", 2)[1]
                self.assertRegex(front, r"(?m)^name:\s*\S+")
                self.assertRegex(front, r"(?m)^description:\s*\S+")

    def test_skill_frontmatter_name_matches_directory(self):
        for skill in skill_files():
            with self.subTest(skill=str(skill.relative_to(REPO))):
                front = skill.read_text(encoding="utf-8").split("---", 2)[1]
                name = re.search(r"(?m)^name:\s*(\S+)", front).group(1)
                self.assertEqual(name, skill.parent.name)

    def test_plugin_root_references_resolve(self):
        for skill in skill_files():
            plugin = skill.parents[2]
            for ref in PLUGIN_ROOT_REF.findall(skill.read_text(encoding="utf-8")):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    self.assertTrue((plugin / ref.lstrip("/")).exists(),
                                    "%s references missing %s" % (skill, ref))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to see which parts fail**

Run: `python3 -m unittest tests.test_plugin_structure -v`
Expected: FAIL on `test_every_plugin_is_registered_in_the_marketplace` (profile is not registered) and possibly on existing plugins' `${CLAUDE_PLUGIN_ROOT}` references. Fix any genuine broken reference you find in an existing plugin; that is exactly what this test is for.

- [ ] **Step 3: Write the plugin manifest**

```json
{
  "name": "profile",
  "version": "1.0.0",
  "description": "Project discovery toolkit: identify what a codebase is built with (stack), what its documentation says it must do (docs), how it deploys and what it depends on (topology), and what workflows its users actually perform (journeys). Read-only; emits versioned JSON contracts for downstream consumers.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 4: Register in the marketplace**

Add to the `plugins` array in `.claude-plugin/marketplace.json`, matching the existing single-line entry style:

```json
{ "name": "profile", "description": "Project discovery toolkit: identify what a codebase is built with (stack), what its requirements documents, PRDs, specs, and wiki pages say it must do (docs), how it deploys and what it depends on (topology), and what workflows its users actually perform (journeys). Read-only inference backed by a deterministic inventory script; emits versioned JSON contracts consumed by other plugins.", "source": "./profile", "category": "development" }
```

- [ ] **Step 5: Add the README section**

Insert after the `## dev` section, matching house style:

```markdown
## profile — project discovery

`stack` (languages, runtimes, package managers, build commands) · `docs`
(requirements, glossary, and domain invariants extracted from PRDs, specs, ADRs,
and wiki pages) · `topology` (deployment shape, real dependencies, third parties,
standup difficulty) · `journeys` (ranked candidate user workflows with dependency
edges).

Read-only inference backed by `scripts/profile_inventory.py`, a deterministic
repo census. `docs` reaches documentation outside the repo only through
capabilities already available in the session — an MCP server, a web fetch, a
local path — and reports anything it cannot reach with a concrete remedy rather
than working around it. Each skill emits a versioned JSON contract under
`references/contracts/`; those contracts are the supported interface for other
plugins.
```

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m unittest discover -s tests -t . 2>&1 | tail -5`
Expected: `OK`

- [ ] **Step 7: Verify the plugin against itself**

Run: `uv run --script profile/scripts/profile_inventory.py . --indent 0 | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['coverage_confidence'], len(d['test_files']))"`
Expected: prints a confidence value and a non-zero test-file count. This repo has a root
`pyproject.toml` and `uv.lock`, so `manifests` is non-empty and confidence should be `high`
or `partial` — `low` here would mean either languages or manifests came back empty, which
is worth investigating. (An earlier draft of this plan claimed the repo had no root
manifest; that stopped being true when the repo adopted uv.)

- [ ] **Step 8: Lint and commit**

```bash
ruff check profile/ tests/test_profile_*.py tests/repobuilder.py tests/schema_check.py tests/test_plugin_structure.py
git add profile/.claude-plugin tests/test_plugin_structure.py .claude-plugin/marketplace.json README.md
git commit -m "feat(profile): plugin manifest, structural tests, marketplace registration"
```

---

## Completion

`profile` is done when:

- `python3 -m unittest discover -s tests -t .` reports `OK`
- `ruff check profile/ tests/test_profile_*.py tests/repobuilder.py tests/schema_check.py tests/test_plugin_structure.py` passes
- `uv run --script profile/scripts/profile_inventory.py .` emits valid JSON at exit 0, and so does the `python3` fallback
- All four contracts have validating examples
- `profile` appears in `.claude-plugin/marketplace.json` and `README.md`

Then proceed to `docs/superpowers/plans/2026-07-26-itest-plugin.md`.
