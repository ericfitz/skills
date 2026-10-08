#!/bin/bash
# SessionStart hook: when the repo at the session's cwd has a HANDOFF.md, tell Claude to
# run /session:continue. Prints only for source startup|resume (the hooks.json matcher also
# filters, but the hook does not rely on it). Always exits 0. Run with --self-test to check.

HINT="HANDOFF.md exists in this repo. Before other work, invoke the /session:continue skill (the repo may have changed since the handoff was written), unless the user's first message gives a different instruction."

# field <json> <key>: print the string value of a top-level key, or nothing
field() {
  printf '%s' "$1" | python3 -c '
import json, sys
try:
    v = json.load(sys.stdin).get(sys.argv[1])
except Exception:
    v = None
print(v if isinstance(v, str) else "")' "$2" 2>/dev/null || true
}

# hint <json>: print the hint when it applies
hint() {
  local input=$1 source cwd root common
  source=$(field "$input" source)
  case "$source" in
    startup | resume) ;;
    *) return 0 ;;
  esac
  cwd=$(field "$input" cwd)
  [[ -n $cwd && -d $cwd ]] || cwd=$PWD
  root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || return 0
  if [[ ! -f $root/HANDOFF.md ]]; then
    # linked worktree: fall back to the main checkout (parent of the common git dir)
    common=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || return 0
    [[ $common == /* ]] || common=$cwd/$common
    root=$(dirname "$common")
  fi
  [[ -f $root/HANDOFF.md ]] && printf '%s\n' "$HINT"
  return 0
}

selftest() {
  local self tmp src dir out rc want got fails=0
  case "$0" in /*) self=$0 ;; *) self=$PWD/$0 ;; esac
  tmp=$(mktemp -d) || exit 1
  export GIT_CONFIG_GLOBAL=/dev/null
  mkdir -p "$tmp/with/sub" "$tmp/without" "$tmp/plain"
  git -C "$tmp/with" init -q -b main
  git -C "$tmp/without" init -q -b main
  echo "# HANDOFF" >"$tmp/with/HANDOFF.md"
  for src in startup resume clear compact fork; do
    for dir in with without plain; do
      out=$(printf '{"hook_event_name":"SessionStart","source":"%s","cwd":"%s"}' "$src" "$tmp/$dir" | bash "$self")
      rc=$?
      if [[ $dir == with && ($src == startup || $src == resume) ]]; then want=1; else want=0; fi
      if [[ -n $out ]]; then got=1; else got=0; fi
      if [[ $want != "$got" || $rc != 0 ]]; then
        echo "FAIL: source=$src dir=$dir printed=$got rc=$rc"
        fails=1
      fi
    done
  done
  out=$(printf '{"source":"startup","cwd":"%s"}' "$tmp/with/sub" | bash "$self")
  [[ $out == "$HINT" ]] || { echo "FAIL: subdirectory (got: $out)"; fails=1; }
  for dir in with without; do
    git -C "$tmp/$dir" -c user.name=t -c user.email=t@t commit -q --allow-empty -m init
    git -C "$tmp/$dir" worktree add -q "$tmp/wt-$dir" -b "wt-$dir"
  done
  git -C "$tmp/without" worktree add -q "$tmp/wt-own" -b wt-own
  echo "# HANDOFF" >"$tmp/wt-own/HANDOFF.md"
  out=$(printf '{"source":"startup","cwd":"%s"}' "$tmp/wt-with" | bash "$self")
  [[ $out == "$HINT" ]] || { echo "FAIL: worktree, main checkout has HANDOFF (got: $out)"; fails=1; }
  out=$(printf '{"source":"startup","cwd":"%s"}' "$tmp/wt-without" | bash "$self")
  [[ -z $out ]] || { echo "FAIL: worktree, no HANDOFF anywhere (got: $out)"; fails=1; }
  out=$(printf '{"source":"startup","cwd":"%s"}' "$tmp/wt-own" | bash "$self")
  [[ $out == "$HINT" ]] || { echo "FAIL: worktree with its own HANDOFF (got: $out)"; fails=1; }
  out=$(printf 'not json' | bash "$self"); rc=$?
  [[ $rc == 0 && -z $out ]] || { echo "FAIL: garbage input rc=$rc out=$out"; fails=1; }
  out=$(printf '' | bash "$self"); rc=$?
  [[ $rc == 0 && -z $out ]] || { echo "FAIL: empty input rc=$rc out=$out"; fails=1; }
  out=$(printf '{"source":"startup","cwd":"/nonexistent/dir"}' | (cd "$tmp/plain" && bash "$self")); rc=$?
  [[ $rc == 0 && -z $out ]] || { echo "FAIL: bad cwd falls back to PWD rc=$rc out=$out"; fails=1; }
  rm -rf "$tmp"
  ((fails == 0)) && echo ok
  exit $fails
}

if [[ ${1:-} == --self-test ]]; then
  selftest
fi
hint "$(cat 2>/dev/null)"
exit 0
