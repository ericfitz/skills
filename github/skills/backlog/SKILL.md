---
name: backlog
version: 1.0.0
description: Pick the next GitHub issue to work on. Use when the user asks what to work on next, requests the next backlog item, or wants an issue prioritized for the current milestone. Fetches open issues, applies exclusion rules, prioritizes by status/security/dependencies, and recommends one.
---

# Working on backlog: Next Issue Command

Pick the next GitHub issue to work on by analyzing open issues, prioritizing them, and recommending one.

**IMPORTANT**: This is a backlog triage command — it has nothing to do with Next.js or any JavaScript framework. Set the session topic/title to "Working on backlog" (use `/rename Working on backlog`).

## Bundled Script Location

This skill bundles `gh-issues.py` inside its plugin at `scripts/gh-issues.py`. When you see `${CLAUDE_PLUGIN_ROOT}` below, it refers to this plugin's install root — typically `~/.claude/plugins/cache/efitz-skills/github/<version>/`. If Claude Code does not pre-substitute the variable when you read this file, resolve it yourself: locate the directory containing this SKILL.md, walk up to the plugin root, and use that absolute path. Do **NOT** fall back to `~/.claude/scripts/gh-issues.py` — that path is from the legacy command and may not exist after cutover.

## Process

### Step 1: Fetch Candidate Issues

Use `${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py` to fetch issues with project status and priority. The script outputs JSON with fields: number, title, milestone, assignee, status, priority, labels, body, comments.

**Fetch all open issues for the current milestone:**

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py
```

The script auto-detects the repo, branch, and extracts a semver from the branch name to filter by milestone. If the branch is `main` or has no semver, it returns all open issues.

Use the milestone-matched results as the candidate pool for Steps 2-4. **Do not fetch backlog issues yet** — only consider backlog if the current milestone has no viable candidates remaining after evaluation (see Step 4).

### Step 2: Evaluate and Exclude

**Remove issues matching ANY exclusion criterion:**

1. **Major version dependency upgrades** — Issues whose title or body indicate a major version bump of a dependency (e.g., "upgrade Angular from 17 to 18", "migrate to RxJS 8"). Minor and patch updates are fine.
2. **Blocked dependency updates** — Issues where the body or comments indicate the update is blocked by conflicting peer dependencies, incompatible packages, or other dependency resolution failures.
3. **UI design required** — Issues that require new UI design work (mockups, wireframes, visual design decisions). Issues that implement an already-designed UI or make minor UI adjustments are fine.

### Step 3: Prioritize Remaining Issues

**Primary sort: Project status** (descending preference):

1. **In Progress** — already started, highest priority to continue
2. **This milestone** — committed work for the current release
3. **All other statuses** — only considered if no In Progress or This milestone issues remain

**Secondary sort (within the same status tier):**

Score each issue using these criteria, in descending order of importance:

1. **Security fixes** (HIGHEST) — Issues with security labels, or whose title/body mentions vulnerabilities, CVEs, security hardening, auth fixes, XSS, CSRF, injection, etc.
2. **Dependency patching** — Issues for minor/patch dependency updates that are not blocked by compatibility issues. Look for labels like `dependencies`, `deps`, or Dependabot/Renovate PRs.
3. **Blocking/prerequisite issues** — Issues that other issues depend on. Look for:
   - "blocked by #X" or "depends on #X" references in other issues pointing to this one
   - Labels like `blocker`, `priority`, `critical`
   - Issues referenced as prerequisites in other issue bodies
4. **Ease of implementation** (LOWEST priority criterion, used as tiebreaker) — Prefer issues that appear simpler:
   - Smaller scope described in the body
   - Labels like `good first issue`, `small`, `quick`
   - Clear, well-defined acceptance criteria
   - Fewer unknowns or open questions in comments

### Step 4: Present Results

Display the full prioritized list as a table:

```
## Candidate Issues for [branch-name]

Search: milestone=[version], project=[project-name or "none"]
Found: [N] issues ([M] excluded)

### Excluded Issues
| # | Title | Reason |
|---|-------|--------|
| 42 | Upgrade to Angular 19 | Major version upgrade |

### Prioritized Issues
| Rank | # | Title | Status | Priority | Priority Reason | Score |
|------|---|-------|--------|----------|-----------------|-------|
| 1 | 15 | Fix CSRF token validation | In Progress | Must Have | Security fix | S1 |
| 2 | 23 | Update lodash to 4.17.21 | This milestone | Must Have | Dep patch (CVE) | S1+D |
| 3 | 31 | Add input validation | This milestone | Should Have | Security + blocks #44 | S1+B |

### Recommendation

**Issue #[N]: [Title]**
[URL]

[2-3 sentence explanation of why this issue was selected, referencing the prioritization criteria]
```

**If no viable candidates remain in the current milestone** (all excluded or list is empty), ask the user before looking at the backlog:

> No actionable issues remain in the current milestone. Would you like me to look at backlog issues?

If the user agrees, fetch backlog issues and repeat Steps 2-4:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/gh-issues.py --status "Backlog"
```

### Step 5: Confirm and Execute

After presenting the recommendation, ask:

> Ready to work on Issue #[N]? (yes / pick a different one / just planning)

If the user confirms (or picks a different issue), you MUST perform these steps in order:

1. **FIRST ACTION — rename the session.** Before any analysis, planning, file reads, or other tool calls, emit the `/rename` slash command to retitle the session to `Working on #[N] [short title]`, where `[short title]` is the issue title condensed to ≤ 60 characters (preserve the issue's actual wording — do not paraphrase). This is mandatory: it is the very next thing you do after the user confirms, and it must happen before you start analyzing the issue, reading files, or planning.
   - Concretely: as the next action after confirmation, output the literal slash command on its own line so the harness picks it up:
     ```
     /rename Working on #142 fix CSRF token validation
     ```
   - If for any reason the rename does not appear to take effect, surface that to the user immediately rather than silently proceeding — do not assume it worked.
2. Analyze what needs to be done based on the issue details already fetched.
3. Create a plan and begin implementation following the project's development process.

### Step 6: Closing the Issue When Done

When the implementation work is complete and committed, how the issue gets closed depends on the branch the commit landed on:

- **Commit on `main`**: A `Closes #[N]` (or `Fixes #[N]`) trailer in the commit message is sufficient — GitHub auto-closes on push.
- **Commit on any other branch** (feature, `dev/x.y.z`, etc.): GitHub will NOT auto-close from non-default branches. You must explicitly close the issue:

  ```bash
  gh issue comment [N] --body "Resolved in <commit-sha-or-PR-link> on branch <branch>."
  gh issue close [N]
  ```

  Do this as part of session completion, not later. Check the current branch with `git branch --show-current` to decide which path applies.

---

Now execute this process.
