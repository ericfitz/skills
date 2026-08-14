# Open Issues Bugfixes (#32, #28, #30) + Deferred #5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three open bug issues (#32 apply ignores exit codes, #28 outdated silently empty without .venv, #30 orphaned SEM anchors classify fresh), defer #5 with an issue comment, then run `/bump` on this repo with the fixed tooling.

**Architecture:** Two independent PRs. PR 1 (deps plugin): a new `bumplib/gitfiles.py` helper verifies `filesModified` against `git status`; all three ecosystem adapters' `apply` verbs check subprocess exit codes and return an `error` contract field on failure; the Python `outdated` verb auto-runs `uv sync` when a uv project has a lockfile but no venv, and strips `VIRTUAL_ENV` as defense-in-depth when it must fall back. PR 2 (dev plugin): `sem_annotate.py` gains a `git merge-base --is-ancestor` reachability check so markers whose anchor commit was orphaned (squash-merge) classify `orphaned` and re-enter the worklist instead of silently reading `fresh`; an upstream bug report for the `sem` CLI is drafted as a doc but NOT filed.

**Tech Stack:** Python 3 (uv-managed, non-package project), unittest + unittest.mock, ruff (sole linter), gh CLI.

## Global Constraints

- Test runner: `uv run pytest tests/<file> -q` per task; full suite `uv run pytest tests/ -q` before each PR.
- Lint: `uv run ruff check .` — must be clean before every commit.
- Never `git add -A`; stage named files only.
- GitHub remotes are SSH and Touch ID-gated; pushes/PR ops require the user present. If a push fails waiting for the key, wait and retry the same command — never fall back to HTTPS.
- Plugin version bumps: `deps/.claude-plugin/plugin.json` 2.0.3 → 2.0.4 (PR 1); `dev/.claude-plugin/plugin.json` 2.4.2 → 2.4.3 (PR 2).
- After editing any SKILL.md or plugin.json, regenerate Codex manifests: `uv run python scripts/gen_codex_manifests.py`, then `uv run pytest tests/test_codex_manifests.py -q`; commit regenerated files if changed.
- Repo merges are squash merges to `main` (match existing history, e.g. `fix(bump): … (v2.0.3) (#27)`).
- Do NOT file anything against `ataraxy-labs/sem` — the upstream issue is drafted locally only (user decision 2026-08-13).

## File Structure

- Create: `deps/scripts/bumplib/gitfiles.py` — `changed_files()` helper (git-verified filesModified).
- Create: `tests/test_bump_gitfiles.py` — tests for the helper (real temp git repos).
- Modify: `deps/scripts/bumplib/ecosystems/python.py` — apply exit codes (#32), outdated auto-sync (#28).
- Modify: `deps/scripts/bumplib/ecosystems/go.py` — apply exit codes (#32).
- Modify: `deps/scripts/bumplib/ecosystems/node.py` — apply exit codes (#32).
- Modify: `tests/test_bump_eco_python.py`, `tests/test_bump_eco_go.py`, `tests/test_bump_eco_node.py`.
- Modify: `deps/skills/bump/reference/contracts.md` — apply verb error shape; filesModified semantics.
- Modify: `deps/skills/bump/SKILL.md` — Phase 7/8 error handling; outdated/audit cross-check note.
- Modify: `dev/scripts/sem_annotate.py` — `sha_reachable()` + `orphaned` status (#30).
- Modify: `tests/test_sem_annotate.py`.
- Modify: `dev/skills/sem-annotate/SKILL.md` — status vocabulary.
- Create: `docs/upstream/sem-orphaned-anchor-staleness.md` — upstream issue draft (not filed).
- Modify: `deps/.claude-plugin/plugin.json`, `dev/.claude-plugin/plugin.json` — version bumps.

---

### Task 1: `changed_files` git helper

**Files:**
- Create: `deps/scripts/bumplib/gitfiles.py`
- Test: `tests/test_bump_gitfiles.py`

**Interfaces:**
- Produces: `changed_files(candidates: list[str], cwd=".") -> list[str]` — subset of `candidates` (order preserved) that `git status --porcelain` reports as changed/untracked; returns `candidates` unchanged when git is unavailable or `cwd` is not a repo.

- [ ] **Step 1: Create branch**

```bash
git checkout -b fix/bump-apply-outdated main
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_bump_gitfiles.py`:

```python
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from bumplib.gitfiles import changed_files

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_AUTHOR_DATE": "2026-01-01T00:00:00",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00",
           "HOME": "/dev/null", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True)


class TestChangedFiles(unittest.TestCase):
    """apply must report the files git actually saw change, not a hardcoded list."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _git(self.root, "init", "-q")
        (self.root / "go.mod").write_text("module x\n")
        (self.root / "go.sum").write_text("")
        _git(self.root, "add", "go.mod", "go.sum")
        _git(self.root, "commit", "-qm", "init")

    def test_reports_only_the_candidates_that_changed(self):
        (self.root / "go.mod").write_text("module x\nrequire y v1.0.0\n")
        self.assertEqual(changed_files(["go.mod", "go.sum"], cwd=self.root), ["go.mod"])

    def test_untracked_candidate_counts_as_changed(self):
        (self.root / "uv.lock").write_text("x")
        self.assertEqual(changed_files(["pyproject.toml", "uv.lock"], cwd=self.root), ["uv.lock"])

    def test_clean_tree_reports_nothing(self):
        self.assertEqual(changed_files(["go.mod", "go.sum"], cwd=self.root), [])

    def test_non_repo_falls_back_to_candidates(self):
        with TemporaryDirectory() as plain:
            self.assertEqual(changed_files(["a", "b"], cwd=plain), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_bump_gitfiles.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'bumplib.gitfiles'`

- [ ] **Step 4: Write the implementation**

Create `deps/scripts/bumplib/gitfiles.py`:

```python
"""Which candidate files actually changed, according to git."""
import subprocess


def changed_files(candidates, cwd="."):
    """Subset of candidates (order preserved) that git reports modified or untracked.

    apply's contract promises the files it changed; a hardcoded list lies whenever the
    underlying command no-ops or fails. When git itself is unavailable (not a repo, no
    binary) degrade to the candidates unchanged -- the old behavior beats crashing.
    """
    try:
        r = subprocess.run(["git", "status", "--porcelain", "--", *candidates],
                           cwd=cwd, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return list(candidates)
    dirty = {line[3:].strip().strip('"') for line in r.stdout.splitlines() if len(line) > 3}
    return [c for c in candidates if c in dirty]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_bump_gitfiles.py -q`
Expected: 4 passed

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check .
git add deps/scripts/bumplib/gitfiles.py tests/test_bump_gitfiles.py
git commit -m "feat(bump): add git-verified changed_files helper"
```

---

### Task 2: Python `apply` checks exit codes (#32)

**Files:**
- Modify: `deps/scripts/bumplib/ecosystems/python.py:151-161`
- Test: `tests/test_bump_eco_python.py`

**Interfaces:**
- Consumes: `changed_files(candidates, cwd)` from Task 1.
- Produces: `apply` returns `{"applied": [...], "filesModified": [...]}` on success (filesModified git-verified) or `{"applied": [], "filesModified": [], "error": "<cmd>: <output tail>"}` on the first failing subprocess. Tasks 3–5 mirror this exact shape.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bump_eco_python.py` (uses the file's existing conventions: `enterContext`, `_path`, module-namespace patching):

```python
class TestApplyReportsFailure(unittest.TestCase):
    """apply must surface a failed package-manager command, never report success (#32)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "pyproject.toml").write_text("[project]\nname='x'\n")
        self.calls = []
        self.fail_on = None          # substring of argv marking the command that fails
        self.enterContext(mock.patch("bumplib.ecosystems.python.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.python._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.python.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))
        self.enterContext(mock.patch("bumplib.ecosystems.python.detect",
                                     return_value={"packageManager": "uv", "present": True}))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args, env=None):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return mock.Mock(returncode=1, stdout="", stderr="resolution is unsatisfiable")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_uv_lock_failure_surfaces_error(self):
        self.fail_on = "lock"
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("unsatisfiable", res["error"])
        self.assertFalse(any("sync" in c for c in self.calls))   # stops at first failure

    def test_uv_sync_failure_surfaces_error(self):
        self.fail_on = "sync"
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)

    def test_success_reports_git_verified_files(self):
        res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], ["tqdm==4.70.0"])
        self.assertEqual(res["filesModified"], ["pyproject.toml", "uv.lock"])
        self.assertNotIn("error", res)

    def test_pip_install_failure_surfaces_error(self):
        with mock.patch("bumplib.ecosystems.python.detect",
                        return_value={"packageManager": "pip", "present": True}):
            self.fail_on = "install"
            res = py.handle("apply", ["tqdm==4.70.0"])
        self.assertEqual(res["applied"], [])
        self.assertIn("error", res)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bump_eco_python.py -q`
Expected: the four new tests FAIL (no `changed_files` attribute to patch / success asserted where error expected)

- [ ] **Step 3: Write the implementation**

In `deps/scripts/bumplib/ecosystems/python.py`, add to imports (after `from ..categorize import classify_bump`):

```python
from ..gitfiles import changed_files
```

Replace the `apply` branch (currently lines 151-161):

```python
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
```

Note: `_run` gains an `env=None` parameter in Task 6; writing `def _run(args, env=None)` now with `env=env` passed through is fine and keeps the mock signature above valid. If doing Task 2 standalone, keep `_run(args)` and drop `env=None` from `_record` — but the plan executes Tasks 2 and 6 on the same branch, so use the two-parameter form from the start:

```python
def _run(args, env=None):
    """Safe: list form, no shell."""
    return subprocess.run(args, capture_output=True, text=True, env=env)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bump_eco_python.py -q`
Expected: all pass (existing classes included)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add deps/scripts/bumplib/ecosystems/python.py tests/test_bump_eco_python.py
git commit -m "fix(bump): python apply surfaces package-manager failures (#32)"
```

---

### Task 3: Go `apply` checks exit codes (#32)

**Files:**
- Modify: `deps/scripts/bumplib/ecosystems/go.py:116-123`
- Test: `tests/test_bump_eco_go.py`

**Interfaces:**
- Consumes: `changed_files(candidates, cwd)` from Task 1; same error shape as Task 2.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bump_eco_go.py`:

```python
from pathlib import Path as _P
from tempfile import TemporaryDirectory


class TestApplyReportsFailure(unittest.TestCase):
    """apply must surface a failed go command, never report success (#32)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = _P(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.root / "go.mod").write_text("module x\n")
        self.calls = []
        self.fail_on = None
        self.enterContext(mock.patch("bumplib.ecosystems.go.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.go._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.go.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))

    def _path(self, p):
        return self.root if str(p) == "." else _P(p)

    def _record(self, args):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return mock.Mock(returncode=1, stdout="", stderr="invalid version: unknown revision")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_go_get_failure_surfaces_error(self):
        self.fail_on = "get"
        res = go.handle("apply", ["github.com/foo/bar@v9.9.9"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("unknown revision", res["error"])
        self.assertFalse(any("tidy" in c for c in self.calls))

    def test_go_mod_tidy_failure_surfaces_error(self):
        self.fail_on = "tidy"
        res = go.handle("apply", ["github.com/foo/bar@v1.2.3"])
        self.assertIn("error", res)
        self.assertEqual(res["applied"], [])

    def test_success_reports_git_verified_files(self):
        res = go.handle("apply", ["github.com/foo/bar@v1.2.3"])
        self.assertEqual(res["applied"], ["github.com/foo/bar@v1.2.3"])
        self.assertEqual(res["filesModified"], ["go.mod", "go.sum"])
        self.assertNotIn("error", res)
```

(If `tests/test_bump_eco_go.py` lacks `from unittest import mock` usage in classes with `enterContext`, the imports at the top of the file already cover `unittest`, `mock`, `Path` — adjust the local `_P`/`TemporaryDirectory` imports to the top of the file per ruff.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bump_eco_go.py -q`
Expected: new tests FAIL

- [ ] **Step 3: Write the implementation**

In `deps/scripts/bumplib/ecosystems/go.py`, add import `from ..gitfiles import changed_files` next to the existing relative imports, then replace the `apply` branch:

```python
    if verb == "apply":
        steps = [["go", "get", spec] for spec in argv]   # spec e.g. "github.com/foo/bar@v1.2.3"
        steps.append(["go", "mod", "tidy"])
        if (root / "go.work").exists():
            steps.append(["go", "work", "sync"])
        for cmd in steps:
            r = _run(cmd)
            if r.returncode != 0:
                return {"applied": [], "filesModified": [],
                        "error": f"{' '.join(cmd)}: " + (r.stdout + r.stderr)[-4000:]}
        return {"applied": argv, "filesModified": changed_files(["go.mod", "go.sum"], cwd=root)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bump_eco_go.py -q`
Expected: all pass

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add deps/scripts/bumplib/ecosystems/go.py tests/test_bump_eco_go.py
git commit -m "fix(bump): go apply surfaces command failures (#32)"
```

---

### Task 4: Node `apply` checks exit codes (#32)

**Files:**
- Modify: `deps/scripts/bumplib/ecosystems/node.py:277-298`
- Test: `tests/test_bump_eco_node.py`

**Interfaces:**
- Consumes: `changed_files(candidates, cwd)` from Task 1; same error shape as Task 2. Node keeps its existing derivation of the candidate set (lockfile + rewritten manifests) and filters it through `changed_files`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bump_eco_node.py` a class following `TestApply`'s conventions exactly (same `setUp` fixture tree with root `package.json`, workspace manifest, `package-lock.json`), plus:

```python
class TestApplyReportsFailure(unittest.TestCase):
    """apply must surface a failed npm/pnpm command, never report success (#32)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _write(self.root / "package.json",
               {"name": "monorepo", "devDependencies": {"eslint": "^10.3.0"}})
        (self.root / "package-lock.json").write_text("{}")
        self.calls = []
        self.fail_on = None
        self.enterContext(mock.patch("bumplib.ecosystems.node.Path", side_effect=self._path))
        self.enterContext(mock.patch("bumplib.ecosystems.node._run", side_effect=self._record))
        self.enterContext(mock.patch("bumplib.ecosystems.node.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))

    def _path(self, p):
        return self.root if str(p) == "." else Path(p)

    def _record(self, args):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and self.fail_on in args:
            return mock.Mock(returncode=1, stdout="", stderr="ERESOLVE unable to resolve")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def test_update_failure_surfaces_error(self):
        self.fail_on = "update"
        res = node.handle("apply", ["eslint@10.8.0"])
        self.assertEqual(res["applied"], [])
        self.assertEqual(res["filesModified"], [])
        self.assertIn("ERESOLVE", res["error"])
        self.assertFalse(any(c[-1:] == ["install"] for c in self.calls))  # stops before final install

    def test_install_failure_surfaces_error(self):
        self.fail_on = "install"
        res = node.handle("apply", ["eslint@10.8.0"])
        self.assertIn("error", res)

    def test_success_shape_unchanged(self):
        res = node.handle("apply", ["eslint@10.8.0"])
        self.assertEqual(res["applied"], ["eslint@10.8.0"])
        # eslint is declared in the root manifest, so its location joins the lockfile
        self.assertEqual(res["filesModified"], ["package-lock.json", "package.json"])
        self.assertNotIn("error", res)
```

Also update the existing `TestApply.setUp` to add the same `changed_files` passthrough patch (its `test_files_modified_reports_real_manifests` and `test_pnpm_targets_workspace_by_name` assert `filesModified` contents, which now flow through `changed_files`):

```python
        self.enterContext(mock.patch("bumplib.ecosystems.node.changed_files",
                                     side_effect=lambda cands, cwd=None: list(cands)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bump_eco_node.py -q`
Expected: new tests FAIL (attribute to patch missing)

- [ ] **Step 3: Write the implementation**

In `deps/scripts/bumplib/ecosystems/node.py`, add import `from ..gitfiles import changed_files` next to the existing relative imports. In the `apply` branch, define a local checker and route every `_run` through it:

```python
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
                err = _checked(_install_cmd(mgr, name, version, decl))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bump_eco_node.py -q`
Expected: all pass, including the pre-existing `TestApply` class

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check .
git add deps/scripts/bumplib/ecosystems/node.py tests/test_bump_eco_node.py
git commit -m "fix(bump): node apply surfaces command failures (#32)"
```

---

### Task 5: Contract + SKILL.md updates for apply errors (#32)

**Files:**
- Modify: `deps/skills/bump/reference/contracts.md` (apply row of the ecosystem verb table, ~line 180)
- Modify: `deps/skills/bump/SKILL.md` (Phase 7 ~line 228, Phase 8 ~line 264)

- [ ] **Step 1: Update contracts.md**

Replace the `apply` row's Notes cell so it reads (keeping the existing Node range-widening sentences):

> `{"applied": [spec, ...], "filesModified": [path, ...]}` on success — `filesModified` is verified against `git status` and lists only files that actually changed. On any underlying package-manager command failing, returns `{"applied": [], "filesModified": [], "error": "<failed command>: <output tail>"}` — the working tree may hold partial changes from earlier commands in the batch; callers must treat `error` as "nothing durably applied" and revert before retrying. Pass fully-qualified specs (`name@X.Y.Z`); a bare name still works but only permits a within-range move. Node honors the version: a declared dependency whose target is provably outside its range is installed into its own workspace so the manifest range widens, while bare names, transitive packages and unrecognized range forms stay on `update` and touch only the lockfile.

- [ ] **Step 2: Update SKILL.md Phase 7**

After the `bump.py ecosystem <eco> apply <spec> <spec> ...` line (~238), add:

> **If `apply` returns an `error` field:** nothing was durably applied (the tree may hold partial changes). Run `git checkout -- .` to reset, record every spec in the batch as problematic with the error tail, and fall through to the one-at-a-time re-apply below to isolate which spec (if any) can land — a spec whose solo `apply` also errors is recorded with its error and skipped. Never proceed to validate or commit on an `error` result.

- [ ] **Step 3: Update SKILL.md Phase 8**

In the staging step (~line 274), amend the first sentence to:

> **Stage** manifests + lockfiles using the `filesModified` lists from successful `apply` results (these are git-verified; an `apply` that returned `error` contributes nothing) ...

- [ ] **Step 4: Commit**

```bash
uv run ruff check .
git add deps/skills/bump/reference/contracts.md deps/skills/bump/SKILL.md
git commit -m "docs(bump): apply error contract and Phase 7/8 handling (#32)"
```

---

### Task 6: Python `outdated` auto-sync when venv missing (#28)

**Files:**
- Modify: `deps/scripts/bumplib/ecosystems/python.py:133-142` (outdated branch), `_run` (env param — done in Task 2)
- Modify: `deps/skills/bump/SKILL.md` (troubleshooting notes, near "Network/registry errors" ~line 414)
- Test: `tests/test_bump_eco_python.py` (class `TestProjectEnvironmentTargeting`)

**Interfaces:**
- Produces: `outdated` for uv projects: if no project venv and `uv.lock` exists, runs `uv sync` first, then re-resolves the interpreter. If still no venv, warns on stderr and strips `VIRTUAL_ENV` from the subprocess env so the ephemeral PEP 723 env can never answer.

- [ ] **Step 1: Rewrite/extend the tests**

In `tests/test_bump_eco_python.py`, class `TestProjectEnvironmentTargeting`:

Replace `test_outdated_without_venv_omits_flag` (it asserts the buggy fallback) with:

```python
    def test_no_venv_with_lockfile_auto_syncs_then_targets_venv(self):
        """#28: a fresh clone has uv.lock but no .venv; querying the ambient env returns
        [] for every project. outdated must create the env, then ask it."""
        (self.root / "uv.lock").write_text("")
        exe_holder = {}

        def record(args, env=None):
            args = list(args)
            self.calls.append(args)
            if args[:2] == ["uv", "sync"]:
                exe_holder["exe"] = _make_venv(self.root)
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record):
            py.handle("outdated", [])
        self.assertEqual(self.calls[0][:2], ["uv", "sync"])
        listing = self.calls[1]
        self.assertIn("--python", listing)
        self.assertEqual(listing[listing.index("--python") + 1], str(exe_holder["exe"]))

    def test_no_venv_no_lockfile_skips_sync_and_strips_virtual_env(self):
        """Lockless project: don't create an env, but never let the ephemeral
        VIRTUAL_ENV answer 'what is installed?'."""
        captured = {}

        def record(args, env=None):
            self.calls.append(list(args))
            captured["env"] = env
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record), \
                mock.patch.dict(os.environ, {"VIRTUAL_ENV": "/ephemeral"}):
            py.handle("outdated", [])
        self.assertFalse(any(c[:2] == ["uv", "sync"] for c in self.calls))
        self.assertNotIn("--python", self.calls[0])
        self.assertIsNotNone(captured["env"])
        self.assertNotIn("VIRTUAL_ENV", captured["env"])

    def test_sync_failure_still_queries_without_virtual_env(self):
        (self.root / "uv.lock").write_text("")

        def record(args, env=None):
            args = list(args)
            self.calls.append(args)
            rc = 1 if args[:2] == ["uv", "sync"] else 0
            return mock.Mock(returncode=rc, stdout="", stderr="boom")

        with mock.patch("bumplib.ecosystems.python._run", side_effect=record):
            py.handle("outdated", [])
        self.assertNotIn("--python", self.calls[1])
```

Also update the class's shared `_record` signature to `def _record(self, args, env=None):` so the venv-present tests keep passing.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_bump_eco_python.py -q`
Expected: the three new/changed tests FAIL

- [ ] **Step 3: Write the implementation**

In `deps/scripts/bumplib/ecosystems/python.py`, add `import sys` to the imports. Replace the `outdated` branch:

```python
    if verb == "outdated":
        if mgr == "uv":
            venv = _project_python(root)
            if venv is None and (root / "uv.lock").exists():
                # Fresh clone / rm -rf .venv: there is a lockfile to honor but no
                # environment to inspect. Create it -- `uv sync` runs later in the
                # flow anyway -- rather than silently querying the ephemeral env (#28).
                if _run(["uv", "sync"]).returncode == 0:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_bump_eco_python.py -q`
Expected: all pass

- [ ] **Step 5: Add the cross-check note to SKILL.md**

In `deps/skills/bump/SKILL.md`, in the notes near "**Network/registry errors:**" (~line 414), add a sibling bullet:

> - **Empty `outdated` beside non-empty `audit`:** an ecosystem whose `audit` lists advisories while its `outdated` is `[]` is inconsistent — the environment query was probably vacuous. Re-run that `outdated` once; if still empty, surface the discrepancy in the report (list the advisories as un-actioned) instead of reporting a clean run.

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check .
git add deps/scripts/bumplib/ecosystems/python.py tests/test_bump_eco_python.py deps/skills/bump/SKILL.md
git commit -m "fix(bump): python outdated auto-syncs missing venv, strips VIRTUAL_ENV fallback (#28)"
```

---

### Task 7: Version bump, manifests, full validation, PR 1

**Files:**
- Modify: `deps/.claude-plugin/plugin.json` (version 2.0.3 → 2.0.4)
- Possibly regenerated Codex manifest files (whatever `gen_codex_manifests.py` touches)

- [ ] **Step 1: Bump the plugin version**

Edit `deps/.claude-plugin/plugin.json`: `"version": "2.0.4"`.

- [ ] **Step 2: Regenerate Codex manifests**

```bash
uv run python scripts/gen_codex_manifests.py
git status --short   # note what changed
uv run pytest tests/test_codex_manifests.py -q
```

- [ ] **Step 3: Full validation**

```bash
uv run pytest tests/ -q
uv run ruff check .
```

Expected: full suite passes, lint clean. Fix anything that fails before proceeding.

- [ ] **Step 4: Commit and open the PR** (user must be present for the SSH push — Touch ID)

```bash
git add deps/.claude-plugin/plugin.json <regenerated manifest files, if any>
git commit -m "chore(deps-plugin): v2.0.4"
git push -u origin fix/bump-apply-outdated
gh pr create --title "fix(bump): apply surfaces failures; outdated auto-syncs missing venv (v2.0.4)" --body "Fixes #32. Fixes #28.

- apply (python/go/node) checks every package-manager exit code and returns {applied: [], filesModified: [], error} on failure; filesModified is now verified against git status.
- Python outdated auto-runs uv sync when uv.lock exists but no venv; strips VIRTUAL_ENV when it must fall back; warns on stderr.
- contracts.md + SKILL.md updated (Phase 7 revert-on-error, Phase 8 staging, outdated/audit cross-check).

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 5: Squash-merge after checks pass, delete branch, return to main**

```bash
gh pr checks <number> --watch
gh pr merge <number> --squash --delete-branch
git checkout main && git pull
```

---

### Task 8: `sem_annotate.py` orphaned-anchor detection (#30)

**Files:**
- Modify: `dev/scripts/sem_annotate.py` (`scan()` ~lines 237-268; new helper near `head_sha` ~line 198)
- Test: `tests/test_sem_annotate.py`

**Interfaces:**
- Produces: `sha_reachable(sha, cwd=None) -> bool`; scan worklist entries may now carry `"status": "orphaned"` (with `bad_sha` like the existing `invalid-sha` entries); a stderr warning summarizes orphan count.

- [ ] **Step 1: Create branch**

```bash
git checkout -b fix/sem-orphaned-anchors main
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_sem_annotate.py` (it imports the module as `sa`; follow its conventions):

```python
class TestShaReachable(unittest.TestCase):
    """Squash-merge orphans branch commits: they resolve as objects but are not
    ancestors of HEAD, and sem diff against them silently reports nothing (#30)."""

    GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
               "HOME": "/dev/null", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"}

    def _git(self, *args):
        r = subprocess.run(["git", *args], cwd=self.root, env=self.GIT_ENV,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self._git("init", "-q", "-b", "main")
        (self.root / "a.txt").write_text("1\n")
        self._git("add", "a.txt"); self._git("commit", "-qm", "base")
        self.base = self._git("rev-parse", "HEAD")
        self._git("checkout", "-qb", "feat")
        (self.root / "a.txt").write_text("2\n")
        self._git("commit", "-qam", "feat work")
        self.branch_sha = self._git("rev-parse", "HEAD")
        self._git("checkout", "-q", "main")
        self._git("merge", "--squash", "feat")
        self._git("commit", "-qm", "squashed")
        self._git("branch", "-qD", "feat")

    def test_reachable_ancestor(self):
        self.assertTrue(sa.sha_reachable(self.base, cwd=self.root))

    def test_orphaned_commit_resolves_but_is_unreachable(self):
        # the object still exists...
        subprocess.run(["git", "cat-file", "-e", self.branch_sha], cwd=self.root,
                       env=self.GIT_ENV, check=True)
        # ...but must be treated as unreachable
        self.assertFalse(sa.sha_reachable(self.branch_sha, cwd=self.root))

    def test_garbage_sha_is_unreachable(self):
        self.assertFalse(sa.sha_reachable("zzzzzzz", cwd=self.root))


class TestScanClassifiesOrphaned(unittest.TestCase):
    """An unreachable anchor must never classify fresh -- sem diff cannot compute
    against it, so the silent no-op previously hid every squash-merged stale marker."""

    def setUp(self):
        ent = {"name": "F", "type": "function", "file": "a.go",
               "start_line": 2, "end_line": 4}
        self.enterContext(mock.patch.object(sa, "sem_entities", return_value=[ent]))
        self.enterContext(mock.patch.object(sa, "sem_blame", return_value=[]))
        self.enterContext(mock.patch.object(sa, "entity_logic_sha", return_value="a1b2c3d4e5"))
        self.enterContext(mock.patch.object(
            sa, "_read_text", return_value="// SEM@deadbee: does a thing\nfunc F() {}\n"))
        self.diff = self.enterContext(mock.patch.object(sa, "logic_changed_entities"))

    def test_unreachable_anchor_yields_orphaned_not_fresh(self):
        with mock.patch.object(sa, "sha_reachable", return_value=False):
            work = sa.scan(["a.go"])
        self.assertEqual(len(work), 1)
        self.assertEqual(work[0]["status"], "orphaned")
        self.assertEqual(work[0]["bad_sha"], "deadbee")
        self.diff.assert_not_called()          # sem diff against an orphan is meaningless

    def test_reachable_anchor_still_uses_sem_diff(self):
        self.diff.return_value = set()          # cosmetic-only change
        with mock.patch.object(sa, "sha_reachable", return_value=True):
            work = sa.scan(["a.go"])
        self.assertEqual(work, [])              # fresh: not in worklist
        self.diff.assert_called_once()
```

(Add any missing imports — `subprocess`, `TemporaryDirectory`, `Path` — to the file's top-level imports if not already present.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_sem_annotate.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'sha_reachable'`

- [ ] **Step 4: Write the implementation**

In `dev/scripts/sem_annotate.py`, ensure `import sys` is present. Add below `head_sha()`:

```python
def sha_reachable(sha, cwd=None):
    """True when sha is an ancestor of HEAD.

    Squash-merge workflows orphan every branch commit: the objects still resolve, but
    `sem diff <orphan>..HEAD` silently reports no changes, which classified genuinely
    stale markers as fresh (issue #30). An anchor we cannot compare against must be
    re-anchored, never trusted.
    """
    r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, "HEAD"],
                       cwd=cwd, capture_output=True, text=True)
    return r.returncode == 0
```

In `scan()`, inside the block guarded by `if existing_sha and not _is_uncommitted(anchor_sha) and not anchor_sha.startswith(existing_sha):`, insert BEFORE the `try: logic = ...` call:

```python
                    if not sha_reachable(existing_sha, cwd=cwd):
                        work.append({
                            "file": f, "name": e["name"],
                            "start_line": e["start_line"], "end_line": e["end_line"],
                            "status": "orphaned", "anchor_sha": anchor_sha,
                            "existing_desc": existing_desc, "bad_sha": existing_sha,
                        })
                        continue
```

At the end of `scan()`, before `return work`:

```python
    orphans = sum(1 for w in work if w["status"] == "orphaned")
    if orphans:
        print(f"warning: {orphans} marker(s) anchored to commits unreachable from HEAD "
              "(orphaned by squash-merge or history rewrite); staleness could not be "
              "computed against them, so they are queued for re-annotation.",
              file=sys.stderr)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_sem_annotate.py -q`
Expected: all pass

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check .
git add dev/scripts/sem_annotate.py tests/test_sem_annotate.py
git commit -m "fix(sem-annotate): classify unreachable anchors as orphaned, never fresh (#30)"
```

---

### Task 9: SKILL.md vocab, upstream draft, version bump, PR 2

**Files:**
- Modify: `dev/skills/sem-annotate/SKILL.md` (status vocabulary, ~line 150)
- Create: `docs/upstream/sem-orphaned-anchor-staleness.md`
- Modify: `dev/.claude-plugin/plugin.json` (2.4.2 → 2.4.3)

- [ ] **Step 1: Add `orphaned` to the status vocabulary**

In `dev/skills/sem-annotate/SKILL.md` under "**Status vocabulary:**", after the `stale` entry add:

```markdown
- `orphaned` — marker present but its anchor commit is no longer reachable from HEAD
  (typically orphaned by a squash-merge); staleness cannot be computed against it, so
  the entity is re-described and re-anchored at a reachable commit
```

- [ ] **Step 2: Write the upstream issue draft** (do NOT file it)

Create `docs/upstream/sem-orphaned-anchor-staleness.md`:

```markdown
# DRAFT upstream issue for ataraxy-labs/sem — not yet filed

Adapted from ericfitz/skills#30. Review before filing.

---

**Title:** `sem diff <base>..HEAD` silently reports no changes when `<base>` is an
orphaned commit (squash-merge workflows), so staleness checks built on it never fire

## Summary

When the base revision passed to `sem diff` (and consumed by scan/update flows built on
it) resolves as a git object but is **not reachable from HEAD**, sem reports no changes
instead of erroring or flagging the condition. In squash-merge workflows this is the
normal end state for any commit recorded on a feature branch: after the squash-merge the
original commits become orphaned objects — `git cat-file -e <sha>` succeeds, but
`git merge-base --is-ancestor <sha> HEAD` exits 1.

Any tooling that anchors semantic state to a commit sha and later asks sem "did this
entity change since `<sha>`?" gets a silent false "no" for every pre-squash anchor. The
failure does not self-report: no error, no warning, exit 0.

## Reproduction

1. In a repo using squash merges: record a sha on a feature branch (any commit that
   touches a tracked function).
2. Squash-merge the branch to main; delete the branch.
3. Change the function's behavior on main.
4. Run `sem diff <branch-sha>..HEAD --no-cosmetics -- <file>`.

Expected: an error (unreachable base) or the logical change reported.
Actual: empty diff, exit 0.

Check: `git merge-base --is-ancestor <sha> HEAD; echo $?` → `1` for affected shas.

## Impact

Squash-merge is a very common GitHub workflow, so any sem-based staleness tracking
silently stops working for a repo's entire pre-squash history. Users reasonably conclude
"nothing changed" and move on.

## Suggested fixes (any of)

1. During diff/scan, check base reachability (`merge-base --is-ancestor`); treat an
   unreachable base as an error or a distinct "orphaned" result — never as "no changes".
2. Fall back to comparing against the nearest reachable commit instead of giving up.
3. At minimum, emit a loud warning when a base fails reachability so the silent mode is
   impossible.
4. Longer-term: content-hash anchors (hash of the entity's normalized body) instead of
   commit shas — immune to history rewriting entirely.

Options 1 + 3 together would have surfaced this immediately.

## Environment

- sem-cli 0.21.0 (Homebrew), macOS (darwin 25.6.0)
- Observed via SEM@sha marker tooling in ericfitz/skills (see ericfitz/skills#30 for the
  downstream write-up and the consumer-side workaround)
```

- [ ] **Step 3: Version bump + manifests + full validation**

Edit `dev/.claude-plugin/plugin.json`: `"version": "2.4.3"`. Then:

```bash
uv run python scripts/gen_codex_manifests.py
uv run pytest tests/ -q
uv run ruff check .
```

- [ ] **Step 4: Commit and open PR 2** (user present for SSH push)

```bash
git add dev/skills/sem-annotate/SKILL.md docs/upstream/sem-orphaned-anchor-staleness.md dev/.claude-plugin/plugin.json <regenerated manifests, if any>
git commit -m "fix(sem-annotate): orphaned-anchor status docs, upstream draft, v2.4.3 (#30)"
git push -u origin fix/sem-orphaned-anchors
gh pr create --title "fix(sem-annotate): detect anchors orphaned by squash-merge (v2.4.3)" --body "Fixes #30.

- scan() checks git merge-base --is-ancestor before trusting sem diff; unreachable anchors classify 'orphaned' and re-enter the worklist (loud stderr warning).
- SKILL.md status vocabulary documents 'orphaned'.
- Upstream sem CLI issue drafted at docs/upstream/sem-orphaned-anchor-staleness.md — intentionally NOT filed yet.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 5: Comment on issue #30, then merge**

```bash
gh issue comment 30 --body "Consumer-side fix shipped in dev v2.4.3: sem_annotate.py now checks anchor reachability (git merge-base --is-ancestor) and classifies unreachable anchors as 'orphaned' (re-annotated + re-anchored) instead of silently 'fresh'. Root cause is in the sem CLI itself; an upstream report is drafted at docs/upstream/sem-orphaned-anchor-staleness.md, pending review before filing against ataraxy-labs/sem."
gh pr checks <number> --watch
gh pr merge <number> --squash --delete-branch
git checkout main && git pull
```

---

### Task 10: Defer issue #5 with a comment

- [ ] **Step 1: Comment (do not close)**

```bash
gh issue comment 5 --body "Triage 2026-08-13: staying deferred by design — this investigation is gated on the sem toolchain being validated against the tmi server codebase, which hasn't happened yet. When it unblocks, the first step is the cheap one: hand-label a duplicate set from tmi and measure the lexical pre-filter's actual recall before investing in embeddings."
```

---

### Task 11: Run `/bump` on this repo (with the fixed tooling)

- [ ] **Step 1: Preconditions**

Both PRs squash-merged, `main` checked out and pulled, working tree clean.

- [ ] **Step 2: Invoke the skill**

Invoke the `deps:bump` skill (i.e., run `/bump`) against this repo and follow it end to end. This dogfoods both fixes: this repo is a uv project (the #28 shape) and any real apply failure now surfaces (#32).

- [ ] **Step 3: Report**

Summarize the bump results per the skill's report format, and note whether the new code paths (auto-sync, error contract) were exercised.

---

## Final summary reminder (user-requested)

When all work is complete, the work summary MUST remind the user:

> **Follow-up:** review `docs/upstream/sem-orphaned-anchor-staleness.md` and decide whether to file it against `ataraxy-labs/sem`.
