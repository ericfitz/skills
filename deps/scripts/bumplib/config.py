"""Load and merge bump configuration: exclusions, adapter selection, command overrides."""
import json
from pathlib import Path


def parse_claude_exclusions(text: str) -> list:
    out, in_section = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            in_section = s.lower() == "## bump exclusions"
            continue
        if in_section and s.startswith("- "):
            out.append(s[2:].strip())
    return out


def load_config(root: Path) -> dict:
    p = Path(root) / ".bump-config.json"
    if p.exists():
        return json.loads(p.read_text())
    return {}


def merged_exclusions(root: Path):
    root = Path(root)
    exclude, holds = [], {}
    claude = root / "CLAUDE.md"
    if not claude.exists():
        claude = root / ".claude" / "CLAUDE.md"
    if claude.exists():
        exclude += parse_claude_exclusions(claude.read_text())
    cfg = load_config(root)
    exclude += list(cfg.get("exclude", []))
    holds.update(cfg.get("hold", {}))
    # de-dupe, preserve order
    seen, uniq = set(), []
    for p in exclude:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq, holds


def resolve_adapter(axis: str, config: dict, remote_url) -> str:
    if config.get(axis):
        return config[axis]
    if axis in ("codeHost", "issueTracker") and remote_url and "github.com" in remote_url:
        return "github"
    if axis == "ecosystem":
        return ""  # ecosystem is detected, not configured
    return "none"
