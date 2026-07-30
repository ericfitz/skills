---
name: state
version: 1.0.0
description: Discover how test state can be established in a project — writable data stores, factories and builders, seed tooling, test-only endpoints, ID generation, and teardown affordances. Use when planning test data setup or diagnosing test isolation problems. Emits the itest:state contract.
---

# state

Discover what this project makes possible for establishing and removing test state.

Whether state can be injected at all is a fact about the project, not a design choice.
This phase finds the facts; synthesis makes the choices.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/state-and-fixtures.md`
Doctrine: `${CLAUDE_PLUGIN_ROOT}/references/test-design.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/state.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/state.example.json`

## Usage

    /itest:state [path]

## Input

You are normally handed a `profile:stack` contract; use its `inventory` to locate
migrations, models, seed scripts, and test helpers.

You may also be handed a `profile:docs` contract. Its `domain_invariants` and `glossary`
describe what valid state actually looks like in this domain, which is what turns
`direct_write_possible` from a literal answer into a useful one: a store you can write
to but cannot write *validly* is worth reporting as such.

**Standalone invocation:** if you were not handed one, invoke `profile:stack` and use
its output. If `profile` is unavailable, locate schema sources yourself using the
tables in `references/state-and-fixtures.md`.

## Procedure

1. Locate the authoritative schema source per the schema-source table. Record it on
   each store in `schema_source`.
2. For each data store, determine `direct_write_possible` following "Determining
   whether direct writes are possible", and record `how` — the concrete mechanism a
   test would use. When it is false, `how` is `null`.
3. Collect `builders_and_factories` and `seed_tooling` present in the repo. Prefer
   what already exists over what could be written.
4. Find `test_only_endpoints` — routes or commands that exist to manipulate state for
   testing. Record what guards them, since an unguarded one is a finding worth
   reporting.
5. Determine `id_generation.origin` and write its `implications` for setup ordering.
6. Assess each teardown strategy in the enum: available or not, with evidence.
7. Record everything inferred but unconfirmed in `assumptions[]`.
8. Emit the contract, then a short prose summary.

## Rules

- Read-only. Do not connect to any data store, run migrations, or execute seed scripts.
- Report affordances, not decisions. Do not say which journeys should compose or
  inject; that is decided during synthesis.
- An honest "no direct write possible, composition only" is a valuable finding. Do not
  invent a mechanism you did not see evidence for.
