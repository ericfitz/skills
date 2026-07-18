---
name: organize
version: 1.0.0
description: Merge/dedupe and restructure pages in the user's local Logseq graph — combine duplicate topic pages (rewriting inbound links), split overgrown pages, promote journal content into topic pages. Use when the user asks to merge, dedupe, reorganize, restructure, or consolidate Logseq pages.
---

# Logseq Organize

The judgment-heavy skill: you propose content, the CLI applies it safely.
Every operation shows its full plan and diff BEFORE touching files.

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

## Safety preamble (both flows)

- If `resolve` said `"api_up": false`, check whether the app is open anyway
  (`pgrep -x Logseq`). If it is, warn the user: rewrites bypass the app —
  they should avoid editing the affected pages in Logseq until done.
- Dirty-git-tree errors from the CLI: relay; `--force` only on explicit
  user say-so. Report the backup path from every applied result.

## Merge flow

1. Candidates: `logseq-cli.py lint --types near-duplicate,case-conflict`,
   plus `backlinks` overlap for pairs the user suspects.
2. Read BOTH page files in full. Propose: surviving title, merged outline
   (deduplicate blocks, keep both pages' unique content, preserve block
   properties), and note that inbound links to the losing name will be
   rewritten.
3. On approval, write the merged outline to a temp file, then:
   `logseq-cli.py merge --source "<Losing>" --target "<Surviving>"
   --content-file <tmp> --dry-run` → show diff → approval → re-run live.
4. When the surviving title contains spaces, check the dry-run diff for
   rewritten `#tag` references before approving: the tag rewrite is a
   literal text substitution, so `#LosingName` becomes `#Multi Word`, which
   Logseq parses as `#Multi` plus trailing text, not one tag. Fix those
   occurrences by hand to `#[[Multi Word]]` or plain `[[Multi Word]]` before
   applying.

## Restructure flow (split a page / promote journal content)

1. Read the affected pages. Propose the block moves as: which blocks leave
   which page, where they land, what remains.
2. On approval, build the full new content of EVERY affected page and write
   a changeset file: `{"changes": [{"path": "pages/<file>.md", "content":
   "<entire new file>"}, ...]}` (`"content": null` deletes a file). New
   pages that gain content from the move must keep an `[[origin]]` link back
   when context would otherwise be lost.
3. `logseq-cli.py apply --changeset-file <tmp> --dry-run` → show diff →
   approval → re-run live.
