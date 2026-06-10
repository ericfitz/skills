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
   to `update-project-cache`, and triggers it at most once per unresolved state (an unresolved
   project, a missing label, a missing milestone) — each fires at most once, then proceeds
   regardless, so it never loops.
2. **Evidence quality matters** for bugs: include actual payloads and field values.
3. **Conventional-Commit prefixes** by type as in the table above.
4. **Branch → milestone**: exact title match; no fuzzy matching.
