---
name: dependency-model
description: Shortcut that builds a system's whole dependency model in one command — runs synthesize (topology, the six dependency discovery skills, and the merge), then dependency-report to render docs/dependencies.md. Chains existing skills only.
argument-hint: "[path] [--ref <branch>] [--out <file.md>]"
disable-model-invocation: true
---

# dependency-model

Build a system's whole dependency model in one command: gather and merge the
discovery output, then render it as a document.

## Steps

1. Invoke `discover:synthesize` with `[path] [--ref <branch>]`. It runs
   topology and the six dependency discovery skills itself, merges
   them, and emits the `synthesis` contract.
2. Invoke `discover:dependency-report` with the same `[path] [--ref <branch>]`
   plus `[--out <file.md>]`. Hand it the synthesis contract from step 1 so it
   does not run `discover:synthesize` again. Report the path of the document
   it wrote.

## Usage

    /discover:dependency-model [path] [--ref <branch>] [--out <file.md>]

The bare form `/dependency-model` also works in Claude Code when no other command has
that name; Codex uses the namespaced form only.

## Rules

- Invoke every skill by name, never by script path. Each chained skill keeps
  its own confirmation gates; answer none of them for the user.
- Stop at the first step that fails or that the user declines. Report
  `Stopped at step N (<skill>): <reason>` and list what completed.
- This shortcut adds no behavior of its own: it sequences the skills above.
