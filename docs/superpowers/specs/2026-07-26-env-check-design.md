# `env` Plugin — Environment Check

**Date:** 2026-07-26
**Status:** Approved design, not yet implemented

## Problem

Every plugin in this marketplace depends on things that are not in the repository: `sem`
for `dev`, `gh` and `jq` for `github`, `uv` for four plugins, `playwright` for `ui`, plus
the `.local/` config convention and authenticated CLI sessions.

Today each skill improvises its own preflight, or none. `dev/skills/dedupe/SKILL.md` says
"Confirm `sem` is available: `sem --version`. If missing, stop and tell the user to install
it." `github/skills/create-issue/SKILL.md` has an error-table row for `gh` not being
authenticated. These are correct instincts implemented nine different ways, and a user on a
fresh machine discovers each gap one failure at a time, mid-task.

## Solution

A new `env` plugin with one skill, `/env:check`, that answers "is my environment ready" —
for the whole marketplace or for one plugin.

Each plugin declares its own requirements in a sidecar `requirements.json`. The checker
discovers those declarations, probes for what they name, and reports what is missing, why
it matters, and how to fix it. Diagnosis is read-only by default; installation is a
separate, explicitly requested mode that confirms each item.

## Decisions

| Decision | Choice |
|---|---|
| Scope | External CLI tools, local config files, and auth state. Not target-project toolchains, not dependency pre-warming |
| Declaration | Sidecar `requirements.json` per plugin, discovered by glob |
| Install policy | Report-only by default; `--fix` is an explicit opt-in that confirms each item |
| Invocation | Standalone `/env:check [plugin]`; other skills may call it, but are not retrofitted here |
| Shipped declarations | `env`, `github`, `dev` only. The other eight are tracked in [#21](https://github.com/ericfitz/skills/issues/21) |
| Probe safety | argv arrays executed with `shell=False`; only declared probes are ever run |

### Why not target-project toolchains

`go` and `npm` appear across several plugins' skills, but only because a *target repo*
might use them. Checking for them on a machine that legitimately has neither would report
failures that are not failures. Requirements describe what the plugin needs to run, never
what a repo it operates on might need.

### Why the migration is deferred

Writing declarations for the remaining eight plugins means reading each plugin's skills
carefully enough to distinguish a genuine requirement from an incidental mention. That is
real work, independent of building the checker, and it is tracked in
[#21](https://github.com/ericfitz/skills/issues/21). Shipping
`github` and `dev` as exemplars proves the schema against real plugins — one exercising all
three categories, one exercising the single-hard-tool case — before eight more are written
against it.

## Architecture

```
env/
  .claude-plugin/plugin.json
  skills/check/SKILL.md
  scripts/env_check.py
  references/
    requirements.schema.json      # the declaration contract
    writing-declarations.md       # how to author a requirements.json
  requirements.json               # env's own declaration

github/requirements.json          # exemplar: tool + optional config + auth
dev/requirements.json             # exemplar: single hard tool
```

### Discovery

The checker auto-detects which of two layouts it is running in:

- **Source repo** (`~/Projects/skills`): declarations at `<root>/*/requirements.json`, flat,
  one per plugin directory.
- **Installed cache**: `${CLAUDE_PLUGIN_ROOT}` is
  `~/.claude/plugins/cache/efitz-skills/env/<version>/`, so siblings are at
  `../../*/*/requirements.json`.

Multiple versions of a plugin coexist in the cache — the layout today contains both
`ui/1.0.0` and `ui/1.1.0`, and both `wiki/1.0.0` and `wiki/1.1.0`. The checker takes **the
highest version per plugin** and names the version it read in its report. Silently choosing
between coexisting versions is the kind of wrong answer this tool exists to prevent.

If discovery finds no siblings — plugin installed standalone, or an unrecognized layout —
the checker says so and reports on itself only. Degraded discovery costs a shorter report,
not a broken workflow, so an honest partial result is the correct behavior.

### Separation of diagnosis and installation

`env_check.py` is strictly read-only. It discovers declarations, runs probes, and emits
JSON. It contains no install path at all.

`--fix` lives in the skill layer, where per-item confirmation happens in conversation. The
dangerous half sits where it can ask first; the diagnostic half stays deterministic and
unit-testable.

## The declaration contract

`<plugin>/requirements.json`, validated against
`env/references/requirements.schema.json`:

```json
{
  "requirements_version": "1.0.0",
  "plugin": "github",
  "tools": [
    {
      "name": "gh",
      "required": true,
      "why": "every GitHub API call in backlog and create-issue",
      "probe": ["gh", "--version"],
      "version_pattern": "gh version (\\d+\\.\\d+)",
      "min_version": "2.40",
      "install": { "macos": "brew install gh", "docs": "https://cli.github.com" }
    }
  ],
  "config": [
    {
      "path": ".local/gh-projects.json",
      "scope": "repo",
      "required": false,
      "why": "project and field IDs for issue filing",
      "remedy": "run ~/Scripts/provision-repo-config.py in the target repo"
    }
  ],
  "auth": [
    {
      "name": "github",
      "probe": ["gh", "auth", "status"],
      "why": "issue creation and project mutation",
      "remedy": "gh auth login"
    }
  ]
}
```

Four properties are load-bearing:

**`required` separates hard from optional.** `sem` for `dev` is hard; `.local/gh-projects.json`
for `github` is optional, since its absence degrades issue filing rather than breaking it.
Only hard failures make the overall result non-green.

**Probes are argv arrays, executed with `shell=False`.** These files are data that drives
command execution: no shell, no string interpolation, no metacharacters. A schema test
asserts every committed probe is an array, never a string.

**Only declared probes are ever executed.** The checker runs what it finds in a discovered
declaration and nothing else. There is deliberately no general "run this command" entry
point, because that would be an arbitrary-execution primitive reachable through a plugin
script.

**`why` is required on every entry.** "Missing `jq`" is a checklist; "missing `jq` — needed
by `deps` to parse `npm audit` output" is actionable. This field is the difference.

Auth probes record exit status and a one-line summary only. They never capture token
values, and the checker never reads anything under `~/.keys/`.

## Report

The script emits JSON; the skill renders it grouped by plugin, hard failures first, each
line carrying its `why` and its remedy.

Results fall into four categories, kept distinct:

- **Missing (hard)** — a `required: true` entry failed. Drives the exit code.
- **Degraded** — an optional entry failed. Listed with what capability is lost; never
  affects the exit code.
- **Undeclared** — a discovered plugin has no `requirements.json`. Reported neutrally with
  a pointer to [#21](https://github.com/ericfitz/skills/issues/21), not mixed in with failures.
- **OK** — summarized, not enumerated.

Exit codes: `0` all hard requirements met, `1` at least one hard requirement missing, `2`
usage or discovery error.

### `probe` subcommand

`env_check.py probe <plugin> <name>` re-runs a single declared probe. It exists so `--fix`
can verify one item after installing it without repeating the whole sweep, and so an agent
has a cheap way to re-check a single requirement. It can only run probes present in a
discovered declaration.

### `--fix`

Skill-level, constrained three ways: it runs only the exact `install` string declared for
the detected platform, it never composes an install command of its own, and it confirms
each item separately. With no key for the current platform it prints the `docs` URL and
moves on.

After each install it re-verifies with the `probe` subcommand rather than assuming success.
A `brew install` that exits 0 while the binary is not on `PATH` is a common outcome.

## Testing

Stdlib `unittest`, matching the repo's existing style:

- Every committed `requirements.json` validates against the schema. This is what stops
  declarations from rotting as plugins change.
- Discovery works in both the flat source layout and the versioned cache layout, including
  selecting the highest version when several coexist.
- Version comparison handles `2.40` against `2.41.1`, equal versions, missing output, and
  unparseable output.
- Probe execution is exercised against fake commands, so no test depends on `gh`, `sem`, or
  `uv` being installed on the machine running it.
- A safety test asserts every probe in every committed declaration is an array, never a
  string.

## Out of scope

- Declarations for the remaining eight plugins — tracked in
  [#21](https://github.com/ericfitz/skills/issues/21)
- Retrofitting the existing nine plugins' skills to call `/env:check` as a preflight — same
  issue
- Dependency pre-warming (for example `boring`'s spacy model download)
- Checking toolchains that only a target repo would need
- Installing `uv` itself automatically; the checker reports it and prints the command
