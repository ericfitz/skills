---
name: create-issue
description: Use when filing a GitHub issue (bug, feature, task, chore, etc.) against a repo, optionally adding it to a GitHub Project (v2), setting milestone from the current branch, and marking initial status. Reads all project/field/milestone IDs from the local cache (.local/gh-projects.json), provisioned by ~/Scripts/provision-repo-config.py; infers the issue type from context unless the user specifies one.
allowed-tools: Bash, Read, Grep, Glob
argument-hint: <target-project-name> [issue-type]
---

# Create GitHub Issue

Create a detailed, unambiguous GitHub issue, optionally adding it to a GitHub Project (v2) and
setting status. All project metadata (ids, fields, options, milestones, labels, issue types) is
read from the local cache `.local/gh-projects.json`, provisioned out-of-band by
`~/Scripts/provision-repo-config.py`. This skill never enumerates or refreshes project metadata.

## Inputs

- **target** (argument): the project name (a key in `.local/repos.json`) whose repo receives the
  issue. If omitted, ask the user (or default to the sole entry).
- **issue-type** (optional argument): `bug` | `feature` | `task` | `chore` | …. If omitted, infer
  from the conversation and confirm with the user before creating.
- Conversation context: description, evidence, reproduction steps, expected vs. actual behavior,
  acceptance criteria, etc.

## Configuration & cache

- `.local/repos.json` (walk up from `pwd`) is a JSON object **keyed by name**:
  `{ "<name>": { "path": "...", "github": { "owner", "repo", "project", "wiki_path" } } }`.
  `github.project` is a Project **title**; `""` means "no associated project — file a plain
  issue"; absent/null means "not yet resolved".
- `.local/gh-projects.json` (keyed by `<name>`) holds the resolved
  ids/fields/milestones/labels/issue types.

Both files are provisioned by `~/Scripts/provision-repo-config.py`, run once per repo. This skill
reads them and never writes or refreshes them.

## Process

### 1. Resolve the project & cache (cheap checks first)

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

- Only apply labels that exist in the cache's `labels` list. If a desired label is missing, omit it
  and note the omission (the cache refreshes only by re-running the provisioning script).
- If the cache `issue_types` is non-empty and contains a matching type, pass `--type "<Type>"` to
  `gh issue create`.

### 3. Determine milestone from branch

```bash
BRANCH=$(git branch --show-current)
```

Look for a cache milestone whose `title` exactly equals `$BRANCH`. If found, use it. If `$BRANCH`
is not `main` and no milestone matches, create without a milestone (the cache may be stale; re-run
the provisioning script to refresh).

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

If a needed value (status option, etc.) is absent from the cache, proceed without it and note the
omission — never loop. Re-run the provisioning script to refresh the cache.

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
| Target not in `.local/repos.json` | Error with the list of known names. |
| `github.project == ""` | Create a plain issue; skip project add/status. |
| Cache file/entry missing | Tell the user to run `~/Scripts/provision-repo-config.py`, then stop. |
| Individual value missing (label/status option) | Proceed without it and note the omission. |
| Milestone not found (after one refresh) | Create without a milestone. |
| `gh project item-add` / status edit fails | Report; the issue still exists. |

## Implementation Notes

1. **Cache is the source of ids.** This skill never enumerates or refreshes project metadata;
   provisioning is done out-of-band by `~/Scripts/provision-repo-config.py`. When a required cache
   entry is missing, the skill stops and asks the user to run it; individual missing values are
   skipped with a note.
2. **Evidence quality matters** for bugs: include actual payloads and field values.
3. **Conventional-Commit prefixes** by type as in the table above.
4. **Branch → milestone**: exact title match; no fuzzy matching.
