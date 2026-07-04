# Local Config Conventions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize every skill on one repo registry (`.local/repos.json`, name-keyed) and one GitHub Project cache (`.local/gh-projects.json`, name-keyed), provisioned by a single out-of-band script, and eliminate the `update-project-cache` skill and all `*_REPO` env-var repo locations.

**Architecture:** A standalone, uncommitted `~/Scripts/provision-repo-config.py` (ported from the current `github/scripts/update_project_cache.py`) becomes the sole writer/migrator of both `.local/` files: it resolves a repo's GitHub Project, enumerates metadata, writes both files, migrates any legacy shape, and prompts interactively. The four consuming skills (`create-issue`, `verify-doc`, `vrt`, and the removed `update-project-cache`) become read-only or are deleted. Repo manifests, README, the marketplace verifier, and the global `.local/` convention note are updated to match.

**Tech Stack:** Python 3 (stdlib only; PEP-723 script header), `gh` CLI, `git`, unittest, jq (in skill bodies), Markdown skills.

## Global Constraints

- Registry file: `.local/repos.json` — a JSON object **keyed by name**: `{ "<name>": { "path": <str?>, "github": { "owner"?, "repo"?, "project"?, "wiki_path"? } } }`.
- Cache file: `.local/gh-projects.json` — keyed by `<name>`; entry schema unchanged from the prior `project-cache.json` (project id block; `fields` keyed by field name with ordered `{name,id}` option arrays; `milestones` ordered `{title,number,id}`; `labels` string list; `issue_types` string list).
- `github.project` semantics: absent/null = unresolved; `"Some Title"` = use it; `""` = "no project" (honored by `create-issue` only).
- No `*_REPO` environment variables for repo locations anywhere.
- Provisioning script path (verbatim, referenced by skills and docs): `~/Scripts/provision-repo-config.py`.
- Test runner: `python3 -m unittest` (pytest is NOT installed). Repo suite: `python3 -m unittest discover -s tests -p 'test_*.py'`.
- `~/Scripts` is **not** a git repo: the script and its test file are created there and are NOT committed. Their "done" gate is a green test run, not a commit. Only the in-repo changes (Tasks 5–9) produce git commits, on branch `standardize-local-config-conventions`.
- The script is copied from `github/scripts/update_project_cache.py` in Tasks 1–4; that file is deleted in Task 6. **Do Tasks 1–4 before Task 6.**

---

## File Structure

**External (uncommitted, in `~/Scripts/`):**
- `~/Scripts/provision-repo-config.py` — the run-once provisioner (ported + modified).
- `~/Scripts/test_provision_repo_config.py` — unittest suite for the provisioner.

**In-repo (committed on the branch):**
- Delete: `github/skills/update-project-cache/SKILL.md` (and its now-empty dir), `github/scripts/update_project_cache.py`, `tests/test_update_project_cache.py`.
- Modify: `github/skills/create-issue/SKILL.md`, `wiki/skills/verify-doc/SKILL.md`, `ui/skills/vrt/SKILL.md`, `github/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`, `scripts/verify-marketplace.sh`.

**Global (uncommitted):**
- `~/.claude/CLAUDE.md` — add a `.local/` convention section.
- `/Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/local-config-conventions.md` + `MEMORY.md` pointer.

---

### Task 1: Scaffold the provisioning script + test harness

**Files:**
- Create: `~/Scripts/provision-repo-config.py` (copied from the reference, then constants/docstring edited)
- Create: `~/Scripts/test_provision_repo_config.py`

**Interfaces:**
- Produces: module `provision_repo_config` (loaded from the hyphenated path via importlib) exposing all ported functions plus new constants `REPOS_FILENAME="repos.json"`, `CACHE_FILENAME="gh-projects.json"`, `LEGACY_CACHE_FILENAME="project-cache.json"`, `LEGACY_LOCAL_CONFIG="projects.json"`, `LEGACY_ROOT_CONFIG=".local-projects.json"`, `LOCAL_DIR=".local"`.

- [ ] **Step 1: Copy the reference script as the starting point**

```bash
cp /Users/efitz/Projects/skills/github/scripts/update_project_cache.py ~/Scripts/provision-repo-config.py
```

- [ ] **Step 2: Replace the constants block**

In `~/Scripts/provision-repo-config.py`, replace:

```python
LOCAL_DIR = ".local"
CONFIG_FILENAME = "projects.json"
CACHE_FILENAME = "project-cache.json"
LEGACY_CONFIG_FILENAME = ".local-projects.json"
```

with:

```python
LOCAL_DIR = ".local"
REPOS_FILENAME = "repos.json"                 # canonical registry
CACHE_FILENAME = "gh-projects.json"           # canonical cache
LEGACY_CACHE_FILENAME = "project-cache.json"  # legacy .local/ cache name
LEGACY_LOCAL_CONFIG = "projects.json"         # legacy .local/projects.json
LEGACY_ROOT_CONFIG = ".local-projects.json"   # legacy repo-root registry
```

- [ ] **Step 3: Update the module docstring**

Replace the docstring (lines 5–14, `"""Resolve a repo's GitHub Project ... """`) with:

```python
"""Provision a repo's local config: resolve its GitHub Project (v2) and cache metadata.

Writes/refreshes two name-keyed files under the repo's `.local/` dir:
  - repos.json       (registry: path + github {owner, repo, project, wiki_path})
  - gh-projects.json (cache: ids, fields, milestones, labels, issue types)

Migrates any legacy shape (root `.local-projects.json`, `.local/projects.json`,
`.local/project-cache.json`) into the canonical files. Run once per repo.

Usage:
    provision-repo-config.py update [--name NAME] [--dir DIR]
                                    [--select-title TITLE | --select-number N]
"""
```

- [ ] **Step 4: Create the test harness importing the hyphenated script**

Create `~/Scripts/test_provision_repo_config.py`:

```python
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True

_spec = importlib.util.spec_from_file_location(
    "provision_repo_config",
    Path(__file__).resolve().parent / "provision-repo-config.py",
)
prc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prc)


class TestConstants(unittest.TestCase):
    def test_canonical_names(self):
        self.assertEqual(prc.LOCAL_DIR, ".local")
        self.assertEqual(prc.REPOS_FILENAME, "repos.json")
        self.assertEqual(prc.CACHE_FILENAME, "gh-projects.json")
        self.assertEqual(prc.LEGACY_CACHE_FILENAME, "project-cache.json")
        self.assertEqual(prc.LEGACY_LOCAL_CONFIG, "projects.json")
        self.assertEqual(prc.LEGACY_ROOT_CONFIG, ".local-projects.json")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Port the still-valid pure-function tests**

From `/Users/efitz/Projects/skills/tests/test_update_project_cache.py`, copy these test classes **verbatim** into `~/Scripts/test_provision_repo_config.py` (above the `if __name__` block), replacing every `upc.` with `prc.`:
`TestBuildCacheEntry`, `TestParseRepoMetadata`, `TestParseFields`, `TestSelectProject`, `TestParseLinkedProjects`, `TestParseGitRemote`, `TestEnumeration`, and from `TestLocationAndIO` keep only `test_ensure_gitignore_adds_when_missing`, `test_ensure_gitignore_idempotent`, `test_ensure_gitignore_adds_trailing_newline`, `test_write_and_read_json_roundtrip`, and `TestUpdateCache`.
Do **not** copy `TestScaffold`, `TestConfigHelpers`, `TestProcessEntry`, `TestMain`, or the `find_config` tests — those cover functions being changed in Tasks 2–4.

- [ ] **Step 6: Run the test harness — expect green**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: all copied tests PASS (the script still contains the ported functions unchanged from the reference).

---

### Task 2: Name-keyed registry helpers + legacy normalization (TDD)

**Files:**
- Modify: `~/Scripts/provision-repo-config.py`
- Test: `~/Scripts/test_provision_repo_config.py`

**Interfaces:**
- Produces: `normalize_registry(raw) -> dict` (name-keyed map, drops `github.issues_project`); `get_entry(config, name) -> dict|None`; `set_project_title(config, name, title) -> dict`.
- Removes: `migrate_entry` (folded into `normalize_registry`).

- [ ] **Step 1: Write failing tests for the keyed helpers**

Add to `~/Scripts/test_provision_repo_config.py`:

```python
class TestNormalizeRegistry(unittest.TestCase):
    def test_bare_list(self):
        raw = [{"name": "tmi", "path": "/p", "github": {"owner": "e", "repo": "tmi"}}]
        self.assertEqual(prc.normalize_registry(raw),
                         {"tmi": {"path": "/p", "github": {"owner": "e", "repo": "tmi"}}})

    def test_wrapped_list(self):
        raw = {"projects": [{"name": "tmi", "github": {"repo": "tmi"}}]}
        self.assertEqual(prc.normalize_registry(raw),
                         {"tmi": {"github": {"repo": "tmi"}}})

    def test_already_keyed_passthrough(self):
        raw = {"tmi": {"path": "/p", "github": {"repo": "tmi"}}}
        self.assertEqual(prc.normalize_registry(raw), raw)

    def test_drops_issues_project(self):
        raw = {"projects": [{"name": "tmi", "github": {
            "owner": "e", "repo": "tmi", "project": "Roadmap",
            "issues_project": {"id": "PVT_x"}}}]}
        out = prc.normalize_registry(raw)
        self.assertEqual(out["tmi"]["github"],
                         {"owner": "e", "repo": "tmi", "project": "Roadmap"})

    def test_skips_entries_without_name(self):
        raw = [{"github": {}}, {"name": "ok", "github": {}}]
        self.assertEqual(list(prc.normalize_registry(raw)), ["ok"])

    def test_empty_map(self):
        self.assertEqual(prc.normalize_registry({}), {})


class TestKeyedHelpers(unittest.TestCase):
    def test_get_entry_found(self):
        cfg = {"tmi": {"github": {}}}
        self.assertIs(prc.get_entry(cfg, "tmi"), cfg["tmi"])

    def test_get_entry_missing(self):
        self.assertIsNone(prc.get_entry({}, "nope"))

    def test_set_title_existing(self):
        cfg = {"tmi": {"github": {"owner": "e"}}}
        prc.set_project_title(cfg, "tmi", "Roadmap")
        self.assertEqual(cfg["tmi"]["github"], {"owner": "e", "project": "Roadmap"})

    def test_set_title_creates_entry(self):
        cfg = {}
        prc.set_project_title(cfg, "newrepo", "")
        self.assertEqual(cfg, {"newrepo": {"github": {"project": ""}}})
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'normalize_registry'` (and `get_entry`/`set_project_title` still assume the old list shape).

- [ ] **Step 3: Replace `get_entry`/`set_project_title`/`migrate_entry` with keyed versions**

In `~/Scripts/provision-repo-config.py`, replace the three functions `get_entry`, `set_project_title`, and `migrate_entry` (currently around lines 159–183) with:

```python
def normalize_registry(raw):
    """Normalize any legacy registry shape into a name-keyed map.

    Accepts a bare list [{name, ...}], a wrapped {"projects": [...]}, or an
    already-keyed {name: {...}}. Drops any legacy github.issues_project block.
    """
    if isinstance(raw, dict) and isinstance(raw.get("projects"), list):
        entries = raw["projects"]
    elif isinstance(raw, list):
        entries = raw
    else:
        out = {}
        for name, entry in (raw or {}).items():
            e = dict(entry or {})
            gh = dict(e.get("github", {}))
            gh.pop("issues_project", None)
            e["github"] = gh
            out[name] = e
        return out
    out = {}
    for entry in entries:
        if not entry or not entry.get("name"):
            continue
        name = entry["name"]
        e = {k: v for k, v in entry.items() if k != "name"}
        gh = dict(e.get("github", {}))
        gh.pop("issues_project", None)
        e["github"] = gh
        out[name] = e
    return out


def get_entry(config, name):
    """Return the entry for `name` in the keyed registry, or None."""
    return (config or {}).get(name)


def set_project_title(config, name, title):
    """Set github.project for `name`, creating the entry if needed. Returns config."""
    entry = config.get(name)
    if entry is None:
        entry = {"github": {}}
        config[name] = entry
    entry.setdefault("github", {})["project"] = title
    return config
```

- [ ] **Step 4: Run to verify the new tests pass**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: `TestNormalizeRegistry` and `TestKeyedHelpers` PASS. (Discovery/main tests don't exist yet; `process_entry`/`main`/`_load_or_init_config` still reference old shapes but aren't imported by any current test — module still loads.)

---

### Task 3: Registry discovery, config load/init, cache-file migration (TDD)

**Files:**
- Modify: `~/Scripts/provision-repo-config.py`
- Test: `~/Scripts/test_provision_repo_config.py`

**Interfaces:**
- Produces: `find_registry(start_dir) -> (Path|None, str|None)` with kind ∈ `{"current","legacy_local","legacy_root", None}`; `load_or_init_config(start_dir) -> (dict, Path)` where Path is the canonical `<root>/.local/repos.json`; `migrate_cache_file(local_dir) -> Path`.
- Removes: `find_config`, `_load_or_init_config`.

- [ ] **Step 1: Write failing tests for discovery + load + cache migration**

Add to `~/Scripts/test_provision_repo_config.py`:

```python
class TestFindRegistry(unittest.TestCase):
    def test_prefers_current(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "repos.json").write_text("{}")
            (root / ".local" / "projects.json").write_text("{}")
            (root / ".local-projects.json").write_text("[]")
            self.assertEqual(prc.find_registry(root),
                             (root / ".local" / "repos.json", "current"))

    def test_legacy_local(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text("{}")
            (root / ".local-projects.json").write_text("[]")
            self.assertEqual(prc.find_registry(root),
                             (root / ".local" / "projects.json", "legacy_local"))

    def test_legacy_root(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-projects.json").write_text("[]")
            self.assertEqual(prc.find_registry(root),
                             (root / ".local-projects.json", "legacy_root"))

    def test_walks_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "repos.json").write_text("{}")
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            self.assertEqual(prc.find_registry(nested),
                             (root / ".local" / "repos.json", "current"))

    def test_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(prc.find_registry(Path(d)), (None, None))


class TestLoadOrInit(unittest.TestCase):
    def test_init_from_git_remote(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with mock.patch.object(prc, "git_remote_url",
                                   return_value="git@github.com:ericfitz/tmi.git"):
                config, path = prc.load_or_init_config(root)
            self.assertEqual(config, {"tmi": {"github": {"owner": "ericfitz", "repo": "tmi"}}})
            self.assertEqual(path, root / ".local" / "repos.json")

    def test_migrates_legacy_root_to_canonical_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-projects.json").write_text(json.dumps(
                {"projects": [{"name": "tmi", "github": {
                    "owner": "e", "repo": "tmi",
                    "issues_project": {"id": "PVT_x"}}}]}))
            config, path = prc.load_or_init_config(root)
            self.assertEqual(path, root / ".local" / "repos.json")
            self.assertEqual(config, {"tmi": {"github": {"owner": "e", "repo": "tmi"}}})

    def test_migrates_legacy_local_to_canonical_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text(json.dumps(
                {"projects": [{"name": "tmi", "github": {"repo": "tmi"}}]}))
            config, path = prc.load_or_init_config(root)
            self.assertEqual(path, root / ".local" / "repos.json")
            self.assertEqual(config, {"tmi": {"github": {"repo": "tmi"}}})


class TestMigrateCacheFile(unittest.TestCase):
    def test_renames_legacy_cache(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / ".local"
            local.mkdir()
            (local / "project-cache.json").write_text('{"tmi": {"cached_at": "t"}}')
            new = prc.migrate_cache_file(local)
            self.assertEqual(new, local / "gh-projects.json")
            self.assertEqual(json.loads(new.read_text()), {"tmi": {"cached_at": "t"}})

    def test_no_op_when_new_exists(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / ".local"
            local.mkdir()
            (local / "project-cache.json").write_text('{"old": 1}')
            (local / "gh-projects.json").write_text('{"new": 1}')
            prc.migrate_cache_file(local)
            self.assertEqual(json.loads((local / "gh-projects.json").read_text()), {"new": 1})

    def test_no_legacy_is_safe(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / ".local"
            local.mkdir()
            self.assertEqual(prc.migrate_cache_file(local), local / "gh-projects.json")
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: FAIL — `find_registry`, `load_or_init_config`, `migrate_cache_file` are undefined.

- [ ] **Step 3: Replace `find_config` with `find_registry`**

In `~/Scripts/provision-repo-config.py`, replace `find_config` (currently ~lines 206–216) with:

```python
def find_registry(start_dir):
    """Walk up from start_dir. Return (Path, kind).

    kind ∈ {"current", "legacy_local", "legacy_root"}:
      current      → <dir>/.local/repos.json
      legacy_local → <dir>/.local/projects.json
      legacy_root  → <dir>/.local-projects.json
    Returns (None, None) if nothing is found.
    """
    d = Path(start_dir).absolute()
    for parent in [d, *d.parents]:
        current = parent / LOCAL_DIR / REPOS_FILENAME
        if current.exists():
            return (current, "current")
        legacy_local = parent / LOCAL_DIR / LEGACY_LOCAL_CONFIG
        if legacy_local.exists():
            return (legacy_local, "legacy_local")
        legacy_root = parent / LEGACY_ROOT_CONFIG
        if legacy_root.exists():
            return (legacy_root, "legacy_root")
    return (None, None)
```

- [ ] **Step 4: Replace `_load_or_init_config` and add `migrate_cache_file`**

Replace `_load_or_init_config` (currently ~lines 363–385) with:

```python
def load_or_init_config(start_dir):
    """Return (config_dict, repos_path). Config is a name-keyed map.

    Migrates any legacy shape into <repo-root>/.local/repos.json. If nothing
    exists, initializes a single entry named after the repo (git remote else dir).
    """
    start_dir = Path(start_dir).absolute()
    path, kind = find_registry(start_dir)
    if path is None:
        owner, repo = parse_git_remote(git_remote_url())
        name = repo or start_dir.name
        entry = {"github": {}}
        if owner and repo:
            entry["github"] = {"owner": owner, "repo": repo}
        return {name: entry}, start_dir / LOCAL_DIR / REPOS_FILENAME
    config = normalize_registry(json.loads(path.read_text()))
    if kind == "current":
        return config, path
    root = path.parent if kind == "legacy_root" else path.parent.parent
    return config, root / LOCAL_DIR / REPOS_FILENAME


def migrate_cache_file(local_dir):
    """Rename a legacy project-cache.json to gh-projects.json (once). Idempotent.

    Returns the canonical cache Path (whether or not a migration happened).
    """
    local_dir = Path(local_dir)
    new = local_dir / CACHE_FILENAME
    old = local_dir / LEGACY_CACHE_FILENAME
    if old.exists() and not new.exists():
        new.parent.mkdir(parents=True, exist_ok=True)
        new.write_text(old.read_text())
    return new
```

- [ ] **Step 5: Run to verify the new tests pass**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: `TestFindRegistry`, `TestLoadOrInit`, `TestMigrateCacheFile` PASS. (`main`/`process_entry` still reference old names — fixed in Task 4; no test imports them yet.)

---

### Task 4: Interactive selection, local-field prompting, `process_entry`, `main` (TDD)

**Files:**
- Modify: `~/Scripts/provision-repo-config.py`
- Test: `~/Scripts/test_provision_repo_config.py`

**Interfaces:**
- Consumes: `load_or_init_config`, `migrate_cache_file`, `normalize_registry`, `set_project_title` (Tasks 2–3); `discover_linked_projects`, `enumerate_project`, `select_project`, `update_cache`, `ensure_gitignore_file`, `write_json` (ported).
- Produces: `ensure_local_fields(entry, repo_root, interactive) -> dict`; `prompt_project_choice(name, candidates) -> int|None`; `process_entry(name, entry, selection, now_iso, config, config_path, cache_path, gitignore_path, interactive=False) -> dict`; `main(argv=None) -> int` (iterates `config.items()`, runs cache migration, drives interactive selection).

- [ ] **Step 1: Write failing tests for local fields, process_entry, and main**

Add to `~/Scripts/test_provision_repo_config.py`:

```python
class TestEnsureLocalFields(unittest.TestCase):
    def test_defaults_path_non_interactive(self):
        entry = {"github": {}}
        prc.ensure_local_fields(entry, Path("/repo/root"), interactive=False)
        self.assertEqual(entry["path"], "/repo/root")
        self.assertNotIn("wiki_path", entry["github"])

    def test_preserves_existing(self):
        entry = {"path": "/keep", "github": {"wiki_path": "/w"}}
        prc.ensure_local_fields(entry, Path("/other"), interactive=False)
        self.assertEqual(entry["path"], "/keep")
        self.assertEqual(entry["github"]["wiki_path"], "/w")

    def test_prompts_when_interactive(self):
        entry = {"github": {}}
        with mock.patch("builtins.input", side_effect=["/typed", "/wiki"]):
            prc.ensure_local_fields(entry, Path("/def"), interactive=True)
        self.assertEqual(entry["path"], "/typed")
        self.assertEqual(entry["github"]["wiki_path"], "/wiki")

    def test_blank_accepts_default_and_skips_wiki(self):
        entry = {"github": {}}
        with mock.patch("builtins.input", side_effect=["", ""]):
            prc.ensure_local_fields(entry, Path("/def"), interactive=True)
        self.assertEqual(entry["path"], "/def")
        self.assertNotIn("wiki_path", entry["github"])


class TestProcessEntryKeyed(unittest.TestCase):
    def _paths(self, d):
        return (Path(d) / ".local" / "repos.json",
                Path(d) / ".local" / "gh-projects.json",
                Path(d) / ".gitignore")

    def test_resolved_writes_keyed_files(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p, cache_p, gi_p = self._paths(d)
            config = {"tmi": {"github": {"owner": "e", "repo": "tmi"}}}
            linked = [{"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "e"}]
            with mock.patch.object(prc, "discover_linked_projects", return_value=linked), \
                 mock.patch.object(prc, "enumerate_project",
                                   return_value={"cached_at": "t", "project": linked[0]}):
                res = prc.process_entry("tmi", config["tmi"], {}, "t", config,
                                        cfg_p, cache_p, gi_p)
            self.assertEqual(res, {"name": "tmi", "status": "resolved", "title": "Roadmap"})
            written = json.loads(cfg_p.read_text())
            self.assertEqual(written["tmi"]["github"]["project"], "Roadmap")
            self.assertEqual(written["tmi"]["path"], str(Path(d)))  # defaulted
            self.assertIn("tmi", json.loads(cache_p.read_text()))
            self.assertIn(".local/", gi_p.read_text())

    def test_none_marks_empty_no_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p, cache_p, gi_p = self._paths(d)
            config = {"tmi": {"github": {"owner": "e", "repo": "tmi"}}}
            with mock.patch.object(prc, "discover_linked_projects", return_value=[]):
                res = prc.process_entry("tmi", config["tmi"], {}, "t", config,
                                        cfg_p, cache_p, gi_p)
            self.assertEqual(res["status"], "none")
            self.assertEqual(json.loads(cfg_p.read_text())["tmi"]["github"]["project"], "")
            self.assertFalse(cache_p.exists())

    def test_needs_selection_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            cfg_p, cache_p, gi_p = self._paths(d)
            config = {"tmi": {"github": {"owner": "e", "repo": "tmi"}}}
            linked = [{"number": 2, "id": "a", "title": "R", "owner": "e"},
                      {"number": 5, "id": "b", "title": "S", "owner": "e"}]
            with mock.patch.object(prc, "discover_linked_projects", return_value=linked):
                res = prc.process_entry("tmi", config["tmi"], {}, "t", config,
                                        cfg_p, cache_p, gi_p)
            self.assertEqual(res["status"], "needs_selection")
            self.assertEqual(len(res["candidates"]), 2)
            self.assertFalse(cfg_p.exists())


class TestMainKeyed(unittest.TestCase):
    def test_resolves_named_entry_and_migrates_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text(json.dumps(
                {"projects": [{"name": "tmi", "github": {"owner": "e", "repo": "tmi"}}]}))
            (root / ".local" / "project-cache.json").write_text('{"old": {"cached_at": "x"}}')
            linked = [{"number": 2, "id": "a", "title": "Roadmap", "owner": "e"}]
            buf = io.StringIO()
            with mock.patch.object(prc, "discover_linked_projects", return_value=linked), \
                 mock.patch.object(prc, "enumerate_project",
                                   return_value={"cached_at": "t", "project": linked[0]}), \
                 contextlib.redirect_stdout(buf):
                rc = prc.main(["update", "--name", "tmi", "--dir", str(root)])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(buf.getvalue())["results"][0]["status"], "resolved")
            self.assertTrue((root / ".local" / "repos.json").exists())
            self.assertTrue((root / ".local" / "gh-projects.json").exists())  # migrated
            self.assertIn(".local/", (root / ".gitignore").read_text())

    def test_reports_gh_error(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "repos.json").write_text(json.dumps(
                {"tmi": {"github": {"owner": "e", "repo": "tmi"}}}))
            buf = io.StringIO()
            with mock.patch.object(prc, "discover_linked_projects",
                                   side_effect=prc.GhError("boom")), \
                 contextlib.redirect_stdout(buf):
                rc = prc.main(["update", "--name", "tmi", "--dir", str(root)])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["results"][0]["status"], "error")
            self.assertIn("boom", out["results"][0]["message"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: FAIL — `ensure_local_fields`/`prompt_project_choice` undefined and `process_entry`/`main` still use the list shape and old signatures.

- [ ] **Step 3: Add `ensure_local_fields` and `prompt_project_choice`; rewrite `process_entry`**

In `~/Scripts/provision-repo-config.py`, replace the whole `process_entry` function (currently ~lines 323–360) with:

```python
def ensure_local_fields(entry, repo_root, interactive):
    """Ensure a local `path`; optionally prompt for `github.wiki_path`.

    Preserves existing values. Non-interactive: path defaults to repo_root,
    wiki_path left unset. Interactive: blank input accepts the default / skips.
    """
    if not entry.get("path"):
        default = str(repo_root)
        if interactive:
            resp = input(f"Local path for this repo [{default}]: ").strip()
            entry["path"] = resp or default
        else:
            entry["path"] = default
    gh = entry.setdefault("github", {})
    if interactive and not gh.get("wiki_path"):
        resp = input("Wiki clone path (blank to skip): ").strip()
        if resp:
            gh["wiki_path"] = resp
    return entry


def prompt_project_choice(name, candidates):
    """Prompt the user to pick among linked projects. Returns a number or None."""
    print(f"\nRepo '{name}' links to multiple GitHub Projects:", file=sys.stderr)
    for c in candidates:
        print(f"  [{c['number']}] {c['title']}", file=sys.stderr)
    resp = input("Enter project number (blank to skip): ").strip()
    if not resp:
        return None
    try:
        return int(resp)
    except ValueError:
        return None


def process_entry(name, entry, selection, now_iso, config,
                  config_path, cache_path, gitignore_path, interactive=False):
    """Resolve one entry's project and update cache/registry. Returns a result dict."""
    gh = entry.get("github", {})
    owner, repo = gh.get("owner"), gh.get("repo")
    if not owner or not repo:
        o2, r2 = parse_git_remote(git_remote_url())
        owner = owner or o2
        repo = repo or r2
    if not owner or not repo:
        return {"name": name, "status": "error",
                "message": "no owner/repo in config and none derivable from git remote"}

    repo_root = config_path.parent.parent
    ensure_local_fields(entry, repo_root, interactive)
    config[name] = entry

    linked = discover_linked_projects(owner, repo)
    status, payload = select_project(
        linked,
        named_title=gh.get("project"),
        selected_title=selection.get("title"),
        selected_number=selection.get("number"),
    )

    if status == "needs_selection":
        return {"name": name, "status": "needs_selection",
                "candidates": [{"number": p["number"], "title": p["title"]}
                               for p in payload]}
    if status == "none":
        set_project_title(config, name, "")
        write_json(config_path, config)
        ensure_gitignore_file(gitignore_path)
        return {"name": name, "status": "none"}

    project = payload
    cache_entry = enumerate_project(owner, repo, project, now_iso)
    update_cache(cache_path, name, cache_entry)
    set_project_title(config, name, project["title"])
    write_json(config_path, config)
    ensure_gitignore_file(gitignore_path)
    return {"name": name, "status": "resolved", "title": project["title"]}
```

- [ ] **Step 4: Rewrite `main` for the keyed map, cache migration, and interactive selection**

Replace the whole `main` function (currently ~lines 388–427) with:

```python
def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Provision a repo's .local/ registry and GitHub Project cache.")
    parser.add_argument("command", choices=["update"])
    parser.add_argument("--name", help="Only process the entry with this name.")
    parser.add_argument("--dir", default=".", help="Directory to resolve config from.")
    parser.add_argument("--select-title", help="Force-select a project by title.")
    parser.add_argument("--select-number", type=int, help="Force-select a project by number.")
    args = parser.parse_args(argv)

    config, config_path = load_or_init_config(args.dir)
    local_dir = config_path.parent            # <repo-root>/.local
    migrate_cache_file(local_dir)
    cache_path = local_dir / CACHE_FILENAME
    gitignore_path = local_dir.parent / ".gitignore"
    now_iso = datetime.now(timezone.utc).isoformat()

    selection = {}
    if args.select_title:
        selection["title"] = args.select_title
    if args.select_number is not None:
        selection["number"] = args.select_number

    interactive = sys.stdin.isatty() and not selection

    names = list(config.keys())
    if args.name:
        if args.name not in config:
            print(json.dumps({"results": [
                {"name": args.name, "status": "error", "message": "entry not found"}]}))
            return 1
        names = [args.name]

    results = []
    for name in names:
        try:
            res = process_entry(name, config[name], selection, now_iso, config,
                                config_path, cache_path, gitignore_path,
                                interactive=interactive)
            if res.get("status") == "needs_selection" and interactive:
                choice = prompt_project_choice(name, res["candidates"])
                if choice is not None:
                    res = process_entry(name, config[name], {"number": choice}, now_iso,
                                        config, config_path, cache_path, gitignore_path,
                                        interactive=interactive)
            results.append(res)
        except GhError as exc:
            results.append({"name": name, "status": "error", "message": str(exc)})
    print(json.dumps({"results": results}, indent=2))
    return 0
```

- [ ] **Step 5: Run the full script suite — expect green**

Run: `python3 ~/Scripts/test_provision_repo_config.py -v`
Expected: ALL tests PASS (Tasks 1–4).

- [ ] **Step 6: Smoke-check the CLI parses and runs against a temp dir**

```bash
python3 ~/Scripts/provision-repo-config.py --help
mkdir -p /tmp/prc-smoke && git -C /tmp/prc-smoke init -q 2>/dev/null; \
  python3 ~/Scripts/provision-repo-config.py update --dir /tmp/prc-smoke < /dev/null; \
  rm -rf /tmp/prc-smoke
```
Expected: `--help` prints usage; the update run prints a JSON `{"results": [...]}` (status `error` for no remote, or `none`) without a traceback. (No commit — `~/Scripts` is not a git repo.)

---

### Task 5: Rewrite `create-issue` to consume the keyed files (read-only, instruct-and-stop)

**Files:**
- Modify: `github/skills/create-issue/SKILL.md`

**Interfaces:**
- Consumes: `.local/repos.json` (keyed), `.local/gh-projects.json` (keyed), `~/Scripts/provision-repo-config.py`.

- [ ] **Step 1: Update the frontmatter description**

Replace line 3 (`description: ...project-cache.json...`) with:

```
description: Use when filing a GitHub issue (bug, feature, task, chore, etc.) against a repo, optionally adding it to a GitHub Project (v2), setting milestone from the current branch, and marking initial status. Reads all project/field/milestone IDs from the local cache (.local/gh-projects.json), provisioned by ~/Scripts/provision-repo-config.py; infers the issue type from context unless the user specifies one.
```

- [ ] **Step 2: Update the intro paragraph**

Replace lines 10–13 (`Create a detailed... itself.`) with:

```markdown
Create a detailed, unambiguous GitHub issue, optionally adding it to a GitHub Project (v2) and
setting status. All project metadata (ids, fields, options, milestones, labels, issue types) is
read from the local cache `.local/gh-projects.json`, provisioned out-of-band by
`~/Scripts/provision-repo-config.py`. This skill never enumerates or refreshes project metadata.
```

- [ ] **Step 3: Update the Inputs `target` bullet**

Replace line 17 with:

```markdown
- **target** (argument): the project name (a key in `.local/repos.json`) whose repo receives the
  issue. If omitted, ask the user (or default to the sole entry).
```

- [ ] **Step 4: Rewrite the "Configuration & cache" section**

Replace lines 24–32 (the section body from `- \`.local/projects.json\`...` through `` refers to this plugin's install root.``) with:

```markdown
- `.local/repos.json` (walk up from `pwd`) is a JSON object **keyed by name**:
  `{ "<name>": { "path": "...", "github": { "owner", "repo", "project", "wiki_path" } } }`.
  `github.project` is a Project **title**; `""` means "no associated project — file a plain
  issue"; absent/null means "not yet resolved".
- `.local/gh-projects.json` (keyed by `<name>`) holds the resolved
  ids/fields/milestones/labels/issue types.

Both files are provisioned by `~/Scripts/provision-repo-config.py`, run once per repo. This skill
reads them and never writes or refreshes them.
```

- [ ] **Step 5: Rewrite Process step 1 (Resolve the project & cache)**

Replace lines 36–52 (`### 1. Resolve...(plain issue).`) with:

```markdown
### 1. Resolve the project & cache

1. Read the `<target>` entry from `.local/repos.json` (`jq '.["<target>"]'`). If the file or the
   entry is missing, tell the user to run `~/Scripts/provision-repo-config.py` in this repo, then
   **stop**.
2. Branch on `github.project`:
   - **`""`** → create a plain repo issue (skip project add/status).
   - **non-empty title** → load `.local/gh-projects.json` and look up the `<target>` key. If the
     cache file or that key is **missing**, tell the user to run
     `~/Scripts/provision-repo-config.py` in this repo, then **stop**.
   - **absent / null** (unresolved) → the project has not been provisioned. Tell the user to run
     `~/Scripts/provision-repo-config.py` in this repo, then **stop**.

After this step you either have a cache entry for `<target>`, or `github.project == ""` (plain
issue).
```

- [ ] **Step 6: Update the labels/milestone/status degrade-gracefully wording**

Replace line 67–68 (`- Only apply labels ... note the omission).`) with:

```markdown
- Only apply labels that exist in the cache's `labels` list. If a desired label is missing, omit it
  and note the omission (the cache refreshes only by re-running the provisioning script).
```

Replace lines 78–80 (`Look for a cache milestone ... create without a milestone.`) with:

```markdown
Look for a cache milestone whose `title` exactly equals `$BRANCH`. If found, use it. If `$BRANCH`
is not `main` and no milestone matches, create without a milestone (the cache may be stale; re-run
the provisioning script to refresh).
```

Replace lines 162–164 (`If a needed value (status option, etc.) is absent ... never loop.`) with:

```markdown
If a needed value (status option, etc.) is absent from the cache, proceed without it and note the
omission — never loop. Re-run the provisioning script to refresh the cache.
```

- [ ] **Step 7: Update the Error Handling table rows**

Replace line 181 (`| Target not in \`.local/projects.json\` ...`) with:

```markdown
| Target not in `.local/repos.json` | Error with the list of known names. |
```

Replace line 183 (`| Cache missing / value missing | Run update-project-cache once; ...|`) with:

```markdown
| Cache file/entry missing | Tell the user to run `~/Scripts/provision-repo-config.py`, then stop. |
| Individual value missing (label/status option) | Proceed without it and note the omission. |
```

- [ ] **Step 8: Update Implementation Note 1**

Replace lines 189–192 (note 1, `**Cache is the source of ids.** ... never loops.`) with:

```markdown
1. **Cache is the source of ids.** This skill never enumerates or refreshes project metadata;
   provisioning is done out-of-band by `~/Scripts/provision-repo-config.py`. When a required cache
   entry is missing, the skill stops and asks the user to run it; individual missing values are
   skipped with a note.
```

- [ ] **Step 9: Verify no stale references remain and marketplace verifier still passes**

```bash
rg -n 'update-project-cache|update_project_cache|project-cache\.json|\.local/projects\.json|CLAUDE_PLUGIN_ROOT' github/skills/create-issue/SKILL.md
bash scripts/verify-marketplace.sh
```
Expected: the `rg` prints **nothing**; `verify-marketplace.sh` ends with `All structural checks passed`.

- [ ] **Step 10: Commit**

```bash
git add github/skills/create-issue/SKILL.md
git commit -m "refactor(create-issue): read keyed .local/repos.json + gh-projects.json; drop in-skill cache refresh"
```

---

### Task 6: Remove the `update-project-cache` skill, script, test, and references

**Files:**
- Delete: `github/skills/update-project-cache/SKILL.md`, `github/scripts/update_project_cache.py`, `tests/test_update_project_cache.py`
- Modify: `github/.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`, `scripts/verify-marketplace.sh`

- [ ] **Step 1: Delete the skill, script, and test**

```bash
git rm github/skills/update-project-cache/SKILL.md \
       github/scripts/update_project_cache.py \
       tests/test_update_project_cache.py
rmdir github/skills/update-project-cache 2>/dev/null || true
```

- [ ] **Step 2: Update `github/.claude-plugin/plugin.json` description**

Replace the `description` value (line 4) with:

```
  "description": "GitHub workflow toolkit: pick the next issue to work on from a milestone/backlog (backlog) and file detailed issues into a repo/Project using a locally-provisioned metadata cache (create-issue). Use for issue triage and issue filing.",
```

- [ ] **Step 3: Update the github entry in `.claude-plugin/marketplace.json`**

Replace the `description` on the `"name": "github"` plugin object (line 9) with the same text:

```
    { "name": "github", "description": "GitHub workflow toolkit: pick the next issue to work on from a milestone/backlog (backlog) and file detailed issues into a repo/Project using a locally-provisioned metadata cache (create-issue). Use for issue triage and issue filing.", "source": "./github", "category": "development" },
```

- [ ] **Step 4: Update the README github section**

Replace lines 21–23 (`\`backlog\` ... using that cache).`) with:

```markdown
`backlog` (pick the next issue to work on) · `create-issue` (file a detailed issue into a
repo/Project using a locally-provisioned metadata cache).
```

- [ ] **Step 5: Update `scripts/verify-marketplace.sh`**

Replace line 44:

```
  "github:development:backlog,update-project-cache,create-issue"
```

with:

```
  "github:development:backlog,create-issue"
```

Delete the line inside the `SCRIPTS` array (currently line 108):

```
  "github/scripts/update_project_cache.py"
```

- [ ] **Step 6: Run the marketplace verifier — expect pass**

Run: `bash scripts/verify-marketplace.sh`
Expected: ends with `All structural checks passed. Safe to run...`. (It confirms the github plugin now declares exactly `backlog,create-issue`, and no longer expects `update_project_cache.py`.)

- [ ] **Step 7: Run the remaining repo test suite — expect pass**

Run: `python3 -m unittest discover -s tests -p 'test_*.py'`
Expected: ends with `OK` (the dedupe/sem suites; `test_update_project_cache.py` is gone).

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "refactor(github): remove update-project-cache skill; provisioning moves to ~/Scripts"
```

---

### Task 7: Point `wiki/verify-doc` at `.local/repos.json`

**Files:**
- Modify: `wiki/skills/verify-doc/SKILL.md`

- [ ] **Step 1: Update the frontmatter description**

Replace `Reads target repo and wiki path from .local-projects.json.` (end of line 3) with:

```
Reads target repo and wiki path from .local/repos.json.
```

- [ ] **Step 2: Update the Inputs `target` bullet**

Replace line 14 with:

```markdown
- **target** (argument 1): Project name (a key in `.local/repos.json`) whose codebase the doc describes and whose wiki will receive content.
```

- [ ] **Step 3: Rewrite the Configuration section schema**

Replace lines 21–35 (`Reads from \`.local-projects.json\`... the closing ``` ```) with:

```markdown
Reads from `.local/repos.json` (walked up from `pwd`), a JSON object keyed by name:

```jsonc
{
  "<target>": {
    "path": "<absolute local path to repo>",
    "github": {
      "owner": "...",
      "repo": "...",
      "wiki_path": "<absolute local path to wiki clone>"
    }
  }
}
```
```

- [ ] **Step 4: Update the Phase 4 wiki-path reference**

Replace line 103 (`\`WIKI_PATH\` comes from \`.local-projects.json\` (\`github.wiki_path\`).`) with:

```markdown
`WIKI_PATH` comes from `.local/repos.json` (`<target>.github.wiki_path`).
```

- [ ] **Step 5: Verify no stale reference remains**

Run: `rg -n 'local-projects' wiki/skills/verify-doc/SKILL.md`
Expected: prints **nothing**.

- [ ] **Step 6: Commit**

```bash
git add wiki/skills/verify-doc/SKILL.md
git commit -m "refactor(verify-doc): read keyed .local/repos.json"
```

---

### Task 8: Point `ui/vrt` at `.local/repos.json`

**Files:**
- Modify: `ui/skills/vrt/SKILL.md`

- [ ] **Step 1: Rewrite the Configuration intro + schema**

Replace lines 12–24 (`Reads \`.local-projects.json\`... to a project's \`path\` value.`) with:

```markdown
Reads `.local/repos.json` (walked up from `pwd`) to look up the GitHub owner/repo for the current project so that `gh issue view` can fetch task context. If `.local/repos.json` is missing or the current project isn't found, the skill falls back to whatever `gh` is configured to use.

```jsonc
{
  "<name>": {
    "path": "<absolute repo path matching pwd>",
    "github": {"owner": "...", "repo": "..."}
  }
}
```

The skill identifies the current project by matching `pwd` (or its parent) to an entry's `path` value; the matching entry's key is `<name>`.
```

- [ ] **Step 2: Update the `gh issue view` config lookup**

Replace lines 53–54:

```
   OWNER=$(jq -r ... .local-projects.json)   # from config
   REPO=$(jq -r ...)
```

with:

```
   OWNER=$(jq -r --arg n "$NAME" '.[$n].github.owner // empty' .local/repos.json)  # $NAME = matched key
   REPO=$(jq -r --arg n "$NAME" '.[$n].github.repo // empty' .local/repos.json)
```

- [ ] **Step 3: Verify no stale reference remains**

Run: `rg -n 'local-projects' ui/skills/vrt/SKILL.md`
Expected: prints **nothing**.

- [ ] **Step 4: Commit**

```bash
git add ui/skills/vrt/SKILL.md
git commit -m "refactor(vrt): read keyed .local/repos.json"
```

---

### Task 9: Document the convention (global CLAUDE.md + memory)

**Files:**
- Modify: `~/.claude/CLAUDE.md`
- Create: `/Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/local-config-conventions.md`
- Modify/Create: `/Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/MEMORY.md`

- [ ] **Step 1: Add a `.local/` convention section to `~/.claude/CLAUDE.md`**

Append this section to `~/.claude/CLAUDE.md`:

```markdown
## Local repo config convention (`.local/`)

Machine-local, git-ignored per-repo config lives under `.local/` (walk up from `pwd`):

- `.local/repos.json` — registry of related repos, a JSON object **keyed by name**:
  `{ "<name>": { "path": "<abs>", "github": { "owner", "repo", "project", "wiki_path" } } }`.
  This is the ONLY source of a repo's local path. Do **not** use `*_REPO` environment
  variables (e.g. `TMI_REPO`) for repo locations.
- `.local/gh-projects.json` — GitHub Project (v2) metadata cache, keyed by `<name>`.

Both are provisioned by `~/Scripts/provision-repo-config.py` (run once per repo), which is
the sole writer/migrator. Skills read these files and never write them.
```

- [ ] **Step 2: Create the memory file**

Create `/Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/local-config-conventions.md`:

```markdown
---
name: local-config-conventions
description: Canonical .local/ files for repo registry and GitHub project cache across skills
metadata:
  type: project
---

Skills in this repo standardize on two machine-local, git-ignored files (walk up from `pwd`):

- `.local/repos.json` — repo registry, JSON object **keyed by name**:
  `{ "<name>": { "path", "github": { "owner", "repo", "project", "wiki_path" } } }`.
- `.local/gh-projects.json` — GitHub Project (v2) metadata cache, keyed by `<name>`.

Sole writer/migrator: `~/Scripts/provision-repo-config.py` (uncommitted; run once per repo).
It migrates legacy shapes (root `.local-projects.json` array, `.local/projects.json` wrapped
list, `.local/project-cache.json`). Consuming skills (`create-issue`, `verify-doc`, `vrt`) are
read-only. No `*_REPO` env vars for repo locations. The `update-project-cache` skill was removed.
Spec: `docs/superpowers/specs/2026-07-04-local-config-conventions-design.md`.
```

- [ ] **Step 3: Add the MEMORY.md pointer**

Append to `/Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/MEMORY.md` (create the file if absent):

```markdown
- [Local config conventions](local-config-conventions.md) — .local/repos.json + .local/gh-projects.json, provisioned by ~/Scripts/provision-repo-config.py
```

- [ ] **Step 4: Verify the docs are consistent**

```bash
rg -n 'repos\.json|gh-projects\.json|provision-repo-config' ~/.claude/CLAUDE.md /Users/efitz/.claude/projects/-Users-efitz-Projects-skills/memory/local-config-conventions.md
```
Expected: matches in both files. (No commit — these are outside the repo.)

---

## Self-Review

**Spec coverage:**
- Canonical `.local/repos.json` keyed map → Tasks 2–4 (script), 5/7/8 (readers), 9 (docs). ✓
- Canonical `.local/gh-projects.json` → Tasks 1/3/4 (script), 5 (reader), 9 (docs). ✓
- `update-project-cache` skill removed + all references → Task 6. ✓
- External provisioning script, sole writer/migrator, interactive selection, path/wiki_path, legacy migration → Tasks 1–4. ✓
- `create-issue` read-only, instruct-and-stop → Task 5. ✓
- `verify-doc` / `vrt` keyed reads → Tasks 7–8. ✓
- No `*_REPO` env vars (already absent; enforced by the CLAUDE.md note) → Task 9. ✓
- Out-of-scope (dev sem-scope, loc i18n config, backlog) untouched — no tasks, correct. ✓

**Placeholder scan:** No TBD/TODO; every code and edit step carries exact content. ✓

**Type consistency:** `process_entry(name, entry, ...)` signature is defined in Task 4 and used only by `main` (Task 4). `normalize_registry`/`get_entry`/`set_project_title` (Task 2) are consumed by `load_or_init_config`/`process_entry` (Tasks 3–4) with matching keyed-map shapes. Constants (`REPOS_FILENAME`, `CACHE_FILENAME`, `LEGACY_*`) defined in Task 1, used in Tasks 3–4. ✓
