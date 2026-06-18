---
name: sem-auto
version: 1.0.0
description: Set up a project so SEM@<sha> intent markers stay maintained — installs a SEM-marker convention block into the project's CLAUDE.md so Claude adds/updates markers as part of normal editing. Use when the user asks to enable sem markers for a project, set up sem-auto, or keep SEM markers fresh automatically.
---

# sem-auto

Make a project self-maintaining for `SEM@<sha>` intent markers. Marker upkeep is **convention-based**: there is no git hook (writing a marker's description requires an LLM, which a hook doesn't have). Instead, this skill writes a convention block into the project's `CLAUDE.md` so that Claude — which *does* have a model — adds or refreshes markers as a normal part of editing code. Commits made outside Claude get reconciled the next time Claude touches those files or the user runs `/sem-annotate`.

## Usage

```
/sem-auto            # install the SEM-marker convention into ./CLAUDE.md
/sem-auto <path>     # target a specific project root (its CLAUDE.md)
```

## Process

1. **Locate the target `CLAUDE.md`.** Default to `<repo-root>/CLAUDE.md` (the nearest `.git` directory, or cwd). If the path argument names a directory, use that directory's `CLAUDE.md`. If no `CLAUDE.md` exists, create one.

2. **Check idempotently.** Look for the sentinel `<!-- sem-markers -->` in the file. If present, the convention is already installed — report that and stop (do not duplicate it). If the user passed `--force` / asks to refresh, replace the existing block (from the opening sentinel to the closing `<!-- /sem-markers -->`) instead.

3. **Confirm `sem-annotate` is available.** This convention assumes the `sem-annotate` skill and the `sem` CLI are installed (the marker-writing tooling). Note it in the report if `sem --version` fails.

4. **Append the convention block** below, verbatim, to the target `CLAUDE.md` (preceded by a blank line). Preserve all existing content.

5. **Report** the file changed and show the inserted block with `git diff` (do not commit automatically unless asked).

## Convention block (insert verbatim)

```markdown
<!-- sem-markers -->
## SEM markers

This project uses `SEM@<sha>` intent markers: a one-line comment directly above each
function/method/class describing **what it does** (intent, not mechanism), plus the commit
its body last changed at. Example:

    // SEM@4abcf04: validate a JWT and return its claims; reject if expired (pure)

**Why they matter:** the descriptions are the signal the `dedupe` tool uses to find duplicate
code, and they make the codebase easier for both humans and `sem` to navigate. Keeping them
accurate is load-bearing — a stale description is worse than none.

**The rule:** when you add a new function/method/class, or change one's behavior, add or update
its `SEM@` marker. Run `/sem-annotate --update <changed files>` to (re)generate markers for the
files you touched, or `/sem-annotate <path>` to cover a whole scope. Only entities that are new
or whose logic changed get rewritten — unchanged siblings keep their markers.

**Writing the description** (so duplicates cluster reliably): one line, ≤ ~12 words, intent not
mechanism; lead with a canonical verb (validate, parse, fetch, store, build, convert, serialize,
register, handle, authenticate, …) and a canonical domain noun; abstract incidental
identifiers; don't restate the entity name; tag a strong side-effect when it discriminates
(`(pure)`, `(reads DB)`).

**Drift is handled for you:** the `@<sha>` lets `/sem-annotate` tell whether a marker is stale
via `sem diff` (formatting/reformatting never marks it stale), so you don't need to touch a
marker whose entity didn't logically change.
<!-- /sem-markers -->
```

## Notes
- Idempotent: re-running `/sem-auto` is a no-op once the sentinel is present (unless refreshing).
- This skill only edits `CLAUDE.md`; it never modifies source. Marker generation is the
  `sem-annotate` skill's job.
