# DRAFT upstream issue for ataraxy-labs/sem — not yet filed

Adapted from ericfitz/skills#30. Review before filing.

---

**Title:** `sem diff <base>..HEAD` silently reports no changes when `<base>` is an
orphaned commit (squash-merge workflows), so staleness checks built on it never fire

## Summary

When the base revision passed to `sem diff` (and consumed by scan/update flows built on
it) resolves as a git object but is **not reachable from HEAD**, sem reports no changes
instead of erroring or flagging the condition. In squash-merge workflows this is the
normal end state for any commit recorded on a feature branch: after the squash-merge the
original commits become orphaned objects — `git cat-file -e <sha>` succeeds, but
`git merge-base --is-ancestor <sha> HEAD` exits 1.

Any tooling that anchors semantic state to a commit sha and later asks sem "did this
entity change since `<sha>`?" gets a silent false "no" for every pre-squash anchor. The
failure does not self-report: no error, no warning, exit 0.

## Reproduction

1. In a repo using squash merges: record a sha on a feature branch (any commit that
   touches a tracked function).
2. Squash-merge the branch to main; delete the branch.
3. Change the function's behavior on main.
4. Run `sem diff <branch-sha>..HEAD --no-cosmetics -- <file>`.

Expected: an error (unreachable base) or the logical change reported.
Actual: empty diff, exit 0.

Check: `git merge-base --is-ancestor <sha> HEAD; echo $?` → `1` for affected shas.

## Impact

Squash-merge is a very common GitHub workflow, so any sem-based staleness tracking
silently stops working for a repo's entire pre-squash history. Users reasonably conclude
"nothing changed" and move on.

## Suggested fixes (any of)

1. During diff/scan, check base reachability (`merge-base --is-ancestor`); treat an
   unreachable base as an error or a distinct "orphaned" result — never as "no changes".
2. Fall back to comparing against the nearest reachable commit instead of giving up.
3. At minimum, emit a loud warning when a base fails reachability so the silent mode is
   impossible.
4. Longer-term: content-hash anchors (hash of the entity's normalized body) instead of
   commit shas — immune to history rewriting entirely.

Options 1 + 3 together would have surfaced this immediately.

## Environment

- sem-cli 0.21.0 (Homebrew), macOS (darwin 25.6.0)
- Observed via SEM@sha marker tooling in ericfitz/skills (see ericfitz/skills#30 for the
  downstream write-up and the consumer-side workaround)
