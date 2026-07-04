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
every consuming skill, with no `*_REPO` env vars anywhere. Provisioning of the
`.local/` files is done **out-of-band by a script the user runs once per repo**,
not by an in-repo skill.

## Decisions

1. **Both files live in a gitignored `.local/` directory**, discovered by walking
   up from `pwd`. `.local/` is ensured present in `.gitignore`.
2. **Registry file → `.local/repos.json`**, a **top-level map keyed by name**.
3. **Cache file → `.local/gh-projects.json`**, a **top-level map keyed by name**
   (same content as today's `project-cache.json`, renamed).
4. **The `update-project-cache` skill is removed.** Its resolution/enumeration/
   migration logic moves into a standalone provisioning script that lives at
   `~/Scripts/provision-repo-config.py` (uncommitted; not part of this repo).
   The script is the sole writer/migrator of both `.local/` files.
5. **Consuming skills are read-only.** They read the canonical keyed maps and never
   write, migrate, or auto-refresh. When a needed file/entry is absent, they
   instruct the user to run the provisioning script and stop (or fall back to
   their existing unconfigured behavior — see per-skill notes).
6. **No `*_REPO` environment variables.** A repo's local path comes only from
   `.local/repos.json` (`<name>.path`).

## Schemas

### `.local/repos.json` (registry; written by the provisioning script, read by skills)

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

| Field | create-issue | provision script | wiki/verify-doc | ui/vrt |
|-------|:---:|:---:|:---:|:---:|
| `path` | – | prompts / preserves | reads | reads (matches `pwd`) |
| `github.owner` / `github.repo` | reads | derives / writes | reads | reads |
| `github.project` | reads | resolves, writes title | – | – |
| `github.wiki_path` | – | prompts / preserves | reads | – |

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

## Provisioning script — `~/Scripts/provision-repo-config.py`

A standalone, uncommitted CLI the user runs **once per repo** (from inside the
repo, or with `--dir <path>`). It is the sole writer and migrator of the two
`.local/` files. It carries forward the logic currently in
`github/scripts/update_project_cache.py`.

Behavior per run:

1. Determine `owner/repo` from the git remote (or an existing legacy entry).
2. Build/refresh the `.local/repos.json` entry for the repo's `name`:
   - preserve existing `path` / `github.wiki_path`; prompt for them when absent.
   - resolve `github.project` via Projects v2 discovery
     (`repository.projectsV2`). On multiple linked projects, prompt the user to
     choose interactively (stdin). Write the resolved title back.
3. Enumerate GitHub Project metadata (ids, fields, milestones, labels, issue
   types) and write `.local/gh-projects.json` keyed by `name`.
4. Migrate any legacy files found (see table) into the canonical files.
5. Ensure `.local/` is present in `.gitignore`.
6. Writes are atomic (temp file + rename).

### Migration (on-disk legacy → canonical)

| Legacy | Location | Shape | Normalize to |
|--------|----------|-------|--------------|
| Bare array | root `.local-projects.json` | `[{name, path, github}]` | `.local/repos.json` keyed map |
| Wrapped list | `.local/projects.json` | `{"projects":[{name, path, github}]}` | `.local/repos.json` keyed map |
| Already keyed | `.local/repos.json` | `{name: {...}}` | idempotent no-op |
| Old cache | `.local/project-cache.json` | keyed map | rename → `.local/gh-projects.json` |

Normalization drops any legacy `github.issues_project` id block. Legacy source
files are left in place (not deleted) after the canonical files are written.

## Skill changes

### Removed: `github/update-project-cache`
- Delete the skill directory `github/skills/update-project-cache/`.
- Delete `github/scripts/update_project_cache.py` (logic extracted to the
  external provisioning script) and `tests/test_update_project_cache.py`.
- Remove it from `github/.claude-plugin/plugin.json`, the root
  `.claude-plugin/marketplace.json`, `README.md`, and
  `scripts/verify-marketplace.sh` (both the skill list and the script-path list).

### `github/create-issue`
- Read `.local/repos.json` by key (`.["<name>"]`) and the cache from
  `.local/gh-projects.json`.
- Remove all auto-invocation of `update-project-cache`. When the cache file or
  the `<name>` entry is **missing**: instruct the user to run
  `~/Scripts/provision-repo-config.py` against this repo, then stop. (The `""`
  "no project" marker still means "create a plain repo issue".)
- Fix the SKILL.md wording ("maps name → …", "cache built by the
  update-project-cache skill") to describe the keyed map, the new filenames, and
  the external script.

### `wiki/verify-doc`
- Read `.local/repos.json` (keyed map) for `path` + `github.wiki_path`.
- When absent, keep the existing graceful behavior (verification-only, migration
  skipped) and note the provisioning script.
- Update the `description` frontmatter and body references from `.local-projects.json`.

### `ui/vrt`
- Read `.local/repos.json` (keyed map) for `github.{owner, repo}`, matching the
  current project by `path` vs `pwd`.
- When absent, keep the existing fallback to plain `gh` and note the provisioning
  script.
- Update body references from `.local-projects.json`.

## Documentation

- This spec is the canonical description of both files and the provisioning script.
- Update the `.local/` convention note in `~/.claude/CLAUDE.md` and its global
  memory pointer to: (a) name `repos.json` and `gh-projects.json`, (b) describe
  the keyed-map registry, (c) name `~/Scripts/provision-repo-config.py` as the
  sole provisioner, (d) forbid `*_REPO` environment variables for repo locations.

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
