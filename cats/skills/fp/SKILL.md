---
name: fp
version: 0.1.0
description: Manage CATS false-positive rules (add, review, reclassify). Use when asked to suppress a CATS finding, add a false-positive rule, audit existing rules, or reclassify a database against the current rules.
---

# cats:fp

Manages the declarative false-positive rules file. Adding a rule suppresses a
finding from every future report and query against `true_positives_view` — get
it wrong and a real bug goes quiet with nobody noticing. The `add` workflow
below exists specifically to make that hard to do by accident: **never skip
the dry-run step**, even for a rule that looks obviously safe.

Three modes: `add`, `review`, `reclassify`.

## Rule vocabulary

A rule is:

```yaml
- id: UNIQUE_ID
  why: One-line justification — required, every rule must explain itself.
  when: { <field>: <condition>, ... }   # AND across fields
  # or:
  any_of:                                # OR across blocks, AND within each
    - { <field>: <condition> }
    - { <field>: <condition> }
  enabled: true                          # optional, default true
  tags: [optional, list]
```

At least one of `when` / `any_of` is required — a rule with neither is
rejected when the file is loaded, as is an empty `when` or an empty block
inside `any_of`. Both may be given together, and are ANDed: the rule only
matches a record that satisfies `when` **and** at least one `any_of` block.

**Fields:**

| Field | Meaning |
|---|---|
| `result` | `error` / `warn` (only these two are ever classified) |
| `response_code` | HTTP status, as an integer |
| `fuzzer` | CATS fuzzer name |
| `path` | concrete request path |
| `contract_path` | templated OpenAPI path (e.g. `/widgets/{id}`), when CATS reported one |
| `method` | HTTP method |
| `url` | full request URL |
| `scenario` | CATS's scenario description |
| `result_reason`, `result_details` | CATS's classification reason/detail |
| `any_text` | `result_reason` + `result_details` concatenated with a space — convenient when you don't care which one matched |
| `request_body` | the raw request payload, as sent |
| `response_body` | the response's **JSON body, re-serialized** — empty (`""`) when the response wasn't JSON, so a condition on this field can never match a plain-text or HTML error page. Use `response_content_type` or `any_text` for those. |
| `response_content_type` | raw text, e.g. `application/json` |
| `json_body.<dotted.path>` | a value inside the parsed response JSON body, e.g. `json_body.error.code` |
| `request_header.<name>` | a request header value, matched case-insensitively by name |
| `json_body`, `request_headers` | the whole parsed JSON body / whole headers map, bare (no dotted path) — rarely useful directly, but valid with `exists` to check whether the response had *any* JSON body, or the request had *any* headers, at all |

**Operators** (used as `{field: {operator: value}}`; a bare
`{field: value}` is shorthand for `equals`):

| Operator | Operand | Case |
|---|---|---|
| `equals` | scalar | sensitive |
| `not_equals` | scalar | sensitive |
| `in` | list | sensitive |
| `contains` | scalar | insensitive |
| `contains_any` | list | insensitive |
| `contains_all` | list | insensitive |
| `starts_with` | scalar | insensitive |
| `starts_with_any` | list | insensitive |
| `ends_with` | scalar | insensitive |
| `matches` | regex string | insensitive (`re.search`, not full-match) |
| `exists` | `true`/`false` | — field present and non-null vs. absent/null |

A bare list on a scalar field (`{path: [a, b]}`) is rejected at load time —
it can never match; use `{path: {in: [a, b]}}`.

## `add` — draft, validate, then write

`classify --rules PATH` classifies against a rules file other than the
configured one, for that invocation only — it never reads or writes
`.local/cats/config.yaml`'s `false_positives:` file. That's what makes it
possible to fully validate a draft rule with **zero writes to the committed
rules file** until it has actually passed: no revert-on-failure branch to get
wrong, because nothing was ever written there to revert.

1. **Draft the rule.** Write the YAML block above, with a real `why`.

2. **Build a scratch rules file.** Copy the configured rules file's contents
   (the path in `.local/cats/config.yaml`'s `false_positives:` key) to a
   temporary file, and append the draft rule to its `rules:` list — same
   position it would occupy if added for real (the end of the file). This
   scratch file, not the committed one, is what gets tested; delete it when
   this workflow ends, on every branch (success, refusal, or decline).

3. **Dry-run against the scratch file:**

   ```
   uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py classify --db latest --dry-run --rules <scratch-file>
   ```

   This classifies a throwaway copy of the database against the scratch
   rules — the real database, `latest.db`, and the committed rules file are
   all untouched regardless of outcome. Read the output:
   - **"By rule"** — the new rule's own match count. This is always
     populated when the rule matched anything, and is the number to trust.
   - **"Newly suppressed"** — the exact test ids it would newly mark as
     false positive. Show these to the user; this is the whole point of the
     dry run. **This list is empty on a database that has never been
     classified before** (fresh `--db` pointing at a raw parse), even if the
     rule matched — that's expected, not a sign the rule did nothing; check
     "By rule" instead. (`--db latest` is normally already classified once,
     since a run classifies before `latest.db` is updated — see
     `/cats:report`.)
   - **"N rule match(es) refused for hitting a 5xx response"** (exit code 1)
     — if the new rule's id appears here, it matched at least one 5xx.

4. **Refuse on any 5xx match, unconditionally.** If step 3's violations
   list names this rule, delete the scratch file and stop — the committed
   rules file was never touched, so there is nothing to revert. Do not ask
   the user to override this one; a 5xx is always a real bug (see
   `/cats:report`, query 3, and `/cats:analyze`, which enforces the same
   rule). If the rule matched cleanly, keep going.

5. **Warn if it suppresses more than 5% of remaining true positives.**
   Compare the new rule's match count (from "By rule") against the current
   true-positive total (`SELECT COUNT(*) FROM true_positives_view` on the
   *real* database, unaffected by the dry run — see `/cats:report` for query
   syntax). If the ratio exceeds 5%, tell the user explicitly and get
   confirmation before continuing — a rule that broad is more often an
   overly generic condition than a genuinely narrow class of noise. If the
   user declines, delete the scratch file and stop; the committed file is
   still untouched.

6. **Only now write it.** Append the same draft rule to the *committed*
   rules file — the first and only write to it in this workflow — then
   reclassify the real database for real:

   ```
   uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py classify --db latest
   ```

   Report the "Newly suppressed" delta this produces (should match the dry
   run) as confirmation the rule is now live. Delete the scratch file.

## `review` — find zero-match and over-broad rules

**Zero-match** — rules that never fired this run; candidates for removal or a
bug in their condition:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --sql "
  SELECT rule_id, why FROM fp_rules WHERE enabled = 1 AND match_count = 0
"
```

**Over-broad** — every enabled rule with at least one match, ranked by the
share of what would otherwise be true positives it suppresses (`pct`); apply
the same 5% judgment call `add` uses when deciding which ones are worth a
closer look — the query itself doesn't filter, it just ranks:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py query --db latest --sql "
  SELECT r.rule_id, r.why, r.match_count,
         ROUND(100.0 * r.match_count /
               ((SELECT COUNT(*) FROM true_positives_view) + r.match_count), 2) AS pct
  FROM fp_rules r
  WHERE r.enabled = 1 AND r.match_count > 0
  ORDER BY r.match_count DESC
"
```

Present both lists with the rule's `why`; a stale or overly broad rule is
worth tightening or removing, but that edit is the user's call — describe
what you found and let them decide, don't rewrite rules unattended.

## `reclassify` — apply the current rules and show the delta

For when the rules file changed outside this workflow (manual edit, merge
from another branch) and the database needs to catch up:

```
uv run ${CLAUDE_PLUGIN_ROOT}/scripts/cats_tool.py classify --db latest
```

This is a fast, re-runnable pass (seconds, unlike a 30-40 minute fuzz run —
that separation is why classification is its own command). Report the
"Newly suppressed" and "Newly surfaced" lists from its output — that delta
*is* the reclassification's effect. If the database has never been
classified before (`run_meta.classified_at` was NULL), there is no delta to
show on this first pass; that's expected, not an error.
