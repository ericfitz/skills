"""sem-annotate: generate and refresh SEM@<sha> intent markers on code entities."""
import argparse
import json
import os
import re
import subprocess
import sys

import sem_scope

COMMENT_BY_EXT = {
    ".go": "//", ".ts": "//", ".tsx": "//", ".js": "//", ".jsx": "//",
    ".py": "#",
}

# Matches a SEM marker line: indent, comment prefix, short/full hex sha, description.
SEM_MARKER_RE = re.compile(
    r"^(?P<indent>\s*)(?P<prefix>//|#)\s*SEM@(?P<sha>[0-9a-fA-F]{4,40}):\s?(?P<desc>.*)$"
)


def comment_prefix(path):
    """Return the line-comment prefix for a file path, or None if unsupported."""
    _, ext = os.path.splitext(path)
    return COMMENT_BY_EXT.get(ext.lower())


def parse_markers(text):
    """Return {0-based line index: {'sha', 'desc'}} for every SEM marker line."""
    out = {}
    for i, line in enumerate(text.splitlines()):
        m = SEM_MARKER_RE.match(line)
        if m:
            out[i] = {"sha": m.group("sha"), "desc": m.group("desc")}
    return out


def find_marker_above(lines, start_line):
    """Return the SEM marker dict on the line directly above 1-based start_line, or None."""
    above_idx = start_line - 2  # line above the entity, 0-based
    if above_idx < 0 or above_idx >= len(lines):
        return None
    m = SEM_MARKER_RE.match(lines[above_idx])
    if not m:
        return None
    return {"sha": m.group("sha"), "desc": m.group("desc")}


def build_marker(prefix, indent, sha, desc):
    """Build a SEM marker line with the given prefix, indentation, SHA, and description."""
    return f"{indent}{prefix} SEM@{sha}: {desc}"


def apply_marker(lines, start_line, prefix, sha, desc):
    """Insert or replace the SEM marker directly above 1-based start_line.

    Indentation is copied from the entity definition line. Returns a NEW list.
    """
    lines = list(lines)
    idx = start_line - 1                       # entity line, 0-based
    entity_line = lines[idx] if 0 <= idx < len(lines) else ""
    indent = entity_line[: len(entity_line) - len(entity_line.lstrip())]
    marker = build_marker(prefix, indent, sha, desc)
    above = idx - 1
    if above >= 0 and SEM_MARKER_RE.match(lines[above]):
        lines[above] = marker
    else:
        lines.insert(idx, marker)
    return lines


_ZERO_SHA_RE = re.compile(r"0{7,40}")


def _is_uncommitted(sha):
    """True for a missing/blank/all-zeros blame sha (git's 'Not Committed Yet')."""
    return not sha or _ZERO_SHA_RE.fullmatch(sha) is not None


def classify(existing_sha, anchor_sha, logic_changed):
    """Classify entity status.

    missing      no marker
    uncommitted  marker present but anchor is uncommitted/blank (dirty tree)
    fresh        anchor sha current, or change cosmetic
    stale        anchor moved and a logical change occurred
    """
    if not existing_sha:
        return "missing"
    if _is_uncommitted(anchor_sha):
        return "uncommitted"
    if anchor_sha.startswith(existing_sha):
        return "fresh"
    return "stale" if logic_changed else "fresh"


# ---------------------------------------------------------------------------
# sem CLI wrappers
# ---------------------------------------------------------------------------

CODE_TYPES = {"function", "method", "class", "type"}


class SemError(RuntimeError):
    pass


class InvalidRevError(SemError):
    """A sem command failed because a commit/revspec does not exist."""


def _is_revspec_not_found(stderr):
    s = (stderr or "").lower()
    return "not found" in s and ("revspec" in s or "reference" in s)


def _read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def run_sem(args, cwd=None):
    if not args:
        raise SemError("run_sem called with empty args")
    cmd = ["sem", args[0], "--json", *args[1:]]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SemError("'sem' CLI not found on PATH") from None
    except subprocess.CalledProcessError as e:
        msg = f"sem {' '.join(args)} failed: {e.stderr.strip()}"
        if _is_revspec_not_found(e.stderr):
            raise InvalidRevError(msg) from e
        raise SemError(msg) from e
    return r.stdout


def sem_entities(paths, cwd=None):
    out = run_sem(["entities", *paths], cwd=cwd)
    return json.loads(out)


def sem_blame(file, cwd=None):
    return json.loads(run_sem(["blame", file], cwd=cwd))


_ANCHOR_INVALIDATING_CHANGES = ("modified", "added")


def _parse_changed_entities(data):
    """Names of entities whose anchor can no longer vouch for them, per a sem diff
    --json payload (run with --no-cosmetics, so anything left is a logical change).

    `modified` is the obvious case. `added` means the entity does not exist at the anchor
    at all -- the marker was written before the introducing commit existed (typically
    hand-anchored at HEAD in the same commit that created the entity), so the anchor
    predates the body and a later change is indistinguishable from the original. Treat it
    as changed, never fresh (#39). Deleted/moved/reordered entities keep their marker.
    """
    names = set()
    for ch in data.get("changes", []):
        if ch.get("changeType") in _ANCHOR_INVALIDATING_CHANGES:
            n = ch.get("entityName")
            if n:
                names.add(n)
    return names


def logic_changed_entities(base_sha, file, cwd=None):
    """Names of entities in `file` with a non-cosmetic change since base_sha."""
    out = run_sem(["diff", f"{base_sha}..HEAD", "--no-cosmetics", "--", file], cwd=cwd)
    return _parse_changed_entities(json.loads(out))


_LOGIC_CHANGE_TYPES = ("added", "modified (logic)")


def sem_log_entity(name, file, cwd=None):
    """Parsed `sem log --json <name> --file <file>`; {'changes': []} on any failure."""
    try:
        out = run_sem(["log", name, "--file", file], cwd=cwd)
    except SemError:
        return {"changes": []}
    try:
        data = json.loads(out)
    except (ValueError, json.JSONDecodeError):
        return {"changes": []}
    if not isinstance(data, dict):
        return {"changes": []}
    return data


def entity_logic_sha(name, file, cwd=None, fallback_sha=""):
    """SHA of the entity's newest added/logic change (cosmetic-aware anchor).

    `sem log` changes are oldest-first, so the last matching entry is newest.
    Falls back to fallback_sha (e.g. the entity's sem blame commit) when there
    is no added/logic entry.
    """
    sha = ""
    for ch in sem_log_entity(name, file, cwd=cwd).get("changes", []):
        if ch.get("change_type") in _LOGIC_CHANGE_TYPES:
            s = (ch.get("commit") or {}).get("sha")
            if s:
                sha = s
    return sha or (fallback_sha or "")


def head_sha(cwd=None):
    """git rev-parse HEAD, or '' if unavailable."""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd,
                           capture_output=True, text=True, check=True)
        return r.stdout.strip()
    except Exception:
        return ""


def scan(paths, cwd=None, rebuild=False):
    """Worklist for entities classified missing/stale (or all when rebuild=True).

    paths is None or [] => consult .local/sem-scope.json (include/exclude). Non-empty
    paths are explicit and bypass the scope file entirely.
    """
    if paths:
        scope = None
        scan_paths = list(paths)
    else:
        scope = sem_scope.load_scope(cwd)
        scan_paths = sem_scope.include_paths(scope)
    entities = [e for e in sem_entities(scan_paths, cwd=cwd) if e.get("type") in CODE_TYPES]
    by_file = {}
    for e in entities:
        f = e.get("file") or (scan_paths[0] if len(scan_paths) == 1 else None)
        if f is None:
            continue
        if scope is not None and sem_scope.is_excluded(f, scope):
            continue
        by_file.setdefault(f, []).append(e)

    work = []
    for f, ents in by_file.items():
        read_path = f if cwd is None else os.path.join(cwd, f)
        text = _read_text(read_path)
        lines = text.splitlines()
        blame_by_name = {b["name"]: (b.get("commit") or "")
                         for b in sem_blame(f, cwd=cwd)}
        for e in ents:
            marker = find_marker_above(lines, e["start_line"])
            existing_sha = marker["sha"] if marker else None
            anchor_sha = entity_logic_sha(
                e["name"], f, cwd=cwd,
                fallback_sha=blame_by_name.get(e["name"], "")) or ""
            existing_desc = marker["desc"] if marker else None
            if rebuild:
                status = "missing"
            else:
                logic = False
                if existing_sha and not _is_uncommitted(anchor_sha) \
                        and not anchor_sha.startswith(existing_sha):
                    # Anchors orphaned by squash-merge still diff correctly (sem resolves
                    # the object; Ataraxy-Labs/sem#479), so no reachability gate here --
                    # an unresolvable anchor errors loudly and lands in invalid-sha below.
                    try:
                        logic = e["name"] in logic_changed_entities(existing_sha, f, cwd=cwd)
                    except SemError:
                        work.append({
                            "file": f, "name": e["name"],
                            "start_line": e["start_line"], "end_line": e["end_line"],
                            "status": "invalid-sha", "anchor_sha": anchor_sha,
                            "existing_desc": existing_desc, "bad_sha": existing_sha,
                        })
                        continue
                status = classify(existing_sha, anchor_sha, logic)
            if status in ("missing", "stale"):
                work.append({
                    "file": f, "name": e["name"],
                    "start_line": e["start_line"], "end_line": e["end_line"],
                    "status": status, "anchor_sha": anchor_sha,
                    "existing_desc": existing_desc,
                })
    return work


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

def write(descriptions, worklist, cwd=None):
    """Apply markers, stamping the authoritative anchor_sha from the worklist.

    descriptions: list of {"file","name","start_line","desc"} (LLM output, no sha).
    worklist:     list of {"file","name","start_line","anchor_sha", ...} (scan output).
    The sha is taken from the worklist (NEVER the LLM); a blank anchor falls back to
    the current HEAD sha. Returns {"files_written","markers","skipped"}.
    """
    anchors = {(w["file"], w["name"], w["start_line"]): (w.get("anchor_sha") or "")
               for w in worklist}
    by_file = {}
    skipped = 0
    for d in descriptions:
        key = (d["file"], d["name"], d["start_line"])
        if key not in anchors:
            skipped += 1
            continue
        if comment_prefix(d["file"]) is None:
            skipped += 1
            continue
        sha = anchors[key] or head_sha(cwd)
        by_file.setdefault(d["file"], []).append(
            {"start_line": d["start_line"], "sha": sha, "desc": d["desc"]})
    written = 0
    markers = 0
    for f, ups in by_file.items():
        abspath = f if cwd is None else os.path.join(cwd, f)
        prefix = comment_prefix(f)
        if prefix is None:
            continue
        lines = _read_text(abspath).splitlines()
        for u in sorted(ups, key=lambda x: x["start_line"], reverse=True):
            lines = apply_marker(lines, u["start_line"], prefix, u["sha"], u["desc"])
        with open(abspath, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        written += 1
        markers += len(ups)
    return {"files_written": written, "markers": markers, "skipped": skipped}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv):
    p = argparse.ArgumentParser(prog="sem_annotate")
    p.add_argument("--update", nargs="+", metavar="FILE",
                   help="scan only these files (entity-granular update)")
    p.add_argument("-C", "--cwd", default=None,
                   help="working directory forwarded to sem CLI")
    p.add_argument("--rebuild", action="store_true",
                   help="regenerate all markers, ignoring existing ones")
    sub = p.add_subparsers(dest="cmd")
    s = sub.add_parser("scan")
    s.add_argument("paths", nargs="*", default=None)
    s.add_argument("--rebuild", action="store_true")
    s.add_argument("-C", "--cwd", default=None)
    w = sub.add_parser("write")
    w.add_argument("--worklist", required=True)
    w.add_argument("-C", "--cwd", default=None)
    dbp = sub.add_parser("db")
    dbp.add_argument("db_action", choices=["build", "update", "status"])
    dbp.add_argument("paths", nargs="*", default=None)
    dbp.add_argument("-C", "--cwd", default=None)
    ns = p.parse_args(argv)
    if ns.update:
        ns.cmd = "scan"
        ns.paths = ns.update
        ns.rebuild = getattr(ns, "rebuild", False)
        ns.cwd = getattr(ns, "cwd", None)
    return ns


def main(argv=None):
    ns = parse_args(argv if argv is not None else sys.argv[1:])
    if ns.cmd == "scan":
        print(json.dumps(scan(ns.paths, cwd=ns.cwd, rebuild=ns.rebuild), indent=2))
        return 0
    if ns.cmd == "write":
        descriptions = json.load(sys.stdin)
        with open(ns.worklist, encoding="utf-8") as wf:
            worklist = json.load(wf)
        res = write(descriptions, worklist, cwd=ns.cwd)
        print(json.dumps(res))
        return 0
    if ns.cmd == "db":
        import sem_db
        action = ns.db_action
        paths = ns.paths or None
        if action == "build":
            res = sem_db.build(cwd=ns.cwd, paths=paths)
        elif action == "update":
            res = sem_db.update(cwd=ns.cwd, files=paths) if paths \
                else sem_db.auto_update(cwd=ns.cwd)
        else:  # status
            res = sem_db.status(cwd=ns.cwd)
        print(json.dumps(res))
        return 0
    print("usage: sem_annotate [scan|write|db|--update FILES]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
