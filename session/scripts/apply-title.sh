#!/bin/bash
# UserPromptSubmit hook: when /go left a pending session title for this session, emit it
# as hookSpecificOutput.sessionTitle and delete the file. Does nothing when the user has
# already named the session (non-empty session_title), when session_id is unsafe, or on
# any error. Always exits 0. Run with --self-test to check.

# apply <json>: print the hook output JSON when a title applies
apply() {
  local state=${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin
  # Nothing pending: skip starting python3 (builtins only, so it works without any tools)
  local -a pending
  shopt -s nullglob dotglob
  pending=("$state"/titles/*)
  shopt -u nullglob dotglob
  ((${#pending[@]} > 0)) || return 0
  printf '%s' "$1" | python3 -c '
import json, os, re, sys, time, unicodedata

try:
    data = json.load(sys.stdin)
    if not isinstance(data, dict):
        sys.exit(0)
    sid = data.get("session_id")
    if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
        sys.exit(0)
    titles = os.path.join(sys.argv[1], "titles")
    cutoff = time.time() - 7 * 86400
    try:
        for name in os.listdir(titles):
            path = os.path.join(titles, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                    os.remove(path)
            except OSError:
                pass
    except OSError:
        pass
    path = os.path.join(titles, sid)
    existing = data.get("session_title")
    if isinstance(existing, str) and existing:
        try:
            os.remove(path)
        except OSError:
            pass
        sys.exit(0)
    if not os.path.isfile(path):
        sys.exit(0)
    with open(path, encoding="utf-8", errors="replace") as f:
        line = f.readline(1024)
    try:
        os.remove(path)
    except OSError:
        pass
    bad = ("Cc", "Cf", "Zl", "Zp")
    title = "".join(c for c in line if unicodedata.category(c) not in bad).strip()[:80]
    if title:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "sessionTitle": title}}))
except BaseException:
    pass' "$state" 2>/dev/null || true
}

selftest() {
  local self tmp state out rc fails=0
  case "$0" in /*) self=$0 ;; *) self=$PWD/$0 ;; esac
  tmp=$(mktemp -d) || exit 1
  export XDG_STATE_HOME=$tmp
  state=$tmp/session-plugin/titles
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$state"

  # run <json>: set out and rc from the hook
  run() { out=$(printf '%s' "$1" | bash "$self"); rc=$?; }
  fail() { echo "FAIL: $1"; fails=1; }
  # title_of <out>: print the sessionTitle in the hook output, or "<invalid>"
  title_of() {
    printf '%s' "$1" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    h = d["hookSpecificOutput"]
    assert d == {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "sessionTitle": h["sessionTitle"]}}
    assert h["hookEventName"] == "UserPromptSubmit"
    print(h["sessionTitle"], end="")
except Exception:
    print("<invalid>", end="")'
  }

  printf '#42 fix pagination\n' >"$state/abc-123"
  run '{"session_id":"abc-123","hook_event_name":"UserPromptSubmit"}'
  [[ $rc == 0 && $(title_of "$out") == "#42 fix pagination" && ! -e $state/abc-123 ]] || fail "(a) happy path rc=$rc out=$out"

  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && -z $out ]] || fail "(b) no file rc=$rc out=$out"

  printf 'Pending\n' >"$state/abc-123"
  run '{"session_id":"abc-123","session_title":"Mine"}'
  [[ $rc == 0 && -z $out && ! -e $state/abc-123 ]] || fail "(c) custom title rc=$rc out=$out"

  printf 'planted\n' >"$tmp/session-plugin/x"
  run '{"session_id":"../x"}'
  [[ $rc == 0 && -z $out && -e $tmp/session-plugin/x ]] || fail "(d) unsafe id rc=$rc out=$out"

  printf 'a\tb\033c\nsecond line\n' >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && $(title_of "$out") == abc ]] || fail "(e) control chars rc=$rc out=$out"

  printf '%0100d\n' 0 >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && $(title_of "$out" | wc -c | tr -d ' ') == 80 ]] || fail "(f) long title rc=$rc out=$out"

  printf 'fix "quoted" \\ path\n' >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && $(title_of "$out") == 'fix "quoted" \ path' ]] || fail "(g) quotes rc=$rc out=$out"

  : >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && -z $out && ! -e $state/abc-123 ]] || fail "(h) empty file rc=$rc out=$out"

  printf 'old\n' >"$state/old-one"
  printf 'recent\n' >"$state/recent-one"
  python3 -c '
import os, sys, time
now = time.time()
os.utime(sys.argv[1] + "/old-one", (now - 8 * 86400,) * 2)
os.utime(sys.argv[1] + "/recent-one", (now - 86400,) * 2)' "$state"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && ! -e $state/old-one && -e $state/recent-one ]] || fail "(i) pruning rc=$rc"

  run 'not json'
  [[ $rc == 0 && -z $out ]] || fail "(j) bad input rc=$rc out=$out"
  run ''
  [[ $rc == 0 && -z $out ]] || fail "(j) empty input rc=$rc out=$out"

  out=$(printf '{"session_id":"abc-123"}' | XDG_STATE_HOME=/nonexistent/x bash "$self"); rc=$?
  [[ $rc == 0 && -z $out ]] || fail "(k) missing state dir rc=$rc out=$out"

  printf 'pending\n' >"$state/abc-123"
  mkdir "$tmp/bin"
  ln -s "$(command -v bash)" "$tmp/bin/bash"
  ln -s "$(command -v cat)" "$tmp/bin/cat"
  out=$(printf '{"session_id":"abc-123"}' | PATH=$tmp/bin "$tmp/bin/bash" "$self"); rc=$?
  [[ $rc == 0 && -z $out ]] || fail "(l) no python3 rc=$rc out=$out"

  printf 'a\xe2\x80\xa8b\n' >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && $(title_of "$out") == ab ]] || fail "(m) U+2028 rc=$rc out=$out"

  printf 'a\xe2\x80\x8bb\xe2\x80\xaec\n' >"$state/abc-123"
  run '{"session_id":"abc-123"}'
  [[ $rc == 0 && $(title_of "$out") == abc ]] || fail "(n) Cf chars rc=$rc out=$out"

  printf 'pending\n' >"$state/abc-123"
  run '[]'
  [[ $rc == 0 && -z $out ]] || fail "(o) json array rc=$rc out=$out"
  run '{"session_id":123}'
  [[ $rc == 0 && -z $out ]] || fail "(p) integer session_id rc=$rc out=$out"
  mkdir "$state/dir-id"
  run '{"session_id":"dir-id"}'
  [[ $rc == 0 && -z $out ]] || fail "(q) directory at title path rc=$rc out=$out"

  ((fails == 0)) && echo ok
  exit $fails
}

if [[ ${1:-} == --self-test ]]; then
  selftest
fi
apply "$(cat 2>/dev/null)"
exit 0
