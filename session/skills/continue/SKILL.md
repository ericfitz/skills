---
name: continue
description: Use at the start of a session when HANDOFF.md exists, when asked to /continue, or on phrasing like "resume from handoff", "pick up where we left off", "where were we", or "what's next in this repo". Reads HANDOFF.md, checks it against the real repo state, reports drift, and proposes the next action, or runs github:backlog when nothing is queued. It never starts work. Not for a plain "continue" or "keep going" mid-task.
---

# /continue

Start the session from the current state, not from memory. HANDOFF.md says what the last
session believed; `repo-state.sh` says what is true now. The job is to report both, flag every
difference, and stop. When the handoff queues no work, hand off to `github:backlog`, which
recommends an issue and stops at its own confirmation question.

## Bundled Script Location

This skill bundles `repo-state.sh` inside its plugin at `scripts/repo-state.sh`.
When you see `${CLAUDE_PLUGIN_ROOT}` below, it refers to this plugin's
install root. If Claude Code does not pre-substitute the variable when you read this file,
resolve it yourself: locate the directory containing this SKILL.md, walk up to the plugin
root, and use that absolute path.

## Steps

1. **Find and read HANDOFF.md.** Check `<git rev-parse --show-toplevel>/HANDOFF.md` first. If it
   is absent, use the main checkout root: the parent of
   `git rev-parse --path-format=absolute --git-common-dir`. (A worktree session shares the main
   checkout's handoff.) Say which path you read.
   - If it is in the legacy multi-session format (more than one dated or session section, or
     over 80 lines: `wc -l HANDOFF.md`, `rg -c '^#+ .*(20[0-9]{2}-[0-9]{2}|[Ss]ession)' HANDOFF.md`),
     read only the top current block and recommend running `/session:handoff` once to convert it.
   - If HANDOFF.md is missing in both places, continue using the facts alone and say so.

2. **Collect facts:** run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/repo-state.sh` from inside the repo. It
   prints `== git`, `== github` and `== state-checks` sections: BRANCH, HEAD, UPSTREAM, DIRTY,
   WORKTREES, UNMERGED BRANCHES, OPEN PRS (mine), MAIN CI, then whatever `.local/state-checks.sh`
   emits (typically `DEPLOYED ...` and `IMAGE ...` lines) and a final `STATE-CHECKS:` line.
   `.local/state-checks.sh` is an optional, machine-local, untracked script in the repo root
   that prints `DEPLOYED <site>: <version>` / `IMAGE ...` lines; when it is missing the output
   says `STATE-CHECKS: not configured`.
   Degraded labels to recognize: `UPSTREAM: none`, `GITHUB: unavailable (<reason>)`,
   `OPEN PRS (mine): unavailable (...)`, `MAIN CI: unavailable (...)`, and
   `STATE-CHECKS: not configured | FAILED (exit N) | TIMEOUT`.
   Exit 2 means the cwd is not a git repo: report that and stop.

3. **Compare** every claim in HANDOFF.md with the facts. List each mismatch as **drift**:
   - a DEPLOYED version that differs from what HANDOFF.md says;
   - unpushed commits (`ahead N`), dirty files, worktrees or unmerged branches HANDOFF.md
     does not mention;
   - a PR HANDOFF.md calls open that is merged or closed, or whose checks now fail;
   Drift is only a mismatch between a HANDOFF.md claim and the facts. Main CI status is not
   drift by itself: it goes on the State line, and counts as drift only when HANDOFF.md asserts
   something it contradicts (e.g. "main is green"). Likewise `STATE-CHECKS: FAILED|TIMEOUT|not
   configured`, `GITHUB: unavailable` and `MAIN CI: unavailable` are not drift: they make the
   corresponding facts unverified, which goes on the State line. Drift is reported, not fixed.

4. **Check agentbus** for pending messages, only when an agentbus MCP server is available:
   follow the using-agentbus skill (register, then `receive`; do not start a background
   `wait`) and note any message that changes the next step. Without an agentbus server, skip
   this step.

5. **Print a summary of 10 lines or fewer** with exactly these headings:
   - **State:** branch, HEAD, upstream, dirty/clean, open PRs, main CI: <status>, deployed versions; plus "unverified: PRs/CI/deployed" for whichever of those the labels above mark unavailable.
   - **Drift:** the mismatches from step 3, or "none".
   - **Waiting on the user:** each item with the exact command to run (absolute paths) or the
     exact `Approve: <action and target>` line to send. Read the handoff's `WAITING ON USER:`
     section; also accept the legacy heading `WAITING ON ERIC:` in existing handoff files.
   - **Proposed next action:** one item, taken from HANDOFF.md NEXT unless drift changes it.
     When step 6 applies, it is "run `/github:backlog`".

6. **No queued work: run the backlog.** No queued work means all of these hold:
   - HANDOFF.md IN FLIGHT is empty or "none" (or HANDOFF.md is missing in both places);
   - HANDOFF.md NEXT is empty, "none", or only says to pick an item from the backlog or issue list;
   - the Drift line is "none". Drift means unrecorded work exists, so propose handling it instead.
   WAITING ON USER items do not block this step; they stay on their summary line.
   When all hold and the `github:backlog` skill is in the available-skills list, print the
   summary, then invoke `github:backlog` by name and follow it. It ends by asking which issue to
   work on; that question is where this session stops. If the skill is not available, propose
   from NEXT as usual and append "(`/github:backlog` unavailable: github plugin not installed)"
   to the Proposed next action line. If the user's first message already gave a different
   instruction, skip this step.

7. **Stop and wait for the user. Do not start work.** If the user's first message already gave
   a different instruction, follow it instead of the proposal. After step 6 the stop is
   `github:backlog`'s own confirmation question.

## Rules

- Read-only: `/continue` never edits files, commits, pushes, deploys or sends agentbus
  messages other than the protocol's registration. The step 6 handoff to `github:backlog`
  only reads issues; any work begins only after the user confirms an issue there.
- Facts beat HANDOFF.md. When they disagree, the fact goes in State and the disagreement goes
  in Drift.
- Keep it short. Detail belongs in the next step, after the user chooses it.
