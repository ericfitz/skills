---
name: design
version: 1.0.0
description: Design an integration test suite for a project — discovering its stack, its documented requirements, deployment shape, customer journeys, test conventions, existing-test quality, and state affordances, then synthesizing a prioritized scenario plan. Use when asked to design, plan, or scope integration tests, or to find gaps in an existing integration suite. Requires the profile plugin.
---

# design

Design integration tests for a project: discover, confirm the journeys and requirements
with the user, then synthesize a plan.

Doctrine: `${CLAUDE_PLUGIN_ROOT}/references/test-design.md`
Handoff contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/scenario.schema.json`
Worked example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/scenario.example.json`

## Usage

    /itest:design [path]

## Phase 0 — Preflight

Check your available skills for `profile:stack`, `profile:docs`, `profile:topology`,
and `profile:journeys`. If any is missing, stop and tell the user:

> This skill needs the `profile` plugin, which is not installed. Install it from the
> `efitz-skills` marketplace and run `/itest:design` again.

Do not attempt to reach `profile`'s files by path, and do not proceed with partial
discovery. Failing here costs nothing; failing three subagents deep wastes the run.

Then ask the user one question, and accept "none":

> Are there requirements documents, PRDs, specifications, or wiki pages for this project
> that do not live in the repository? Paste links or paths, or say none.

Ask it here rather than later, because the phase that reads documentation runs as a
subagent and cannot ask anything.

## Phase 1 — Stack gate

Invoke `profile:stack` for the target path. Every other phase depends on knowing the
ecosystem, and its contract carries the repo inventory that all later phases use.

If its `confidence` is `low`, say so before continuing — everything downstream inherits
that uncertainty.

## Phase 2 — Documentation gate

Invoke `profile:docs`, handing it the `stack` contract and any external pointers the
user gave in Phase 0.

This is a gate rather than a parallel peer because all five phases below read from it,
and one shared reading of the documentary record beats five private ones. It is the
slowest step in discovery; say so if the corpus is large rather than going quiet.

When it returns, surface two things immediately:

- `unavailable_sources[]` — named documents it could not reach, each with a remedy. Ask
  whether to proceed without them or stop so the user can supply them. **Do not try to
  reach them another way.**
- how many documents it read out of how many it found, straight from its summary.

## Phase 3 — Parallel discovery

Dispatch five subagents concurrently, one per phase, each handed the `stack` contract
and the `docs` contract:

| Subagent | Invokes | Returns |
|---|---|---|
| topology | `profile:topology` | topology contract |
| journeys | `profile:journeys` | journeys contract |
| conventions | `itest:conventions` | conventions contract |
| critique | `itest:critique` | critique contract |
| state | `itest:state` | state contract |

Instruct each to invoke its skill **by name** and return only the contract JSON plus a
short summary.

If `conventions` and `critique` disagree about which tests are integration tests,
report the disagreement in the plan. Do not silently pick a side.

## Phase 4 — Gate prep

Before asking the user anything, map each requirement in the `docs` contract onto the
journey candidates it plausibly belongs to. A requirement that maps to none is
**cross-cutting** — "every response carries a request id", "all writes are audited",
"tenant data never crosses tenants". These are real integration-tier concerns that no
single journey owns, and they would otherwise vanish.

This mapping happens here, not inside `profile:docs`, because cross-cutting-ness is a
judgment about the journey set, which does not exist when that phase runs.

## Phase 5 — Human gate

**Subagents cannot ask the user anything, so this gate runs here, in the main
conversation.** Present four things, tightest first, as short default-approve lists —
not four separate interrogations:

1. **Ranked journey candidates** with evidence and dependency edges. Approve, edit,
   remove, add. Confirm the `depends_on` edges explicitly: users usually know the
   prerequisite relationships faster than they can be inferred, and those edges drive
   precondition design.
2. **Unmapped requirements** from Phase 4, ordered by `modality` (must first) then
   `authority`. Approve, drop, or attach to a journey.
3. **Unavailable sources**, if the user chose to continue past them — restated once so
   the gap is a decision rather than an oversight.
4. **Deferred documents** — offer to pull one in if journey coverage looks thin.

Do not proceed until the user has responded.

## Phase 6 — Synthesis

Work through these eight steps in order, presenting each and checking before moving on.

1. **Boundary selection.** Combine `standup_notes`, `integration_separation`, and the
   state affordances into one chosen boundary. State it explicitly with its rationale,
   and name what is real and what is stubbed. This is the most important sentence in
   the plan; write it down rather than assuming it.
2. **Scenario expansion.** Expand each approved journey into one happy path plus the
   failure scenarios that qualify under the doctrine's tier rule. Attach the
   `requirement_ids` each scenario satisfies, and set `provenance` to `journey` or
   `both`. Documented acceptance criteria are a rich source of failure cases that
   code-mining alone will not reveal — but the tier rule still applies to them: a
   documented input-validation rule is still a unit test. Push everything disqualified
   down and say that you did.
2b. **Cross-cutting expansion.** Turn each *approved* unmapped requirement into a
   scenario with `provenance: requirement` and `journey_id: null`. Only approved ones;
   the gate is where scope was set.
3. **Precondition design.** Build the DAG from the confirmed `depends_on` edges, plus
   any `preconditions_stated` the requirements name. Resolve each edge to compose or
   inject against the doctrine's composition rules, and choose isolation and cleanup
   from the discovered teardown affordances.
4. **Assertion design.** For each scenario, what is observable at the chosen boundary,
   what to assert, which negative assertions matter, and which determinism controls are
   required. Use documented `acceptance_criteria` verbatim wherever they are observable
   at the boundary, turn `domain_invariants` into negative assertions, and name things
   using the `glossary` — a plan written in the project's own vocabulary reads as though
   someone who knows the domain wrote it.
5. **Gap map.** Two axes.
   - *Journey coverage*: approved journeys crossed with critique verdicts —
     covered, weak, missing, misleading.
   - *Requirements coverage*: each requirement — covered, weak, untested,
     contradicted, unobservable. `contradicted` means the code appears to do something
     else. `unobservable` means the requirement is real but cannot be checked at the
     chosen boundary; say so rather than dropping it, because it is a finding about the
     boundary.

   Priority order: **contradicted > misleading > untested > missing > weak.**
   Contradicted leads because a normative document disagreeing with the code is either
   a live defect or a specification nobody maintained. Misleading still outranks
   absence: a test that passes while the journey is broken is worse than no test.
6. **Risks and assumptions.** Collect every `assumptions[]` entry from `topology` and
   `state`. Discovery was read-only, so none of them were proven. They ride into each
   scenario's `open_assumptions`, to be confirmed on the build phase's first run.

   Then record `doc_code_conflicts[]`, one entry per conflict that touches a scenario:

       { requirement_id, doc_claim, code_evidence, authority,
         verdict: likely_stale_doc | likely_code_defect | undetermined }

   State the conflict and both readings. **Do not adjudicate** — you did not run
   anything, and `authority` is what tells the reader how much the document's claim is
   worth. Only conflicts touching a scenario go here; this is not a documentation audit.
7. **Emission.** Produce the scenario set conforming to the handoff contract, print the
   whole plan as one markdown document, then ask whether to save it and where.
8. **Conflict disposition.** If `doc_code_conflicts[]` is non-empty, offer — never
   assume — one of:
   - **Create tracking issues**, one per conflict or one grouped issue, using a
     capability already available in this session: the `github:create-issue` skill, an
     issue-tracking MCP, or `gh`. **No new issue-creation mechanism is built.** If none
     is available, say so and offer the next option instead.
   - **Save a findings document** at a path the user names, listing each conflict, its
     document anchor, its code evidence, and both readings.
   - **Neither** — the conflicts stay in the emitted plan and nowhere else.

   This exists so an inconsistency found in passing is not lost when the session ends.

## Rules

- Nothing in this workflow executes anything. No builds, no test runs, no containers.
- Never invoke `profile`'s inventory script by path. Inventory reaches this plugin only
  inside the `stack` contract.
- Never work around an unreachable document. Report it with its remedy and move on.
- Every scenario must carry `placement` and `runner_invocation`. A scenario the runner
  would not pick up is not finished.
- Every scenario must carry `provenance`, and `requirement_ids` for every requirement it
  covers. A reader asking "why does this test exist" should get an answer with a
  document anchor attached.
- If the user's approved journeys have no failure scenarios that qualify under the tier
  rule, say so — a short honest plan beats a padded one.
