# Bump Modularization Design

**Date:** 2026-07-04
**Status:** Approved (design), pending implementation plan
**Scope:** Behavior-preserving refactor of the `deps:bump` skill into a thin orchestrator + adapter scripts + a common JSON contract, leaving documented seams for new ecosystems, code hosts, and issue trackers.

## Problem

`deps/skills/bump/SKILL.md` is a 964-line monolith. Three concerns are woven through every phase:

1. **Ecosystem-specific mechanics** (Go / Python / Node): detection, cache refresh, outdated parsing, security audit, apply semantics, build/test/lint, bisect.
2. **GitHub-specific integration**: dependency issues, Dependabot alerts, dependency-PR enumeration, and the branch → PR → monitor → squash-merge lifecycle.
3. **Ecosystem- and tracker-agnostic core**: exclusion merging, categorization, display, the prioritized plan, and overall flow control.

Because these are interleaved as prose, the skill cannot be extended to another issue tracker (Jira), another code host (GitLab), or another ecosystem without editing a large document, and none of the logic is testable in isolation. It is also trapped inside a Claude Code skill, so no other agent harness can reuse it.

## Goals

- Extract the variable logic into **config-selected adapters** along three independent axes: **ecosystem**, **code host**, **issue tracker**.
- Make all adapters speak a **common JSON contract** so the agnostic core and orchestrator never care which provider produced the data.
- Keep the **analysis/categorization deterministic and agnostic**, implemented as testable code (not prose).
- Preserve **today's exact behavior** for GitHub + Go/Python/Node (verifiable against the current skill).
- Leave **documented seams** — `none` fallbacks and an "adding an adapter" guide — for Jira / GitLab / new ecosystems, without building them now.
- Move ~90% of the logic into **plain Python** callable by any agent harness (Claude Code today, Codex later via a thin `AGENTS.md` wrapper), leaving only a thin orchestrator as harness-specific.

## Non-Goals

- Building Jira, GitLab, or any second-provider adapter in this effort (seams only).
- Adding new ecosystems beyond Go / Python / Node.
- Changing the user-facing behavior, categorization rules, or PR/merge policy.
- Converting the orchestrator away from a Claude Code skill (a Codex wrapper is future work enabled by, but out of scope for, this design).

## Architecture

```
                    ┌──────────────────────────────────────┐
                    │   bump/SKILL.md  (thin orchestrator)  │
                    │   flow · git · display · plan · report│
                    └───────────────┬──────────────────────┘
                                    │ calls bump.py <axis> <name> <verb>, selected by config
      ┌───────────────┬────────────┼─────────────┬──────────────────┐
      ▼               ▼            ▼              ▼                  ▼
 ecosystem       ecosystem     code-host      tracker          agnostic core
   go.py         node.py       github.py      github.py       categorize.py
 python.py                     (gitlab…)      (jira…)         config.py
   └── VARIABLE, config-selected ──────────────┘            └── MECHANICAL, fixed
        every adapter emits / consumes the COMMON JSON CONTRACT
```

- **Three independent axes**, each resolved from config to a single adapter module. They are independent: a project may run Go/Node code on **GitHub** (code host) while tracking work in **Jira** (issue tracker).
- **Agnostic mechanical core** (`config.py`, `categorize.py`) never varies by provider.
- **The skill** holds only orchestration and judgment: git branch flow, changelog research, the human-facing prioritized plan, and the final report.

### Security advisories come from two source kinds

Advisories are normalized from **both**:
- the **ecosystem** adapter's own audit tools (`govulncheck`, `pnpm/npm audit`, `safety`/`pip-audit`), and
- the **code host** adapter's host-native alerts (Dependabot).

Both emit the same advisory shape and feed the one agnostic categorizer.

## Components

### 1. Adapter interface (verbs per axis)

Every adapter is a module invoked as `bump.py <axis> <name> <verb> [args]`, reading options as flags/stdin and writing contract JSON to stdout.

**Ecosystem** (`go`, `python`, `node`) — owns all parsing/apply/version logic in code:
- `detect` → is this ecosystem present; which package manager; manifests; workspace info.
- `cache-clear` → refresh registry metadata (command overridable via config).
- `outdated` → normalized **update records**.
- `audit` → normalized **advisories** from the ecosystem's audit tool.
- `apply <pkg@ver …>` → apply specific updates, run lockfile sync; report files modified.
- `validate` → run build/test/lint (commands overridable via config); report pass/fail + output.

**Code host** (`github`, `none`) — owns the PR lifecycle:
- `detect` → is the git remote this host; extract owner/repo.
- `alerts` → Dependabot-style **advisories**.
- `prs` → dependency-labeled PRs (**context**).
- `open-pr`, `pr-status`, `merge-pr` → the branch → PR → monitor → squash-merge flow.

**Issue tracker** (`github`, `jira`, `none`):
- `issues` → dependency-related work items (**context**).
- `advisories` (optional) → tracker-sourced advisories.

Branch creation and stash/restore stay **git-generic** in the skill (not a code-host concern), matching today's behavior.

### 2. Common JSON contract

All shapes are provider-neutral. Documented in `skills/bump/reference/contracts.md`.

- **update record**:
  `{ name, current, latest, wanted, bump: "major"|"minor"|"patch", kind: "direct"|"override"|"transitive", location, pinned: bool, meta: {…ecosystem-specific…} }`
  - `pinned` is set by the ecosystem adapter from manifest comments (`// pinned:`, `# pinned:`, `"//pinned"`), since the adapter is already reading the manifest.
- **advisory** (from any source):
  `{ package, ecosystem, severity, current, fixed, ids: ["CVE-…"], summary, source }`
- **context**:
  `{ issues: [{ id, title, url, labels }], pullRequests: [{ id, title, head, url }] }`
- **categories** (categorizer output):
  `{ securityFixes: [...], safe: [...], needsPlan: [{ …, reason }], skipped: [...] }`

### 3. Agnostic core (mechanical, in code)

- **`config.py`** — loads and merges the two file-based exclusion sources:
  1. project `CLAUDE.md` `## Bump Exclusions` (glob patterns),
  2. `.bump-config.json` `exclude` / `hold`.

  The **third** source — code-comment `pinned:` markers — is not scanned here; it is surfaced by the ecosystem adapter's `pinned` flag on each update record (the adapter is already parsing the manifest). `categorize.py` treats a `pinned` record the same as an exclusion. `config.py` also resolves **adapter selection** for each axis (which module to invoke) and per-ecosystem **command overrides**.
- **`categorize.py`** — pure semver comparison + glob matching. Consumes update records + advisories + exclusions, emits the four categories with reasons. This is the "analysis stays agnostic" requirement, implemented as testable code. Category rules are preserved exactly from the current Phase 5:
  - **Security fix (auto)**: resolves an advisory, patch/minor, not excluded.
  - **Safe (auto)**: patch/minor, not excluded, not major, not a Go replace target, no hold.
  - **Needs plan**: major, excluded, held, pinned, major security fix, or flagged by issue/PR context.
  - **Skipped**: Go replace targets, up-to-date packages.

### 4. Config file (`.bump-config.json`, extended)

```json
{
  "codeHost": "github",           // "github" | "none"; unset ⇒ auto-detect from git remote
  "issueTracker": "github",       // "github" | "jira" | "none"
  "exclude": ["@angular/*"],
  "hold": { "@antv/x6": "v3 breaking" },
  "ecosystems": {
    "node": { "cacheClear": "…", "build": "…", "test": "…", "lint": "…" }
  }
}
```

- Only **selection** + **command overrides** live in config. Non-trivial logic (parsing, apply semantics, version comparison) stays in adapter code.
- Defaults preserve **today's zero-config behavior**: `codeHost`/`issueTracker` unset ⇒ auto-detect GitHub from the remote; ecosystem commands fall back to the current built-in defaults and the existing Makefile / package.json / pyproject.toml discovery order.

### 5. Mechanism & layout

A single PEP-723 CLI entrypoint dispatches over a shared `bumplib/` package.

```
deps/
  scripts/
    bump.py                         # PEP-723 CLI entrypoint; adds its dir to sys.path, dispatches <axis> <name> <verb>
    bumplib/
      __init__.py
      contracts.py                  # dataclasses + (de)serialization for update records, advisories, context, categories
      config.py                     # load & merge exclusions + adapter selection + command overrides
      categorize.py                 # agnostic categorizer
      dispatch.py                   # resolve axis+name → adapter module; invoke verb; validate output shape
      ecosystems/{go,python,node}.py
      codehosts/github.py
      trackers/github.py
    tests/                          # unit tests per adapter + categorizer, with recorded tool fixtures
  skills/bump/
    SKILL.md                        # thin orchestrator (still the only skill in the plugin)
    reference/
      contracts.md                  # the JSON contract, authoritative
      adding-adapters.md            # how to add an ecosystem / code host / tracker
```

**Deliberate convention departure (flagged):** the repo convention is standalone, self-contained PEP-723 scripts (`github/scripts/gh-issues.py`). This design uses **one entrypoint + a shared `bumplib` package** instead, because ~8 adapters must share the contract and config code; N copy-pasted standalone scripts would drift. `bump.py` resolves its own directory onto `sys.path` at startup so imports work regardless of cwd or harness.

**Cross-harness portability:** adapters are invoked as ordinary subprocesses (`uv run bump.py …`), so Claude Code and Codex drive them identically — the package-vs-scripts choice is orthogonal to portability. Only `SKILL.md` is Claude-flavored; a future Codex `AGENTS.md` can shell out to the same `bump.py`.

## Phase → component mapping (behavior preservation)

| Current SKILL.md phase | New home |
|---|---|
| 0 Parse args / detect ecosystems | ecosystem `detect` + skill arg parsing |
| 1 Branch management | skill (git-generic) + code-host `detect` |
| 2 Load exclusion rules | `config.py` (+ ecosystem `pinned` flag) |
| 3 Cache refresh | ecosystem `cache-clear` |
| 4a GitHub integration | code-host `alerts`/`prs` + tracker `issues` |
| 4b/c/d Ecosystem checks | ecosystem `outdated` + `audit` |
| 4e Changelog research | skill (judgment; optional code-host helper) |
| 5 Analysis / categorization | `categorize.py` |
| 6 Display analysis | skill |
| 7 Apply safe updates | ecosystem `apply` |
| 8 Build/test/lint | ecosystem `validate` |
| 9 Failure handling (bisect) | skill loop over ecosystem `apply` + `validate` |
| 10 Commit | skill (git-generic) |
| 11 Pull request flow | code-host `open-pr`/`pr-status`/`merge-pr` |
| 12 Plan for remaining | skill (judgment) |
| 13 Cleanup & report | skill |

## Error handling

Preserve the current skill's error posture, now enforced at the contract boundary:
- **Missing tool** (govulncheck, safety, pip-audit, gh): the adapter emits an empty result plus a `warnings` field with install guidance; the skill surfaces it and continues. Never fail the whole run for one optional tool.
- **Non-GitHub / no tracker**: `code-host: none` / `issue-tracker: none` adapters return empty context; the skill skips host/tracker steps gracefully.
- **Build/test failure**: skill enters the bisect loop (unchanged policy).
- **`git push` / SSH-key failure, `gh` missing, PR not mergeable**: unchanged — stop, leave branch + PR in place, report. (Honors the SSH-key-touch and never-force-a-questionable-merge rules.)
- **Malformed adapter output**: `dispatch.py` validates output against the contract and raises a structured error naming the adapter and verb.

## Testing

- **Unit tests** per adapter verb against recorded fixtures (captured `go list`, `pnpm outdated --json`, `pnpm audit --json`, `gh api dependabot/alerts`, etc.), so parsing is verified without live network/tools.
- **Categorizer tests**: table-driven over semver edge cases, glob exclusions, holds, pinned, Go `/vN` majors, replace targets.
- **Config-merge tests**: precedence across CLAUDE.md / `.bump-config.json` / code comments; default resolution when unset.
- **Contract conformance**: a shared schema check every adapter's output must pass.
- **Behavior-preservation check**: run the new pipeline against a representative repo and diff the categorization + plan against the current skill's output.

## Open questions

None blocking. Provider-name-to-module resolution is convention-based (`bumplib/<axis>/<name>.py`); a future enhancement could allow a filesystem path in config for out-of-tree adapters, but that is not needed for the seams this design targets.
