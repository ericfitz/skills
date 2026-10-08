# Installer + Session-Start Refresh (#16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship issue #16 per `docs/superpowers/specs/2026-07-31-installer-session-refresh-design.md` (authoritative): a best-effort SessionStart refresh of `.local/gh-projects.json` bundled in the `github` plugin, plus a one-step installer for both harnesses.

**Architecture:** Per the spec. The refresher mirrors the cache shape of `~/Scripts/provision-repo-config.py` (`build_cache_entry`: `cached_at`, `project{number,owner,id,title}`, `fields`, `milestones`, `labels`, `issue_types`; name-keyed file) — read that script before implementing to copy its `gh` resolution calls (GraphQL project/fields query; REST milestones/labels/issue-types) and output shape exactly. It is user-machine-local; do not vendor it, only mirror the refresh-relevant subset.

**Tech Stack:** Python 3 stdlib (refresher — NO PEP 723 deps, runs under bare `python3`), bash (installer), unittest + fake-`gh`-on-PATH tests, existing manifest generator.

## Global Constraints

- Spec governs; deviations → BLOCKED.
- Refresher invariants (each needs a pinning test): always exits 0; per-`gh`-call timeout 5s; never touches `repos.json`; never creates `.local/` or the cache file; atomic rewrite only when content (minus `cached_at`) changed.
- Commits go directly to main. Push is currently BLOCKED on an SSH key touch — commit locally, attempt one push, report its state honestly, never work around. CI verification is deferred until a push succeeds.
- Lint `uv run ruff check .`; suite `uv run pytest -q` fully green (753 passed / 454 subtests baseline).
- End every commit message with:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_018a81HJnmo8CacJVPNDL127`

---

### Task 1: The refresher — `github/scripts/refresh_gh_projects.py` + tests

**Files:**
- Create: `github/scripts/refresh_gh_projects.py`
- Test: `tests/test_github_refresh.py`

**Interfaces:**
- Produces: CLI `python3 github/scripts/refresh_gh_projects.py [--verbose] [--cwd PATH]` (`--cwd` for tests; default `.`). Always exit 0. Task 2's hook invokes it with no flags.

- [ ] **Step 1: Failing tests first** — the spec's Testing section lists the required cases verbatim (no-repo; repo-no-cache with `.local/` non-creation; happy-path rewrite in provisioning shape from a fake `gh`; per-entry failure preserves entry; missing `gh` → untouched file; sleeping fake `gh` → timeout honored, still exit 0; `repos.json` present and byte-identical after; unchanged content → mtime preserved). Fake `gh` = executable script on prepended PATH (see `tests/test_cats_runner.py` `_with_fake_cats` idiom) that dispatches on argv to return canned JSON.
- [ ] **Step 2: RED, then implement.** Read `~/Scripts/provision-repo-config.py` first; mirror its `build_cache_entry` shape and its `gh` calls for fields/milestones/labels/issue-types. `subprocess.run(argv, shell=False, capture_output=True, timeout=5)`; total soft budget ~15s (stop refreshing further entries past it, keep old values). Atomic write: `tempfile` in same dir + `os.replace`. Every exception path swallowed to exit 0 (`--verbose` prints diagnostics).
- [ ] **Step 3: GREEN + full suite + lint + commit (push attempt; likely blocked — say so).** Subject: `feat(github): best-effort session-start refresher for .local/gh-projects.json (#16)`

---

### Task 2: The hook + structure guard + bump

**Files:**
- Create: `github/hooks/hooks.json`
- Modify: `tests/test_plugin_structure.py` (hooks guard), `github/.claude-plugin/plugin.json` (patch bump)
- Regenerate: `github/.codex-plugin/plugin.json`

**Interfaces:**
- Consumes: Task 1's CLI.

- [ ] **Step 1: Failing structure test** — new test in `test_plugin_structure.py`: every `<plugin>/hooks/hooks.json` parses; every `"command"` string's `${CLAUDE_PLUGIN_ROOT}/...` path references an existing file (reuse `PLUGIN_ROOT_REF` regex).
- [ ] **Step 2: Write the hook** —

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/scripts/refresh_gh_projects.py\"",
            "shell": "bash",
            "async": true,
            "statusMessage": "Refreshing GitHub Project cache"
          }
        ]
      }
    ]
  }
}
```

(`async: true`: the refresh is fire-and-forget; combined with always-exit-0 this doubly guarantees session start is never blocked. If the structure test or docs check shows either harness rejects `async`/`statusMessage`, drop the offending key — both are enhancements, not load-bearing.)

- [ ] **Step 3:** GREEN; bump github 1.2.1 → 1.2.2; `uv run scripts/gen_codex_manifests.py`; full suite + lint + `REPO="$PWD" bash scripts/verify-marketplace.sh`; commit. Subject: `feat(github): SessionStart hook wiring for the gh-projects refresher (#16)`
- [ ] **Step 4: Live hook verification (inline, controller):** reinstall github from the local checkout in Codex (marketplace swap as before), run one `codex exec` session in a tmp git repo with a fixture `.local/gh-projects.json` pointing at a real repo (`ericfitz/skills`), confirm the cache's `cached_at` advanced after the session (proves the hook fired) and that a repo WITHOUT the cache file is untouched. If Codex doesn't execute plugin SessionStart hooks in `exec` mode, record that honestly and verify via the Claude Code side instead (install from local marketplace, new session).

---

### Task 3: The installer — `scripts/install.sh`

**Files:**
- Create: `scripts/install.sh` (executable)
- Modify: `tests/test_plugin_structure.py` or new `tests/test_install_sh.py` (a `bash -n` syntax-check test)

- [ ] **Step 1:** Write the installer: `install.sh [claude|codex|all]` (default `all`). For each requested harness whose CLI is on PATH: add marketplace `ericfitz/skills` if not already configured, then install every plugin listed in `.claude-plugin/marketplace.json` (parse with python3). Claude Code CLI forms: `claude plugin marketplace add ericfitz/skills`, `claude plugin install <name>@efitz-skills` (verify exact subcommands via `claude plugin --help` during implementation; if the CLI lacks non-interactive forms, print the interactive `/plugin` instructions instead of failing). Codex forms (already proven in this repo): `codex plugin marketplace add ericfitz/skills`, `codex plugin add <name>@efitz-skills`. Missing CLI → skip with note, exit 0; any real install failure → non-zero with the failing command echoed.
- [ ] **Step 2:** `bash -n` test + run `bash scripts/install.sh codex` for real (Codex is installed here; idempotency check — everything already installed → clean no-op exit 0). Full suite + lint; commit. Subject: `feat(scripts): one-step installer for Claude Code and Codex (#16)`

---

### Task 4: Wrap-up (inline, controller)

- [ ] Final whole-effort review (subagent, most capable model) over the three commits; fix wave if needed.
- [ ] When the user's key touch lands: push, watch CI, then close #16 (`gh issue close 16`) with: component summary, acceptance-criteria checklist mapped to evidence (hook verification transcript, installer run), and the repos.json non-involvement statement. Close #21 at the same time (its closing comment is already owed; see the env-plan ledger).

---

## Self-Review (completed)

- Spec coverage: refresher (T1), hook + not-on-subagent + bump (T2), installer (T3), acceptance evidence + issue close (T4). Out-of-scope respected (no cache creation, no provisioning vendoring).
- No placeholders: hook JSON inline; test list delegated to the spec's Testing section by explicit reference; CLI verification steps carry concrete fallbacks.
- Consistency: exit-0 invariant, 5s/15s timeouts, and cache-shape fields named identically in spec and tasks.
