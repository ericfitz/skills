# HANDOFF — dependency-model layer 2 (#49): 11 of 12 tasks committed, mid-execution

Session date: 2026-08-22/23. This file is working state, not documentation — delete it
once #49 is merged.

**The authoritative record is the SDD ledger**, not this file:
`.superpowers/sdd/2026-08-22-dependency-synthesis/progress.md`
It holds the pre-flight scan, every ruling, every deferred minor, and a per-task log with
commit ranges. It is git-ignored but survives a restart. Read it before acting. This file
carries only what a fresh session needs that the ledger does not spell out.

## Current state

**Branch `feat/dependency-model-layer2`, 14 commits, nothing in flight, tree clean.**
Branched from `main` at `b9d640e`. **Not pushed.**

`main` itself is also ahead of `origin/main` by 5 commits — the #49 spec and plan, committed
this session before the branch was cut. So `origin/main` is at `0ca7d58` (the merged layer-1
work) and 19 commits total are unpushed. Nothing here has been pushed; that is deliberate,
not an oversight.

All four CI checks green at `fff79ee`:

    uv run ruff check .                          # clean
    uv run pytest -q                             # 1109 passed / 1071 subtests
    uv run scripts/gen_codex_manifests.py --check # 16 in sync
    REPO="$(pwd)" bash scripts/verify-marketplace.sh  # PASS 42 / FAIL 0

Baseline when the branch started was 1035 passed.

## What is done

Tasks 1–11 of `docs/superpowers/plans/2026-08-22-dependency-synthesis.md`, all committed,
all reviewed except where noted below:

| # | Task | State |
|---|---|---|
| 1 | `pkglifecycle.py` — build-vs-run derivation | complete, 2 fix rounds, re-review clean |
| 2 | `lifecycle` on the layer-1 contract | complete, reviewed with T1 |
| 3 | six skills set `lifecycle` | complete, review clean |
| 4 | `references/definitions.md` | complete, review clean |
| 5 | `synthesis.schema.json` + example | complete, 1 fix round, re-review clean |
| 6 | `depgraph.py` merge + CLI | complete, reviewed with T5 |
| 7 | typed edges + cycle detection | complete-pending-review |
| 8 | Mermaid emission + node cap | complete, 1 fix round, re-review clean |
| 9 | `synthesize` skill | complete-pending-review |
| 10 | `report` skill | complete-pending-review |
| 11 | registration + coupling-test restructure | complete-pending-review |

**Tasks 7, 9, 10 and 11 have not had a task review.** They are committed and green, but the
per-task review gate was not run for them. Either run those reviews or let the final
whole-branch review cover them — decide deliberately, do not let it pass silently.

## What remains — two things

### 1. Task 12 — architecture documentation

**Re-dispatch it. Its brief in the plan is fine now; it was not before.**

Task 12 was dispatched out of order (my error — see Controller errors below), stood down, and
its partial edit reverted. Nothing of it is committed. Now that Tasks 9–11 have landed, the
brief's original instructions are finally accurate: the two skills exist, the plugin is
registered with eight, so the `x_synth` / `x_report` graph nodes and catalog rows it calls
for **are** warranted.

Brief: `.superpowers/sdd/2026-08-22-dependency-synthesis/task-12-brief.md`

Two things its dispatch must carry:

- **Re-render the Mermaid, do not eyeball it.** `CLAUDE.md` requires it. Extract the fence and
  run `npx -y -p @mermaid-js/mermaid-cli mmdc -i /tmp/arch.mmd -o /tmp/arch.svg`; `mmdc` must
  exit 0. A syntax error there ships a broken graph to `main`.
- **Do not let it run `git push` or `gh issue close`** — the brief's final steps mention both.
  Those are the human's call.

### 2. Final whole-branch review

Then the final review, per `superpowers:subagent-driven-development`:

    scripts/review-package PLAN_FILE $(git merge-base main HEAD) HEAD

Dispatch on the most capable model. **Point it at the ledger's deferred-minor and parked
lines** so it can triage which must be fixed before merge — there are 17, listed there with
context. Several matter more than their label suggests; the three below especially.

## Findings a fresh session should not have to rediscover

**A design question left open for the user has since been decided.** The T3 review flagged
that `platform`'s `runtime-version` / `arch` / `os` → `build` was in tension with
`definitions.md`: `lifecycle` records *which environment must contain* a dependency, and all
three are constraints on the **runtime** environment. The user's ruling: `platform` is `run`
for every `details.kind`. That collapses the per-kind split entirely — all eight
`details.kind` values are `run`, and `package` is left as the only category with a derived
`lifecycle`. Applied in the catch-up fix wave, across the spec's D3 table, `platform/SKILL.md`,
this plan's Task 3 text, and T11's pinning test.

**The PEP 621 manifest pass is unguarded** (`pkglifecycle.py`). `project = "x"` raises
AttributeError; `[project] dependencies = 5` raises TypeError; and `dependencies = "requests"`
**silently classifies the single characters r/e/q/u/s/t as run** — garbage roots rather than a
loud failure. This is the plan's original code, not introduced by any fix, and the same
rationale used to guard the Poetry pass applies to it verbatim. Deferred, in the ledger.

**Cross-file lifecycle precedence asymmetry.** A package in `[tool.poetry.dev-dependencies]`
in one file and `[project.optional-dependencies]` in another resolves to `build`, because the
optional-deps `setdefault` loses to a `BUILD` already set by an earlier-walked file. Confirmed
pre-existing as a class. Within a single file, run-wins holds in every ordering.

**`depgraph.py`'s `mermaid` key is consumed by nobody in the skill path.** `report` regenerates
the fence from the contract's `graph` instead, which is correct — the contract is its stated
interface and deliberately excludes presentation. The key remains useful to a human running
the script directly. Recorded so nobody deletes it assuming it is dead.

## Conventions this work established

- **No version numbers move** until the user declares the feature productionized.
  `contract_version` stays `1.0.0`, `plugin.json` stays `0.1.0`. Do not propose a bump.
  Saved to auto-memory as `version-bumps-gated-on-user`.
- **The two definitions** — build-vs-run, and what counts for health — are in
  `dependency-model/references/definitions.md` and in auto-memory as
  `dependency-and-health-definitions`. Both were got wrong several times before settling; read
  them rather than re-deriving.
- **Branch, not worktree.** `scripts/verify-marketplace.sh` hardcodes
  `REPO="${REPO:-/Users/efitz/Projects/skills}"`, so from a worktree a bare invocation
  validates `main`'s tree while reporting success. Always run it as `REPO="$(pwd)" bash ...`.

## Controller errors from this session, so they are not repeated

Three, recorded in full in the ledger. Two share a shape: **giving an instruction, then acting
on it myself without revising the instruction.**

1. Told Task 8 "the tree is yours", then dispatched two fix rounds into that tree.
2. Told Task 12 to revert its own edit, then reverted it myself before its reply arrived — it
   spent a round on forensics that correctly found a checkout had run and wrongly concluded it
   was not me.
3. Skipped Tasks 9–11 and dispatched Task 12 out of order — then tried to work *around* the gap
   by rewriting Task 12's instructions rather than fixing the sequence. Caught on re-reading.

Correct form for parallel dispatch: name the in-flight files explicitly, and revise the
instruction when the situation changes.

## Issue map

- [#46](https://github.com/ericfitz/skills/issues/46) parent — dependency-analysis skills
- [#48](https://github.com/ericfitz/skills/issues/48) layer 1 — **closed**, merged to `main`
- [#49](https://github.com/ericfitz/skills/issues/49) layer 2 — **this branch**, narrowed to
  synthesis; journey exposure split out
- [#50](https://github.com/ericfitz/skills/issues/50) layer 3 — monitoring/resilience gaps
- [#51](https://github.com/ericfitz/skills/issues/51) layer 4 — chaos test plan
- [#53](https://github.com/ericfitz/skills/issues/53) hardening follow-ups from #48's final review
- [#54](https://github.com/ericfitz/skills/issues/54) journey exposure, split out of #49 during
  its brainstorm

Spec: `docs/superpowers/specs/2026-08-22-dependency-synthesis-design.md`
Plan: `docs/superpowers/plans/2026-08-22-dependency-synthesis.md`
