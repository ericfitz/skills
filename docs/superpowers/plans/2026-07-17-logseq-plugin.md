# Logseq Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new `logseq` plugin (5 skills: capture, query, lint, organize, from-obsidian) over a shared, tested `logseqlib` Python library, per `docs/superpowers/specs/2026-07-17-logseq-skills-design.md`.

**Architecture:** Thin SKILL.md orchestrators call one CLI (`logseq/scripts/logseq-cli.py`), which dispatches to `logseqlib` modules: `config` (graph resolution + auto-discovery), `page` (round-trip outline parser/writer), `api` (hybrid HTTP-API-with-file-fallback writes), `scan` (link index + lint checks), `apply` (safe changeset application: backup/git-check/diff), `refactor` (rename-refs, merge), `convert` (Obsidian → Logseq).

**Tech Stack:** Python 3.11+ stdlib only (urllib, json, re, difflib, hashlib, shutil, argparse, dataclasses). Tests: `unittest` in repo-root `tests/` (same style as `test_bump_*.py`). Lint: `ruff`.

## Global Constraints

- **Stdlib only** — no third-party imports anywhere in `logseq/scripts/` (skills run it via `uv run` with `python3` fallback, no venv).
- **Round-trip contract:** `page.write(page.parse(text)) == text` byte-for-byte for any file the parser accepts. Unmodeled syntax (`{{query …}}`, `{{embed …}}`, `:LOGBOOK:` drawers, code fences) is opaque raw text, never rewritten.
- **Never write back a page that failed to parse** — flag and skip.
- **CLI output:** every subcommand prints exactly one JSON value to stdout; unexpected errors → `{"error": "<message>"}` on stdout and exit code 1.
- **Mutating operations** support `--dry-run`; multi-file operations snapshot affected files to `<graph>/logseq/.backups/<UTC-timestamp>/` and require a clean git tree (if the graph is a git repo) unless `--force`.
- **Test imports** follow the repo pattern: `sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))` then `from logseqlib import …`. `sys.dont_write_bytecode = True` at top of each test file.
- Run tests with `python3 -m unittest tests.<module> -v`; lint with `ruff check logseq/ tests/`.
- Commits: conventional-commit style `feat(logseq): …` / `test(logseq): …` etc., each ending with the standard Co-Authored-By / Claude-Session trailer used in this repo.
- Config file: `~/.config/logseq-skills/config.json` (schema in spec §1). API token comes from the env var named by `api.token_env` (default `LOGSEQ_API_TOKEN`), never from the file.
- All library file paths are `Path` objects; all JSON output uses `str(path)`.

---

### Task 1: Plugin scaffold + marketplace registration

**Files:**
- Create: `logseq/.claude-plugin/plugin.json`
- Create: `logseq/scripts/logseqlib/__init__.py`
- Modify: `.claude-plugin/marketplace.json` (add plugin entry)
- Modify: `scripts/verify-marketplace.sh` (plugin count, roster, scripts list)
- Create: `logseq/skills/capture/SKILL.md`, `logseq/skills/query/SKILL.md`, `logseq/skills/lint/SKILL.md`, `logseq/skills/organize/SKILL.md`, `logseq/skills/from-obsidian/SKILL.md` (minimal stubs — real bodies come in Task 12)

**Interfaces:**
- Consumes: nothing.
- Produces: plugin directory structure every later task writes into; `verify-marketplace.sh` green baseline.

- [ ] **Step 1: Create plugin.json**

`logseq/.claude-plugin/plugin.json`:

```json
{
  "name": "logseq",
  "version": "1.0.0",
  "description": "Interact with a local classic (file-based) Logseq graph: capture notes/TODOs into journals or pages, answer questions from the graph, lint it for consistency, merge/restructure pages, and import notes from an Obsidian vault. Hybrid access: reads files directly, writes via the Logseq local HTTP API when the app is running, file fallback otherwise.",
  "author": { "name": "efitz" }
}
```

- [ ] **Step 2: Create the package init and skill stubs**

`logseq/scripts/logseqlib/__init__.py` — empty file.

Five stub SKILL.md files so structural checks pass before Task 12 fills them in. Each has ONLY frontmatter + one placeholder line. Example for capture (repeat for query, lint, organize, from-obsidian, changing `name:`):

```markdown
---
name: capture
version: 1.0.0
description: Stub — replaced in Task 12.
---

Body arrives in Task 12.
```

- [ ] **Step 3: Register in marketplace.json**

In `.claude-plugin/marketplace.json`, append to `plugins` array:

```json
{ "name": "logseq", "description": "Logseq graph toolkit for a local classic (file-based) graph: capture notes/TODOs into journals or pages (capture), answer questions from the graph (query), find consistency problems (lint), merge/dedupe and restructure pages (organize), and import notes from an Obsidian vault (from-obsidian). Hybrid file/HTTP-API access with automatic graph discovery.", "source": "./logseq", "category": "productivity" }
```

- [ ] **Step 4: Update verify-marketplace.sh**

Three edits:
1. `if [ "$PLUGIN_COUNT" -eq 8 ]` → `-eq 9`, and the two message strings `8 plugin entries` → `9 plugin entries`.
2. Add to the `PLUGINS` array: `"logseq:productivity:capture,query,lint,organize,from-obsidian"`
3. Add to the `SCRIPTS` array: `"logseq/scripts/logseq-cli.py"` — **and** create an empty executable placeholder now so the check passes: `logseq/scripts/logseq-cli.py` containing just `#!/usr/bin/env python3` and `raise SystemExit("logseq-cli: implemented in Task 11")` (replaced in Task 11).

- [ ] **Step 5: Run the verifier**

Run: `bash scripts/verify-marketplace.sh`
Expected: `PASS` count includes `logseq (category=productivity, skills: capture,query,lint,organize,from-obsidian)`, `FAIL: 0`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add logseq .claude-plugin/marketplace.json scripts/verify-marketplace.sh
git commit -m "feat(logseq): scaffold logseq plugin and register in marketplace"
```

---

### Task 2: `logseqlib/config.py` — graph resolution with auto-discovery

**Files:**
- Create: `logseq/scripts/logseqlib/config.py`
- Test: `tests/test_logseq_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces (exact signatures later tasks rely on):
  - `CONFIG_PATH: Path` (default `~/.config/logseq-skills/config.json`)
  - `class ConfigError(Exception)` — message describes what's wrong.
  - `class AmbiguousGraphError(ConfigError)` — has `.candidates: list[Path]`.
  - `@dataclass Resolved: name: str; path: Path; source: str` (`"config"` | `"discovered"`)`; api_url: str; api_token: str | None; obsidian_vault: Path | None`
  - `def is_graph_dir(path: Path) -> bool` — true iff `path / "logseq"` is a directory.
  - `def discover_graphs(graphs_dir: Path) -> list[Path]` — decode `logseq_local_*.transit` filenames, return existing graph dirs only.
  - `def resolve(graph: str | None = None, config_path: Path = CONFIG_PATH, graphs_dir: Path | None = None, env: dict | None = None) -> Resolved`
  - `def write_config(resolved: Resolved, config_path: Path = CONFIG_PATH) -> None` — writes/refreshes the config file from a discovered graph (used by the "offer to write config" flow).

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_config.py`:

```python
# tests/test_logseq_config.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import config as cfg  # noqa: E402


def make_graph(root: Path, name: str = "notes") -> Path:
    g = root / name
    (g / "logseq").mkdir(parents=True)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    return g


class TestDiscovery(unittest.TestCase):
    def test_decodes_transit_filenames(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            gdir = root / "graphs"
            gdir.mkdir()
            enc = str(g).replace("/", "++")
            (gdir / f"logseq_local_{enc}.transit").write_text("{}")
            self.assertEqual(cfg.discover_graphs(gdir), [g])

    def test_skips_missing_and_non_graph_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            gone = root / "gone"
            plain = root / "plain"
            plain.mkdir()  # exists but no logseq/ inside
            gdir = root / "graphs"
            gdir.mkdir()
            for p in (gone, plain):
                enc = str(p).replace("/", "++")
                (gdir / f"logseq_local_{enc}.transit").write_text("{}")
            self.assertEqual(cfg.discover_graphs(gdir), [])

    def test_empty_or_absent_dir(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cfg.discover_graphs(Path(td) / "nope"), [])


class TestResolve(unittest.TestCase):
    def _config(self, root: Path, graph: Path, name="main", extra=None) -> Path:
        cp = root / "config.json"
        data = {
            "graphs": {name: {"path": str(graph)}},
            "default_graph": name,
            "api": {"url": "http://127.0.0.1:12315", "token_env": "LOGSEQ_TEST_TOKEN"},
        }
        if extra:
            data.update(extra)
        cp.write_text(json.dumps(data))
        return cp

    def test_resolves_default_graph_from_config(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, g)
            r = cfg.resolve(config_path=cp, env={"LOGSEQ_TEST_TOKEN": "sekrit"})
            self.assertEqual(r.name, "main")
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "config")
            self.assertEqual(r.api_url, "http://127.0.0.1:12315")
            self.assertEqual(r.api_token, "sekrit")
            self.assertIsNone(r.obsidian_vault)

    def test_named_graph_and_vault(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g2 = make_graph(root, "work")
            cp = root / "config.json"
            cp.write_text(json.dumps({
                "graphs": {"main": {"path": str(root / "gone")},
                           "work": {"path": str(g2)}},
                "default_graph": "main",
                "obsidian_vault": str(root),
                "api": {"url": "http://127.0.0.1:12315"},
            }))
            r = cfg.resolve(graph="work", config_path=cp, env={})
            self.assertEqual(r.path, g2)
            self.assertEqual(r.obsidian_vault, root)
            self.assertIsNone(r.api_token)

    def test_missing_token_env_is_none(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, g)
            r = cfg.resolve(config_path=cp, env={})
            self.assertIsNone(r.api_token)

    def test_stale_config_falls_back_to_discovery(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            cp = self._config(root, root / "moved-away")  # stale path
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            r = cfg.resolve(config_path=cp, graphs_dir=gdir, env={})
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "discovered")

    def test_missing_config_single_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            gdir = root / "graphs"
            gdir.mkdir()
            (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            r = cfg.resolve(config_path=root / "absent.json", graphs_dir=gdir, env={})
            self.assertEqual(r.path, g)
            self.assertEqual(r.source, "discovered")
            self.assertEqual(r.api_url, cfg.DEFAULT_API_URL)

    def test_ambiguous_discovery_raises_with_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g1 = make_graph(root, "a")
            g2 = make_graph(root, "b")
            gdir = root / "graphs"
            gdir.mkdir()
            for g in (g1, g2):
                (gdir / f"logseq_local_{str(g).replace('/', '++')}.transit").write_text("{}")
            with self.assertRaises(cfg.AmbiguousGraphError) as ctx:
                cfg.resolve(config_path=root / "absent.json", graphs_dir=gdir, env={})
            self.assertEqual(sorted(ctx.exception.candidates), sorted([g1, g2]))

    def test_nothing_found_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            with self.assertRaises(cfg.ConfigError):
                cfg.resolve(config_path=root / "absent.json",
                            graphs_dir=root / "graphs", env={})


class TestWriteConfig(unittest.TestCase):
    def test_write_and_reread(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            g = make_graph(root)
            r = cfg.Resolved(name="notes", path=g, source="discovered",
                             api_url=cfg.DEFAULT_API_URL, api_token=None,
                             obsidian_vault=None)
            cp = root / "cfg" / "config.json"
            cfg.write_config(r, config_path=cp)
            r2 = cfg.resolve(config_path=cp, env={})
            self.assertEqual(r2.path, g)
            self.assertEqual(r2.source, "config")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_config -v`
Expected: FAIL — `ImportError: cannot import name 'config'` (module doesn't exist yet).

- [ ] **Step 3: Implement `logseqlib/config.py`**

```python
# logseq/scripts/logseqlib/config.py
"""Graph resolution: config file first, Logseq's own recent-graphs list as fallback."""
import json
import os
from dataclasses import dataclass
from pathlib import Path

CONFIG_PATH = Path.home() / ".config" / "logseq-skills" / "config.json"
LOGSEQ_GRAPHS_DIR = Path.home() / ".logseq" / "graphs"
DEFAULT_API_URL = "http://127.0.0.1:12315"
DEFAULT_TOKEN_ENV = "LOGSEQ_API_TOKEN"
TRANSIT_PREFIX = "logseq_local_"


class ConfigError(Exception):
    pass


class AmbiguousGraphError(ConfigError):
    def __init__(self, candidates):
        self.candidates = list(candidates)
        names = ", ".join(str(c) for c in self.candidates)
        super().__init__(f"multiple Logseq graphs found, pick one: {names}")


@dataclass
class Resolved:
    name: str
    path: Path
    source: str  # "config" | "discovered"
    api_url: str
    api_token: str | None
    obsidian_vault: Path | None


def is_graph_dir(path: Path) -> bool:
    return (path / "logseq").is_dir()


def discover_graphs(graphs_dir: Path) -> list[Path]:
    if not graphs_dir.is_dir():
        return []
    found = []
    for f in sorted(graphs_dir.iterdir()):
        if not (f.name.startswith(TRANSIT_PREFIX) and f.suffix == ".transit"):
            continue
        encoded = f.name[len(TRANSIT_PREFIX):-len(".transit")]
        p = Path(encoded.replace("++", "/"))
        if is_graph_dir(p):
            found.append(p)
    return found


def _from_config(data: dict, graph: str | None, env: dict) -> Resolved | None:
    graphs = data.get("graphs", {})
    name = graph or data.get("default_graph")
    entry = graphs.get(name)
    if not entry:
        return None
    path = Path(entry.get("path", ""))
    if not is_graph_dir(path):
        return None  # stale — caller falls back to discovery
    api = data.get("api", {})
    token_env = api.get("token_env", DEFAULT_TOKEN_ENV)
    vault = data.get("obsidian_vault")
    return Resolved(
        name=name,
        path=path,
        source="config",
        api_url=api.get("url", DEFAULT_API_URL),
        api_token=env.get(token_env),
        obsidian_vault=Path(vault) if vault else None,
    )


def resolve(graph: str | None = None, config_path: Path = CONFIG_PATH,
            graphs_dir: Path | None = None, env: dict | None = None) -> Resolved:
    env = os.environ if env is None else env
    graphs_dir = LOGSEQ_GRAPHS_DIR if graphs_dir is None else graphs_dir

    data = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            raise ConfigError(f"unreadable config {config_path}: {e}") from e
        r = _from_config(data, graph, env)
        if r is not None:
            return r

    candidates = discover_graphs(graphs_dir)
    if len(candidates) == 1:
        api = data.get("api", {})
        token_env = api.get("token_env", DEFAULT_TOKEN_ENV)
        vault = data.get("obsidian_vault")
        return Resolved(
            name=candidates[0].name,
            path=candidates[0],
            source="discovered",
            api_url=api.get("url", DEFAULT_API_URL),
            api_token=env.get(token_env),
            obsidian_vault=Path(vault) if vault else None,
        )
    if len(candidates) > 1:
        raise AmbiguousGraphError(candidates)
    raise ConfigError(
        f"no Logseq graph found: config {config_path} missing/stale and no "
        f"graphs discovered under {graphs_dir}"
    )


def write_config(resolved: Resolved, config_path: Path = CONFIG_PATH) -> None:
    data = {}
    if config_path.is_file():
        try:
            data = json.loads(config_path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    graphs = data.setdefault("graphs", {})
    graphs[resolved.name] = {"path": str(resolved.path)}
    data.setdefault("default_graph", resolved.name)
    data.setdefault("api", {"url": resolved.api_url,
                            "token_env": DEFAULT_TOKEN_ENV})
    if resolved.obsidian_vault:
        data.setdefault("obsidian_vault", str(resolved.obsidian_vault))
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(data, indent=2) + "\n")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_config -v`
Expected: all tests PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_config.py
git add logseq/scripts/logseqlib/config.py tests/test_logseq_config.py
git commit -m "feat(logseq): config module with graph resolution and auto-discovery"
```

---

### Task 3: `logseqlib/page.py` — round-trip outline parser

**Files:**
- Create: `logseq/scripts/logseqlib/page.py`
- Test: `tests/test_logseq_page.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `class PageParseError(Exception)`
  - `@dataclass Block: lines: list[str]; children: list["Block"]` — `lines` are RAW source lines (indent stripped from the bullet line and continuations, `- ` marker kept on line 0). `content` property → first line without the `- ` marker.
  - `@dataclass Page: pre_lines: list[str]; blocks: list[Block]; indent_unit: str` — `pre_lines` raw lines before the first bullet (page-properties area).
  - `def parse(text: str) -> Page`
  - `def write(page: Page) -> str` — byte-for-byte inverse of `parse` for accepted input.
  - `def block_properties(block: Block) -> dict[str, str]` — `key:: value` pairs in the block's own lines.
  - `def page_properties(page: Page) -> dict[str, str]` — from `pre_lines` plus, if present, a first bullet consisting only of `key:: value` lines.

Parsing rules (v1, from spec §2):
- A bullet line matches `^(?P<indent>\s*)- (?P<rest>.*)$`. Depth = how many times `indent_unit` repeats in `indent`. `indent_unit` = indentation of the FIRST indented bullet found (`\t` if it starts with a tab, else the literal spaces, default `"  "` when no nesting exists).
- Non-bullet lines after a bullet (continuations: code fences, logbook, multiline text) belong to the preceding block, raw.
- A non-bullet line before any bullet goes to `pre_lines`.
- A bullet indented deeper than `parent depth + 1` units, or with indentation that isn't a whole repetition of `indent_unit`, raises `PageParseError` (never guess structure — constraint: unparseable pages are flagged, not rewritten).

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_page.py`:

```python
# tests/test_logseq_page.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import page as pg  # noqa: E402

SIMPLE = "- alpha\n- beta\n"

NESTED_TABS = "- a\n\t- a1\n\t\t- a1x\n- b\n"

NESTED_SPACES = "- a\n  - a1\n    - a1x\n- b\n"

PROPS = (
    "title:: My Page\n"
    "tags:: project, active\n"
    "\n"
    "- first block\n"
    "  id:: 6650some-uuid\n"
    "- TODO call [[Alice]]\n"
)

OPAQUE = (
    "- notes\n"
    "\t- ```python\n"
    "\t  x = 1\n"
    "\t  ```\n"
    "\t- {{query (todo TODO)}}\n"
    "- DONE ship it\n"
    "  :LOGBOOK:\n"
    "  CLOCK: [2026-07-16 Thu 09:00]\n"
    "  :END:\n"
)


class TestRoundTrip(unittest.TestCase):
    def test_round_trips(self):
        for text in (SIMPLE, NESTED_TABS, NESTED_SPACES, PROPS, OPAQUE, ""):
            self.assertEqual(pg.write(pg.parse(text)), text)


class TestStructure(unittest.TestCase):
    def test_simple_two_blocks(self):
        p = pg.parse(SIMPLE)
        self.assertEqual([b.content for b in p.blocks], ["alpha", "beta"])
        self.assertEqual(p.pre_lines, [])

    def test_nesting_tabs(self):
        p = pg.parse(NESTED_TABS)
        self.assertEqual(p.indent_unit, "\t")
        a = p.blocks[0]
        self.assertEqual(a.content, "a")
        self.assertEqual(a.children[0].content, "a1")
        self.assertEqual(a.children[0].children[0].content, "a1x")
        self.assertEqual(p.blocks[1].content, "b")

    def test_nesting_spaces(self):
        p = pg.parse(NESTED_SPACES)
        self.assertEqual(p.indent_unit, "  ")
        self.assertEqual(p.blocks[0].children[0].children[0].content, "a1x")

    def test_continuation_lines_stay_with_block(self):
        p = pg.parse(OPAQUE)
        code = p.blocks[0].children[0]
        self.assertEqual(code.lines[0], "- ```python")
        self.assertEqual(len(code.lines), 3)
        done = p.blocks[1]
        self.assertEqual(done.content, "DONE ship it")
        self.assertEqual(len(done.lines), 4)  # bullet + 3 logbook lines

    def test_page_properties(self):
        p = pg.parse(PROPS)
        self.assertEqual(pg.page_properties(p),
                         {"title": "My Page", "tags": "project, active"})
        first = p.blocks[0]
        self.assertEqual(pg.block_properties(first), {"id": "6650some-uuid"})

    def test_first_bullet_props_page(self):
        text = "- title:: Alt Style\n  alias:: other\n- body\n"
        p = pg.parse(text)
        self.assertEqual(pg.page_properties(p),
                         {"title": "Alt Style", "alias": "other"})

    def test_bad_indent_raises(self):
        with self.assertRaises(pg.PageParseError):
            pg.parse("- a\n\t\t\t- too deep\n")
        with self.assertRaises(pg.PageParseError):
            pg.parse("- a\n   - ragged (3 spaces vs 2-space unit)\n  - ok\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_page -v`
Expected: FAIL — `ImportError` (no `page` module).

- [ ] **Step 3: Implement `logseqlib/page.py`**

```python
# logseq/scripts/logseqlib/page.py
"""Round-trip parser/writer for classic Logseq outline pages.

Contract: write(parse(text)) == text, byte-for-byte, for any accepted text.
Unmodeled syntax (queries, embeds, logbook, code fences) rides along as raw
continuation lines and is never rewritten. Pages we cannot parse raise
PageParseError and must never be written back.
"""
import re
from dataclasses import dataclass, field

BULLET_RE = re.compile(r"^(?P<indent>[ \t]*)- (?P<rest>.*)$")
PROP_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_-]+):: (?P<val>.*)$")


class PageParseError(Exception):
    pass


@dataclass
class Block:
    lines: list[str] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)

    @property
    def content(self) -> str:
        m = BULLET_RE.match(self.lines[0])
        return m.group("rest") if m else self.lines[0]


@dataclass
class Page:
    pre_lines: list[str] = field(default_factory=list)
    blocks: list[Block] = field(default_factory=list)
    indent_unit: str = "  "


def _detect_indent_unit(lines: list[str]) -> str:
    for line in lines:
        m = BULLET_RE.match(line)
        if m and m.group("indent"):
            ind = m.group("indent")
            return "\t" if ind.startswith("\t") else ind
    return "  "


def _depth(indent: str, unit: str, lineno: int) -> int:
    if not indent:
        return 0
    n, rem = divmod(len(indent), len(unit))
    if rem or indent != unit * n:
        raise PageParseError(f"line {lineno}: indentation is not a whole "
                             f"number of {unit!r} units")
    return n


def parse(text: str) -> Page:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()  # trailing newline; write() re-adds one per line
    page = Page(indent_unit=_detect_indent_unit(lines))
    stack: list[Block] = []  # stack[i] = open block at depth i
    for i, line in enumerate(lines, start=1):
        m = BULLET_RE.match(line)
        if not m:
            if stack:
                stack[-1].lines.append(_strip_unit(line, page.indent_unit,
                                                   len(stack) - 1))
            else:
                page.pre_lines.append(line)
            continue
        depth = _depth(m.group("indent"), page.indent_unit, i)
        if depth > len(stack):
            raise PageParseError(f"line {i}: bullet depth {depth} with no "
                                 f"parent at depth {depth - 1}")
        del stack[depth:]
        block = Block(lines=[f"- {m.group('rest')}"])
        if depth == 0:
            page.blocks.append(block)
        else:
            stack[-1].children.append(block)
        stack.append(block)
    return page


def _strip_unit(line: str, unit: str, depth: int) -> str:
    prefix = unit * depth
    return line[len(prefix):] if prefix and line.startswith(prefix) else line


def _write_block(out: list[str], block: Block, unit: str, depth: int) -> None:
    prefix = unit * depth
    for line in block.lines:
        out.append(prefix + line if line else line)
    for child in block.children:
        _write_block(out, child, unit, depth + 1)


def write(page: Page) -> str:
    out: list[str] = list(page.pre_lines)
    for block in page.blocks:
        _write_block(out, block, page.indent_unit, 0)
    return "\n".join(out) + "\n" if out else ""


def block_properties(block: Block) -> dict[str, str]:
    props = {}
    for line in block.lines:
        m = PROP_RE.match(line)
        if m:
            props[m.group("key")] = m.group("val")
    return props


def page_properties(page: Page) -> dict[str, str]:
    props = {}
    for line in page.pre_lines:
        m = PROP_RE.match(line)
        if m:
            props[m.group("key")] = m.group("val")
    if not props and page.blocks:
        first = page.blocks[0]
        if first.lines and all(PROP_RE.match(ln) for ln in first.lines):
            props = block_properties(first)
    return props
```

Note on round-trip: continuation lines are stored with their depth prefix stripped (`_strip_unit`) and re-added by `_write_block`, so a continuation line that did NOT carry the exact prefix (e.g. code-fence internals indented with extra spaces, as in the `OPAQUE` fixture where continuations use `\t  `) is stored raw and re-emitted raw — `_strip_unit` only strips when the prefix matches exactly, and `_write_block` must not double-prefix those. To keep write() the exact inverse, `_write_block` re-adds the prefix ONLY to lines that were stripped. Implement by storing continuations as `(stripped: bool, text: str)`? No — simpler: store continuation lines RAW (skip `_strip_unit` entirely, keep the full original line) and have `_write_block` prefix only `block.lines[0]`. Adjust both functions accordingly:

```python
# in parse(): replace the continuation branch with
            if stack:
                stack[-1].lines.append(line)  # raw, full original line
# in _write_block(): only the bullet line gets the computed prefix
    out.append(prefix + block.lines[0])
    out.extend(block.lines[1:])
```

Use this raw-continuation variant — it is the one that satisfies the byte-for-byte contract; delete `_strip_unit`. (Consequence, acceptable for v1: freshly built blocks — Task 4 — generate their own continuation lines with explicit prefixes.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_page -v`
Expected: all PASS, including every round-trip case.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_page.py
git add logseq/scripts/logseqlib/page.py tests/test_logseq_page.py
git commit -m "feat(logseq): round-trip outline page parser"
```

---

### Task 4: `page.py` mutation + naming helpers

**Files:**
- Modify: `logseq/scripts/logseqlib/page.py` (append functions at end)
- Test: `tests/test_logseq_page_mutate.py`

**Interfaces:**
- Consumes: Task 3's `Page`, `Block`, `parse`, `write`.
- Produces:
  - `def make_block(content: str, indent_unit: str = "  ") -> Block` — multiline `content` becomes bullet line 0 + prefixed continuation lines (continuations prefixed with two spaces after the unit so they align under the bullet text).
  - `def append_block(page: Page, content: str) -> Page` — append a top-level block.
  - `def journal_filename(date_iso: str) -> str` — `"2026-07-17"` → `"2026_07_17.md"`.
  - `def page_filename(name: str) -> str` — page name → filename: `/` → `%2F` URL-encoding (classic Logseq convention); otherwise the name verbatim + `.md`.
  - `def filename_to_page_name(stem: str) -> str` — inverse (`%2F` → `/` via `urllib.parse.unquote`).
  - `def append_to_file(path: Path, content: str) -> None` — parse file (empty Page if absent), `append_block`, atomic write back (`.tmp` + `os.replace`). Raises `PageParseError` upward — never writes on parse failure.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_page_mutate.py`:

```python
# tests/test_logseq_page_mutate.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import page as pg  # noqa: E402


class TestMakeAppend(unittest.TestCase):
    def test_make_block_single_line(self):
        b = pg.make_block("TODO buy milk")
        self.assertEqual(b.lines, ["- TODO buy milk"])

    def test_make_block_multiline(self):
        b = pg.make_block("meeting notes\nwith [[Alice]]")
        self.assertEqual(b.lines, ["- meeting notes", "  with [[Alice]]"])

    def test_append_block_preserves_existing(self):
        text = "- a\n\t- a1\n"
        p = pg.parse(text)
        pg.append_block(p, "new one")
        self.assertEqual(pg.write(p), text + "- new one\n")


class TestNaming(unittest.TestCase):
    def test_journal_filename(self):
        self.assertEqual(pg.journal_filename("2026-07-17"), "2026_07_17.md")

    def test_page_filename_roundtrip(self):
        self.assertEqual(pg.page_filename("project/roadmap"),
                         "project%2Froadmap.md")
        self.assertEqual(pg.filename_to_page_name("project%2Froadmap"),
                         "project/roadmap")
        self.assertEqual(pg.page_filename("Plain Name"), "Plain Name.md")


class TestAppendToFile(unittest.TestCase):
    def test_appends_to_existing(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "j.md"
            f.write_text("- existing\n")
            pg.append_to_file(f, "added")
            self.assertEqual(f.read_text(), "- existing\n- added\n")

    def test_creates_missing_file(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "new.md"
            pg.append_to_file(f, "first")
            self.assertEqual(f.read_text(), "- first\n")

    def test_never_writes_unparseable(self):
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "bad.md"
            bad = "- a\n\t\t\t- too deep\n"
            f.write_text(bad)
            with self.assertRaises(pg.PageParseError):
                pg.append_to_file(f, "x")
            self.assertEqual(f.read_text(), bad)  # untouched


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_page_mutate -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'make_block'`.

- [ ] **Step 3: Implement (append to `page.py`)**

```python
# --- mutation + naming helpers (Task 4) ---
import os  # noqa: E402  (top of file with other imports in practice)
from pathlib import Path  # noqa: E402
from urllib.parse import quote, unquote  # noqa: E402


def make_block(content: str, indent_unit: str = "  ") -> Block:
    first, *rest = content.split("\n")
    lines = [f"- {first}"] + [f"  {ln}" for ln in rest]
    return Block(lines=lines)


def append_block(page: Page, content: str) -> Page:
    page.blocks.append(make_block(content, page.indent_unit))
    return page


def journal_filename(date_iso: str) -> str:
    return date_iso.replace("-", "_") + ".md"


def page_filename(name: str) -> str:
    return quote(name, safe=" ") .replace("/", "%2F") + ".md" \
        if "/" in name else name + ".md"


def filename_to_page_name(stem: str) -> str:
    return unquote(stem)


def append_to_file(path: Path, content: str) -> None:
    text = path.read_text() if path.is_file() else ""
    page = parse(text)  # PageParseError propagates; file untouched
    append_block(page, content)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(write(page))
    os.replace(tmp, path)
```

Correction to `page_filename` (the one-liner above is muddled — use this exact body): only `/` needs encoding for v1; everything else stays verbatim.

```python
def page_filename(name: str) -> str:
    return name.replace("/", "%2F") + ".md"
```

Move the three imports (`os`, `Path`, `quote`/`unquote` — drop `quote`, it is unused after the correction) to the top of `page.py` with the existing imports.

- [ ] **Step 4: Run tests — both page test modules**

Run: `python3 -m unittest tests.test_logseq_page tests.test_logseq_page_mutate -v`
Expected: all PASS (round-trip contract still green).

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_page_mutate.py
git add logseq/scripts/logseqlib/page.py tests/test_logseq_page_mutate.py
git commit -m "feat(logseq): page mutation and naming helpers"
```

---

### Task 5: `logseqlib/api.py` — hybrid write layer

**Files:**
- Create: `logseq/scripts/logseqlib/api.py`
- Test: `tests/test_logseq_api.py`

**Interfaces:**
- Consumes: `config.Resolved` (Task 2); `page.append_to_file`, `page.journal_filename`, `page.page_filename` (Task 4).
- Produces:
  - `class ApiUnavailable(Exception)`
  - `def _post(url: str, token: str | None, method: str, args: list, timeout: float = 3.0) -> object` — POST `{url}/api` with JSON body `{"method": method, "args": args}`, `Authorization: Bearer {token}`; returns decoded JSON. Raises `ApiUnavailable` on any `URLError`/`OSError`/HTTP error/missing token. **Module-level so tests monkeypatch `api._post`.**
  - `def probe(resolved) -> bool` — `_post(..., "logseq.App.getCurrentGraph", [])`; False on `ApiUnavailable`.
  - `def journal_page_name(resolved, date_iso: str) -> str | None` — datascript query `[:find (pull ?p [:block/name]) :where [?p :block/journal-day {yyyymmdd}]]` via `logseq.DB.datascriptQuery`; returns the page name or None.
  - `def append_to_journal(resolved, text: str, date_iso: str) -> dict` — API-first (`logseq.Editor.appendBlockInPage` with the journal page name), file fallback to `journals/{journal_filename(date_iso)}`. Returns `{"via": "api"|"files", "target": str}`.
  - `def append_to_page(resolved, page_name: str, text: str) -> dict` — API-first (`appendBlockInPage`), file fallback to `pages/{page_filename(name)}`.
  - `def create_page(resolved, page_name: str, content: str) -> dict` — **always files** (a brand-new file is the watcher-safe case per spec §4): writes `content` verbatim to `pages/{page_filename(name)}`; raises `FileExistsError` if the page exists. Returns `{"via": "files", "target": str}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_api.py`:

```python
# tests/test_logseq_api.py
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import api, config as cfg  # noqa: E402


def resolved(graph: Path) -> cfg.Resolved:
    return cfg.Resolved(name="t", path=graph, source="config",
                        api_url="http://127.0.0.1:12315", api_token="tok",
                        obsidian_vault=None)


def make_graph(td: str) -> Path:
    g = Path(td)
    (g / "journals").mkdir()
    (g / "pages").mkdir()
    (g / "logseq").mkdir()
    return g


class TestApiPath(unittest.TestCase):
    def test_append_to_page_via_api(self):
        calls = []

        def fake_post(url, token, method, args, timeout=3.0):
            calls.append((method, args))
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(api, "_post", fake_post):
                out = api.append_to_page(resolved(make_graph(td)), "Inbox", "hi")
        self.assertEqual(out["via"], "api")
        self.assertIn(("logseq.Editor.appendBlockInPage", ["Inbox", "hi"]),
                      calls)

    def test_append_to_journal_via_api_uses_query(self):
        def fake_post(url, token, method, args, timeout=3.0):
            if method == "logseq.DB.datascriptQuery":
                self.assertIn("20260717", args[0])
                return [[{"block/name": "jul 17th, 2026"}]]
            return {"ok": True}

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(api, "_post", fake_post):
                out = api.append_to_journal(resolved(make_graph(td)), "note",
                                            "2026-07-17")
        self.assertEqual(out["via"], "api")
        self.assertEqual(out["target"], "jul 17th, 2026")


class TestFileFallback(unittest.TestCase):
    def _down(self, *a, **kw):
        raise api.ApiUnavailable("down")

    def test_journal_falls_back_to_file(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            with mock.patch.object(api, "_post", self._down):
                out = api.append_to_journal(resolved(g), "note", "2026-07-17")
            self.assertEqual(out["via"], "files")
            f = g / "journals" / "2026_07_17.md"
            self.assertEqual(f.read_text(), "- note\n")

    def test_page_falls_back_and_appends(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            (g / "pages" / "Inbox.md").write_text("- old\n")
            with mock.patch.object(api, "_post", self._down):
                out = api.append_to_page(resolved(g), "Inbox", "new")
            self.assertEqual(out["via"], "files")
            self.assertEqual((g / "pages" / "Inbox.md").read_text(),
                             "- old\n- new\n")

    def test_probe_false_when_down(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(api, "_post", self._down):
                self.assertFalse(api.probe(resolved(make_graph(td))))


class TestCreatePage(unittest.TestCase):
    def test_creates_file_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            g = make_graph(td)
            out = api.create_page(resolved(g), "proj/plan", "- start\n")
            self.assertEqual(out["via"], "files")
            f = g / "pages" / "proj%2Fplan.md"
            self.assertEqual(f.read_text(), "- start\n")
            with self.assertRaises(FileExistsError):
                api.create_page(resolved(g), "proj/plan", "- again\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_api -v`
Expected: FAIL — `ImportError` (no `api` module).

- [ ] **Step 3: Implement `logseqlib/api.py`**

```python
# logseq/scripts/logseqlib/api.py
"""Hybrid write layer: Logseq local HTTP API when up, file edits otherwise."""
import json
import urllib.error
import urllib.request

from . import page as pg


class ApiUnavailable(Exception):
    pass


def _post(url, token, method, args, timeout=3.0):
    if not token:
        raise ApiUnavailable("no API token configured")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/api",
        data=json.dumps({"method": method, "args": args}).encode(),
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode() or "null")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise ApiUnavailable(str(e)) from e


def probe(resolved) -> bool:
    try:
        _post(resolved.api_url, resolved.api_token,
              "logseq.App.getCurrentGraph", [])
        return True
    except ApiUnavailable:
        return False


def journal_page_name(resolved, date_iso):
    day = date_iso.replace("-", "")
    q = ("[:find (pull ?p [:block/name]) "
         f":where [?p :block/journal-day {day}]]")
    try:
        rows = _post(resolved.api_url, resolved.api_token,
                     "logseq.DB.datascriptQuery", [q])
    except ApiUnavailable:
        return None
    if rows and rows[0] and isinstance(rows[0][0], dict):
        return rows[0][0].get("block/name")
    return None


def append_to_journal(resolved, text, date_iso):
    name = journal_page_name(resolved, date_iso)
    if name:
        try:
            _post(resolved.api_url, resolved.api_token,
                  "logseq.Editor.appendBlockInPage", [name, text])
            return {"via": "api", "target": name}
        except ApiUnavailable:
            pass
    path = resolved.path / "journals" / pg.journal_filename(date_iso)
    pg.append_to_file(path, text)
    return {"via": "files", "target": str(path)}


def append_to_page(resolved, page_name, text):
    try:
        _post(resolved.api_url, resolved.api_token,
              "logseq.Editor.appendBlockInPage", [page_name, text])
        return {"via": "api", "target": page_name}
    except ApiUnavailable:
        path = resolved.path / "pages" / pg.page_filename(page_name)
        pg.append_to_file(path, text)
        return {"via": "files", "target": str(path)}


def create_page(resolved, page_name, content):
    path = resolved.path / "pages" / pg.page_filename(page_name)
    if path.exists():
        raise FileExistsError(f"page already exists: {path}")
    path.write_text(content)
    return {"via": "files", "target": str(path)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_api -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_api.py
git add logseq/scripts/logseqlib/api.py tests/test_logseq_api.py
git commit -m "feat(logseq): hybrid api/file write layer"
```

---

### Task 6: `logseqlib/scan.py` — graph index + lint checks

**Files:**
- Create: `logseq/scripts/logseqlib/scan.py`
- Test: `tests/test_logseq_scan.py`

**Interfaces:**
- Consumes: `page.parse`, `page.page_properties`, `page.filename_to_page_name` (Tasks 3–4).
- Produces:
  - `@dataclass PageInfo: name: str; path: Path; is_journal: bool; links: set[str]; tags: set[str]; properties: dict[str, str]; parse_error: str | None`
  - `@dataclass Index: pages: dict[str, PageInfo]` — keyed by `name.lower()`.
  - `def scan_graph(graph: Path) -> Index` — walks `pages/*.md` + `journals/*.md`; regex link/tag extraction works even when `parse` fails (parse failure only sets `parse_error`, recorded for the "unparseable" finding).
  - `def backlinks(index: Index, name: str) -> set[str]` — page names (lowercased) linking to `name`.
  - Lint check functions, each `(index) -> list[dict]` with findings shaped `{"type": str, "page": str, "detail": str}`:
    - `lint_unparseable` — type `"unparseable"`.
    - `lint_broken_links` — type `"broken-link"`: link target has no page file (journals excluded as targets).
    - `lint_case_conflicts` — type `"case-conflict"`: same link target spelled with ≥2 casings across the graph (e.g. `[[foo]]` and `[[Foo]]`).
    - `lint_orphans` — type `"orphan"`: non-journal page with no inbound links and no tags on it.
    - `lint_near_duplicates` — type `"near-duplicate"`: two page names with `difflib.SequenceMatcher` ratio ≥ 0.85 (compared case-insensitively, skipping exact case conflicts already reported).
  - `def lint_all(index: Index) -> list[dict]` — concatenation in the order above.
  - `LINK_RE`, `TAG_RE` — exported (Task 8 reuses `LINK_RE`).

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_scan.py`:

```python
# tests/test_logseq_scan.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import scan  # noqa: E402


def build_graph(td: str) -> Path:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    (g / "logseq").mkdir()
    (g / "pages" / "Alpha.md").write_text(
        "type:: project\n\n- links to [[Beta]] and [[beta]]\n- see [[Gone]]\n")
    (g / "pages" / "Beta.md").write_text("- tagged #active\n- plain\n")
    (g / "pages" / "Betta.md").write_text("- near-dupe of Beta\n")
    (g / "pages" / "Loner.md").write_text("- nobody links here\n")
    (g / "pages" / "Broken.md").write_text("- a\n\t\t\t- bad indent\n")
    (g / "journals" / "2026_07_17.md").write_text("- day note [[Alpha]]\n")
    return g


class TestScan(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.index = scan.scan_graph(build_graph(self.td.name))

    def tearDown(self):
        self.td.cleanup()

    def test_pages_indexed(self):
        self.assertIn("alpha", self.index.pages)
        self.assertIn("2026_07_17", self.index.pages)
        self.assertTrue(self.index.pages["2026_07_17"].is_journal)

    def test_links_tags_properties(self):
        a = self.index.pages["alpha"]
        self.assertIn("beta", {ln.lower() for ln in a.links})
        self.assertEqual(a.properties.get("type"), "project")
        self.assertIn("active", self.index.pages["beta"].tags)

    def test_backlinks(self):
        self.assertIn("2026_07_17", scan.backlinks(self.index, "alpha"))

    def test_parse_error_recorded_but_links_still_scanned(self):
        b = self.index.pages["broken"]
        self.assertIsNotNone(b.parse_error)


class TestLint(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.findings = scan.lint_all(scan.scan_graph(build_graph(self.td.name)))
        self.by_type = {}
        for f in self.findings:
            self.by_type.setdefault(f["type"], []).append(f)

    def tearDown(self):
        self.td.cleanup()

    def test_unparseable(self):
        self.assertEqual(self.by_type["unparseable"][0]["page"], "Broken")

    def test_broken_link(self):
        details = [f["detail"] for f in self.by_type["broken-link"]]
        self.assertTrue(any("Gone" in d for d in details))

    def test_case_conflict(self):
        details = " ".join(f["detail"] for f in self.by_type["case-conflict"])
        self.assertIn("Beta", details)
        self.assertIn("beta", details)

    def test_orphan_excludes_journals_and_linked(self):
        pages = [f["page"] for f in self.by_type["orphan"]]
        self.assertIn("Loner", pages)
        self.assertNotIn("Alpha", pages)  # linked from journal
        self.assertNotIn("2026_07_17", pages)

    def test_near_duplicate(self):
        details = " ".join(f["detail"] for f in self.by_type["near-duplicate"])
        self.assertIn("Betta", details)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_scan -v`
Expected: FAIL — `ImportError` (no `scan` module).

- [ ] **Step 3: Implement `logseqlib/scan.py`**

```python
# logseq/scripts/logseqlib/scan.py
"""Read-only graph walker: link index + pure lint checks over it."""
import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import page as pg

LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
TAG_RE = re.compile(r"(?<!\S)#([A-Za-z0-9/_-]+)")


@dataclass
class PageInfo:
    name: str
    path: Path
    is_journal: bool
    links: set = field(default_factory=set)
    tags: set = field(default_factory=set)
    properties: dict = field(default_factory=dict)
    parse_error: str | None = None


@dataclass
class Index:
    pages: dict = field(default_factory=dict)  # lower-name -> PageInfo


def _scan_file(path: Path, is_journal: bool) -> PageInfo:
    name = pg.filename_to_page_name(path.stem)
    text = path.read_text()
    info = PageInfo(name=name, path=path, is_journal=is_journal,
                    links=set(LINK_RE.findall(text)),
                    tags=set(TAG_RE.findall(text)))
    try:
        parsed = pg.parse(text)
        info.properties = pg.page_properties(parsed)
    except pg.PageParseError as e:
        info.parse_error = str(e)
    return info


def scan_graph(graph: Path) -> Index:
    index = Index()
    for sub, is_journal in (("pages", False), ("journals", True)):
        d = graph / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            info = _scan_file(f, is_journal)
            index.pages[info.name.lower()] = info
    return index


def backlinks(index: Index, name: str) -> set:
    target = name.lower()
    return {key for key, info in index.pages.items()
            if target in {ln.lower() for ln in info.links}}


def lint_unparseable(index: Index):
    return [{"type": "unparseable", "page": info.name,
             "detail": info.parse_error}
            for info in index.pages.values() if info.parse_error]


def lint_broken_links(index: Index):
    out = []
    for info in index.pages.values():
        for link in sorted(info.links):
            if link.lower() not in index.pages:
                out.append({"type": "broken-link", "page": info.name,
                            "detail": f"[[{link}]] has no page file"})
    return out


def lint_case_conflicts(index: Index):
    spellings = {}
    for info in index.pages.values():
        for link in info.links:
            spellings.setdefault(link.lower(), set()).add(link)
    out = []
    for low, forms in sorted(spellings.items()):
        if len(forms) > 1:
            canonical = index.pages[low].name if low in index.pages else None
            out.append({"type": "case-conflict",
                        "page": canonical or sorted(forms)[0],
                        "detail": "link spellings: " + ", ".join(sorted(forms))})
    return out


def lint_orphans(index: Index):
    linked = set()
    for info in index.pages.values():
        linked |= {ln.lower() for ln in info.links}
        linked |= {t.lower() for t in info.tags}
    return [{"type": "orphan", "page": info.name,
             "detail": "no inbound links and no tags"}
            for key, info in sorted(index.pages.items())
            if not info.is_journal and key not in linked and not info.tags]


def lint_near_duplicates(index: Index):
    names = sorted(k for k, v in index.pages.items() if not v.is_journal)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a == b:
                continue
            if difflib.SequenceMatcher(None, a, b).ratio() >= 0.85:
                out.append({"type": "near-duplicate",
                            "page": index.pages[a].name,
                            "detail": f"{index.pages[a].name} ~ "
                                      f"{index.pages[b].name}"})
    return out


def lint_all(index: Index):
    return (lint_unparseable(index) + lint_broken_links(index)
            + lint_case_conflicts(index) + lint_orphans(index)
            + lint_near_duplicates(index))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_scan -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_scan.py
git add logseq/scripts/logseqlib/scan.py tests/test_logseq_scan.py
git commit -m "feat(logseq): graph scanner and lint checks"
```

---

### Task 7: `logseqlib/apply.py` — safe changeset application

**Files:**
- Create: `logseq/scripts/logseqlib/apply.py`
- Test: `tests/test_logseq_apply.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (works on raw paths/strings, so it stays reusable).
- Produces:
  - `class ApplyError(Exception)`
  - `@dataclass Change: path: Path; new_content: str | None` — `None` means delete the file. `path` is absolute, must live under the graph.
  - `def diff_changeset(changes: list[Change]) -> str` — unified diff, old (current file content, `""` if absent) vs new (`""` for delete), one section per change, headers `a/<relpath>` / `b/<relpath>` relative to the graph root passed in… **correction:** relpaths need the graph; exact signature is `def diff_changeset(graph: Path, changes: list[Change]) -> str`.
  - `def backup(graph: Path, changes: list[Change], now_stamp: str) -> Path | None` — copies each currently-existing affected file to `graph/logseq/.backups/{now_stamp}/{relpath}`; returns the backup dir, or None when no file existed yet.
  - `def git_is_dirty(graph: Path) -> bool | None` — None when the graph is not in a git repo; else `git status --porcelain` non-empty (run via `subprocess`, `git -C graph`).
  - `def apply_changeset(graph: Path, changes: list[Change], now_stamp: str, dry_run: bool = False, force: bool = False) -> dict` — the one entry point:
    1. any `change.path` outside `graph` → `ApplyError`.
    2. `dry_run` → `{"dry_run": True, "diff": diff_changeset(...), "files": [relpaths]}` — touches nothing.
    3. graph in git and dirty and not `force` → `ApplyError("graph git tree is dirty; commit/stash or pass force")`.
    4. `backup(...)`, then write each change atomically (`.tmp` + `os.replace`), delete for `None`.
    5. returns `{"applied": [relpaths], "backup": str | None, "diff": str}`.
  - `now_stamp` is always supplied by the caller (CLI passes `datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")`) — keeps the library deterministic for tests.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_apply.py`:

```python
# tests/test_logseq_apply.py
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import apply as ap  # noqa: E402

STAMP = "20260717T120000Z"


def graph_with_page(td: str) -> tuple[Path, Path]:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "logseq").mkdir()
    f = g / "pages" / "A.md"
    f.write_text("- old\n")
    return g, f


class TestDryRunAndDiff(unittest.TestCase):
    def test_dry_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            out = ap.apply_changeset(
                g, [ap.Change(f, "- new\n")], STAMP, dry_run=True)
            self.assertTrue(out["dry_run"])
            self.assertIn("-- old", out["diff"].replace("\n", " "))
            self.assertEqual(f.read_text(), "- old\n")

    def test_diff_covers_create_and_delete(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            new = g / "pages" / "B.md"
            d = ap.diff_changeset(g, [ap.Change(new, "- born\n"),
                                      ap.Change(f, None)])
            self.assertIn("pages/B.md", d)
            self.assertIn("+- born", d)
            self.assertIn("-- old", d)  # deletion of the "- old" line


class TestApply(unittest.TestCase):
    def test_apply_writes_backs_up_and_deletes(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            other = g / "pages" / "B.md"
            out = ap.apply_changeset(
                g, [ap.Change(f, None), ap.Change(other, "- hi\n")], STAMP)
            self.assertFalse(f.exists())
            self.assertEqual(other.read_text(), "- hi\n")
            bdir = g / "logseq" / ".backups" / STAMP
            self.assertEqual((bdir / "pages" / "A.md").read_text(), "- old\n")
            self.assertEqual(out["backup"], str(bdir))
            self.assertIn("pages/B.md", out["applied"])

    def test_path_outside_graph_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            g, _ = graph_with_page(td)
            with tempfile.TemporaryDirectory() as td2:
                stray = Path(td2) / "x.md"
                with self.assertRaises(ap.ApplyError):
                    ap.apply_changeset(g, [ap.Change(stray, "- x\n")], STAMP)


class TestGitGuard(unittest.TestCase):
    def _git(self, g, *args):
        subprocess.run(["git", "-C", str(g), *args], check=True,
                       capture_output=True)

    def test_dirty_tree_blocks_without_force(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            self._git(g, "init", "-q")
            self._git(g, "add", "-A")
            self._git(g, "-c", "user.email=t@t", "-c", "user.name=t",
                      "commit", "-qm", "init")
            f.write_text("- dirty\n")  # uncommitted change
            with self.assertRaises(ap.ApplyError):
                ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            out = ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP,
                                     force=True)
            self.assertEqual(f.read_text(), "- new\n")
            self.assertIn("pages/A.md", out["applied"])

    def test_non_git_graph_needs_no_force(self):
        with tempfile.TemporaryDirectory() as td:
            g, f = graph_with_page(td)
            ap.apply_changeset(g, [ap.Change(f, "- new\n")], STAMP)
            self.assertEqual(f.read_text(), "- new\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_apply -v`
Expected: FAIL — `ImportError` (no `apply` module).

- [ ] **Step 3: Implement `logseqlib/apply.py`**

```python
# logseq/scripts/logseqlib/apply.py
"""Safe multi-file changeset application: diff, backup, git guard, atomic writes."""
import difflib
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class ApplyError(Exception):
    pass


@dataclass
class Change:
    path: Path
    new_content: str | None  # None = delete


def _relpath(graph: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(graph.resolve()))
    except ValueError:
        raise ApplyError(f"path outside graph: {path}") from None


def diff_changeset(graph: Path, changes: list) -> str:
    chunks = []
    for ch in changes:
        rel = _relpath(graph, ch.path)
        old = ch.path.read_text() if ch.path.is_file() else ""
        new = ch.new_content if ch.new_content is not None else ""
        diff = difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}")
        chunks.append("".join(diff))
    return "\n".join(c for c in chunks if c)


def backup(graph: Path, changes: list, now_stamp: str):
    bdir = graph / "logseq" / ".backups" / now_stamp
    backed_any = False
    for ch in changes:
        rel = _relpath(graph, ch.path)
        if ch.path.is_file():
            dest = bdir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ch.path, dest)
            backed_any = True
    return bdir if backed_any else None


def git_is_dirty(graph: Path):
    if not (graph / ".git").exists():
        return None
    try:
        r = subprocess.run(["git", "-C", str(graph), "status", "--porcelain"],
                           capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(r.stdout.strip())


def apply_changeset(graph: Path, changes: list, now_stamp: str,
                    dry_run: bool = False, force: bool = False) -> dict:
    rels = [_relpath(graph, ch.path) for ch in changes]  # validates all paths
    diff = diff_changeset(graph, changes)
    if dry_run:
        return {"dry_run": True, "diff": diff, "files": rels}
    if git_is_dirty(graph) and not force:
        raise ApplyError("graph git tree is dirty; commit/stash or pass force")
    bdir = backup(graph, changes, now_stamp)
    for ch in changes:
        if ch.new_content is None:
            if ch.path.is_file():
                ch.path.unlink()
            continue
        ch.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = ch.path.with_suffix(ch.path.suffix + ".tmp")
        tmp.write_text(ch.new_content)
        os.replace(tmp, ch.path)
    return {"applied": rels, "backup": str(bdir) if bdir else None,
            "diff": diff}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_apply -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_apply.py
git add logseq/scripts/logseqlib/apply.py tests/test_logseq_apply.py
git commit -m "feat(logseq): safe changeset application with backup and git guard"
```

---

### Task 8: `logseqlib/refactor.py` — rename-refs + merge changeset builders

**Files:**
- Create: `logseq/scripts/logseqlib/refactor.py`
- Test: `tests/test_logseq_refactor.py`

**Interfaces:**
- Consumes: `scan.Index`, `scan.LINK_RE` (Task 6); `apply.Change` (Task 7); `page.page_filename` (Task 4).
- Produces (both return `list[Change]` — callers hand them to `apply.apply_changeset`):
  - `def rename_refs(index, old: str, new: str) -> list[Change]` — rewrite `[[old]]` → `[[new]]` and `#old` → `#new` in every page containing them. Matching is case-INSENSITIVE on the old name (that is what makes it usable for case-conflict fixes); replacement text is exactly `new`. Only whole link/tag targets match — `[[old-timer]]` and `#golden` must NOT match `old`.
  - `def merge_pages(index, source: str, target: str, merged_content: str) -> list[Change]` — target page's file gets `merged_content` verbatim; source page's file is deleted (`new_content=None`); plus `rename_refs(index, source, target)` over all OTHER pages (the source page itself is being deleted; the target's rewrite must apply to `merged_content`, so `merge_pages` runs the same substitution on `merged_content` before emitting it). Raises `KeyError` if source or target is not in the index.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_refactor.py`:

```python
# tests/test_logseq_refactor.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import refactor, scan  # noqa: E402


def build_graph(td: str) -> Path:
    g = Path(td)
    (g / "pages").mkdir()
    (g / "journals").mkdir()
    (g / "logseq").mkdir()
    (g / "pages" / "Foo.md").write_text("- the foo page\n")
    (g / "pages" / "Bar.md").write_text(
        "- see [[foo]] and [[Foo]] but not [[foo-timer]]\n- tag #foo here\n")
    (g / "pages" / "Baz.md").write_text("- links [[Bar]]\n")
    return g


class TestRenameRefs(unittest.TestCase):
    def test_case_insensitive_whole_target_only(self):
        with tempfile.TemporaryDirectory() as td:
            g = build_graph(td)
            index = scan.scan_graph(g)
            changes = refactor.rename_refs(index, "foo", "Food Court")
            by_rel = {str(c.path.relative_to(g)): c.new_content
                      for c in changes}
            self.assertEqual(
                by_rel["pages/Bar.md"],
                "- see [[Food Court]] and [[Food Court]] but not "
                "[[foo-timer]]\n- tag #Food Court here\n")
            self.assertNotIn("pages/Baz.md", by_rel)  # untouched pages omitted

    def test_no_matches_no_changes(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            self.assertEqual(refactor.rename_refs(index, "nothere", "x"), [])


class TestMergePages(unittest.TestCase):
    def test_merge_deletes_source_rewrites_refs(self):
        with tempfile.TemporaryDirectory() as td:
            g = build_graph(td)
            index = scan.scan_graph(g)
            merged = "- combined\n- from [[foo]]\n"
            changes = refactor.merge_pages(index, "Foo", "Bar", merged)
            by_rel = {str(c.path.relative_to(g)): c.new_content
                      for c in changes}
            self.assertIsNone(by_rel["pages/Foo.md"])  # delete
            self.assertEqual(by_rel["pages/Bar.md"],
                             "- combined\n- from [[Bar]]\n")

    def test_unknown_page_raises(self):
        with tempfile.TemporaryDirectory() as td:
            index = scan.scan_graph(build_graph(td))
            with self.assertRaises(KeyError):
                refactor.merge_pages(index, "Nope", "Bar", "- x\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_refactor -v`
Expected: FAIL — `ImportError` (no `refactor` module).

- [ ] **Step 3: Implement `logseqlib/refactor.py`**

```python
# logseq/scripts/logseqlib/refactor.py
"""Changeset builders for reference renames and page merges."""
import re

from .apply import Change


def _substitute(text: str, old: str, new: str) -> str:
    link = re.compile(r"\[\[" + re.escape(old) + r"\]\]", re.IGNORECASE)
    tag = re.compile(r"(?<!\S)#" + re.escape(old) + r"(?![\w/-])",
                     re.IGNORECASE)
    text = link.sub(f"[[{new}]]", text)
    return tag.sub(f"#{new}", text)


def rename_refs(index, old: str, new: str) -> list:
    changes = []
    for info in index.pages.values():
        text = info.path.read_text()
        replaced = _substitute(text, old, new)
        if replaced != text:
            changes.append(Change(info.path, replaced))
    return changes


def merge_pages(index, source: str, target: str, merged_content: str) -> list:
    src = index.pages[source.lower()]
    tgt = index.pages[target.lower()]
    changes = [
        Change(tgt.path, _substitute(merged_content, source, target)),
        Change(src.path, None),
    ]
    for ch in rename_refs(index, source, target):
        if ch.path not in (src.path, tgt.path):
            changes.append(ch)
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_refactor -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_refactor.py
git add logseq/scripts/logseqlib/refactor.py tests/test_logseq_refactor.py
git commit -m "feat(logseq): rename-refs and merge changeset builders"
```

---

### Task 9: `logseqlib/convert.py` — Obsidian note conversion

**Files:**
- Create: `logseq/scripts/logseqlib/convert.py`
- Test: `tests/test_logseq_convert.py`

**Interfaces:**
- Consumes: nothing (pure text transformation).
- Produces:
  - `@dataclass ConvertResult: content: str; warnings: list[str]; assets: list[str]` — `assets` are vault-relative paths referenced by the note (to be copied in Task 10).
  - `def convert_note(text: str, title: str) -> ConvertResult`
  - `ADMONITIONS: dict[str, str]` — `{"note": "NOTE", "warning": "WARNING", "tip": "TIP", "important": "IMPORTANT", "caution": "CAUTION"}`
  - `ASSET_EXTS: set[str]` — `{".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}`

Conversion rules (spec §2 `convert`):
1. **Frontmatter** (`---` fenced YAML at top): simple `key: value` lines → `key:: value` pre-lines. Inline lists `[a, b]` → `a, b`. Indented list items under a key are joined with `, `. Any other nesting → warning `frontmatter key '<k>' skipped (nested value)`, key dropped.
2. **Headings** `## H` → their own block `- ## H`.
3. **Lists**: `-`/`*` items become blocks at their indent depth (2 spaces or 1 tab = 1 level). `1.`-style items become plain blocks (marker dropped) + one warning `numbered list flattened` per note.
4. **Code fences**: the whole fence is ONE block — bullet line is `- ```lang`, remaining fence lines (through closing ```) are continuation lines prefixed with two spaces.
5. **Blockquotes**: a `> …` run is one block `- > first` with following quote lines as two-space continuations. **Callout** first-line `> [!type] Title…` with a known type maps to `- #+BEGIN_{ADMONITIONS[type]}` block: Title and body lines as continuations, closing `#+END_…` continuation; unknown type → warning + plain blockquote treatment.
6. **Paragraphs** (contiguous prose lines) → one block: first line after `- `, rest as two-space continuations. Blank lines separate blocks.
7. **Embeds/assets**: `![[Note Name]]` → `{{embed [[Note Name]]}}`; `![[file.png]]` (asset extension) → `![file.png](../assets/file.png)` + record asset; `![alt](rel/path.png)` (non-URL) → `![alt](../assets/path.png)` + record asset `rel/path.png`. URLs (`http…`) untouched.
8. `[[wikilinks]]` and `#tags` pass through verbatim.
9. Output always ends with a single trailing newline; frontmatter properties (if any) are followed by one blank line before the first block.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_convert.py`:

```python
# tests/test_logseq_convert.py
import sys
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import convert as cv  # noqa: E402


class TestFrontmatter(unittest.TestCase):
    def test_simple_and_inline_list(self):
        r = cv.convert_note("---\ntitle: My Note\ntags: [a, b]\n---\nBody.\n",
                            "My Note")
        self.assertEqual(r.content,
                         "title:: My Note\ntags:: a, b\n\n- Body.\n")
        self.assertEqual(r.warnings, [])

    def test_nested_value_warns_and_drops(self):
        r = cv.convert_note("---\nmeta:\n  deep: 1\n---\nBody.\n", "t")
        self.assertTrue(any("meta" in w for w in r.warnings))
        self.assertNotIn("meta", r.content)


class TestBody(unittest.TestCase):
    def test_paragraphs_and_headings(self):
        r = cv.convert_note("# Head\n\nPara one\nstill one\n\nPara two\n", "t")
        self.assertEqual(r.content,
                         "- # Head\n- Para one\n  still one\n- Para two\n")

    def test_lists_keep_nesting(self):
        r = cv.convert_note("- a\n  - a1\n- b\n", "t")
        self.assertEqual(r.content, "- a\n  - a1\n- b\n")

    def test_numbered_list_flattens_with_warning(self):
        r = cv.convert_note("1. one\n2. two\n", "t")
        self.assertEqual(r.content, "- one\n- two\n")
        self.assertTrue(any("numbered" in w for w in r.warnings))

    def test_code_fence_single_block(self):
        r = cv.convert_note("```python\nx = 1\n```\n", "t")
        self.assertEqual(r.content, "- ```python\n  x = 1\n  ```\n")

    def test_callout_known_type(self):
        r = cv.convert_note("> [!note] Heads up\n> body line\n", "t")
        self.assertEqual(r.content,
                         "- #+BEGIN_NOTE\n  Heads up\n  body line\n"
                         "  #+END_NOTE\n")

    def test_callout_unknown_type_warns(self):
        r = cv.convert_note("> [!zany] eh\n", "t")
        self.assertTrue(any("zany" in w for w in r.warnings))
        self.assertIn("- > [!zany] eh", r.content)

    def test_plain_blockquote(self):
        r = cv.convert_note("> quoted\n> more\n", "t")
        self.assertEqual(r.content, "- > quoted\n  > more\n")


class TestEmbedsAssets(unittest.TestCase):
    def test_note_embed(self):
        r = cv.convert_note("![[Other Note]]\n", "t")
        self.assertEqual(r.content, "- {{embed [[Other Note]]}}\n")
        self.assertEqual(r.assets, [])

    def test_asset_embed_and_md_image(self):
        r = cv.convert_note("![[shot.png]]\n\n![alt](img/pic.jpg)\n", "t")
        self.assertIn("- ![shot.png](../assets/shot.png)", r.content)
        self.assertIn("- ![alt](../assets/pic.jpg)", r.content)
        self.assertEqual(sorted(r.assets), ["img/pic.jpg", "shot.png"])

    def test_url_image_untouched(self):
        r = cv.convert_note("![x](https://e.com/a.png)\n", "t")
        self.assertIn("- ![x](https://e.com/a.png)", r.content)
        self.assertEqual(r.assets, [])

    def test_wikilinks_tags_pass_through(self):
        r = cv.convert_note("See [[Page]] #tag\n", "t")
        self.assertEqual(r.content, "- See [[Page]] #tag\n")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_convert -v`
Expected: FAIL — `ImportError` (no `convert` module).

- [ ] **Step 3: Implement `logseqlib/convert.py`**

```python
# logseq/scripts/logseqlib/convert.py
"""Obsidian markdown -> Logseq outline conversion (pure text, no I/O)."""
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

ADMONITIONS = {"note": "NOTE", "warning": "WARNING", "tip": "TIP",
               "important": "IMPORTANT", "caution": "CAUTION"}
ASSET_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".pdf", ".webp"}

EMBED_RE = re.compile(r"!\[\[([^\[\]]+)\]\]")
MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
CALLOUT_RE = re.compile(r"^> \[!(\w+)\]\s*(.*)$")
LIST_RE = re.compile(r"^(?P<ind>[ \t]*)(?P<mark>[-*]|\d+\.) (?P<rest>.*)$")


@dataclass
class ConvertResult:
    content: str
    warnings: list = field(default_factory=list)
    assets: list = field(default_factory=list)


def _frontmatter(lines, warnings):
    """Return (prop_lines, rest_lines)."""
    if not lines or lines[0].strip() != "---":
        return [], lines
    try:
        end = next(i for i in range(1, len(lines))
                   if lines[i].strip() == "---")
    except StopIteration:
        return [], lines
    props, i = [], 1
    while i < end:
        line = lines[i]
        m = re.match(r"^(\w[\w-]*):\s*(.*)$", line)
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        items = []
        j = i + 1
        while j < end and re.match(r"^\s+- ", lines[j]):
            items.append(lines[j].strip()[2:])
            j += 1
        if items and not val:
            val, i = ", ".join(items), j
        elif not val or (j < end and lines[j].startswith((" ", "\t"))
                         and lines[j].strip()):
            warnings.append(f"frontmatter key '{key}' skipped (nested value)")
            while j < end and lines[j].startswith((" ", "\t")):
                j += 1
            i = j
            continue
        else:
            i += 1
        if val.startswith("[") and val.endswith("]"):
            val = ", ".join(p.strip() for p in val[1:-1].split(","))
        props.append(f"{key}:: {val}")
    return props, lines[end + 1:]


def _inline(line, assets):
    def embed(m):
        target = m.group(1)
        if PurePosixPath(target).suffix.lower() in ASSET_EXTS:
            assets.append(target)
            name = PurePosixPath(target).name
            return f"![{name}](../assets/{name})"
        return f"{{{{embed [[{target}]]}}}}"

    def image(m):
        alt, src = m.group(1), m.group(2)
        if src.startswith(("http://", "https://")):
            return m.group(0)
        assets.append(src)
        return f"![{alt}](../assets/{PurePosixPath(src).name})"

    return MD_IMG_RE.sub(image, EMBED_RE.sub(embed, line))


def convert_note(text: str, title: str) -> ConvertResult:
    warnings, assets, out = [], [], []
    props, lines = _frontmatter(text.split("\n"), warnings)
    numbered_warned = False
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            block = [f"- {line}"]
            i += 1
            while i < len(lines):
                block.append(f"  {lines[i]}")
                if lines[i].startswith("```"):
                    i += 1
                    break
                i += 1
            out.extend(block)
            continue
        if line.startswith("> "):
            quote = []
            while i < len(lines) and lines[i].startswith("> "):
                quote.append(lines[i])
                i += 1
            m = CALLOUT_RE.match(quote[0])
            if m and m.group(1).lower() in ADMONITIONS:
                kind = ADMONITIONS[m.group(1).lower()]
                body = ([m.group(2)] if m.group(2) else []) + \
                       [q[2:] for q in quote[1:]]
                out.append(f"- #+BEGIN_{kind}")
                out.extend(f"  {_inline(b, assets)}" for b in body)
                out.append(f"  #+END_{kind}")
            else:
                if m:
                    warnings.append(f"unknown callout type '{m.group(1)}'")
                out.append(f"- {_inline(quote[0], assets)}")
                out.extend(f"  {_inline(q, assets)}" for q in quote[1:])
            continue
        lm = LIST_RE.match(line)
        if lm:
            while i < len(lines) and LIST_RE.match(lines[i]):
                m2 = LIST_RE.match(lines[i])
                ind = m2.group("ind").replace("\t", "  ")
                depth = len(ind) // 2
                if m2.group("mark") not in ("-", "*") and not numbered_warned:
                    warnings.append("numbered list flattened")
                    numbered_warned = True
                out.append("  " * depth + f"- {_inline(m2.group('rest'), assets)}")
                i += 1
            continue
        if line.startswith("#") and line.lstrip("#").startswith(" "):
            out.append(f"- {_inline(line, assets)}")
            i += 1
            continue
        para = []
        while (i < len(lines) and lines[i].strip()
               and not lines[i].startswith(("```", "> "))
               and not LIST_RE.match(lines[i])
               and not (lines[i].startswith("#")
                        and lines[i].lstrip("#").startswith(" "))):
            para.append(_inline(lines[i], assets))
            i += 1
        out.append(f"- {para[0]}")
        out.extend(f"  {p}" for p in para[1:])
    head = "\n".join(props) + "\n\n" if props else ""
    body = "\n".join(out) + "\n" if out else ""
    return ConvertResult(content=head + body, warnings=warnings,
                         assets=assets)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest tests.test_logseq_convert -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_convert.py
git add logseq/scripts/logseqlib/convert.py tests/test_logseq_convert.py
git commit -m "feat(logseq): obsidian note conversion engine"
```

---

### Task 10: `convert.py` import pipeline — plan, collisions, hash-skip, assets

**Files:**
- Modify: `logseq/scripts/logseqlib/convert.py` (append)
- Test: `tests/test_logseq_import.py`

**Interfaces:**
- Consumes: `convert_note` (Task 9); `apply.Change` (Task 7); `page.page_filename`, `page.parse`, `page.page_properties` (Tasks 3–4).
- Produces:
  - `@dataclass NotePlan: source: Path; page_name: str; target: Path; status: str; warnings: list[str]; assets: list[str]; content: str | None` — `status ∈ {"new", "changed", "unchanged", "collision"}`; `content` is the converted page text (properties `imported-from::`/`import-hash::` + blank line + converted body), None for `unchanged`/`collision`.
  - `def source_hash(text: str) -> str` — `hashlib.sha256(text.encode()).hexdigest()[:16]`.
  - `def plan_import(vault: Path, graph: Path, scope: Path | None = None) -> list[NotePlan]` — scope None → whole vault; a file → that note; a dir → `rglob("*.md")` under it. Skips `.obsidian/` and `.trash/`. Page name = vault-relative path without `.md`, `/`-joined (folders become Logseq namespaces). Status logic:
    - target file absent → `new`
    - target exists, its `import-hash::` page property == hash of the CURRENT source → `unchanged`
    - target exists with a DIFFERENT `import-hash::` → `changed` (re-import overwrites)
    - target exists with NO `import-hash::` (a native Logseq page) → `collision` (never overwrite; user resolves)
  - `def import_changes(plans: list[NotePlan]) -> list` — `apply.Change(target, content)` for every plan with status `new`/`changed`.
  - `def asset_copies(vault: Path, graph: Path, plans: list[NotePlan]) -> list[tuple[Path, Path]]` — `(src, dest)` pairs for every referenced asset that exists in the vault (searched as vault-relative path first, then by filename anywhere in the vault); dest `graph/assets/<basename>`; a missing asset becomes a warning on its plan; a dest that already exists with identical bytes is skipped, different bytes → dest name gets `-<hash8>` suffix before the extension.
  - `def copy_assets(pairs: list[tuple[Path, Path]]) -> list[str]` — performs the copies (`shutil.copy2`, mkdir parents), returns dest strs.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_import.py`:

```python
# tests/test_logseq_import.py
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "logseq" / "scripts"))

from logseqlib import convert as cv  # noqa: E402


def build(td: str) -> tuple[Path, Path]:
    root = Path(td)
    vault = root / "vault"
    (vault / "sub").mkdir(parents=True)
    (vault / ".obsidian").mkdir()
    (vault / "Simple.md").write_text("Hello\n")
    (vault / "sub" / "Deep.md").write_text("Deep note ![[pic.png]]\n")
    (vault / "pic.png").write_bytes(b"PNG")
    (vault / ".obsidian" / "junk.md").write_text("skip me\n")
    graph = root / "graph"
    (graph / "pages").mkdir(parents=True)
    (graph / "logseq").mkdir()
    (graph / "assets").mkdir()
    return vault, graph


class TestPlanImport(unittest.TestCase):
    def test_statuses_and_naming(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            src_hash = cv.source_hash((vault / "Simple.md").read_text())
            # pre-existing native page -> collision
            (graph / "pages" / "sub%2FDeep.md").write_text("- native\n")
            plans = {p.page_name: p for p in cv.plan_import(vault, graph)}
            self.assertEqual(plans["Simple"].status, "new")
            self.assertIn(f"import-hash:: {src_hash}",
                          plans["Simple"].content)
            self.assertIn("imported-from:: Simple.md", plans["Simple"].content)
            self.assertEqual(plans["sub/Deep"].status, "collision")
            self.assertNotIn(".obsidian/junk", plans)

    def test_unchanged_and_changed(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            plans = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            cv_changes = cv.import_changes(plans)
            for ch in cv_changes:
                ch.path.parent.mkdir(parents=True, exist_ok=True)
                ch.path.write_text(ch.new_content)
            again = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            self.assertEqual(again[0].status, "unchanged")
            (vault / "Simple.md").write_text("Hello edited\n")
            third = cv.plan_import(vault, graph, scope=vault / "Simple.md")
            self.assertEqual(third[0].status, "changed")

    def test_scope_dir(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            plans = cv.plan_import(vault, graph, scope=vault / "sub")
            self.assertEqual([p.page_name for p in plans], ["sub/Deep"])


class TestAssets(unittest.TestCase):
    def test_asset_copy_pairs_and_missing(self):
        with tempfile.TemporaryDirectory() as td:
            vault, graph = build(td)
            (vault / "sub" / "Gone.md").write_text("![[nope.png]]\n")
            plans = cv.plan_import(vault, graph, scope=vault / "sub")
            pairs = cv.asset_copies(vault, graph, plans)
            self.assertEqual(pairs, [(vault / "pic.png",
                                      graph / "assets" / "pic.png")])
            gone = next(p for p in plans if p.page_name == "sub/Gone")
            self.assertTrue(any("nope.png" in w for w in gone.warnings))
            dests = cv.copy_assets(pairs)
            self.assertEqual((graph / "assets" / "pic.png").read_bytes(),
                             b"PNG")
            self.assertEqual(dests, [str(graph / "assets" / "pic.png")])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_import -v`
Expected: FAIL — `AttributeError` on `plan_import`.

- [ ] **Step 3: Implement (append to `convert.py`)**

Add imports at top of file: `import hashlib`, `import shutil`, `from pathlib import Path`, `from . import page as pg`.

```python
# --- import pipeline (Task 10) ---
@dataclass
class NotePlan:
    source: Path
    page_name: str
    target: Path
    status: str
    warnings: list = field(default_factory=list)
    assets: list = field(default_factory=list)
    content: str | None = None


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


SKIP_DIRS = {".obsidian", ".trash"}


def _vault_notes(vault: Path, scope: Path | None):
    if scope and scope.is_file():
        return [scope]
    base = scope if scope else vault
    return [f for f in sorted(base.rglob("*.md"))
            if not (set(f.relative_to(vault).parts) & SKIP_DIRS)]


def _existing_import_hash(target: Path) -> str | None:
    """None if page absent; '' if present without import-hash (native page)."""
    if not target.is_file():
        return None
    try:
        props = pg.page_properties(pg.parse(target.read_text()))
    except pg.PageParseError:
        return ""
    return props.get("import-hash", "")


def plan_import(vault: Path, graph: Path, scope: Path | None = None):
    plans = []
    for src in _vault_notes(vault, scope):
        rel = src.relative_to(vault)
        page_name = str(rel.with_suffix("")).replace("\\", "/")
        target = graph / "pages" / pg.page_filename(page_name)
        text = src.read_text()
        h = source_hash(text)
        existing = _existing_import_hash(target)
        if existing is None:
            status = "new"
        elif existing == h:
            status = "unchanged"
        elif existing == "":
            status = "collision"
        else:
            status = "changed"
        plan = NotePlan(source=src, page_name=page_name, target=target,
                        status=status)
        if status in ("new", "changed"):
            r = convert_note(text, page_name)
            plan.warnings = r.warnings
            plan.assets = r.assets
            plan.content = (f"imported-from:: {rel}\n"
                            f"import-hash:: {h}\n\n{r.content}")
        plans.append(plan)
    return plans


def import_changes(plans):
    from .apply import Change
    return [Change(p.target, p.content) for p in plans
            if p.status in ("new", "changed")]


def _find_asset(vault: Path, ref: str) -> Path | None:
    direct = vault / ref
    if direct.is_file():
        return direct
    name = PurePosixPath(ref).name
    hits = [f for f in vault.rglob(name)
            if not (set(f.relative_to(vault).parts) & SKIP_DIRS)]
    return hits[0] if hits else None


def asset_copies(vault: Path, graph: Path, plans):
    pairs, seen = [], set()
    for plan in plans:
        for ref in plan.assets:
            src = _find_asset(vault, ref)
            if src is None:
                plan.warnings.append(f"asset not found in vault: {ref}")
                continue
            dest = graph / "assets" / src.name
            if dest.exists() and dest.read_bytes() != src.read_bytes():
                h8 = hashlib.sha256(src.read_bytes()).hexdigest()[:8]
                dest = dest.with_name(f"{dest.stem}-{h8}{dest.suffix}")
            if dest.exists() or (src, dest) in seen:
                continue
            seen.add((src, dest))
            pairs.append((src, dest))
    return pairs


def copy_assets(pairs):
    out = []
    for src, dest in pairs:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        out.append(str(dest))
    return out
```

- [ ] **Step 4: Run tests — convert + import modules**

Run: `python3 -m unittest tests.test_logseq_convert tests.test_logseq_import -v`
Expected: all PASS.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_import.py
git add logseq/scripts/logseqlib/convert.py tests/test_logseq_import.py
git commit -m "feat(logseq): obsidian import pipeline with collision and hash-skip"
```

---

### Task 11: `logseq-cli.py` — argparse dispatch over the library

**Files:**
- Modify: `logseq/scripts/logseq-cli.py` (replace the Task 1 placeholder entirely)
- Test: `tests/test_logseq_cli.py`

**Interfaces:**
- Consumes: everything produced by Tasks 2–10 (exact names as specified there).
- Produces: `def main(argv: list[str] | None = None) -> int` — importable for tests (`sys.path` trick + `importlib` won't work on a hyphenated filename; tests load it via `importlib.util.spec_from_file_location("logseq_cli", path)`). One JSON value on stdout per invocation; `{"error": "..."}` + exit 1 on any `ConfigError`/`ApplyError`/`PageParseError`/`FileExistsError`/`KeyError`/`OSError`.

Subcommands (all accept `--graph NAME` and `--config PATH` where relevant; `--config` exists so tests and unusual setups can point at a non-default config file):

| Command | Args | Behavior / stdout JSON |
|---|---|---|
| `resolve` | `[--write-config]` | `{"name", "path", "source", "api_up": bool, "obsidian_vault"}`; `--write-config` persists a discovered graph via `config.write_config` |
| `append` | `--journal \| --page NAME`, `--text TEXT`, `[--date YYYY-MM-DD]` | result of `api.append_to_journal` / `api.append_to_page` (`--date` defaults to today) |
| `create-page` | `--page NAME`, `--text TEXT \| --content-file F` | result of `api.create_page` |
| `scan` | | `{"pages": {name: {"path", "is_journal", "links", "tags", "properties", "parse_error"}}}` (sets → sorted lists) |
| `backlinks` | `--page NAME` | `{"page": NAME, "backlinks": [names]}` |
| `lint` | `[--types t1,t2]` | `{"findings": [...]}` filtered to the requested types |
| `rename-refs` | `--old X --new Y [--dry-run] [--force]` | result of `apply.apply_changeset` over `refactor.rename_refs` |
| `merge` | `--source A --target B --content-file F [--dry-run] [--force]` | result of `apply_changeset` over `refactor.merge_pages` |
| `apply` | `--changeset-file F [--dry-run] [--force]` | generic escape hatch for restructure ops: F is JSON `{"changes": [{"path": "<graph-relative>", "content": "..." \| null}]}` |
| `convert-plan` | `[--vault V] [--scope PATH]` | `{"plans": [{"source", "page_name", "target", "status", "warnings", "assets"}]}` (content omitted — it goes through `convert-import`) |
| `convert-import` | `[--vault V] [--scope PATH] [--dry-run] [--force]` | `apply_changeset` result + `{"assets_copied": [...], "skipped": {"unchanged": n, "collision": [page_names]}}`; assets copied only when not `--dry-run` |

`--vault` falls back to `resolved.obsidian_vault`; neither present → error.

- [ ] **Step 1: Write the failing tests**

`tests/test_logseq_cli.py`:

```python
# tests/test_logseq_cli.py
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "logseq" / "scripts"))

spec = importlib.util.spec_from_file_location(
    "logseq_cli", ROOT / "logseq" / "scripts" / "logseq-cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

from logseqlib import api  # noqa: E402


def run(argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli.main(argv)
    return code, json.loads(buf.getvalue())


def setup_env(td: str):
    root = Path(td)
    g = root / "graph"
    for d in ("pages", "journals", "logseq"):
        (g / d).mkdir(parents=True)
    (g / "pages" / "Foo.md").write_text("- see [[Bar]]\n")
    (g / "pages" / "Bar.md").write_text("- hi\n")
    cfgp = root / "config.json"
    cfgp.write_text(json.dumps({
        "graphs": {"main": {"path": str(g)}},
        "default_graph": "main",
        "api": {"url": "http://127.0.0.1:1", "token_env": "NO_SUCH_TOKEN"},
    }))
    return g, cfgp


class TestCli(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.g, self.cfgp = setup_env(self.td.name)
        # no token in env -> every API attempt raises ApiUnavailable
        patcher = mock.patch.dict("os.environ", {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.td.cleanup)

    def _run(self, *args):
        return run([*args, "--config", str(self.cfgp)])

    def test_resolve(self):
        code, out = self._run("resolve")
        self.assertEqual(code, 0)
        self.assertEqual(out["name"], "main")
        self.assertEqual(out["path"], str(self.g))
        self.assertFalse(out["api_up"])

    def test_append_journal_files_fallback(self):
        code, out = self._run("append", "--journal", "--text", "note",
                              "--date", "2026-07-17")
        self.assertEqual(code, 0)
        self.assertEqual(out["via"], "files")
        f = self.g / "journals" / "2026_07_17.md"
        self.assertEqual(f.read_text(), "- note\n")

    def test_lint_and_scan(self):
        code, out = self._run("lint", "--types", "orphan")
        self.assertEqual(code, 0)
        self.assertTrue(all(f["type"] == "orphan" for f in out["findings"]))
        code, out = self._run("scan")
        self.assertIn("foo", out["pages"])
        self.assertEqual(out["pages"]["foo"]["links"], ["Bar"])

    def test_rename_refs_dry_then_apply(self):
        code, out = self._run("rename-refs", "--old", "Bar", "--new", "Baz",
                              "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(out["dry_run"])
        self.assertEqual((self.g / "pages" / "Foo.md").read_text(),
                         "- see [[Bar]]\n")
        code, out = self._run("rename-refs", "--old", "Bar", "--new", "Baz")
        self.assertEqual(code, 0)
        self.assertEqual((self.g / "pages" / "Foo.md").read_text(),
                         "- see [[Baz]]\n")

    def test_error_is_json_exit_1(self):
        code, out = self._run("merge", "--source", "Nope", "--target", "Bar",
                              "--content-file", "/dev/null")
        self.assertEqual(code, 1)
        self.assertIn("error", out)

    def test_convert_plan_and_import(self):
        vault = Path(self.td.name) / "vault"
        vault.mkdir()
        (vault / "Note.md").write_text("Hello\n")
        code, out = self._run("convert-plan", "--vault", str(vault))
        self.assertEqual(code, 0)
        self.assertEqual(out["plans"][0]["status"], "new")
        code, out = self._run("convert-import", "--vault", str(vault))
        self.assertEqual(code, 0)
        target = self.g / "pages" / "Note.md"
        self.assertIn("- Hello", target.read_text())
        code, out = self._run("convert-import", "--vault", str(vault))
        self.assertEqual(out["skipped"]["unchanged"], 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m unittest tests.test_logseq_cli -v`
Expected: FAIL — the placeholder script raises `SystemExit` at import time.

- [ ] **Step 3: Implement `logseq/scripts/logseq-cli.py`**

```python
#!/usr/bin/env python3
"""CLI over logseqlib. One JSON value per invocation; errors -> {"error"} + rc 1."""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from logseqlib import api, apply as ap, config as cfg  # noqa: E402
from logseqlib import convert as cv, page as pg, refactor, scan  # noqa: E402


def _stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ")


def _resolve(args):
    return cfg.resolve(graph=args.graph,
                       config_path=Path(args.config) if args.config
                       else cfg.CONFIG_PATH)


def cmd_resolve(args):
    r = _resolve(args)
    if args.write_config and r.source == "discovered":
        cfg.write_config(r, config_path=Path(args.config) if args.config
                         else cfg.CONFIG_PATH)
    return {"name": r.name, "path": str(r.path), "source": r.source,
            "api_up": api.probe(r),
            "obsidian_vault": str(r.obsidian_vault) if r.obsidian_vault
            else None}


def cmd_append(args):
    r = _resolve(args)
    if args.journal:
        date = args.date or datetime.date.today().isoformat()
        return api.append_to_journal(r, args.text, date)
    return api.append_to_page(r, args.page, args.text)


def cmd_create_page(args):
    r = _resolve(args)
    content = (Path(args.content_file).read_text() if args.content_file
               else args.text)
    return api.create_page(r, args.page, content)


def cmd_scan(args):
    index = scan.scan_graph(_resolve(args).path)
    return {"pages": {k: {"path": str(v.path), "is_journal": v.is_journal,
                          "links": sorted(v.links), "tags": sorted(v.tags),
                          "properties": v.properties,
                          "parse_error": v.parse_error}
                      for k, v in sorted(index.pages.items())}}


def cmd_backlinks(args):
    index = scan.scan_graph(_resolve(args).path)
    return {"page": args.page,
            "backlinks": sorted(scan.backlinks(index, args.page))}


def cmd_lint(args):
    findings = scan.lint_all(scan.scan_graph(_resolve(args).path))
    if args.types:
        wanted = set(args.types.split(","))
        findings = [f for f in findings if f["type"] in wanted]
    return {"findings": findings}


def _apply(graph, changes, args):
    return ap.apply_changeset(graph, changes, _stamp(),
                              dry_run=args.dry_run, force=args.force)


def cmd_rename_refs(args):
    r = _resolve(args)
    index = scan.scan_graph(r.path)
    return _apply(r.path, refactor.rename_refs(index, args.old, args.new),
                  args)


def cmd_merge(args):
    r = _resolve(args)
    index = scan.scan_graph(r.path)
    merged = Path(args.content_file).read_text()
    return _apply(r.path,
                  refactor.merge_pages(index, args.source, args.target,
                                       merged), args)


def cmd_apply(args):
    r = _resolve(args)
    data = json.loads(Path(args.changeset_file).read_text())
    changes = [ap.Change(r.path / c["path"], c["content"])
               for c in data["changes"]]
    return _apply(r.path, changes, args)


def _vault(args, r):
    if args.vault:
        return Path(args.vault)
    if r.obsidian_vault:
        return r.obsidian_vault
    raise cfg.ConfigError("no Obsidian vault: pass --vault or set "
                          "obsidian_vault in the config")


def cmd_convert_plan(args):
    r = _resolve(args)
    vault = _vault(args, r)
    scope = Path(args.scope) if args.scope else None
    plans = cv.plan_import(vault, r.path, scope)
    return {"plans": [{"source": str(p.source), "page_name": p.page_name,
                       "target": str(p.target), "status": p.status,
                       "warnings": p.warnings, "assets": p.assets}
                      for p in plans]}


def cmd_convert_import(args):
    r = _resolve(args)
    vault = _vault(args, r)
    scope = Path(args.scope) if args.scope else None
    plans = cv.plan_import(vault, r.path, scope)
    result = _apply(r.path, cv.import_changes(plans), args)
    copied = []
    if not args.dry_run:
        copied = cv.copy_assets(cv.asset_copies(vault, r.path, plans))
    result["assets_copied"] = copied
    result["skipped"] = {
        "unchanged": sum(1 for p in plans if p.status == "unchanged"),
        "collision": [p.page_name for p in plans if p.status == "collision"],
    }
    return result


def main(argv=None):
    top = argparse.ArgumentParser(prog="logseq-cli")
    top.add_argument("--graph")
    top.add_argument("--config")
    sub = top.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("resolve")
    p.add_argument("--write-config", action="store_true")
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("append")
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--journal", action="store_true")
    m.add_argument("--page")
    p.add_argument("--text", required=True)
    p.add_argument("--date")
    p.set_defaults(fn=cmd_append)

    p = sub.add_parser("create-page")
    p.add_argument("--page", required=True)
    m = p.add_mutually_exclusive_group(required=True)
    m.add_argument("--text")
    m.add_argument("--content-file")
    p.set_defaults(fn=cmd_create_page)

    sub.add_parser("scan").set_defaults(fn=cmd_scan)

    p = sub.add_parser("backlinks")
    p.add_argument("--page", required=True)
    p.set_defaults(fn=cmd_backlinks)

    p = sub.add_parser("lint")
    p.add_argument("--types")
    p.set_defaults(fn=cmd_lint)

    def mutating(name):
        q = sub.add_parser(name)
        q.add_argument("--dry-run", action="store_true")
        q.add_argument("--force", action="store_true")
        return q

    p = mutating("rename-refs")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.set_defaults(fn=cmd_rename_refs)

    p = mutating("merge")
    p.add_argument("--source", required=True)
    p.add_argument("--target", required=True)
    p.add_argument("--content-file", required=True)
    p.set_defaults(fn=cmd_merge)

    p = mutating("apply")
    p.add_argument("--changeset-file", required=True)
    p.set_defaults(fn=cmd_apply)

    p = sub.add_parser("convert-plan")
    p.add_argument("--vault")
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_convert_plan)

    p = mutating("convert-import")
    p.add_argument("--vault")
    p.add_argument("--scope")
    p.set_defaults(fn=cmd_convert_import)

    args = top.parse_args(argv)
    try:
        out = args.fn(args)
        rc = 0
    except (cfg.ConfigError, ap.ApplyError, pg.PageParseError,
            FileExistsError, KeyError, OSError, json.JSONDecodeError) as e:
        out, rc = {"error": str(e)}, 1
    json.dump(out, sys.stdout, indent=2)
    print()
    return rc


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the CLI tests, then the whole logseq suite**

Run: `python3 -m unittest tests.test_logseq_cli -v`
Expected: all PASS.
Run: `python3 -m unittest discover -s tests -p 'test_logseq_*.py' -v`
Expected: every logseq test module PASSES.

- [ ] **Step 5: Lint and commit**

```bash
ruff check logseq/ tests/test_logseq_cli.py
git add logseq/scripts/logseq-cli.py tests/test_logseq_cli.py
git commit -m "feat(logseq): logseq-cli argparse dispatch over logseqlib"
```

---

### Task 12: SKILL.md bodies + README

**Files:**
- Modify: `logseq/skills/capture/SKILL.md`, `logseq/skills/query/SKILL.md`, `logseq/skills/lint/SKILL.md`, `logseq/skills/organize/SKILL.md`, `logseq/skills/from-obsidian/SKILL.md` (replace Task 1 stubs entirely)
- Modify: `README.md` (add plugin section)

**Interfaces:**
- Consumes: the CLI surface exactly as built in Task 11 (`resolve`, `append`, `create-page`, `scan`, `backlinks`, `lint`, `rename-refs`, `merge`, `apply`, `convert-plan`, `convert-import`).
- Produces: user-facing skills. Frontmatter `name:` MUST equal the directory name (verify-marketplace checks it).

Every SKILL.md starts with this shared CLI section (repeat verbatim in each file, after the title):

```markdown
## CLI

All mechanics go through one CLI:

    uv run "${CLAUDE_PLUGIN_ROOT}/scripts/logseq-cli.py" <command> [args...]

`${CLAUDE_PLUGIN_ROOT}` is this plugin's install root. If the variable is not
pre-substituted when you read this file, resolve it yourself: take the
directory containing this SKILL.md and walk up two levels (`skills/<name>/` →
plugin root). The scripts are stdlib-only; if `uv` is unavailable, use
`python3` directly. Below written as `logseq-cli.py` for brevity.

Every command prints one JSON value. `{"error": ...}` + exit 1 means stop and
show the user the message — do not improvise around it.

## Graph resolution

Run `logseq-cli.py resolve` first.
- `"source": "discovered"` → re-run with `--write-config` to persist, tell the user.
- Error mentioning "multiple Logseq graphs" → show the candidate paths, ask
  the user which one, then write `~/.config/logseq-skills/config.json`:
  `{"graphs": {"<name>": {"path": "<chosen>"}}, "default_graph": "<name>",
  "api": {"url": "http://127.0.0.1:12315", "token_env": "LOGSEQ_API_TOKEN"}}`
  and re-run.
- `"api_up": false` is fine — writes fall back to files automatically.
```

- [ ] **Step 1: Write `logseq/skills/capture/SKILL.md`**

```markdown
---
name: capture
version: 1.0.0
description: Capture a note, TODO, or meeting summary into the user's local Logseq graph — today's journal by default, or a named page. Use when the user says "add this to Logseq", "log this in my journal", "note this down in Logseq", or wants a TODO captured.
---

# Logseq Capture

Add user-provided content to the Logseq graph. Judgment (formatting,
destination) is yours; writing is the CLI's.

[SHARED CLI + GRAPH RESOLUTION SECTION — see task preamble, paste verbatim]

## Process

1. Resolve the graph (above).
2. Decide the destination: today's journal unless the user names a page.
3. Format the content as Logseq outline text:
   - Actionable items start with `TODO `. Add `SCHEDULED: <YYYY-MM-DD Day>`
     on a continuation line only when the user gave a date.
   - Multi-line content: first line is the bullet, later lines are
     continuations (the CLI handles indentation).
   - Add `[[links]]` / `#tags` only for names/topics the user actually said.
4. Append — one CLI call per top-level bullet:
   - Journal: `logseq-cli.py append --journal --text "<text>"`
   - Page: `logseq-cli.py append --page "<Page Name>" --text "<text>"`
   - Brand-new page wanted: `logseq-cli.py create-page --page "<Name>" --text "<full outline>"`
5. Report to the user: what was written, where (`target`), and whether it
   went `via: api` (visible in the app immediately) or `via: files`.
```

- [ ] **Step 2: Write `logseq/skills/query/SKILL.md`**

```markdown
---
name: query
version: 1.0.0
description: Answer questions from the user's local Logseq graph — search pages and journals, follow backlinks, surface TODOs and tagged content. Read-only. Use when the user asks "what do my notes say about…", "find in my Logseq", "which pages link to…", or similar.
---

# Logseq Query

Answer from the graph. Read-only — never write during this skill.

[SHARED CLI + GRAPH RESOLUTION SECTION — see task preamble, paste verbatim]

## Strategy — cheapest sufficient tier first

1. **Keyword lookup** → `rg` directly over the graph path from `resolve`:
   `rg -il "<term>" "<graph>/pages" "<graph>/journals"` then read the hits.
2. **Structural questions** (backlinks, orphans, tags, properties) →
   `logseq-cli.py scan` (whole index as JSON) or
   `logseq-cli.py backlinks --page "<Name>"`.
3. **Datalog** — only when `resolve` reported `"api_up": true` AND the
   question needs real graph queries (e.g. all TODOs with a deadline):
   `curl -s -X POST <api_url>/api -H "Authorization: Bearer $LOGSEQ_API_TOKEN"
   -H "Content-Type: application/json"
   -d '{"method":"logseq.DB.datascriptQuery","args":["<datalog>"]}'`

## Answering

- Cite pages as `[[Page Name]]` plus the file path.
- Journal hits: cite the date.
- Quote the relevant blocks rather than paraphrasing when the user asks
  "what did I write".
- If nothing is found, say so and name the strategies tried.
```

- [ ] **Step 3: Write `logseq/skills/lint/SKILL.md`**

```markdown
---
name: lint
version: 1.0.0
description: Find consistency problems in the user's local Logseq graph — broken links, case-conflicting link spellings, orphan pages, near-duplicate page names, unparseable pages — and apply chosen fixes. Use when the user asks to lint, clean up, or check their Logseq graph for consistency.
---

# Logseq Lint

Scan for findings; the user chooses what to fix; every fix shows a dry-run
diff first. Nothing auto-applies.

[SHARED CLI + GRAPH RESOLUTION SECTION — see task preamble, paste verbatim]

## Process

1. Resolve, then `logseq-cli.py lint` (optionally `--types broken-link,orphan,...`).
2. Present findings grouped by type, with counts. Explain what each type
   means; recommend which groups are safe to fix mechanically:
   - `case-conflict` → pick the canonical spelling (prefer an existing page's
     actual name), fix via `rename-refs`.
   - `broken-link` → per link: rename to an existing page (`rename-refs`) if
     it is clearly a typo/rename, else leave (a link to a future page is
     normal in Logseq — say so).
   - `unparseable` → show the page and the parse error; fixing the file is a
     manual edit the user must approve; the CLI will never rewrite these.
   - `orphan` / `near-duplicate` → informational; offer the organize skill
     for merges.
3. For each approved mechanical fix:
   `logseq-cli.py rename-refs --old "<X>" --new "<Y>" --dry-run` → show diff
   → on approval re-run without `--dry-run`.
4. Dirty-git-tree errors: relay to the user; only pass `--force` if they
   explicitly say to. Backups land in `<graph>/logseq/.backups/<stamp>/` —
   include the path in your report.
```

- [ ] **Step 4: Write `logseq/skills/organize/SKILL.md`**

```markdown
---
name: organize
version: 1.0.0
description: Merge/dedupe and restructure pages in the user's local Logseq graph — combine duplicate topic pages (rewriting inbound links), split overgrown pages, promote journal content into topic pages. Use when the user asks to merge, dedupe, reorganize, restructure, or consolidate Logseq pages.
---

# Logseq Organize

The judgment-heavy skill: you propose content, the CLI applies it safely.
Every operation shows its full plan and diff BEFORE touching files.

[SHARED CLI + GRAPH RESOLUTION SECTION — see task preamble, paste verbatim]

## Safety preamble (both flows)

- If `resolve` said `"api_up": false`, check whether the app is open anyway
  (`pgrep -x Logseq`). If it is, warn the user: rewrites bypass the app —
  they should avoid editing the affected pages in Logseq until done.
- Dirty-git-tree errors from the CLI: relay; `--force` only on explicit
  user say-so. Report the backup path from every applied result.

## Merge flow

1. Candidates: `logseq-cli.py lint --types near-duplicate,case-conflict`,
   plus `backlinks` overlap for pairs the user suspects.
2. Read BOTH page files in full. Propose: surviving title, merged outline
   (deduplicate blocks, keep both pages' unique content, preserve block
   properties), and note that inbound links to the losing name will be
   rewritten.
3. On approval, write the merged outline to a temp file, then:
   `logseq-cli.py merge --source "<Losing>" --target "<Surviving>"
   --content-file <tmp> --dry-run` → show diff → approval → re-run live.

## Restructure flow (split a page / promote journal content)

1. Read the affected pages. Propose the block moves as: which blocks leave
   which page, where they land, what remains.
2. On approval, build the full new content of EVERY affected page and write
   a changeset file: `{"changes": [{"path": "pages/<file>.md", "content":
   "<entire new file>"}, ...]}` (`"content": null` deletes a file). New
   pages that gain content from the move must keep an `[[origin]]` link back
   when context would otherwise be lost.
3. `logseq-cli.py apply --changeset-file <tmp> --dry-run` → show diff →
   approval → re-run live.
```

- [ ] **Step 5: Write `logseq/skills/from-obsidian/SKILL.md`**

```markdown
---
name: from-obsidian
version: 1.0.0
description: Convert and import notes from a local Obsidian vault into the user's Logseq graph — a single note, a folder, or the whole vault. Repeatable; already-imported unchanged notes are skipped. Use when the user asks to transfer, migrate, or import Obsidian notes into Logseq.
---

# Obsidian → Logseq Import

Conversion (prose → outline, frontmatter → properties, embeds/assets) is the
CLI's; scoping, collision decisions, and the final go-ahead are yours + the
user's.

[SHARED CLI + GRAPH RESOLUTION SECTION — see task preamble, paste verbatim]

## Vault resolution

`resolve` reports `obsidian_vault`. If null: ask the user for the vault path
once, add `"obsidian_vault": "<path>"` to
`~/.config/logseq-skills/config.json`, and continue with `--vault "<path>"`.

## Process

1. Scope from the user's request: one note (`--scope <file>`), a folder
   (`--scope <dir>`), or the whole vault (no `--scope`).
2. Plan: `logseq-cli.py convert-plan [--vault V] [--scope P]`. Present as a
   table: counts by status (`new` / `changed` / `unchanged` /
   `collision`), every collision by name, and all conversion warnings
   (nested frontmatter dropped, unknown callouts, missing assets, flattened
   numbered lists).
   - `collision` = a native Logseq page already has that name; it will NOT
     be overwritten. Offer: rename the Obsidian note, or merge manually
     later via the organize skill.
3. Dry run: `logseq-cli.py convert-import ... --dry-run` → show the diff
   (or its size + a sample for large imports).
4. On approval: re-run without `--dry-run`. Assets are copied into
   `<graph>/assets/`.
5. Report: pages imported (new/changed), unchanged skips, collisions left
   for the user, assets copied, backup path if one was made.

Notes are stamped with `imported-from::` and `import-hash::` page
properties — that is what makes re-runs skip unchanged notes. Tell the user
these properties must stay if they want re-import detection.
```

- [ ] **Step 6: Update `README.md`**

After the `## deps` section, add:

```markdown
## logseq

`capture` (add notes/TODOs to today's journal or a page) · `query` (answer
questions from the graph, read-only) · `lint` (broken links, case conflicts,
orphans, near-duplicates) · `organize` (merge/dedupe and restructure pages
with safe changesets) · `from-obsidian` (convert + import an Obsidian vault,
repeatable with hash-skip).
```

Also update the README intro line "Eight plugins" → "Nine plugins".

- [ ] **Step 7: Verify and commit**

Run: `bash scripts/verify-marketplace.sh`
Expected: `FAIL: 0`, logseq listed with all five skills.
Run: `python3 -m unittest discover -s tests -p 'test_logseq_*.py'`
Expected: all PASS (no code changed, sanity only).

```bash
git add logseq/skills README.md
git commit -m "docs(logseq): five skill bodies and README section"
```

---

### Task 13: Final verification

**Files:** none created — verification only (fix anything found, commit fixes).

- [ ] **Step 1: Full test suite** — `python3 -m unittest discover -s tests -v` — EVERY test in the repo passes (bump suites included: proves no cross-contamination).
- [ ] **Step 2: Lint everything new** — `ruff check logseq/ tests/` — clean.
- [ ] **Step 3: Marketplace structure** — `bash scripts/verify-marketplace.sh` — exit 0.
- [ ] **Step 4: CLI smoke test against a throwaway graph** — build a tiny graph in the scratchpad (pages/journals/logseq dirs + one page), point `--config` at a scratch config, run `resolve`, `append --journal`, `lint`, `convert-plan` against a two-note scratch vault; each must return sane JSON and exit 0.
- [ ] **Step 5: Commit any fixes** — `git status` clean or a final `fix(logseq): …` commit.

---

## Plan Self-Review (completed at write time)

- **Spec coverage:** §1 layout/config/discovery → Tasks 1–2; §2 page/api/scan/convert → Tasks 3–6, 9–10 (+ apply/refactor Tasks 7–8 realizing §3 organize and §4 safety); §3 five skills → Task 12 (CLI verbs Task 11); §4 safety/backups/git-guard/dry-run → Task 7 + skill bodies; testing reqs → every task + Task 13. Datalog-for-query is via curl in the query skill (CLI stays minimal) — deliberate.
- **Placeholders:** none; the two inline "correction" notes (Tasks 3, 4) are explicit resolved instructions, not TBDs.
- **Type consistency:** `Resolved` fields, `Change(path, new_content)`, finding dicts `{type, page, detail}`, `NotePlan` statuses, and CLI verb names cross-checked across tasks.






