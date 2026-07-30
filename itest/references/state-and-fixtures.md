# State and fixtures reference

Lookup tables and reading order for the `itest:state` skill. Use the schema-source
table to fill `schema_source`, the factory/builder and seed-tooling tables to fill
`builders_and_factories` and `seed_tooling`, and the two closing sections to fill
`id_generation` and `teardown_affordances`.

## Schema-source table

Where the authoritative shape of a data store's records lives, per ecosystem. Prefer
whichever of these is closest to what actually runs against the store; a hand-written
doc or comment is not a schema source.

| Ecosystem | Schema source | Where to look |
|---|---|---|
| SQL, any | Migration directory | `migrations/`, `db/migrate/`, `alembic/versions/` — the most recent migration in sequence is the current shape |
| Python (Django) | ORM model modules | `models.py` / `models/` packages, classes subclassing `django.db.models.Model` |
| Python (SQLAlchemy) | ORM model modules | Classes subclassing a `declarative_base()` result, or annotated with `Mapped[...]` under SQLAlchemy 2.x |
| Go (GORM) | ORM model modules | Structs with `gorm` struct tags, typically under `internal/models/` or similar |
| Ruby (ActiveRecord) | ORM model modules, or generated dump | `app/models/*.rb` for associations and validations; `db/schema.rb` for the actual column set |
| Ruby, any SQL | Generated schema dump | `db/schema.rb` (ActiveRecord) or `db/structure.sql` (raw SQL migrations) — regenerated from migrations, so it is current by construction |
| Node/TS (Prisma) | ORM model modules | `schema.prisma`, the `model` blocks |
| Rust/Go (Ent) | ORM model modules | `ent/schema/*.go`, the `Fields()` method of each schema type |

When a migration directory and an ORM model module disagree, the migration directory
wins — it is what the store actually ran. Record both in evidence and let the
disagreement itself be a finding rather than resolving it silently.

## Factory/builder table

Code that already knows how to construct valid domain objects. Prefer these over
writing new fixtures; they encode validation rules a hand-rolled object literal would
have to rediscover.

| Ecosystem | Tool | What it produces | Signal |
|---|---|---|---|
| Python | `factory_boy` | Model instances via `factory.Factory` subclasses | `import factory`, classes subclassing `factory.django.DjangoModelFactory` or `factory.Factory` |
| Python (Django) | `model_bakery` | Persisted model instances with sensible defaults | `from model_bakery import baker`, calls to `baker.make(...)` |
| Ruby | `factory_bot` | Model instances via `FactoryBot.define` blocks | `factories/*.rb`, `FactoryBot.create(...)` / `FactoryBot.build(...)` |
| Any | `faker` / `@faker-js/faker` | Realistic field values (names, emails, addresses) used inside factories | `import faker` / `from faker import Faker`; `import { faker } from '@faker-js/faker'` |
| Any | `testcontainers` modules | A running, disposable instance of a real dependency (database, queue, cache) | `testcontainers` import plus a module for the specific dependency, e.g. `testcontainers-python`'s `PostgresContainer`, `testcontainers-go`'s `postgres` module |
| Go | Table-driven helper constructors | A local `newX(t *testing.T, ...) X` function returning a populated struct, called from table-driven test cases | Grep for `func new[A-Z]` in `_test.go` files, or a `testing.go` helper file alongside the package under test |
| Node/TS (Prisma) | Prisma seed scripts | Rows inserted via the Prisma Client, run once to establish a baseline dataset | `prisma/seed.ts`, the `prisma.seed` key in `package.json` |

## Seed tooling table

Commands that establish schema or baseline data before tests run. These matter to
`direct_write_possible` even when they are not run by the test process itself — they
tell you whether a store can be brought to a known state at all.

| Tool | Ecosystem | Invocation shape | Signal |
|---|---|---|---|
| `alembic` | Python/SQLAlchemy | `alembic upgrade head` | `alembic.ini`, `alembic/versions/` |
| `golang-migrate` | Go | `migrate -path ... -database ... up` | `migrate` invocation in `Makefile`/CI, a `migrations/` directory of numbered `.sql` files |
| `flyway` | JVM, polyglot | `flyway migrate` | `flyway.conf`, `db/migration/` with `V<version>__<name>.sql` files |
| `liquibase` | JVM, polyglot | `liquibase update` | `liquibase.properties`, a changelog file (`db/changelog/*.xml`/`.yaml`/`.sql`) |
| `knex` | Node/TS | `knex migrate:latest`, `knex seed:run` | `knexfile.js`/`.ts`, `migrations/` and `seeds/` directories |
| `prisma migrate` | Node/TS | `prisma migrate dev`, `prisma migrate deploy` | `prisma/migrations/`, `prisma migrate` in scripts or CI |

Beyond the named tools, check `Makefile` and `justfile` targets whose name contains
`seed`, `fixtures`, or `migrate` — these are frequently the actual entry point a
developer or CI job calls, even in a repo that also has one of the tools above
installed. Read the recipe body: a target named `seed` that only runs `migrate` is
not the same finding as one that inserts rows.

## Determining whether direct writes are possible

`direct_write_possible` is true only when a test process, running the way tests
actually run in this repo, could open a connection to the store and write to it
without going through the system's own interface. Check for all of the following;
the absence of any one of them means the answer is false and composition through the
public interface is the only route:

- **Credentials and network access.** Does the test process have (or could it
  plausibly obtain) a credential for the store, and is the store reachable from
  wherever tests run — locally, in CI, or in whatever environment the suite targets?
- **Reachability outside the service process.** Is the store exposed on its own port
  or socket, separate from the service under test, or is it only reachable through
  code embedded in that service (an in-process cache, an embedded database file the
  service opens exclusively)?
- **A connection string in test config or CI environment.** A `DATABASE_URL`,
  connection string, or equivalent set in test configuration or CI environment
  variables is direct evidence a write path exists, distinct from the service's own
  runtime config.
- **An ORM or driver test-session helper.** Does the ORM or store client ship a
  helper meant for tests — a session factory, a test database helper, a
  `sqlite3 :memory:` shortcut — that a test could call directly?

Evidence for `how` should point at the concrete mechanism found, not merely at the
possibility: the connection string's location, the helper function's signature, or
the driver import a test would use. Absence of evidence is not itself evidence of
absence, so when discovery does not turn up any of the four signals above, report
`direct_write_possible: false` and say what would need to be true for it to become
possible, rather than guessing at a mechanism that was never actually observed.

## ID generation and why it matters

`id_generation.origin` determines the order in which state can be assembled, and
whether a test can choose its own identifiers up front:

- **`server`** — the store or service assigns the identifier (an auto-increment
  column, a database-generated UUID, a sequence). A test cannot know the id before
  creation completes. Any prerequisite entity must be created first, and its id
  captured from the response or a subsequent read, before it can be referenced by
  anything that depends on it. This forces composition order: dependencies before
  dependents, always, with the id threaded through each subsequent request.
- **`client`** — the caller supplies the identifier (a client-generated UUID, a
  natural key chosen by the test). This allows a test to construct a whole graph of
  related entities with known ids ahead of time, in any convenient order, and makes
  assertions simpler because expected ids do not have to be read back from anywhere.
- **`mixed`** — some entities take client-supplied ids and others are server-assigned,
  commonly when a single service fronts more than one store or table with different
  conventions. Record which kind applies to which entity; a blanket `implications`
  statement is not useful when the two halves of the graph behave differently.
- **`unknown`** — discovery did not turn up enough evidence to tell. Say so plainly
  in `assumptions[]` rather than defaulting to either origin; guessing here produces
  test designs that break on the very first prerequisite entity.

Write `implications` as a concrete statement about setup ordering for this project,
not a restatement of the definition above — e.g. "the `order` id is assigned by
Postgres on insert, so a test must create the order first and read its id from the
response before it can create line items against it."

## Teardown affordances

Every value the `teardown_affordances[].strategy` enum can take, and how to recognize
whether it is available in a given project. Assess all six for every relevant store;
an enum value with no evidence either way is `available: false`, not omitted.

| `strategy` | Definition | How to recognize it |
|---|---|---|
| `transaction-rollback` | The test wraps its work in a transaction that the system under test itself honors, then rolls it back instead of committing, so nothing written is ever visible outside the test. | The test harness or a helper opens a transaction and the code path under test executes within that same transaction (not a separate connection) — look for a per-test transaction wrapper in test setup, and confirm the system's own connection participates in it rather than opening a second, independent connection. |
| `truncate` | A target, script, or helper empties one or more tables (or equivalent collections) between tests, without dropping and recreating schema. | A `Makefile`/`justfile` target or test helper that runs `TRUNCATE`/`DELETE FROM` across known tables, often invoked in a global teardown or between test files. |
| `namespacing` | Each test (or test run) gets its own tenant id, schema, database name, or key prefix, so tests never collide and nothing needs to be deleted for isolation to hold. | Test setup generates a unique tenant/schema/prefix per run (a UUID, a worker id, a timestamp) and every write in the test is scoped under it; look for this in fixture or setup code rather than production code. |
| `ephemeral-container` | A fresh instance of the dependency is started for the test run (or per test) and discarded afterward, so isolation comes from the instance's lifetime rather than any cleanup logic. | A `testcontainers` module or equivalent container-lifecycle call in test setup, with the container started before tests run and stopped/removed after — see the factory/builder table above. |
| `delete-via-api` | The system's own public interface can remove what a test created — a `DELETE` endpoint, an RPC, a CLI command — so teardown drives the same interface the test used to set up. | A delete/destroy operation exists on the public interface and is reachable with credentials the test already has; confirm it actually removes the created entity rather than soft-deleting or archiving it in a way that would still cause collisions. |
| `none` | Nothing in the repo removes or isolates state created by a test; whatever a test writes persists and can affect later tests or runs. | No transaction wrapper, truncate step, namespacing, ephemeral instance, or delete path was found for this store. Report this plainly — it is itself a finding, not a gap in discovery. |

Report affordances, not decisions. Whether to compose or inject is decided during
synthesis against the doctrine; your job is to say what this project makes possible.
