# `itest` Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `itest` plugin that discovers a project's testing reality (conventions, existing-test quality, state-establishment affordances) and synthesizes an integration test design from it — grounded in both the code and the project's own requirements documents — ending in a scenario set a future build skill can implement.

**Architecture:** Three discovery skills emit versioned JSON contracts; an orchestrator skill (`/itest:design`) preflights the `profile` plugin, runs two serial gates (`profile:stack`, then `profile:docs`), dispatches five discovery subagents in parallel, maps extracted requirements onto candidate journeys, runs a human confirmation gate on both lists, and synthesizes the plan in the main context. The plan is emitted as markdown, optionally saved, and any conflict found between a document and the code can be turned into a tracking issue or a findings document.

**Tech Stack:** Markdown skills and JSON Schema contracts. Python only for tests. No runtime code ships in this plugin.

**Spec:** `docs/superpowers/specs/2026-07-26-integration-test-design-design.md`
**Prerequisite:** `docs/superpowers/plans/2026-07-26-profile-plugin.md` must be complete. This plan depends on `tests/schema_check.py`, `tests/test_plugin_structure.py`, and the four `profile` contracts existing.

## Global Constraints

- **Python: stdlib only.** `jsonschema` is not installed. Contract tests use `tests/schema_check.py` built in the `profile` plan (Task 8).
- **Test style:** `unittest.TestCase`, matching `tests/test_dedupe.py`. Every test module starts with `sys.dont_write_bytecode = True`.
- **Test command:** `python3 -m unittest discover -s tests -t .` from the repo root. Single module: `python3 -m unittest tests.<module> -v`.
- **Lint command:** `ruff check tests/test_itest_*.py` — scoped to the files this plan creates. `itest/` ships no Python. Whole-directory linting fails on pre-existing errors that are out of scope. The root `ruff.toml` created by the profile plan (Task 1) governs the rules.
- **Branch:** create `feat/itest-plugin` before Task 1. Do not commit to `main`.
- **`itest` never invokes `profile_inventory.py`.** Inventory data arrives only inside the `stack` contract. This is the coupling rule that justifies the two-plugin split; a test enforces it.
- **`${CLAUDE_PLUGIN_ROOT}` never crosses a plugin boundary.** Cross-plugin work happens by invoking skills by name.
- **Discovery is read-only.** No skill in this plugin executes builds, tests, containers, or health checks.
- **Every contract requires `contract_version`** as a required top-level string property, matching the `profile` contracts.
- **Document/code conflicts are reported, never adjudicated.** Synthesis states the conflict, the document's claim, the code evidence, and both readings. It does not decide which is right.
- **No new issue-creation mechanism is ever built.** The conflict-disposition step uses a capability already present in the session — the `github:create-issue` skill, an issue-tracking MCP, or `gh` — or it falls back to saving a findings document. Same rule as `profile:docs` and document retrieval.
- **What the tests do not cover, stated plainly.** The `unittest` suite checks contract shapes, cross-plugin coupling, and plugin structure. Synthesis behavior — boundary selection, requirement-to-journey mapping, conflict detection, gap-map ordering — is model judgment and is exercised by no test here. Do not add an assertion that pretends otherwise.

## File Structure

```
itest/
  .claude-plugin/plugin.json
  references/
    test-design.md                    # the quality doctrine — issue vocabulary, tier rule,
                                      #   compose-vs-inject rule, assertion rules
    test-frameworks.md                # framework fingerprints, integration separation mechanisms
    state-and-fixtures.md             # ORM/migration/factory/seed signatures per ecosystem
    contracts/conventions.schema.json
    contracts/critique.schema.json
    contracts/state.schema.json
    contracts/scenario.schema.json
    contracts/examples/conventions.example.json
    contracts/examples/critique.example.json
    contracts/examples/state.example.json
    contracts/examples/scenario.example.json
  skills/
    conventions/SKILL.md
    critique/SKILL.md
    state/SKILL.md
    design/SKILL.md                   # orchestrator

tests/
  test_itest_contracts.py
  test_itest_coupling.py
```

---

### Task 1: The quality doctrine

**Files:**
- Create: `itest/references/test-design.md`
- Create: `itest/.claude-plugin/plugin.json`

**Interfaces:**
- Consumes: nothing
- Produces: the fixed `ISSUE_TYPES` vocabulary used by the `critique` contract (Task 4), the tier rule and compose-vs-inject rule used by synthesis (Task 7). Every other task in this plan references this file.

This task comes first because three later contracts encode vocabulary defined here. Writing it later means rewriting them.

- [ ] **Step 1: Write the doctrine**

`itest/references/test-design.md` must contain these five sections, with this content:

**Section 1 — "What an integration test is for."** An integration test exercises a customer-meaningful workflow across a real boundary, asserting on outcomes observable from outside the system. It is not a slower unit test.

**Section 2 — "The tier rule"** (used by synthesis step 2). Verbatim rule: *"An integration test is justified when the failure it catches arises from integration."* Followed by the qualifying list — dependency unavailable or slow; partial failure mid-sequence; concurrent access to the same entity; authorization and tenancy boundaries; data crossing a serialization boundary; transaction rollback and retry; configuration mismatch between components — and the disqualifying list — input-validation permutations; pure logic branches; formatting and presentation; error-message wording. Close with: *"Push disqualified cases down to unit tests. The most expensive tier is where combinatorial explosion does the most damage, and a suite people disable protects nothing."*

**Section 3 — "The issue vocabulary."** A table with exactly these eight `type` values, each with a definition and a one-line detection heuristic. These are the only permitted values in `critique.assessed[].issues[].type`:

| type | definition |
|---|---|
| `over-mocking` | The boundary under test is itself mocked, so the test cannot observe the integration it claims to cover |
| `implementation-detail-assertion` | Asserts on internal call sequences, private state, or structures no customer can observe |
| `non-determinism` | Depends on sleeps, wall-clock time, iteration order, or unseeded randomness |
| `shared-mutable-state` | Depends on state left behind by another test, or leaves state that affects others |
| `tautological-assertion` | Asserts something that cannot fail, or re-asserts the value just written by the test |
| `assertion-free` | Executes a flow and asserts nothing beyond absence of an exception |
| `framework-not-system` | Verifies that the framework, ORM, or library works, not that this system works |
| `missing-failure-path` | Covers only the happy path for a workflow whose failure modes matter |

**Section 4 — "Composition and injection"** (used by synthesis step 3). The five rules verbatim from the spec:
- Compose by default when the prerequisite is itself a journey under test — state is valid by construction and the create path gets extra coverage for free.
- Inject when the chain is deep enough that composition dominates runtime; or the state is unreachable through the public interface; or it belongs to a third party being stubbed; or a corrupt or edge-case state is what is under test.
- Never inject state the real system could not itself produce, unless resilience to exactly that corruption is under test. Otherwise the test asserts on fiction and passes forever.
- Composed setup must be asserted on, or fail loudly. If `create` silently half-fails, the `delete` test reports a delete bug. Failure attribution is the main hidden cost of composition, and it is payable.
- Prefer per-test isolation over hoisted shared setup, even at a runtime cost, until setup cost is measured as prohibitive. Hoisting is what introduces order dependence.

Add a closing line: *"Whatever you injected, you must be able to remove. Decide cleanup in the same step as setup."*

**Section 5 — "Assertion design."** Assert on what is observable at the chosen boundary: the response, persisted state read back through the interface, an emitted event, an observable effect on a real dependency. Never on internals. Include negative assertions ("and nothing else was modified") where a workflow could over-reach. Control determinism explicitly: freeze time, seed randomness, wait on conditions rather than sleeping, and never assert on unordered collections as if they were ordered.

- [ ] **Step 2: Write the plugin manifest**

```json
{
  "name": "itest",
  "version": "1.0.0",
  "description": "Integration test design toolkit: discover a project's test conventions (conventions), assess the quality of the tests it already has (critique), find its state-establishment affordances (state), and synthesize a full integration test design from customer journeys (design). Read-only discovery; requires the profile plugin.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 3: Commit**

```bash
git add itest/references/test-design.md itest/.claude-plugin/plugin.json
git commit -m "feat(itest): quality doctrine and plugin manifest"
```

---

### Task 2: Discovery contracts and their tests

**Files:**
- Create: `itest/references/contracts/conventions.schema.json`
- Create: `itest/references/contracts/critique.schema.json`
- Create: `itest/references/contracts/state.schema.json`
- Create: `itest/references/contracts/examples/conventions.example.json`
- Create: `itest/references/contracts/examples/critique.example.json`
- Create: `itest/references/contracts/examples/state.example.json`
- Test: `tests/test_itest_contracts.py`

**Interfaces:**
- Consumes: `tests/schema_check.py` (`validate(instance, schema, path="$") -> list[str]`) from the profile plan
- Produces: the three discovery contracts consumed by the orchestrator's synthesis in Task 7

- [ ] **Step 1: Write the failing test**

```python
# tests/test_itest_contracts.py
import json
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from schema_check import validate

REPO = Path(__file__).resolve().parents[1]
CONTRACTS = REPO / "itest" / "references" / "contracts"
DOCTRINE = REPO / "itest" / "references" / "test-design.md"

ISSUE_TYPES = [
    "over-mocking",
    "implementation-detail-assertion",
    "non-determinism",
    "shared-mutable-state",
    "tautological-assertion",
    "assertion-free",
    "framework-not-system",
    "missing-failure-path",
]


class TestItestContracts(unittest.TestCase):
    def test_expected_contracts_exist_with_metadata(self):
        names = sorted(p.name for p in CONTRACTS.glob("*.schema.json"))
        self.assertEqual(names, [
            "conventions.schema.json", "critique.schema.json",
            "scenario.schema.json", "state.schema.json",
        ])
        for path in CONTRACTS.glob("*.schema.json"):
            with self.subTest(schema=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["type"], "object")
                self.assertIn("contract_version", schema["required"])

    def test_every_contract_has_a_validating_example(self):
        for path in sorted(CONTRACTS.glob("*.schema.json")):
            name = path.name.replace(".schema.json", "")
            example = CONTRACTS / "examples" / ("%s.example.json" % name)
            with self.subTest(contract=name):
                self.assertTrue(example.exists(), "missing example for %s" % name)
                errors = validate(json.loads(example.read_text(encoding="utf-8")),
                                  json.loads(path.read_text(encoding="utf-8")))
                self.assertEqual(errors, [])

    def test_critique_issue_types_match_the_doctrine(self):
        schema = json.loads((CONTRACTS / "critique.schema.json").read_text(encoding="utf-8"))
        enum = (schema["properties"]["assessed"]["items"]["properties"]["issues"]
                ["items"]["properties"]["type"]["enum"])
        self.assertEqual(sorted(enum), sorted(ISSUE_TYPES))

    def test_doctrine_documents_every_issue_type(self):
        text = DOCTRINE.read_text(encoding="utf-8")
        for issue in ISSUE_TYPES:
            with self.subTest(issue=issue):
                self.assertIn(issue, text)

    def test_doctrine_states_the_tier_rule_and_composition_rules(self):
        text = DOCTRINE.read_text(encoding="utf-8").lower()
        self.assertIn("arises from integration", text)
        self.assertIn("valid by construction", text)
        self.assertIn("could not itself produce", text)
        self.assertIn("must be asserted on", text)

    def test_conventions_contract_requires_integration_separation(self):
        schema = json.loads(
            (CONTRACTS / "conventions.schema.json").read_text(encoding="utf-8"))
        self.assertIn("integration_separation", schema["required"])
        separation = schema["properties"]["integration_separation"]
        self.assertEqual(sorted(separation["required"]), ["how_to_add", "mechanism"])

    def test_state_contract_records_whether_injection_is_possible(self):
        schema = json.loads((CONTRACTS / "state.schema.json").read_text(encoding="utf-8"))
        store = schema["properties"]["writable_stores"]["items"]
        self.assertIn("direct_write_possible", store["required"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_itest_contracts -v`
Expected: FAIL — the contracts directory does not exist yet.

- [ ] **Step 3: Write `conventions.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "itest:conventions contract",
  "type": "object",
  "required": ["contract_version", "frameworks", "runner_commands", "integration_separation", "house_style"],
  "properties": {
    "contract_version": { "type": "string" },
    "frameworks": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "language", "evidence"],
        "properties": {
          "name": { "type": "string" },
          "language": { "type": "string" },
          "scope": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "runner_commands": {
      "type": "object",
      "properties": {
        "unit": { "type": ["string", "null"] },
        "integration": { "type": ["string", "null"] },
        "all": { "type": ["string", "null"] }
      }
    },
    "integration_separation": {
      "type": "object",
      "required": ["mechanism", "how_to_add"],
      "properties": {
        "mechanism": {
          "enum": ["build-tag", "marker", "directory", "filename-suffix",
                   "separate-config", "separate-project", "none", "unknown"]
        },
        "how_to_add": { "type": "string" },
        "evidence": { "type": "array", "items": { "type": "string" } }
      }
    },
    "house_style": {
      "type": "object",
      "properties": {
        "naming": { "type": ["string", "null"] },
        "layout": { "type": ["string", "null"] },
        "fixture_mechanism": { "type": ["string", "null"] },
        "setup_teardown": { "type": ["string", "null"] },
        "assertion_style": { "type": ["string", "null"] }
      }
    },
    "reusable_helpers": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "path", "purpose"],
        "properties": {
          "name": { "type": "string" },
          "path": { "type": "string" },
          "purpose": { "type": "string" },
          "signature": { "type": ["string", "null"] }
        }
      }
    },
    "existing_fixtures": { "type": "array", "items": { "type": "string" } },
    "ci_invocation": { "type": ["string", "null"] },
    "convention_gaps": { "type": "array", "items": { "type": "string" } }
  }
}
```

- [ ] **Step 4: Write `critique.schema.json`**

The `type` enum must contain exactly the eight values from the doctrine, in the order listed there:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "itest:critique contract",
  "type": "object",
  "required": ["contract_version", "assessed", "systemic_issues"],
  "properties": {
    "contract_version": { "type": "string" },
    "assessed": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["path", "verdict", "issues", "recommendation"],
        "properties": {
          "path": { "type": "string" },
          "verdict": { "enum": ["sound", "weak", "misleading"] },
          "covers": { "type": "array", "items": { "type": "string" } },
          "issues": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["type", "severity", "evidence"],
              "properties": {
                "type": {
                  "enum": ["over-mocking", "implementation-detail-assertion",
                           "non-determinism", "shared-mutable-state",
                           "tautological-assertion", "assertion-free",
                           "framework-not-system", "missing-failure-path"]
                },
                "severity": { "enum": ["high", "medium", "low"] },
                "evidence": { "type": "string" }
              }
            }
          },
          "recommendation": { "enum": ["keep", "repair", "replace", "delete"] }
        }
      }
    },
    "systemic_issues": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["summary", "affected_count"],
        "properties": {
          "summary": { "type": "string" },
          "affected_count": { "type": "integer" }
        }
      }
    }
  }
}
```

- [ ] **Step 5: Write `state.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "itest:state contract",
  "type": "object",
  "required": ["contract_version", "writable_stores", "id_generation", "assumptions"],
  "properties": {
    "contract_version": { "type": "string" },
    "writable_stores": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "direct_write_possible", "how", "evidence"],
        "properties": {
          "name": { "type": "string" },
          "direct_write_possible": { "type": "boolean" },
          "how": { "type": ["string", "null"] },
          "schema_source": { "type": ["string", "null"] },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "builders_and_factories": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "path", "produces"],
        "properties": {
          "name": { "type": "string" },
          "path": { "type": "string" },
          "produces": { "type": "string" }
        }
      }
    },
    "seed_tooling": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["name", "invocation"],
        "properties": {
          "name": { "type": "string" },
          "invocation": { "type": "string" },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "test_only_endpoints": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["endpoint", "purpose", "guarded_by"],
        "properties": {
          "endpoint": { "type": "string" },
          "purpose": { "type": "string" },
          "guarded_by": { "type": ["string", "null"] }
        }
      }
    },
    "id_generation": {
      "type": "object",
      "required": ["origin"],
      "properties": {
        "origin": { "enum": ["client", "server", "mixed", "unknown"] },
        "implications": { "type": ["string", "null"] }
      }
    },
    "teardown_affordances": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["strategy", "available"],
        "properties": {
          "strategy": {
            "enum": ["transaction-rollback", "truncate", "namespacing",
                     "ephemeral-container", "delete-via-api", "none"]
          },
          "available": { "type": "boolean" },
          "evidence": { "type": "array", "items": { "type": "string" } }
        }
      }
    },
    "assumptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["claim", "why_unconfirmed"],
        "properties": {
          "claim": { "type": "string" },
          "why_unconfirmed": { "type": "string" }
        }
      }
    }
  }
}
```

- [ ] **Step 6: Write the three examples**

All three describe the same imaginary Go HTTP order service used in the `profile` examples, so the set reads coherently.

```json
// itest/references/contracts/examples/conventions.example.json
{
  "contract_version": "1.0.0",
  "frameworks": [
    { "name": "go-test", "language": "go", "scope": "all tests",
      "evidence": ["internal/http/handler_test.go:1"] }
  ],
  "runner_commands": {
    "unit": "go test ./...",
    "integration": "go test -tags=integration ./...",
    "all": "go test -tags=integration ./..."
  },
  "integration_separation": {
    "mechanism": "build-tag",
    "how_to_add": "Add '//go:build integration' as the first line of the file, before the package clause.",
    "evidence": ["internal/store/store_integration_test.go:1", ".github/workflows/test.yml:22"]
  },
  "house_style": {
    "naming": "TestXxx_Scenario",
    "layout": "test files sit beside the code under test",
    "fixture_mechanism": "t.Helper() constructors returning cleanup funcs",
    "setup_teardown": "t.Cleanup",
    "assertion_style": "stdlib if/t.Fatalf, no assertion library"
  },
  "reusable_helpers": [
    { "name": "newTestServer", "path": "internal/http/testing.go",
      "purpose": "starts the HTTP service against a live database",
      "signature": "func newTestServer(t *testing.T) (*httptest.Server, func())" }
  ],
  "existing_fixtures": ["testdata/orders.json"],
  "ci_invocation": "go test -tags=integration ./...",
  "convention_gaps": ["No documented way to run a single integration test in isolation."]
}
```

```json
// itest/references/contracts/examples/critique.example.json
{
  "contract_version": "1.0.0",
  "assessed": [
    {
      "path": "internal/store/store_integration_test.go",
      "verdict": "misleading",
      "covers": ["J1"],
      "issues": [
        { "type": "over-mocking", "severity": "high",
          "evidence": "store_integration_test.go:31 replaces the database with an in-memory fake, so the integration it claims to test never runs" },
        { "type": "missing-failure-path", "severity": "medium",
          "evidence": "only the successful insert is exercised; constraint violations are never asserted" }
      ],
      "recommendation": "replace"
    },
    {
      "path": "internal/http/handler_test.go",
      "verdict": "sound",
      "covers": [],
      "issues": [],
      "recommendation": "keep"
    }
  ],
  "systemic_issues": [
    { "summary": "Tests named *_integration_test.go mock their primary dependency, so the integration tier is nominal only.",
      "affected_count": 3 }
  ]
}
```

```json
// itest/references/contracts/examples/state.example.json
{
  "contract_version": "1.0.0",
  "writable_stores": [
    { "name": "postgres", "direct_write_possible": true,
      "how": "database/sql connection using DATABASE_URL, same credentials as the service",
      "schema_source": "migrations/0003_orders.sql",
      "evidence": ["migrations/0003_orders.sql:1", "internal/store/store.go:18"] }
  ],
  "builders_and_factories": [
    { "name": "newOrder", "path": "internal/store/testing.go",
      "produces": "a persisted order row with defaults" }
  ],
  "seed_tooling": [
    { "name": "migrate", "invocation": "make migrate",
      "evidence": ["Makefile:14"] }
  ],
  "test_only_endpoints": [],
  "id_generation": {
    "origin": "server",
    "implications": "Tests cannot choose ids; prerequisite state must be created first and its id captured."
  },
  "teardown_affordances": [
    { "strategy": "transaction-rollback", "available": false,
      "evidence": ["internal/store/store.go:44"] },
    { "strategy": "truncate", "available": true, "evidence": ["Makefile:18"] }
  ],
  "assumptions": [
    { "claim": "the migrations directory is the complete schema",
      "why_unconfirmed": "discovery is read-only; no database was inspected" }
  ]
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_itest_contracts -v`
Expected: FAIL on `test_expected_contracts_exist_with_metadata` only, because `scenario.schema.json` arrives in Task 6. All other tests PASS. This is the expected intermediate state; do not weaken the test.

- [ ] **Step 8: Commit**

```bash
git add itest/references/contracts tests/test_itest_contracts.py
git commit -m "feat(itest): discovery contracts with doctrine-linked issue vocabulary"
```

---

### Task 3: `itest:conventions` skill and framework reference

**Files:**
- Create: `itest/skills/conventions/SKILL.md`
- Create: `itest/references/test-frameworks.md`

**Interfaces:**
- Consumes: the `profile:stack` contract, including its embedded `inventory` (specifically `test_files`, `test_dirs`, `test_config`, `ci`)
- Produces: the `conventions` contract

- [ ] **Step 1: Write the framework reference**

`itest/references/test-frameworks.md` must contain:

- A **fingerprint table**: per ecosystem, the frameworks and how to recognize each from imports and config — Python (`pytest`, `unittest`, `nose2`); Go (stdlib `testing`, `testify`, `ginkgo`); JS/TS (`jest`, `vitest`, `mocha`, `playwright`, `cypress`); Java (`junit4`, `junit5`, `testng`); Ruby (`rspec`, `minitest`); C# (`xunit`, `nunit`); Rust (built-in `#[test]`, `cargo nextest`).
- An **integration separation table** mapping each `mechanism` enum value to its concrete form per ecosystem, and to the exact text of `how_to_add`: Go build tags (`//go:build integration` first line, before `package`); pytest markers (`@pytest.mark.integration` plus a `markers` entry in config); directory conventions (`tests/integration/`); filename suffixes (`*.integration.test.ts`); separate config (`vitest.integration.config.ts`, a second `tox` env, a Maven failsafe profile); separate project or module.
- A section **"Finding the runner commands"**: read CI workflows first (they show what actually runs), then Makefile/justfile targets, then `package.json` scripts, then config files, then the ecosystem default. Record where each command came from.
- A section **"What counts as a reusable helper"**: a constructor that starts the system or a dependency; a factory that builds a valid domain object; a client wrapper for the system's public interface; an assertion helper on domain state. Not: generic string utilities, or anything private to one test file.
- A closing rule, verbatim: *"If you cannot determine how a new integration test would be picked up by the runner, set `mechanism` to `unknown` and say so in `convention_gaps`. A confident wrong answer here makes every test that follows unrunnable."*

- [ ] **Step 2: Write the skill**

```markdown
---
name: conventions
version: 1.0.0
description: Determine how tests are written and run in a project — frameworks, runner commands, how integration tests are separated from unit tests, house style, and reusable fixtures and helpers. Use before writing or designing tests in an unfamiliar codebase. Emits the itest:conventions contract.
---

# conventions

Determine how this project writes and runs tests, so new tests match it and get run.

Reference: `${CLAUDE_PLUGIN_ROOT}/references/test-frameworks.md`
Contract: `${CLAUDE_PLUGIN_ROOT}/references/contracts/conventions.schema.json`
Example: `${CLAUDE_PLUGIN_ROOT}/references/contracts/examples/conventions.example.json`

## Usage

    /itest:conventions [path]

## Input

You are normally handed a `profile:stack` contract. Use its `inventory` for
`test_files`, `test_dirs`, `test_config`, and `ci`.

You may also be handed a `profile:docs` contract. Its corpus often contains a
CONTRIBUTING file or a testing guide, which is the most direct statement of house style
and runner commands available anywhere. Prefer it over inference — then check it against
what CI actually runs, because guides go stale and CI does not.

**Standalone invocation:** if you were not handed one, invoke the `profile:stack`
skill and use its output. If the `profile` plugin is not available, read the repo
directly using the fingerprint tables in `references/test-frameworks.md`, and say
in your summary that you ran without an inventory.

Never invoke `profile`'s inventory script by path. Inventory data reaches this
plugin only through the `stack` contract.

## Procedure

1. Identify `frameworks` from imports in the census's test files and from
   `test_config`, using the fingerprint table.
2. Determine `runner_commands` following the source order in "Finding the runner
   commands". CI is the strongest evidence: it shows what actually runs.
3. Determine `integration_separation` — the single most consequential output. Find
   how existing integration tests are distinguished, and write `how_to_add` as a
   concrete instruction someone can follow without reading anything else. If nothing
   in the repo separates them, `mechanism` is `none`; if you cannot tell, it is
   `unknown` and goes in `convention_gaps`.
4. Read enough test files to describe `house_style` accurately — naming, layout,
   fixture mechanism, setup and teardown, assertion style.
5. Collect `reusable_helpers` per "What counts as a reusable helper", with real
   signatures. Downstream work reuses these instead of inventing parallel fixtures.
6. Record `convention_gaps` — anything a newcomer would get wrong.
7. Emit the contract, then a short prose summary.

## Rules

- Read-only. Do not run the test suite.
- Describe what this repo does, not what it should do. Quality assessment belongs to
  `/itest:critique`.
- Every framework and separation claim carries `file:line` evidence.
```

- [ ] **Step 3: Verify structure**

Run: `python3 -m unittest tests.test_plugin_structure -v`
Expected: FAIL only on marketplace registration (Task 8). All `${CLAUDE_PLUGIN_ROOT}` references must resolve; fix any that do not.

- [ ] **Step 4: Commit**

```bash
git add itest/skills/conventions itest/references/test-frameworks.md
git commit -m "feat(itest): conventions skill and test-frameworks reference"
```

---

### Task 4: `itest:critique` skill

**Files:**
- Create: `itest/skills/critique/SKILL.md`

**Interfaces:**
- Consumes: the `profile:stack` contract's `inventory.test_files`, and `references/test-design.md`
- Produces: the `critique` contract

- [ ] **Step 1: Write the skill**

```markdown
---
name: critique
version: 1.0.0
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
```

- [ ] **Step 2: Verify structure**

Run: `python3 -m unittest tests.test_plugin_structure -v`
Expected: FAIL only on marketplace registration. All plugin-root references resolve.

- [ ] **Step 3: Commit**

```bash
git add itest/skills/critique
git commit -m "feat(itest): critique skill for existing-test quality assessment"
```

---

### Task 5: `itest:state` skill and state reference

**Files:**
- Create: `itest/skills/state/SKILL.md`
- Create: `itest/references/state-and-fixtures.md`

**Interfaces:**
- Consumes: the `profile:stack` contract's `inventory`
- Produces: the `state` contract

- [ ] **Step 1: Write the state reference**

`itest/references/state-and-fixtures.md` must contain:

- A **schema-source table**: where the authoritative data shape lives per ecosystem — SQL migration directories (`migrations/`, `db/migrate/`, `alembic/versions/`), ORM model modules (Django models, SQLAlchemy declarative, GORM structs, ActiveRecord, Prisma schema, Ent schema), and generated schema dumps (`schema.rb`, `structure.sql`).
- A **factory/builder table**: `factory_boy`, `model_bakery`, `factory_bot`, `faker`, `testcontainers` modules, Go table-driven helper constructors, `@faker-js`, Prisma seed scripts.
- A **seed tooling table**: migration runners (`alembic`, `golang-migrate`, `flyway`, `liquibase`, `knex`, `prisma migrate`), plus Makefile/justfile targets containing `seed`, `fixtures`, or `migrate`.
- A section **"Determining whether direct writes are possible"**: does a test process have credentials and network access to the store, is the store reachable outside the service process, is there a connection string in test config or CI env, does the ORM ship a test-session helper. Absence of any of these means `direct_write_possible` is false and composition is the only route.
- A section **"ID generation and why it matters"**: server-generated ids mean prerequisite entities must be created first and their ids captured, so composition order is forced; client-generated ids allow injection with known ids and simpler assertions.
- A section **"Teardown affordances"**, defining each `strategy` enum value and how to recognize it: transaction rollback (test wraps in a transaction the system honors), truncate (a target or helper that empties tables), namespacing (per-test tenant, schema, or key prefix), ephemeral container (a fresh dependency instance per run), delete-via-api (the public interface can remove what it created), none.
- A closing rule, verbatim: *"Report affordances, not decisions. Whether to compose or inject is decided during synthesis against the doctrine; your job is to say what this project makes possible."*

- [ ] **Step 2: Write the skill**

```markdown
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
```

- [ ] **Step 3: Verify structure**

Run: `python3 -m unittest tests.test_plugin_structure -v`
Expected: FAIL only on marketplace registration.

- [ ] **Step 4: Commit**

```bash
git add itest/skills/state itest/references/state-and-fixtures.md
git commit -m "feat(itest): state skill and state-and-fixtures reference"
```

---

### Task 6: The scenario contract

**Files:**
- Create: `itest/references/contracts/scenario.schema.json`
- Create: `itest/references/contracts/examples/scenario.example.json`
- Modify: `tests/test_itest_contracts.py` (add scenario-specific assertions)

**Interfaces:**
- Consumes: every discovery contract
- Produces: the handoff seam. A future build skill consumes exactly this and nothing else from a design session.

- [ ] **Step 1: Add the failing scenario assertions**

Append to `tests/test_itest_contracts.py`:

```python
class TestScenarioContract(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(
            (CONTRACTS / "scenario.schema.json").read_text(encoding="utf-8"))
        self.scenario = self.schema["properties"]["scenarios"]["items"]

    def test_scenario_carries_placement_and_runner(self):
        required = self.scenario["required"]
        self.assertIn("placement", required)
        self.assertIn("runner_invocation", required)
        placement = self.scenario["properties"]["placement"]["required"]
        self.assertEqual(sorted(placement), ["file_path", "marker_or_tag", "naming"])

    def test_preconditions_record_method_and_assertion(self):
        precondition = self.scenario["properties"]["preconditions"]["items"]
        self.assertEqual(precondition["properties"]["method"]["enum"],
                         ["compose", "inject"])
        self.assertIn("assert_established", precondition["required"])

    def test_open_assumptions_survive_into_every_scenario(self):
        self.assertIn("open_assumptions", self.scenario["required"])

    def test_scenario_records_provenance_and_requirement_traceability(self):
        required = self.scenario["required"]
        self.assertIn("provenance", required)
        self.assertIn("requirement_ids", required)
        self.assertEqual(self.scenario["properties"]["provenance"]["enum"],
                         ["journey", "requirement", "both"])

    def test_cross_cutting_scenarios_may_have_no_journey(self):
        """A requirement no journey owns still produces a scenario."""
        self.assertEqual(self.scenario["properties"]["journey_id"]["type"],
                         ["string", "null"])

    def test_example_has_a_composed_and_an_injected_precondition(self):
        example = json.loads(
            (CONTRACTS / "examples" / "scenario.example.json").read_text(encoding="utf-8"))
        methods = {p["method"]
                   for scenario in example["scenarios"]
                   for p in scenario["preconditions"]}
        self.assertEqual(methods, {"compose", "inject"})

    def test_example_demonstrates_a_cross_cutting_scenario(self):
        example = json.loads(
            (CONTRACTS / "examples" / "scenario.example.json").read_text(encoding="utf-8"))
        by_provenance = {s["provenance"]: s for s in example["scenarios"]}
        self.assertIn("requirement", by_provenance)
        self.assertIsNone(by_provenance["requirement"]["journey_id"])
        self.assertTrue(by_provenance["requirement"]["requirement_ids"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_itest_contracts -v`
Expected: FAIL — `scenario.schema.json` does not exist.

- [ ] **Step 3: Write `scenario.schema.json`**

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "itest scenario set — the handoff seam to a build phase",
  "type": "object",
  "required": ["contract_version", "boundary", "scenarios"],
  "properties": {
    "contract_version": { "type": "string" },
    "boundary": {
      "type": "object",
      "required": ["description", "rationale", "real", "stubbed"],
      "properties": {
        "description": { "type": "string" },
        "rationale": { "type": "string" },
        "real": { "type": "array", "items": { "type": "string" } },
        "stubbed": { "type": "array", "items": { "type": "string" } }
      }
    },
    "scenarios": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "journey_id", "title", "priority", "boundary",
                     "provenance", "requirement_ids", "preconditions", "steps",
                     "assertions", "dependencies", "isolation", "placement",
                     "runner_invocation", "open_assumptions"],
        "properties": {
          "id": { "type": "string" },
          "journey_id": { "type": ["string", "null"] },
          "title": { "type": "string" },
          "priority": { "enum": ["p0", "p1", "p2"] },
          "est_cost": { "enum": ["low", "medium", "high"] },
          "boundary": { "type": "string" },
          "provenance": { "enum": ["journey", "requirement", "both"] },
          "requirement_ids": { "type": "array", "items": { "type": "string" } },
          "preconditions": {
            "type": "array",
            "items": {
              "type": "object",
              "required": ["state", "method", "via", "assert_established"],
              "properties": {
                "state": { "type": "string" },
                "method": { "enum": ["compose", "inject"] },
                "via": { "type": "string" },
                "assert_established": { "type": "string" },
                "rationale": { "type": "string" }
              }
            }
          },
          "steps": { "type": "array", "items": { "type": "string" } },
          "assertions": { "type": "array", "items": { "type": "string" } },
          "negative_assertions": { "type": "array", "items": { "type": "string" } },
          "dependencies": {
            "type": "object",
            "required": ["real", "stubbed"],
            "properties": {
              "real": { "type": "array", "items": { "type": "string" } },
              "stubbed": { "type": "array", "items": { "type": "string" } }
            }
          },
          "isolation": {
            "type": "object",
            "required": ["strategy", "cleanup"],
            "properties": {
              "strategy": {
                "enum": ["transaction-rollback", "truncate", "namespacing",
                         "ephemeral-container", "delete-via-api", "none"]
              },
              "cleanup": { "type": "array", "items": { "type": "string" } }
            }
          },
          "determinism_controls": { "type": "array", "items": { "type": "string" } },
          "fixtures_to_reuse": { "type": "array", "items": { "type": "string" } },
          "new_helpers_needed": { "type": "array", "items": { "type": "string" } },
          "placement": {
            "type": "object",
            "required": ["file_path", "naming", "marker_or_tag"],
            "properties": {
              "file_path": { "type": "string" },
              "naming": { "type": "string" },
              "marker_or_tag": { "type": ["string", "null"] }
            }
          },
          "runner_invocation": { "type": "string" },
          "open_assumptions": { "type": "array", "items": { "type": "string" } }
        }
      }
    }
  }
}
```

- [ ] **Step 4: Write the example**

Continues the order-service example, and reuses the requirement ids `R1` and `R2` from
`profile`'s `docs.example.json` so the two plugins' examples read as one story. It must
demonstrate the doctrine rather than describe it: one composed and one injected
precondition, and one cross-cutting scenario that came from a requirement no journey owns:

```json
{
  "contract_version": "1.0.0",
  "boundary": {
    "description": "The api service running in the compose stack, driven over HTTP, with a real Postgres.",
    "rationale": "Compose declares both services and the api is externally reachable; Stripe is the only dependency that cannot be run locally.",
    "real": ["api", "postgres"],
    "stubbed": ["stripe"]
  },
  "scenarios": [
    {
      "id": "S1",
      "journey_id": "J2",
      "title": "Cancelling a placed order marks it cancelled and refunds nothing else",
      "priority": "p0",
      "est_cost": "medium",
      "boundary": "HTTP against the api service with a real Postgres; Stripe stubbed",
      "provenance": "both",
      "requirement_ids": ["R1"],
      "preconditions": [
        {
          "state": "an order exists for the acting customer",
          "method": "compose",
          "via": "POST /orders, capturing the returned order id",
          "assert_established": "response is 201 and the body contains a non-empty id",
          "rationale": "Order creation is journey J1, already under test, and ids are server-generated so they cannot be chosen."
        },
        {
          "state": "the order is older than the 24-hour free-cancellation window",
          "method": "inject",
          "via": "UPDATE orders SET created_at = now() - interval '48 hours' WHERE id = $1",
          "assert_established": "one row updated",
          "rationale": "The state is produced only by the passage of time and is unreachable through the public interface."
        }
      ],
      "steps": [
        "POST /orders/{id}/cancel as the owning customer"
      ],
      "assertions": [
        "response is 200",
        "GET /orders/{id} reports status 'cancelled'",
        "the stubbed Stripe client received exactly one refund call for the order total"
      ],
      "negative_assertions": [
        "no other order belonging to the customer changed status"
      ],
      "dependencies": { "real": ["postgres"], "stubbed": ["stripe"] },
      "isolation": {
        "strategy": "truncate",
        "cleanup": ["truncate orders, order_items, customers after the test"]
      },
      "determinism_controls": [
        "inject the age rather than sleeping",
        "poll GET /orders/{id} until status settles, with a bounded timeout; never sleep a fixed duration"
      ],
      "fixtures_to_reuse": ["newTestServer (internal/http/testing.go)"],
      "new_helpers_needed": ["a stub Stripe client recording refund calls"],
      "placement": {
        "file_path": "internal/http/cancel_order_integration_test.go",
        "naming": "TestCancelOrder_AfterFreeWindow",
        "marker_or_tag": "//go:build integration"
      },
      "runner_invocation": "go test -tags=integration ./internal/http/ -run TestCancelOrder_AfterFreeWindow",
      "open_assumptions": [
        "the compose stack starts cleanly on a developer machine",
        "the migrations directory is the complete schema"
      ]
    },
    {
      "id": "S2",
      "journey_id": null,
      "title": "Every response carries a non-empty X-Request-Id header",
      "priority": "p1",
      "est_cost": "low",
      "boundary": "HTTP against the api service with a real Postgres; Stripe stubbed",
      "provenance": "requirement",
      "requirement_ids": ["R2"],
      "preconditions": [
        {
          "state": "an order exists so a 200 and a 404 can both be exercised",
          "method": "compose",
          "via": "POST /orders, capturing the returned order id",
          "assert_established": "response is 201 and the body contains a non-empty id",
          "rationale": "The requirement is about every response, so the check needs both a hit and a miss."
        }
      ],
      "steps": [
        "GET /orders/{id} for the created order",
        "GET /orders/{id} for an id that does not exist"
      ],
      "assertions": [
        "the 200 response carries a non-empty X-Request-Id header",
        "the 404 response carries a non-empty X-Request-Id header"
      ],
      "negative_assertions": [
        "the two responses do not carry the same X-Request-Id"
      ],
      "dependencies": { "real": ["postgres"], "stubbed": ["stripe"] },
      "isolation": {
        "strategy": "truncate",
        "cleanup": ["truncate orders, order_items, customers after the test"]
      },
      "determinism_controls": [
        "assert the header is non-empty rather than asserting a specific value"
      ],
      "fixtures_to_reuse": ["newTestServer (internal/http/testing.go)"],
      "new_helpers_needed": [],
      "placement": {
        "file_path": "internal/http/request_id_integration_test.go",
        "naming": "TestResponses_CarryRequestId",
        "marker_or_tag": "//go:build integration"
      },
      "runner_invocation": "go test -tags=integration ./internal/http/ -run TestResponses_CarryRequestId",
      "open_assumptions": [
        "the compose stack starts cleanly on a developer machine"
      ]
    }
  ]
}
```

`S2` is the worked example of the cross-cutting case: it came from requirement `R2`,
which the gate approved because it mapped to no journey, so its `journey_id` is `null`
and its `provenance` is `requirement`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_itest_contracts -v`
Expected: PASS, all tests including `test_expected_contracts_exist_with_metadata`, which now finds all four contracts.

- [ ] **Step 6: Commit**

```bash
git add itest/references/contracts tests/test_itest_contracts.py
git commit -m "feat(itest): scenario contract defining the build handoff seam"
```

---

### Task 7: `itest:design` orchestrator

**Files:**
- Create: `itest/skills/design/SKILL.md`
- Test: `tests/test_itest_coupling.py`

**Interfaces:**
- Consumes: `profile:stack`, `profile:topology`, `profile:journeys`, `itest:conventions`, `itest:critique`, `itest:state`
- Produces: the conversational plan, the markdown emission, and a scenario set conforming to `scenario.schema.json`

- [ ] **Step 1: Write the failing coupling test**

This test enforces the architectural rules that the split depends on — the ones a reviewer cannot check by eye across seven files.

```python
# tests/test_itest_coupling.py
import re
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
ITEST_SKILLS = sorted((REPO / "itest" / "skills").glob("*/SKILL.md"))
PROFILE_SKILLS = sorted((REPO / "profile" / "skills").glob("*/SKILL.md"))


class TestCrossPluginCoupling(unittest.TestCase):
    def test_itest_skills_exist(self):
        self.assertEqual([p.parent.name for p in ITEST_SKILLS],
                         ["conventions", "critique", "design", "state"])

    def test_itest_never_references_the_inventory_script(self):
        for skill in ITEST_SKILLS:
            with self.subTest(skill=skill.parent.name):
                text = skill.read_text(encoding="utf-8")
                self.assertNotIn("profile_inventory.py", text.replace(
                    "Never invoke `profile`'s inventory script by path.", ""))

    def test_itest_plugin_root_refs_stay_inside_itest(self):
        for skill in ITEST_SKILLS:
            for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[A-Za-z0-9_./-]+)",
                                  skill.read_text(encoding="utf-8")):
                with self.subTest(skill=skill.parent.name, ref=ref):
                    self.assertTrue((REPO / "itest" / ref.lstrip("/")).exists())

    def test_profile_skills_never_reference_itest(self):
        for skill in PROFILE_SKILLS:
            with self.subTest(skill=skill.parent.name):
                self.assertNotIn("itest", skill.read_text(encoding="utf-8"))

    def test_design_preflights_all_four_profile_skills(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8")
        for name in ("profile:stack", "profile:docs", "profile:topology",
                     "profile:journeys"):
            with self.subTest(skill=name):
                self.assertIn(name, text)

    def test_design_documents_the_human_gate(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("gate", text)
        self.assertIn("subagents cannot ask", text)

    def test_design_maps_requirements_to_journeys_before_the_gate(self):
        """Cross-cutting requirements only exist relative to the journey set, so the
        mapping has to happen in the main context before the user is asked."""
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("gate prep", text)
        self.assertIn("cross-cutting", text)

    def test_design_offers_conflict_disposition_without_building_a_mechanism(self):
        text = (REPO / "itest" / "skills" / "design" / "SKILL.md").read_text(
            encoding="utf-8").lower()
        self.assertIn("doc_code_conflicts", text)
        self.assertIn("github:create-issue", text)
        self.assertIn("no new issue-creation mechanism", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_itest_coupling -v`
Expected: FAIL on `test_itest_skills_exist` — `design/SKILL.md` does not exist yet.

- [ ] **Step 3: Write the orchestrator**

```markdown
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
```

- [ ] **Step 4: Run the coupling test**

Run: `python3 -m unittest tests.test_itest_coupling -v`
Expected: PASS, 8 tests

- [ ] **Step 5: Commit**

```bash
git add itest/skills/design tests/test_itest_coupling.py
git commit -m "feat(itest): design orchestrator with docs gate, gate prep, and synthesis"
```

---

### Task 8: Marketplace registration and full verification

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`

**Interfaces:**
- Consumes: everything above
- Produces: an installable `itest` plugin and a green suite

- [ ] **Step 1: Register in the marketplace**

Add to the `plugins` array in `.claude-plugin/marketplace.json`, after the `profile` entry:

```json
{ "name": "itest", "description": "Integration test design toolkit: discover a project's test conventions and how integration tests are separated (conventions), assess the quality of existing tests for over-mocking and misleading coverage (critique), find state-establishment and teardown affordances (state), and synthesize a prioritized scenario plan from confirmed customer journeys and documented requirements (design). Reports conflicts between what the documentation requires and what the code does. Read-only discovery; requires the profile plugin.", "source": "./itest", "category": "development" }
```

- [ ] **Step 2: Add the README section**

Insert after the `## profile` section:

```markdown
## itest — integration test design

`design` (orchestrates the whole workflow) · `conventions` (frameworks, runner
commands, how integration tests are separated) · `critique` (quality assessment of
existing tests — over-mocking, implementation-detail assertions, non-determinism) ·
`state` (writable stores, factories, seed tooling, teardown affordances).

Requires the `profile` plugin, which supplies stack, documented requirements,
deployment topology, and candidate user journeys. Scenarios trace back to the
requirement they cover, and requirements no journey owns are surfaced separately
rather than dropped. Where a normative document and the code disagree, the plan
reports the conflict and both readings and offers to open a tracking issue.

Discovery is read-only: nothing is built, booted, or run, and every unproven
inference is carried into the plan as an explicit assumption. Output is a scenario
set conforming to `references/contracts/scenario.schema.json`, the handoff seam to
a future build phase.
```

- [ ] **Step 3: Run the full suite**

Run: `python3 -m unittest discover -s tests -t . 2>&1 | tail -5`
Expected: `OK`

- [ ] **Step 4: Lint**

Run: `ruff check tests/test_itest_*.py`
Expected: `All checks passed!`

- [ ] **Step 5: Verify both plugins are registered and structurally sound**

Run: `python3 -m unittest tests.test_plugin_structure tests.test_itest_coupling -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "feat(itest): marketplace registration and README"
```

---

## Completion

`itest` is done when:

- `python3 -m unittest discover -s tests -t .` reports `OK`
- `ruff check tests/test_itest_*.py` passes
- All four `itest` contracts have validating examples, including a scenario example demonstrating both a composed and an injected precondition, and a cross-cutting scenario with `provenance: requirement` and a null `journey_id`
- `tests/test_itest_coupling.py` passes, proving `itest` never reaches into `profile` by path, `profile` never mentions `itest`, and the orchestrator preflights all four `profile` phases, prepares the gate, and offers conflict disposition without building an issue-creation mechanism
- Both plugins appear in `.claude-plugin/marketplace.json` and `README.md`

## Deferred

The build skill that implements scenarios is out of scope, as specified. Its input is
`references/contracts/scenario.schema.json` and nothing else from a design session.
