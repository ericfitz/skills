# dependency-model hardening (#53) — design

Date: 2026-10-18. Issue: #53, the four residual items from the ericfitz/skills2#48 review.

## Decisions

The user asked for this issue to be handled autonomously (2026-10-18). Every decision
below was made by Claude under that instruction, not by the user.

1. **`$ref` hardening lives in `dependency-model/scripts/validate.py:resolve_refs`**
   (`tests/schema_check.py` only re-exports it).
   - A non-string `$ref` raises `ValueError` naming the value.
   - Any `#` in the ref (not only a leading one) is an unsupported fragment.
   - Cycle detection keys on the resolved target path, so two `shared.json` files in
     different directories are not a cycle.
   - A ref whose resolved target is not inside the top-level `base_dir` (an absolute
     path, or `..` escaping it) is rejected. The top-level directory is carried through
     the recursion, so a nested target may still refer to a sibling under that root.
   - The "every other key overrides" merge branch gets a direct test.
2. **`resilience-signatures.md` is pinned to `RESILIENCE_PATTERNS` by a test.** The test
   parses each language table in the reference, and for each row runs a sample source
   line kept in the test (keyed by the row's pattern cell) through
   `RESILIENCE_PATTERNS[lang]`, asserting the documented `kind`. A row with no sample, a
   sample with no row, or a pattern kind no row documents fails the test.
3. **`resilience_calls.raw` is cut before anything that is not the call.** After the
   match, `raw` is truncated at the first `;` and at the language's comment marker (`#`
   for Python, `//` for Go and JS/TS), then stripped and capped at `RAW_MAX_LEN`. This
   covers both examples in the issue (`... 'p-retry'; const pw = "..."` and an `@retry`
   line with a trailing `# token`). Masking with `QUERY_SECRET_PARAM_NAMES` was not
   chosen: it only recognizes `name=value` query parameters, and neither example is one.
4. **The credential-in-URL hand-off is stated as what it is.** Layer 1 has no channel
   between skills, and `report` reads per-category `assumptions[]`. `network` and
   `service` now say to record, in their own category's `assumptions[]`, that a
   credential is embedded in the URL (naming the entry id, never the value), because
   the `security` category cannot be told directly. No new mechanism is invented.
