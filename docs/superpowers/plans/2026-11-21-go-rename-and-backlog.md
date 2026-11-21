# /session:go Rename and Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/go` names the session after the user's first reply, applied by a UserPromptSubmit hook. It also runs `github:backlog` itself when every NEXT item is already done.

**Architecture:** The skill (model) writes a one-line title file keyed by `CLAUDE_CODE_SESSION_ID` under a state directory outside the repo. A new bash hook `apply-title.sh` emits it as `hookSpecificOutput.sessionTitle` on the next prompt and deletes it. The backlog change is wording only: SKILL.md steps 3, 5 and 6 classify NEXT items as done or open.

**Tech Stack:** bash and python3 (JSON parsing, same pattern as `handoff-hint.sh`), Python unittest under `uv run pytest`.

**Spec:** `docs/superpowers/specs/2026-11-21-go-rename-and-backlog-design.md`

## Global Constraints

- **State directory:** `STATE=${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin`. Title file: `$STATE/titles/<session_id>`.
- **Hook output, exactly this shape:** `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","sessionTitle":"<title>"}}`.
- **Title limits:** the skill writes 50 characters or fewer. The hook truncates to 80 characters and strips control characters.
- **session_id format:** must match `^[A-Za-z0-9_-]+$`, otherwise the hook does nothing.
- **Pruning:** the hook deletes title files older than 7 days.
- **Exit code:** the hook always exits 0. On any error it prints nothing.
- **No private names:** files under `session/` must not match `efitz|eric|tmi|/Users|_lib|\.claude/skills` (tested by `test_no_private_names_in_plugin`).
- **No version bump** in `plugin.json` or anywhere else.
- **Exit criteria:** `uv run ruff check .`, `uv run pytest -q`, `uv run scripts/gen_codex_manifests.py --check`, `bash scripts/verify-marketplace.sh`.

## Review Focus

1. **The user already ran `/rename`** (input carries a non-empty `session_title`). Expect no output, and the pending file deleted. *(Task 1 self-test)*
2. **The `session_id` contains `../` or `/`.** Expect no read or delete outside `$STATE/titles`, and no output. *(Task 1 self-test)*
3. **The title file holds several lines, a tab or ESC, or more than 80 characters.** Expect one clean line of 80 characters or fewer. *(Task 1 self-test)*
4. **The title has quotes or backslashes, e.g. `fix "quoted" \ path`.** Expect valid JSON on output. Build it with python `json.dumps`, never printf. *(Task 1 self-test)*
5. **`HOME` and `XDG_STATE_HOME` point at a missing directory, or `python3` is absent.** Expect exit 0 and silence. *(Task 1 self-test, missing-dir case)*

---

### Task 1: apply-title.sh UserPromptSubmit hook

**Files:**
- Create: `session/scripts/apply-title.sh` (mode 755)
- Modify: `session/hooks/hooks.json` (add a `UserPromptSubmit` entry)
- Modify: `tests/test_session_scripts.py` (add the script to `SCRIPTS`; extend `TestSessionHooks`)
- Modify: `session/requirements.json` (python3 `why`: add "and the title hook stays silent")

**Interfaces:**
- Produces: hook stdin is the Claude Code UserPromptSubmit JSON. The script reads `session_id` and `session_title`.
- Produces: the state file path in Global Constraints. Task 2's SKILL.md text writes to that path.

- [ ] **Step 1: Write failing tests in `tests/test_session_scripts.py`**
  - Add `PLUGIN / "scripts" / "apply-title.sh"` to `SCRIPTS`. The existing exist, executable, syntax and self-test tests then cover it.
  - Replace `test_hooks_json_points_at_existing_script` with a loop over both events:
    - `SessionStart` keeps matcher `startup|resume` and `handoff-hint.sh`.
    - `UserPromptSubmit` has exactly one entry, with no matcher (or an empty one), one command that resolves via `${CLAUDE_PLUGIN_ROOT}` to `scripts/apply-title.sh`, and a `timeout` of 10 or less.
    - For each event, assert the referenced file exists.

- [ ] **Step 2: Run the tests to verify they fail**
  - Run: `uv run pytest -q tests/test_session_scripts.py`
  - Expected: FAIL. `apply-title.sh` does not exist, and there is no `UserPromptSubmit` key.

- [ ] **Step 3: Implement `session/scripts/apply-title.sh`**
  - Use the same structure as `handoff-hint.sh`: a header comment, a `--self-test` mode, then `main "$(cat 2>/dev/null)"; exit 0`.
  - Do all the logic in a single `python3 -c` program, given the input JSON on stdin and `STATE` as argv. It does the following:
    1. Parse the JSON. On failure, exit 0.
    2. Validate `session_id`.
    3. Prune `$STATE/titles/*` files with mtime older than 7 days.
    4. If `session_title` is a non-empty string, delete the session's file and exit.
    5. Otherwise read the file's first line. Remove characters with `ord < 32` or `ord == 127`, strip it, and cut it to 80 characters.
    6. Delete the file, then print the JSON with `json.dumps` if the title is non-empty.
  - Swallow every exception.
  - Do not use `set -e`, because the hook must exit 0.

- [ ] **Step 4: Write `selftest()` in the script**
  - Run in a `mktemp -d` dir with `XDG_STATE_HOME` pointed into it, and remove it at the end. Print `ok` and exit 0 on success. Print `FAIL: <case>` lines and exit 1 on failure.
  - Cases, each piping JSON into `bash "$self"`:

    | Case | Setup and input | Expected |
    |------|-----------------|----------|
    | (a) happy path | file `abc-123` containing `#42 fix pagination` | stdout parses to the exact Global Constraints shape with that title; file gone |
    | (b) no file | no title file | empty stdout |
    | (c) custom title | `session_title:"Mine"` with a file present | empty stdout; file deleted |
    | (d) unsafe id | `session_id:"../x"`, with a file planted at `$STATE/x` | empty stdout; planted file still exists |
    | (e) control chars | first line `a\tb\x1bc` plus a second line | title `abc` |
    | (f) long title | 100 characters | title is 80 characters |
    | (g) quotes | `fix "quoted" \ path` | stdout is valid JSON round-tripping that exact string |
    | (h) empty file | empty title file | empty stdout; file deleted |
    | (i) pruning | other session's file with mtime 8 days ago (`touch -t`, BSD/GNU-portable via a python `os.utime`) and a 1-day-old file | 8-day file gone, 1-day file kept |
    | (j) bad input | `not json` and empty input | rc 0, empty stdout |
    | (k) missing state dir | `XDG_STATE_HOME=/nonexistent/x` | rc 0, empty stdout |

  - Every case also asserts rc 0.

- [ ] **Step 5: Register the hook in `session/hooks/hooks.json`**
  - Add `"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "bash \"${CLAUDE_PLUGIN_ROOT}/scripts/apply-title.sh\"", "shell": "bash", "timeout": 5}]}]`.
  - Update the python3 `why` in `session/requirements.json`.

- [ ] **Step 6: Run the tests to verify they pass**
  - Run: `chmod 755 session/scripts/apply-title.sh && bash session/scripts/apply-title.sh --self-test && uv run pytest -q tests/test_session_scripts.py`
  - Expected: `ok`, and all tests pass.

- [ ] **Step 7: Commit**
  - Run: `git add session/scripts/apply-title.sh session/hooks/hooks.json session/requirements.json tests/test_session_scripts.py && git commit -m "feat(session): UserPromptSubmit hook applies a pending session title"`

---

### Task 2: go SKILL.md (name the session, stale-NEXT backlog), docs

**Files:**
- Modify: `session/skills/go/SKILL.md` (steps 3, 5, 6, 7 and Rules)
- Modify: `tests/test_session_scripts.py` (`TestSessionSkills`)
- Modify: `session/.claude-plugin/plugin.json` (`description` only, NOT `version`)
- Modify: `README.md` (`### session` section, lines 171–176)
- Run: `uv run scripts/gen_codex_manifests.py` if the description feeds Codex manifests, and commit its output.

**Interfaces:**
- Consumes: the Task 1 state path and the 50-character skill limit (Global Constraints).

- [ ] **Step 1: Write failing tests in `TestSessionSkills`**
  - Add `test_go_names_session`. The go SKILL.md contains:
    - `CLAUDE_CODE_SESSION_ID`
    - `${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin/titles/`
    - `50 characters`
  - It also asserts that the Rules section mentions the title file as the only write exception (regex on the `## Rules` section matching `title file`).
  - Add `test_go_classifies_next`. SKILL.md contains `NEXT done:` and `open`, and the step 6 condition text contains `no open items`.
  - Keep `test_go_hands_off_to_backlog` passing unchanged.

- [ ] **Step 2: Run the tests to verify they fail**
  - Run: `uv run pytest -q tests/test_session_scripts.py -k "names_session or classifies_next"`
  - Expected: FAIL.

- [ ] **Step 3: Edit `session/skills/go/SKILL.md` per spec §Design**
  - **Step 3 (Compare):** add NEXT classification.
    - An item is **done** when facts already collected confirm it, or a read-only `git`/`gh` query quoted in the item confirms it.
    - Allowed queries: `gh ... list|view|status`, `gh api` GET with no `-X`/`--method` other than GET and no `-f`/`-F`/`--field`/`--input`, and `git log|show|status`.
    - Every other item is **open**. "Pick from the backlog" items don't count.
    - A done item is not drift.
  - **Step 5 State line:** append `NEXT done: <item numbers>` when any items are done.
  - **Step 5 Proposed next action:** the first open NEXT item, unless step 6 applies.
  - **Step 6 condition:** replace the second bullet with "NEXT has no open items after step 3".
  - **New step 8, "Name the session", after step 7:**
    - On the user's first reply that chooses work (or a first message that already gave an instruction), before starting the work, run one Bash command:
      ```bash
      d="${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin/titles"; mkdir -p "$d" && printf '%s\n' '<title>' > "$d/$CLAUDE_CODE_SESSION_ID"
      ```
    - The title is 50 characters or fewer and names the work, e.g. `#42 backlog pagination fix`.
    - Skip the step when `CLAUDE_CODE_SESSION_ID` is unset, e.g. on Codex.
    - Skip it, and wait, when the reply chooses nothing.
    - Note that the hook applies the title on the following prompt and never replaces a title the user set.
  - **Update step 7** so it doesn't contradict step 8 (stop, then step 8 runs on the reply).
  - **Rules, read-only bullet:** add "except the step 8 title file, which lives outside the repo".
  - **Frontmatter `description`:** mention naming the session; keep the existing trigger phrases.

- [ ] **Step 4: Update `plugin.json` description and README**
  - In both, mention:
    - "names the session after the first reply via a UserPromptSubmit hook";
    - "runs github:backlog when every NEXT item is already done".
  - README hook sentence: "Two hooks: SessionStart prints a reminder…; UserPromptSubmit applies the title `go` chose."

- [ ] **Step 5: Run the full exit criteria**
  - Run: `uv run ruff check . && uv run pytest -q && uv run scripts/gen_codex_manifests.py --check && bash scripts/verify-marketplace.sh`
  - Expected: all pass. If the manifest check fails, run `uv run scripts/gen_codex_manifests.py` and re-run.

- [ ] **Step 6: Commit**
  - Run: `git add session/skills/go/SKILL.md session/.claude-plugin/plugin.json README.md tests/test_session_scripts.py <regenerated manifests if any> && git commit -m "feat(session): go names the session and runs backlog when NEXT is stale"`
