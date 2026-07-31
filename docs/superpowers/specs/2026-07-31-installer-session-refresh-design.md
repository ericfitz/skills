# Installer + Session-Start gh-projects Refresh (issue #16) — Design

**Date:** 2026-07-31
**Status:** Approved (designed autonomously per user directive; decisions documented below)
**Tracks:** https://github.com/ericfitz/skills/issues/16

## Goal

1. One-step install of the `efitz-skills` marketplace into Claude Code or Codex.
2. `.local/gh-projects.json` (the resolved GitHub Project metadata cache that
   `github:create-issue` / `github:backlog` read) refreshed at the start of each
   top-level session, best-effort, so those skills never operate on stale
   Project ids/fields/milestones.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Where the hook lives | The `github` plugin ships `hooks/hooks.json` (SessionStart) + `scripts/refresh_gh_projects.py` | The plugin whose skills consume the cache owns its freshness. Claude Code auto-detects plugin `hooks/hooks.json` and exports `CLAUDE_PLUGIN_ROOT` (verified live via the superpowers plugin), so installing `github` there sets up the refresh with zero extra steps. Codex does NOT currently execute plugin-shipped hooks (see the "Codex session refresh" row); the file still ships so Codex picks it up if the platform enables `plugin_hooks` later. |
| Hook matcher | `startup` only (not `clear`/`compact`) | "New session means a top-level session start." Subagents fire no SessionStart in either harness — satisfies the not-on-subagent requirement structurally. |
| Refresh semantics | Refresh-only: if `<repo-root>/.local/gh-projects.json` exists, re-resolve each entry and rewrite; if absent, exit 0 silently | Creating the cache requires choosing a Project — that's provisioning (`~/Scripts/provision-repo-config.py`, user-run). Refresh-only also guarantees the hook never creates `.local/` state in repos the user hasn't opted in. |
| `repos.json` | Never read, never written, never required | Issue constraint, verbatim. |
| Best-effort guarantee | The refresher ALWAYS exits 0; every subprocess has a timeout (5s per `gh` call, ~15s total budget); no repo / no cache / no `gh` / offline / auth-expired all end silently | "A failed refresh never blocks or breaks session start." Exit 0 always is belt-and-braces on top of both harnesses tolerating hook failures. |
| Refresher runtime | `python3`, stdlib only (no PEP 723 deps, no uv) | A session-start hook must not depend on the very tooling the env plugin exists to check. `gh` does all API work. |
| Cache shape | Byte-compatible with `provision-repo-config.py`'s `build_cache_entry` (`cached_at`, `project{number,owner,id,title}`, `fields`, `milestones`, `labels`, `issue_types`), name-keyed | The provisioning script remains the sole creator/migrator (per `.local/` convention); the refresher only updates values in the shape it found. |
| Installer | `scripts/install.sh <claude|codex|all>` at repo root | Wraps `claude plugin marketplace add ericfitz/skills` + installs, and `codex plugin marketplace add ericfitz/skills` + `codex plugin add <p>@efitz-skills` for each plugin. Idempotent (add-if-missing). `all` (default) targets whichever CLIs are on PATH; a missing CLI is a skip with a note, not an error. |
| Codex session refresh | Opt-in installer flag `--codex-session-hook`: merges a `SessionStart` entry into `~/.codex/hooks.json` (backup first) whose command resolves the highest installed `github` plugin version's refresher at run time | Verified on Codex 0.146.0: plugin-shipped hooks do NOT fire (`codex features list` → `plugin_hooks removed false`; no hook trace in a live session record), while user-level hooks are stable/enabled. Mutating `~/.codex` config is opt-in only — default install prints a hint instead. Claude Code needs nothing: plugin `hooks/hooks.json` fires natively (same mechanism as the working superpowers plugin). |

## Components

```
github/
  hooks/hooks.json                  # SessionStart -> refresh_gh_projects.py (async-safe, startup matcher)
  scripts/refresh_gh_projects.py    # stdlib; refresh-only; always exit 0
scripts/install.sh                  # repo-root installer, both harnesses
```

`github/requirements.json` gains nothing: `gh` is already declared; the hook
degrades silently without it by design.

## Refresher flow

1. Resolve repo root: `git rev-parse --show-toplevel` from cwd (hook cwd = the
   session's project dir in both harnesses). Failure → exit 0.
2. Load `<root>/.local/gh-projects.json`. Absent/unparseable → exit 0 (never
   "fix" a broken cache — that's provisioning's job).
3. Per entry (name-keyed): re-resolve via `gh` — project fields/options
   (`gh project field-list`, as provisioning does), milestones, labels, issue types (REST) —
   and rebuild the entry in the identical shape with a fresh `cached_at`.
   Any per-entry failure keeps the old entry untouched.
4. Write atomically (temp file + rename) only if content actually changed
   (ignoring `cached_at`), preserving the file otherwise. Exit 0.

## Error handling

Every failure path is silent-and-0 by design. One diagnostic affordance: a
`--verbose` flag (used when running the script by hand) prints what was
refreshed/skipped; the hook invocation does not pass it.

## Testing

- `tests/test_github_refresh.py` (unittest, fake `gh` on prepended PATH, tmp
  repos): no-repo → 0; repo without cache → 0, `.local/` not created;
  cache present → entries rewritten in provisioning shape with fields from the
  fake `gh`; per-entry `gh` failure preserves that entry; `gh` missing
  entirely → 0, file untouched; timeout respected (fake `gh` that sleeps);
  `repos.json` never read (fake it present, assert untouched/unopened via
  content check); unchanged content → no rewrite (mtime preserved).
- `tests/test_plugin_structure.py` addition: any `<plugin>/hooks/hooks.json`
  must parse and its `command` strings must reference `${CLAUDE_PLUGIN_ROOT}`
  paths that exist (mirrors the existing ref-resolution test).
- Installer: `bash -n` syntax check in tests; behavior verified manually with
  the real CLIs (Codex side already exercised in this repo's E2E work).

## Acceptance criteria (from #16)

- [x] Installer supports both Claude Code and Codex → `scripts/install.sh`.
- [x] Cache updated at each top-level session start, not subagent start →
  Claude Code: plugin SessionStart hook, `startup` matcher, automatic on
  install. Codex: plugin hooks are platform-disabled (0.146.0), so the refresh
  requires the installer's opt-in `--codex-session-hook` user-level hook.
  Subagents fire no SessionStart in either harness.
- [x] Nothing creates or requires `.local/repos.json` → refresher never touches
  it; installer never touches `.local/` at all.
- [x] Failed refresh never blocks session start → always-exit-0 + timeouts.

## Out of scope

- Creating `.local/gh-projects.json` for unprovisioned repos (user runs the
  provisioning script once per repo, unchanged).
- Bundling/replacing `~/Scripts/provision-repo-config.py` in the plugin.
- Auto-installing `gh` or auth handling (env plugin's territory).
