---
name: bump
version: 1.0.0
description: Update dependencies safely across Go, Python, and Node ecosystems. Use when the user asks to bump, update, or upgrade dependencies, packages, or deps; run a dependency bump/upgrade; fix Dependabot or security advisories; or refresh outdated packages. Triggers on phrasings like 'bump the deps', 'bump dependencies on <branch>', 'update packages on main', or 'run a dep upgrade'. Auto-detects ecosystems (Go/Python/Node), applies safe patch and minor updates with build, test, and lint validation, bisects failures to isolate bad packages, and surfaces a prioritized plan for major or held packages that need manual review.
---

# Bump Command

Analyze dependencies across all ecosystems, check for security vulnerabilities, auto-update safe packages, and produce a plan for packages that need manual attention.

## Overview

This command performs a controlled, multi-ecosystem dependency update:
1. Detects which ecosystems are present (Go, Python, Node) or uses the specified one
2. Manages branch state. When working from `main`, it creates a dedicated bump branch and runs the whole update there (never commits dependency bumps directly to `main`). On any other branch it works in place.
3. Loads exclusion rules from multiple sources
4. Refreshes package manager caches
5. Gathers security advisories, audit results, outdated packages, and GitHub context
6. Categorizes updates into safe (auto-apply) and needs-plan (manual review)
7. Applies safe updates (security fixes first)
8. Validates with build, test, and lint
9. If validation fails, bisects to isolate problematic packages
10. Commits successful updates
11. When working from `main`: pushes the bump branch, opens a pull request, monitors it until checks pass and it is mergeable, squash-merges it automatically, and deletes the branch
12. Presents a prioritized plan for remaining updates
13. Restores original branch and stash state

## Usage

```bash
/bump              # Auto-detect ecosystems, process all
/bump go           # Go ecosystem only
/bump python       # Python ecosystem only
/bump node         # Node.js ecosystem only
```

Aliases: `py` for python, `npm`/`pnpm`/`js`/`ts` for node.

Arguments:
- First positional arg: ecosystem name. If omitted, auto-detect all present ecosystems.
- If a specified ecosystem is not present in the project, display what was detected and exit.

## Process

### Phase 0: Parse Arguments and Detect Ecosystems

1. Parse the user's request for an ecosystem hint:
   - If the request mentions `go`, target Go only.
   - If the request mentions `python`, `py`, `pip`, or `uv`, target Python only.
   - If the request mentions `node`, `npm`, `pnpm`, `js`, or `ts`, target Node only.
   - If invoked via the `/bump` command wrapper, the user's arguments are passed as the skill's args — parse them the same way.
   - If no ecosystem hint is present, auto-detect all ecosystems.

2. Auto-detect ecosystems by checking for manifest files in the project root:

**Go detection:**
- Check for `go.mod` in the project root
- Check for `go.work` (Go workspace / multi-module)
- If `go.work` exists, list all workspace modules from it

**Python detection:**
- Check for `pyproject.toml`, `requirements.txt`, `requirements/*.txt`, `setup.py`
- Determine package manager variant:
  - If `uv` command is available AND (`uv.lock` exists OR `pyproject.toml` exists): use **uv**
  - Else if `requirements.txt` or `setup.py` exists: use **pip**
  - If both indicators exist, prefer uv

**Node detection:**
- Check for `package.json` in the project root
- Determine package manager variant:
  - If `pnpm-lock.yaml` exists: use **pnpm**
  - If `package-lock.json` exists: use **npm**
  - Also check the `"packageManager"` field in `package.json` for hints
  - If both lockfiles exist, prefer pnpm (warn about both being present)
- Check for workspace configuration:
  - `pnpm-workspace.yaml` for pnpm workspaces
  - `"workspaces"` field in `package.json` for npm workspaces

3. If an argument was given but that ecosystem is not detected:
   - Display which ecosystems WERE detected
   - Display: `Ecosystem "<arg>" not detected in this project.`
   - Exit

4. If multiple ecosystems detected and no argument given, display them and process all:
   ```
   Detected ecosystems:
     Go (go.mod)
     Python/uv (pyproject.toml + uv.lock)
     Node/pnpm (pnpm-lock.yaml)

   Processing all ecosystems.
   ```

### Phase 1: Branch Management

This phase decides **where** the bump happens and sets a mode that later phases depend on:

- **`MODE=pr`** — work is done on a freshly created bump branch off `main`, and integrated via a pull request (Phase 11). This is the mode whenever the effective working base is `main`.
- **`MODE=direct`** — work is committed directly to the current branch, with no pull request. This is the mode on any non-`main` branch the user chooses to stay on.

Record the chosen mode; Phases 10, 11, and 13 read it.

1. Check current branch:
   ```bash
   git rev-parse --abbrev-ref HEAD
   ```

2. If current branch is NOT `main`:
   - Display: `Current branch: <branch-name>`
   - Ask the user: "You're not on main. Would you like to switch to main before bumping dependencies?"
   - If user says **no**: set `MODE=direct` and continue on the current branch. (No bump branch, no PR — the rest of the run commits directly here, as before.)
   - If user says **yes**:
     a. Check for uncommitted changes:
        ```bash
        git status --porcelain
        ```
     b. If there are uncommitted changes:
        ```bash
        git stash push -m "bump-auto-stash"
        ```
        Record `STASH_APPLIED=true`.
     c. Switch to main and pull:
        ```bash
        git checkout main && git pull
        ```
     d. Record `ORIGINAL_BRANCH=<branch-name>` for cleanup in Phase 13.
     e. The effective base is now `main` — fall through to step 3 to set up `MODE=pr`.

3. If on `main` (either started there, or just switched in step 2):
   - Run `git pull` to ensure main is up to date.
   - Determine whether a pull request is possible by checking the remote (this reuses the GitHub detection from Phase 4a; you may run it now):
     ```bash
     git remote get-url origin 2>/dev/null
     ```
   - **If the remote is GitHub:** set `MODE=pr`. Create and switch to a dedicated bump branch so that `main` is never modified directly:
     ```bash
     BUMP_BRANCH="chore/bump-deps-$(date +%Y%m%d-%H%M%S)"
     git checkout -b "$BUMP_BRANCH"
     ```
     Record `BUMP_BRANCH` for Phases 11 and 13. Display: `Working on bump branch: <BUMP_BRANCH> (will open a PR into main)`.
   - **If the remote is NOT GitHub:** a pull request cannot be opened. Display: `Remote is not GitHub -- cannot open a pull request. Committing directly to main instead.` Set `MODE=direct` and continue on `main`. (This preserves the original direct-to-main behavior for non-GitHub repos.)

### Phase 2: Load Exclusion Rules

Merge exclusion rules from three sources. An exclusion means the package will NOT be auto-updated and will instead appear in the "Needs Plan" section.

**Source 1: Project CLAUDE.md**

Read the project's `CLAUDE.md` (check project root, then `.claude/CLAUDE.md`). Look for a section headed `## Bump Exclusions`. Parse any bullet points as package name patterns (glob-style). Example:

```markdown
## Bump Exclusions
- @angular/*
- @angular-devkit/*
- zone.js
- @antv/x6*
```

**Source 2: `.bump-config.json`**

Look for `.bump-config.json` in the project root. If found, parse it:

```json
{
  "exclude": ["@angular/*", "@antv/x6*"],
  "hold": {
    "typescript": "Waiting for ecosystem support for v6",
    "@antv/x6": "v3.x has breaking API changes"
  },
  "ecosystems": {
    "go": { "buildCommand": "make build", "testCommand": "make test-unit", "lintCommand": "make lint" },
    "node": { "buildCommand": "pnpm run build", "testCommand": "pnpm test", "lintCommand": "pnpm run lint:all" }
  }
}
```

- `exclude`: Array of package name patterns (glob) to never auto-update
- `hold`: Object mapping package names to human-readable reasons for delaying updates
- `ecosystems`: Optional per-ecosystem build/test/lint command overrides

**Source 3: Code Comments**

Scan manifest files for pinning comments:
- `go.mod`: Lines containing `// pinned:` after a require entry. Example: `github.com/foo/bar v1.2.3 // pinned: compat issue with v2`
- `package.json`: Look for `"//pinned"` keys or comments adjacent to version entries
- `pyproject.toml`: Lines containing `# pinned:` after a dependency. Example: `"requests>=2.28.0",  # pinned: v3 breaks auth module`
- `requirements.txt`: Lines containing `# pinned:` after a version pin. Example: `requests==2.28.0  # pinned: v3 breaks auth module`

**Merge and display:**

```
Exclusion rules loaded:
  From CLAUDE.md: @angular/*, @angular-devkit/*, zone.js
  From .bump-config.json: @antv/x6* (hold: v3.x has breaking API changes)
  From code comments: express (pinned: middleware compat)
  Total: 6 exclusion patterns
```

If no exclusions found from any source, display: `No exclusion rules found.`

### Phase 3: Cache Refresh

For each detected ecosystem, clear stale package metadata so we check against the latest available packages:

**Go:**
- No aggressive cache clean needed. The `go list -m -u all` command in Phase 4 fetches fresh data from the module proxy.

**Python/uv:**
```bash
uv cache clean
```

**Python/pip:**
```bash
pip cache purge
```

**Node/pnpm:**
```bash
pnpm store prune
pnpm cache delete *
npm cache clean --force
```

**Node/npm:**
```bash
npm cache clean --force
pnpm store prune 2>/dev/null || true
pnpm cache delete '*' 2>/dev/null || true
```

> **Note:** Both pnpm and npm maintain independent caches. Registry metadata (e.g., available versions) can be stale in either cache even when only one package manager is in use. Always clear both to ensure `pnpm view` / `npm view` return current data.

Display: `Cache refreshed for: <list of ecosystems>`

### Phase 4: Information Gathering

This is the core data collection phase. Collect data from multiple sources per ecosystem.

#### 4a. GitHub Integration (run once, shared across ecosystems)

Determine if the remote is GitHub:
```bash
git remote get-url origin 2>/dev/null
```

If the URL contains `github.com`, extract `OWNER/REPO` from the URL and set `IS_GITHUB=true`.

If `IS_GITHUB=true`, run the following checks:

**Search repo issues for dependency-related items:**
```bash
gh issue list --label "dependencies" --state open --json number,title,labels --limit 20
gh issue list --search "dependency OR upgrade OR bump OR vulnerability" --state open --json number,title --limit 20
```

**Check Dependabot alerts:**
```bash
gh api repos/OWNER/REPO/dependabot/alerts --jq '[.[] | select(.state=="open") | {summary: .security_advisory.summary, severity: .security_advisory.severity, ecosystem: .dependency.package.ecosystem, name: .dependency.package.name}]' 2>/dev/null
```

**Check dependency-labeled PRs:**
```bash
gh pr list --label "dependencies" --json number,title,headRefName --limit 20
```

If the remote is NOT GitHub, display:
```
Remote is not GitHub -- skipping GitHub-specific checks (issues, Dependabot).
```

Do not treat this as an error.

#### 4b. Go Ecosystem Checks

**Security vulnerabilities:**
```bash
govulncheck ./...
```
Parse the output for affected packages, CVE identifiers, and fix versions. If `govulncheck` is not installed, display: `govulncheck not found -- skipping Go vulnerability scan. Install with: go install golang.org/x/vuln/cmd/govulncheck@latest` and continue.

**Outdated packages:**
```bash
go list -m -u all 2>&1
```
Parse the output. Lines like `github.com/foo/bar v1.2.3 [v1.3.0]` indicate an update is available (the version in brackets is the latest). Lines without brackets are up to date.

**Replace directives:**
Read `go.mod` and identify all `replace` directives. These are **completely skipped** -- do not attempt to update, modify, or report on packages that are targets of replace directives.

**Go workspaces:**
If `go.work` exists, read it to identify all workspace modules. Run the above checks from the root (govulncheck and go list -m -u work across the workspace).

#### 4c. Python Ecosystem Checks

**Security audit (try in order, use first that succeeds):**

1. If `safety` is available:
   ```bash
   safety check --json
   ```
2. If `pip-audit` is available:
   ```bash
   pip-audit --format json
   ```
   Or with uv: `uv run pip-audit --format json`

If neither tool is available, display: `No Python security audit tool found -- skipping. Install safety: pip install safety` and continue.

**Outdated packages:**

If using uv:
```bash
uv pip list --outdated 2>/dev/null || uv run pip list --outdated --format json
```

If using pip:
```bash
pip list --outdated --format json
```

**Detect dependency format and record which files will be modified:**
- `pyproject.toml` with `[project.dependencies]`: primary modern format
- `requirements.txt`: legacy format, direct version pins
- `requirements/*.txt`: multiple requirement files (e.g., requirements/dev.txt, requirements/prod.txt)
- `setup.py`: legacy format
- `uv.lock`: will be regenerated automatically after updates

#### 4d. Node Ecosystem Checks

**Security audit:**

pnpm:
```bash
pnpm audit --json
```

npm:
```bash
npm audit --json
```

Parse the JSON output for advisories with severity, affected package, patched version, and CVE.

**Outdated packages:**

pnpm:
```bash
pnpm outdated --format json
```

npm:
```bash
npm outdated --json
```

Parse the JSON output. Key fields: `current` (installed version), `latest` (newest available), `wanted` (latest matching semver range in package.json), `dependencyType`.

**Check overrides/resolutions:**

Read `package.json` and extract:
- pnpm: `pnpm.overrides` section
- npm: `overrides` section

For each override entry, check if a newer patch/minor version is available:
```bash
npm view <package> version
```
or:
```bash
pnpm view <package> version
```

Skip overrides using complex selectors (e.g., `"wrap-ansi@9.0.1": "9.0.0"` -- these are targeted transitive dependency pins).

**Workspace handling:**
- pnpm: `pnpm outdated` and `pnpm audit` natively cover the entire workspace
- npm: Use `--workspaces` flag with outdated and audit commands

#### 4e. Changelog Research for Major/Minor Updates

For any package with a major or minor version update available, attempt to fetch changelog information. Only check GitHub releases -- do not perform web searches.

For packages hosted on GitHub (extract owner/repo from module path or registry metadata):
```bash
gh api repos/OWNER/REPO/releases/latest --jq '.tag_name + ": " + .body' 2>/dev/null
```

For Go modules, extract owner/repo from the module path (e.g., `github.com/foo/bar` -> `foo/bar`).

For npm packages, get the repository URL from:
```bash
npm view <package> repository.url
```

If the changelog fetch fails or the package is not on GitHub, skip gracefully. This information is supplementary, not required.

### Phase 5: Analysis and Categorization

For each ecosystem, categorize every dependency that has an available update:

**Category: Security Fix (auto-apply)**
- Resolves a known vulnerability (from govulncheck, safety, pnpm/npm audit, or Dependabot alerts)
- The fix is a patch or minor version bump
- NOT in the exclusion list
- Major version security fixes go to "Needs Plan" instead

**Category: Safe Update (auto-apply)**
- Patch version bump (e.g., `1.2.3` -> `1.2.5`)
- Minor version bump (e.g., `1.2.3` -> `1.5.0`)
- NOT in the exclusion list (from any source)
- NOT a major version change
- NOT a Go replace directive target
- No hold reason in `.bump-config.json`

**Category: Needs Plan (do NOT auto-apply)**
- Major version updates (e.g., `1.x.x` -> `2.x.x`)
- Packages matching any exclusion pattern
- Packages with a hold reason in `.bump-config.json`
- Packages with `// pinned:` or `# pinned:` comments
- Major version security fixes
- Packages where GitHub issues or Dependabot context indicates complications

**Category: Skipped**
- Go replace directive targets
- Up-to-date packages (no update available)

**Version comparison logic:**
- Parse versions as semver: `MAJOR.MINOR.PATCH`
- A major bump: target major > current major
- A minor bump: same major, target minor > current minor
- A patch bump: same major and minor, target patch > current patch
- For Go modules with `/vN` paths (e.g., `/v4` -> `/v5`), this is a major bump

**Exclusion pattern matching:**
- Exact match: `zone.js` matches only `zone.js`
- Prefix glob: `@angular/*` matches `@angular/core`, `@angular/router`, etc.
- Prefix glob: `@antv/x6*` matches `@antv/x6`, `@antv/x6-plugin-selection`, etc.

### Phase 6: Display Analysis

Present the analysis per ecosystem in tables. Example:

```
=== Go Ecosystem Analysis ===

Security Vulnerabilities:
-----------------------------------------
Severity   Package                          Current    Fix        CVE
-----------------------------------------
CRITICAL   github.com/foo/bar               v1.2.3     v1.2.5     CVE-2024-XXXXX
HIGH       github.com/baz/qux               v2.0.0     v2.0.3     CVE-2024-YYYYY
-----------------------------------------
Total: 2 packages

Safe Updates (will be applied):
-----------------------------------------
Package                          Current    Target     Type
-----------------------------------------
github.com/gin-gonic/gin         v1.10.0    v1.11.0    minor
golang.org/x/crypto              v0.46.0    v0.47.0    minor
golang.org/x/text                v0.21.0    v0.21.1    patch
-----------------------------------------
Total: 3 packages

Needs Plan (will NOT be auto-applied):
-----------------------------------------
Package                          Current    Latest     Reason
-----------------------------------------
github.com/jackc/pgx/v4          v4.18.3    v5.8.0     Major (v4 -> v5)
-----------------------------------------
Total: 1 package

Skipped: 2 replace directives
```

```
=== Node/pnpm Ecosystem Analysis ===

Security Fixes (will be applied):
-----------------------------------------
Severity   Package    Current   Patched   Source
-----------------------------------------
HIGH       qs         6.14.1    6.14.2    audit (override)
-----------------------------------------

Override Updates (will be applied):
-----------------------------------------
Package    Current   Target    Type       Notes
-----------------------------------------
hono       4.11.7    4.11.9    patch      exact pin
-----------------------------------------
Skipped overrides: 2 (targeted selectors: wrap-ansi@9.0.1, slice-ansi@7.1.1)

Safe Updates (will be applied):
-----------------------------------------
Package    Current   Target    Type
-----------------------------------------
rxjs       7.8.1     7.8.2     patch
marked     16.4.0    16.4.2    patch
eslint     9.38.0    9.39.2    minor
-----------------------------------------
Total: 3 packages

Needs Plan (will NOT be auto-applied):
-----------------------------------------
Package          Current   Latest    Reason
-----------------------------------------
@angular/core    20.2.0    21.0.0    Excluded (@angular/*, major)
typescript       5.8.0     6.0.0     Major version
-----------------------------------------
Total: 2 packages
```

Repeat for each ecosystem.

### Phase 7: Apply Safe Updates

Apply updates in priority order: security fixes first, then overrides, then safe updates.

#### Go

For each safe update:
```bash
go get github.com/package@vX.Y.Z
```

After all updates:
```bash
go mod tidy
```

If `go.work` is present:
```bash
go work sync
```

#### Python/uv

For `pyproject.toml` projects:
```bash
uv lock --upgrade-package package1 --upgrade-package package2
uv sync
```

For `requirements.txt` projects:
- Edit the `requirements.txt` file directly, updating version pins from `package==OLD` to `package==NEW`
- Then install:
  ```bash
  uv pip install -r requirements.txt
  ```

#### Python/pip

```bash
pip install package1==X.Y.Z package2==X.Y.Z
```

Then update `requirements.txt` if it exists:
- Edit the file directly, updating version pins

#### Node/pnpm

For security fixes that need overrides:
1. Update the version in `pnpm.overrides` in `package.json`
2. If the package also appears as a direct dependency, update that version too

For safe updates:
```bash
pnpm update package1 package2 package3
```

After all updates:
```bash
pnpm install
```

**Important:** Use `pnpm update` without `--latest` to respect semver ranges and only apply wanted versions. For packages that need to go beyond the semver range (when the range itself is the constraint), update the version range in `package.json` first, then run `pnpm install`.

#### Node/npm

For overrides:
1. Update the version in `overrides` in `package.json`

For safe updates:
```bash
npm update package1 package2 package3
```

After all updates:
```bash
npm install
```

### Phase 8: Build, Test, and Lint

Run the project's build, test, and lint commands. Determine which commands to use in this priority order:

1. **`.bump-config.json` ecosystems section**: If the config file has custom commands for this ecosystem, use those.

2. **Project CLAUDE.md**: Check for project-specific build/test/lint instructions in the project's CLAUDE.md file.

3. **Makefile**: If a Makefile exists, look for `build`, `test` (or `test-unit`), and `lint` targets.

4. **Package scripts**: Check `package.json` for `build`, `test`, `lint`, `lint:all` scripts.

5. **pyproject.toml**: Check for pytest, ruff, mypy configuration.

6. **Generic fallbacks per ecosystem:**

Go:
```bash
go build ./...
go test ./...
go vet ./...
```

Python/uv:
```bash
uv run pytest
uv run ruff check .
```

Python/pip:
```bash
pytest
ruff check . || flake8
```

Node/pnpm:
```bash
pnpm run build
pnpm test
pnpm run lint:all || pnpm run lint
```

Node/npm:
```bash
npm run build
npm test
npm run lint
```

**If build, test, AND lint all pass:** proceed to Phase 10 (Commit).

**If any step fails:** proceed to Phase 9 (Bisect).

### Phase 9: Failure Handling (Bisect)

If build or tests fail after applying all safe updates:

1. **Revert ALL changes:**
   ```bash
   git checkout -- .
   ```
   This restores all modified files to their pre-update state.

2. **Re-apply updates ONE BY ONE in priority order:**
   a. Security fixes first (most important to keep)
   b. Then patch updates
   c. Then minor updates

3. **For each individual update:**
   a. Apply the single update using the ecosystem-specific command
   b. Run the lockfile update (e.g., `go mod tidy`, `pnpm install`)
   c. Run build
   d. Run tests
   e. If build AND tests pass: **keep** this update, move to next
   f. If either fails: **revert** this specific update, record it as problematic, move to next

4. **After bisection completes, display:**
   ```
   Bisection Results:
     Successfully applied: 11 packages
     Caused failures: 2 packages
       - github.com/foo/bar v1.5.0: build error: cannot use X as Y
       - eslint v9.39.0: test failure: 3 tests in lint.spec.ts
   ```

5. Run lint on the final state (with all successful updates applied).

6. If lint fails, the lint failure is likely in the codebase and not caused by a dependency update. Report the lint failure but do not revert updates because of it.

### Phase 10: Commit

This commits to the **current working branch** — the bump branch when `MODE=pr`, or the user's branch when `MODE=direct`.

**No-change guard:** If no safe updates were applied (or bisection reverted everything), there is nothing to commit:
- If `MODE=pr`: do not create an empty PR. Switch back to `main` and delete the unused bump branch, then skip Phase 11:
  ```bash
  git checkout main
  git branch -D "$BUMP_BRANCH"
  ```
  Record that no PR was opened and continue to Phase 12 (plan) and Phase 13 (cleanup/report).
- If `MODE=direct`: report that there was nothing to update and continue to Phase 12/13.

Otherwise, after all validations pass (or after bisection stabilizes the safe subset):

1. **Stage all changes** -- include manifest files and lockfiles:
   ```bash
   git add go.mod go.sum pyproject.toml uv.lock requirements.txt package.json pnpm-lock.yaml package-lock.json
   ```
   Only add files that exist and were modified. Also add any `requirements/*.txt` files if they were updated.

2. **Compose a detailed commit message** listing every updated package, grouped by ecosystem:
   ```
   chore(deps): bump dependencies

   Go:
   - github.com/gin-gonic/gin v1.10.0 -> v1.11.0
   - golang.org/x/crypto v0.46.0 -> v0.47.0

   Node/pnpm:
   - rxjs 7.8.1 -> 7.8.2
   - eslint 9.38.0 -> 9.39.2

   Security fixes:
   - github.com/foo/bar v1.2.3 -> v1.2.5 (CVE-2024-XXXXX)
   - qs 6.14.1 -> 6.14.2 (HIGH severity)

   Reverted (caused build/test failures):
   - github.com/baz/qux v2.0.0 (build error)
   ```

3. **Commit:**
   ```bash
   git commit -m "<message>"
   ```

### Phase 11: Pull Request Flow (MODE=pr only)

**Skip this entire phase when `MODE=direct`.** In direct mode the commit from Phase 10 is the final integration step — go straight to Phase 12.

When `MODE=pr` and a commit was produced, push the bump branch, open a PR, monitor it until it is ready, then squash-merge and clean up.

**Step 1: Push the bump branch**

```bash
git push -u origin "$BUMP_BRANCH"
```

If the push fails because of an inaccessible SSH key (e.g. a required physical touch was not provided), do **not** attempt to work around it — report the failure, leave the branch and commit intact locally, and stop the PR flow. The user can push and open the PR manually.

**Step 2: Open the pull request**

Reuse the Phase 10 commit message body as the PR body so the PR lists every updated package and security fix.

```bash
gh pr create \
  --base main \
  --head "$BUMP_BRANCH" \
  --title "chore(deps): bump dependencies" \
  --body "<commit message body>"
```

Capture the PR number/URL from the output. Display: `Opened PR #<number>: <url>`.

**Step 3: Monitor until ready to merge**

The PR is "ready to merge" when its required status checks have **passed** AND it is in a mergeable state (no conflicts, no blocking required review).

1. Wait for checks to complete:
   ```bash
   gh pr checks <number> --watch --interval 30
   ```
   - `gh pr checks` exits non-zero if any required check **fails**, and reports `no checks` when the repo has none configured (treat "no checks" as nothing to wait on, not as an error).

2. Confirm the merge state once checks settle:
   ```bash
   gh pr view <number> --json state,mergeable,mergeStateStatus,reviewDecision
   ```
   - Ready: `mergeable` is `MERGEABLE` and `mergeStateStatus` is `CLEAN` (or `UNSTABLE` only due to non-required checks).
   - Not ready: any of failing checks, `mergeStateStatus` of `DIRTY`/`BLOCKED`/`BEHIND`, or `reviewDecision` of `REVIEW_REQUIRED`.

**Step 4: Handle a not-ready PR — stop and report (do NOT merge)**

If checks fail, never complete, or the PR is otherwise not mergeable (conflicts, required review pending), **stop here**. Do not merge and do not delete anything. Leave the branch and the open PR in place so the user can inspect and resolve them. Display a clear report, e.g.:

```
PR #<number> is not ready to merge -- stopping.
  Reason: <failing check name(s) / merge conflict / review required>
  PR: <url>
The bump branch and PR have been left in place for manual resolution.
```

Then skip Steps 5-6, leave `MODE=pr` state as-is, and proceed to Phase 12 (plan). In Phase 13, because the PR is still open, do **not** delete the bump branch; just restore the user's original branch/stash if applicable.

**Step 5: Merge automatically (squash)**

Once the PR is ready, merge it without asking for confirmation, deleting the remote branch as part of the merge:

```bash
gh pr merge <number> --squash --delete-branch
```

Display: `Merged PR #<number> (squash) and deleted remote branch.`

**Step 6: Local cleanup of the bump branch**

```bash
git checkout main
git pull
git branch -D "$BUMP_BRANCH"
```

`git pull` fast-forwards `main` to include the squash-merged commit. Use `-D` (force delete) because the squash merge leaves the branch's individual commits unreachable, so `git branch -d` would refuse. Record that the PR was merged for the Phase 13 report.

### Phase 12: Plan for Remaining Updates

For all packages categorized as "Needs Plan", produce a prioritized action plan:

**Priority 1: Security Updates Requiring Major Version Changes**

These are the most urgent. Example:
```
1. github.com/jackc/pgx/v4 v4.18.3 -> v5.8.0
   MAJOR version change (v4 -> v5) -- contains fix for CVE-2024-XXXXX (HIGH)
   Changelog: <summary from GitHub releases>
   Breaking changes: Connection API redesigned, pool management moved to pgxpool
   Recommendation: Create a feature branch, update import paths, test thoroughly
```

**Priority 2: Ecosystem-Coordinated Updates**

Packages that should be updated together (e.g., Angular ecosystem). Example:
```
2. Angular ecosystem (update together):
   @angular/core 20.2.0 -> 21.0.0
   @angular/material 20.1.0 -> 20.2.14
   @angular/router 20.2.0 -> 21.0.0
   Recommendation: Use `ng update` on a feature branch. Review https://angular.dev/update-guide
```

**Priority 3: Major Version Updates (no security implications)**

Lower urgency major updates. Example:
```
3. typescript 5.8.0 -> 6.0.0
   No security implications
   Changelog: <summary>
   Recommendation: Test on a feature branch, check ecosystem compatibility
```

**Priority 4: Held Packages**

Packages with explicit hold reasons. Example:
```
4. @antv/x6 2.19.2 -> 3.0.0
   Hold reason: v3.x has breaking API changes (from .bump-config.json)
   Recommendation: Defer until refactoring is planned
```

Include changelog summaries where they were successfully fetched in Phase 4e. If no changelog was available, note that.

### Phase 13: Cleanup and Final Report

**Step 1: Reconcile the bump branch (MODE=pr only)**

By the time this phase runs in `MODE=pr`, the bump branch has already been handled by an earlier phase. Confirm the expected end state and do nothing further to it here:
- **PR merged** (Phase 11 Step 6): the bump branch was already deleted locally and remotely, and `main` was fast-forwarded. The current branch is `main`.
- **PR left open** (Phase 11 Step 4, not ready): the bump branch and PR remain on purpose. Do **not** delete them.
- **No commit produced** (Phase 10 no-change guard): the empty bump branch was already deleted and the current branch is `main`.

In `MODE=direct`, there is no bump branch to reconcile.

**Step 2: Restore branch state**

If the user switched to main from another branch (`ORIGINAL_BRANCH` is set):
```bash
git checkout ORIGINAL_BRANCH
```

**Important:** This MUST happen BEFORE the stash pop. `git stash pop` applies changes to the *current* branch.

**Step 3: Restore stashed changes**

If `STASH_APPLIED=true`:
```bash
git stash pop
```

This restores the user's uncommitted changes to their original branch.

**Step 4: Display final summary**

```
=== Bump Complete ===

Updates Applied:
  Go: 12 packages updated (2 security fixes)
  Python/uv: 5 packages updated (0 security fixes)
  Node/pnpm: 15 packages updated (1 security fix)
  Total: 32 packages updated

Commit: abc1234 chore(deps): bump dependencies
Pull Request: #42 merged (squash) -- branch chore/bump-deps-20260623-101500 deleted

Reverted During Bisection: 2 packages
  - github.com/foo/bar v1.5.0: build error
  - eslint v9.39.0: test failure

Remaining (needs manual attention): 6 packages
  2 security-related major updates (Priority 1)
  1 ecosystem-coordinated update group (Priority 2)
  2 major version updates (Priority 3)
  1 held package (Priority 4)

Build: PASSED
Tests: PASSED
Lint: PASSED
```

The `Pull Request:` line reflects the actual outcome:
- `#<n> merged (squash) -- branch <name> deleted` when the PR was merged.
- `#<n> OPEN -- not ready to merge (<reason>); branch <name> left in place` when Phase 11 stopped.
- `none (committed directly to <branch>)` in `MODE=direct`.
- Omit the line entirely if no changes were committed.

## Error Handling

- **Tool not installed** (govulncheck, safety, pip-audit): Skip that specific check, display a note with install instructions, and continue. Never fail the entire command because one optional tool is missing.
- **Security audit command fails**: Report the error, continue with outdated checks. Audit failure should not block dependency updates.
- **GitHub API calls fail** (rate limit, auth issues, not GitHub): Skip gracefully with a note. GitHub checks are supplementary.
- **Build/test fails after updates**: Enter bisect mode (Phase 9). Never leave the project in a broken state.
- **ALL packages fail during bisection**: Revert everything completely, report that no updates could be safely applied, still display the plan for manual updates.
- **Git operations fail** (stash, checkout): Report the error and stop. Do not continue if git state is uncertain.
- **Network errors on package registry**: Retry once, then report and skip that check.
- **Lint fails**: Report the failure but do not revert dependency updates because of it. Lint failures are often pre-existing and unrelated to dependency changes.
- **`git push` fails (e.g. inaccessible SSH key)**: Do not attempt to work around it. Leave the local bump branch and commit intact, report the failure, and stop the PR flow so the user can push and open the PR manually.
- **`gh` not installed or not authenticated**: The PR flow cannot run. Report it, leave the committed bump branch in place, and stop the PR flow (skip merge/cleanup). Suggest `gh auth login`.
- **PR checks fail or never complete, or PR is not mergeable** (conflicts, required review): Stop and report (Phase 11 Step 4). Never merge a not-ready PR, and leave the branch and open PR in place for manual resolution.
- **`gh pr merge` fails**: Report the error, leave the PR open and the branch in place, and stop. Do not delete the branch if the merge did not succeed.

## Implementation Notes

1. **Transitive dependencies**: Direct dependency tools (`go list -m -u`, `pnpm outdated`) show direct dependencies. Transitive dependency vulnerabilities are caught by audit tools (`govulncheck`, `pnpm audit`, `safety`). For Node, transitive dependency versions can be pinned via overrides.

2. **Lockfile changes**: Lockfiles (`go.sum`, `pnpm-lock.yaml`, `package-lock.json`, `uv.lock`) will be updated. This is expected and should be committed.

3. **Go replace directives**: Always skip. Replace directives are intentional project-specific overrides (local modules, forks, etc.) and must never be auto-modified.

4. **Go workspace modules**: When `go.work` exists, `govulncheck ./...` and `go list -m -u all` work across the workspace. After updates, run `go work sync` to keep the workspace consistent.

5. **Coordinated ecosystem updates**: Some packages must be updated together (e.g., Angular core + material + router). These are identified by exclusion patterns and grouped in the plan.

6. **Dual entries**: Some packages appear both as a direct dependency and as an override (e.g., `hono` in pnpm). When updating these, both entries must be updated together to avoid version conflicts.

7. **Override selector syntax**: Overrides using the `package@version` selector format (e.g., `"wrap-ansi@9.0.1": "9.0.0"`) target specific transitive resolution paths. These should not be auto-bumped -- they require manual analysis.

8. **Python dependency formats**: The command adapts to whichever format the project uses. For `pyproject.toml`, edit the `[project.dependencies]` and `[dependency-groups]` sections. For `requirements.txt`, edit version pins directly. For `uv.lock`, it regenerates automatically when running `uv lock`.

9. **Commit message**: The commit message lists every package that was updated with old and new versions, grouped by ecosystem. Security fixes are called out separately with CVE identifiers.

10. **Branch restore order**: When restoring state after completion, always checkout the original branch FIRST, then pop the stash. This ensures stashed changes are applied to the correct branch.

11. **Main is never bumped directly (on GitHub repos)**: When the effective base is `main` and the remote is GitHub, the bump runs on a dedicated `chore/bump-deps-<timestamp>` branch and is integrated only through a pull request. `main` is updated solely by merging that PR. The only time changes land on `main` without a PR is when the remote is not GitHub (no PR mechanism available), in which case the original direct-to-main behavior is preserved.

12. **Squash merge + force delete**: The PR is squash-merged (`gh pr merge --squash`), which collapses the bump branch's commits into one new commit on `main`. Because the branch's original commits then become unreachable, the local branch must be removed with `git branch -D` (force) — `git branch -d` would refuse, wrongly believing the branch is unmerged.

13. **Automatic merge, conservative on failure**: A ready PR (checks passed, mergeable, no required review pending) is squash-merged automatically without confirmation. A not-ready PR is never merged — the branch and PR are left in place and the user is told why. This asymmetry keeps the happy path hands-off while never forcing a questionable merge.

---

Now execute this process.
