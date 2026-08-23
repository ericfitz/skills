# Definitions

Two terms the whole plugin rests on, each of which has been got wrong more than
once before being settled here. This page carries the conclusion *and* the
reasoning, so a future reader has no need to re-derive either — and no room to
re-derive it differently.

## 1. The two senses of "dependency"

A dependency has a lifecycle value that answers one question: *when is it
needed?*

| Value | Needed when | Present in the deployed artifact? | npm example |
|---|---|---|---|
| `build` | Only to build and test the service. | No — it is absent from the deployed artifact. | `devDependencies` |
| `run` | While the service runs in production. | Yes — and therefore also present at build. | `dependencies` |

`build` covers compilers, test frameworks, linters, type stubs, and anything
else that touches the source tree but never ships. `run` covers everything the
running process actually loads or calls — which, because the process has to be
built before it can run, also has to be present during build.

The same distinction recurs across ecosystems under different names: npm's
`devDependencies` vs `dependencies`, Python's `[dependency-groups] dev` vs the
project's core dependencies, Cargo's `[dev-dependencies]` vs
`[dependencies]`. Whatever the manifest calls it, the question is the same one:
does this survive into the artifact that gets deployed, or does it stop at the
build step?

### The superset relation

**The build environment is a strict superset of the runtime environment.** Every
`run` dependency is also present at build. Not every `build` dependency is
present at runtime.

The reasoning: to build and test a service, you have to be able to *run* it —
debugging a build means executing the code, and executing the code requires
everything the code calls at runtime. So the runtime dependency set is
necessarily a subset of what's available during build. The reverse does not
hold — a test framework or a linter is available during build but has no
reason to be loaded once the service is running in production.

`npm ci --omit=dev` (and its equivalents in other ecosystems) is the operator
that drops the difference: it takes the build-time superset and prunes it down
to the `run` subset for the deployed artifact.

### Why there is no `both`

A naive reading suggests a dependency could be `build`, `run`, or `both` —
needed during build for one reason and during runtime for another. There is no
`both` value, and the superset relation is why: a runtime dependency is
present at build *because* it is a runtime dependency, not for some separate
build-time reason. Recording it as `both` would state the containment twice —
once as "needed at build" and once as "needed at run," when the build-time
presence is entirely explained by, and adds no information beyond, the
run-time need. `run` already implies "and also present at build." `both` would
be a duplicate fact wearing a third label.

`dependency-core.schema.json`'s `lifecycle` property description restates the
superset claim, the no-`both` conclusion, and lifecycle-is-not-health in
miniature — keep the two in step; a change to one without the other is a
stale claim in whichever file was not updated.

## 2. What counts for health

**Healthy** means: the service in production has all of its environment and
service dependencies met, and all metric-sensitive ones within acceptable
bounds.

That definition tells you what health *is*. It does not, by itself, tell you
which dependencies to check. The filter for that is a separate question, and
getting it wrong is the mistake this section exists to prevent.

### The failability test

The filter is **not** build-vs-run, and it is **not** category. It is:

**A dependency enters a health definition iff it can fail independently while the process is up.**

| Can fail independently while the process is up | Cannot |
|---|---|
| A service the code calls (database, queue, third-party API) | A bundled library — it is in the artifact, or the deploy failed |
| A credential (expires, gets revoked, gets rotated out from under the process) | |
| A resource limit (memory, disk, connection pool exhausts while running) | |
| Remote configuration (a flag service, a config server, changes after startup) | |
| A network path (a hostname stops resolving, a port stops accepting connections, after the process is already up) | |
| A dynamically loaded package (resolved reflectively or on demand, so its absence or breakage surfaces only when the load is attempted — after the process is already up) | |

The last row of the "can" column is the one that's easy to miss, and the whole
reason category is not the filter: a dynamically loaded package is still a
`package` by category, but it behaves like a service for health purposes,
because loading it can fail at a moment independent of process startup. A
reflectively resolved JDBC driver, a Python `importlib` plugin, a `dlopen`ed
`.so` — each is only known to be present once something asks for it, and that
ask can happen, and fail, at any point while the process is running.

### Why lifecycle is not the health filter either

Most libraries are `run` under npm semantics (or the local ecosystem's
equivalent) and still contribute nothing to health. A bundled, statically
linked dependency that is `run`-lifecycle cannot fail independently once the
process is up — it was already loaded successfully, or the process never
started. Using lifecycle (`build`/`run`) as the health filter would pull in
every ordinary library alongside the things that actually vary at runtime,
diluting the health definition with entries that can never change state on
their own.

### Why category is not the health filter either

A category filter — "packages are excluded, services and everything else are
included" — is fully testable, and silently wrong about dynamic loading. It
would exclude the reflectively resolved JDBC driver, the `importlib` plugin,
the `dlopen`ed `.so` — each categorized `package`, each capable of failing
independently after the process is already running. Category answers "what
kind of thing is this," not "can this still fail on its own once we're up,"
and those two questions diverge exactly at dynamic loading.

### The actual rule

A dependency enters a health definition iff a condition can be stated about it
with evidence:

- A bundled library produces no such condition — there is nothing to observe
  about it after startup that could change — and it self-excludes.
- A dynamically loaded package produces a `presence` condition, citing the
  `file:line` of the site that performs the load — **when such a site
  appears in the evidence a discovery skill can read**. Nothing in layer 1
  records dynamic-loading sites today (issue #56); until it does,
  `synthesize` records an assumption naming the gap instead. Keep this
  bullet and `synthesize/SKILL.md` step 3 in step.
- A service, credential, resource limit, remote-config value, or network path
  produces whatever condition (`presence`, a metric bound, and so on) its own
  reference page defines.

If no condition with evidence can be written down for a dependency, it does
not belong in the health definition — not because it was excluded by category
or lifecycle, but because there is nothing to check.

## The taxonomy (stated intent only)

Three health states are named here as prose, and are explicitly **not yet technically defined** — no schema anywhere encodes them. They exist on this
page so a reader knows the omission is a decision, not an oversight:

- **healthy** — all conditions hold.
- **unhealthy** — a `presence` condition fails for something critical
  functionality needs.
- **degraded** — anything between `healthy` and `unhealthy`: a dependency
  reporting itself degraded, one whose metric is outside its declared bounds,
  or one that is unavailable but only a secondary function needs it.

Leaving these undefined technically is deliberate: a state that is not encoded
cannot be encoded wrongly. `degraded` in particular spans several genuinely
different situations (self-reported, out-of-bounds, secondary-only) that a
premature schema would have to either conflate or arbitrarily split. Defining
it later, once a consumer needs to act on the distinction, costs nothing —
nothing downstream depends on today's phrasing of it.
