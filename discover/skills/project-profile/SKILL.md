---
name: project-profile
description: Shortcut that profiles a project end to end — runs stack, docs, journeys and topology, saves the four contracts, then project-report to render one offline HTML report. Chains existing skills only.
argument-hint: "[path] [--out <file.html>] [--title <text>] [--no-open]"
disable-model-invocation: true
---

# project-profile

Profile a project end to end: run the four project discovery skills, save
their contracts, and render one offline HTML report.

## Steps

0. Setup. Create the artifact directory with
   `mktemp -d "${TMPDIR:-/tmp}/project-profile-XXXXXX"`. It is never inside
   the target repository, and it is the run dir for the steps below.
1. Invoke `discover:stack` with `[path]`, giving it the artifact directory as
   its run dir; it saves `stack.json` there.
2. Invoke `discover:docs` with `[path]` and the stack contract. Save its reply
   as `docs.json` in the artifact directory.
3. Invoke `discover:journeys` with `[path]` and the stack and docs contracts.
   Save its reply as `journeys.json` in the artifact directory. In the final
   message, say that the journeys are unconfirmed candidates.
4. Invoke `discover:topology` with `[path]`, giving it the artifact directory
   as its run dir; it saves `topology.json` there.
5. Invoke `discover:project-report` with `<artifact_dir> [--out <file.html>]
   [--title <text>] [--no-open]`. Report both the artifact directory and the
   report path.

## Usage

    /discover:project-profile [path] [--out <file.html>] [--title <text>] [--no-open]

The bare form `/project-profile` also works in Claude Code when no other command has
that name; Codex uses the namespaced form only.

## Rules

- Invoke every skill by name, never by script path. Each chained skill keeps
  its own confirmation gates; answer none of them for the user.
- Stop at the first step that fails or that the user declines. Report
  `Stopped at step N (<skill>): <reason>` and list what completed.
- This shortcut adds no behavior of its own: it sequences the skills above.
