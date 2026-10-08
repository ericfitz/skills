# Upstream issue for ataraxy-labs/sem — RETRACTED 2026-08-17

Filed 2026-08-15 as https://github.com/Ataraxy-Labs/sem/issues/479 (adapted from
ericfitz/skills#30). Closed by the maintainer 2026-08-16 as cannot-reproduce; the maintainer
was right.

## What the report claimed

`sem diff <base>..HEAD` silently reports no changes when `<base>` is a commit orphaned by a
squash-merge (resolvable object, not an ancestor of HEAD).

## What was actually happening

The anchor in the motivating case (tmi `DeduplicateGroups`, `SEM@91a78cdd`) was a commit at
which the entity's file **did not exist yet**: the marker had been hand-written in the same
commit that created the file, anchored at then-HEAD (the parent). `sem diff` correctly reported
the entity as `added` relative to that base; sem-annotate's parser only counted `modified` and
so classified the marker fresh. Reachability was a coincidence — in a squash-merge repo every
branch-written anchor is unreachable — not the cause. Reproduced in linear history with a fully
reachable anchor.

Independently verified with sem 0.21.0 that `sem diff <orphaned-branch-sha>..HEAD` reports the
modification (JSON and human output, exit 0), matching the maintainer's seven-variant test.

## Consumer-side resolution

ericfitz/skills#39 — sem-annotate v2.4.4 treats `added`-since-anchor as stale and drops the
v2.4.3 reachability check (which, in squash-merge repos, re-described every branch-written
marker after every release for no correctness gain).

The original text is preserved in git history (`git show 68634bd:docs/upstream/sem-orphaned-anchor-staleness.md`).
