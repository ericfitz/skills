---
name: handoff
description: Use when asked to /handoff, "update the handoff", "write the handoff", "checkpoint", at a checkpoint (task finished, decision made, PR merged), or when the user says they are stopping, going to sleep, or ending the session. Rewrites HANDOFF.md with current state only, routes long-lived knowledge out, and reports everything not yet landed. It never commits, pushes or deploys.
---

# /handoff

End (or checkpoint) the session so the next one can start with `/session:continue`. HANDOFF.md
holds only current state: it is replaced, never appended. Long-lived knowledge moves to
where it belongs. Nothing that hasn't landed goes unreported.

## Bundled Script Location

This skill uses `repo-state.sh`, bundled inside its plugin at `scripts/repo-state.sh`.
When you see `${CLAUDE_PLUGIN_ROOT}` below, it refers to this plugin's
install root. If Claude Code does not pre-substitute the variable when you read this file,
resolve it yourself: locate the directory containing this SKILL.md, walk up to the plugin
root, and use that absolute path.

## Where HANDOFF.md lives

Check `<git rev-parse --show-toplevel>/HANDOFF.md` first. If it is absent, use the main
checkout root: the parent of `git rev-parse --path-format=absolute --git-common-dir`. Write to
the file you found. If neither exists, create it at the main checkout root, so worktree
sessions share one handoff. Say which path you wrote.

## Steps

1. **Collect:** run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/repo-state.sh` from inside the repo. Read the
   current HANDOFF.md (location above), if any. Review this session for: what was done, what is
   in flight, what is blocked, decisions the user made, and facts learned. Labels you will see:
   BRANCH, HEAD, UPSTREAM, DIRTY, WORKTREES, UNMERGED BRANCHES, OPEN PRS (mine), MAIN CI,
   `DEPLOYED ...`/`IMAGE ...` lines, and `STATE-CHECKS:`. The `DEPLOYED`/`IMAGE` lines come from
   `.local/state-checks.sh`, an optional, machine-local, untracked script in the repo root; when
   it is missing the output says `STATE-CHECKS: not configured`. If you see
   `GITHUB: unavailable`, `MAIN CI: unavailable`, `STATE-CHECKS: FAILED|TIMEOUT|not configured`,
   or `UPSTREAM: none`, treat the dependent facts (merged, deployed, pushed) as unverified: do
   not drop work on their strength, and mark DEPLOYED values `carried over, unverified`.

2. **Sort every item** from the old file and from the session into one of three bins:
   - **Current state** -> the new HANDOFF.md.
   - **Finished work** -> dropped, but only when the facts prove it landed: pushed (`ahead 0`),
     merged (PR closed as merged), or deployed (DEPLOYED line shows the version). Anything else
     stays in IN FLIGHT.
   - **Long-lived knowledge** -> the routing list, using this table:
     | Kind | Destination |
     |---|---|
     | applies to every session in this repo | project CLAUDE.md |
     | situational fact, tool quirk, benign noise | agentbus `memory/<project>` when an agentbus MCP server is available; otherwise the project CLAUDE.md (the closest row), and the report says so |
     | human decision | ADR in `docs/adr/`, plus a one-line "see ADR-NNNN" in the project CLAUDE.md if it keeps coming up |

3. **Route, without asking.** Make every move on the routing list; do not stop for approval.
   The moves are easy to undo:
   - Tracked files (CLAUDE.md, ADRs) are edited but **not committed**.
   - Agentbus memories (when a server is available) are created with `send` to the project's
     memory channel; do not ask before creating them.
   Nothing is moved silently: every move appears in the "routed" table in step 6.

4. **Rewrite HANDOFF.md** from this template. Aim for 40 lines or fewer; going over means
   something should be routed out in step 3.
   ```markdown
   # HANDOFF (machine-local, never commit)

   STATE: <commit> on <branch>; clean|dirty (<n> files); upstream ahead/behind; worktrees; open PRs.
   DEPLOYED: <site>: <version> (verified <date> | carried over, unverified)
   IN FLIGHT:
   - <branch/worktree/PR>: <what's left>
   WAITING ON USER:
   - <why>: `<exact command, absolute paths, no redundant cd>`
   - <production gate>: send "Approve: <exact action and target>"
   NEXT:
   1. <ordered next steps>
   ```
   The production-gate line is the message the user sends to clear a permission-classifier
   block on a production action (production deploy, protected infrastructure apply): the
   message must name the exact action and target, for example
   `Approve: terraform apply in infra/environments/prod for #123`. An approval
   recorded in an earlier HANDOFF does not count; it has to be sent in the session that acts.
   DEPLOYED values not re-verified this session are marked `carried over, unverified`.

5. **Keep it untracked:** if `git -C <dir containing HANDOFF.md> check-ignore -q HANDOFF.md` fails
   (use the directory where the file lives, not the cwd, which may be a worktree), append
   `HANDOFF.md` to that directory's `.gitignore` and say so. Do not commit the `.gitignore` change.

6. **End with a report** of what was routed and what is not landed, without asking any questions:
   - **Routed:** a table (item, destination, file path or memory id) of every move made in
     step 3, so the user can revert any of them. Omit it if nothing was routed.
   - **Not landed:** everything uncommitted, unpushed, unmerged or undeployed, each with the
     command that would land it (absolute paths), for example
     `cd /path/to/repo && git push origin feat/x`, `gh pr merge 123 --squash`.

## Rules

- `/handoff` never commits, pushes or deploys. It only writes HANDOFF.md, makes routing
  edits, and reports.
- `/handoff` never prompts the user. If an item's destination is unclear, pick the closest row
  of the routing table and say so in the report.
- History is dropped by design. The record of finished work is git log, merged PRs and closed
  issues.
- At a mid-session checkpoint (task, decision, merge), run the same steps; the routing list is
  usually empty and the file gets shorter.
