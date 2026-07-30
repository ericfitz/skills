# Codex Marketplace Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make this repo installable as a plugin marketplace in OpenAI Codex (via the GitHub URL `ericfitz/skills`) while keeping the Claude Code manifests as the single source of truth.

**Architecture:** A generator script reads `.claude-plugin/marketplace.json` and each plugin's `.claude-plugin/plugin.json`, then emits committed Codex-native files: `.agents/plugins/marketplace.json` plus one `.codex-plugin/plugin.json` per plugin. A pytest drift check keeps the generated files in sync; `scripts/verify-marketplace.sh` gains a dynamic plugin count and a drift-check call. Spec: `docs/superpowers/specs/2026-07-30-codex-marketplace-design.md`.

**Tech Stack:** Python 3.11+ stdlib only (no new deps), uv, pytest (unittest-style test classes, matching `tests/test_plugin_structure.py`), ruff, bash.

## Global Constraints

- Python ≥ 3.11; stdlib only for the generator (no new entries in `pyproject.toml`).
- Lint with `uv run ruff check .` — line length 120, rules E/F/W/I/UP/B/SIM/C4/RUF (tests are exempt from E501/E402/I001).
- Run tests with `uv run pytest tests/<file> -q`; full suite `uv run pytest -q` before finishing.
- Test files follow the repo's unittest style: `REPO = Path(__file__).resolve().parents[1]`, `sys.dont_write_bytecode = True`, classes deriving `unittest.TestCase`, `subTest` for per-plugin loops.
- Generated files are never hand-edited; every fix goes into the generator followed by regeneration.
- Generated JSON format: 2-space indent, insertion key order, single trailing newline.
- Commit after each task; stage only files named in the task (never `git add -A`).

---

### Task 1: Generator script with unit tests

**Files:**
- Create: `scripts/gen_codex_manifests.py`
- Test: `tests/test_codex_manifests.py`

**Interfaces:**
- Produces: `gen_codex_manifests.generate(repo: Path) -> dict[Path, str]` mapping each Codex manifest path to rendered JSON text; `gen_codex_manifests.GenerationError(ValueError)`; CLI `uv run scripts/gen_codex_manifests.py [--repo PATH] [--check]` with exit codes 0 = ok, 1 = drift (`--check`), 2 = structural error. Task 2 and Task 3 rely on these exact names and exit codes.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/test_codex_manifests.py`:

```python
# tests/test_codex_manifests.py
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

import gen_codex_manifests as gcm


def build_repo(root: Path, plugins: dict[str, dict], market_entries: list[dict] | None = None) -> Path:
    """Build a minimal fake marketplace repo under root.

    plugins: name -> manifest dict written to <name>/.claude-plugin/plugin.json.
             A manifest of None skips writing plugin.json (missing-manifest case).
             Set "_no_skills" in the manifest to skip creating skills/.
    market_entries: overrides the generated marketplace plugin list.
    """
    entries = []
    for name, manifest in plugins.items():
        plugin_dir = root / name
        (plugin_dir / "skills" / "demo").mkdir(parents=True)
        if manifest is not None:
            no_skills = manifest.pop("_no_skills", False)
            if no_skills:
                import shutil
                shutil.rmtree(plugin_dir / "skills")
            (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
            (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        entries.append({"name": name, "description": "d", "source": f"./{name}", "category": "development"})
    (root / ".claude-plugin").mkdir()
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps({"name": "test-market", "plugins": market_entries if market_entries is not None else entries}),
        encoding="utf-8")
    return root


def manifest(name: str, **overrides) -> dict:
    base = {"name": name, "version": "1.0.0", "description": "does things", "author": {"name": "efitz"}}
    base.update(overrides)
    return base


class TestGenerate(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_happy_path_renders_marketplace_and_plugin_manifests(self):
        build_repo(self.root, {"alpha": manifest("alpha"), "beta": manifest("beta")})
        out = gcm.generate(self.root)
        self.assertEqual(
            set(out),
            {self.root / ".agents" / "plugins" / "marketplace.json",
             self.root / "alpha" / ".codex-plugin" / "plugin.json",
             self.root / "beta" / ".codex-plugin" / "plugin.json"})
        market = json.loads(out[self.root / ".agents" / "plugins" / "marketplace.json"])
        self.assertEqual(market["name"], "test-market")
        self.assertEqual(
            market["plugins"][0],
            {"name": "alpha", "category": "development",
             "source": {"source": "local", "path": "./alpha"}})
        alpha = json.loads(out[self.root / "alpha" / ".codex-plugin" / "plugin.json"])
        self.assertEqual(alpha, {"name": "alpha", "version": "1.0.0", "description": "does things",
                                 "author": {"name": "efitz"}, "skills": "./skills/"})

    def test_rendered_json_is_two_space_indented_with_trailing_newline(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        for content in gcm.generate(self.root).values():
            self.assertTrue(content.endswith("}\n"))
            self.assertIn('\n  "name"', content)

    def test_missing_plugin_manifest_fails(self):
        build_repo(self.root, {"alpha": None})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha.*plugin.json"):
            gcm.generate(self.root)

    def test_missing_skills_dir_fails(self):
        build_repo(self.root, {"alpha": manifest("alpha", _no_skills=True)})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha.*skills"):
            gcm.generate(self.root)

    def test_duplicate_plugin_name_fails(self):
        build_repo(self.root, {"alpha": manifest("alpha")})
        entries = json.loads((self.root / ".claude-plugin" / "marketplace.json").read_text())["plugins"]
        (self.root / ".claude-plugin" / "marketplace.json").write_text(
            json.dumps({"name": "test-market", "plugins": entries + entries}), encoding="utf-8")
        with self.assertRaisesRegex(gcm.GenerationError, "duplicate.*alpha"):
            gcm.generate(self.root)

    def test_name_mismatch_between_marketplace_and_plugin_json_fails(self):
        build_repo(self.root, {"alpha": manifest("omega")})
        with self.assertRaisesRegex(gcm.GenerationError, "alpha"):
            gcm.generate(self.root)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_codex_manifests.py -q`
Expected: collection error — `ModuleNotFoundError: No module named 'gen_codex_manifests'`

- [ ] **Step 3: Write the generator**

Create `scripts/gen_codex_manifests.py`:

```python
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


def generate(repo: Path) -> dict[Path, str]:
    """Map each Codex manifest path to its rendered JSON content."""
    marketplace = json.loads((repo / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    seen: set[str] = set()
    entries: list[dict] = []
    out: dict[Path, str] = {}
    for entry in marketplace["plugins"]:
        name = entry["name"]
        if name in seen:
            raise GenerationError(f"duplicate plugin name in marketplace.json: {name}")
        seen.add(name)
        source = entry["source"]
        if not isinstance(source, str) or not source.startswith("./"):
            raise GenerationError(f"{name}: expected string source './<dir>', got {source!r}")
        plugin_dir = repo / source
        claude_manifest = plugin_dir / ".claude-plugin" / "plugin.json"
        if not claude_manifest.is_file():
            raise GenerationError(f"{name}: missing {source}/.claude-plugin/plugin.json")
        if not (plugin_dir / "skills").is_dir():
            raise GenerationError(f"{name}: missing {source}/skills/ directory")
        pdata = json.loads(claude_manifest.read_text(encoding="utf-8"))
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_codex_manifests.py -q`
Expected: all 6 tests PASS

- [ ] **Step 5: Lint**

Run: `uv run ruff check scripts/gen_codex_manifests.py tests/test_codex_manifests.py`
Expected: no findings (fix any before committing)

- [ ] **Step 6: Commit**

```bash
git add scripts/gen_codex_manifests.py tests/test_codex_manifests.py
git commit -m "feat(codex): generator for Codex-native plugin manifests"
```

---

### Task 2: Generate, commit, and pin the real manifests

**Files:**
- Create (generated): `.agents/plugins/marketplace.json`, `<plugin>/.codex-plugin/plugin.json` for all 12 plugins (loc, security, github, ui, wiki, dev, writing, deps, logseq, cats, profile, itest)
- Modify: `tests/test_codex_manifests.py` (append a real-repo test class)

**Interfaces:**
- Consumes: `gcm.generate(repo)` and the CLI `--check` exit codes from Task 1.
- Produces: committed Codex manifests that Task 3's `--check` call and Task 4's end-to-end run depend on.

- [ ] **Step 1: Append failing real-repo tests**

Append to `tests/test_codex_manifests.py` (module imports from Task 1 already provide `json`, `sys`, `unittest`, `Path`, `REPO`, `gcm`; add `import subprocess` to the import block at the top):

```python
CLAUDE_MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = REPO / ".agents" / "plugins" / "marketplace.json"


class TestCommittedCodexManifests(unittest.TestCase):
    def test_committed_files_match_fresh_regeneration(self):
        for path, content in gcm.generate(REPO).items():
            with self.subTest(path=str(path.relative_to(REPO))):
                self.assertTrue(path.is_file(), f"{path} missing — run scripts/gen_codex_manifests.py")
                self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_marketplace_membership_matches_both_ways(self):
        claude = {p["name"] for p in json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]}
        codex = {p["name"] for p in json.loads(CODEX_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]}
        self.assertEqual(claude, codex)

    def test_codex_plugin_skills_paths_exist(self):
        for entry in json.loads(CODEX_MARKETPLACE.read_text(encoding="utf-8"))["plugins"]:
            plugin_dir = REPO / entry["source"]["path"]
            data = json.loads((plugin_dir / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
            with self.subTest(plugin=entry["name"]):
                self.assertEqual(data["skills"], "./skills/")
                self.assertTrue((plugin_dir / "skills").is_dir())

    def test_check_flag_passes_on_committed_tree(self):
        proc = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "gen_codex_manifests.py"), "--check"],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
```

- [ ] **Step 2: Run tests to verify the new class fails**

Run: `uv run pytest tests/test_codex_manifests.py -q`
Expected: `TestCommittedCodexManifests` fails (generated files don't exist yet); `TestGenerate` still passes

- [ ] **Step 3: Generate the manifests**

Run: `uv run scripts/gen_codex_manifests.py`
Expected: 13 `wrote ...` lines (12 plugin manifests + 1 marketplace). Spot-check `.agents/plugins/marketplace.json` lists all 12 plugins with `{"source": "local", "path": "./<dir>"}` sources.

- [ ] **Step 4: Verify git will track the new files**

Run: `git status --porcelain | grep -E '\.agents|\.codex-plugin' | head -15` and `git check-ignore .agents/plugins/marketplace.json loc/.codex-plugin/plugin.json || echo "not ignored"`
Expected: files show as untracked; `not ignored` printed. If ignored, fix `.gitignore` before proceeding.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all tests pass (including `test_plugin_structure.py`, untouched)

- [ ] **Step 6: Commit**

```bash
git add .agents/plugins/marketplace.json */.codex-plugin/plugin.json tests/test_codex_manifests.py
git commit -m "feat(codex): commit generated Codex marketplace and plugin manifests"
```

---

### Task 3: Fix verify-marketplace.sh (dynamic count + drift check)

**Files:**
- Modify: `scripts/verify-marketplace.sh:30-35` (plugin count) and append a new section before the summary (drift check)

**Interfaces:**
- Consumes: generator CLI `--check` (exit 0 in-sync / 1 drift / 2 structural error) from Task 1.

- [ ] **Step 1: Replace the hardcoded count check**

Replace lines 30–35 (`PLUGIN_COUNT=...` through the closing `fi`) with a comparison against the actual number of plugin directories, so the check no longer goes stale when plugins are added:

```bash
PLUGIN_COUNT=$(python3 -c "import json; print(len(json.load(open('.claude-plugin/marketplace.json'))['plugins']))")
DIR_COUNT=$(ls -d */.claude-plugin/plugin.json 2>/dev/null | wc -l | tr -d ' ')
if [ "$PLUGIN_COUNT" -eq "$DIR_COUNT" ]; then
  ok "marketplace.json has $PLUGIN_COUNT plugin entries, matching $DIR_COUNT plugin dirs"
else
  bad "marketplace.json has $PLUGIN_COUNT plugin entries but $DIR_COUNT plugin dirs have .claude-plugin/plugin.json"
fi
```

- [ ] **Step 2: Add the Codex drift-check section**

Insert immediately before the `# ---------- summary ----------` line:

```bash
# ---------- Codex manifests in sync ----------
hdr "Codex manifests (generated from Claude manifests)"

if python3 scripts/gen_codex_manifests.py --check >/dev/null 2>&1; then
  ok "Codex manifests match a fresh regeneration"
else
  bad "Codex manifests out of sync — run: uv run scripts/gen_codex_manifests.py"
fi
```

- [ ] **Step 3: Run the script to verify it passes**

Run: `bash scripts/verify-marketplace.sh`
Expected: `FAIL: 0`, exit 0. (The per-plugin `PLUGINS` array only covers 9 of 12 plugins — pre-existing staleness, explicitly out of scope per the spec; do not extend it in this task.)

- [ ] **Step 4: Verify the drift check actually catches drift**

```bash
sed -i.bak 's/"skills": ".\/skills\/"/"skills": ".\/skillz\/"/' loc/.codex-plugin/plugin.json
bash scripts/verify-marketplace.sh; echo "exit=$?"
mv loc/.codex-plugin/plugin.json.bak loc/.codex-plugin/plugin.json
bash scripts/verify-marketplace.sh
```

Expected: middle run reports the Codex drift FAIL with exit=1; final run passes clean (backup restored, no `.bak` left behind).

- [ ] **Step 5: Commit**

```bash
git add scripts/verify-marketplace.sh
git commit -m "fix(scripts): dynamic plugin count and Codex drift check in verify-marketplace"
```

---

### Task 4: End-to-end verification in real Codex

No new files; this task validates the manifests against the actual Codex CLI and feeds any rejection back into the generator (never into the generated files by hand). Run inline in the main session (needs GitHub push and possibly interactive auth), not in a subagent.

- [ ] **Step 1: Locate or install the Codex CLI**

`codex` is not on PATH in the working shell, but `~/.codex/` state exists (version ~0.135.0). Try, in order:
1. `zsh -lc 'which codex'` (login shell PATH)
2. `ls /opt/homebrew/bin/codex ~/.local/bin/codex 2>/dev/null` and `npm ls -g --depth=0 2>/dev/null | grep -i codex`
3. Install: `npm install -g @openai/codex` (fallback: `brew install codex`)

Expected: a runnable `codex --version`.

- [ ] **Step 2: Push main to GitHub**

Run: `git push origin main`
This machine requires a physical key touch for SSH; if the push fails because the user is away, do NOT work around it — continue with the local-path fallback in Step 3 and record that the URL-based test is pending the push.

- [ ] **Step 3: Add the marketplace and install a plugin**

Discover exact syntax with `codex --help` / `codex plugin --help` (expected shape, from Codex docs: `/plugin marketplace add`, `/plugin install`, `/reload-plugins`; a non-interactive `codex plugin ...` form may exist). Then:
1. Add marketplace from `ericfitz/skills` (URL form) — or from `/Users/efitz/Projects/skills` (local path) if the push is pending.
2. Install the `loc` plugin.
3. Verify install landed under `~/.codex/plugins/cache/` and the plugin is enabled in `~/.codex/config.toml`.
4. List skills (`/skills` in a Codex session, or inspect the installed tree) and confirm the 7 loc skills appear.

Expected: marketplace registers, `loc` installs, skills visible.

- [ ] **Step 4: Feed back any rejections**

If Codex rejects a manifest field or source shape: change `scripts/gen_codex_manifests.py`, add/adjust a unit test in `tests/test_codex_manifests.py` capturing the corrected shape, regenerate (`uv run scripts/gen_codex_manifests.py`), re-run `uv run pytest -q` and the Codex step, then commit:

```bash
git add scripts/gen_codex_manifests.py tests/test_codex_manifests.py .agents/plugins/marketplace.json */.codex-plugin/plugin.json
git commit -m "fix(codex): adjust generated manifest shape per real Codex behavior"
```

If everything works first try, there is nothing to commit in this task.

- [ ] **Step 5: Record the E2E result**

Note in the final report: which Codex version, URL or local-path add, what was verified, anything pending (e.g. URL test blocked on push).

---

### Task 5: File the full-parity follow-up issue

No repo files; files a GitHub issue. Run inline in the main session.

- [ ] **Step 1: File the issue**

Preferred: invoke the `github:create-issue` skill. It reads `.local/gh-projects.json`, which does not exist in this repo — if the skill cannot proceed without it, fall back to:

```bash
gh issue create --repo ericfitz/skills \
  --title "Rework Claude-specific skill content for full Codex parity" \
  --body "$(cat <<'EOF'
The repo now ships Codex-native marketplace manifests (see
docs/superpowers/specs/2026-07-30-codex-marketplace-design.md). Skills install
and run in Codex, but several rely on Claude Code features with no Codex
equivalent and currently degrade gracefully (Codex executes subagent-dispatch
instructions inline).

Rework for full parity:

- Subagent dispatch: dev (dedupe, sem-annotate reference agents/*.md workers)
  and cats (run references agents/cats-run.md) should gain explicit
  "no-subagent" inline paths for harnesses without a Task tool.
- `allowed-tools` frontmatter (dev/sem-annotate, wiki/verify-doc,
  github/create-issue): ignored by Codex; confirm the skills don't depend on
  tool restriction for correctness.
- Audit remaining SKILL.md files for Claude-only assumptions (Task tool,
  AskUserQuestion, plugin cache paths). `${CLAUDE_PLUGIN_ROOT}` is fine —
  Codex exports it as a compatibility alias.

Acceptance: each affected skill states what to do when subagents/tools are
unavailable, verified by a manual run of one dev and one cats skill in Codex.
EOF
)"
```

Expected: issue URL printed.

- [ ] **Step 2: Record the issue URL in the final report**

---

## Self-Review (completed)

- **Spec coverage:** generated files (Task 2), generator + failure modes + `--check` (Task 1), tests/CI (Tasks 1–2), verify-marketplace.sh fixes (Task 3), E2E (Task 4), follow-up issue (Task 5), out-of-scope items untouched. No gaps.
- **Placeholder scan:** all code steps carry full code; the only discovery step (Codex CLI syntax) lists concrete candidate commands and fallbacks.
- **Type consistency:** `generate(repo: Path) -> dict[Path, str]`, `GenerationError`, and CLI exit codes 0/1/2 are used identically in Tasks 1, 2, and 3.
