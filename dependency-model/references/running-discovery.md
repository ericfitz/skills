# Running discovery

The sequence for producing a complete `dependency-model` picture of a repository:
one seed contract, one scan, six independent skills reading the same scan output.

## The sequence

1. **Invoke `profile:topology`** to get the seed contract. It supplies
   `real_dependencies` and `external_third_parties` as starting evidence for the
   `service` category, and establishes the repo's deployment shape that several
   categories' evidence should be read against.
2. **Run `depscan.py` once** against the target repository. Every one of the six
   skills reads this same output; the scan is not re-run per skill.
3. **Run the six skills — in any order, or concurrently** — each reading the same
   scan output and emitting its own envelope with exactly one category populated.
   No skill depends on another skill's output; only on the shared scan and the
   seed contract from step 1.

## Commands

```bash
uv run --script ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> > /tmp/depscan.json
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/depscan.py <repo> > /tmp/depscan.json   # fallback, no deps
```

Use the `uv run --script` form when `uv` is available — it resolves the script's
declared dependencies automatically. The `python3` fallback runs the same script
with only the standard library, for environments where `uv` isn't installed;
`depscan.py` is written to support both invocation paths without a code change
between them.

## The six skills

Each names its own category and consumes the scan output at `/tmp/depscan.json`
(or wherever it was written) plus its own contract and reference documents. Run
any or all of the following, in any order:

- `/dependency-model:package`
- `/dependency-model:service`
- `/dependency-model:config`
- `/dependency-model:security`
- `/dependency-model:platform`
- `/dependency-model:network`

## Why there is no orchestrator here

This layer deliberately ships no seventh skill that runs the other six and
merges their output. That is by design (D8 in the design spec), not an
oversight: layer 2's report skill already has to gather all six contracts before
it can render anything, which makes it the orchestrator whether or not layer 1
also builds one. Building an orchestrator in this layer would mean building the
same gathering logic twice — once here, once again in layer 2 — for no benefit,
since nothing in layer 1 itself needs the six results merged.

A caller who wants all six today invokes them directly, in the sequence above;
a caller who wants a rendered report waits for layer 2's report skill, which
performs that invocation and the merge described next as part of producing its
output.

## How the six envelopes merge

Each skill emits a full envelope — `contract_version`, `target`, `seeded_by`,
and a `categories` object — with exactly one key populated under `categories`
(per D6 in the design spec). Merging six such envelopes into one complete
picture is a **key union under `categories`**: take the single populated key
from each envelope and union them into one `categories` object. No conflict
resolution is needed because no two skills ever populate the same key, and no
transform is needed because every skill's single-category output is already
valid against the shared envelope schema on its own.

## `exclusions[]` is the single source of truth

`depscan.py`'s output carries an `exclusions[]` list — a fixed set, not a
configurable one: `EXCLUDE_DIRS` in `walk.py` is the sole source, and
`depscan.py` takes no `--exclude` flag or other config input to extend it.
See `walk.py` for the current membership; this document does not restate it,
so it cannot go stale against the code. This fixed list is the single source
of truth for both tools that need to skip the same noise:

- The `package` skill reads `exclusions[]` and rewrites each bare directory
  name to a `**/<name>` glob before passing it to `syft --exclude` — see
  `skills/package/SKILL.md` step 2 for the exact form and why the bare and
  root-anchored forms don't work.
- The five file-scanning skills inherit the same list by reading it from the
  scan index — they don't re-derive their own exclusion rules.

Without it, `syft scan dir:` reports a nested virtualenv or `node_modules` tree
as part of the project's own dependency set — verified against this repository,
where an unscoped `syft scan dir:.` reported 270 packages against the 2 direct
dependencies plus one optional extra that `pyproject.toml` actually declares,
with 188 coming from a nested `writing/skills/boring/.venv/` and 7 from the
repo's own `.venv/`. Reading
`exclusions[]` from the shared index, rather than each tool maintaining its own
list, is what keeps that from happening independently in six places.
