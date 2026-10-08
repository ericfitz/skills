#!/bin/bash
# repo-state.sh: collect facts about the git repo containing the current directory.
# Never changes anything. Used by the /session:continue and /session:handoff skills.
# Part of the session plugin.
#
# Exit 0 whenever a report was produced; exit 2 when not inside a git repo.
# Each external call is guarded so one failing check does not stop the report.
# .local/state-checks.sh is looked up in the worktree root first, then in the main
# checkout (.local/ is untracked, so a linked worktree does not have it).
# REPO_STATE_TIMEOUT (default 30s) bounds gh calls and .local/state-checks.sh.
# Bash 3.2 compatible (macOS /bin/bash). Run with --self-test to check.

set -uo pipefail

TIMEOUT="${REPO_STATE_TIMEOUT:-30}"
ROOT=""
MAIN_ROOT=""   # the main checkout; differs from ROOT inside a linked worktree
DEFAULT=""
GH_STATUS=""   # empty when gh is usable, otherwise the reason it is not
PRS_JSON="[]"

# with_timeout <seconds> <cmd...>: no GNU timeout on macOS; perl's alarm survives exec,
# so the command dies with SIGALRM (status 142) when the time is up.
with_timeout() {
  perl -e 'alarm shift; exec @ARGV' "$@"
}

# join_by <sep> <items...>
join_by() {
  local sep=$1 out="" x
  shift
  for x in "$@"; do out+="${out:+$sep}$x"; done
  printf '%s' "$out"
}

default_branch() {
  local d
  if d=$(git symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null); then
    echo "${d#origin/}"
  elif git show-ref -q --verify refs/heads/main; then
    echo main
  elif git show-ref -q --verify refs/heads/master; then
    echo master
  else
    git symbolic-ref --short -q HEAD 2>/dev/null || echo main
  fi
}

gather_github() {
  command -v gh >/dev/null 2>&1 || { GH_STATUS="gh not installed"; return 0; }
  git remote get-url origin >/dev/null 2>&1 || { GH_STATUS="no origin remote"; return 0; }
  with_timeout "$TIMEOUT" gh auth status >/dev/null 2>&1 || { GH_STATUS="gh not authenticated or no network"; return 0; }
  PRS_JSON=$(with_timeout "$TIMEOUT" gh pr list --author @me --state open \
    --json number,headRefName,title,statusCheckRollup 2>/dev/null) || { GH_STATUS="gh pr list failed"; PRS_JSON="[]"; }
}

# pr_for_branch <branch>: "PR #N" or "no PR" (gh data already gathered)
pr_for_branch() {
  printf '%s' "$PRS_JSON" | python3 -c '
import json, sys
b = sys.argv[1]
for pr in json.load(sys.stdin):
    if pr.get("headRefName") == b:
        print("PR #%s" % pr["number"]); break
else:
    print("no PR")' "$1" 2>/dev/null || echo "no PR"
}

git_section() {
  local branch head upstream counts ahead behind dirty n list line path items b cnt
  echo "== git"
  branch=$(git symbolic-ref --short -q HEAD 2>/dev/null) || branch="(detached)"
  echo "BRANCH: $branch"
  head=$(git log -1 --format='%h (%s)' 2>/dev/null) || head="none"
  echo "HEAD: $head"
  if upstream=$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null); then
    counts=$(git rev-list --left-right --count "$upstream...HEAD" 2>/dev/null) || counts="? ?"
    behind=${counts%%[[:space:]]*}
    ahead=${counts##*[[:space:]]}
    echo "UPSTREAM: $upstream  ahead $ahead  behind $behind"
  else
    echo "UPSTREAM: none"
  fi
  dirty=$(git status --porcelain 2>/dev/null) || dirty=""
  if [[ -z $dirty ]]; then
    echo "DIRTY: clean"
  else
    n=$(printf '%s\n' "$dirty" | wc -l | tr -d ' ')
    list=$(printf '%s\n' "$dirty" | head -10 | sed -E 's/^ +//; s/  +/ /' | paste -sd '|' - | sed 's/|/, /g')
    echo "DIRTY: $n files ($list)"
  fi
  items=()
  path=""
  while IFS= read -r line; do
    case "$line" in
      "worktree "*) path=${line#worktree } ;;
      "branch refs/heads/"*) items+=("$path [${line#branch refs/heads/}]") ;;
      detached) items+=("$path [detached]") ;;
    esac
  done < <(git worktree list --porcelain 2>/dev/null)
  echo "WORKTREES: $(join_by '; ' ${items[@]+"${items[@]}"})"
  items=()
  while IFS= read -r b; do
    [[ -z $b || $b == "$DEFAULT" ]] && continue
    cnt=$(git rev-list --count "$DEFAULT..$b" 2>/dev/null) || cnt=0
    if ((cnt > 0)); then
      if [[ -z $GH_STATUS ]]; then
        items+=("$b ($cnt ahead of $DEFAULT, $(pr_for_branch "$b"))")
      else
        items+=("$b ($cnt ahead of $DEFAULT)")
      fi
    fi
  done < <(git for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null)
  if ((${#items[@]} == 0)); then
    echo "UNMERGED BRANCHES: none"
  else
    echo "UNMERGED BRANCHES: $(join_by '; ' "${items[@]}")"
  fi
}

github_section() {
  local run
  echo "== github"
  if [[ -n $GH_STATUS ]]; then
    echo "GITHUB: unavailable ($GH_STATUS)"
    return 0
  fi
  printf '%s' "$PRS_JSON" | python3 -c '
import json, sys
prs = json.load(sys.stdin)
if not prs:
    print("OPEN PRS (mine): none")
FAIL = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}
WAIT = {"", "PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "WAITING", "REQUESTED"}
for pr in prs:
    states = [(c.get("conclusion") or c.get("state") or c.get("status") or "").upper()
              for c in (pr.get("statusCheckRollup") or [])]
    if not states:
        checks = "none"
    elif any(s in FAIL for s in states):
        checks = "fail"
    elif any(s in WAIT for s in states):
        checks = "pending"
    else:
        checks = "pass"
    print("OPEN PRS (mine): #%s %s \"%s\" checks=%s" % (pr["number"], pr["headRefName"], pr["title"], checks))' 2>/dev/null \
    || echo "OPEN PRS (mine): unavailable (could not parse gh output)"
  # Judge the runs on the default branch's head commit, latest run per workflow.
  # (gh run list --branch X --limit 1 can return a stale run, not the newest one.)
  # Event "dynamic" runs (GitHub's Dependabot security updates) are not the repo's CI:
  # their failures are listed after the verdict instead of deciding it.
  sha=$(git rev-parse -q --verify "origin/$DEFAULT^{commit}" 2>/dev/null) \
    || sha=$(git rev-parse -q --verify "$DEFAULT^{commit}" 2>/dev/null) || {
    echo "MAIN CI: unavailable (no $DEFAULT commit)"
    return 0
  }
  run=$(with_timeout "$TIMEOUT" gh run list --commit "$sha" --limit 100 \
    --json status,conclusion,workflowName,createdAt,event 2>/dev/null) || {
    echo "MAIN CI: unavailable (gh run list failed)"
    return 0
  }
  printf '%s' "$run" | python3 -c '
import json, sys
sha = sys.argv[1][:7]
latest, dynamic = {}, {}
for r in json.load(sys.stdin):
    w = r.get("workflowName") or "?"
    d = dynamic if r.get("event") == "dynamic" else latest
    if w not in d or r.get("createdAt", "") > d[w].get("createdAt", ""):
        d[w] = r
OK = {"success", "skipped", "neutral"}
BAD = {"failure", "cancelled", "timed_out", "action_required", "startup_failure", "stale"}

def judge(runs):
    failed, pending = [], []
    for w in sorted(runs):
        r = runs[w]
        c = r.get("conclusion") or ""
        if r.get("status") != "completed":
            pending.append(w)
        elif c in BAD:
            failed.append(w)
        elif c not in OK:  # unrecognized conclusion: never report it as green
            failed.append("%s: %s" % (w, c or "no conclusion"))
    return failed, pending

failed, pending = judge(latest)
if not latest:
    line = "MAIN CI: none (no runs on %s)" % sha
elif failed:
    line = "MAIN CI: failure (%s on %s)" % (", ".join(failed), sha)
elif pending:
    line = "MAIN CI: pending (%s on %s)" % (", ".join(pending), sha)
else:
    n = len(latest)
    line = "MAIN CI: success (%d workflow%s on %s)" % (n, "" if n == 1 else "s", sha)
dyn_failed = judge(dynamic)[0]
if dyn_failed:
    line += "; dynamic failing: " + ", ".join(dyn_failed)
print(line)' "$sha" 2>/dev/null \
    || echo "MAIN CI: unavailable"
}

state_section() {
  local script="$ROOT/.local/state-checks.sh" out start elapsed rc
  echo "== state-checks"
  if [[ ! -f $script && -n $MAIN_ROOT && $MAIN_ROOT != "$ROOT" ]]; then
    script="$MAIN_ROOT/.local/state-checks.sh"
  fi
  if [[ ! -f $script ]]; then
    echo "STATE-CHECKS: not configured"
    return 0
  fi
  out=$(mktemp) || { echo "STATE-CHECKS: FAILED (mktemp)"; return 0; }
  start=$(date +%s)
  # Output goes to a file, not a pipe: a timed-out child left behind would otherwise
  # hold the pipe open and stall this report.
  (cd "$ROOT" && with_timeout "$TIMEOUT" bash "$script" >"$out" 2>&1 </dev/null)
  rc=$?
  elapsed=$(($(date +%s) - start))
  [[ -s $out ]] && cat "$out"
  rm -f "$out"
  if ((rc == 0)); then
    echo "STATE-CHECKS: exit 0 (${elapsed}s)"
  elif ((rc == 142)); then
    echo "STATE-CHECKS: TIMEOUT"
  else
    echo "STATE-CHECKS: FAILED (exit $rc)"
  fi
}

main() {
  local common
  ROOT=$(git rev-parse --show-toplevel 2>/dev/null) || {
    echo "repo-state: not inside a git repository" >&2
    exit 2
  }
  cd "$ROOT" || exit 2
  common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || common=""
  case "$common" in
    */.git) MAIN_ROOT=${common%/.git} ;;
    *) MAIN_ROOT="" ;;
  esac
  DEFAULT=$(default_branch)
  gather_github
  git_section
  github_section
  state_section
  exit 0
}

selftest() {
  local self tmp bin out rc fails=0
  case "$0" in /*) self=$0 ;; *) self=$PWD/$0 ;; esac
  tmp=$(cd "$(mktemp -d)" && pwd -P) || exit 1
  bin="$tmp/bin"
  mkdir -p "$bin"
  ln -s "$(command -v git)" "$bin/git"
  # gh is deliberately absent from PATH; only git, perl, python3 and coreutils remain
  export PATH="$bin:/usr/bin:/bin" GIT_CONFIG_GLOBAL=/dev/null REPO_STATE_TIMEOUT=1

  gitc() { git -c user.name=t -c user.email=t@t -c commit.gpgsign=false "$@"; }
  check() { # check <label> <expected substring> <text>
    if ! grep -qF -- "$2" <<<"$3"; then
      echo "FAIL: $1: missing '$2'"
      printf '    %s\n' "$3"
      fails=1
    fi
  }

  git init -q --bare -b main "$tmp/origin.git"
  git init -q -b main "$tmp/work"
  cd "$tmp/work" || exit 1
  echo a >a.txt && gitc add a.txt && gitc commit -q -m init
  git remote add origin "$tmp/origin.git" && git push -q -u origin main
  git remote set-head origin -a >/dev/null 2>&1

  out=$(bash "$self"); rc=$?
  [[ $rc == 0 ]] || { echo "FAIL: clean rc=$rc"; fails=1; }
  check clean "BRANCH: main" "$out"
  check clean "UPSTREAM: origin/main  ahead 0  behind 0" "$out"
  check clean "DIRTY: clean" "$out"
  check clean "WORKTREES: $tmp/work [main]" "$out"
  check clean "UNMERGED BRANCHES: none" "$out"
  check clean "GITHUB: unavailable (gh not installed)" "$out"
  check clean "STATE-CHECKS: not configured" "$out"

  echo n >notes.txt
  out=$(bash "$self"); check dirty "DIRTY: 1 files (?? notes.txt)" "$out"
  rm notes.txt

  mkdir sub
  out=$(cd sub && bash "$self"); check subdir "BRANCH: main" "$out"
  rmdir sub

  echo b >a.txt && gitc commit -q -am second
  out=$(bash "$self"); check ahead "ahead 1  behind 0" "$out"

  git worktree add -q "$tmp/wt" -b feat/x
  (cd "$tmp/wt" && echo c >c.txt && gitc add c.txt && gitc commit -q -m c)
  out=$(bash "$self")
  check worktree "$tmp/wt [feat/x]" "$out"
  check unmerged "UNMERGED BRANCHES: feat/x (1 ahead of main)" "$out"

  mkdir -p .local
  printf '#!/bin/bash\necho "DEPLOYED api: 1.2.3"\n' >.local/state-checks.sh
  out=$(bash "$self"); check state-ok "DEPLOYED api: 1.2.3" "$out"; check state-ok "STATE-CHECKS: exit 0 (" "$out"
  printf '#!/bin/bash\necho partial\nexit 3\n' >.local/state-checks.sh
  out=$(bash "$self"); check state-fail "partial" "$out"; check state-fail "STATE-CHECKS: FAILED (exit 3)" "$out"
  printf '#!/bin/bash\necho before\nsleep 5\necho after\n' >.local/state-checks.sh
  out=$(bash "$self"); check state-hang "before" "$out"; check state-hang "STATE-CHECKS: TIMEOUT" "$out"
  grep -qF "after" <<<"$out" && { echo "FAIL: state-hang: script was not killed"; fails=1; }

  # linked worktree: state-checks.sh comes from the main checkout, which has .local/
  printf '#!/bin/bash\necho "DEPLOYED api: 1.2.3"\n' >.local/state-checks.sh
  out=$(cd "$tmp/wt" && bash "$self"); rc=$?
  [[ $rc == 0 ]] || { echo "FAIL: worktree rc=$rc"; fails=1; }
  check wt-state "DEPLOYED api: 1.2.3" "$out"; check wt-state "STATE-CHECKS: exit 0 (" "$out"
  check wt-branch "BRANCH: feat/x" "$out"
  # the worktree's own copy wins over the main checkout's
  mkdir -p "$tmp/wt/.local"
  printf '#!/bin/bash\necho "DEPLOYED local: wt"\n' >"$tmp/wt/.local/state-checks.sh"
  out=$(cd "$tmp/wt" && bash "$self"); check wt-own "DEPLOYED local: wt" "$out"
  grep -qF "1.2.3" <<<"$out" && { echo "FAIL: wt-own: used main checkout script"; fails=1; }
  rm -rf "$tmp/wt/.local"
  # worktree and main checkout both without a script
  rm .local/state-checks.sh
  out=$(cd "$tmp/wt" && bash "$self"); check wt-none "STATE-CHECKS: not configured" "$out"

  # stubbed gh: success path and failure paths
  mkdir "$tmp/ghbin"
  cat >"$tmp/ghbin/gh" <<'GH'
#!/bin/bash
case "$1 $2" in
  "auth status") exit 0 ;;
  "pr list") echo '[{"number":7,"headRefName":"feat/x","title":"T","statusCheckRollup":[{"conclusion":"FAILURE"}]}]' ;;
  "run list")
    [[ -n ${GH_STUB_RUN_FAIL:-} ]] && exit 1
    # like the real API, a bare --branch --limit 1 query returns a stale run
    [[ " $* " == *" --commit "* ]] || { echo '[{"status":"completed","conclusion":"failure","databaseId":1,"createdAt":"2020-01-01T00:00:00Z","workflowName":"Old"}]'; exit 0; }
    echo "$*" >"$GH_STUB_ARGS"
    W='"status":"completed","workflowName"'
    case ${GH_STUB_RUNS:-ok} in
      # CI failed first, then a re-run passed: the latest run per workflow wins
      ok) echo "[{$W:\"CI\",\"conclusion\":\"success\",\"createdAt\":\"2026-10-05T02:00:00Z\"},{$W:\"CI\",\"conclusion\":\"failure\",\"createdAt\":\"2026-10-05T01:00:00Z\"},{$W:\"Lint\",\"conclusion\":\"skipped\",\"createdAt\":\"2026-10-05T01:00:00Z\"}]" ;;
      fail) echo "[{$W:\"CI\",\"conclusion\":\"failure\",\"createdAt\":\"2026-10-05T02:00:00Z\"},{$W:\"Lint\",\"conclusion\":\"success\",\"createdAt\":\"2026-10-05T01:00:00Z\"}]" ;;
      pending) echo '[{"status":"in_progress","conclusion":"","workflowName":"CI","createdAt":"2026-10-05T02:00:00Z"}]' ;;
      odd) echo "[{$W:\"CI\",\"conclusion\":\"bogus\",\"createdAt\":\"2026-10-05T02:00:00Z\"}]" ;;
      empty) echo '[]' ;;
      # GitHub's Dependabot security-update job (event dynamic) is not the repo's CI
      dyn) echo "[{$W:\"CI\",\"conclusion\":\"success\",\"event\":\"push\",\"createdAt\":\"2026-10-05T02:00:00Z\"},{$W:\"Dependabot Updates\",\"conclusion\":\"failure\",\"event\":\"dynamic\",\"createdAt\":\"2026-10-05T03:00:00Z\"}]" ;;
    esac ;;
  *) exit 1 ;;
esac
GH
  chmod +x "$tmp/ghbin/gh"
  export GH_STUB_ARGS="$tmp/gh-args"
  head7=$(git rev-parse --short=7 origin/main)
  out=$(PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-pr 'OPEN PRS (mine): #7 feat/x "T" checks=fail' "$out"
  check gh-ci "MAIN CI: success (2 workflows on $head7)" "$out"
  check gh-ci-commit "--commit $(git rev-parse origin/main)" "$(cat "$GH_STUB_ARGS")"
  check gh-unmerged "feat/x (1 ahead of main, PR #7)" "$out"
  out=$(GH_STUB_RUNS=fail PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-red "MAIN CI: failure (CI on $head7)" "$out"
  out=$(GH_STUB_RUNS=pending PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-pending "MAIN CI: pending (CI on $head7)" "$out"
  out=$(GH_STUB_RUNS=odd PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-unknown "MAIN CI: failure (CI: bogus on $head7)" "$out"
  out=$(GH_STUB_RUNS=empty PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-none "MAIN CI: none (no runs on $head7)" "$out"
  out=$(GH_STUB_RUNS=dyn PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-dynamic "MAIN CI: success (1 workflow on $head7); dynamic failing: Dependabot Updates" "$out"
  out=$(GH_STUB_RUN_FAIL=1 PATH="$tmp/ghbin:$PATH" bash "$self")
  check gh-ci-fail "MAIN CI: unavailable" "$out"
  check gh-ci-fail "OPEN PRS (mine): #7" "$out"
  # shellcheck disable=SC2016  # the stub script must keep $1 $2 literal
  printf '#!/bin/bash\ncase "$1 $2" in "auth status") exit 0 ;; "pr list") echo garbage ;; *) exit 1 ;; esac\n' >"$tmp/ghbin/gh"
  out=$(PATH="$tmp/ghbin:$PATH" bash "$self"); rc=$?
  [[ $rc == 0 ]] || { echo "FAIL: gh-garbage rc=$rc"; fails=1; }
  check gh-garbage "OPEN PRS (mine): unavailable" "$out"
  check gh-garbage "== state-checks" "$out"

  git init -q -b main "$tmp/solo"
  (cd "$tmp/solo" && echo a >a && gitc add a && gitc commit -q -m i)
  out=$(cd "$tmp/solo" && bash "$self"); check no-upstream "UPSTREAM: none" "$out"

  mkdir "$tmp/plain"
  out=$(cd "$tmp/plain" && bash "$self" 2>/dev/null); rc=$?
  [[ $rc == 2 ]] || { echo "FAIL: not-a-repo rc=$rc"; fails=1; }

  cd / && rm -rf "$tmp"
  ((fails == 0)) && echo ok
  exit $fails
}

if [[ ${1:-} == --self-test ]]; then
  selftest
fi
main
