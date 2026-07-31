---
name: check
description: Check whether your environment is ready to use this marketplace's plugins — required CLI tools, config files, and auth sessions. Use when asked "is my environment ready", to check requirements, run an env check, or do a preflight before starting work. Reports hard failures, degraded (optional) capability loss, and undeclared plugins; supports checking a single plugin and an explicit --fix mode.
---

# check — environment readiness skill

Answers "is my environment ready" for the whole marketplace, or for one
plugin, by discovering each plugin's sidecar `requirements.json`, probing for
what it declares, and reporting what is missing, why it matters, and how to
fix it. Diagnosis is read-only by default; `--fix` is a separate, explicit
mode that confirms before changing anything.

## Bundled Script Location

This skill bundles `env_check.py` inside its plugin at `scripts/env_check.py`.
When you see `${CLAUDE_PLUGIN_ROOT}` below, it refers to this plugin's
install root — typically
`~/.claude/plugins/cache/efitz-skills/env/<version>/`. If Claude Code does
not pre-substitute the variable when you read this file, resolve it
yourself: locate the directory containing this SKILL.md, walk up to the
plugin root, and use that absolute path.

## When to invoke

Invoke when the user asks any of:

- "Is my environment ready?" / "Am I set up correctly?"
- "Check requirements" / "check my environment" / "env check"
- "Preflight" before starting work on this repo
- "Is `<plugin>` ready to use?" — a single-plugin check
- "Fix my environment" / "install what's missing" — the `--fix` flow

## Step 1: Run the checker

`env_check.py` is invoked through `uv` (it declares `uv` as its own hard
requirement — see `${CLAUDE_PLUGIN_ROOT}/requirements.json`):

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/env_check.py check --json
```

To scope the check to one plugin, add `--plugin NAME`:

```bash
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/env_check.py check --json --plugin github
```

Capture stdout and the exit code regardless of which exit code comes back
(`0` all hard requirements met, `1` at least one hard requirement missing,
`2` usage or discovery error). Parse stdout as JSON — the report shape is:

```
{
  "plugins": {"<name>": {"version": <str|null>, "path": <str>}, ...},
  "degraded_discovery": <bool>,
  "missing": [{"plugin","section","name","why","remedy","detail"}, ...],
  "degraded": [{"plugin","section","name","why","remedy","detail"}, ...],
  "undeclared": ["<plugin>", ...],
  "ok_count": <int>,
  "exit_code": <int>,
  "error": <str, only on exit 2 with a bad --plugin filter>
}
```

`section` is one of `"tool"`, `"config"`, `"auth"`, or `"declaration"`. A
`"declaration"` entry means a sibling `requirements.json` exists but failed
to parse — a broken declaration, not a missing requirement.

If `"error"` is present (exit 2, e.g. an unknown `--plugin` name), report the
error and stop; there is no report to render. A discovery error (e.g. the
env plugin's own declaration can't be found or read) also exits 2, but
prints its message to stderr with **no JSON on stdout at all** — the
`"error"` JSON key only ever appears for the bad-`--plugin` case above.

## Step 2: Render the report

Render in this order. These rules are load-bearing — do not summarize past
them:

1. **If `degraded_discovery` is true**, say so first: only this plugin's own
   declaration was visible, so the report covers `env` only, not the whole
   marketplace.

2. **Broken declarations first, in their own heading**, before anything
   else in `degraded`. These are the `degraded` entries with
   `"section": "declaration"`. Render each with its full `detail` (it
   contains the path that failed to parse and the parse error) — a plugin
   can legitimately be healthy in `plugins` (a newer cached version) *and*
   broken here (a stale older version still on disk); showing both facts
   side by side is what makes that explainable rather than contradictory.
   **A report containing any broken-declaration finding must never be
   summarized as "all good" or "environment ready," even when `exit_code`
   is `0`** — broken declarations don't affect the exit code, but they are
   never nothing.

3. **Missing (hard failures)** — every entry in `missing`. Each line: what's
   missing, its `why`, and its `remedy`. This is what drives `exit_code`
   to `1`.

4. **Degraded (optional)** — the rest of `degraded` (excluding the
   declaration entries already rendered in step 2). Each line: what's
   missing, what capability is lost (`why`), and its `remedy`. Never
   treated as a failure and never affects the exit code.

5. **Undeclared plugins** — plugins discovered with no `requirements.json`
   at all. The JSON list itself carries no issue pointer, so add one when
   rendering: "see https://github.com/ericfitz/skills/issues/21". Keep this
   list separate from failures — it is neutral, not a finding.

6. **OK** — summarize as a count (`ok_count`), never enumerated
   individually.

Only call the environment fully ready when `exit_code` is `0`, `degraded`
contains no `"declaration"` entries, and `undeclared` is empty (or note the
undeclared plugins explicitly even then, since it's neutral information the
user may still want).

## Step 3: `--fix` (only when explicitly requested)

`--fix` is opt-in and never runs unless the user asked for it. It is
constrained three ways, matching the design spec exactly:

- **Only the exact `install` string declared for the detected platform** —
  never a command you compose yourself.
- **One confirmation per item**, in plain conversation. Don't assume an
  `AskUserQuestion`-style UI exists; just ask and wait for a yes/no reply
  before running anything.
- **Re-verify after each install** via the `probe` subcommand, rather than
  trusting the install command's own exit code. A `brew install` that exits
  0 while the binary isn't on `PATH` yet is a common outcome this catches.

`--fix` only applies to **`tool` findings** (in `missing` or `degraded`,
excluding `declaration` entries). `config` and `auth` findings carry a
`remedy` that is guidance text (e.g. "run a provisioning script," "`gh auth
login`"), not an installable package — surface their remedy in the report
but don't attempt to automate them.

For each eligible tool finding:

1. **Detect the platform**: run `uname -s` (or equivalent). `Darwin` →
   `macos`; `Linux` → `linux`; anything Windows-like → `windows`.

2. **Look up the full `install` object** for that tool. The JSON report's
   `remedy` field is already a resolved hint string, not the raw `install`
   map — read the tool's own entry from the plugin's `requirements.json`
   (its path is in the report's `plugins` section) to get the per-platform
   keys.

3. **If the detected platform has a key**: show the user the exact command
   (e.g. `brew install gh`) and the `why`, and ask for confirmation. On
   yes, run that exact string — nothing appended, nothing substituted. On
   no, skip it and move on.

4. **If the detected platform has no key**: don't guess at an equivalent
   command. Print the `docs` URL from the `install` object (if present) and
   move on to the next item.

5. **After a successful install** (or after any install attempt), re-verify
   with the probe subcommand rather than trusting the installer's exit
   code:

   ```bash
   uv run ${CLAUDE_PLUGIN_ROOT}/scripts/env_check.py probe <plugin> <name>
   ```

   Report the re-verified status (fixed / still failing) per item, not just
   the install command's own result.

6. When every eligible item has been offered, summarize what was fixed,
   what was skipped, and what still needs manual attention (config/auth
   remedies, and any platform with no declared install key).

## Notes

- The checker never touches anything under `~/.keys/` and auth probes
  capture only exit status and a one-line summary — never token values.
- `env_check.py` itself is strictly read-only; all installation happens at
  this skill layer, in conversation, with the user's confirmation.
