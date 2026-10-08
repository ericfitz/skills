#!/usr/bin/env bash
# One-step installer for the efitz-skills marketplace, for Claude Code and/or
# Codex CLI. Idempotent: adds the marketplace only if missing, installs only
# the plugins not already installed.
#
# Usage: install.sh [claude|codex|all] [--codex-session-hook]
#
#   claude|codex|all       Which harness(es) to install into. Default: all
#                           (whichever of the two CLIs are found on PATH).
#   --codex-session-hook   Opt-in: merge a SessionStart entry into
#                           ~/.codex/hooks.json that refreshes
#                           .local/gh-projects.json at the start of each
#                           top-level Codex session. Codex does not execute
#                           plugin-shipped hooks (unlike Claude Code, which
#                           runs github/hooks/hooks.json natively), so this
#                           is the only way to get the same refresh there.
#                           Never applied without this flag.
#
# Never touches .local/ in this repo, and never modifies
# ~/.codex/hooks.json unless --codex-session-hook is passed.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
MARKETPLACE_NAME="efitz-skills"
MARKETPLACE_SOURCE="ericfitz/skills"

usage() {
  cat <<EOF
Usage: $(basename "$0") [claude|codex|all] [--codex-session-hook]

Installs the $MARKETPLACE_NAME marketplace and all its plugins into Claude
Code and/or Codex CLI. Default target is "all" (whichever CLIs are on PATH).

  --codex-session-hook   Also merge a SessionStart entry into
                          ~/.codex/hooks.json that refreshes
                          .local/gh-projects.json at Codex session start.
                          Opt-in; never applied without this flag.
EOF
}

TARGET=""
CODEX_SESSION_HOOK=0

for arg in "$@"; do
  case "$arg" in
    claude|codex|all)
      if [ -n "$TARGET" ]; then
        echo "Only one of claude|codex|all may be given (got '$TARGET' and '$arg')" >&2
        exit 1
      fi
      TARGET="$arg"
      ;;
    --codex-session-hook)
      CODEX_SESSION_HOOK=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      usage >&2
      exit 1
      ;;
  esac
done

TARGET="${TARGET:-all}"

if [ "$CODEX_SESSION_HOOK" -eq 1 ] && [ "$TARGET" = "claude" ]; then
  echo "Note: --codex-session-hook has no effect when the target is 'claude' (it only applies to codex)."
fi

# Print the plugin names declared in .claude-plugin/marketplace.json, one per line.
plugin_names() {
  python3 -c "
import json
with open('$REPO_ROOT/.claude-plugin/marketplace.json') as f:
    data = json.load(f)
for p in data['plugins']:
    print(p['name'])
"
}

install_claude() {
  if ! command -v claude >/dev/null 2>&1; then
    echo "claude CLI not found on PATH; skipping Claude Code install."
    return 0
  fi

  echo "== Claude Code =="

  if claude plugin marketplace list --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m.get('name') for m in data]
sys.exit(0 if '$MARKETPLACE_NAME' in names else 1)
"; then
    echo "marketplace '$MARKETPLACE_NAME' already configured"
  else
    echo "+ claude plugin marketplace add $MARKETPLACE_SOURCE"
    if ! claude plugin marketplace add "$MARKETPLACE_SOURCE"; then
      echo "FAILED: claude plugin marketplace add $MARKETPLACE_SOURCE" >&2
      exit 1
    fi
  fi

  local installed
  installed="$(claude plugin list --json 2>/dev/null || echo '[]')"

  local names
  if ! names="$(plugin_names)"; then
    echo "FAILED: could not read plugin names from $REPO_ROOT/.claude-plugin/marketplace.json" >&2
    exit 1
  fi

  local name
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    if printf '%s' "$installed" | python3 -c "
import json, sys
data = json.load(sys.stdin)
ids = [p.get('id', '') for p in data]
sys.exit(0 if '$name@$MARKETPLACE_NAME' in ids else 1)
"; then
      echo "plugin '$name' already installed"
    else
      echo "+ claude plugin install $name@$MARKETPLACE_NAME"
      if ! claude plugin install "$name@$MARKETPLACE_NAME"; then
        echo "FAILED: claude plugin install $name@$MARKETPLACE_NAME" >&2
        exit 1
      fi
    fi
  done <<< "$names"
}

# Merge a SessionStart hook into ~/.codex/hooks.json that resolves and runs
# the highest installed github plugin version's refresh_gh_projects.py at
# run time, so plugin upgrades never leave the hook stale. Merges (never
# clobbers) an existing hooks.json; idempotent (skips, untouched, if an
# entry already references refresh_gh_projects.py). A backup is written to
# hooks.json.bak only at the moment the file is actually about to be
# modified, and an existing .bak is never overwritten, so it always holds
# the file's original pre-installer content. Malformed JSON, or JSON that
# doesn't parse to an object, is left completely untouched (no backup, no
# write, no invented structure) — that's the user's to fix or discard.
install_codex_session_hook() {
  local codex_dir="$HOME/.codex"
  local hooks_file="$codex_dir/hooks.json"

  mkdir -p "$codex_dir"

  if ! python3 - "$hooks_file" <<'PYEOF'
import json
import shutil
import sys
from pathlib import Path

hooks_path = Path(sys.argv[1])
backup_path = hooks_path.parent / (hooks_path.name + ".bak")

command = (
    "bash -c 'p=$(ls -d \"$HOME\"/.codex/plugins/cache/efitz-skills/github/*/scripts/refresh_gh_projects.py "
    "2>/dev/null | sort -V | tail -1); [ -n \"$p\" ] && exec python3 \"$p\"; exit 0'"
)


def refuse(reason: str) -> None:
    print(
        f"REFUSING to modify {hooks_path}: {reason}\n"
        f"Fix or remove the file by hand, then re-run with --codex-session-hook.",
        file=sys.stderr,
    )
    sys.exit(1)


if hooks_path.exists():
    try:
        data = json.loads(hooks_path.read_text())
    except json.JSONDecodeError as e:
        refuse(f"not valid JSON ({e})")
    except OSError as e:
        refuse(f"could not be read ({e})")
    if not isinstance(data, dict):
        refuse(f"top-level JSON is a {type(data).__name__}, expected an object")
else:
    data = {}

hooks = data.setdefault("hooks", {})
if not isinstance(hooks, dict):
    refuse('the "hooks" key is not an object')

session_start = hooks.setdefault("SessionStart", [])
if not isinstance(session_start, list):
    refuse('"hooks.SessionStart" is not an array')

for matcher_entry in session_start:
    if not isinstance(matcher_entry, dict):
        continue
    for h in matcher_entry.get("hooks", []) or []:
        if isinstance(h, dict) and "refresh_gh_projects.py" in h.get("command", ""):
            print(f"{hooks_path}: a SessionStart entry already references refresh_gh_projects.py; leaving as-is")
            sys.exit(0)

session_start.append({
    "matcher": "startup",
    "hooks": [
        {
            "type": "command",
            "command": command,
            "shell": "bash",
            "async": True,
        }
    ],
})

if hooks_path.exists():
    if backup_path.exists():
        print(f"note: {backup_path} already exists; leaving it as the original backup")
    else:
        shutil.copy2(hooks_path, backup_path)
        print(f"backed up {hooks_path} to {backup_path}")

hooks_path.write_text(json.dumps(data, indent=2) + "\n")
print(f"merged SessionStart refresh_gh_projects.py hook into {hooks_path}")
PYEOF
  then
    echo "FAILED: could not merge SessionStart hook into $hooks_file (see message above)" >&2
    exit 1
  fi
}

install_codex() {
  if ! command -v codex >/dev/null 2>&1; then
    echo "codex CLI not found on PATH; skipping Codex install."
    return 0
  fi

  echo "== Codex =="

  if codex plugin marketplace list --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
names = [m.get('name') for m in data.get('marketplaces', [])]
sys.exit(0 if '$MARKETPLACE_NAME' in names else 1)
"; then
    echo "marketplace '$MARKETPLACE_NAME' already configured"
  else
    echo "+ codex plugin marketplace add $MARKETPLACE_SOURCE"
    if ! codex plugin marketplace add "$MARKETPLACE_SOURCE"; then
      echo "FAILED: codex plugin marketplace add $MARKETPLACE_SOURCE" >&2
      exit 1
    fi
  fi

  local installed
  installed="$(codex plugin list --json 2>/dev/null || echo '{"installed": []}')"

  local names
  if ! names="$(plugin_names)"; then
    echo "FAILED: could not read plugin names from $REPO_ROOT/.claude-plugin/marketplace.json" >&2
    exit 1
  fi

  local name
  while IFS= read -r name; do
    [ -z "$name" ] && continue
    if printf '%s' "$installed" | python3 -c "
import json, sys
data = json.load(sys.stdin)
ids = [p.get('pluginId', '') for p in data.get('installed', [])]
sys.exit(0 if '$name@$MARKETPLACE_NAME' in ids else 1)
"; then
      echo "plugin '$name' already installed"
    else
      echo "+ codex plugin add $name@$MARKETPLACE_NAME"
      if ! codex plugin add "$name@$MARKETPLACE_NAME"; then
        echo "FAILED: codex plugin add $name@$MARKETPLACE_NAME" >&2
        exit 1
      fi
    fi
  done <<< "$names"

  if [ "$CODEX_SESSION_HOOK" -eq 1 ]; then
    install_codex_session_hook
  else
    echo "Hint: pass --codex-session-hook to enable the .local/gh-projects.json session-start refresh for Codex (plugin-shipped hooks don't run there; a user-level ~/.codex/hooks.json entry is needed instead)."
  fi
}

case "$TARGET" in
  claude)
    install_claude
    ;;
  codex)
    install_codex
    ;;
  all)
    install_claude
    install_codex
    ;;
esac
