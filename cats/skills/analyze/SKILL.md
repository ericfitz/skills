---
name: analyze
version: 0.1.0
description: Triage CATS true positives into a remediation plan (real bug, spec gap, or false-positive candidate). Use after a CATS run completes, or when asked to analyze/triage CATS findings.
---

# cats:analyze

Turns the true positives from a completed CATS run into a remediation plan: for
each cluster of similar findings, decide whether it's a real bug, a gap in the
OpenAPI spec, or a false-positive candidate — and never guess. Every
disposition must be backed by evidence from the spec or the response, not by
how the finding "seems."

## 0. Check run validity first

A run can complete and still be worthless to analyze: if a large fraction of
its tests never reached the API (e.g. an unreachable server, or a throttled
kubectl port-forward silently dropping requests under load), the true/false
positive counts reflect connection failures, not API behavior. Before
clustering anything, check the connection-error rate:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --json --sql "
  SELECT (SELECT COUNT(*) FROM responses WHERE response_code IN (953, 999)) AS connection_errors,
         (SELECT COUNT(*) FROM tests) AS total_tests
"
```

If `connection_errors / total_tests` exceeds ~1%, **stop** — do not draw
per-rule or per-path conclusions from this database. `run` itself already
gates this (a contaminated run exits 3 and never becomes `latest.db`), so
seeing it here on `--db latest` most likely means an explicit `--db <file>`
pointed at an older, invalid run, or the gate's threshold doesn't match this
analysis's bar. Report the contamination percentage to the user and ask
whether to re-run instead of proceeding.

## 1. Resolve the database and the spec

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --json --sql "SELECT run_id, spec_path FROM run_meta"
```

`--db latest` is the default if the user doesn't name a specific run. Read
`.local/cats/config.yaml`'s `spec:` value (or `spec_path` from the query
above) and read that OpenAPI file — every disposition below needs to check
against it.

## 2. Pull and cluster the true positives

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --json --sql "
  SELECT path, contract_path, http_method, fuzzer, response_code,
         COUNT(*) AS count, MIN(test_id) AS example_test_id
  FROM true_positives_view
  GROUP BY path, fuzzer, response_code
  ORDER BY response_code DESC, count DESC
"
```

Cluster by `(path, fuzzer, response_code)` — this is the unit of triage, not
the individual test. For each cluster, pull the example test's
`result_reason`, `result_details`, and request/response bodies for closer
inspection. `test_results_view` doesn't carry `result_details` or either
body — those live on `tests`/`requests`/`responses` — so join them explicitly
rather than selecting `*` from the view:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --json --sql "
  SELECT t.test_id, t.scenario, t.result_reason, t.result_details,
         req.request_body, resp.response_body, resp.response_content_type
  FROM tests t
  JOIN requests req ON req.test_id = t.id
  JOIN responses resp ON resp.test_id = t.id
  WHERE t.test_id = '<example_test_id>'
"
```

Note `response_body` is the response's JSON body, re-serialized — empty when
the response wasn't JSON (see `/cats:fp`'s field vocabulary for the same
caveat, since it applies equally to a rule condition on this field).

(See `/cats:report` for the full schema and more query patterns.)

## 3. Disposition each cluster

Exactly one of three, and always with a cited reason:

- **Real bug** — the response contradicts the spec's documented behavior for
  a code it *does* document (e.g. spec says this operation returns 400 with
  a validation-error body on malformed input; the server 500'd instead), or
  the response is self-evidently broken regardless of the spec (a stack
  trace in the body, a hung connection, corrupted JSON).
- **Spec gap** — the response code is one the server plausibly means to
  return, but that operation's `responses` object in the OpenAPI spec
  doesn't document it. Cite the operation (path + method) and confirm by
  reading the spec's `responses` keys for that operation — don't assert a
  gap without checking.
- **False-positive candidate** — the finding reflects fuzzer behavior that
  isn't a defect in this API at all (the fuzzer's input isn't a request a
  real client would ever send, or the "failure" is actually correct
  behavior CATS scored wrong). This needs the same evidence bar as the
  other two: point at what in the response or spec makes it not a bug.

**Every 5xx response is Real bug and goes first, unconditionally.** Never
disposition a 5xx as a false-positive candidate, regardless of how
fuzzer-specific the triggering input looks — a server that crashes on bad
input is a real defect no matter how contrived the input was. (This mirrors
the tool-level rule: `classify` refuses to let any false-positive rule
suppress a 5xx unless the repo has explicitly opted in via
`allow_suppressing_5xx: true`.)

## 4. Produce the remediation plan

Order strictly by severity:

1. Every 5xx cluster (Real bug, always).
2. Remaining Real bug clusters, most-affected-paths first.
3. Spec gap clusters.
4. False-positive candidates, last.

For each item: path, method, response code, fuzzer(s), affected test count,
disposition, and the one-line evidence that justifies it (a spec quote, a
response excerpt, or the specific contradiction).

## 5. Hand off false-positive candidates

For each false-positive candidate, draft a rule (id, `why`, `when`/`any_of`
using the field/operator vocabulary from `/cats:fp`) and hand it to
`/cats:fp add` rather than writing to the rules file yourself — that skill's
dry-run-before-writing workflow is the safety check against suppressing a
real bug by mistake. Present the drafted rule to the user as part of the
plan; do not apply it here.
