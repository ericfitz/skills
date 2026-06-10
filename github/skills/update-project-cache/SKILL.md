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
