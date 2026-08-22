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
DIR_COUNT=$(ls -d */.claude-plugin/plugin.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$PLUGIN_COUNT" -eq "$DIR_COUNT" ]; then
  ok "marketplace.json has $PLUGIN_COUNT plugin entries, matching $DIR_COUNT plugin dirs"
else
  bad "marketplace.json has $PLUGIN_COUNT plugin entries but $DIR_COUNT plugin dirs have .claude-plugin/plugin.json"
fi

# ---------- Per-plugin structural checks ----------
hdr "Per-plugin structure (multi-skill)"

# "plugin:category:skill1,skill2,..."  — skills are the dir names under <plugin>/skills/
declare -a PLUGINS=(
  "loc:localization:analyze,coverage,detect-nonloc,translate-to,update-json,validate-translation,backfill"
  "security:security:vet-plugin,race-cond"
  "github:development:backlog,create-issue"
  "ui:development:vrt"
  "wiki:documentation:verify-doc"
  "dev:development:dedupe,sem-annotate,sem-auto"
  "writing:writing:boring"
  "deps:development:bump"
  "logseq:productivity:capture,query,lint,organize,from-obsidian"
  "cats:testing:analyze,fp,init,report,run"
  "profile:development:docs,journeys,stack,topology"
  "itest:development:conventions,critique,design,state"
  "openapi:development:arazzo,init"
  "env:development:check"
  "dependency-model:development:config,network,package,platform,security,service"
)

# Guard against this array going stale again: it must name every plugin dir.
ARRAY_COUNT=${#PLUGINS[@]}
if [ "$ARRAY_COUNT" -eq "$DIR_COUNT" ]; then
  ok "PLUGINS array covers all $DIR_COUNT plugin dirs"
else
  bad "PLUGINS array has $ARRAY_COUNT entries but $DIR_COUNT plugin dirs exist — update the array"
fi

for entry in "${PLUGINS[@]}"; do
  IFS=: read -r name expected_cat skills_csv <<< "$entry"

  # plugin.json exists and parses
  if [ ! -f "$name/.claude-plugin/plugin.json" ]; then
    bad "$name: .claude-plugin/plugin.json missing"; continue
  fi
  if ! python3 -c "import json; json.load(open('$name/.claude-plugin/plugin.json'))" 2>/dev/null; then
    bad "$name: .claude-plugin/plugin.json invalid JSON"; continue
  fi

  # plugin.json fields
  pn=$(python3 -c "import json; print(json.load(open('$name/.claude-plugin/plugin.json')).get('name',''))")
  pv=$(python3 -c "import json; print(json.load(open('$name/.claude-plugin/plugin.json')).get('version',''))")
  if [ "$pn" != "$name" ]; then bad "$name: plugin.json name=$pn (expected $name)"; continue; fi
  if ! printf '%s' "$pv" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then bad "$name: plugin.json version='$pv' (expected semver X.Y.Z)"; continue; fi

  # Marketplace entry exists with correct category
  cat=$(python3 -c "
import json
d = json.load(open('.claude-plugin/marketplace.json'))
e = next((p for p in d['plugins'] if p.get('name')=='$name'), None)
print(e['category'] if e else '')
")
  if [ "$cat" != "$expected_cat" ]; then
    bad "$name: marketplace category='$cat' (expected $expected_cat)"; continue
  fi

  # No stale SKILL.md at the plugin's flat location
  if [ -f "$name/SKILL.md" ]; then
    bad "$name: stale $name/SKILL.md at plugin root"; continue
  fi

  # Each declared skill: SKILL.md exists with frontmatter name == skill dir
  plugin_ok=1
  IFS=, read -ra skills <<< "$skills_csv"
  for skill in "${skills[@]}"; do
    sm="$name/skills/$skill/SKILL.md"
    if [ ! -f "$sm" ]; then
      bad "$name: skills/$skill/SKILL.md missing"; plugin_ok=0; continue
    fi
    fm_name=$(awk '/^---$/{c++; next} c==1 && /^name:/ {sub(/^name:[[:space:]]*/,""); print; exit}' "$sm")
    if [ "$fm_name" != "$skill" ]; then
      bad "$name/$skill: SKILL.md frontmatter name='$fm_name' (expected $skill)"; plugin_ok=0
    fi
  done
  [ "$plugin_ok" -eq 1 ] && ok "$name (category=$expected_cat, skills: $skills_csv)"
done

# ---------- Bundled scripts present at expected paths ----------
hdr "Bundled scripts: presence at plugin-root scripts/"

declare -a SCRIPTS=(
  "loc/scripts/check-i18n.py"
  "loc/scripts/find_duplicate_localizations.py"
  "github/scripts/gh-issues.py"
  "dev/scripts/dedupe.py"
  "dev/scripts/sem_annotate.py"
  "logseq/scripts/logseq-cli.py"
  "dependency-model/scripts/depscan.py"
)
for s in "${SCRIPTS[@]}"; do
  if [ -f "$s" ]; then ok "$s exists"; else bad "$s missing"; fi
done

# Shared check-i18n.py must NOT be duplicated back under the loc skill dirs
if ls loc/skills/analyze/scripts/check-i18n.py loc/skills/coverage/scripts/check-i18n.py >/dev/null 2>&1; then
  bad "loc: check-i18n.py still duplicated under a skill dir (should be only loc/scripts/check-i18n.py)"
else
  ok "loc: check-i18n.py is a single shared copy at loc/scripts/"
fi

# ---------- dev worker agents ----------
hdr "dev worker agents"

for agent in dedupe-verify-dead dedupe-verify-dup sem-describe; do
  af="dev/agents/$agent.md"
  if [ ! -f "$af" ]; then bad "dev/agents/$agent.md missing"; continue; fi
  n=$(awk '/^---$/{c++; next} c==1 && /^name:/ {sub(/^name:[[:space:]]*/,""); print; exit}' "$af")
  if [ -z "$n" ]; then bad "dev/agents/$agent.md missing name: in frontmatter"; continue; fi
  ok "dev/agents/$agent.md (name='$n')"
done

for agent in dedupe-verify-dead dedupe-verify-dup sem-describe; do
  if grep -rq "\${CLAUDE_PLUGIN_ROOT}/agents/$agent.md" dev/skills/*/SKILL.md; then
    ok "a dev SKILL.md references $agent via \${CLAUDE_PLUGIN_ROOT}/agents/$agent.md"
  else
    bad "no dev SKILL.md references \${CLAUDE_PLUGIN_ROOT}/agents/$agent.md"
  fi
done

# ---------- Skill bodies: no legacy paths or env vars ----------
hdr "Skill bodies: no legacy paths or env vars"

scan_legacy() {
  local pattern="$1"; local label="$2"; local hits
  hits=$(grep -rn "$pattern" --include='SKILL.md' . 2>/dev/null \
    | grep -viE 'do \*?\*?not\*?\*?|fall back|legacy|after cutover' \
    || true)
  if [ -n "$hits" ]; then
    bad "Active $label references found:"
    echo "$hits" | while IFS= read -r line; do printf '         %s\n' "$line"; done
  else
    ok "No active $label references in any SKILL.md"
  fi
}

scan_legacy '\$SKILL_DIR'              '$SKILL_DIR'
scan_legacy '\$COMMAND_DIR'            '$COMMAND_DIR'
scan_legacy '~/\.claude/scripts'       '~/.claude/scripts/'
scan_legacy '~/\.claude/agents'        '~/.claude/agents/'

# ---------- No stale old-plugin example paths in SKILL bodies ----------
hdr "No stale old-plugin example paths"

OLD_NAMES='analyze-localization-files|validate-localization-coverage|detect-non-localizable|translate-to-language|update-json-localization-file|localization-backfill|plugin-vetter|race-condition-audit|backlog-next|file-github-bug|verify-migrate-doc|visual-regression-triage'
stale=$(grep -rnE "efitz-skills/($OLD_NAMES)/" --include='SKILL.md' . 2>/dev/null || true)
if [ -n "$stale" ]; then
  bad "Stale efitz-skills/<old-plugin>/ example paths in SKILL.md:"
  echo "$stale" | while IFS= read -r line; do printf '         %s\n' "$line"; done
else
  ok "No stale efitz-skills/<old-plugin>/ example paths"
fi

# ---------- Repo cleanup ----------
hdr "Repo cleanup"

if [ ! -d "commands" ]; then ok "repo-root commands/ removed"; else bad "repo-root commands/ still exists"; fi

cmd_dirs=$(find . -path ./.git -prune -o -type d -name commands -print 2>/dev/null | grep -v node_modules || true)
if [ -z "$cmd_dirs" ]; then
  ok "no per-plugin commands/ dirs (all command wrappers dropped)"
else
  bad "stray commands/ dirs found:"; echo "$cmd_dirs" | while IFS= read -r d; do printf '         %s\n' "$d"; done
fi

# ---------- Codex manifests in sync ----------
hdr "Codex manifests (generated from Claude manifests)"

drift_out=$(python3 scripts/gen_codex_manifests.py --check 2>&1)
drift_rc=$?
case $drift_rc in
  0) ok "Codex manifests match a fresh regeneration" ;;
  1) bad "Codex manifests out of sync — run: uv run scripts/gen_codex_manifests.py"
     printf '%s\n' "$drift_out" | while IFS= read -r line; do printf '         %s\n' "$line"; done ;;
  *) bad "Codex manifest generator failed (rc=$drift_rc) — structural problem in the Claude manifests:"
     printf '%s\n' "$drift_out" | while IFS= read -r line; do printf '         %s\n' "$line"; done ;;
esac

# ---------- summary ----------
hdr "Summary"
printf 'PASS: %d\nFAIL: %d\n' "$PASS" "$FAIL"

if [ "$FAIL" -ne 0 ]; then
  echo
  echo "Failures:"
  for f in "${FAILURES[@]}"; do printf '  - %s\n' "$f"; done
  exit 1
fi

echo
echo "All structural checks passed. Safe to run /plugin marketplace add and /plugin install."
exit 0
