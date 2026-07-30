---
name: lint
description: Find consistency problems in the user's local Logseq graph — broken links, case-conflicting link spellings, orphan pages, near-duplicate page names, unparseable pages — and apply chosen fixes. Use when the user asks to lint, clean up, or check their Logseq graph for consistency.
---

# Logseq Lint

Scan for findings; the user chooses what to fix; every fix shows a dry-run
diff first. Nothing auto-applies.

## CLI

All mechanics go through one CLI:

    uv run "${CLAUDE_PLUGIN_ROOT}/scripts/logseq-cli.py" <command> [args...]

`${CLAUDE_PLUGIN_ROOT}` is this plugin's install root. If the variable is not
pre-substituted when you read this file, resolve it yourself: take the
directory containing this SKILL.md and walk up two levels (`skills/<name>/` →
plugin root). The scripts are stdlib-only; if `uv` is unavailable, use
`python3` directly. Below written as `logseq-cli.py` for brevity.

Every command prints one JSON value. `{"error": ...}` + exit 1 means stop and
show the user the message — do not improvise around it.

## Graph resolution

Run `logseq-cli.py resolve` first.
- `"source": "discovered"` → re-run with `--write-config` to persist, tell the user.
- Error mentioning "multiple Logseq graphs" → show the candidate paths, ask
  the user which one, then write `~/.config/logseq-skills/config.json`:
  `{"graphs": {"<name>": {"path": "<chosen>"}}, "default_graph": "<name>",
  "api": {"url": "http://127.0.0.1:12315", "token_env": "LOGSEQ_API_TOKEN"}}`
  and re-run.
- `"api_up": false` is fine — writes fall back to files automatically.

## Process

1. Resolve, then `logseq-cli.py lint` (optionally `--types broken-link,orphan,...`).
2. Present findings grouped by type, with counts. Explain what each type
   means; recommend which groups are safe to fix mechanically:
   - `case-conflict` → pick the canonical spelling (prefer an existing page's
     actual name), fix via `rename-refs`.
   - `broken-link` → per link: rename to an existing page (`rename-refs`) if
     it is clearly a typo/rename, else leave (a link to a future page is
     normal in Logseq — say so). Links to journal pages by their display
     name (e.g. `[[Jul 17th, 2026]]`) commonly show up here too, because the
     index keys journal pages by file stem (`2026_07_17`) rather than the
     display date — treat these as expected noise, not real breakage, and
     tell the user so.
   - `unparseable` → show the page and the parse error; fixing the file is a
     manual edit the user must approve; the CLI will never rewrite these.
   - `orphan` / `near-duplicate` → informational; offer the organize skill
     for merges.
3. For each approved mechanical fix:
   `logseq-cli.py rename-refs --old "<X>" --new "<Y>" --dry-run` → show diff
   → on approval re-run without `--dry-run`.
4. Dirty-git-tree errors: relay to the user; only pass `--force` if they
   explicitly say to. Backups land in `<graph>/logseq/.backups/<stamp>/` —
   include the path in your report.
