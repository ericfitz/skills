# Session plugin design

Date: 2026-10-08
Status: approved

## Goal

Move the user-level `/continue` and `/handoff` skills (and their shared `repo-state.sh`
script and SessionStart hint hook) out of `~/.claude` and into this marketplace, as a new
`session` plugin. The skills keep their current behavior: `/handoff` rewrites a
machine-local `HANDOFF.md` holding only current state; `/continue` reads it, compares it
with live repo facts, reports drift and stops.

## Human decisions (Eric, 2026-10-08)

1. **Plugin home:** a new top-level `session` plugin. Skills are invoked as
   `/session:continue` and `/session:handoff`.
2. **Generalization:** the repo is public, so the skills are generalized. The user's name
   becomes "the user", examples use no private paths, hosts or project names, and agentbus
   is optional: the agentbus steps run only when an agentbus MCP server is available.
3. **Cutover:** after the plugin is installed and its self-tests pass from the installed
   path, the user-level copies are removed and the global config is pointed at the new names.
   The user sees the diff and approves before anything in `~/.claude` is deleted or edited.

## Decision made during design (not yet reviewed by Eric)

- **The hint hook moves into the plugin** (`session/hooks/hooks.json`, SessionStart,
  matcher `startup|resume`), because its only job is to invoke `/session:continue`. Precedent:
  `github/hooks/hooks.json`. The cutover removes the global registration so the hint does not
  fire twice.

## Layout

```
session/
  .claude-plugin/plugin.json      name "session", version 1.0.0 (first release, not a bump)
  .codex-plugin/plugin.json       generated
  requirements.json               git, perl required; gh, agentbus optional
  hooks/hooks.json                SessionStart -> scripts/handoff-hint.sh
  scripts/repo-state.sh           from ~/.claude/skills/_lib/repo-state.sh
  scripts/handoff-hint.sh         from ~/.claude/hooks/handoff-hint.sh
  skills/continue/SKILL.md
  skills/handoff/SKILL.md
```

`~/.claude/skills/_lib/checkpoint.py` stays where it is: the user-level threat-model skill uses it.

## Changes from the user-level versions

- Script paths become `${CLAUDE_PLUGIN_ROOT}/scripts/repo-state.sh`, with the explanatory
  line `env/skills/check/SKILL.md` uses.
- `handoff-hint.sh` calls `python3` from PATH, not `/usr/bin/python3`, and its hint names
  `/session:continue`.
- "Eric" becomes "the user". The HANDOFF.md template heading `WAITING ON ERIC:` and the
  `/continue` report heading "Waiting on Eric" change together to `WAITING ON USER:` /
  "Waiting on the user", so `/continue` still recognizes what `/handoff` wrote. `/continue`
  also accepts the legacy `WAITING ON ERIC:` heading in existing handoff files.
- The private examples (a `terraform apply` path, a `/Users/...` push command, PR numbers) are
  replaced with generic ones.
- Agentbus: `/continue` step 4 and the `/handoff` routing row "agentbus `memory/<project>`"
  apply only when an agentbus MCP server is available. Without one, situational facts route to
  the project CLAUDE.md (the closest row) and the report says so. The "standing permission"
  wording becomes "do not ask before creating agentbus memories".
- `.local/state-checks.sh` is explained in the skills: an optional, machine-local,
  untracked script in the repo root that prints `DEPLOYED <site>: <version>` / `IMAGE ...`
  lines. It's missing → `STATE-CHECKS: not configured`.
- The `Approve: <action and target>` production-gate line stays, described as the message the
  user sends to clear a permission-classifier block on a production action.

## Testing

`tests/test_session_scripts.py`: for each script, exists / executable / `bash -n` / runs its
own `--self-test` successfully from a temp directory (the self-tests build their own scratch
repos and must leave the working tree clean). `hooks.json` parses and points at a script that
exists.

## Out of scope

- Any behavior change to the skills beyond the generalization above.
- The cutover itself (a separate, user-approved step after install).
