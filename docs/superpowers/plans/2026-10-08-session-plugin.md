# Session plugin implementation plan

Spec: `docs/superpowers/specs/2026-10-08-session-plugin-design.md`

## Task 1: scripts and their tests

1. Copy `~/.claude/skills/_lib/repo-state.sh` and `~/.claude/hooks/handoff-hint.sh` to
   `session/scripts/`, mode 755.
2. Write `tests/test_session_scripts.py` (exists, executable, `bash -n`, `--self-test` exit 0
   run from a temp cwd, working tree unchanged afterwards). Run it.
3. Change `handoff-hint.sh`: `python3` from PATH; hint names `/session:continue`; update its
   self-test expectations. Update script header comments that name `~/.claude` paths.
4. Check both scripts for private names: `rg -n -i 'efitz|eric|tmi|/Users' session`.

## Task 2: skills

1. Copy both SKILL.md files to `session/skills/{continue,handoff}/`.
2. Apply the spec's "Changes from the user-level versions" list.
3. `rg -n -i 'efitz|eric|tmi|/Users|_lib|\.claude/skills' session` returns only the legacy
   `WAITING ON ERIC` compatibility note.

## Task 3: plugin wiring and derived artifacts

1. `session/.claude-plugin/plugin.json` (version 1.0.0), `session/hooks/hooks.json`,
   `session/requirements.json` (follow the schema used by `env`; check what it can express).
2. `.claude-plugin/marketplace.json` entry, category `productivity`.
3. `scripts/verify-marketplace.sh` PLUGINS: `"session:productivity:continue,handoff"`.
4. `uv run scripts/gen_codex_manifests.py`.
5. README plugin count and `### session` section. `docs/ARCHITECTURE.md`: no change (the
   plugin hands nothing to another plugin), unless its catalog lists every plugin.
6. Add a hooks.json test to `tests/test_session_scripts.py`.

## Done gate

```
uv run ruff check .
uv run pytest -q
uv run scripts/gen_codex_manifests.py --check
bash scripts/verify-marketplace.sh
```
