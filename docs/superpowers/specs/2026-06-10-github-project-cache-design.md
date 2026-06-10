# GitHub Project Cache — Design

**Date:** 2026-06-10
**Status:** Approved (pending implementation plan)
**Plugin:** `github`

## Problem

The `file-bug` skill resolves GitHub Projects (v2) metadata — project id, status field id,
option ids — on every invocation, and that metadata is currently expected to live inline in
`.local-projects.json`. This duplicates lookup logic, hits the GitHub API repeatedly, and
couples the association config to volatile IDs.

We want to:

1. Cache all project-specific GitHub metadata (project ids, custom fields, milestones, labels,
   issue types) in a generated, non-tracked file per repo.
2. Factor all lookup/enumeration logic into a single place (no duplication, run on demand).
3. Keep `.local-projects.json` as a thin association config (project *name* only).
4. Rename `file-bug` → `create-issue` and broaden it beyond bug reports.

## Goals / Non-Goals

**Goals**
- Single source of lookup logic, invoked on demand rather than per-issue.
- `create-issue` reads IDs only from the local cache.
- Auto-discover the associated GitHub Project for repos that don't name one.
- Establish a global `.local/` convention for non-tracked, machine-local config/cache.

**Non-Goals**
- No changes to the `backlog` skill in this work (may consume the cache later).
- No cache TTL / time-based invalidation (refresh is triggered by missing values only).
- Not a store for high-volume artifacts (logs, test output).

## Approach

Bundled Python script (`scripts/update-project-cache.py`) owns all git-context detection,
project resolution, GraphQL enumeration of Projects v2 fields, milestones, labels, and issue
types, and the cache + config write-back. The two skills orchestrate the script. Chosen over
inline `gh`/`jq` because Projects v2 enumeration needs GraphQL with several field-type shapes
that are fragile and easily duplicated in bash. Mirrors the existing `gh-issues.py` pattern.

## Components & File Layout

**Plugin (`github/`):**
- `scripts/update-project-cache.py` — all lookup/enumeration logic (new).
- `skills/update-project-cache/SKILL.md` — orchestrates the script; handles the
  "multiple projects → ask user" interaction (new).
- `skills/create-issue/SKILL.md` — renamed from `file-bug`, broadened to any issue type;
  reads only the cache (modified). Update `plugin.json` description accordingly.
- `skills/backlog/` — unchanged.

**In each working repo (all non-tracked, under `.local/`):**
- `.local/projects.json` — association config (migrated from root `.local-projects.json`;
  skills fall back to reading the old root path if the new one is absent).
- `.local/project-cache.json` — generated cache (IDs, fields, milestones, labels, issue types).

**Global, one-time (this session):**
- A section in `~/.claude/CLAUDE.md` documenting the `.local/` convention.
- A matching global memory file + `MEMORY.md` pointer.

## Data Schemas

### `.local/projects.json` (association + resolution state; skills write back to it)

```jsonc
{
  "projects": [{
    "name": "tmi",                  // local handle, also the cache key
    "github": {
      "owner": "ericfitz",          // optional; derived from git remote if absent
      "repo": "tmi",                // optional; derived from git remote if absent
      "project": "TMI Roadmap"      // resolved Project *title*. States:
                                    //   absent / null  → not yet resolved (run discovery)
                                    //   "Some Title"   → use this project
                                    //   ""             → resolved to "no project"
                                    //                    (honored by create-issue only)
    }
  }]
}
```

For a repo with no `projects.json` at all, the skill creates one with a single entry keyed by
repo name.

### `.local/project-cache.json` (generated; keyed by the `name` above)

```jsonc
{
  "tmi": {
    "cached_at": "2026-06-10T12:00:00Z",       // script stamps real time
    "project": { "number": 2, "owner": "ericfitz", "id": "PVT_...", "title": "TMI Roadmap" },
    "fields": {                                  // keyed by field name
      "Status": {
        "id": "PVTSSF_...", "type": "single_select",
        "options": [                             // ordered array
          { "name": "Backlog",        "id": "<opt-id>" },
          { "name": "This milestone", "id": "<opt-id>" },
          { "name": "In progress",    "id": "<opt-id>" },
          { "name": "Done",           "id": "<opt-id>" }
        ]
      },
      "Priority": { "id": "...", "type": "single_select", "options": [ /* ... */ ] },
      "Estimate": { "id": "...", "type": "number" },
      "Sprint":   { "id": "...", "type": "iteration",
                    "options": [ { "name": "...", "id": "..." } ] }
    },
    "milestones": [                              // ordered array
      { "title": "release/1.3.0", "number": 5, "id": "MI_..." }
    ],
    "labels": ["bug", "api", "enhancement"],
    "issue_types": ["Bug", "Feature", "Task"]    // [] if repo has none enabled
  }
}
```

**Schema decisions:**
- Options and milestones are **ordered arrays of `{name, id}`** — preserves the project's
  option ordering (needed for the default-status "first option" fallback), avoids name-collision
  corner cases, leaves room for per-option metadata.
- `fields` is **keyed by field name** (per preference).
- Status **default option** is *not* stored in the cache — default selection is policy and
  lives in `create-issue`.

## `update-project-cache` — Skill + Script Behavior

The script exposes resolution + enumeration; the skill orchestrates the one interactive step.
**`update-project-cache` always ignores the `""` marker** and re-runs discovery, so a manual or
scheduled run can pick up a project created/linked since the last check.

**Resolution flow (per project entry, or the current repo if no config):**
1. Load `.local/projects.json` (fallback: root `.local-projects.json`; if found there, migrate
   it into `.local/projects.json`).
2. Determine `owner/repo` — from the entry, else from the git remote.
3. Read `github.project`:
   - non-empty title → verify the project still exists / links to the repo. If yes → enumerate.
     If the named one no longer exists → fall through to discovery.
   - absent / null / `""` → discovery (the `""` marker is **not** honored here).
4. **Discovery:** query Projects v2 linked to the repo (GraphQL `repository.projectsV2`).
   - exactly one → use it; write its title back to `projects.json`.
   - multiple → script emits the candidate list as JSON and exits with a "needs selection"
     status; the skill asks the user to pick, then re-invokes the script with the chosen
     project; selection written back.
   - none → write `"project": ""` marker back; no cache entry.
5. **Enumerate** the chosen project: project id/number, all custom fields (+options/iterations),
   repo milestones, labels, issue types → write/refresh that key in `.local/project-cache.json`
   with a fresh `cached_at`.

**Invocation modes:** full refresh (all entries) and single-target (`<name>`). On first run it
ensures `.local/` exists and that `.local/` is in `.gitignore`.

## `create-issue` — Skill Behavior

create-issue does the cheap check itself and only escalates to `update-project-cache` when
warranted — it never blindly refreshes.

**Decision logic:**
1. Load `.local/projects.json` (fallback to root `.local-projects.json`) for the target entry.
2. Branch on `github.project`:
   - **`""`** → honor the marker. Create a plain repo issue (no project add, no status). Do
     **not** run update-project-cache.
   - **absent / null** (unresolved) → run the `update-project-cache` skill, then re-read. Now
     it's either a resolved title or `""`; continue accordingly.
   - **non-empty title** → look for `.local/project-cache.json[name]`. If the cache file or that
     key is **missing** → run update-project-cache, then re-read.
3. Resolve the values needed for this issue (status, milestone-from-branch, any field/label the
   user specified or inferred) against the cache.
4. **Single cache-miss refresh:** if a *specific needed value* isn't in the cache (e.g. the
   branch's milestone was created after the last cache build), run update-project-cache **once**
   to refresh, then re-resolve. If still missing after that one refresh, proceed without that
   value (don't loop); note the omission in output.

**Broadened issue creation (infer-unless-specified):**
- Infer issue type from the conversation (bug / feature / task / chore / …); if the user named a
  type, use it.
- Map type → labels + Conventional-Commit title prefix (`bug`→`fix:`, `feature`→`feat:`,
  `chore`→`chore:`, etc.), and → repo issue type if the repo has issue types enabled and one
  matches.
- Pick a body template by type — the current detailed bug template becomes the bug variant;
  lighter templates for feature/task. When type is inferred (not user-specified), confirm
  type/labels/prefix with the user before creating.
- Default **status** is the "this milestone"-style option if present, else the first status
  option.

## Error Handling & Edge Cases

| Situation | Behavior |
|---|---|
| `gh` not authenticated | Tell user to run `gh auth login`; abort. |
| Not in a git repo / no remote, no `owner/repo` in config | Error; ask user to add `owner`/`repo` to the entry. |
| GraphQL/`gh` call fails mid-enumeration | Don't write a partial cache key; report which call failed; leave any prior cache entry intact. |
| Project named in config no longer exists | Fall through to discovery. |
| Discovery returns multiple | Skill asks user to pick; never auto-guesses. |
| Discovery returns none | Write `"project": ""`; create-issue makes plain issues. |
| Needed value missing after one refresh | create-issue proceeds without it (no loop); notes omission in output. |
| `.local/` or `projects.json` missing | Created on demand. |

**Loop prevention:** create-issue triggers `update-project-cache` in at most two situations per
run — once for an unresolved project, and at most once more for a single missing value — then
proceeds regardless. The `""` marker stops repeated discovery across runs.

**Migration:** if a root `.local-projects.json` exists and `.local/projects.json` does not, move
it into `.local/projects.json` (preserving entries) and note it in skill output. If the old file
used a legacy `issues_project{...}` ID block, keep `owner/repo/project-title` and drop the
embedded IDs (now sourced from the cache).

**.gitignore:** on first run ensure an entry for `.local/` exists (add if missing). Ignoring the
whole dir is simplest since it holds only non-tracked config/cache.

## Global `.local/` Convention (one-time, this session)

- Add a `~/.claude/CLAUDE.md` section: *"Per-project `.local/` directory holds non-tracked,
  machine-local config and cache files (e.g. resolved project metadata, ID caches). Not for
  high-volume artifacts like logs or test output. Always gitignored."*
- Write a matching global memory file + `MEMORY.md` pointer.

## Testing

- Script unit-level checks against fixture GraphQL/`gh` JSON: field-type shapes (single_select,
  text, number, date, iteration), milestone/label/issue-type extraction, write-back states
  (resolved title, `""` marker, multiple-candidates).
- Resolution flow: named-exists, named-missing→discovery, unresolved→discovery (one / multiple /
  none).
- create-issue decision matrix: `""` marker, unresolved, cache-present-with-value,
  cache-missing-key, single-miss-refresh-then-proceed (loop prevention).
- Migration: root `.local-projects.json` (plain + legacy ID block) → `.local/projects.json`.
- `.gitignore` insertion idempotency.
