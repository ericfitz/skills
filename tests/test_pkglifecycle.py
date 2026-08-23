# tests/test_pkglifecycle.py
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

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

POETRY_PYPROJECT = """\
[tool.poetry]
name = "x"
version = "1.0.0"

[tool.poetry.dependencies]
python = "^3.11"
pyyaml = "^6.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
"""

LEGACY_POETRY_PYPROJECT = """\
[tool.poetry]
name = "x"
version = "1.0.0"

[tool.poetry.dependencies]
python = "^3.11"
requests = "^2.0"

[tool.poetry.dev-dependencies]
black = "^24.0"
"""

# Spec-invalid pyproject.toml shapes: valid TOML, but not a shape the poetry
# pass expects. classify_roots must return {} for these, not raise.
INVALID_POETRY_SHAPES = {
    "tool_is_a_string": 'tool = "x"\n',
    "poetry_is_a_string": '[tool]\npoetry = "x"\n',
    "group_dev_is_a_string": '[tool.poetry.group]\ndev = "x"\n',
    "dependencies_is_an_array_of_tables": (
        '[[tool.poetry.dependencies]]\nname = "requests"\n'
    ),
}


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

    def test_poetry_pyproject_splits_dependencies_from_dev_group(self):
        """Poetry predates PEP 621 and has no [project] table at all; a
        pyproject.toml can carry only [tool.poetry.*]. Since pyproject.toml is
        already claimed by MANIFESTS, unresolved_ecosystems can never flag
        this -- classify_roots must parse it directly or the gap is silent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": POETRY_PYPROJECT})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["pyyaml"], "run")
            self.assertEqual(roots["pytest"], "build")
            self.assertNotIn("python", roots)  # a version constraint, not a package

    def test_legacy_poetry_dev_dependencies_spelling_is_build(self):
        """Pre-1.2 Poetry used [tool.poetry.dev-dependencies], not
        [tool.poetry.group.dev.dependencies]. Missing this spelling is the
        same silent-miss class as F2, one spelling over: black would default
        to run end to end via propagate's unreachable-artifact fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_repo(tmp, {"pyproject.toml": LEGACY_POETRY_PYPROJECT})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["requests"], "run")
            self.assertEqual(roots["black"], "build")

    def test_invalid_poetry_shapes_do_not_raise(self):
        """Spec-invalid but syntactically valid TOML must degrade to an empty
        result, not crash classify_roots. A crash is worse than an empty
        result -- nothing above classify_roots catches it."""
        for label, text in INVALID_POETRY_SHAPES.items():
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root = build_repo(tmp, {"pyproject.toml": text})
                self.assertEqual(pkglifecycle.classify_roots(Path(root)), {})

    def test_repo_nested_under_a_skip_dir_name_is_still_walked(self):
        """SKIP_DIRS must be tested against the path relative to the scanned
        root, not the absolute path: a checkout under /build/ or /target/ (or
        any ancestor named like a SKIP_DIRS entry) must not silently prune
        the whole walk and no-op the feature."""
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "build" / "myrepo"
            root = build_repo(nested, {"pyproject.toml": PYPROJECT})
            roots = pkglifecycle.classify_roots(Path(root))
            self.assertEqual(roots["pyyaml"], "run")
            self.assertEqual(roots["pytest"], "build")


class TestPropagate(unittest.TestCase):
    """Edge direction is load-bearing: {parent: A, child: B} means A is a
    dependency of B. Inverting it inverts every classification silently."""

    ARTIFACTS: ClassVar = [
        {"id": "a1", "name": "pytest"},
        {"id": "a2", "name": "pluggy"},
        {"id": "a3", "name": "pyyaml"},
        {"id": "a4", "name": "shared"},
    ]
    # pluggy is a dependency of pytest; shared is a dependency of pyyaml
    RELS: ClassVar = [
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
        rels = [*self.RELS, {"parent": "a2", "child": "a3", "type": "dependency-of"}]
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
        arts = [*self.ARTIFACTS, {"id": "a9", "name": "mystery"}]
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
