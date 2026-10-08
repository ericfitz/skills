# GitHub Project Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache GitHub Projects v2 metadata per-repo in a non-tracked file, factor all lookup logic into a new `update-project-cache` skill + bundled Python script, and rename/broaden `file-bug` into `create-issue` that reads only from the cache.

**Architecture:** A bundled, zero-dependency Python script (`github/scripts/update_project_cache.py`) owns git-context detection, project discovery (GraphQL), Projects v2 field/milestone/label/issue-type enumeration, and cache + config write-back. Two skills orchestrate it: `update-project-cache` (builds/refreshes the cache, handles the interactive "pick a project" step) and `create-issue` (reads the cache, escalates to the updater only when a project is unresolved or a needed value is missing).

**Tech Stack:** Python 3.10+ (stdlib only; PEP 723 inline metadata, matching `gh-issues.py`), `gh` CLI (incl. `gh api graphql`), stdlib `unittest` for tests, Markdown skills.

---

## Conventions for this plan

- **All commits** use two `-m` flags: the subject/body, then the trailer
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>` (repo convention).
- **Run tests from** `github/scripts/`: `cd github/scripts && python3 -m unittest discover -s tests -v`.
- The script filename uses an **underscore** (`update_project_cache.py`) so `tests/` can import it.
- Work happens on branch `feat/github-project-cache` (already created).

## File Structure

**Create:**
- `github/scripts/update_project_cache.py` — resolution + enumeration + cache/config write-back; CLI subcommand `update`.
- `github/scripts/tests/__init__.py` — empty, makes `tests` a package.
- `github/scripts/tests/test_update_project_cache.py` — unittest suite for the pure functions and the orchestration core.
- `github/skills/update-project-cache/SKILL.md` — orchestrates the script; handles multi-project selection.

**Modify / rename:**
- `github/skills/file-bug/` → `github/skills/create-issue/` (git mv), SKILL.md rewritten for cache reads + broadened issue types.
- `github/.claude-plugin/plugin.json` — description references `create-issue`/`update-project-cache`.
- `.claude-plugin/marketplace.json` — github plugin description references `create-issue`.
- `~/.claude/CLAUDE.md` — add the `.local/` convention section (global, outside repo).
- `~/.claude/projects/-Users-efitz/memory/` — add a memory file + `MEMORY.md` pointer for the `.local/` convention.

**Generated at runtime in each target repo (not in this repo):**
- `.local/projects.json` — association config.
- `.local/project-cache.json` — generated cache.

---

## Task 1: Scaffold the script module and test harness

**Files:**
- Create: `github/scripts/update_project_cache.py`
- Create: `github/scripts/tests/__init__.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Create `github/scripts/tests/test_update_project_cache.py`:

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import update_project_cache as upc


class TestScaffold(unittest.TestCase):
    def test_constants_exist(self):
        self.assertEqual(upc.CONFIG_FILENAME, "projects.json")
        self.assertEqual(upc.CACHE_FILENAME, "project-cache.json")
        self.assertEqual(upc.LOCAL_DIR, ".local")
        self.assertEqual(upc.LEGACY_CONFIG_FILENAME, ".local-projects.json")


if __name__ == "__main__":
    unittest.main()
```

Create `github/scripts/tests/__init__.py` as an empty file.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'update_project_cache'`.

- [ ] **Step 3: Write minimal implementation**

Create `github/scripts/update_project_cache.py`:

```python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# ///
"""Resolve a repo's GitHub Project (v2) and cache its metadata locally.

Builds/refreshes `.local/project-cache.json` (ids, fields, milestones, labels,
issue types) for projects named or discovered for a repo, and records the
resolved project title back into `.local/projects.json`.

Usage:
    update_project_cache.py update [--name NAME] [--dir DIR]
                                   [--select-title TITLE | --select-number N]
"""

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

LOCAL_DIR = ".local"
CONFIG_FILENAME = "projects.json"
CACHE_FILENAME = "project-cache.json"
LEGACY_CONFIG_FILENAME = ".local-projects.json"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/__init__.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): scaffold update_project_cache script + tests" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Parse git remote URL → (owner, repo)

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append to the test file:

```python
class TestParseGitRemote(unittest.TestCase):
    def test_https_with_git_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_https_no_suffix(self):
        self.assertEqual(upc.parse_git_remote("https://github.com/ericfitz/tmi"),
                         ("ericfitz", "tmi"))

    def test_ssh_form(self):
        self.assertEqual(upc.parse_git_remote("git@github.com:ericfitz/tmi.git"),
                         ("ericfitz", "tmi"))

    def test_empty(self):
        self.assertEqual(upc.parse_git_remote(""), (None, None))

    def test_garbage(self):
        self.assertEqual(upc.parse_git_remote("not-a-url"), (None, None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — `AttributeError: module 'update_project_cache' has no attribute 'parse_git_remote'`.

- [ ] **Step 3: Write minimal implementation**

Add to `update_project_cache.py`:

```python
def parse_git_remote(url):
    """Parse a git remote URL into (owner, repo); (None, None) if unparseable."""
    if not url:
        return (None, None)
    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    m = re.search(r"[:/]([^/:]+)/([^/:]+)$", url)
    if not m:
        return (None, None)
    return (m.group(1), m.group(2))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): parse git remote into owner/repo" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Parse linked-projects GraphQL response

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestParseLinkedProjects(unittest.TestCase):
    SAMPLE = {
        "data": {
            "repository": {
                "projectsV2": {
                    "nodes": [
                        {"number": 2, "id": "PVT_a", "title": "TMI Roadmap",
                         "owner": {"login": "ericfitz"}},
                        {"number": 5, "id": "PVT_b", "title": "Security",
                         "owner": {"login": "ericfitz"}},
                    ]
                }
            }
        }
    }

    def test_parses_nodes(self):
        out = upc.parse_linked_projects(self.SAMPLE)
        self.assertEqual(out, [
            {"number": 2, "id": "PVT_a", "title": "TMI Roadmap", "owner": "ericfitz"},
            {"number": 5, "id": "PVT_b", "title": "Security", "owner": "ericfitz"},
        ])

    def test_empty_repo(self):
        self.assertEqual(upc.parse_linked_projects({"data": {"repository": None}}), [])

    def test_missing_keys(self):
        self.assertEqual(upc.parse_linked_projects({}), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `parse_linked_projects`.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_linked_projects(data):
    """Extract a list of {number, id, title, owner} from a repository.projectsV2 query."""
    repo = (data or {}).get("data", {}).get("repository") or {}
    nodes = (repo.get("projectsV2") or {}).get("nodes") or []
    out = []
    for n in nodes:
        if not n:
            continue
        out.append({
            "number": n.get("number"),
            "id": n.get("id"),
            "title": n.get("title"),
            "owner": (n.get("owner") or {}).get("login"),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): parse linked projectsV2 graphql response" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Project selection decision logic

This is the core decision: explicit selection wins, then a named title (must still be linked), then auto-discovery (one → use, many → ask, none → none). A falsy `named_title` (including the `""` marker) is ignored, so `update-project-cache` always re-discovers.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestSelectProject(unittest.TestCase):
    ONE = [{"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "ericfitz"}]
    TWO = ONE + [{"number": 5, "id": "PVT_b", "title": "Security", "owner": "ericfitz"}]

    def test_explicit_number_match(self):
        status, payload = upc.select_project(self.TWO, selected_number=5)
        self.assertEqual(status, "resolved")
        self.assertEqual(payload["title"], "Security")

    def test_explicit_number_no_match(self):
        self.assertEqual(upc.select_project(self.TWO, selected_number=99), ("none", None))

    def test_explicit_title_case_insensitive(self):
        status, payload = upc.select_project(self.TWO, selected_title="security")
        self.assertEqual((status, payload["number"]), ("resolved", 5))

    def test_named_title_still_linked(self):
        status, payload = upc.select_project(self.TWO, named_title="Roadmap")
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_named_title_no_longer_linked_falls_through_to_one(self):
        status, payload = upc.select_project(self.ONE, named_title="Gone")
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_empty_marker_named_title_discovers(self):
        status, payload = upc.select_project(self.TWO, named_title="")
        self.assertEqual(status, "needs_selection")

    def test_discovery_single(self):
        status, payload = upc.select_project(self.ONE)
        self.assertEqual((status, payload["number"]), ("resolved", 2))

    def test_discovery_multiple(self):
        status, payload = upc.select_project(self.TWO)
        self.assertEqual(status, "needs_selection")
        self.assertEqual(len(payload), 2)

    def test_discovery_none(self):
        self.assertEqual(upc.select_project([]), ("none", None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `select_project`.

- [ ] **Step 3: Write minimal implementation**

```python
def _find_by_title(linked, title):
    for p in linked:
        if (p.get("title") or "").lower() == title.lower():
            return p
    return None


def select_project(linked, named_title=None, selected_title=None, selected_number=None):
    """Decide which project to use.

    Returns (status, payload):
      ("resolved", project_dict)
      ("needs_selection", [candidate_dicts])
      ("none", None)
    """
    if selected_number is not None:
        for p in linked:
            if p.get("number") == selected_number:
                return ("resolved", p)
        return ("none", None)
    if selected_title:
        p = _find_by_title(linked, selected_title)
        return ("resolved", p) if p else ("none", None)
    if named_title:  # "" marker is falsy -> skipped -> discovery
        p = _find_by_title(linked, named_title)
        if p:
            return ("resolved", p)
        # named project no longer linked: fall through to discovery
    if len(linked) == 1:
        return ("resolved", linked[0])
    if len(linked) > 1:
        return ("needs_selection", linked)
    return ("none", None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): project selection decision logic" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Parse `gh project field-list` JSON into the cache fields shape

Maps gh field type strings to short tokens (`single_select`, `iteration`, `field`), keeps fields keyed by name, and stores options as ordered `{name, id}` arrays. Iteration options come from `configuration.iterations`.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestParseFields(unittest.TestCase):
    SAMPLE = {
        "fields": [
            {"id": "PVTF_title", "name": "Title", "type": "ProjectV2Field"},
            {"id": "PVTSSF_s", "name": "Status", "type": "ProjectV2SingleSelectField",
             "options": [
                 {"id": "o1", "name": "Backlog"},
                 {"id": "o2", "name": "This milestone"},
                 {"id": "o3", "name": "Done"},
             ]},
            {"id": "PVTIF_sp", "name": "Sprint", "type": "ProjectV2IterationField",
             "configuration": {"iterations": [
                 {"id": "it1", "title": "Sprint 1"},
                 {"id": "it2", "title": "Sprint 2"},
             ]}},
        ],
        "totalCount": 3,
    }

    def test_field_keyed_by_name(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(set(fields), {"Title", "Status", "Sprint"})

    def test_generic_field(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Title"], {"id": "PVTF_title", "type": "field"})

    def test_single_select_options_ordered(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Status"]["type"], "single_select")
        self.assertEqual(fields["Status"]["options"], [
            {"name": "Backlog", "id": "o1"},
            {"name": "This milestone", "id": "o2"},
            {"name": "Done", "id": "o3"},
        ])

    def test_iteration_options_from_configuration(self):
        fields = upc.parse_fields(self.SAMPLE)
        self.assertEqual(fields["Sprint"]["type"], "iteration")
        self.assertEqual(fields["Sprint"]["options"], [
            {"name": "Sprint 1", "id": "it1"},
            {"name": "Sprint 2", "id": "it2"},
        ])

    def test_empty(self):
        self.assertEqual(upc.parse_fields({}), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `parse_fields`.

- [ ] **Step 3: Write minimal implementation**

```python
FIELD_TYPE_MAP = {
    "ProjectV2SingleSelectField": "single_select",
    "ProjectV2IterationField": "iteration",
    "ProjectV2Field": "field",
}


def parse_fields(data):
    """Convert `gh project field-list --format json` output to the cache fields map."""
    fields = {}
    for f in (data or {}).get("fields", []) or []:
        name = f.get("name")
        if not name:
            continue
        ftype = FIELD_TYPE_MAP.get(f.get("type"), "field")
        entry = {"id": f.get("id"), "type": ftype}
        if f.get("options"):
            entry["options"] = [{"name": o.get("name"), "id": o.get("id")}
                                for o in f["options"]]
        elif ftype == "iteration":
            iters = (f.get("configuration") or {}).get("iterations") or []
            if iters:
                entry["options"] = [{"name": it.get("title"), "id": it.get("id")}
                                    for it in iters]
        fields[name] = entry
    return fields
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): parse project field-list into cache fields" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Parse milestones, labels, and issue types

Three small, defensive parsers over `gh api` REST output.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestParseRepoMetadata(unittest.TestCase):
    def test_milestones(self):
        data = [
            {"title": "release/1.3.0", "number": 5, "node_id": "MI_a"},
            {"title": "release/1.4.0", "number": 6, "node_id": "MI_b"},
            {"number": 7, "node_id": "MI_c"},  # no title -> dropped
        ]
        self.assertEqual(upc.parse_milestones(data), [
            {"title": "release/1.3.0", "number": 5, "id": "MI_a"},
            {"title": "release/1.4.0", "number": 6, "id": "MI_b"},
        ])

    def test_milestones_empty(self):
        self.assertEqual(upc.parse_milestones([]), [])

    def test_labels(self):
        data = [{"name": "bug"}, {"name": "api"}, {"color": "fff"}]
        self.assertEqual(upc.parse_labels(data), ["bug", "api"])

    def test_issue_types_list_of_objects(self):
        self.assertEqual(upc.parse_issue_types([{"name": "Bug"}, {"name": "Feature"}]),
                         ["Bug", "Feature"])

    def test_issue_types_wrapped(self):
        self.assertEqual(upc.parse_issue_types({"issue_types": [{"name": "Task"}]}),
                         ["Task"])

    def test_issue_types_empty(self):
        self.assertEqual(upc.parse_issue_types(None), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `parse_milestones`.

- [ ] **Step 3: Write minimal implementation**

```python
def parse_milestones(data):
    """Map `gh api repos/{o}/{r}/milestones` output to ordered {title, number, id}."""
    return [{"title": m.get("title"), "number": m.get("number"), "id": m.get("node_id")}
            for m in (data or []) if m.get("title")]


def parse_labels(data):
    """Map `gh api repos/{o}/{r}/labels` output to a list of label names."""
    return [l.get("name") for l in (data or []) if l.get("name")]


def parse_issue_types(data):
    """Best-effort: accept a list of {name} or a {issue_types|data: [...]} wrapper."""
    if isinstance(data, dict):
        data = data.get("issue_types") or data.get("data") or []
    return [t.get("name") for t in (data or [])
            if isinstance(t, dict) and t.get("name")]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): parse milestones, labels, issue types" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Assemble a cache entry

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestBuildCacheEntry(unittest.TestCase):
    def test_assembles_full_entry(self):
        project = {"number": 2, "owner": "ericfitz", "id": "PVT_a", "title": "Roadmap"}
        entry = upc.build_cache_entry(
            project,
            fields={"Status": {"id": "PVTSSF_s", "type": "single_select", "options": []}},
            milestones=[{"title": "release/1.3.0", "number": 5, "id": "MI_a"}],
            labels=["bug"],
            issue_types=["Bug"],
            now_iso="2026-06-10T12:00:00+00:00",
        )
        self.assertEqual(entry["cached_at"], "2026-06-10T12:00:00+00:00")
        self.assertEqual(entry["project"], project)
        self.assertEqual(entry["labels"], ["bug"])
        self.assertEqual(entry["issue_types"], ["Bug"])
        self.assertIn("Status", entry["fields"])
        self.assertEqual(entry["milestones"][0]["number"], 5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `build_cache_entry`.

- [ ] **Step 3: Write minimal implementation**

```python
def build_cache_entry(project, fields, milestones, labels, issue_types, now_iso):
    """Assemble one project's cache entry."""
    return {
        "cached_at": now_iso,
        "project": {
            "number": project.get("number"),
            "owner": project.get("owner"),
            "id": project.get("id"),
            "title": project.get("title"),
        },
        "fields": fields,
        "milestones": milestones,
        "labels": labels,
        "issue_types": issue_types,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): assemble project cache entry" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Config helpers — entry lookup, set title, legacy migration

`migrate_entry` drops a legacy `issues_project` ID block (IDs now live in the cache) while keeping `owner`/`repo` and any `project` title. `get_entry`/`set_project_title` manage entries; `set_project_title` creates the entry if absent.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestConfigHelpers(unittest.TestCase):
    def test_get_entry_found(self):
        cfg = {"projects": [{"name": "tmi", "github": {}}]}
        self.assertEqual(upc.get_entry(cfg, "tmi")["name"], "tmi")

    def test_get_entry_missing(self):
        self.assertIsNone(upc.get_entry({"projects": []}, "nope"))

    def test_set_title_existing(self):
        cfg = {"projects": [{"name": "tmi", "github": {"owner": "ericfitz"}}]}
        upc.set_project_title(cfg, "tmi", "Roadmap")
        self.assertEqual(cfg["projects"][0]["github"]["project"], "Roadmap")
        self.assertEqual(cfg["projects"][0]["github"]["owner"], "ericfitz")

    def test_set_title_creates_entry(self):
        cfg = {}
        upc.set_project_title(cfg, "newrepo", "")
        self.assertEqual(cfg["projects"][0],
                         {"name": "newrepo", "github": {"project": ""}})

    def test_migrate_drops_legacy_ids_keeps_title(self):
        entry = {"name": "tmi", "github": {
            "owner": "ericfitz", "repo": "tmi", "project": "Roadmap",
            "issues_project": {"id": "PVT_x", "number": 2, "fields": {"status": {}}},
        }}
        out = upc.migrate_entry(entry)
        self.assertEqual(out["github"],
                         {"owner": "ericfitz", "repo": "tmi", "project": "Roadmap"})

    def test_migrate_legacy_without_title_leaves_project_unset(self):
        entry = {"name": "tmi", "github": {
            "owner": "ericfitz", "repo": "tmi",
            "issues_project": {"id": "PVT_x", "number": 2},
        }}
        out = upc.migrate_entry(entry)
        self.assertNotIn("project", out["github"])
        self.assertNotIn("issues_project", out["github"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `get_entry`.

- [ ] **Step 3: Write minimal implementation**

```python
def get_entry(config, name):
    for e in (config or {}).get("projects", []):
        if e.get("name") == name:
            return e
    return None


def set_project_title(config, name, title):
    """Set github.project for `name`, creating the entry if needed. Returns config."""
    e = get_entry(config, name)
    if e is None:
        e = {"name": name, "github": {}}
        config.setdefault("projects", []).append(e)
    e.setdefault("github", {})["project"] = title
    return config


def migrate_entry(entry):
    """Drop a legacy issues_project ID block; keep owner/repo/project title."""
    gh = dict(entry.get("github", {}))
    gh.pop("issues_project", None)
    out = dict(entry)
    out["github"] = gh
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): config entry helpers + legacy migration" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: File location + JSON IO + gitignore helpers

Locates config (new `.local/projects.json`, then legacy root `.local-projects.json`), computes the repo-relative paths for cache and gitignore, writes JSON atomically, and ensures `.local/` is gitignored (idempotent).

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import tempfile


class TestLocationAndIO(unittest.TestCase):
    def test_ensure_gitignore_adds_when_missing(self):
        self.assertEqual(upc.ensure_gitignore_text(""), ".local/\n")
        self.assertEqual(upc.ensure_gitignore_text("node_modules\n"),
                         "node_modules\n.local/\n")

    def test_ensure_gitignore_idempotent(self):
        self.assertEqual(upc.ensure_gitignore_text(".local/\n"), ".local/\n")
        self.assertEqual(upc.ensure_gitignore_text("foo\n.local\nbar\n"),
                         "foo\n.local\nbar\n")

    def test_ensure_gitignore_adds_trailing_newline(self):
        self.assertEqual(upc.ensure_gitignore_text("foo"), "foo\n.local/\n")

    def test_write_and_read_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "out.json"
            upc.write_json(p, {"a": 1})
            self.assertEqual(json.loads(p.read_text()), {"a": 1})

    def test_find_config_prefers_new_location(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text("{}")
            (root / ".local-projects.json").write_text("{}")
            path, legacy = upc.find_config(root)
            self.assertEqual(path, root / ".local" / "projects.json")
            self.assertFalse(legacy)

    def test_find_config_falls_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-projects.json").write_text("{}")
            path, legacy = upc.find_config(root)
            self.assertEqual(path, root / ".local-projects.json")
            self.assertTrue(legacy)

    def test_find_config_walks_up(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text("{}")
            nested = root / "a" / "b"
            nested.mkdir(parents=True)
            path, legacy = upc.find_config(nested)
            self.assertEqual(path, root / ".local" / "projects.json")

    def test_find_config_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(upc.find_config(Path(d)), (None, False))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `ensure_gitignore_text`.

- [ ] **Step 3: Write minimal implementation**

```python
def ensure_gitignore_text(text, entry=".local/"):
    """Return gitignore text with `entry` present (idempotent)."""
    target = entry.rstrip("/")
    for line in text.splitlines():
        if line.strip().rstrip("/") == target:
            return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + entry + "\n"


def write_json(path, data):
    """Write JSON atomically, creating parent dirs."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def find_config(start_dir):
    """Walk up from start_dir. Return (Path, is_legacy) or (None, False)."""
    d = Path(start_dir).resolve()
    for parent in [d, *d.parents]:
        new = parent / LOCAL_DIR / CONFIG_FILENAME
        if new.exists():
            return (new, False)
        legacy = parent / LEGACY_CONFIG_FILENAME
        if legacy.exists():
            return (legacy, True)
    return (None, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): config location + atomic json + gitignore helpers" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Cache merge helper

Updating one project's key must preserve other keys already in the cache file.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestUpdateCache(unittest.TestCase):
    def test_creates_and_preserves_other_keys(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / ".local" / "project-cache.json"
            upc.update_cache(cache_path, "tmi", {"cached_at": "t1"})
            upc.update_cache(cache_path, "other", {"cached_at": "t2"})
            data = json.loads(cache_path.read_text())
            self.assertEqual(set(data), {"tmi", "other"})
            self.assertEqual(data["tmi"]["cached_at"], "t1")

    def test_overwrites_same_key(self):
        with tempfile.TemporaryDirectory() as d:
            cache_path = Path(d) / "project-cache.json"
            upc.update_cache(cache_path, "tmi", {"cached_at": "t1"})
            upc.update_cache(cache_path, "tmi", {"cached_at": "t2"})
            data = json.loads(cache_path.read_text())
            self.assertEqual(data["tmi"]["cached_at"], "t2")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `update_cache`.

- [ ] **Step 3: Write minimal implementation**

```python
def update_cache(cache_path, name, entry):
    """Merge one project's entry into the cache file, preserving other keys."""
    cache_path = Path(cache_path)
    cache = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
    cache[name] = entry
    write_json(cache_path, cache)
    return cache
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): cache merge helper" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Subprocess wrappers + enumeration orchestration

`run_gh` / `run_gh_json` / `run_gh_graphql` wrap the `gh` CLI; `git_remote_url` reads the origin URL; `discover_linked_projects` and `enumerate_project` compose the parsers. Tests patch `run_gh_json` / `run_gh_graphql` so no network is required.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
from unittest import mock


class TestEnumeration(unittest.TestCase):
    def test_discover_linked_projects(self):
        sample = {"data": {"repository": {"projectsV2": {"nodes": [
            {"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": {"login": "ericfitz"}},
        ]}}}}
        with mock.patch.object(upc, "run_gh_graphql", return_value=sample):
            out = upc.discover_linked_projects("ericfitz", "tmi")
        self.assertEqual(out[0]["title"], "Roadmap")

    def test_enumerate_project_composes_parsers(self):
        project = {"number": 2, "owner": "ericfitz", "id": "PVT_a", "title": "Roadmap"}

        def fake_run_gh_json(args):
            if args[:2] == ["project", "field-list"]:
                return {"fields": [{"id": "PVTSSF_s", "name": "Status",
                                    "type": "ProjectV2SingleSelectField",
                                    "options": [{"id": "o1", "name": "Backlog"}]}]}
            if "milestones" in args[1]:
                return [{"title": "release/1.3.0", "number": 5, "node_id": "MI_a"}]
            if "/labels" in args[1]:
                return [{"name": "bug"}]
            if "issue-types" in args[1]:
                return [{"name": "Bug"}]
            raise AssertionError(f"unexpected args: {args}")

        with mock.patch.object(upc, "run_gh_json", side_effect=fake_run_gh_json):
            entry = upc.enumerate_project("ericfitz", "tmi", project, "2026-06-10T00:00:00+00:00")

        self.assertEqual(entry["project"]["title"], "Roadmap")
        self.assertIn("Status", entry["fields"])
        self.assertEqual(entry["milestones"][0]["number"], 5)
        self.assertEqual(entry["labels"], ["bug"])
        self.assertEqual(entry["issue_types"], ["Bug"])

    def test_enumerate_tolerates_issue_types_failure(self):
        project = {"number": 2, "owner": "ericfitz", "id": "PVT_a", "title": "Roadmap"}

        def fake_run_gh_json(args):
            if args[:2] == ["project", "field-list"]:
                return {"fields": []}
            if "milestones" in args[1]:
                return []
            if "/labels" in args[1]:
                return []
            if "issue-types" in args[1]:
                raise upc.GhError("404")
            raise AssertionError(f"unexpected args: {args}")

        with mock.patch.object(upc, "run_gh_json", side_effect=fake_run_gh_json):
            entry = upc.enumerate_project("ericfitz", "tmi", project, "t")
        self.assertEqual(entry["issue_types"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `run_gh_graphql` / `GhError`.

- [ ] **Step 3: Write minimal implementation**

```python
class GhError(RuntimeError):
    """Raised when a gh CLI call fails."""


PROJECTS_QUERY = """
query($owner:String!, $repo:String!) {
  repository(owner:$owner, name:$repo) {
    projectsV2(first:50) {
      nodes {
        number title id
        owner { ... on User { login } ... on Organization { login } }
      }
    }
  }
}
"""


def run_gh(args):
    """Run a gh command; return stdout. Raise GhError on failure."""
    try:
        result = subprocess.run(["gh"] + args, capture_output=True, text=True, check=True)
        return result.stdout
    except FileNotFoundError:
        print("Error: 'gh' CLI not found. Install it from https://cli.github.com/",
              file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as e:
        raise GhError(e.stderr.strip()) from e


def run_gh_json(args):
    """Run a gh command and parse stdout as JSON."""
    return json.loads(run_gh(args))


def run_gh_graphql(query, variables):
    """Run a GraphQL query via `gh api graphql` with -F field=value variables."""
    args = ["api", "graphql", "-f", f"query={query}"]
    for k, v in variables.items():
        args += ["-F", f"{k}={v}"]
    return run_gh_json(args)


def git_remote_url():
    """Return the origin remote URL, or '' if unavailable."""
    try:
        result = subprocess.run(["git", "remote", "get-url", "origin"],
                                capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""


def discover_linked_projects(owner, repo):
    """Return linked Projects v2 for a repo as a list of {number,id,title,owner}."""
    data = run_gh_graphql(PROJECTS_QUERY, {"owner": owner, "repo": repo})
    return parse_linked_projects(data)


def enumerate_project(owner, repo, project, now_iso):
    """Gather all metadata for the chosen project and assemble a cache entry."""
    field_data = run_gh_json([
        "project", "field-list", str(project["number"]),
        "--owner", project["owner"], "--format", "json",
    ])
    fields = parse_fields(field_data)

    milestones = parse_milestones(run_gh_json([
        "api", f"repos/{owner}/{repo}/milestones?state=all&per_page=100",
    ]))
    labels = parse_labels(run_gh_json([
        "api", f"repos/{owner}/{repo}/labels?per_page=100",
    ]))
    try:
        issue_types = parse_issue_types(run_gh_json([
            "api", f"repos/{owner}/{repo}/issue-types",
        ]))
    except GhError:
        issue_types = []  # issue types not enabled / endpoint unavailable

    return build_cache_entry(project, fields, milestones, labels, issue_types, now_iso)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): gh wrappers + project enumeration" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: `process_entry` orchestration core

The single testable function that ties resolution → write-back → enumeration → cache together for one entry. Returns a result dict (`resolved` / `needs_selection` / `none` / `error`). Tests patch `discover_linked_projects` and `enumerate_project`.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestProcessEntry(unittest.TestCase):
    def _paths(self, d):
        return {
            "cache_path": Path(d) / ".local" / "project-cache.json",
            "config_path": Path(d) / ".local" / "projects.json",
            "gitignore_path": Path(d) / ".gitignore",
        }

    def test_resolved_writes_cache_config_and_gitignore(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self._paths(d)
            config = {"projects": [{"name": "tmi",
                                    "github": {"owner": "ericfitz", "repo": "tmi"}}]}
            entry = config["projects"][0]
            linked = [{"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "ericfitz"}]
            with mock.patch.object(upc, "discover_linked_projects", return_value=linked), \
                 mock.patch.object(upc, "enumerate_project",
                                   return_value={"cached_at": "t", "project": linked[0]}):
                result = upc.process_entry(entry, {}, "t", config, paths["config_path"],
                                           paths["cache_path"], paths["gitignore_path"])
            self.assertEqual(result["status"], "resolved")
            self.assertEqual(result["title"], "Roadmap")
            self.assertEqual(json.loads(paths["config_path"].read_text())
                             ["projects"][0]["github"]["project"], "Roadmap")
            self.assertIn("tmi", json.loads(paths["cache_path"].read_text()))
            self.assertIn(".local/", paths["gitignore_path"].read_text())

    def test_none_writes_empty_marker_no_cache(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self._paths(d)
            config = {"projects": [{"name": "tmi",
                                    "github": {"owner": "ericfitz", "repo": "tmi"}}]}
            entry = config["projects"][0]
            with mock.patch.object(upc, "discover_linked_projects", return_value=[]):
                result = upc.process_entry(entry, {}, "t", config, paths["config_path"],
                                           paths["cache_path"], paths["gitignore_path"])
            self.assertEqual(result["status"], "none")
            self.assertEqual(json.loads(paths["config_path"].read_text())
                             ["projects"][0]["github"]["project"], "")
            self.assertFalse(paths["cache_path"].exists())

    def test_needs_selection_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self._paths(d)
            config = {"projects": [{"name": "tmi",
                                    "github": {"owner": "ericfitz", "repo": "tmi"}}]}
            entry = config["projects"][0]
            linked = [
                {"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "ericfitz"},
                {"number": 5, "id": "PVT_b", "title": "Security", "owner": "ericfitz"},
            ]
            with mock.patch.object(upc, "discover_linked_projects", return_value=linked):
                result = upc.process_entry(entry, {}, "t", config, paths["config_path"],
                                           paths["cache_path"], paths["gitignore_path"])
            self.assertEqual(result["status"], "needs_selection")
            self.assertEqual(len(result["candidates"]), 2)
            self.assertFalse(paths["config_path"].exists())
            self.assertFalse(paths["cache_path"].exists())

    def test_error_when_no_owner_repo(self):
        with tempfile.TemporaryDirectory() as d:
            paths = self._paths(d)
            config = {"projects": [{"name": "tmi", "github": {}}]}
            entry = config["projects"][0]
            with mock.patch.object(upc, "git_remote_url", return_value=""):
                result = upc.process_entry(entry, {}, "t", config, paths["config_path"],
                                           paths["cache_path"], paths["gitignore_path"])
            self.assertEqual(result["status"], "error")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — no attribute `process_entry`.

- [ ] **Step 3: Write minimal implementation**

```python
def ensure_gitignore_file(gitignore_path):
    """Ensure `.local/` is ignored in the given .gitignore file."""
    path = Path(gitignore_path)
    text = path.read_text() if path.exists() else ""
    new_text = ensure_gitignore_text(text)
    if new_text != text:
        path.write_text(new_text)


def process_entry(entry, selection, now_iso, config, config_path, cache_path, gitignore_path):
    """Resolve one entry's project and update cache/config. Returns a result dict."""
    name = entry.get("name")
    gh = entry.get("github", {})
    owner, repo = gh.get("owner"), gh.get("repo")
    if not owner or not repo:
        o2, r2 = parse_git_remote(git_remote_url())
        owner = owner or o2
        repo = repo or r2
    if not owner or not repo:
        return {"name": name, "status": "error",
                "message": "no owner/repo in config and none derivable from git remote"}

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
        return {"name": name, "status": "none"}

    project = payload
    cache_entry = enumerate_project(owner, repo, project, now_iso)
    update_cache(cache_path, name, cache_entry)
    set_project_title(config, name, project["title"])
    write_json(config_path, config)
    ensure_gitignore_file(gitignore_path)
    return {"name": name, "status": "resolved", "title": project["title"]}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): process_entry orchestration core" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: CLI `main()` — argparse, path resolution, migration, output contract

`main()` resolves the config location (creating `.local/projects.json` for the current repo if none exists, migrating a legacy root file if found), selects entries (all, or one via `--name`), runs `process_entry`, and prints a JSON result object to stdout. Output contract: `{"results": [ <result dict>, ... ]}`.

**Files:**
- Modify: `github/scripts/update_project_cache.py`
- Test: `github/scripts/tests/test_update_project_cache.py`

- [ ] **Step 1: Write the failing test**

Append:

```python
import io
import contextlib


class TestMain(unittest.TestCase):
    def test_main_resolves_single_named_entry(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local").mkdir()
            (root / ".local" / "projects.json").write_text(json.dumps(
                {"projects": [{"name": "tmi",
                               "github": {"owner": "ericfitz", "repo": "tmi"}}]}))
            linked = [{"number": 2, "id": "PVT_a", "title": "Roadmap", "owner": "ericfitz"}]
            buf = io.StringIO()
            with mock.patch.object(upc, "discover_linked_projects", return_value=linked), \
                 mock.patch.object(upc, "enumerate_project",
                                   return_value={"cached_at": "t", "project": linked[0]}), \
                 contextlib.redirect_stdout(buf):
                rc = upc.main(["update", "--name", "tmi", "--dir", str(root)])
            self.assertEqual(rc, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual(out["results"][0]["status"], "resolved")

    def test_main_migrates_legacy_root_file(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".local-projects.json").write_text(json.dumps(
                {"projects": [{"name": "tmi", "github": {
                    "owner": "ericfitz", "repo": "tmi",
                    "issues_project": {"id": "PVT_x", "number": 2}}}]}))
            with mock.patch.object(upc, "discover_linked_projects", return_value=[]):
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    rc = upc.main(["update", "--dir", str(root)])
            # New config created under .local/, legacy IDs dropped.
            self.assertTrue((root / ".local" / "projects.json").exists())
            migrated = json.loads((root / ".local" / "projects.json").read_text())
            self.assertNotIn("issues_project", migrated["projects"][0]["github"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: FAIL — `main()` takes no args / not callable with a list.

- [ ] **Step 3: Write minimal implementation**

Replace any placeholder `main` with:

```python
def _load_or_init_config(start_dir):
    """Return (config_dict, config_path). Migrate a legacy file if found.

    If no config exists, initialize one under <start_dir>/.local/projects.json with a
    single entry named after the repo (from git remote, else the directory name).
    """
    start_dir = Path(start_dir).resolve()
    path, is_legacy = find_config(start_dir)
    if path is None:
        owner, repo = parse_git_remote(git_remote_url())
        name = repo or start_dir.name
        config = {"projects": [{"name": name, "github": {}}]}
        if owner and repo:
            config["projects"][0]["github"] = {"owner": owner, "repo": repo}
        new_path = start_dir / LOCAL_DIR / CONFIG_FILENAME
        return config, new_path
    config = json.loads(path.read_text())
    config["projects"] = [migrate_entry(e) for e in config.get("projects", [])]
    if is_legacy:
        # Move into .local/projects.json beside the legacy file's directory.
        new_path = path.parent / LOCAL_DIR / CONFIG_FILENAME
        return config, new_path
    return config, path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Resolve a repo's GitHub Project and cache its metadata.")
    parser.add_argument("command", choices=["update"])
    parser.add_argument("--name", help="Only process the entry with this name.")
    parser.add_argument("--dir", default=".", help="Directory to resolve config from.")
    parser.add_argument("--select-title", help="Force-select a project by title.")
    parser.add_argument("--select-number", type=int, help="Force-select a project by number.")
    args = parser.parse_args(argv)

    config, config_path = _load_or_init_config(args.dir)
    cache_path = config_path.parent / CACHE_FILENAME
    gitignore_path = config_path.parent.parent / ".gitignore"
    now_iso = datetime.now(timezone.utc).isoformat()

    selection = {}
    if args.select_title:
        selection["title"] = args.select_title
    if args.select_number is not None:
        selection["number"] = args.select_number

    entries = config.get("projects", [])
    if args.name:
        entries = [e for e in entries if e.get("name") == args.name]
        if not entries:
            print(json.dumps({"results": [
                {"name": args.name, "status": "error", "message": "entry not found"}]}))
            return 1

    results = [process_entry(e, selection, now_iso, config, config_path,
                             cache_path, gitignore_path)
               for e in entries]
    print(json.dumps({"results": results}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: PASS (full suite green).

- [ ] **Step 5: Commit**

```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "feat(github): CLI main, path resolution, legacy migration" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Real-repo integration check (no automated test)

Verify the script against a real repo and reconcile any JSON-shape differences from the fixtures. Use a repo you know is linked to a Project (e.g. `tmi`).

- [ ] **Step 1: Confirm `gh` is authenticated**

Run: `gh auth status`
Expected: logged in. If not, run `gh auth login` and retry.

- [ ] **Step 2: Inspect real `gh` output shapes the script depends on**

Run (substitute a real linked project number/owner):
```bash
gh api graphql -f query='query($owner:String!,$repo:String!){repository(owner:$owner,name:$repo){projectsV2(first:50){nodes{number title id owner{... on User{login} ... on Organization{login}}}}}}' -F owner=ericfitz -F repo=tmi
gh project field-list <NUMBER> --owner ericfitz --format json
gh api "repos/ericfitz/tmi/milestones?state=all&per_page=100"
gh api "repos/ericfitz/tmi/labels?per_page=100"
gh api "repos/ericfitz/tmi/issue-types" || echo "(issue-types unavailable; expected for many repos)"
```
Expected: JSON whose keys match what the parsers read (`fields[].type`/`options`/`configuration.iterations`, milestone `node_id`, label `name`). If a key differs, update the corresponding parser AND its fixture test, then re-run the suite.

- [ ] **Step 3: Run the script end-to-end in a scratch copy**

```bash
mkdir -p /tmp/upc-it/.local && cd /tmp/upc-it
git init -q && git remote add origin https://github.com/ericfitz/tmi.git
printf '{"projects":[{"name":"tmi","github":{"owner":"ericfitz","repo":"tmi"}}]}' > .local/projects.json
python3 ~/.claude/plugins/marketplaces/efitz-skills/github/scripts/update_project_cache.py update --name tmi --dir /tmp/upc-it
cat .local/project-cache.json
cat .gitignore
```
Expected: a populated `project-cache.json` with `project`, `fields` (incl. a `Status` single_select with options), `milestones`, `labels`; `.gitignore` contains `.local/`; `projects.json` now has `github.project` set to the resolved title.

- [ ] **Step 4: Clean up scratch dir**

```bash
rm -rf /tmp/upc-it
cd /Users/efitz/.claude/plugins/marketplaces/efitz-skills
```

- [ ] **Step 5: Commit any parser/fixture fixes**

Only if Step 2 required changes:
```bash
git add github/scripts/update_project_cache.py github/scripts/tests/test_update_project_cache.py
git commit -m "fix(github): reconcile parsers with real gh output shapes" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 15: Write the `update-project-cache` SKILL.md

**Files:**
- Create: `github/skills/update-project-cache/SKILL.md`

- [ ] **Step 1: Create the skill file**

Create `github/skills/update-project-cache/SKILL.md`:

````markdown
---
name: update-project-cache
description: Use when refreshing or building the local cache of GitHub Project (v2) metadata for a repo — resolves the associated Project (from .local/projects.json or by discovery), enumerates milestones, statuses, custom fields, labels, and issue types, and writes them to .local/project-cache.json. Run by create-issue when a project is unresolved or a needed value is missing.
allowed-tools: Bash, Read, Glob
argument-hint: [project-name]
---

# Update Project Cache

Resolve a repo's associated GitHub Project (v2) and cache all of its metadata locally so other
skills don't re-query GitHub on every invocation. All lookup logic lives in the bundled script
`scripts/update_project_cache.py`; this skill orchestrates it and handles the one interactive step
(choosing among multiple linked projects).

## Bundled Script Location

This skill bundles `update_project_cache.py` at `scripts/update_project_cache.py` inside its plugin.
`${CLAUDE_PLUGIN_ROOT}` refers to this plugin's install root (typically
`~/.claude/plugins/cache/efitz-skills/github/<version>/`). If the variable is not pre-substituted,
resolve it by locating the directory containing this SKILL.md and walking up to the plugin root.

## What gets cached

For each resolved project, `.local/project-cache.json` (keyed by the local project name) holds:
project id/number/owner/title, all custom fields (keyed by name, with ordered `{name,id}` option
arrays for single-select and iteration fields), repo milestones, labels, and issue types.

## Process

### 1. Run the updater

Run for a single named entry, or omit `--name` to process every entry in `.local/projects.json`:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/update_project_cache.py update [--name <project-name>]
```

The script:
- Reads `.local/projects.json` (falls back to a legacy root `.local-projects.json`, migrating it
  into `.local/projects.json` and dropping any embedded IDs).
- Determines `owner/repo` from the entry or the git remote.
- **Always re-discovers** (it ignores the `""` "no project" marker, so a project created since the
  last run is picked up).
- Resolves the project: a still-linked named title is used; otherwise it discovers Projects v2
  linked to the repo.
- On success, writes the cache entry, records the resolved title in `.local/projects.json`, and
  ensures `.local/` is in `.gitignore`.

It prints a JSON object: `{"results": [ { "name", "status", ... } ]}` where `status` is
`resolved`, `needs_selection`, `none`, or `error`.

### 2. Handle `needs_selection`

If any result has `status: "needs_selection"`, the repo links to multiple projects. Show the user
the `candidates` (each has `number` and `title`) and ask which to use. Then re-run for that entry
with the chosen project:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/update_project_cache.py update \
  --name <project-name> --select-number <chosen-number>
```

(Use `--select-title "<title>"` if you prefer.)

### 3. Report

Summarize per entry:

```
<name>: resolved → "<title>" (cache updated)
<name>: no associated project (marked; create-issue will file plain issues)
<name>: needs selection → asked user
```

## Error Handling

| Result/Error | Behavior |
|---|---|
| `gh` not authenticated | Script exits; tell the user to run `gh auth login`. |
| `status: error`, no owner/repo | Ask the user to add `owner`/`repo` to the entry in `.local/projects.json`. |
| `status: needs_selection` | Ask the user to pick; re-run with `--select-number`. |
| `status: none` | No project linked; nothing cached. This is normal. |
| A `gh` enumeration call fails mid-run | Script raises; prior cache entry (if any) is left intact. Report which call failed. |
````

- [ ] **Step 2: Verify the skill file is valid**

Run: `head -8 github/skills/update-project-cache/SKILL.md`
Expected: frontmatter with `name: update-project-cache`.

- [ ] **Step 3: Commit**

```bash
git add github/skills/update-project-cache/SKILL.md
git commit -m "feat(github): add update-project-cache skill" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Rename `file-bug` → `create-issue` and rewrite it for cache reads + broadened issue types

**Files:**
- Rename: `github/skills/file-bug/SKILL.md` → `github/skills/create-issue/SKILL.md`
- Modify: the renamed `SKILL.md` (full rewrite of the config/lookup sections)

- [ ] **Step 1: Rename the skill directory with git**

```bash
git mv github/skills/file-bug github/skills/create-issue
```

Run: `ls github/skills/`
Expected: `backlog  create-issue  update-project-cache` (no `file-bug`).

- [ ] **Step 2: Rewrite the skill file**

Overwrite `github/skills/create-issue/SKILL.md` with:

````markdown
---
name: create-issue
description: Use when filing a GitHub issue (bug, feature, task, chore, etc.) against a repo, optionally adding it to a GitHub Project (v2), setting milestone from the current branch, and marking initial status. Reads all project/field/milestone IDs from the local cache (.local/project-cache.json); infers the issue type from context unless the user specifies one.
allowed-tools: Bash, Read, Grep, Glob
argument-hint: <target-project-name> [issue-type]
---

# Create GitHub Issue

Create a detailed, unambiguous GitHub issue, optionally adding it to a GitHub Project (v2) and
setting status. All project metadata (ids, fields, options, milestones, labels, issue types) is
read from the local cache built by the `update-project-cache` skill — this skill never enumerates
project metadata itself.

## Inputs

- **target** (argument): the project name in `.local/projects.json` whose repo receives the issue.
  If omitted, ask the user (or default to the sole entry).
- **issue-type** (optional argument): `bug` | `feature` | `task` | `chore` | …. If omitted, infer
  from the conversation and confirm with the user before creating.
- Conversation context: description, evidence, reproduction steps, expected vs. actual behavior,
  acceptance criteria, etc.

## Configuration & cache

- `.local/projects.json` (walk up from `pwd`; fall back to legacy root `.local-projects.json`)
  maps `name → github.{owner, repo, project}`. `github.project` is a Project **title**, `""` means
  "no associated project — do not re-check", and absent/null means "not yet resolved".
- `.local/project-cache.json` (keyed by `name`) holds the resolved ids/fields/milestones/labels/
  issue types. See the `update-project-cache` skill for its shape.

`${CLAUDE_PLUGIN_ROOT}` refers to this plugin's install root.

## Process

### 1. Resolve the project & cache (cheap checks first)

1. Read the target entry from `.local/projects.json`.
2. Branch on `github.project`:
   - **`""`** → honor the marker: create a plain repo issue (skip project add/status). Do **not**
     run update-project-cache.
   - **absent / null** (unresolved) → run the cache updater, then re-read:
     ```bash
     python3 ${CLAUDE_PLUGIN_ROOT}/scripts/update_project_cache.py update --name <target>
     ```
     If the result is `needs_selection`, ask the user to choose and re-run with
     `--select-number <n>` (see the update-project-cache skill). Then re-read.
   - **non-empty title** → load `.local/project-cache.json` and look up the `<target>` key. If the
     cache file or that key is **missing**, run the updater (command above), then re-read.

After this step you either have a cache entry for `<target>`, or `github.project == ""` (plain
issue).

### 2. Determine issue type, labels, and title prefix

- If the user passed/named a type, use it; otherwise infer it from the conversation and **confirm
  with the user** before creating.
- Map type → label(s) + Conventional-Commit prefix:

  | Type | Prefix | Default labels |
  |------|--------|----------------|
  | bug | `fix:` | `bug` (+`api` if an API endpoint is involved) |
  | feature | `feat:` | `enhancement` |
  | task | `chore:` | (none, or `chore` if it exists) |
  | chore | `chore:` | (none, or `chore` if it exists) |

- Only apply labels that exist in the cache's `labels` list. If a desired label is missing from the
  cache, run the updater once to refresh, re-read, and if still missing, omit it (note the omission).
- If the cache `issue_types` is non-empty and contains a matching type, pass `--type "<Type>"` to
  `gh issue create`.

### 3. Determine milestone from branch

```bash
BRANCH=$(git branch --show-current)
```

Look for a cache milestone whose `title` exactly equals `$BRANCH`. If found, use it. If `$BRANCH`
is not `main` and no milestone matches, run the updater once to refresh the cache (a milestone may
have been created after the last build), then re-check. If still none, create without a milestone.

### 4. Build the body (by type)

Use a template matched to the issue type. Omit sections that don't apply.

**Bug:**
```markdown
## Summary
<1-3 sentence description>

## Steps to Reproduce
1. <step>

## Expected Behavior
<what should happen>

## Actual Behavior
<what actually happens>

## Evidence
<logs, payloads, code refs>

## Possible Cause
<root-cause hypotheses with code references>

## Impact
<severity, user-facing impact>

## Environment
<endpoint, client version, content-type, etc.>
```

**Feature / Task:**
```markdown
## Summary
<what to build and why>

## Acceptance Criteria
- [ ] <criterion>

## Notes
<design considerations, references, constraints>
```

### 5. Create the issue

```bash
gh issue create --repo "$OWNER/$REPO" \
  --title "<prefix> <concise description>" \
  --label "<labels>" \
  ${ISSUE_TYPE:+--type "$ISSUE_TYPE"} \
  ${MILESTONE:+--milestone "$MILESTONE"} \
  --body "$(cat <<'EOF'
<body content>
EOF
)"
```

Capture the issue URL and number.

### 6. Add to the project & set status (only if a cache entry exists)

Read ids from the cache entry for `<target>`:
- `project.number`, `project.owner`, `project.id`
- `fields.Status.id` and the option id for the chosen status from `fields.Status.options`

```bash
gh project item-add "<project.number>" --owner "<project.owner>" --url "$ISSUE_URL"

ITEM_ID=$(gh project item-list "<project.number>" --owner "<project.owner>" \
  --format json --limit 200 \
  | jq -r --argjson n "$ISSUE_NUMBER" '.items[] | select(.content.number==$n) | .id')

gh project item-edit --project-id "<project.id>" --id "$ITEM_ID" \
  --field-id "<fields.Status.id>" --single-select-option-id "<status-option-id>"
```

**Default status** (policy, not cached): choose the option named like "This milestone" if present;
otherwise the first option in `fields.Status.options`. The caller may override by naming a status;
match it case-insensitively against option names.

If a needed value (status option, etc.) is absent from the cache, run the updater **once** to
refresh, then re-read. If still absent after that single refresh, proceed without it and note the
omission — never loop.

### 7. Report

```
Created: <issue_url>
  Type:      <type> (<prefix>)
  Labels:    <labels>
  Milestone: <milestone or "none">
  Project:   <title or "none"> (<status or "n/a">)
```

## Error Handling

| Situation | Behavior |
|---|---|
| `gh` not authenticated | Tell the user to run `gh auth login`. |
| Target not in `.local/projects.json` | Error with the list of known names. |
| `github.project == ""` | Create a plain issue; skip project add/status. |
| Cache missing / value missing | Run update-project-cache once; if still missing, proceed without and note it. |
| Milestone not found (after one refresh) | Create without a milestone. |
| `gh project item-add` / status edit fails | Report; the issue still exists. |

## Implementation Notes

1. **Cache is the source of ids.** This skill never enumerates project metadata; it delegates that
   to `update-project-cache`, and triggers it at most twice per run (once for an unresolved
   project, once for a single missing value).
2. **Evidence quality matters** for bugs: include actual payloads and field values.
3. **Conventional-Commit prefixes** by type as in the table above.
4. **Branch → milestone**: exact title match; no fuzzy matching.
````

- [ ] **Step 3: Verify**

Run: `head -6 github/skills/create-issue/SKILL.md && test ! -d github/skills/file-bug && echo "rename OK"`
Expected: frontmatter `name: create-issue` and `rename OK`.

- [ ] **Step 4: Commit**

```bash
git add -A github/skills/
git commit -m "feat(github): rename file-bug to create-issue; read from cache; broaden issue types" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Update plugin + marketplace descriptions

**Files:**
- Modify: `github/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Update `github/.claude-plugin/plugin.json`**

Replace its `description` value with:

```
GitHub workflow toolkit: pick the next issue to work on from a milestone/backlog (backlog), cache a repo's GitHub Project (v2) metadata locally (update-project-cache), and file detailed issues into a repo/Project using that cache (create-issue). Use for issue triage, project metadata caching, and issue filing.
```

- [ ] **Step 2: Update the github entry in `.claude-plugin/marketplace.json`**

Replace the github plugin's `description` value with:

```
GitHub workflow toolkit: pick the next issue to work on from a milestone/backlog (backlog), cache a repo's GitHub Project (v2) metadata locally (update-project-cache), and file detailed issues into a repo/Project using that cache (create-issue). Use for issue triage, project metadata caching, and issue filing.
```

- [ ] **Step 3: Verify JSON is valid**

Run: `python3 -c "import json; json.load(open('github/.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('valid')"`
Expected: `valid`.

- [ ] **Step 4: Commit**

```bash
git add github/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "docs(github): update plugin/marketplace descriptions for create-issue + update-project-cache" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Record the global `.local/` convention (memory + global CLAUDE.md)

This step writes to `~/.claude/`, outside the plugin repo (no commit in this repo).

**Files:**
- Modify (or create): `~/.claude/CLAUDE.md`
- Create: `~/.claude/projects/-Users-efitz/memory/local-dir-convention.md`
- Modify: `~/.claude/projects/-Users-efitz/memory/MEMORY.md`

- [ ] **Step 1: Add the convention section to `~/.claude/CLAUDE.md`**

Append this section (create the file if it doesn't exist):

```markdown
## `.local/` directory convention

Each project may contain a `.local/` directory holding **non-tracked, machine-local** config and
cache files — e.g. resolved GitHub Project metadata and ID caches (`.local/projects.json`,
`.local/project-cache.json`). It is **always gitignored**. Do **not** use it for high-volume
artifacts like logs or test output. Tools that generate local config/cache should write it here.
```

- [ ] **Step 2: Write the memory file**

Create `~/.claude/projects/-Users-efitz/memory/local-dir-convention.md`:

```markdown
---
name: local-dir-convention
description: Per-project .local/ directory holds non-tracked machine-local config and cache files
metadata:
  type: feedback
---

Projects use a `.local/` directory for non-tracked, machine-local config and cache files
(e.g. `.local/projects.json`, `.local/project-cache.json`). Always gitignored. Not for
high-volume artifacts like logs or test output.

**Why:** Keeps generated/local-only state out of git and in one predictable place.

**How to apply:** When a tool needs to persist local config or a cache, write it under `.local/`
and ensure `.local/` is in `.gitignore`. Established for the github plugin's project cache.
```

- [ ] **Step 3: Add the MEMORY.md pointer**

Append to `~/.claude/projects/-Users-efitz/memory/MEMORY.md`:

```markdown
- [.local/ convention](local-dir-convention.md) — non-tracked per-project config/cache dir
```

- [ ] **Step 4: Verify**

Run: `ls ~/.claude/projects/-Users-efitz/memory/local-dir-convention.md && grep -q ".local/" ~/.claude/CLAUDE.md && echo OK`
Expected: the path prints and `OK`.

(No repo commit — these files live in `~/.claude/`.)

---

## Task 19: Final full-suite run

**Files:** none (verification only).

- [ ] **Step 1: Run the full test suite**

Run: `cd github/scripts && python3 -m unittest discover -s tests -v`
Expected: all tests PASS, 0 failures/errors.

- [ ] **Step 2: Confirm the branch state**

Run: `cd /Users/efitz/.claude/plugins/marketplaces/efitz-skills && git status && git log --oneline -15`
Expected: clean working tree; commits for each task present on `feat/github-project-cache`.

---

## Self-Review notes (for the implementer)

- **Spec coverage:** discovery flow (Tasks 4, 11, 12, 13), `""` marker semantics — ignored by
  updater (Task 4 `select_project`), honored by create-issue (Task 16) — full enumeration
  (Tasks 5–7, 11), cache shape with ordered option/milestone arrays + name-keyed fields
  (Tasks 5–7), migration from legacy root file dropping IDs (Tasks 8, 13), `.gitignore` handling
  (Tasks 9, 12), rename + broadening (Task 16), global `.local/` convention (Task 18).
- **Loop prevention** is enforced in create-issue (Task 16), which calls the updater at most twice.
- **Naming consistency:** function names used across tasks — `parse_git_remote`,
  `parse_linked_projects`, `select_project`, `parse_fields`, `parse_milestones`, `parse_labels`,
  `parse_issue_types`, `build_cache_entry`, `get_entry`, `set_project_title`, `migrate_entry`,
  `ensure_gitignore_text`, `ensure_gitignore_file`, `write_json`, `find_config`, `update_cache`,
  `run_gh`/`run_gh_json`/`run_gh_graphql`, `git_remote_url`, `discover_linked_projects`,
  `enumerate_project`, `process_entry`, `_load_or_init_config`, `main`.
