# Test frameworks reference

Lookup tables and reading order for the `itest:conventions` skill. Use the fingerprint
table to name `frameworks`, the integration separation table to fill in
`integration_separation`, and the two closing sections to fill `runner_commands` and
`reusable_helpers`.

## Fingerprint table

Per ecosystem, the frameworks this skill recognizes and the signals that identify each.
An import signal is decisive; a config file alone is corroborating — a repo can carry a
leftover config for a framework it no longer runs.

| Ecosystem | Framework | Import signal | Config signal |
|---|---|---|---|
| Python | `pytest` | `import pytest`, `from pytest import ...` | `pytest.ini`, `pyproject.toml` `[tool.pytest.ini_options]`, `conftest.py` present |
| Python | `unittest` | `import unittest`, classes subclassing `unittest.TestCase` | none standard — stdlib, no config file implies it |
| Python | `nose2` | `import nose2`, `from nose2.tools import ...` | `nose2.cfg`, `unittest.cfg` |
| Go | stdlib `testing` | `import "testing"`, `func TestXxx(t *testing.T)` | none — stdlib |
| Go | `testify` | `github.com/stretchr/testify/assert`, `.../require`, `.../suite` | `go.mod` requires `github.com/stretchr/testify` |
| Go | `ginkgo` | `github.com/onsi/ginkgo/v2`, `github.com/onsi/gomega` | `go.mod` requires `github.com/onsi/ginkgo/v2` |
| JS/TS | `jest` | `from '@jest/globals'`, or bare `describe`/`it`/`expect` with no other runner installed | `jest.config.js`/`.ts`/`.mjs`, `jest` key in `package.json` |
| JS/TS | `vitest` | `import { describe, it, expect } from 'vitest'` | `vitest.config.ts`, `vite.config.ts` with a `test` block |
| JS/TS | `mocha` | `require('mocha')`, bare `describe`/`it` paired with a separate assertion lib (`chai`, `assert`) | `.mocharc.js`/`.json`/`.yml`, `mocha` key in `package.json` |
| JS/TS | `playwright` | `import { test, expect } from '@playwright/test'` | `playwright.config.ts`/`.js` |
| JS/TS | `cypress` | `cy.visit(...)`, `cy.get(...)` calls, `/// <reference types="cypress" />` | `cypress.config.ts`/`.js`, a `cypress/` directory |
| Java | `junit4` | `import org.junit.Test`, `@Test` from `org.junit` | `junit:junit` dependency in `pom.xml`/`build.gradle` |
| Java | `junit5` | `import org.junit.jupiter.api.Test` | `org.junit.jupiter:junit-jupiter` dependency |
| Java | `testng` | `import org.testng.annotations.Test` | `org.testng:testng` dependency, `testng.xml` |
| Ruby | `rspec` | `RSpec.describe`, `require 'rspec'` | `.rspec`, `spec/spec_helper.rb` |
| Ruby | `minitest` | `require 'minitest/autorun'`, classes subclassing `Minitest::Test` | none standard — often ships via `test_helper.rb` |
| C# | `xunit` | `using Xunit;`, `[Fact]`/`[Theory]` | `xunit` package reference in the `.csproj` |
| C# | `nunit` | `using NUnit.Framework;`, `[Test]`/`[TestCase]` | `NUnit` package reference in the `.csproj` |
| Rust | built-in `#[test]` | `#[test]` attribute on a function, `#[cfg(test)] mod tests` | none — stdlib, driven by `cargo test` |
| Rust | `cargo nextest` | no import signal (it runs the same `#[test]` functions) | `.config/nextest.toml` present, or `cargo nextest run` in CI/Makefile |

When a repo's test files show no recognizable import and no config file matches, name the
framework `unknown` in your summary rather than guessing from directory names alone.

## Integration separation table

How each `mechanism` enum value (from `conventions.schema.json`) shows up concretely per
ecosystem, and the `how_to_add` text to use once you've confirmed which one applies.
`how_to_add` must be copied or closely adapted from the matching row — it has to be a
concrete instruction someone can follow without reading anything else.

| `mechanism` | Ecosystem(s) | Concrete form | `how_to_add` |
|---|---|---|---|
| `build-tag` | Go | A build constraint restricts the file to a specific `go build`/`go test` invocation | Add `//go:build integration` as the first line of the file, before the `package` clause, followed by a blank line. |
| `marker` | Python (pytest) | A custom pytest marker decorates the test function or class | Add `@pytest.mark.integration` above the test function, and confirm `integration` is registered under `markers` in `pytest.ini` or `pyproject.toml`'s `[tool.pytest.ini_options]` (unregistered markers only warn, they don't fail — so registration is easy to miss). |
| `directory` | Any | Integration tests live under a dedicated directory, separate from unit tests | Place the new test file under `tests/integration/` (or whatever the repo's existing integration directory is named — confirm from `test_dirs` rather than assuming `tests/integration/`). |
| `filename-suffix` | JS/TS (mainly) | The file name itself carries the distinction, independent of directory | Name the file with the repo's existing integration suffix, e.g. `*.integration.test.ts`, matching the pattern already in use rather than inventing a new one. |
| `separate-config` | JS/TS, Python, Java | A second config file (or a second environment within one config file) points at a distinct set of tests and often a distinct runner invocation | JS/TS: add the test to the tree covered by the second config, e.g. `vitest.integration.config.ts`. Python: add it to the environment covered by a second `tox` (or `nox`) env dedicated to integration tests. Java (Maven): add it to the sources covered by the `failsafe` plugin's integration-test phase (typically `*IT.java` under `src/test/java`, run via a separate Maven profile). |
| `separate-project` | Go, Java, C#, JS/TS monorepos | Integration tests live in their own module, package, or top-level project with its own manifest | Add the test inside that separate module/project (its own `go.mod`, `pom.xml`, `.csproj`, or `package.json`), not inside the unit-test module — it is built and run independently of the primary module. |
| `none` | Any | Nothing in the repo distinguishes integration tests from unit tests — they run together, in the same command, the same directories, no marker or tag | State plainly that there is no existing separation; the newcomer should not invent one silently. If new tests need separation, that decision belongs to a human, not to inference. |
| `unknown` | Any | You read the repo and still cannot tell how (or whether) integration tests are set apart | Do not guess. Set `mechanism` to `unknown`, leave `how_to_add` as a statement that this is undetermined, and record the gap in `convention_gaps` (see the closing rule below). |

## Finding the runner commands

Determine `runner_commands` (and `ci_invocation`) by reading sources in this order,
stopping as soon as a command is confirmed, and recording where it came from:

1. **CI workflow files** (`.github/workflows/*.yml`, `.gitlab-ci.yml`, `Jenkinsfile`,
   `.circleci/config.yml`). This is the strongest evidence available: CI has to actually
   invoke the runner for the build to mean anything, so whatever command sits in a `run:`
   or `script:` step is what really executes, not what a doc claims. Prefer this over
   every other source when it's present and unambiguous.
2. **`Makefile` or `justfile` targets.** Look for targets named `test`, `test-unit`,
   `test-integration`, `check`, or similar, and read the recipe body — a target name
   alone can be misleading if its body chains to something else.
3. **`package.json` scripts** (`scripts.test`, `scripts["test:integration"]`, etc.), for
   Node projects without a clearer Makefile/CI signal.
4. **Config files** for the framework itself (`pytest.ini`, `jest.config.js`,
   `vitest.config.ts`, `tox.ini`, and similar) — these can encode default paths, markers,
   or `testPathIgnorePatterns` that change what a bare invocation actually runs, even when
   no explicit command exists anywhere else.
5. **Ecosystem default**, only when nothing above supplies a command: e.g. `pytest`,
   `go test ./...`, `npm test`, `cargo test`, `bundle exec rspec`, `dotnet test`.

A command found in an earlier source always overrides a later one when they disagree —
CI beats a Makefile, a Makefile beats a stale README, and so on. Record which source each
`runner_commands` entry and `ci_invocation` came from as part of your evidence, so a
downstream reader can tell inferred defaults apart from confirmed commands.

## What counts as a reusable helper

Collect into `reusable_helpers` only things a new test would actually call instead of
duplicating:

- **A constructor that starts the system or a dependency** — e.g. a function that boots
  the service under test against a real or containerized dependency and returns a handle
  plus a cleanup function.
- **A factory that builds a valid domain object** — e.g. a function that returns a
  well-formed order, user, or record with sensible defaults, usable as-is or with fields
  overridden.
- **A client wrapper for the system's public interface** — e.g. a thin wrapper around
  HTTP or RPC calls that a test suite already uses instead of raw HTTP/RPC calls at every
  call site.
- **An assertion helper on domain state** — e.g. a function that checks a business
  invariant across several fields or a stored record, rather than restating that check in
  every test.

Do not collect:

- Generic string, time, or collection utilities with no domain meaning of their own.
- Anything private to a single test file (unexported/module-private, used nowhere else).

For each helper record a real name, its path, its purpose in one sentence, and — when
available — its actual signature, so downstream work can call it correctly rather than
guessing its shape.

---

If you cannot determine how a new integration test would be picked up by the runner, set
`mechanism` to `unknown` and say so in `convention_gaps`. A confident wrong answer here
makes every test that follows unrunnable.
