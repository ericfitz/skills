---
name: critique
description: Assess the quality of a project's existing integration tests — finding over-mocking, implementation-detail assertions, non-determinism, shared state, and missing failure paths — and recommend keep, repair, replace, or delete for each. Use when auditing a test suite or before adding tests to one. Emits the itest:critique contract.
---

# critique

Assess the integration tests this project already has. A test that passes while the
workflow is broken is worse than no test; finding those is the point of this phase.

Doctrine: `${CLAUDE_PLUGIN_ROOT}/references/test-design.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/critique.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/critique.example.json`

## Usage

    /itest:critique [path]

## Input

You are normally handed a `profile:stack` contract; use `inventory.test_files` and
select the records whose `kind` is `integration` or `e2e`.

You may also be handed a `profile:docs` contract. Its `requirements[]` tell you which
failure paths the project committed to handling. A test that covers only the happy path
of a documented `must` requirement is a `missing-failure-path` issue with evidence
behind it, not a matter of taste.

**Standalone invocation:** if you were not handed one, invoke `profile:stack` and use
its output. If `profile` is unavailable, find test files yourself and say so.

You run in parallel with `/itest:conventions` and do not depend on it. If the census
disagrees with your own reading about which tests are integration tests, assess the
ones you believe are, and say which files you added or excluded and why — the caller
reports the disagreement rather than resolving it silently.

## Procedure

1. Select the integration and e2e test files. If there are none, emit an empty
   `assessed` list and say so plainly. That is a finding, not a failure.
2. Read each file completely. Partial reads produce wrong verdicts about mocking and
   shared state.
3. For each file, record issues using **only** the eight `type` values defined in the
   doctrine's issue vocabulary. Every issue carries `file:line` evidence and a severity.
4. Assign a verdict:
   - `sound` — no high-severity issues; the test would fail if the workflow broke.
   - `weak` — real coverage, but undermined by issues worth fixing.
   - `misleading` — would pass while the workflow it names is broken. Over-mocking the
     boundary under test and assertion-free tests land here.
5. Recommend `keep`, `repair`, `replace`, or `delete`. Reserve `delete` for tests that
   assert nothing of value and duplicate nothing worth keeping.
6. Record `systemic_issues` — patterns across three or more files. These matter more
   than individual verdicts, because they indicate the convention itself is wrong.
7. Emit the contract, then a short prose summary leading with the misleading tests.

## Rules

- Read-only. Do not run tests to check whether they pass. A passing test can still be
  misleading, which is exactly what you are looking for.
- Judge against the doctrine, not against house style. Over-mocking is a defect even
  when every test in the repo does it — that is a `systemic_issue`.
- Do not propose new tests. Coverage gaps are the caller's synthesis step.
