# Codex Skill Parity (#23) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every subagent-dispatching skill states exactly what to do when subagents are unavailable, guarded by structure tests, version-bumped so Codex installs refresh, and dry-run-verified in real Codex.

**Architecture:** Six SKILL.md files gain one standardized `**No-subagent fallback:**` block at their first dispatch point (`security/race-cond` swaps its dangling `COMPATIBILITY.md` reference for the block). Two guard tests in `tests/test_plugin_structure.py` enforce resolving relative links and fallback presence. Patch bumps for the 5 edited plugins + manifest regeneration propagate to Codex. Spec: `docs/superpowers/specs/2026-07-30-codex-parity-design.md`.

**Tech Stack:** Markdown edits, Python stdlib tests (unittest style), `uv run pytest`, ruff, `gh`, Codex CLI (`zsh -lc 'codex …'`).

## Global Constraints

- The fallback marker is the exact string `**No-subagent fallback:**` in every affected skill — greppable and asserted by tests.
- Lint with `uv run ruff check .`; run tests with `uv run pytest -q`. Full suite has one pre-existing unrelated collection error (`tests/test_profile_testfiles.py::test_dirs`); "passing" means no NEW failures.
- Generated Codex manifests are never hand-edited — after version bumps run `uv run scripts/gen_codex_manifests.py`.
- Commit after each task; stage only files named in the task; never `git add -A`.
- End every commit message with exactly:
  `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
  `Claude-Session: https://claude.ai/code/session_018a81HJnmo8CacJVPNDL127`

---

### Task 1: Guard tests + fallback notes in six skills

**Files:**
- Modify: `tests/test_plugin_structure.py` (append a test class)
- Modify: `cats/skills/run/SKILL.md:9-10` area, `dev/skills/dedupe/SKILL.md:91-95` area, `dev/skills/sem-annotate/SKILL.md:77-79` area, `itest/skills/design/SKILL.md:63-66` area, `loc/skills/backfill/SKILL.md:96-98` area, `security/skills/race-cond/SKILL.md:26`

**Interfaces:**
- Produces: the marker string `**No-subagent fallback:**` present in all six skills; `TestCodexParity` test class. Task 2 does not depend on these; Task 3 verifies the notes in Codex.

- [ ] **Step 1: Write the failing guard tests**

Append to `tests/test_plugin_structure.py` (module already imports `json`, `re`, `sys`, `unittest`, `Path` and defines `REPO`, `skill_files()`):

```python
MD_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)#]+?)(?:#[^)]*)?\)")
SUBAGENT_REF = re.compile(r"\bsub-?agents?\b", re.IGNORECASE)
FALLBACK_MARKER = "**No-subagent fallback:**"


class TestCodexParity(unittest.TestCase):
    def test_relative_markdown_links_resolve(self):
        for skill in skill_files():
            text = skill.read_text(encoding="utf-8")
            for target in MD_LINK.findall(text):
                if "${" in target:
                    continue  # env-var paths are covered by test_plugin_root_references_resolve
                with self.subTest(skill=str(skill.relative_to(REPO)), link=target):
                    self.assertTrue((skill.parent / target).exists(),
                                    f"dangling relative link: {target}")

    def test_dispatching_skills_declare_no_subagent_fallback(self):
        for skill in skill_files():
            text = skill.read_text(encoding="utf-8")
            if not SUBAGENT_REF.search(text):
                continue
            with self.subTest(skill=str(skill.relative_to(REPO))):
                self.assertIn(FALLBACK_MARKER, text,
                              "skill dispatches subagents but has no fallback note")
```

- [ ] **Step 2: Run to verify both fail as expected**

Run: `uv run pytest tests/test_plugin_structure.py -q`
Expected: `test_relative_markdown_links_resolve` fails on `security/skills/race-cond/SKILL.md` link `../../COMPATIBILITY.md` (and ONLY that link); `test_dispatching_skills_declare_no_subagent_fallback` fails for exactly six skills: `cats/run`, `dev/dedupe`, `dev/sem-annotate`, `itest/design`, `loc/backfill`, `security/race-cond`. If any OTHER skill trips the fallback test, stop and report BLOCKED with the list (regex too broad — do not silently add notes to unplanned skills).

- [ ] **Step 3: Add the six fallback notes**

Each is one paragraph inserted at the stated location, exact text below.

`cats/skills/run/SKILL.md` — after the intro paragraph ending "reports its summary." (line 10):

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), do the worker's job inline: read
`${CLAUDE_PLUGIN_ROOT}/agents/cats-run.md` and execute the campaign yourself,
following it exactly. Same output contract (the compact summary).
```

`dev/skills/dedupe/SKILL.md` — immediately under the `### 4. Verify (parallel subagents, BATCHED)` heading (line 91), before the first bullet:

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), do the workers' jobs inline: read
`${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dead.md` and
`${CLAUDE_PLUGIN_ROOT}/agents/dedupe-verify-dup.md` and process each batch
yourself, sequentially, following them exactly. Same batch sizes, same output
contracts.
```

`dev/skills/sem-annotate/SKILL.md` — immediately under the `### 3. Generate descriptions (parallel subagents)` heading (line 77):

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), do the worker's job inline: read
`${CLAUDE_PLUGIN_ROOT}/agents/sem-describe.md` and process each batch
yourself, sequentially, following it exactly (the Sonnet model note below
applies only to dispatched subagents). Same batch sizes, same output
contract.
```

`itest/skills/design/SKILL.md` — immediately under the `## Phase 3 — Parallel discovery` heading (line 63):

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), run the five phase discoveries yourself, sequentially, following the
same instructions and returning the same contracts you would have handed
each subagent.
```

`loc/skills/backfill/SKILL.md` — immediately under the `### Step 4: Spawn translation sub-agents in parallel` heading (line 96):

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool), translate each locale yourself, sequentially, using the sub-agent
prompt template below as your own checklist. Same per-locale scope, same
output contract.
```

`security/skills/race-cond/SKILL.md` — replace the entire `**Codex note:** …` paragraph (line 26) with:

```markdown
**No-subagent fallback:** If your harness cannot dispatch subagents (no Task
tool — e.g. Codex), run the per-language and per-category analyses yourself,
sequentially, following the same instructions you would have handed each
subagent (in Codex, plain tool calls such as `functions.shell_command`
replace `Task(...)`).
```

- [ ] **Step 4: Audit sweep for other Claude-only assumptions**

Run: `rg -n 'Task\(|AskUserQuestion|~/.claude/plugins|claude\.ai' --glob '*/skills/*/SKILL.md'`
Expected hits: `security/race-cond` `Task(...)` mentions (now covered by its fallback note — leave). For any OTHER hit: fix trivially if it's wording/a path; otherwise record it verbatim in the report for the #23 closing comment. Do not restructure any skill.

- [ ] **Step 5: Run tests to verify green**

Run: `uv run pytest tests/test_plugin_structure.py -q` then `uv run pytest -q`
Expected: structure tests all pass; full suite passes (baseline collection error only).

- [ ] **Step 6: Lint and commit**

Run: `uv run ruff check .`
Then:

```bash
git add tests/test_plugin_structure.py cats/skills/run/SKILL.md dev/skills/dedupe/SKILL.md dev/skills/sem-annotate/SKILL.md itest/skills/design/SKILL.md loc/skills/backfill/SKILL.md security/skills/race-cond/SKILL.md
git commit -m "feat(skills): no-subagent fallback notes + link/fallback guard tests (#23)"
```

(If Step 4 changed additional files, stage those too — list them in the commit body.)

---

### Task 2: Version bumps + manifest regeneration

**Files:**
- Modify: `cats/.claude-plugin/plugin.json` (0.1.0 → 0.1.1), `dev/.claude-plugin/plugin.json` (2.4.0 → 2.4.1), `itest/.claude-plugin/plugin.json` (1.0.0 → 1.0.1), `loc/.claude-plugin/plugin.json` (1.0.0 → 1.0.1), `security/.claude-plugin/plugin.json` (1.0.0 → 1.0.1)
- Regenerate: `.agents/plugins/marketplace.json` (unchanged content expected), `{cats,dev,itest,loc,security}/.codex-plugin/plugin.json`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: bumped versions that Task 3's Codex reinstall relies on.

- [ ] **Step 1: Verify drift detection fires (RED)**

Edit the five `version` fields in the `.claude-plugin/plugin.json` files (only the version string changes). Then:
Run: `uv run pytest tests/test_codex_manifests.py -q`
Expected: `test_committed_files_match_fresh_regeneration` FAILS for the five stale `.codex-plugin/plugin.json` files.

- [ ] **Step 2: Regenerate (GREEN)**

Run: `uv run scripts/gen_codex_manifests.py` then `uv run pytest -q`
Expected: 13 `wrote …` lines; full suite passes (baseline error only). `git diff --stat` shows exactly 10 modified files (5 Claude manifests + 5 Codex manifests); `.agents/plugins/marketplace.json` may appear only if its bytes changed — it should NOT (versions aren't in it); if it changed, stop and inspect.

- [ ] **Step 3: Commit**

```bash
git add cats/.claude-plugin/plugin.json dev/.claude-plugin/plugin.json itest/.claude-plugin/plugin.json loc/.claude-plugin/plugin.json security/.claude-plugin/plugin.json cats/.codex-plugin/plugin.json dev/.codex-plugin/plugin.json itest/.codex-plugin/plugin.json loc/.codex-plugin/plugin.json security/.codex-plugin/plugin.json
git commit -m "chore(plugins): patch-bump edited plugins and regenerate Codex manifests (#23)"
```

---

### Task 3: Codex dry-run verification + close #23

Run inline in the main session (Codex CLI + gh auth). No repo files change unless verification exposes a defect (fix goes in the skill text, re-run Task 1's tests, amend via a new commit).

- [ ] **Step 1: Point Codex at the working tree**

The registered `efitz-skills` marketplace snapshots GitHub, which doesn't have this branch yet. Swap to the local checkout:

```bash
zsh -lc 'codex plugin marketplace remove efitz-skills'
zsh -lc 'codex plugin marketplace add <worktree-or-checkout-path> --json'
zsh -lc 'codex plugin add dev@efitz-skills --json'
zsh -lc 'codex plugin add cats@efitz-skills --json'
```

Expected: installs land at versions 2.4.1 / 0.1.1.

- [ ] **Step 2: Dry-run comprehension checks**

For each of `dev:dedupe` and `cats:run`:

```bash
zsh -lc 'codex exec --sandbox read-only "You have no subagent capability: there is no Task tool and you cannot dispatch agents. Read the <skill> skill and state, step by step, how you would execute it in this harness. Do not actually execute it. Then stop."'
```

Pass criteria: the stated plan (a) invokes the fallback — processes batches/the campaign inline and sequentially, (b) names the bundled `agents/*.md` worker file(s) as instructions to follow, (c) invents no delegation. Save both transcripts to the SDD workspace. If either fails, treat as a review finding: fix the skill wording, re-run `uv run pytest tests/test_plugin_structure.py -q`, commit, reinstall, re-check.

- [ ] **Step 3: Restore the GitHub-sourced marketplace**

After the branch merges and pushes (finishing flow):

```bash
zsh -lc 'codex plugin marketplace remove efitz-skills'
zsh -lc 'codex plugin marketplace add ericfitz/skills --json'
```

Then reinstall whichever plugins the user had (at minimum re-add the ones present before the swap — capture `codex plugin list` output in Step 1 before removing).

- [ ] **Step 4: Close #23 with evidence**

```bash
gh issue close 23 --repo ericfitz/skills --comment "<body>"
```

Body: what changed (fallback notes in 6 skills, guard tests, version bumps), the dry-run transcript excerpts for dev:dedupe and cats:run, allowed-tools analysis conclusion (permissive scoping, no correctness dependency, unchanged), audit-sweep leftovers (or "none"), and the explicit out-of-scope note (full functional runs deferred).

---

## Self-Review (completed)

- **Spec coverage:** §1 notes → Task 1 Step 3; §2 bumps/regeneration → Task 2; §3 guard tests → Task 1 Steps 1–2; §4 dry-run verification → Task 3 Steps 1–2; §5 audit sweep → Task 1 Step 4 + Task 3 Step 4 reporting. Out-of-scope items untouched.
- **Placeholder scan:** all edit content and commands are verbatim; the only variable (`<worktree-or-checkout-path>`, `<skill>`, `<body>`) are runtime values with their content specified in place.
- **Type consistency:** marker string, regexes, and version numbers are identical across tasks.
