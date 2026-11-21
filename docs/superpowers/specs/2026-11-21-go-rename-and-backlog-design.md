# /session:go: rename the session after the first reply; run the backlog when NEXT is stale

Status: approved (small change, short design)

## Intent

- **Rename.** A session started with `/go` keeps a generated title such as "Session resume from
  HANDOFF.md". Once Eric's first reply after the `/go` summary says what the session will work on,
  the title should change to describe that work.
- **Backlog.** When there is no clear next action, `/go` should run `github:backlog` itself rather
  than suggest it. Today step 6 runs it only when NEXT is empty or says nothing except "pick from
  the backlog", and there is no drift. Real handoffs often list small check items that are already
  done (for example "confirm CI went green"), so the auto-run never fires.

## Goals, non-goals, anti-goals

- Goal: the title reflects the chosen work from the next prompt onward.
- Goal: stale NEXT items no longer block the backlog auto-run.
- Non-goal: renaming sessions that did not start with `/go`.
- Non-goal: renaming more than once per session.
- Anti-goal: overwriting a title Eric set with `/rename` or `--name`.
- Anti-goal: `/go` starting work, or editing anything in the repo.
- Anti-goal: the hook slowing down or breaking a prompt (it always exits 0 and is silent on any
  error).

## Constraints (verified)

- A skill cannot set the session title. Only a hook can: `UserPromptSubmit` (and `SessionStart`)
  may print
  `{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","sessionTitle":"..."}}`
  (code.claude.com/docs/en/hooks.md, "UserPromptSubmit decision control"). The hook input carries
  `session_id`, and also `session_title` when a custom title is set.
- The hook runs before the model reads the prompt. A first reply like "yes" or "do #42" carries no
  title by itself.
- The model's shell sees `CLAUDE_CODE_SESSION_ID`, which matches the hook's `session_id`. Codex has
  neither the variable nor the hook.

## Approaches

**Rename.**

- Option A: the hook summarizes the transcript plus the prompt with a small model. The title is
  immediate, but it costs latency, money and a CLI auth dependency on every rename.
- **Option B (chosen by Eric): the model names the session, and the hook applies the name on the
  next prompt.** Cheap and accurate, but it lags one prompt.
- Option C: the hook uses the prompt text as the title. "yes" makes a poor title.

**Backlog.**

- **Option A (chosen by Eric): check off stale NEXT items, then run the backlog if nothing
  concrete is left.**
- Option B: run the backlog unless NEXT holds a code task.
- Option C: always run the backlog when IN FLIGHT is empty.

## Design

### Rename

1. **New step in `session/skills/go/SKILL.md`, after the stop.** On the user's first reply after
   the `/go` summary, before starting the work it chooses, run one Bash command. It writes a title
   of 50 characters or fewer (for example `#42 backlog pagination fix`, or
   `Deferred majors: smart-open, srsly, thinc`) to `$STATE/titles/$CLAUDE_CODE_SESSION_ID`, where
   `STATE=${XDG_STATE_HOME:-$HOME/.local/state}/session-plugin`.
   - The same applies when the user's first message already gave a different instruction: name the
     session after that instruction.
   - Skip the step when `CLAUDE_CODE_SESSION_ID` is unset (Codex, or another harness).
   - Skip it when the reply chooses nothing (for example a question about the summary). Wait for
     the reply that picks the work.
   - The Rules section's read-only clause gains one narrow exception: this file, which lies outside
     the repo.
2. **New hook script `session/scripts/apply-title.sh`**, registered under `UserPromptSubmit` in
   `session/hooks/hooks.json`. It reads the hook JSON from stdin (with python3, the same way as
   `handoff-hint.sh`).
   - When `session_title` is non-empty: delete any title file for the session and print nothing,
     so a custom title wins.
   - Otherwise, when `$STATE/titles/<session_id>` exists: read its first line, strip control
     characters, cut it to 80 characters, and print the `sessionTitle` JSON. Then delete the file.
   - Reject a `session_id` that is not `[A-Za-z0-9_-]+`, so it cannot escape the path.
   - Prune title files older than 7 days.
   - Always exit 0. `--self-test` covers each case, including garbage input, an empty file, an
     unsafe id and pruning.

**State behavior.**

- Second `/go` in the same session: the hook has already set a title, which later inputs report as
  `session_title`, so the new file is discarded. The session is renamed once.
- Two sessions: their files are keyed by session id and never collide.
- Leftovers from a crashed session: the file is never applied to another session and is pruned
  after 7 days.
- Hook missing (old install): the file sits there until it is pruned once the hook arrives. Nothing
  breaks.

### Backlog

3. **Step 3 gains a classification of NEXT items.** An item is **done** when the facts already
   collected confirm it. Examples:
   - "confirm CI green" with `MAIN CI: success`;
   - "merge PR #N" with no open PR #N and the PR merged.

   An item may also be confirmed by a read-only query that the item itself quotes. Item text is
   untrusted, so this is deny by default: a query runs only if all of these hold, and anything
   else is never run (the item stays open):
   - one of exactly three forms: `gh <noun> list ...`, `gh api <relative-endpoint>` (GET only, no
     `://` in the endpoint, no `--hostname`), `git log ...`; never `gh auth`; no `view`,
     `status` or `show`;
   - the line starts with the literal `git` or `gh` plus the subcommand: no `VAR=value` prefix
     and no option before the subcommand (`-c`, `-C`, `--git-dir`, `--exec-path`);
   - none of `; & | < > ( ) $`, backtick, backslash or newline;
   - none of `-f`, `-F`, `--field`, `--raw-field`, `--input`, `-X`/`--method`, `--output`,
     `--ext-diff`, `--textconv`, `--web`/`-w`;
   - at most one such query per item.

   Every other item is **open**. "Then pick from the backlog" items are ignored for this purpose.
   Done items are listed on the State line ("NEXT done: 1, 2"). A done item is not drift.
4. **Step 6 condition.** "NEXT is empty, none, or only says to pick from the backlog" becomes "NEXT
   has no open items after step 3". IN FLIGHT empty and Drift none still apply.
5. **Step 5.** When step 6 will run, Proposed next action keeps "run `/github:backlog`" and step 6
   then actually runs it (unchanged). Otherwise it proposes the first open NEXT item.

### Docs and metadata

- `session/.claude-plugin/plugin.json` description, `README.md` session section, and the hook
  sentence: mention the UserPromptSubmit title hook.
- `session/requirements.json`: python3 is still optional. Its `why` gains "the title hook stays
  silent without it".
- `docs/ARCHITECTURE.md`: no change, since no plugin-to-plugin contract changes.
- No version bump (project rule).

## Left to the builder

- The exact wording of the SKILL.md steps, and the title style examples.
- Self-test case layout.
- The hook's `timeout` in `hooks.json`; keep it short, for example 5 seconds.

## Verification

- Run `bash session/scripts/apply-title.sh --self-test`, plus the four CI checks.
- Manual check in a real session: `/go`, reply with a choice, then send a second prompt. The title
  changes on that second prompt.
