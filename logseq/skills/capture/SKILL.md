---
name: capture
description: Capture a note, TODO, or meeting summary into the user's local Logseq graph — today's journal by default, or a named page. Use when the user says "add this to Logseq", "log this in my journal", "note this down in Logseq", or wants a TODO captured.
---

# Logseq Capture

Add user-provided content to the Logseq graph. Judgment (formatting,
destination) is yours; writing is the CLI's.

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

1. Resolve the graph (above).
2. Decide the destination: today's journal unless the user names a page.
3. Format the content as Logseq outline text:
   - Actionable items start with `TODO `. Add `SCHEDULED: <YYYY-MM-DD Day>`
     on a continuation line only when the user gave a date.
   - Multi-line content: first line is the bullet, later lines are
     continuations (the CLI handles indentation).
   - Add `[[links]]` / `#tags` only for names/topics the user actually said.
4. Append — one CLI call per top-level bullet:
   - Journal: `logseq-cli.py append --journal --text "<text>"`
   - Page: `logseq-cli.py append --page "<Page Name>" --text "<text>"`
   - Brand-new page wanted: `logseq-cli.py create-page --page "<Name>" --text "<full outline>"`
5. Report to the user: what was written, where (`target`), and whether it
   went `via: api` (visible in the app immediately) or `via: files`.
