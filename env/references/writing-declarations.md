# Writing a `requirements.json`

A plugin declares what it needs to run in a sidecar `<plugin>/requirements.json`, validated
against `requirements.schema.json` in this directory. `env_check.py` discovers these files,
probes for what they name, and reports what's missing, why it matters, and how to fix it.
This guide is about authoring the declaration; the design rationale lives in
`docs/superpowers/specs/2026-07-26-env-check-design.md`.

## Read the plugin's skills first

Don't guess at a plugin's requirements from its name or its scripts' imports. Read every
`SKILL.md` under `<plugin>/skills/*/` and note every external command, config file, or
authenticated session they actually invoke or reference. The declaration should be
traceable line-by-line back to something a skill does.

## Requirement vs. incidental mention

A `SKILL.md` mentioning a tool is not the same as the plugin depending on it. Ask: does a
skill in *this* plugin invoke this, or is it just discussed, exemplified, or listed as
something a *target* repo might have? Only the former belongs in `requirements.json`.

## Target-repo toolchains are out of scope

`go`, `npm`, `pytest`, and similar appear across plugin skills only because a repo the
plugin operates *on* might use them. A machine that legitimately has neither is not missing
anything — checking for them would report a failure that isn't one. Requirements describe
what the plugin itself needs to run, never what a target repo might need. See "Why not
target-project toolchains" in the design spec.

## `why` must name the consuming skill(s)

"Missing `jq`" is a checklist entry. "missing `jq` — needed by `deps` to parse `npm audit`
output" is actionable: it tells the reader which skill breaks and lets them judge whether
they'll ever hit it. Every `tools[]`, `config[]`, and `auth[]` entry's `why` must name at
least one skill by its directory name.

## `required` separates hard from optional

Set `required: true` only when the plugin's skills cannot function without the entry — the
kind of gap that should make the overall check non-green. Set `required: false` when
absence degrades a capability rather than breaking it (an optional cache file that a skill
falls back to reading fresh, for example). When in doubt, check what the skill actually
does when the entry is missing: does it stop, or does it proceed with reduced function?

## Probes must be cheap, read-only, argv arrays

`probe` is always a JSON array of strings — `["gh", "--version"]`, never the shell string
`"gh --version"`. It is executed with `shell=False`; there is no shell interpolation and no
other way to run an arbitrary command through a declaration. Every committed probe is
checked for this by `tests/test_env_declarations.py`.

Probes must be:
- **Cheap** — a version flag or a lightweight status call, not something that hits a
  network or does real work.
- **Read-only** — never a probe that could mutate state, install anything, or write a file.
- **Deterministic enough to parse** — if you need a version number, pair the probe with
  `version_pattern` (a regex with one capture group) and `min_version`.

Auth probes (`gh auth status` and the like) record exit status and a one-line summary only.
Never write a probe that could print or capture a token, and never declare anything that
reads from `~/.keys/`.

## `install`, when you have it

`install` is optional on `tools[]` entries. Key it by platform (`macos`, `linux`,
`windows`) with the exact command `--fix` would run verbatim — never a template `--fix`
would need to compose. Always include `docs` when you have a URL; it's what gets printed
when the current platform has no key.

## Shape reference

See `requirements.schema.json` for the full contract, and `github/requirements.json` for an
example exercising all three sections (`tools`, `config`, `auth`), or `dev/requirements.json`
for the minimal single-hard-tool case.
