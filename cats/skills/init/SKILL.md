---
name: init
version: 0.1.0
description: Bootstrap CATS fuzzing configuration for this repo. Use when setting up CATS/API fuzzing for the first time, or when .local/cats/config.yaml is missing.
---

# cats:init

Bootstraps `.local/cats/config.yaml` (machine-local, gitignored) and a committed
false-positive rules file for this repo, then walks through the setup `init` cannot
do for you, and finishes with a `doctor` check.

## 1. Run init

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py init
```

If `.local/cats/config.yaml` already exists, this prints a message and exits 0
without changing anything — pass `--force` to overwrite.

Useful flags (all optional):

| Flag | Default | Purpose |
|---|---|---|
| `--spec PATH` | auto-discovered | OpenAPI spec, relative to repo root |
| `--server URL` | `http://localhost:8080` | Server under test |
| `--health-url URL` | same as `--server` | Endpoint `doctor`/preflight probes for "server is up" |
| `--results-dir PATH` | `test/results/cats` | Where run artifacts and databases land |
| `--rules PATH` | `test/cats/false-positives.yaml` | Committed false-positive rules file |
| `--non-interactive` | off | Fail instead of prompting when the spec can't be found |
| `--force` | off | Overwrite an existing config |

Spec auto-discovery tries, in order: `openapi.json`, `openapi.yaml`,
`api/openapi*.json`, `api/openapi*.yaml`, `docs/openapi*.json`,
`docs/openapi*.yaml`. One match wins; more than one match is an error asking
for `--spec` explicitly; no match prompts for a path (or fails under
`--non-interactive`).

`init` also writes the rules file (with two starter rules, `RATE_LIMIT_429` and
`CONNECTION_ERROR_999`) if it doesn't already exist, and creates the results
directory. It never overwrites an existing rules file.

## 2. Walk the user through what init cannot infer

`init` writes a config with one placeholder that must be filled in by hand
before anything will work (`token_cmd`), plus two empty hooks worth asking
about now while you have the user's attention. Ask about each, then edit
`.local/cats/config.yaml` directly:

**`identities.default.token_cmd`** — a shell command that prints a bearer token
on stdout and *nothing else* (no logging, no newline-wrapped JSON — just the
raw token). It runs via `shell=True` with the repo root as its cwd, so it can
be as simple as `echo $MY_TOKEN` or as involved as a script that performs a
login flow. Nothing else may write to stdout; extra output becomes part of the
token, and the fuzz run's HTTP calls will look correctly unauthenticated or
malformed. Ask how this repo issues bearer tokens for automated testing before
guessing.

`identities` is a map, not a single entry — `init` only ever writes `default`,
but if the user needs to fuzz as more than one identity (e.g. an admin and a
regular user), add more entries under `identities:` with their own
`token_cmd`, and select among them with `default_identity:` or per-run via
`cats_tool.py run --identity NAME`.

**`hooks.seed`** — a shell command to seed the database or environment with
fixture data before fuzzing starts (e.g. so paths like `GET /widgets/{id}`
have an id to fuzz against). Runs once per `cats_tool.py run`, unless the user
passes `--skip-seed`. Empty by default — ask whether this repo needs one.

**`hooks.pre_run`** — a shell command to run before anything else (e.g. start
a server, wait for a health check, reset rate limits). Runs on every `run`
with no way to skip it. Empty by default.

The order is **pre_run -> seed -> fuzz -> post_run**. pre_run comes first so a
repo can clear what the previous campaign left behind before the seed's own
burst of API calls, rather than seeding into exhausted state (#595).

There is also `hooks.post_run` (e.g. to send a notification or clean up
after a run); its failure only logs a warning, never fails the run. It runs
after the run's pipeline finishes without an unhandled exception — which
includes a `--skip-parse` run, where neither parse nor classify ever
happened, not only the normal case where both succeeded. Mention it exists,
but it's lower priority than the three above.

Every hook and `token_cmd` receives these environment variables:
`CATS_SERVER`, `CATS_SPEC`, `CATS_RESULTS_DIR`, `CATS_REPORT_DIR`,
`CATS_RUN_ID`, `CATS_IDENTITY` (plus `CATS_DB` and `CATS_EXIT_CODE` for
`post_run` only).

## 3. Offer to update .gitignore

Read the repo's `.gitignore`. If it does not already contain the results
directory (the `--results-dir` value, e.g. `test/results/cats/`), offer to
append one line for it:

```
test/results/cats/
```

Only append — never rewrite or reorder the rest of the file. Skip this step
silently if the line (or an equivalent pattern) is already present.

## 4. Verify with doctor

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py doctor
```

Show the output verbatim. `doctor` checks four things independently and
prints ✓/✗ for each — spec file exists, `cats` binary is on PATH, the rules
file parses, and `health_url` responds — then exits 1 if any failed. A
placeholder `token_cmd` is not checked by `doctor` (there is no way to
distinguish a fake token from a real one), so remind the user that even an
all-✓ `doctor` run doesn't confirm authentication actually works — that's
only proven by a real `/cats:run`.

If `cats` itself isn't installed, point at
https://github.com/Endava/cats (e.g. `brew install cats`).
