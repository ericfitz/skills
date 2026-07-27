---
name: report
version: 0.1.0
description: Query and render CATS fuzzing results. Documents the CATS results SQLite schema (tables, views, worked queries) so results can be queried directly. Use when asked about CATS results, fuzzing findings, or to generate a CATS report.
---

# cats:report

A CATS run is parsed into a normalized SQLite database (one file per run,
`test/results/cats/cats-results-<run_id>.db` by convention, with
`latest.db` symlinked to the most recent **complete** run — see below). This
file is the durable reference for that schema, so a query can be written
without opening any source file.

## Resolving the database

Every command below takes `--db`. Omit it, or pass `--db latest`, to use
`results_dir/latest.db` — the default. That symlink is only ever updated
after a run's parse **and** classify stages both succeed (see `run_meta`
below), so it never points at a half-written or interrupted run. Pass an
explicit `--db PATH` to target a specific run's database instead.

## Re-parsing a retained report directory

`/cats:run` normally drives parse and classify for you. But if
`retain_raw_report: true` is set, the raw CATS report directory survives
after the run — useful for re-parsing it later, e.g. after a schema change
or to try a different `--db` location, without re-running the fuzzer:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py parse --report PATH [--db PATH]
```

`--report` is the CATS report directory (required). `--db` defaults to a
fresh `cats-results-<run_id>.db` under `results_dir`, same as a normal run.

Two caveats, both real:

- **The report shows the "this run never finished" banner.** `parse` only
  ever writes `run_meta.run_id` — it has no `finished_at` to stamp, because
  that's set by the classify stage of a full `/cats:run`. Follow `parse`
  with `classify` (see `/cats:fp`) against the same `--db` if you want a
  report without that banner.
- **It does not update `latest.db`.** Every command above defaults to
  `--db latest`; a database produced by a bare `parse` is invisible to that
  default until you either point `--db` at it explicitly on every
  subsequent command, or repoint the `latest.db` symlink at it yourself.

## Schema

### Lookup tables

Small tables that resolve an id to a name; every one of them is referenced by
`tests` (see the join shape below).

| Table | Columns |
|---|---|
| `result_types` | `id` INTEGER PK, `name` TEXT NOT NULL UNIQUE — `'success'`, `'warn'`, `'error'`, etc. |
| `fuzzers` | `id` INTEGER PK, `name` TEXT NOT NULL UNIQUE — the CATS fuzzer that generated the test |
| `servers` | `id` INTEGER PK, `base_url` TEXT NOT NULL UNIQUE |
| `paths` | `id` INTEGER PK, `path` TEXT NOT NULL UNIQUE, `contract_path` TEXT — `path` is the concrete request path, `contract_path` the templated OpenAPI path (e.g. `/widgets/{id}`) when CATS reported one |
| `http_methods` | `id` INTEGER PK, `method` TEXT NOT NULL UNIQUE |

### Main tables

**`tests`** — the hub. One row per fuzz test case.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | internal row id, used by every FK below |
| `test_id` | TEXT NOT NULL UNIQUE | CATS's own test identifier |
| `test_number` | INTEGER NOT NULL | numeric part of `test_id`, for stable ordering |
| `trace_id` | TEXT NOT NULL | |
| `scenario` | TEXT NOT NULL | human-readable description of what was fuzzed |
| `expected_result` | TEXT NOT NULL | CATS's expectation for this scenario |
| `result_type_id` | INTEGER NOT NULL FK → `result_types.id` | |
| `fuzzer_id` | INTEGER NOT NULL FK → `fuzzers.id` | |
| `server_id` | INTEGER NOT NULL FK → `servers.id` | |
| `path_id` | INTEGER NOT NULL FK → `paths.id` | |
| `result_reason` | TEXT | why CATS classified it this way |
| `result_details` | TEXT | |
| `source_file` | TEXT NOT NULL | original CATS report filename |
| `is_false_positive` | BOOLEAN DEFAULT 0 | set by `classify`; only ever true for `error`/`warn` rows — `success` rows are never classified |
| `fp_rule` | TEXT | the matching rule's `id`, or NULL |

**`requests`** / **`responses`** — one row each per test, 1:1 via a `UNIQUE`
FK on `test_id` (`ON DELETE CASCADE`).

| Table | Columns |
|---|---|
| `requests` | `id` PK, `test_id` INTEGER NOT NULL UNIQUE FK → `tests.id`, `http_method_id` INTEGER NOT NULL FK → `http_methods.id`, `url` TEXT NOT NULL, `timestamp` TEXT NOT NULL, `request_body` TEXT |
| `responses` | `id` PK, `test_id` INTEGER NOT NULL UNIQUE FK → `tests.id`, `http_method_id` INTEGER NOT NULL FK → `http_methods.id`, `response_code` INTEGER NOT NULL, `response_time_ms` INTEGER, `num_words` INTEGER, `num_lines` INTEGER, `content_length_bytes` INTEGER, `response_content_type` TEXT, `response_body` TEXT |

`request_body` and `response_body` are only populated (non-NULL) for
`error`/`warn` results — bodies for `success` results are dropped at parse
time to keep the database small, since they're rarely needed and can be
in the tens of thousands of rows.

**`request_headers`** / **`response_headers`** — many rows per parent, hung
off `requests.id` / `responses.id` respectively (`ON DELETE CASCADE`).

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `request_id` (or `response_id`) | INTEGER NOT NULL FK |
| `header_key` | TEXT NOT NULL |
| `header_value` | TEXT NOT NULL |
| `header_order` | INTEGER NOT NULL — original header order; a duplicate key resolves last-wins in this order |

**`run_meta`** — exactly one row, the provenance record for this database.

| Column | Type | Notes |
|---|---|---|
| `run_id` | TEXT PK | |
| `started_at` | TEXT | |
| `finished_at` | TEXT | **NULL means this run was interrupted** — parse started but parse+classify never both completed. `latest.db` never points at such a run. |
| `identity` | TEXT | which configured identity's `token_cmd` was used |
| `spec_path`, `spec_sha256` | TEXT | OpenAPI spec used, and its hash |
| `rules_sha256` | TEXT | hash of the false-positive rules file used |
| `git_sha` | TEXT | repo HEAD at run time, if it's a git repo |
| `cats_version` | TEXT | |
| `cats_args` | TEXT | the CATS invocation, with the bearer token redacted |
| `server` | TEXT | |
| `tool_version` | TEXT | version of this plugin's tooling |
| `classified_at` | TEXT | **NULL means never classified.** Distinguishes a genuine first classification from a reclassification — see `/cats:fp`'s `reclassify` mode. |

**`fp_rules`** — a snapshot of the rule set that produced the *current*
classification, rewritten wholesale on every `classify` pass (not a history).

| Column | Type |
|---|---|
| `rule_id` | TEXT PK |
| `why` | TEXT NOT NULL — the rule author's justification |
| `order_index` | INTEGER NOT NULL — position in the rules file |
| `enabled` | BOOLEAN NOT NULL DEFAULT 1 |
| `match_count` | INTEGER NOT NULL DEFAULT 0 — how many rows this rule suppressed this pass |

### Views

| View | Purpose |
|---|---|
| `test_results_view` | Every test, fully denormalized (all the lookup names already joined in) — every result type, including `success`. Start here for anything not covered by a more specific view. |
| `test_results_filtered_view` | Same as above, `WHERE is_false_positive = 0` — everything except suppressed false positives, still includes `success`. |
| `true_positives_view` | `test_results_view` narrowed to `is_false_positive = 0 AND result IN ('error', 'warn')` — the actionable findings. Almost every "what's broken" question starts here. |
| `fp_rule_stats_view` | Per matched `fp_rule`: count, `pct_of_total` (of all tests), `pct_of_fps` (of all suppressed tests). Only rows with `is_false_positive = 1`. |
| `fuzzer_stats_view` | Per (fuzzer, result): count, percentage within that fuzzer, average response time. Covers all results, not just true positives. |
| `path_error_analysis_view` | Per (path, http_method): total tests, error/warning/success counts, and an error rate percentage. |
| `response_code_stats_view` | Per (response_code, result): count, avg/min/max response time. Not filtered by path — use `test_results_view` filtered by `path` instead if you need one path's distribution (see query 6 below). |

### Join shape

`tests` is the hub. `requests` and `responses` are 1:1 with it on
`test_id`. `request_headers` hangs off `requests.id` and
`response_headers` off `responses.id` — both many-per-parent, ordered by
`header_order`. Five lookup tables (`result_types`, `fuzzers`, `servers`,
`paths`, `http_methods`) resolve `tests`'/`requests`'/`responses`' id
columns to human-readable names.

**Prefer the views.** They already do all of the above joins and name
resolution. Only write a raw join yourself when you need `request_headers`,
`response_headers`, or a request/response body — none of the views expose
those.

## Worked queries

Run any of these with:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --sql "<SQL>"
```

Add `--json` for machine-readable output — `--json` requires `--sql` (it
exits 2 otherwise; the canned summary below is text-table only). Omitting
`--sql` entirely prints that canned summary (results by type, false-positive
count, top errors/warnings by path) instead of running arbitrary SQL.

**1. True positives by path** — where are the real findings concentrated?

```sql
SELECT path, COUNT(*) AS count
FROM true_positives_view
GROUP BY path
ORDER BY count DESC;
```

**2. Errors by fuzzer** — which fuzzers are finding actual defects (as
opposed to warnings or false positives)?

```sql
SELECT fuzzer, COUNT(*) AS count
FROM true_positives_view
WHERE result = 'error'
GROUP BY fuzzer
ORDER BY count DESC;
```

**3. 5xx anywhere (should be empty)** — a false-positive rule can never
suppress a 5xx response unless `allow_suppressing_5xx: true` is set in
config (it defaults to `false`), so any row here is an unambiguous server
defect, not a classification artifact:

```sql
SELECT test_id, path, response_code, fuzzer
FROM true_positives_view
WHERE response_code >= 500;
```

**4. FP rules by match count** — which rules are doing the most
suppression work this run?

```sql
SELECT rule_id, why, match_count
FROM fp_rules
WHERE enabled = 1
ORDER BY match_count DESC;
```

**5. Zero-match rules** — staleness candidates; a rule that never fires is
either dead (the condition it guards against no longer occurs) or has a bug
in its `when`/`any_of` clause:

```sql
SELECT rule_id, why
FROM fp_rules
WHERE enabled = 1 AND match_count = 0;
```

**6. Response-code distribution for one path** — every result, not just
true positives, for a single path (swap in the path you care about):

```sql
SELECT response_code, result, COUNT(*) AS count
FROM test_results_view
WHERE path = '/widgets/{id}'
GROUP BY response_code, result
ORDER BY response_code;
```

## Generating the HTML report

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py report --db latest [--out PATH] [--open]
```

`--db latest` is the default — it can be omitted. Without `--out`, the report
is written to `results_dir/report-<run_id>.html`. `--open` opens it in the
default browser afterward. The report is a single self-contained HTML file
(inline CSS, no external requests): run provenance, result mix, false
positives by rule, zero-match rules, true positives by path, and a capped
table of individual true positives (ordered by response code descending, then
path) — large runs are capped in the report itself; use `query`/`--sql` above
for anything beyond the cap.
