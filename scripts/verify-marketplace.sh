#!/usr/bin/env bash
# Structural sanity check for the efitz-skills marketplace.
# No /plugin commands; just verifies files and content patterns.
# Exits non-zero on first failure with a clear message.

set -uo pipefail

REPO="${REPO:-/Users/efitz/Projects/skills}"
cd "$REPO" || { echo "FAIL: cannot cd to $REPO"; exit 1; }

PASS=0
FAIL=0
FAILURES=()

ok()   { PASS=$((PASS+1)); printf '  ok    %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); FAILURES+=("$1"); printf '  FAIL  %s\n' "$1"; }
hdr()  { printf '\n== %s ==\n' "$1"; }

# ---------- marketplace.json ----------
hdr "marketplace.json"

if ! python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))" 2>/dev/null; then
  bad ".claude-plugin/marketplace.json: missing or invalid JSON"
  echo
  echo "Cannot continue without a parseable marketplace.json."
  exit 1
fi
ok ".claude-plugin/marketplace.json parses as JSON"

PLUGIN_COUNT=$(python3 -c "import json; print(len(json.load(open('.claude-plugin/marketplace.json'))['plugins']))")
if [ "$PLUGIN_COUNT" -eq 16 ]; then
  ok "marketplace.json has 16 plugin entries"
else
  bad "marketplace.json has $PLUGIN_COUNT plugin entries (expected 16)"
fi

# ---------- Per-plugin structural checks ----------
hdr "Per-plugin structure"

# (name, category) tuples expected in marketplace.json
declare -a PLUGINS=(
  "plugin-vetter:security"
  "race-condition-audit:security"
  "analyze-localization-files:localization"
  "validate-localization-coverage:localization"
  "detect-non-localizable:localization"
  "translate-to-language:localization"
  "update-json-localization-file:localization"
  "validate-translation:localization"
  "file-github-bug:misc"
  "verify-migrate-doc:misc"
  "visual-regression-triage:misc"
  "boring:writing"
  "bump:development"
  "backlog-next:development"
  "dedupe:development"
  "localization-backfill:localization"
)

for entry in "${PLUGINS[@]}"; do
  name="${entry%:*}"
  expected_cat="${entry#*:}"

  # plugin.json exists and parses
  if [ ! -f "$name/.claude-plugin/plugin.json" ]; then
    bad "$name: .claude-plugin/plugin.json missing"
    continue
  fi
  if ! python3 -c "import json; json.load(open('$name/.claude-plugin/plugin.json'))" 2>/dev/null; then
    bad "$name: .claude-plugin/plugin.json invalid JSON"
    continue
  fi

  # plugin.json fields
  pn=$(python3 -c "import json; print(json.load(open('$name/.claude-plugin/plugin.json')).get('name',''))")
  pv=$(python3 -c "import json; print(json.load(open('$name/.claude-plugin/plugin.json')).get('version',''))")
  if [ "$pn" != "$name" ]; then bad "$name: plugin.json name=$pn (expected $name)"; continue; fi
  if [ "$pv" != "1.0.0" ]; then bad "$name: plugin.json version=$pv (expected 1.0.0)"; continue; fi

  # SKILL.md exists at the expected nested path
  if [ ! -f "$name/skills/$name/SKILL.md" ]; then
    bad "$name: skills/$name/SKILL.md missing"
    continue
  fi

  # SKILL.md has frontmatter with name matching plugin name
  fm_name=$(awk '/^---$/{c++; next} c==1 && /^name:/ {sub(/^name:[[:space:]]*/,""); print; exit}' "$name/skills/$name/SKILL.md")
  if [ "$fm_name" != "$name" ]; then
    bad "$name: SKILL.md frontmatter name='$fm_name' (expected $name)"
    continue
  fi

  # No stale SKILL.md at the old flat location
  if [ -f "$name/SKILL.md" ]; then
    bad "$name: stale $name/SKILL.md still exists at flat location"
    continue
  fi

  # Marketplace entry exists with correct category
  cat=$(python3 -c "
import json
d = json.load(open('.claude-plugin/marketplace.json'))
e = next((p for p in d['plugins'] if p.get('name')=='$name'), None)
print(e['category'] if e else '')
")
  if [ "$cat" != "$expected_cat" ]; then
    bad "$name: marketplace category='$cat' (expected $expected_cat)"
    continue
  fi

  ok "$name (category=$expected_cat)"
done

# ---------- Command-wrapper plugins (4) ----------
hdr "Command wrappers (bump, backlog-next, dedupe, localization-backfill)"

for plugin in bump backlog-next dedupe localization-backfill; do
  wrapper="$plugin/commands/$plugin.md"
  if [ ! -f "$wrapper" ]; then
    bad "$plugin: command wrapper $wrapper missing"
    continue
  fi
  # Must reference the plugin:skill Skill tool invocation
  if ! grep -q "\`$plugin:$plugin\`" "$wrapper"; then
    bad "$plugin: wrapper does not reference \`$plugin:$plugin\` skill name"
    continue
  fi
  # Must pass through \$ARGUMENTS
  if ! grep -q '\$ARGUMENTS' "$wrapper"; then
    bad "$plugin: wrapper does not pass through \$ARGUMENTS"
    continue
  fi
  ok "$plugin: command wrapper OK"
done

# ---------- No stale legacy env vars or hardcoded paths ----------
hdr "Skill bodies: no legacy paths or env vars"

# $SKILL_DIR should be gone from all SKILL.md files
hits=$(grep -rln '\$SKILL_DIR' --include='SKILL.md' . 2>/dev/null || true)
if [ -n "$hits" ]; then
  bad "Stale \$SKILL_DIR references found in:\n$hits"
else
  ok "No \$SKILL_DIR references in any SKILL.md"
fi

# $COMMAND_DIR should be gone
hits=$(grep -rln '\$COMMAND_DIR' --include='SKILL.md' . 2>/dev/null || true)
if [ -n "$hits" ]; then
  bad "Stale \$COMMAND_DIR references found in:\n$hits"
else
  ok "No \$COMMAND_DIR references in any SKILL.md"
fi

# ~/.claude/scripts/ should be gone from skill bodies
hits=$(grep -rln '~/\.claude/scripts\|/\.claude/scripts/' --include='SKILL.md' . 2>/dev/null || true)
if [ -n "$hits" ]; then
  bad "Stale ~/.claude/scripts/ references found in:\n$hits"
else
  ok "No ~/.claude/scripts/ references in any SKILL.md"
fi

# ~/.claude/agents/ should be gone from skill bodies
hits=$(grep -rln '~/\.claude/agents\|/\.claude/agents/' --include='SKILL.md' . 2>/dev/null || true)
if [ -n "$hits" ]; then
  bad "Stale ~/.claude/agents/ references found in:\n$hits"
else
  ok "No ~/.claude/agents/ references in any SKILL.md"
fi

# ---------- Bundled scripts present where SKILL.md references them ----------
hdr "Bundled scripts: presence at \${CLAUDE_PLUGIN_ROOT} paths"

# (plugin, relative-path-from-plugin-root)
declare -a SCRIPTS=(
  "bump:none"
  "backlog-next:scripts/gh-issues.py"
  "dedupe:scripts/dedupe-report.py"
  "localization-backfill:scripts/find_duplicate_localizations.py"
  "analyze-localization-files:skills/analyze-localization-files/scripts/check-i18n.py"
  "validate-localization-coverage:skills/validate-localization-coverage/scripts/check-i18n.py"
)

for entry in "${SCRIPTS[@]}"; do
  plugin="${entry%%:*}"
  rel="${entry#*:}"
  if [ "$rel" = "none" ]; then
    continue
  fi
  if [ -f "$plugin/$rel" ]; then
    ok "$plugin/$rel exists"
  else
    bad "$plugin/$rel missing"
  fi
done

# ---------- dedupe-specific: 3 worker agents present ----------
hdr "Dedupe worker agents"

for agent in dedupe-analyzer dedupe-grouper dedupe-deduplicator; do
  af="dedupe/agents/$agent.md"
  if [ ! -f "$af" ]; then
    bad "dedupe/agents/$agent.md missing"
    continue
  fi
  # has a name: field in frontmatter
  n=$(awk '/^---$/{c++; next} c==1 && /^name:/ {sub(/^name:[[:space:]]*/,""); print; exit}' "$af")
  if [ -z "$n" ]; then
    bad "dedupe/agents/$agent.md missing name: in frontmatter"
    continue
  fi
  ok "dedupe/agents/$agent.md (name='$n')"
done

# Confirm SKILL.md references each agent file via \${CLAUDE_PLUGIN_ROOT}/agents/
for agent in dedupe-analyzer dedupe-grouper dedupe-deduplicator; do
  if grep -q "\${CLAUDE_PLUGIN_ROOT}/agents/$agent.md" dedupe/skills/dedupe/SKILL.md; then
    ok "dedupe SKILL.md references $agent via \${CLAUDE_PLUGIN_ROOT}/agents/$agent.md"
  else
    bad "dedupe SKILL.md does not reference \${CLAUDE_PLUGIN_ROOT}/agents/$agent.md"
  fi
done

# ---------- repo-root commands/ dir is gone ----------
hdr "Repo cleanup"

if [ ! -d "commands" ]; then
  ok "repo-root commands/ removed"
else
  bad "repo-root commands/ still exists (should have been removed by Task 18)"
fi

# ---------- summary ----------
hdr "Summary"
printf 'PASS: %d\nFAIL: %d\n' "$PASS" "$FAIL"

if [ "$FAIL" -ne 0 ]; then
  echo
  echo "Failures:"
  for f in "${FAILURES[@]}"; do
    printf '  - %s\n' "$f"
  done
  exit 1
fi

echo
echo "All structural checks passed. Safe to run /plugin marketplace add and /plugin install."
exit 0
