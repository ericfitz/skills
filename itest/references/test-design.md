# Integration test design doctrine

This is the shared vocabulary and rule set for the `itest` plugin. The `conventions`,
`critique`, `state`, and `design` skills all read this file; the tier rule, the issue
and verdict vocabularies, and the composition/injection rules defined here are
load-bearing for their contracts — do not restate or redefine them locally.

## What an integration test is for

An integration test exercises a customer-meaningful workflow across a real boundary,
asserting on outcomes observable from outside the system. It is not a slower unit test.
A unit test asks whether one component behaves correctly in isolation; an integration
test asks whether components, once connected, produce the outcome a customer actually
depends on. If a test's failure would not surprise anyone who already trusts each
component individually, it has not earned the integration tier.

## The tier rule

An integration test is justified when the failure it catches arises from integration.

That failure has to come from the seam between components, not from logic that lives
entirely inside one of them. The following kinds of failure qualify:

- Dependency unavailable or slow
- Partial failure mid-sequence
- Concurrent access to the same entity
- Authorization and tenancy boundaries
- Data crossing a serialization boundary
- Transaction rollback and retry
- Configuration mismatch between components

The following do not, no matter how important they are to get right:

- Input-validation permutations
- Pure logic branches
- Formatting and presentation
- Error-message wording

Push disqualified cases down to unit tests. The most expensive tier is where
combinatorial explosion does the most damage, and a suite people disable protects
nothing.

## The issue vocabulary

These eight values are the only permitted entries in `critique.assessed[].issues[].type`.
Do not introduce a ninth value or rename one of these — later contracts depend on exact
spelling.

| `type` | Definition | Detection heuristic |
|---|---|---|
| `over-mocking` | The boundary under test is itself mocked, so the test cannot observe the integration it claims to cover | The component named in the test's title or docstring appears in the mock/stub/fake setup rather than in a real call — check what's constructed against what's claimed. |
| `implementation-detail-assertion` | Asserts on internal call sequences, private state, or structures no customer can observe | The assertion target is a private attribute, a mock's call count, or a value never returned by any public interface. |
| `non-determinism` | Depends on sleeps, wall-clock time, iteration order, or unseeded randomness | The test body calls a sleep/timer function, reads the system clock, uses unseeded randomness, or asserts on set/map iteration order as if it were stable. |
| `shared-mutable-state` | Depends on state left behind by another test, or leaves state that affects others | The test reads fixture or global state it did not itself create in this run, or skips teardown of state it created. |
| `tautological-assertion` | Asserts something that cannot fail, or re-asserts the value just written by the test | The expected and actual sides of the assertion trace back to the same literal or variable with no independent read path in between. |
| `assertion-free` | Executes a flow and asserts nothing beyond absence of an exception | Zero assertion/expect calls appear in the test body, or the only one checks that the call didn't raise. |
| `framework-not-system` | Verifies that the framework, ORM, or library works, not that this system works | The assertions would still pass if the system's own application code were deleted and only the framework/ORM default behavior remained. |
| `missing-failure-path` | Covers only the happy path for a workflow whose failure modes matter | The workflow has a documented error, validation, auth, or conflict condition with no corresponding test case anywhere in the file. |

## The verdict vocabulary

These three values are the only permitted entries in `critique.assessed[].verdict`:

- `sound` — no high-severity issues; the test would fail if the workflow it covers broke.
- `weak` — real coverage, but undermined by issues worth fixing.
- `misleading` — would pass while the workflow it names is broken. Over-mocking the
  boundary under test and assertion-free tests land here.

## Composition and injection

State a test needs can be composed (built by driving the system's own prerequisite
workflow) or injected (written directly into a store, bypassing the interface). Choose
deliberately:

- Compose by default when the prerequisite is itself a journey under test — state is
  valid by construction and the create path gets extra coverage for free.
- Inject when the chain is deep enough that composition dominates runtime; or the state
  is unreachable through the public interface (produced by a background job, aged by
  time, migrated legacy data); or it belongs to a third party being stubbed; or a
  corrupt or edge-case state is what is under test.
- Never inject state the real system could not itself produce, unless resilience to
  exactly that corruption is under test. Otherwise the test asserts on fiction and
  passes forever.
- Composed setup must be asserted on, or fail loudly. If `create` silently half-fails,
  the `delete` test reports a delete bug. Failure attribution is the main hidden cost of
  composition, and it is payable.
- Prefer per-test isolation over hoisted shared setup, even at a runtime cost, until
  setup cost is measured as prohibitive. Hoisting is what introduces order dependence.

Whatever you injected, you must be able to remove. Decide cleanup in the same step as
setup.

## Assertion design

Assert on what is observable at the chosen boundary: the response, persisted state read
back through the interface, an emitted event, an observable effect on a real dependency.
Never on internals. Include negative assertions ("and nothing else was modified") where
a workflow could over-reach. Control determinism explicitly: freeze time, seed
randomness, wait on conditions rather than sleeping, and never assert on unordered
collections as if they were ordered.
