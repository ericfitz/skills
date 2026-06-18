"""sem-annotate: generate and refresh SEM@<sha> intent markers on code entities."""
import json
import os
import re
import subprocess

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


def classify(existing_sha, blame_commit, logic_changed):
    """Classify entity status: missing (no marker) / fresh (sha current or change cosmetic) / stale (logic changed).

    SHA comparison is prefix-based: blame_commit.startswith(existing_sha).
    """
    if not existing_sha:
        return "missing"
    if blame_commit.startswith(existing_sha):
        return "fresh"
    return "stale" if logic_changed else "fresh"


# ---------------------------------------------------------------------------
# sem CLI wrappers
# ---------------------------------------------------------------------------

CODE_TYPES = {"function", "method", "class", "type"}


class SemError(RuntimeError):
    pass


def _read_text(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def run_sem(args, cwd=None):
    cmd = ["sem"] + args + ["--json"]
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    except FileNotFoundError:
        raise SemError("'sem' CLI not found on PATH")
    except subprocess.CalledProcessError as e:
        raise SemError(f"sem {' '.join(args)} failed: {e.stderr.strip()}")
    return r.stdout


def sem_entities(paths, cwd=None):
    out = run_sem(["entities", *paths], cwd=cwd)
    return json.loads(out)


def sem_blame(file, cwd=None):
    return json.loads(run_sem(["blame", file], cwd=cwd))


def logic_changed_entities(base_sha, file, cwd=None):
    """Names of entities in `file` with a non-cosmetic change since base_sha."""
    out = run_sem(["diff", f"{base_sha}..HEAD", "--no-cosmetics", "--", file], cwd=cwd)
    data = json.loads(out)
    names = set()
    for ch in data.get("changes", []):
        n = ch.get("name") or ch.get("entity")
        if n:
            names.add(n)
    return names


def scan(paths, cwd=None, rebuild=False):
    """Return worklist items for entities classified missing/stale (or all when rebuild=True)."""
    entities = [e for e in sem_entities(paths, cwd=cwd) if e.get("type") in CODE_TYPES]
    by_file = {}
    for e in entities:
        f = e.get("file") or (paths[0] if len(paths) == 1 else None)
        if f:
            by_file.setdefault(f, []).append(e)

    work = []
    for f, ents in by_file.items():
        read_path = f if cwd is None else os.path.join(cwd, f)
        text = _read_text(read_path)
        lines = text.splitlines()
        blame = {b["name"]: b for b in sem_blame(f, cwd=cwd)}
        for e in ents:
            marker = find_marker_above(lines, e["start_line"])
            existing_sha = marker["sha"] if marker else None
            blame_sha = blame.get(e["name"], {}).get("commit", "")
            if rebuild:
                status = "missing"
            else:
                logic = False
                if existing_sha and blame_sha and not blame_sha.startswith(existing_sha):
                    logic = e["name"] in logic_changed_entities(existing_sha, f, cwd=cwd)
                status = classify(existing_sha, blame_sha, logic)
            if status in ("missing", "stale"):
                work.append({
                    "file": f, "name": e["name"],
                    "start_line": e["start_line"], "end_line": e["end_line"],
                    "status": status, "blame_sha": blame_sha,
                    "existing_desc": marker["desc"] if marker else None,
                })
    return work
