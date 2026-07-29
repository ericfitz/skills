# Ecosystems reference

Lookup tables and reading order for the `profile:stack` skill. These tables mirror
`MANIFESTS` and `LOCKFILE_PM` in `profile/scripts/inventorylib/manifests.py` — if the
script's tables change, update this file to match.

## Manifest table

Every key in `MANIFESTS`, the ecosystem it implies, the runtime that owns it, and the
version-pinning file to read (when the ecosystem has a standard one). A manifest with no
listed version file has no single conventional pin — read the fallback order below (CI
workflow, Makefile, or README) instead of guessing a version.

| Manifest file | Ecosystem | Runtime | Version file |
|---|---|---|---|
| `pyproject.toml` | python | Python | `.python-version` |
| `requirements.txt` | python | Python | `.python-version` |
| `setup.py` | python | Python | `.python-version` |
| `Pipfile` | python | Python | `.python-version` |
| `go.mod` | go | Go | the `go` directive inside `go.mod` itself |
| `package.json` | node | Node.js | `.nvmrc` |
| `Cargo.toml` | rust | Rust | `rust-toolchain.toml` |
| `Gemfile` | ruby | Ruby | `.ruby-version` |
| `pom.xml` | java | Java | none of the standard five — check CI config or a Makefile |
| `build.gradle` | java | Java | none of the standard five — check CI config or a Makefile |
| `build.gradle.kts` | kotlin | Kotlin | none of the standard five — check CI config or a Makefile |
| `composer.json` | php | PHP | none of the standard five — check CI config or a Makefile |
| `mix.exs` | elixir | Elixir | none of the standard five — check CI config or a Makefile |
| `Package.swift` | swift | Swift | none of the standard five — check CI config or a Makefile |
| `pubspec.yaml` | dart | Dart | none of the standard five — check CI config or a Makefile |

## Lockfile table

Every key in `LOCKFILE_PM`, its package manager, and the command that installs
dependencies from the lock. A lockfile only resolves the package manager for manifests of
its **own ecosystem** that sit in the **same directory** — a `package-lock.json` next to a
`go.mod` says nothing about how the Go module is managed, and must not be read as if it
did.

| Lockfile | Ecosystem | Package manager | Install command |
|---|---|---|---|
| `uv.lock` | python | uv | `uv sync` |
| `poetry.lock` | python | poetry | `poetry install` |
| `pdm.lock` | python | pdm | `pdm install` |
| `Pipfile.lock` | python | pipenv | `pipenv install` |
| `package-lock.json` | node | npm | `npm ci` |
| `yarn.lock` | node | yarn | `yarn install --frozen-lockfile` |
| `pnpm-lock.yaml` | node | pnpm | `pnpm install --frozen-lockfile` |
| `bun.lockb` | node | bun | `bun install` |

Two lockfiles of the same ecosystem in one directory (e.g. `package-lock.json` and
`yarn.lock` both present) resolve to whichever manager sorts first alphabetically — this
mirrors the tie-break the script itself applies, so the model's manual reading agrees with
the census rather than contradicting it.

## When the script comes back low-confidence

`coverage_confidence` measures the whole tree, assets included — a repo can be `high`
while one niche source directory is opaque. Read `unclassified[]` too, not just the label.

When confidence is `partial` or `low`, read in this order and stop as soon as the
ecosystem is clear:

1. **Root directory listing.** The files sitting at the repo root are usually enough on
   their own — a stray manifest the census missed, a lockfile, a version file.
2. **`Makefile` or `justfile` targets.** Target names and their bodies often name the
   real build/test/install commands directly, which beats any ecosystem default.
3. **CI workflow files** (e.g. `.github/workflows/*.yml`, `.gitlab-ci.yml`,
   `Jenkinsfile`). CI has to actually build and test the repo, so its steps are a ground
   truth for both the toolchain and the runtime version in use.
4. **`README` build instructions.** Prose setup/installation sections frequently spell
   out the exact commands and prerequisite versions.
5. **Editor config** (`.editorconfig`, IDE run configs, `.tool-versions`). These narrow
   down language and sometimes an exact runtime version even when no manifest exists.
6. **File extensions by frequency**, as a last resort. Only use this to corroborate a
   language already suggested by one of the steps above — never to declare an ecosystem
   on its own (see the closing rule below).

## Build command inference

Canonical build command per ecosystem, used only when no Makefile, justfile, or CI
workflow supplies a more specific one:

| Ecosystem | Canonical build command |
|---|---|
| go | `go build ./...` |
| rust | `cargo build` |
| node | `npm run build` |
| python | `uv build` |
| java | `mvn package` (or `gradle build` under `build.gradle`) |
| csharp | `dotnet build` |
| kotlin | `gradle build` |
| ruby | `bundle exec rake build` |
| php | `composer install --no-dev` |
| elixir | `mix compile` |
| swift | `swift build` |
| dart | `dart build` |

A command actually present in the repo's own Makefile, justfile, or CI workflow always
takes precedence over this table.

---

If you cannot identify the ecosystem, say so in `unknowns[]` and set `confidence` to
`low`. Do not guess a language from a single file.
