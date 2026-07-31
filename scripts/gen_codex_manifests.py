#!/usr/bin/env python3
"""Generate Codex-native plugin manifests from the Claude Code ones.

Source of truth: .claude-plugin/marketplace.json plus each plugin's
.claude-plugin/plugin.json. Emits .agents/plugins/marketplace.json and one
<plugin>/.codex-plugin/plugin.json per plugin so the repo also works as a
plugin marketplace in OpenAI Codex. --check verifies the committed files
match a fresh regeneration without writing anything.
"""

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class GenerationError(ValueError):
    """A structural problem in the Claude manifests that blocks generation."""


def _render(obj: dict) -> str:
    return json.dumps(obj, indent=2) + "\n"


def _load_json(path: Path, label: str) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GenerationError(f"{label}: cannot read {path.name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GenerationError(f"{label}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise GenerationError(f"{label}: expected a JSON object")
    return data


def generate(repo: Path) -> dict[Path, str]:
    """Map each Codex manifest path to its rendered JSON content."""
    marketplace = _load_json(repo / ".claude-plugin" / "marketplace.json", "marketplace.json")
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list):
        raise GenerationError('marketplace.json: missing "plugins" list')
    if not marketplace.get("name"):
        raise GenerationError('marketplace.json: missing "name"')
    seen: set[str] = set()
    entries: list[dict] = []
    out: dict[Path, str] = {}
    for entry in plugins:
        if not isinstance(entry, dict) or not entry.get("name"):
            raise GenerationError(f'marketplace.json: entry missing "name": {entry!r}')
        name = entry["name"]
        if name in seen:
            raise GenerationError(f"duplicate plugin name in marketplace.json: {name}")
        seen.add(name)
        source = entry.get("source")
        if not isinstance(source, str) or not source.startswith("./"):
            raise GenerationError(f"{name}: expected string source './<dir>', got {source!r}")
        plugin_dir = repo / source
        claude_manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        if not claude_manifest.is_file():
            raise GenerationError(f"{name}: missing {source}/.claude-plugin/plugin.json")
        if not (plugin_dir / "skills").is_dir():
            raise GenerationError(f"{name}: missing {source}/skills/ directory")
        pdata = _load_json(claude_manifest, name)
        if pdata.get("name") != name:
            raise GenerationError(f"{name}: plugin.json name is {pdata.get('name')!r}, expected {name!r}")
        missing = [key for key in ("version", "description") if not pdata.get(key)]
        if missing:
            raise GenerationError(f"{name}: plugin.json missing {', '.join(missing)}")
        codex_manifest = {"name": name, "version": pdata["version"], "description": pdata["description"]}
        if "author" in pdata:
            codex_manifest["author"] = pdata["author"]
        codex_manifest["skills"] = "./skills/"
        out[plugin_dir / ".codex-plugin" / "plugin.json"] = _render(codex_manifest)
        codex_entry: dict = {"name": name}
        if "category" in entry:
            codex_entry["category"] = entry["category"]
        codex_entry["source"] = {"source": "local", "path": source}
        entries.append(codex_entry)
    out[repo / ".agents" / "plugins" / "marketplace.json"] = _render(
        {"name": marketplace["name"], "plugins": entries})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=REPO, help="repo root (default: this repo)")
    parser.add_argument("--check", action="store_true", help="verify committed files match; write nothing")
    args = parser.parse_args()
    try:
        rendered = generate(args.repo)
    except GenerationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if args.check:
        drift = [path for path, content in rendered.items()
                 if not path.is_file() or path.read_text(encoding="utf-8") != content]
        if drift:
            for path in sorted(drift):
                print(f"DRIFT: {path.relative_to(args.repo)}", file=sys.stderr)
            print("Run: uv run scripts/gen_codex_manifests.py", file=sys.stderr)
            return 1
        print(f"OK: {len(rendered)} Codex manifests in sync")
        return 0
    for path, content in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(args.repo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
