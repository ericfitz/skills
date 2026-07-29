---
name: topology
version: 1.0.0
description: Determine how a system deploys and what it depends on — components, real dependencies, third-party services, configuration, startup order, and how hard each component is to stand up. Read-only. Use when profiling an unfamiliar project for test design, deployment documentation, or onboarding. Emits the profile:topology contract.
---

# topology

Determine the deployment shape of a system by reading its configuration. Emits the
`topology` contract.

**This phase never executes anything.** No container boots, no health checks, no
builds. Every factual claim carries `file:line` evidence; everything inferred but
unconfirmed goes in `assumptions[]`.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/deployment-shapes.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/topology.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/topology.example.json`

## Usage

    /profile:topology [path]

Standalone invocation: if you were not handed a `stack` contract, invoke
`profile:stack` first and use its output. Do not run the inventory script directly.

## Procedure

1. From the `stack` contract's `inventory`, read every path under `containers`,
   `iac`, `ci`, and `entrypoints`. Those files are your primary evidence.
2. Match against the signature table in `references/deployment-shapes.md` to set `shape`.
3. Enumerate `components` — each independently deployable or independently runnable
   unit, with the evidence that shows it exists.
4. Enumerate `real_dependencies` — infrastructure the system genuinely needs (database,
   cache, queue, object store). Record how each is normally started and which config
   key points at it.
5. Enumerate `external_third_parties` — services owned by someone else. These are the
   things a consumer will likely need to substitute.
6. Determine `config_mechanism`, `ports_and_endpoints`, and `startup_sequence`.
7. For each component, write a `standup_notes` entry: difficulty per the definitions in
   the reference, the config it needs, and whether it is reachable from outside the
   process.
8. Emit the contract, then a short prose summary.

## Rules

- Read-only. If you want to know whether something works, you may not find out here —
  record it as an assumption.
- Do not describe test strategy, test boundaries, mocking, or fixtures. This phase
  reports facts about the system; consumers decide what to do with them.
- An empty `real_dependencies` list is a legitimate finding for a library or pure CLI.
