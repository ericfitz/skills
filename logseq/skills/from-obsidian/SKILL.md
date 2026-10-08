---
name: from-obsidian
description: Convert and import notes from a local Obsidian vault into the user's Logseq graph — a single note, a folder, or the whole vault. Repeatable; already-imported unchanged notes are skipped. Use when the user asks to transfer, migrate, or import Obsidian notes into Logseq.
---

# Obsidian → Logseq Import

Conversion (prose → outline, frontmatter → properties, embeds/assets) is the
CLI's; scoping, collision decisions, and the final go-ahead are yours + the
user's.

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

## Vault resolution

`resolve` reports `obsidian_vault`. If null: ask the user for the vault path
once, add `"obsidian_vault": "<path>"` to
`~/.config/logseq-skills/config.json`, and continue with `--vault "<path>"`.

## Process

1. Scope from the user's request: one note (`--scope <file>`), a folder
   (`--scope <dir>`), or the whole vault (no `--scope`).
2. Plan: `logseq-cli.py convert-plan [--vault V] [--scope P]`. Present as a
   table: counts by status (`new` / `changed` / `unchanged` /
   `collision`), every collision by name, and all conversion warnings
   (nested frontmatter dropped, unknown callouts, missing assets, flattened
   numbered lists).
   - `collision` = a native Logseq page already has that name; it will NOT
     be overwritten. Offer: rename the Obsidian note, or merge manually
     later via the organize skill.
3. Dry run: `logseq-cli.py convert-import ... --dry-run` → show the diff
   (or its size + a sample for large imports).
4. On approval: re-run without `--dry-run`. Assets are copied into
   `<graph>/assets/`.
5. Report: pages imported (new/changed), unchanged skips, collisions left
   for the user, assets copied, backup path if one was made. Asset filename
   collisions across notes are auto-resolved by appending an `-<hash8>`
   suffix (an 8-character content hash) to the copied file — call this out
   so the user isn't surprised by a renamed asset like `diagram-a1b2c3d4.png`.

Notes are stamped with `imported-from::` and `import-hash::` page
properties — that is what makes re-runs skip unchanged notes. Tell the user
these properties must stay if they want re-import detection.
