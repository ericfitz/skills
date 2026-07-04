# Local config conventions: `.local/repos.json` + `.local/gh-projects.json`

**Date:** 2026-07-04
**Status:** Approved (design)

## Problem

Skills that need to know *where a related local repo lives* and *what a repo's
GitHub Project metadata is* currently disagree on file name, location, and shape:

- **Repo location** was expressed two ways historically: a file, and `*_REPO`
  environment variables (e.g. `TMI_REPO`) pointing at local working copies. The
  env-var pattern is to be eliminated entirely.
- **The registry file** exists in two variants:
  - `.local-projects.json` at repo root — a bare array `[{name, path, github:{owner, repo, wiki_path}}]`
    (used by `wiki/verify-doc`, `ui/vrt`).
  - `.local/projects.json` — a wrapped list `{"projects":[{name, path, github:{owner, repo, project}}]}`
    (used by `github/create-issue`, `github/update-project-cache`).
- **The GitHub cache** exists once: `.local/project-cache.json` (a true map keyed
  by name), used only by the `github` skills.

The goal: one canonical name, location, and format for each concern, adopted by
every consuming skill, with no `*_REPO` env vars anywhere.

## Decisions

1. **Both files live in a gitignored `.local/` directory**, discovered by walking
   up from `pwd`. `.local/` is ensured present in `.gitignore`.
2. **Registry file → `.local/repos.json`**, a **top-level map keyed by name**.
3. **Cache file → `.local/gh-projects.json`**, a **top-level map keyed by name**
   (same content as today's `project-cache.json`, renamed).
4. **Refactor freely.** github's currently-tested `{"projects":[...]}` shape is
   dropped in favor of the keyed map. All four consuming skills are updated.
5. **No `*_REPO` environment variables.** A repo's local path comes only from
   `.local/repos.json` (`<name>.path`).

## Schemas

### `.local/repos.json` (registry; skills read it, `update-project-cache` writes back)

Top-level object keyed by the repo's local handle (`name`). Each entry is a
superset object; a consumer reads only the fields it needs and degrades
gracefully when an optional field is absent.

```jsonc
{
  "tmi": {                          // the key IS the name, and the gh-projects.json key
    "path": "/abs/path/to/repo",    // local working copy; replaces all *_REPO env vars
    "github": {
      "owner": "ericfitz",          // optional; derived from git remote if absent
      "repo": "tmi",                // optional; derived from git remote if absent
      "project": "TMI Roadmap",     // Project *title*:
                                    //   absent / null → not yet resolved (run discovery)
                                    //   "Some Title"   → use this project
                                    //   ""             → resolved to "no project"
                                    //                    (honored by create-issue only)
      "wiki_path": "/abs/path/wiki" // optional; only wiki/verify-doc needs it
    }
  }
}
```

Field ownership by consumer:

| Field | create-issue | update-project-cache | wiki/verify-doc | ui/vrt |
|-------|:---:|:---:|:---:|:---:|
| `path` | – | – | reads | reads (matches `pwd`) |
| `github.owner` / `github.repo` | reads | reads / derives | reads | reads |
| `github.project` | reads/writes state | reads, writes back title | – | – |
| `github.wiki_path` | – | – | reads | – |

### `.local/gh-projects.json` (generated cache; keyed by name — unchanged content)

```jsonc
{
  "tmi": {
    "cached_at": "2026-06-10T12:00:00Z",
    "project": { "number": 2, "owner": "ericfitz", "id": "PVT_...", "title": "TMI Roadmap" },
    "fields": {                                  // keyed by field name
      "Status": {
        "id": "PVTSSF_...", "type": "single_select",
        "options": [                             // ordered array of {name,id}
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
    "milestones": [ { "title": "release/1.3.0", "number": 5, "id": "MI_..." } ],
    "labels": ["bug", "api", "enhancement"],
    "issue_types": ["Bug", "Feature", "Task"]
  }
}
```

Schema is otherwise identical to the prior `project-cache.json` design: `fields`
keyed by field name; options and milestones are ordered `{name, id}` arrays;
default-status selection is policy that lives in `create-issue`, not the cache.

## Migration (on-disk legacy → new files)

`update-project-cache` (the only writer) owns migration. On any run it normalizes
whatever legacy shape it finds into `.local/repos.json` (keyed map) and, if a
legacy cache exists, renames it to `.local/gh-projects.json`.

Legacy shapes to accept and normalize:

| Legacy | Location | Shape | Normalize to |
|--------|----------|-------|--------------|
| Bare array | root `.local-projects.json` | `[{name, path, github}]` | `.local/repos.json` keyed map |
| Wrapped list | `.local/projects.json` | `{"projects":[{name, path, github}]}` | `.local/repos.json` keyed map |
| Already keyed | `.local/repos.json` | `{name: {...}}` | idempotent no-op |
| Old cache | `.local/project-cache.json` | keyed map | rename → `.local/gh-projects.json` |

Normalization also drops any legacy `github.issues_project` id block (as the
current migrator already does). The legacy source files are left in place (not
deleted) after the new files are written.

Read-only consumers (`create-issue`, `wiki/verify-doc`, `ui/vrt`) look up
`.["<name>"]` in `.local/repos.json`. If `.local/repos.json` is absent, they fall
back to reading a legacy file **read-only** (normalizing in-memory) and note that
the user should run `update-project-cache` once to persist the migration. They do
not write the new files themselves.

## Skill changes

### `github/update-project-cache` (+ `scripts/update_project_cache.py`, `tests/test_update_project_cache.py`)
- Registry constant → `repos.json`; cache constant → `gh-projects.json`.
- Replace `config["projects"]` list access (`get_entry`, `set_project_title`)
  with keyed-map access (`config[name]`).
- Add normalization for the three legacy registry shapes and the cache rename.
- Update `find_config` / write paths and gitignore ensuring accordingly.
- Update unit tests to the keyed-map shape and new filenames; add a migration test
  per legacy shape.

### `github/create-issue`
- Read `.local/repos.json` by key (`.["<name>"]`) instead of scanning a list.
- Read the cache from `.local/gh-projects.json`.
- Fix the SKILL.md wording ("maps name → …") to describe the true keyed map and
  the new filenames.

### `wiki/verify-doc`
- Read `.local/repos.json` (keyed map) for `path` + `github.wiki_path`; legacy
  root array as read-only fallback.
- Update the `description` frontmatter and body references from `.local-projects.json`.

### `ui/vrt`
- Read `.local/repos.json` (keyed map) for `github.{owner, repo}`, matching the
  current project by `path` vs `pwd`; legacy root array as read-only fallback.
- Update body references from `.local-projects.json`.

## Documentation

- This spec is the canonical description of both files.
- Update the `.local/` convention note in `~/.claude/CLAUDE.md` and its global
  memory pointer to: (a) name `repos.json` and `gh-projects.json`, (b) describe
  the keyed-map registry, (c) forbid `*_REPO` environment variables for repo
  locations.

## Out of scope

- `dev/dedupe` and `dev/sem-annotate` use `.local/sem-scope.json` and
  `.local/sem.db` — the same `.local/` convention but a different concern (scan
  scope, not repo location or GitHub metadata). Already conformant; unchanged.
- `dev` skills' `-C <repo-dir>` / `REPO_DIR` are *runtime* "operate on this repo
  now" parameters, not a persistent registry. Unchanged.
- `loc`'s in-repo `.claude/i18n.config.json` is a within-repo config, not a
  related-repos registry. Unchanged.
- `github/backlog` auto-detects owner/repo from the git remote; it reads neither
  file. Unchanged.
