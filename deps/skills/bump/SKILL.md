---
name: bump
version: 2.0.0
description: Update dependencies safely across Go, Python, and Node ecosystems. Use when the user asks to bump, update, or upgrade dependencies, packages, or deps; run a dependency bump/upgrade; fix Dependabot or security advisories; or refresh outdated packages. Triggers on phrasings like 'bump the deps', 'bump dependencies on <branch>', 'update packages on main', or 'run a dep upgrade'. Auto-detects ecosystems (Go/Python/Node), applies safe patch and minor updates with build, test, and lint validation, bisects failures to isolate bad packages, and surfaces a prioritized plan for major or held packages that need manual review.
---

# Bump Command

Analyze dependencies across all ecosystems, check for security vulnerabilities, auto-update safe packages, and produce a plan for packages that need manual attention.

## Architecture

This skill is a **thin orchestrator**. All provider mechanics — detecting ecosystems, listing outdated packages, running audits, querying GitHub, applying updates, validating, and driving PRs — live in the `bumplib` CLI and its adapters. The skill's job is the parts that require judgment and git-generic flow control: branch management, categorization display, changelog research, bisect strategy, the prioritized plan, and the final report.

**The CLI.** Every provider call goes through one command:

```bash
uv run "$CLAUDE_PLUGIN_ROOT/scripts/bump.py" <axis> <name> <verb> [args...]
```

- `$CLAUDE_PLUGIN_ROOT/scripts/bump.py` is the script (falls back to `python3 <path>/scripts/bump.py` if `uv` is unavailable). Below this is written as `bump.py` for brevity.
- **Axes:** `ecosystem` (`go`|`python`|`node`), `codeHost` (`github`|`none`), `issueTracker` (`github`|`none`).
- Each verb prints **exactly one JSON value** to stdout. Output shapes are defined in `reference/contracts.md` — read it to know what each verb returns. Adapters **degrade gracefully**: a missing tool (`gh`, `govulncheck`, `pip-audit`, …) yields the empty contract shape (`[]`, empty `Context`, `{"error": ...}`) rather than an error.
- The special `none` adapter is a no-op returning fixed empty shapes; use it whenever an axis resolves to `none`.

Save each verb's JSON to a temp file as you gather it, so later phases can re-read it without re-running the command.

## Usage

```bash
/bump              # Auto-detect ecosystems, process all
/bump go           # Go ecosystem only
/bump python       # Python ecosystem only
/bump node         # Node.js ecosystem only
```

Aliases: `py` → python; `npm`/`pnpm`/`js`/`ts` → node.

- First positional arg: ecosystem name. If omitted, auto-detect all present ecosystems.
- If a specified ecosystem is not present in the project, display what was detected and exit.

## Process

### Phase 0: Parse Arguments and Detect Ecosystems

1. Parse the user's request for an ecosystem hint:
   - `go` → Go only. `python`/`py`/`pip`/`uv` → Python only. `node`/`npm`/`pnpm`/`js`/`ts` → Node only.
   - If invoked via the `/bump` wrapper, the user's arguments are the skill's args — parse them the same way.
   - No hint → auto-detect all ecosystems.

2. Detect each candidate ecosystem via the CLI:
   ```bash
   bump.py ecosystem go detect
   bump.py ecosystem python detect
   bump.py ecosystem node detect
   ```
   Keep every ecosystem whose `detect` returns `present: true`. The dict also carries `packageManager` (e.g. `uv`/`pip`, `pnpm`/`npm`; empty for Go) and, for Go, `workspace` (true when `go.work` exists). If an explicit ecosystem arg was given, run only that one.

3. If an argument was given but that ecosystem's `detect` reports `present: false`:
   - Display which ecosystems WERE detected, then: `Ecosystem "<arg>" not detected in this project.` and exit.

4. If multiple ecosystems detected and no argument given, display and process all:
   ```
   Detected ecosystems:
     Go (go.mod)
     Python/uv (pyproject.toml + uv.lock)
     Node/pnpm (pnpm-lock.yaml)

   Processing all ecosystems.
   ```

### Phase 1: Resolve Axes (code host + issue tracker)

Determine which non-ecosystem adapters to use. This mirrors `config.resolve_adapter`:

1. Read `.bump-config.json` from the project root if present.
2. Get the remote: `git remote get-url origin 2>/dev/null`.
3. For each of `codeHost` and `issueTracker`:
   - If `.bump-config.json` sets the axis explicitly (e.g. `"codeHost": "github"`), use that value.
   - Else if the remote URL contains `github.com`, use `github`.
   - Else use `none`.

Record `HOST` (codeHost adapter) and `TRACKER` (issueTracker adapter) for later phases. `none` on either axis means the corresponding gather calls return empty shapes — no special-casing needed.

### Phase 2: Branch Management

This phase decides **where** the bump happens and sets a mode later phases depend on:

- **`MODE=pr`** — work on a fresh bump branch off `main`, integrated via a pull request (Phase 9). Used whenever the effective working base is `main` **and** `HOST` is `github`.
- **`MODE=direct`** — work committed directly to the current branch, no pull request.

Record the chosen mode; Phases 7, 9, and 11 read it.

1. Current branch: `git rev-parse --abbrev-ref HEAD`.

2. If current branch is NOT `main`:
   - Display: `Current branch: <branch-name>`.
   - Ask: "You're not on main. Would you like to switch to main before bumping dependencies?"
   - **No** → set `MODE=direct`, continue on the current branch (no bump branch, no PR; commits land here).
   - **Yes**:
     a. Check uncommitted changes: `git status --porcelain`.
     b. If any: `git stash push -m "bump-auto-stash"`; record `STASH_APPLIED=true`.
     c. `git checkout main && git pull`.
     d. Record `ORIGINAL_BRANCH=<branch-name>` for cleanup in Phase 11.
     e. Effective base is now `main` — fall through to step 3.

3. If on `main` (started there or just switched):
   - `git pull` to bring main up to date.
   - **If `HOST` is `github`** (from Phase 1): set `MODE=pr`. Create a dedicated bump branch so `main` is never modified directly:
     ```bash
     BUMP_BRANCH="chore/bump-deps-$(date +%Y%m%d-%H%M%S)"
     git checkout -b "$BUMP_BRANCH"
     ```
     Record `BUMP_BRANCH` for Phases 9 and 11. Display: `Working on bump branch: <BUMP_BRANCH> (will open a PR into main)`.
   - **If `HOST` is not `github`:** a PR cannot be opened. Display: `Remote is not GitHub -- cannot open a pull request. Committing directly to main instead.` Set `MODE=direct`, continue on `main`.

### Phase 3: Cache Refresh

For each detected ecosystem, clear stale package metadata so checks hit the latest versions:

```bash
bump.py ecosystem <eco> cache-clear
```

Returns `{"warnings": [...]}` (no-op for Go). **Config override:** if `.bump-config.json` sets `ecosystems.<eco>.cacheClear` to a non-empty string, run that shell command **instead** of the CLI call (the CLI only runs the adapter default).

Display: `Cache refreshed for: <list of ecosystems>`.

### Phase 4: Gather

Collect data from every source. Save each JSON payload to a temp file.

**Per ecosystem:**
```bash
bump.py ecosystem <eco> outdated    # -> [UpdateRecord, ...]
bump.py ecosystem <eco> audit       # -> [Advisory, ...]
```

**Once, shared across ecosystems** (using `HOST`/`TRACKER` from Phase 1):
```bash
bump.py codeHost   <HOST>    alerts   # -> [Advisory, ...]  (Dependabot; [] if gh missing/none)
bump.py codeHost   <HOST>    prs      # -> Context(pullRequests=[...])
bump.py issueTracker <TRACKER> issues # -> Context(issues=[...])
```

If `HOST`/`TRACKER` is `none`, these return empty shapes — no error, nothing to skip.

**Merge advisories:** the full advisory set = (union of every ecosystem's `audit`) ∪ (`codeHost alerts`). De-dupe by package name where sensible. Keep the issues/PRs context for the plan and to flag complications in Phase 5.

### Phase 5: Categorize and Display

Gather the exclusion/skip inputs the way the original skill did, then let the CLI categorize:

1. **Exclusions & holds** — the CLI's categorize path already merges `## Bump Exclusions` bullets from `CLAUDE.md` (root or `.claude/CLAUDE.md`) and `exclude`/`hold` from `.bump-config.json` (via `config.merged_exclusions`). You do **not** need to pass those; they are read from disk.
2. **Pinned packages** — scan manifests for pin comments and collect the package names:
   - `go.mod`: `// pinned:` after a require entry.
   - `package.json`: `"//pinned"` keys / comments adjacent to a version.
   - `pyproject.toml` / `requirements.txt`: `# pinned:` after a dependency.
   Pass these names in the payload's `exclude` list (they merge with the disk exclusions).
3. **Go replace targets** — read each `go.mod` and collect the module paths that are targets of `replace` directives. Pass them as `replaceTargets`; the categorizer routes them to **Skipped** (never updated or reported).

Build a single payload combining all ecosystems and pipe it to the categorize path:

```bash
echo '{
  "updates":        [ ...every ecosystem'\''s outdated records... ],
  "advisories":     [ ...merged advisories from Phase 4... ],
  "exclude":        [ ...pinned package names... ],
  "replaceTargets": [ ...go replace target module paths... ]
}' | bump.py categorize
```

`bump.py categorize` reads the payload JSON from stdin (optional `--root DIR`, default `.`), merges disk exclusions/holds, and prints a `Categories` value with four buckets: `securityFixes`, `safe`, `needsPlan`, `skipped` (each an UpdateRecord with an added `reason`, and `advisory` when one applies). See `reference/contracts.md`.

**Categorization rules** (enforced by the CLI, summarized for the reader):
- **Security Fix** (auto-apply): patch/minor bump that resolves an advisory, not excluded/held/pinned. Major security fixes go to Needs Plan.
- **Safe Update** (auto-apply): patch or minor bump, not excluded/held/pinned, not a major, not a replace target.
- **Needs Plan** (never auto-apply): major bumps, excluded/held/pinned packages, major security fixes, packages GitHub issues/Dependabot context flag as complicated.
- **Skipped**: replace-directive targets and up-to-date packages.

**Display** the four categories per ecosystem using the original table formats:

```
=== Go Ecosystem Analysis ===

Security Vulnerabilities:
-----------------------------------------
Severity   Package                          Current    Fix        CVE
-----------------------------------------
CRITICAL   github.com/foo/bar               v1.2.3     v1.2.5     CVE-2024-XXXXX
-----------------------------------------
Total: 1 package

Safe Updates (will be applied):
-----------------------------------------
Package                          Current    Target     Type
-----------------------------------------
github.com/gin-gonic/gin         v1.10.0    v1.11.0    minor
golang.org/x/text                v0.21.0    v0.21.1    patch
-----------------------------------------
Total: 2 packages

Needs Plan (will NOT be auto-applied):
-----------------------------------------
Package                          Current    Latest     Reason
-----------------------------------------
github.com/jackc/pgx/v4          v4.18.3    v5.8.0     Major (v4 -> v5)
-----------------------------------------
Total: 1 package

Skipped: 2 replace directives
```

Repeat per ecosystem (Node's format additionally distinguishes override updates and security fixes — keep those sub-tables when the data has them). If no exclusions were found from any source, note `No exclusion rules found.`

### Phase 6: Changelog Research (Needs-Plan majors)

For each Needs-Plan **major** update, attempt to fetch changelog context — **GitHub releases only**, no web searches. Extract `owner/repo` from the module path (Go `github.com/foo/bar` → `foo/bar`) or registry metadata, then:

```bash
gh api repos/OWNER/REPO/releases/latest --jq '.tag_name + ": " + .body' 2>/dev/null
```

If the fetch fails or the package is not on GitHub, skip gracefully — this is supplementary, used to enrich the Phase 10 plan.

### Phase 7: Apply, Validate, and Bisect

Apply the auto-apply buckets (security fixes first, then safe updates) per ecosystem, then validate. Build **fully-qualified specs** for `apply`:

- **Go:** `module@vX.Y.Z` (e.g. `github.com/foo/bar@v1.2.5`)
- **Node:** `name@X.Y.Z` (scoped: `@scope/name@X.Y.Z`)
- **Python (uv):** `name==X.Y.Z` (pip variant accepts the same spec form)

**Apply all at once, then validate:**
```bash
bump.py ecosystem <eco> apply <spec> <spec> ...   # -> {"applied":[...], "filesModified":[...]}
bump.py ecosystem <eco> validate                   # -> {"build":"pass"/"fail", "build_output":..., "test":..., "lint":...}
```
`validate` returns per-step `pass`/`fail` plus truncated `_output` (Go/Node run build+test+lint; Python runs test+lint only — no build step). **Config override:** if `.bump-config.json` sets `ecosystems.<eco>.{build,test,lint}` commands, run those shell commands directly instead of `validate` (the CLI's `validate` uses only the adapter defaults).

**If build and test both pass:** proceed to Phase 8 (Commit). (A lint-only failure does **not** trigger bisect — see below.)

**If build or test fails — bisect:**
1. Revert everything: `git checkout -- .`.
2. Re-apply updates ONE AT A TIME in priority order (security fixes, then patch, then minor). For each single spec:
   ```bash
   bump.py ecosystem <eco> apply <one spec>
   bump.py ecosystem <eco> validate
   ```
   - If build and test pass: **keep** it, move on.
   - If either fails: **revert that spec** (`git checkout -- .` then re-apply the kept set, or re-apply the good subset), record it as problematic, move on.
3. Report:
   ```
   Bisection Results:
     Successfully applied: 11 packages
     Caused failures: 2 packages
       - github.com/foo/bar v1.5.0: build error: cannot use X as Y
       - eslint v9.39.0: test failure: 3 tests in lint.spec.ts
   ```
4. Run `validate` once more on the final kept set. **A lint failure is reported but never reverts updates** — lint failures are usually pre-existing and unrelated to the bump.

### Phase 8: Commit

Commits to the **current working branch** — the bump branch when `MODE=pr`, the user's branch when `MODE=direct`.

**No-change guard:** if nothing was applied (or bisection reverted everything):
- `MODE=pr`: do not create an empty PR. `git checkout main && git branch -D "$BUMP_BRANCH"`; record that no PR was opened; skip Phase 9; continue to Phases 10/11.
- `MODE=direct`: report nothing to update; continue to Phases 10/11.

Otherwise:

1. **Stage** manifests + lockfiles that exist and were modified (use the `filesModified` lists from `apply`): `go.mod go.sum pyproject.toml uv.lock requirements.txt package.json pnpm-lock.yaml package-lock.json` and any `requirements/*.txt`.
2. **Compose** a detailed message listing every updated package grouped by ecosystem, security fixes called out with CVE/severity, and a "Reverted (caused build/test failures)" section if bisect dropped any:
   ```
   chore(deps): bump dependencies

   Go:
   - github.com/gin-gonic/gin v1.10.0 -> v1.11.0

   Node/pnpm:
   - eslint 9.38.0 -> 9.39.2

   Security fixes:
   - qs 6.14.1 -> 6.14.2 (HIGH severity)

   Reverted (caused build/test failures):
   - github.com/baz/qux v2.0.0 (build error)
   ```
3. `git commit -m "<message>"`.

### Phase 9: Pull Request Flow (MODE=pr only)

**Skip entirely when `MODE=direct`** — the Phase 8 commit is the final integration step; go to Phase 10.

When `MODE=pr` and a commit was produced:

**Step 1 — Push the bump branch:**
```bash
git push -u origin "$BUMP_BRANCH"
```
If the push fails because of an inaccessible SSH key (e.g. a required physical touch was not provided), **do not work around it** — report the failure, leave the branch and commit intact locally, and stop the PR flow. The user can push and open the PR manually.

**Step 2 — Open the PR** (reuse the Phase 8 commit body as the PR body):
```bash
bump.py codeHost <HOST> open-pr "$BUMP_BRANCH" "chore(deps): bump dependencies" "<commit message body>"
```
Returns `{"ok": bool, "output": str}`. If `ok` is false (gh missing or not authenticated, command failed): report it, leave the committed bump branch in place, and stop the PR flow (skip merge/cleanup). Suggest `gh auth login`. On success, capture the PR number/URL from `output` and display `Opened PR #<number>: <url>`.

**Step 3 — Monitor until ready:**
```bash
bump.py codeHost <HOST> pr-status <number>   # -> {"state","mergeable","mergeStateStatus","reviewDecision"} or {"error": ...}
```
Poll until checks settle. The PR is **ready** when `mergeable` is `MERGEABLE` and `mergeStateStatus` is `CLEAN` (or `UNSTABLE` only due to non-required checks). It is **not ready** on failing checks, `mergeStateStatus` of `DIRTY`/`BLOCKED`/`BEHIND`, `reviewDecision` of `REVIEW_REQUIRED`, or an `{"error": ...}` response. Treat "no checks configured" as nothing to wait on, not a failure.

**Step 4 — Not ready → stop and report (do NOT merge):**
If checks fail, never complete, or the PR is otherwise not mergeable, **stop**. Do not merge, do not delete anything. Leave the branch and open PR in place:
```
PR #<number> is not ready to merge -- stopping.
  Reason: <failing check(s) / merge conflict / review required>
  PR: <url>
The bump branch and PR have been left in place for manual resolution.
```
Skip Steps 5–6, proceed to Phase 10. In Phase 11, because the PR is still open, do **not** delete the bump branch; just restore the user's original branch/stash.

**Step 5 — Ready → merge automatically (squash), no confirmation:**
```bash
bump.py codeHost <HOST> merge-pr <number>   # -> {"ok": bool, "output": str}; squash-merges and deletes the remote branch
```
If `ok` is false, report the error, leave the PR open and the branch in place, and stop (do not delete the branch). On success: `Merged PR #<number> (squash) and deleted remote branch.`

**Step 6 — Local cleanup:**
```bash
git checkout main && git pull && git branch -D "$BUMP_BRANCH"
```
`git pull` fast-forwards `main` to include the squash-merged commit; `-D` is required because the squash leaves the branch's individual commits unreachable. Record that the PR was merged for Phase 11.

### Phase 10: Plan for Remaining Updates

For all Needs-Plan packages, produce a prioritized action plan (enrich with the Phase 6 changelogs where available):

**Priority 1 — Security updates requiring major version changes** (most urgent):
```
1. github.com/jackc/pgx/v4 v4.18.3 -> v5.8.0
   MAJOR version change (v4 -> v5) -- contains fix for CVE-2024-XXXXX (HIGH)
   Changelog: <summary from GitHub releases>
   Breaking changes: <from changelog>
   Recommendation: feature branch, update import paths, test thoroughly
```

**Priority 2 — Ecosystem-coordinated updates** (packages to update together, e.g. Angular):
```
2. Angular ecosystem (update together):
   @angular/core 20.2.0 -> 21.0.0
   @angular/router 20.2.0 -> 21.0.0
   Recommendation: `ng update` on a feature branch; review https://angular.dev/update-guide
```

**Priority 3 — Major version updates (no security implications).**

**Priority 4 — Held packages** (explicit hold reasons from `.bump-config.json`).

Note where no changelog was available.

### Phase 11: Cleanup and Final Report

**Step 1 — Reconcile the bump branch (MODE=pr only).** By now the branch was already handled:
- **PR merged** (Phase 9 Step 6): branch already deleted locally+remotely, `main` fast-forwarded, current branch is `main`.
- **PR left open** (Phase 9 Step 4): branch and PR remain on purpose — do **not** delete.
- **No commit** (Phase 8 no-change guard): empty bump branch already deleted, current branch is `main`.

In `MODE=direct` there is no bump branch to reconcile.

**Step 2 — Restore branch state.** If `ORIGINAL_BRANCH` is set: `git checkout "$ORIGINAL_BRANCH"`. This MUST happen **before** the stash pop (`git stash pop` applies to the current branch).

**Step 3 — Restore stashed changes.** If `STASH_APPLIED=true`: `git stash pop`.

**Step 4 — Final summary:**
```
=== Bump Complete ===

Updates Applied:
  Go: 12 packages updated (2 security fixes)
  Node/pnpm: 15 packages updated (1 security fix)
  Total: 27 packages updated

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
- `#<n> merged (squash) -- branch <name> deleted` when merged.
- `#<n> OPEN -- not ready to merge (<reason>); branch <name> left in place` when Phase 9 stopped.
- `none (committed directly to <branch>)` in `MODE=direct`.
- Omit the line entirely if no changes were committed.

## Error Handling

- **Optional tool not installed** (`govulncheck`, `safety`, `pip-audit`, `gh`): the adapter returns the empty contract shape (`[]`, empty `Context`) — treat as "nothing found," display a brief note where useful, and continue. Never fail the whole run because one optional tool is missing.
- **Audit/alerts fail**: adapters return empty; continue with outdated checks. An audit failure never blocks updates.
- **Non-GitHub remote**: `HOST`/`TRACKER` resolve to `none`; gather calls return empty shapes. Skip GitHub-specific behavior gracefully — not an error.
- **Build/test fails after apply**: enter bisect (Phase 7). Never leave the project broken.
- **ALL packages fail during bisection**: revert everything, report that no updates could be safely applied, still display the Phase 10 plan.
- **Git operations fail** (stash, checkout): report and stop. Do not continue with uncertain git state.
- **Lint fails**: report it but do **not** revert updates — lint failures are usually pre-existing and unrelated.
- **`git push` fails (e.g. inaccessible SSH key)**: do not work around it. Leave the local bump branch and commit intact, report, and stop the PR flow so the user can push manually.
- **`gh` missing / not authenticated** (`open-pr`/`merge-pr` return `ok:false`, `pr-status` returns `{"error": ...}`): the PR flow cannot run. Report it, leave the committed bump branch in place, stop the PR flow (skip merge/cleanup). Suggest `gh auth login`.
- **PR checks fail / never complete / PR not mergeable** (conflicts, required review): stop and report (Phase 9 Step 4). Never merge a not-ready PR; leave the branch and open PR for manual resolution.
- **`merge-pr` fails** (`ok:false`): report, leave the PR open and branch in place, stop. Do not delete the branch when the merge did not succeed.

## Implementation Notes

1. **Transitive dependencies**: `outdated` lists direct dependencies; transitive vulnerabilities surface through `audit`/`alerts`. For Node, transitive versions can be pinned via overrides.
2. **Lockfiles**: `go.sum`, `pnpm-lock.yaml`, `package-lock.json`, `uv.lock` change as a result of `apply` (see `filesModified`) and must be committed.
3. **Go replace directives**: always skipped — pass replace-target module paths as `replaceTargets` so the categorizer routes them to Skipped. Never auto-modify them.
4. **Go workspaces**: when `detect` reports `workspace: true` (`go.work`), the Go adapter's `outdated`/`audit`/`apply` operate across the workspace.
5. **Coordinated ecosystem updates**: some packages must move together (e.g. Angular core + router). Group them in the Phase 10 plan (identified via exclusion patterns).
6. **Dual entries / override selectors** (Node): packages that appear both as a direct dependency and an override must update together; overrides using the `package@version` selector form target specific transitive paths and need manual analysis — leave them for the plan.
7. **Python dependency formats**: the Python adapter adapts to `pyproject.toml`/`uv.lock` (uv) or `requirements.txt` (pip); `apply` uses `name==X.Y.Z` specs and reports the files it changed.
8. **Commit message**: lists every updated package with old→new versions, grouped by ecosystem; security fixes called out separately with CVE identifiers.
9. **Branch restore order**: always checkout `ORIGINAL_BRANCH` **first**, then `git stash pop`, so stashed changes land on the correct branch.
10. **Main is never bumped directly (on GitHub repos)**: when the base is `main` and `HOST` is `github`, the bump runs on `chore/bump-deps-<timestamp>` and integrates only via PR. `main` changes solely by merging that PR. Only a non-GitHub remote (no PR mechanism) preserves the direct-to-main path.
11. **Squash merge + force delete**: the PR is squash-merged; the branch's original commits become unreachable, so local deletion needs `git branch -D` (`-d` would refuse).
12. **Automatic merge, conservative on failure**: a ready PR is squash-merged without confirmation; a not-ready PR is never merged — branch and PR are left in place and the user is told why.

## Reference

- **`reference/contracts.md`** — the JSON shape every adapter verb emits (UpdateRecord, Advisory, Context, Categories) and the full verb→shape table per axis. Consult it whenever you parse a CLI result.
- **`reference/adding-adapters.md`** — how the adapters are structured and the subprocess-safety rules they follow.

---

Now execute this process.
