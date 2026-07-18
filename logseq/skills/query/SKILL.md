---
name: query
version: 1.0.0
description: Answer questions from the user's local Logseq graph — search pages and journals, follow backlinks, surface TODOs and tagged content. Read-only. Use when the user asks "what do my notes say about…", "find in my Logseq", "which pages link to…", or similar.
---

# Logseq Query

Answer from the graph. Read-only — never write during this skill.

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

## Strategy — cheapest sufficient tier first

1. **Keyword lookup** → `rg` directly over the graph path from `resolve`:
   `rg -il "<term>" "<graph>/pages" "<graph>/journals"` then read the hits.
2. **Structural questions** (backlinks, orphans, tags, properties) →
   `logseq-cli.py scan` (whole index as JSON) or
   `logseq-cli.py backlinks --page "<Name>"`.
3. **Datalog** — only when `resolve` reported `"api_up": true` AND the
   question needs real graph queries (e.g. all TODOs with a deadline):
   `curl -s -X POST <api_url>/api -H "Authorization: Bearer $LOGSEQ_API_TOKEN"
   -H "Content-Type: application/json"
   -d '{"method":"logseq.DB.datascriptQuery","args":["<datalog>"]}'`

## Answering

- Cite pages as `[[Page Name]]` plus the file path.
- Journal hits: cite the date.
- Quote the relevant blocks rather than paraphrasing when the user asks
  "what did I write".
- If nothing is found, say so and name the strategies tried.
