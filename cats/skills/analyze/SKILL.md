---
name: analyze
description: Triage CATS true positives into a remediation plan (real bug, spec gap, or false-positive candidate). Use after a CATS run completes, or when asked to analyze/triage CATS findings.
---

# cats:analyze

Turns the true positives from a completed CATS run into a remediation plan: for
each cluster of similar findings, decide whether it's a real bug, a gap in the
OpenAPI spec, or a false-positive candidate — and never guess. Every
disposition must be backed by evidence from the spec or the response, not by
how the finding "seems."

## 0. Check run validity first

A run can complete and still be worthless to analyze, in three distinct ways:

- **Transport.** A large fraction of tests never reached the API (an
  unreachable server, or a throttled kubectl port-forward silently dropping
  requests under load), so the true/false positive counts reflect connection
  failures rather than API behavior.
- **Credential.** The campaign lost its bearer token partway through — most
  often by fuzzing an endpoint that revokes the caller's own token — and
  every test after that point exercised only the unauthenticated path.
- **Fixture.** The campaign deleted its own seeded test data, so every test
  nested under the dead fixture ran against a 404. These show up as a wall of
  plausible-looking 404 "findings" on endpoints that are in fact fine.

All three are the same underlying failure: **the campaign sabotaged its own
ability to keep testing, and still reported as complete.** Assume it can happen
in ways not yet enumerated. The diagnostic tell is always identical — findings
that cluster by *when* the test ran rather than by *what* it tested. Before
believing any cluster, check whether its failures begin at some test number and
never stop; if they do, something the fuzzer did to the system caused them, not
the endpoint under test.

Check all three before clustering anything:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --json --sql "
  SELECT (SELECT COUNT(*) FROM responses WHERE response_code IN (953, 999)) AS connection_errors,
         (SELECT COUNT(*) FROM tests t JOIN responses r ON r.test_id = t.id
           WHERE r.response_code = 401 AND t.is_false_positive = 0)        AS unauthenticated,
         (SELECT COUNT(*) FROM tests) AS total_tests
"
```

If `connection_errors / total_tests` exceeds ~1%, or
`unauthenticated / total_tests` exceeds ~5%, **stop** — do not draw per-rule
or per-path conclusions from this database. `run` itself already gates both (a
contaminated run exits 3 and never becomes `latest.db`), so seeing it here on
`--db latest` most likely means an explicit `--db <file>` pointed at an older,
invalid run, or the gate's threshold doesn't match this analysis's bar. Report
the contamination percentage to the user and ask whether to re-run instead of
proceeding.

To identify the culprit, find where the 401s start (the cliff, not the first
401 — isolated early 401s are normal), then read the successful mutations
immediately before it:

```sql
-- 1. the cliff: the bucket where the 401 rate jumps
SELECT (t.test_number / 1000) * 1000 AS bucket,
       SUM(CASE WHEN r.response_code = 401 THEN 1 ELSE 0 END) AS unauth,
       COUNT(*) AS total
FROM tests t JOIN responses r ON r.test_id = t.id
GROUP BY bucket ORDER BY bucket;

-- 2. every 2xx mutation before it; one of them revoked the token
SELECT t.test_number, m.method, p.path, r.response_code
FROM tests t
JOIN paths p ON p.id = t.path_id
JOIN requests rq ON rq.test_id = t.id
JOIN http_methods m ON m.id = rq.http_method_id
JOIN responses r ON r.test_id = t.id
WHERE r.response_code BETWEEN 200 AND 299
  AND m.method IN ('POST', 'PUT', 'PATCH', 'DELETE')
  AND t.test_number < :cliff
ORDER BY t.test_number DESC LIMIT 20;
```

Add whatever that turns up to `cats.skip_paths` and re-run.

The same cliff query diagnoses a **fixture** death — only the fix differs. Look
for a successful `DELETE` on an anchor path (`/things/{id}`) followed by a run of
404s on everything nested under it (`/things/{id}/...`):

```sql
-- successful DELETEs, earliest first: each one consumed something
SELECT t.test_number, m.method, p.path
FROM tests t
JOIN paths p ON p.id = t.path_id
JOIN requests rq ON rq.test_id = t.id
JOIN http_methods m ON m.id = rq.http_method_id
JOIN responses r ON r.test_id = t.id
WHERE m.method = 'DELETE' AND r.response_code BETWEEN 200 AND 299
ORDER BY t.test_number;

-- 404 rate per path, to see which families died wholesale
SELECT p.path,
       SUM(CASE WHEN r.response_code = 404 THEN 1 ELSE 0 END) AS not_found,
       COUNT(*) AS total
FROM tests t JOIN paths p ON p.id = t.path_id JOIN responses r ON r.test_id = t.id
GROUP BY p.path HAVING not_found > 0 ORDER BY not_found DESC LIMIT 20;
```

The fix is not `skip_paths` here — that would drop the anchor's DELETE coverage
entirely. Point the anchor path at a **throwaway decoy** id in the seed's
generated refData, so a successful DELETE consumes the decoy while the fixture
the nested paths depend on survives. Nested paths are distinct path strings and
keep the real fixture. `run`'s fixture gate names the anchor to fix in its
failure message, and says whether that anchor already has a decoy (in which case
the decoy itself is broken, not missing).

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
